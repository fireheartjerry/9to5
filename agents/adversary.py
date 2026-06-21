"""Adversary -- Phase-1 STUB.

In Phase 2 this becomes GPT-5.5 driven via chatgpt.com (CDP). For now it only:
  * decides whether a review should trigger (shouldTrigger), and
  * logs the trigger reason and returns an "approved" verdict (review).

Trigger signals (per the 9TO5 spec):
  * uncertainty phrases in the executor output,
  * >= MAX_SUBTASK_ATTEMPTS attempts on the same subtask,
  * every Nth subtask as a heartbeat floor,
  * a pre-PR safety review.
"""
from __future__ import annotations

import config

LOG = config.getLogger("adversary")


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


def review(subtask_title: str, trigger_reason: str, executor_output: str) -> dict:
    """STUB review -- log the trigger and auto-approve."""
    LOG.info("ADVERSARY STUB triggered for '%s' (%s) -> approved", subtask_title, trigger_reason)
    return {
        "verdict": "approved",
        "trigger_reason": trigger_reason,
        "stub": True,
        "notes": "Adversary is stubbed in Phase 1; auto-approved. Phase 2 -> GPT-5.5 via chatgpt.com CDP.",
    }
