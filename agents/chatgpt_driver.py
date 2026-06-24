"""ChatGPTSession -- the intelligent, DOM-aware hands that drive chatgpt.com for 9to5.

This is the real Phase-2 transport for GPT-5.5 as the second brain. It deliberately is NOT a
screenshot->click-xy loop: it reuses a logged-in browser profile, drives the real DOM through
centralized fallback selectors (agents/chatgpt_selectors.py), waits for the reply to actually
finish streaming before reading it, keeps ONE conversation per run inside a dedicated "9to5"
ChatGPT project, and self-heals selectors via a local VLM when OpenAI ships a UI change.

Design rules:
  * Playwright is imported lazily and isolated behind ``_launch`` / the page object, so the
    pure logic (state classification, completion predicate, reply extraction) is unit-testable
    with a fake page and the module imports cleanly with no browser installed.
  * Every failure surfaces as a typed ``ChatGPTError`` subclass; callers (the Adversary) decide
    whether to retry (transient) or degrade to the Ollama brain. The session NEVER blocks a run.
"""
from __future__ import annotations

import time
from typing import Any, Optional

import config
from agents import chatgpt_selectors as sel

LOG = config.getLogger("chatgpt_driver")


# --- typed failures -------------------------------------------------------------------------
class ChatGPTError(RuntimeError):
    """Base for any chatgpt.com driving failure."""


class ChatGPTLoginRequired(ChatGPTError):
    """The session is not logged in (login wall / redirect)."""


class ChatGPTBlocked(ChatGPTError):
    """A Cloudflare / bot-detection challenge is in the way."""


class ChatGPTRateLimited(ChatGPTError):
    """ChatGPT reported a usage / rate limit."""


class ChatGPTSelectorMiss(ChatGPTError):
    """A required element could not be located even after self-heal."""


# Page-state vocabulary returned by ``classify_state``.
READY, LOGIN_WALL, CLOUDFLARE, RATE_LIMITED, MODAL, UNKNOWN = (
    "ready", "login_wall", "cloudflare", "rate_limited", "modal", "unknown")

_HEAL_ROLES = {"composer", "send_button", "stop_button", "assistant_msg"}


def classify_state(page: Any) -> str:
    """Cheap DOM-only triage of the current page. Order matters: blockers before readiness."""
    if sel.visible_role(page, "cloudflare"):
        return CLOUDFLARE
    if sel.visible_role(page, "rate_limit"):
        return RATE_LIMITED
    if sel.visible_role(page, "login_wall"):
        return LOGIN_WALL
    if sel.visible_role(page, "composer"):
        return READY
    return UNKNOWN


def _locator_text(loc: Any) -> str:
    """inner_text of the LAST matching element (the newest assistant turn). Using ``.last``
    avoids Playwright strict-mode errors once a thread has more than one assistant message."""
    try:
        return (loc.last.inner_text() or "").strip()
    except Exception:  # noqa: BLE001 -- fall back to a plain inner_text for simple fakes
        return (loc.inner_text() or "").strip()


def extract_latest_reply(page: Any) -> str:
    """Text of the newest assistant message. Call ONLY after await_reply_complete."""
    loc = sel.first_visible(page, "assistant_msg")
    if loc is None:
        return ""
    return _locator_text(loc)


class ChatGPTSession:
    """A long-lived, logged-in chatgpt.com session. Open once per run; reuse for every review."""

    def __init__(self) -> None:
        self._pw = None
        self._ctx = None
        self._page = None
        self._conversation_url: Optional[str] = None
        self._turns = 0
        self._heal_used = 0
        self.opened = False

    # -- lifecycle ---------------------------------------------------------------------------
    def _launch(self):
        """Start Playwright + a persistent (logged-in) context. Lazy import so the module loads
        without playwright installed; raises ChatGPTError on absence so the caller degrades."""
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except Exception as e:  # noqa: BLE001
            raise ChatGPTError(
                "browser layer unavailable: `pip install playwright && playwright install chromium`"
            ) from e
        self._pw = sync_playwright().start()
        self._ctx = self._pw.chromium.launch_persistent_context(
            user_data_dir=str(config.CHATGPT_USER_DATA_DIR),
            headless=config.CHATGPT_HEADLESS,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._ctx.set_default_timeout(config.CHATGPT_NAV_TIMEOUT_MS)
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()

    def open(self) -> None:
        if self.opened:
            return
        self._launch()
        self.opened = True

    def close(self) -> None:
        for obj, meth in ((self._ctx, "close"), (self._pw, "stop")):
            try:
                if obj is not None:
                    getattr(obj, meth)()
            except Exception:  # noqa: BLE001
                pass
        self._ctx = self._pw = self._page = None
        self.opened = False

    @property
    def page(self):
        if self._page is None:
            raise ChatGPTError("session not open")
        return self._page

    # -- state / readiness -------------------------------------------------------------------
    def _guard_state(self) -> None:
        """Raise the right typed error for a non-ready page so the caller can route the fallback."""
        state = classify_state(self.page)
        if state == LOGIN_WALL:
            raise ChatGPTLoginRequired("chatgpt.com shows a login wall; profile not authenticated")
        if state == CLOUDFLARE:
            raise ChatGPTBlocked("Cloudflare challenge present")
        if state == RATE_LIMITED:
            raise ChatGPTRateLimited("ChatGPT reported a usage/rate limit")

    def _resolve(self, role: str):
        """Locate ``role``; on a miss try the VLM self-healer once, else raise SelectorMiss."""
        loc = sel.first_visible(self.page, role)
        if loc is not None:
            return loc
        healed = self._try_self_heal(role)
        if healed is not None:
            return healed
        raise ChatGPTSelectorMiss(f"no selector resolved for role={role!r}")

    def _try_self_heal(self, role: str):
        """Ask the local VLM to propose a selector for ``role``; validate it on the live DOM
        before using + caching it. Off the hot path: capped per run, only on a genuine miss."""
        if not (config.VLM_SELF_HEAL_ENABLED and role in _HEAL_ROLES):
            return None
        if self._heal_used >= config.VLM_SELF_HEAL_MAX_PER_RUN:
            return None
        self._heal_used += 1
        try:
            from agents import vlm_healer
            shot = self.page.screenshot()
            dom = self.page.content()
            proposal = vlm_healer.heal(shot, dom, want=role)
            css = (proposal or {}).get("selectors", {}).get(role)
            if not css:
                return None
            loc = self.page.locator(css)
            if loc.count() > 0:                 # validate against the live DOM before trusting it
                sel.save_selector(role, css)
                LOG.info("VLM self-heal resolved role=%s via %s", role, css)
                return loc
        except Exception as e:  # noqa: BLE001 -- self-heal must never crash a review
            LOG.warning("VLM self-heal failed for role=%s: %s", role, e)
        return None

    # -- streaming completion ----------------------------------------------------------------
    def await_reply_complete(self, *, settle_ms: Optional[int] = None,
                             timeout_ms: Optional[int] = None) -> None:
        """Block until GPT finishes generating: the Stop button is gone AND the newest assistant
        message text has been stable for ``settle_ms``. Bails at ``timeout_ms`` (best-effort --
        a timeout still lets the caller read whatever is present)."""
        settle_ms = settle_ms or config.CHATGPT_REPLY_SETTLE_MS
        timeout_ms = timeout_ms or config.CHATGPT_REPLY_TIMEOUT_MS
        deadline = settle_ms  # tracked via wall clock below
        last_text = ""
        stable_since: Optional[float] = None
        start = time.monotonic()
        while (time.monotonic() - start) * 1000 < timeout_ms:
            streaming = sel.visible_role(self.page, "stop_button")
            text = extract_latest_reply(self.page)
            now = time.monotonic()
            if not streaming and text and text == last_text:
                if stable_since is None:
                    stable_since = now
                elif (now - stable_since) * 1000 >= settle_ms:
                    return                      # gone + stable long enough => done
            else:
                stable_since = None
            last_text = text
            self.page.wait_for_timeout(250)
        LOG.warning("await_reply_complete timed out after %dms", timeout_ms)

    # -- project / conversation --------------------------------------------------------------
    def ensure_project(self) -> str:
        """Idempotently resolve the '9to5' ChatGPT project URL: cached -> on-page -> create.
        Returns the project URL ('' if projects can't be reached -- caller still works at root)."""
        cached = sel.cached_project_url()
        if cached:
            self._conversation_url = None
            return cached
        # Best-effort discovery/creation; never fatal -- a missing project just means chats live
        # at the account root, which still works for reviews.
        try:
            self.page.goto(config.CHATGPT_PROJECT_URL or "https://chatgpt.com/")
            link = sel.first_visible(self.page, "project_link")
            if link is not None:
                url = link.last.get_attribute("href") or ""
                if url:
                    full = url if url.startswith("http") else f"https://chatgpt.com{url}"
                    sel.save_project_url(full)
                    return full
        except Exception as e:  # noqa: BLE001
            LOG.warning("ensure_project discovery failed (non-fatal): %s", e)
        return ""

    def start_run_conversation(self, goal: str, task_id: str) -> None:
        """Open a fresh conversation (inside the 9to5 project when known) for this run. GPT then
        accumulates run context across every subtask review -> cheaper, more grounded critiques."""
        project_url = self.ensure_project()
        try:
            self.page.goto(project_url or "https://chatgpt.com/")
            self._guard_state()
            self._conversation_url = self.page.url
            self._turns = 0
            LOG.info("started run conversation for task %s (project=%s)",
                     task_id, project_url or "<root>")
        except ChatGPTError:
            raise
        except Exception as e:  # noqa: BLE001
            raise ChatGPTError(f"could not start run conversation: {e}") from e

    # -- the one verb everything routes through ----------------------------------------------
    def ask(self, message: str, *, expect_json: bool = False) -> Optional[str]:
        """Send one message in the run conversation and return GPT's completed reply text.

        Raises a typed ChatGPTError on login/Cloudflare/rate-limit/selector failure so the
        Adversary can fall back to the Ollama brain. When ``expect_json`` and the reply isn't
        parseable as a JSON object, sends up to CHATGPT_JSON_REPAIR_RETRIES in-conversation
        'reply JSON only' nudges before returning what it has."""
        self.open()
        if self._conversation_url is None:
            # No explicit run conversation was started; operate on whatever page is loaded.
            try:
                self.page.goto("https://chatgpt.com/")
            except Exception as e:  # noqa: BLE001
                raise ChatGPTError(f"navigation failed: {e}") from e
        self._guard_state()

        if self._turns >= config.CHATGPT_MAX_TURNS:
            LOG.info("conversation hit %d turns; rolling over to a fresh chat", self._turns)
            self.start_run_conversation(goal="", task_id="rollover")

        reply = self._send_and_read(message)
        self._turns += 1

        if expect_json and not _looks_like_json(reply):
            for _ in range(max(0, config.CHATGPT_JSON_REPAIR_RETRIES)):
                LOG.info("reply not JSON; sending in-conversation repair nudge")
                reply = self._send_and_read(
                    "Your previous reply was not valid JSON. Reply with ONLY the JSON object, "
                    "no prose, no code fence.")
                self._turns += 1
                if _looks_like_json(reply):
                    break
        return reply or None

    def _send_and_read(self, message: str) -> str:
        composer = self._resolve("composer")
        composer.last.click()
        self._type_humanlike(composer, message)
        # Submit: prefer the send button, fall back to Enter on the composer.
        send = sel.first_visible(self.page, "send_button")
        if send is not None:
            send.last.click()
        else:
            composer.last.press("Enter")
        self.await_reply_complete()
        return extract_latest_reply(self.page)

    def _type_humanlike(self, composer: Any, text: str) -> None:
        """Type with a small per-keystroke delay (less bot-like than an instant fill). Falls back
        to fill() when the page object doesn't support sequential typing (e.g. test fakes)."""
        target = composer.last
        for meth in ("press_sequentially", "type"):
            fn = getattr(target, meth, None)
            if callable(fn):
                try:
                    fn(text, delay=15)
                    return
                except Exception:  # noqa: BLE001
                    break
        target.fill(text)

    # -- run-start health probe --------------------------------------------------------------
    def health_probe(self) -> bool:
        """Confirm the session is logged in + reachable before a run relies on it. Returns False
        (never raises) on any problem so the orchestrator can fall back to Ollama for the run."""
        try:
            self.open()
            self.page.goto("https://chatgpt.com/")
            self._guard_state()
            reply = self.ask("Reply with the single word READY and nothing else.")
            ok = bool(reply) and "READY" in reply.upper()
            LOG.info("health probe %s", "passed" if ok else "failed (no READY)")
            return ok
        except Exception as e:  # noqa: BLE001
            LOG.warning("health probe failed: %s", e)
            return False


def quickLoginCheck(timeout_s: int = 15) -> tuple[str, "ChatGPTSession"]:
    """Open a non-headless browser, navigate to chatgpt.com, return (state, session).
    Caller is responsible for closing the session. Never raises — returns UNKNOWN on error."""
    sess = ChatGPTSession()
    try:
        sess.open()
        sess.page.goto("https://chatgpt.com/", wait_until="domcontentloaded",
                       timeout=timeout_s * 1000)
        state = classify_state(sess.page)
        LOG.info("quickLoginCheck → %s", state)
        return state, sess
    except Exception as e:  # noqa: BLE001
        LOG.warning("quickLoginCheck error: %s", e)
        return UNKNOWN, sess


def waitForLogin(sess: "ChatGPTSession", timeout_s: int = 300, poll_s: int = 3) -> bool:
    """Poll classify_state on an already-open session until READY or timeout.
    Closes the session before returning. Returns True if login was confirmed."""
    import time as _time
    deadline = _time.monotonic() + timeout_s
    try:
        while _time.monotonic() < deadline:
            state = classify_state(sess.page)
            LOG.debug("waitForLogin poll → %s", state)
            if state == READY:
                return True
            _time.sleep(poll_s)
        LOG.warning("waitForLogin timed out after %ds", timeout_s)
        return False
    except Exception as e:  # noqa: BLE001
        LOG.warning("waitForLogin error: %s", e)
        return False
    finally:
        try:
            sess.close()
        except Exception:  # noqa: BLE001
            pass


def _looks_like_json(text: Optional[str]) -> bool:
    import re
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.IGNORECASE).strip()
    return t.startswith("{") and t.endswith("}")
