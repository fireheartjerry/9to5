"""Adversary -- independent reviewer of executor output.

Phase 1 runs a REAL critique through the local Ollama brain (zero marginal API
cost): given an executor output and *why* the review fired, it returns a verdict
(``approved`` | ``challenged``) with concrete concerns. When no Ollama callable
is supplied (or the call fails / returns junk), it degrades gracefully to a
conservative auto-approve so a run is never blocked by the reviewer itself.

In Phase 2 this becomes GPT-5.5 driven via chatgpt.com (CDP); the trigger and
verdict contract stay identical so the call site never changes.

Trigger signals (per the 9TO5 spec):
  * uncertainty phrases in the executor output,
  * >= MAX_SUBTASK_ATTEMPTS attempts on the same subtask,
  * every Nth subtask as a heartbeat floor,
  * a pre-PR safety review.
"""
from __future__ import annotations

import json
import re
import time
from typing import Callable, Optional

import config

LOG = config.getLogger("adversary")


def _loadJsonLoose(content: object):
    """Parse a brain JSON reply the way the orchestrator's _chatJson does -- tolerating a ```json
    fence or prose around the object. Critical for the Adversary (FX-5): a real 'challenged' verdict
    wrapped in a fence/prose must NOT silently fail json.loads and degrade to a conservative
    'approved', which would neuter the PR-hold and remediation. Returns a dict or None."""
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        return None
    text = content.strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)   # salvage the first balanced-looking object
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:  # noqa: BLE001
            return None
    return None

# Vocabulary aligned with notifications.discord_bot._APPROVED / _CHALLENGED.
_APPROVED = "approved"
_CHALLENGED = "challenged"
_CHALLENGE_WORDS = {"challenged", "rejected", "reject", "blocked", "fail", "concern"}

# Cap how much executor output we hand the brain; the rest is noise for review.
ADVERSARY_MAX_OUTPUT_CHARS = 6000

# CDP retry knobs: up to CDP_MAX_RETRIES extra attempts on transient network errors,
# with exponential backoff starting at CDP_RETRY_BACKOFF_BASE seconds.
CDP_MAX_RETRIES: int = 2
CDP_RETRY_BACKOFF_BASE: float = 1.0

# Error substrings that identify transient CDP/network failures worth retrying.
_CDP_TRANSIENT_SIGNALS: tuple[str, ...] = (
    "timeout", "timed out", "net::", "connection", "socket", "reset", "disconnect",
    "econnrefused", "unreachable", "navigation", "target closed",
)

_SYSTEM = (
    "You are the 9TO5 Adversary: a strict, independent reviewer of work just produced by an "
    "executor agent. You did NOT do the work and have no stake in approving it. Judge ONLY what "
    "the output evidences: did it actually accomplish the subtask, or did it cut corners, leave "
    "TODOs, fake/skip verification, mis-handle errors, or drift off-scope? Be skeptical but fair "
    "-- do not invent problems. Respond with JSON ONLY, no prose, exactly this shape:\n"
    '{"verdict": "approved" | "challenged", "concerns": ["short, specific concern", ...], '
    '"notes": "one or two sentences of rationale"}\n'
    'Use "challenged" when there is real evidence of incomplete, incorrect, unsafe, or off-scope '
    'work; otherwise "approved" with an empty concerns list.'
)


def isCdpTransient(exc: BaseException) -> bool:
    """True when ``exc`` looks like a transient CDP/network hiccup worth retrying."""
    msg = str(exc).lower()
    return any(s in msg for s in _CDP_TRANSIENT_SIGNALS)


def shouldTrigger(executor_output: str, subtask_position: int,
                  attempt_count: int = 1, pre_pr: bool = False) -> tuple[bool, str]:
    """Return ``(triggered, reason)``."""
    text = (executor_output or "").lower()
    for phrase in config.ADVERSARY_TRIGGER_PHRASES:
        if phrase in text:
            return True, f"uncertainty phrase detected: '{phrase}'"
    if attempt_count >= config.MAX_SUBTASK_ATTEMPTS:
        return True, f"{attempt_count} attempts on the same subtask"
    if pre_pr:
        return True, "pre-PR safety review"
    if subtask_position > 0 and subtask_position % config.ADVERSARY_HEARTBEAT_EVERY == 0:
        return True, f"heartbeat: every {config.ADVERSARY_HEARTBEAT_EVERY}rd subtask"
    return False, ""


def _normalizeVerdict(raw: object) -> str:
    """Collapse any model phrasing into the two-valued contract."""
    v = str(raw or "").strip().lower()
    if any(w in v for w in _CHALLENGE_WORDS):
        return _CHALLENGED
    return _APPROVED


def _stubReview(trigger_reason: str, *, note: Optional[str] = None) -> dict:
    """Conservative fallback: approve, but mark it as un-reviewed so it is never
    mistaken for a real pass. Used when no brain is wired or the brain errors."""
    return {
        "verdict": _APPROVED,
        "trigger_reason": trigger_reason,
        "concerns": [],
        "notes": note or ("Adversary brain unavailable; auto-approved without a real critique. "
                          "Phase 2 -> GPT-5.5 via chatgpt.com CDP."),
        "stub": True,
    }


def _buildReviewUser(subtask_title: str, trigger_reason: str, executor_output: str,
                     goal: str) -> str:
    """The user-turn prompt handed to whichever brain reviews -- Ollama (Phase 1) or
    GPT-5.5 via chatgpt.com CDP (Phase 2). Single source so the two paths can't drift."""
    return (
        f"Subtask under review: {subtask_title}\n"
        f"Why this review fired: {trigger_reason}\n"
        f"Overall goal: {goal[:1000]}\n\n"
        f"Executor output to judge:\n{(executor_output or '')[:ADVERSARY_MAX_OUTPUT_CHARS]}\n\n"
        "Return the review JSON."
    )


def _parseVerdict(raw_content: object, trigger_reason: str, *, surface: str) -> dict:
    """Turn a brain's raw JSON reply into the verdict contract. Raises on junk so the
    caller can degrade to a conservative stub."""
    data = _loadJsonLoose(raw_content)
    if not isinstance(data, dict):
        raise ValueError("non-object review payload")
    verdict = _normalizeVerdict(data.get("verdict"))
    concerns = [str(c) for c in (data.get("concerns") or []) if str(c).strip()][:10]
    notes = str(data.get("notes") or "").strip()
    return {
        "verdict": verdict,
        "trigger_reason": trigger_reason,
        "concerns": concerns,
        "notes": notes,
        "stub": False,
        "surface": surface,
    }


def reviewViaBrowser(subtask_title: str, trigger_reason: str, executor_output: str, *,
                     browser_ask: Optional[Callable] = None, goal: str = "") -> dict:
    """Phase-2 critique: route the review to GPT-5.5 on chatgpt.com over CDP.

    ``browser_ask`` is a ``(message) -> reply_text | None`` callable; it defaults to
    :func:`agents.browser_executor.askChatGPT`, which drives chatgpt.com through the L1
    browser hands. The verdict contract is identical to :func:`review`, so the call site
    never changes between phases.

    Transient CDP/network errors (timeout, connection reset, etc.) are retried up to
    ``CDP_MAX_RETRIES`` times with exponential backoff before falling back to a
    conservative auto-approve. Non-transient errors (bad JSON, empty reply) skip retries
    and degrade immediately. The reviewer never blocks a run by itself.
    """
    if browser_ask is None:
        from agents import browser_executor
        browser_ask = browser_executor.askChatGPT

    user = _buildReviewUser(subtask_title, trigger_reason, executor_output, goal)
    message = f"{_SYSTEM}\n\n{user}"
    last_exc: Optional[Exception] = None

    for attempt in range(CDP_MAX_RETRIES + 1):
        try:
            reply = browser_ask(message)
            if not reply:
                raise ValueError("empty reply from chatgpt.com")
            rv = _parseVerdict(reply, trigger_reason, surface="browser")
            LOG.info(
                "Adversary (browser/GPT) verdict for '%s' (%s) -> %s (%d concern(s))",
                subtask_title, trigger_reason, rv["verdict"], len(rv["concerns"]),
            )
            return rv
        except Exception as e:  # noqa: BLE001
            last_exc = e
            if attempt < CDP_MAX_RETRIES and isCdpTransient(e):
                wait = CDP_RETRY_BACKOFF_BASE * (2 ** attempt)
                LOG.warning(
                    "Adversary CDP transient error (attempt %d/%d, retry in %.1fs): %s",
                    attempt + 1, CDP_MAX_RETRIES + 1, wait, e,
                )
                time.sleep(wait)
                continue
            # Non-transient or retries exhausted -- log and fall through.
            LOG.warning(
                "Adversary browser critique failed after %d attempt(s) (%s); "
                "conservative auto-approve",
                attempt + 1, e,
            )
            break

    return _stubReview(
        trigger_reason,
        note=f"Adversary chatgpt.com critique errored ({last_exc}); auto-approved conservatively.",
    )


def review(subtask_title: str, trigger_reason: str, executor_output: str, *,
           ollama_chat: Optional[Callable] = None, goal: str = "") -> dict:
    """Critique the executor output and return a verdict dict.

    ``ollama_chat`` is the orchestrator's resilient Ollama caller
    ``(system, user, *, want_json=False) -> resp | None``. When it is None
    (e.g. unit tests, or a deliberately offline run) the reviewer degrades to a
    conservative auto-approve so the run is never blocked by the reviewer itself.
    """
    if ollama_chat is None:
        LOG.info("Adversary (no brain) for '%s' (%s) -> approved [stub]", subtask_title, trigger_reason)
        return _stubReview(trigger_reason)

    user = _buildReviewUser(subtask_title, trigger_reason, executor_output, goal)
    try:
        resp = ollama_chat(_SYSTEM, user, want_json=True)
        content = (resp.get("message") or {}).get("content") if isinstance(resp, dict) else None
        data = _loadJsonLoose(content)
        if not isinstance(data, dict):
            raise ValueError("non-object review payload")
        verdict = _normalizeVerdict(data.get("verdict"))
        concerns = [str(c) for c in (data.get("concerns") or []) if str(c).strip()][:10]
        notes = str(data.get("notes") or "").strip()
        LOG.info("Adversary verdict for '%s' (%s) -> %s (%d concern(s))",
                 subtask_title, trigger_reason, verdict, len(concerns))
        return {
            "verdict": verdict,
            "trigger_reason": trigger_reason,
            "concerns": concerns,
            "notes": notes,
            "stub": False,
        }
    except Exception as e:  # noqa: BLE001
        LOG.warning("Adversary brain critique failed (%s); conservative auto-approve", e)
        return _stubReview(trigger_reason,
                           note=f"Adversary critique errored ({e}); auto-approved conservatively.")
