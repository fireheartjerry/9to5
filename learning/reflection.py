"""Teacher -> student distillation via executor self-reports -- subsystem I of the SIE.

The executor is Claude Code, far stronger than the local brain. Ask it for a small
structured learning summary at the end of a subtask and -- after cross-checking the
self-report against the REAL verify + adversary verdict (trust but verify) -- feed the
trusted recipes into lessons + training. Multi-teacher ready (``teacher`` field, M).
Pure-stdlib parsing; offline-testable.

See the spec (subsystem I + M).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

import config
from memory import experience

LOG = config.getLogger("sie.reflection")

# The instruction the executor is asked to satisfy (appended to its system prompt).
REQUEST = (
    "After completing the task, append a fenced ```json block named LEARNING_SUMMARY with "
    "keys: approach, pitfalls (list), reusable_recipe, spec_feedback, verify_critique, "
    "confidence (0-1). Keep it under 120 words."
)

_APPROVED = {"approved", "approve"}


def parse(text: str) -> Optional[dict[str, Any]]:
    """Extract the LEARNING_SUMMARY JSON object from executor output, or None."""
    if not text:
        return None
    # Prefer a fenced json block; fall back to the last {...} object.
    for m in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL):
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict) and "approach" in obj:
                return obj
        except Exception:  # noqa: BLE001
            continue
    try:
        start = text.rindex("{")
        return json.loads(text[start:])
    except Exception:  # noqa: BLE001
        return None


def trust(summary: dict[str, Any], *, verify_passed: Optional[bool],
          adversary_verdict: Optional[str],
          adversary_stub: bool = False) -> bool:
    """A summary is trusted only if its claim is consistent with the REAL outcome.

    A high-confidence debrief on a FAILED verify is self-serving -> not trusted. A
    challenged adversary verdict also blocks trust. A stub/degraded adversary verdict
    (auto-approve fallback with no real signal) is also untrusted — ``adversary_stub=True``
    means the adversary did not actually evaluate the output.
    """
    if not isinstance(summary, dict):
        return False
    if verify_passed is False:
        return False
    if adversary_verdict and adversary_verdict.lower() not in _APPROVED \
            and adversary_verdict.lower() not in ("", "none"):
        return False
    if adversary_stub:
        return False
    return True


def capture(*, run_id: str, subtask_id: str, executor_output: str,
            verify_passed: Optional[bool] = None, adversary_verdict: Optional[str] = None,
            adversary_stub: bool = False,
            role: str = "executor", teacher: str = "claude",
            db_path: Optional[Path] = None) -> dict[str, Any]:
    """Parse + trust-check + persist a learning summary. Best-effort; returns a small
    status dict. Trusted summaries become retrievable lessons / training recipes."""
    summary = parse(executor_output)
    if summary is None:
        return {"captured": False, "reason": "no_summary"}
    trusted = trust(summary, verify_passed=verify_passed, adversary_verdict=adversary_verdict,
                    adversary_stub=adversary_stub)
    experience.record_reflection(
        run_id=run_id, subtask_id=subtask_id, role=role, teacher=teacher, trusted=trusted,
        approach=summary.get("approach"), reusable_recipe=summary.get("reusable_recipe"),
        spec_feedback=summary.get("spec_feedback"), verify_critique=summary.get("verify_critique"),
        confidence=summary.get("confidence"), db_path=db_path)
    return {"captured": True, "trusted": trusted}


def recipes(*, db_path: Optional[Path] = None) -> list[str]:
    """Trusted reusable recipes -- teacher targets for distillation / lessons."""
    return [r["reusable_recipe"] for r in experience.fetch_reflections(trusted_only=True, db_path=db_path)
            if r.get("reusable_recipe")]
