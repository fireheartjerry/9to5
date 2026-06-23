"""Browser execution backend -- Layer 1 (CDP) "hands" for 9TO5.

A peer to the Claude-CLI executor (agents/executor.py): same call signature, same result-
dict contract, so the orchestrator's dispatcher can route a subtask to the browser when the
brain authors ``surface="browser"``. It drives Chromium via Playwright (real CDP) to run a
list of structured actions (goto/click/type/extract/screenshot/wait). When Playwright is
not installed the call degrades cleanly (ok=False, is_error=True) so the run continues --
exactly like a failed terminal subtask -- rather than crashing.

Deterministic + offline-testable: the Playwright work is isolated behind ``_run_actions``
(mockable); URL-only prompts auto-expand to a fetch+extract so simple "look at this page"
goals work without the brain hand-authoring actions.

See docs (Layer 1 browser) + surfaces.py + the orchestrator dispatcher.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

import config
from agents import executor

LOG = config.getLogger("browser_executor")

_URL_RE = re.compile(r"https?://[^\s\"'<>)]+")

# --- chatgpt.com CDP routing (Phase 2 Adversary brain) --------------------------------
# The Adversary's Phase-2 brain is GPT-5.5 reached by driving chatgpt.com over CDP. We
# express "ask ChatGPT one message and read its reply" as the same structured action list
# runBrowser already executes, so no new transport is needed -- only a small, configurable
# action recipe + a transcript parser. Selectors are module constants so a UI change is a
# one-line fix and tests never depend on the live DOM.
CHATGPT_URL = "https://chatgpt.com/"
CHATGPT_INPUT_SELECTOR = "#prompt-textarea"
CHATGPT_SEND_KEY = "Enter"
CHATGPT_REPLY_SELECTOR = "[data-message-author-role='assistant']"
CHATGPT_REPLY_TIMEOUT_MS = 120000


class BrowserUnavailable(RuntimeError):
    """Raised when no browser backend (Playwright/Chromium) is installed."""


def _result(spec: dict, *, ok: bool, is_error: bool, stdout: str = "", stderr: str = "") -> dict:
    """A runClaude-shaped result so the orchestrator treats browser output identically."""
    return {
        "ok": ok, "returncode": 0 if ok else 1, "stdout": stdout, "stderr": stderr,
        "is_error": is_error, "effort": spec.get("effort_level", "default"),
        "effort_flag": None, "spec": spec, "claude_md_path": None,
        "profile": "browser_navigator", "blocked": False, "surface": "browser",
    }


def _actions_from_prompt(prompt: str) -> list[dict[str, Any]]:
    """Auto-derive simple actions from a URL-bearing prompt: visit each URL + extract text."""
    actions: list[dict[str, Any]] = []
    for url in _URL_RE.findall(prompt or ""):
        actions.append({"action": "goto", "url": url})
        actions.append({"action": "extract"})
    return actions


def _run_actions(actions: list[dict[str, Any]], *, timeout_ms: int = 30000,
                 screenshot_dir: Optional[str] = None) -> str:
    """Execute structured CDP actions via Playwright; return a transcript. Raises
    BrowserUnavailable if Playwright/Chromium is not installed (caller degrades).

    Supported actions: goto, click, type, press, select, scroll, wait, extract, eval,
    screenshot. Each line of the transcript records the action + its observable result so
    the verifier can check the outcome."""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as e:  # noqa: BLE001 -- not installed -> caller degrades cleanly
        raise BrowserUnavailable(
            "browser layer unavailable: `pip install playwright && playwright install chromium`") from e

    lines: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_default_timeout(timeout_ms)
            for i, act in enumerate(actions):
                kind = (act.get("action") or "").lower()
                if kind == "goto":
                    page.goto(act["url"])
                    lines.append(f"goto {act['url']} -> {page.title()!r}")
                elif kind == "click":
                    page.click(act["selector"])
                    lines.append(f"click {act['selector']}")
                elif kind == "type":
                    page.fill(act["selector"], act.get("text", ""))
                    lines.append(f"type into {act['selector']}")
                elif kind == "press":
                    page.press(act["selector"], act.get("key", "Enter"))
                    lines.append(f"press {act.get('key', 'Enter')} on {act['selector']}")
                elif kind == "select":
                    page.select_option(act["selector"], act.get("value"))
                    lines.append(f"select {act.get('value')} in {act['selector']}")
                elif kind == "scroll":
                    page.mouse.wheel(0, int(act.get("dy", 800)))
                    lines.append(f"scroll dy={act.get('dy', 800)}")
                elif kind == "wait":
                    if act.get("selector"):
                        page.wait_for_selector(act["selector"])
                        lines.append(f"wait {act['selector']}")
                    else:
                        page.wait_for_timeout(int(act.get("ms", 1000)))
                        lines.append(f"wait {act.get('ms', 1000)}ms")
                elif kind == "extract":
                    sel = act.get("selector")
                    text = (page.inner_text(sel) if sel else page.inner_text("body"))[:2000]
                    lines.append(f"extract {sel or 'body'}:\n{text}")
                elif kind == "eval":
                    val = page.evaluate(act["script"])
                    lines.append(f"eval -> {str(val)[:500]}")
                elif kind == "screenshot":
                    name = act.get("path") or f"screenshot-{i}.png"
                    path = str(Path(screenshot_dir) / name) if screenshot_dir else name
                    page.screenshot(path=path)
                    lines.append(f"screenshot -> {path}")
                else:
                    lines.append(f"(skipped unknown action {kind!r})")
        finally:
            browser.close()
    return "\n".join(lines)


def runBrowser(spec_or_prompt, *, work_dir: Optional[str] = None, task_state=None,
               subtask: Optional[dict] = None, resume_session: Optional[str] = None,
               **_kw) -> dict:
    """Execute a browser subtask. Matches executor.runClaude's signature + result shape."""
    spec = executor.normalizeSpec(spec_or_prompt)
    actions = spec.get("browser_actions") or _actions_from_prompt(spec.get("prompt", ""))
    if not actions:
        return _result(spec, ok=False, is_error=True,
                       stderr="browser surface needs 'browser_actions' or a URL in the prompt")
    try:
        transcript = _run_actions(actions, screenshot_dir=work_dir)
        LOG.info("browser run: %d actions ok", len(actions))
        return _result(spec, ok=True, is_error=False, stdout=transcript)
    except BrowserUnavailable as e:
        LOG.warning("%s", e)
        return _result(spec, ok=False, is_error=True, stderr=str(e))
    except Exception as e:  # noqa: BLE001 -- a browser failure is a failed subtask, not a crash
        LOG.warning("browser run failed (ignored): %s", e)
        return _result(spec, ok=False, is_error=True, stderr=f"browser run failed: {e}")


def chatgptActions(message: str) -> list[dict[str, Any]]:
    """Build the CDP action recipe that asks chatgpt.com one ``message`` and reads the reply:
    open the chat, type into the composer, submit, wait for the assistant turn, extract it."""
    return [
        {"action": "goto", "url": CHATGPT_URL},
        {"action": "wait", "selector": CHATGPT_INPUT_SELECTOR},
        {"action": "type", "selector": CHATGPT_INPUT_SELECTOR, "text": message},
        {"action": "press", "selector": CHATGPT_INPUT_SELECTOR, "key": CHATGPT_SEND_KEY},
        {"action": "wait", "selector": CHATGPT_REPLY_SELECTOR},
        {"action": "extract", "selector": CHATGPT_REPLY_SELECTOR},
    ]


def _replyFromTranscript(transcript: str) -> str:
    """Pull the assistant text out of a runBrowser transcript. Each ``extract`` step is
    written as ``extract <selector>:\\n<text>`` (see _run_actions); return the body of the
    LAST extract block -- that is GPT's reply to our message."""
    text = transcript or ""
    idx = text.rfind("extract ")
    if idx < 0:
        return ""
    block = text[idx:]                  # "extract <selector>:\n<reply text...>"
    nl = block.find("\n")
    if nl < 0:
        # no newline: the transcript was truncated after the selector line, so there is
        # NO reply body. Return "" (not the selector) -- a CSS selector is not GPT's reply,
        # and feeding it downstream would masquerade as a real critique.
        return ""
    return block[nl + 1:].strip()


def askChatGPT(message: str, *, runner=None, work_dir: Optional[str] = None) -> Optional[str]:
    """Send one ``message`` to chatgpt.com over CDP and return GPT's reply text.

    Routes through :func:`runBrowser` (the L1 hands) using :func:`chatgptActions`, so the
    transport, Playwright degradation, and result contract are shared with every other
    browser subtask. Returns ``None`` when the browser layer is unavailable or the run
    fails, so callers (e.g. the Adversary) can degrade conservatively instead of crashing.
    """
    run = runner or runBrowser
    res = run({"surface": "browser", "browser_actions": chatgptActions(message)},
              work_dir=work_dir)
    if not res or not res.get("ok"):
        LOG.warning("askChatGPT failed: %s", (res or {}).get("stderr", "no result"))
        return None
    reply = _replyFromTranscript(res.get("stdout", ""))
    return reply or None
