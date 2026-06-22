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
from typing import Callable, Optional

import config

LOG = config.getLogger("adversary")

# Vocabulary aligned with notifications.discord_bot._APPROVED / _CHALLENGED.
_APPROVED = "approved"
_CHALLENGED = "challenged"
_CHALLENGE_WORDS = {"challenged", "rejected", "reject", "blocked", "fail", "concern"}

# Cap how much executor output we hand the brain; the rest is noise for review.
ADVERSARY_MAX_OUTPUT_CHARS = 6000

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

    user = (
        f"Subtask under review: {subtask_title}\n"
        f"Why this review fired: {trigger_reason}\n"
        f"Overall goal: {goal[:1000]}\n\n"
        f"Executor output to judge:\n{(executor_output or '')[:ADVERSARY_MAX_OUTPUT_CHARS]}\n\n"
        "Return the review JSON."
    )
    try:
        resp = ollama_chat(_SYSTEM, user, want_json=True)
        data = json.loads(resp["message"]["content"]) if resp else None
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
