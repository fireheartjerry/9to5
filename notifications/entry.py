"""NotificationEntry — typed schema for entries written to task.data['notifications'].

Required keys: at (ISO-8601), kind (non-empty str), detail (str).
Optional keys: any **extra kwargs passed to makeEntry.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# Canonical kinds; consumers may use others but these are the defined vocabulary.
VALID_KINDS: frozenset[str] = frozenset({
    "plan_gate",
    "plan_challenged",
    "architecture_challenged",
    "subtask_failed",
    "subtask_crashed",
    "subtask_done",
    "adversary_triggered",
    "backfill",
    "replan",
    "replan_removed",
    "architect_done",
    "planning_start",
    "selfmod_gate",
    "pr_held",
    "complete",
    "aborted",
    "blocked",
})

REQUIRED_KEYS: tuple[str, ...] = ("at", "kind", "detail")


def makeEntry(kind: str, detail: str, **extra: Any) -> dict[str, Any]:
    """Build a well-formed notification entry with a UTC ISO-8601 timestamp."""
    if not isinstance(kind, str) or not kind:
        raise ValueError("kind must be a non-empty string")
    if not isinstance(detail, str):
        raise TypeError(f"detail must be a str, got {type(detail).__name__!r}")
    return {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kind": kind,
        "detail": detail,
        **extra,
    }


def validate(entry: dict[str, Any]) -> list[str]:
    """Return a list of validation errors (empty means valid)."""
    errors: list[str] = []
    if not isinstance(entry, dict):
        return [f"entry must be a dict, got {type(entry).__name__!r}"]
    for key in REQUIRED_KEYS:
        if key not in entry:
            errors.append(f"missing required key: {key!r}")
    if "at" in entry:
        try:
            datetime.fromisoformat(entry["at"])
        except (ValueError, TypeError):
            errors.append(f"'at' is not valid ISO-8601: {entry['at']!r}")
    if "kind" in entry and not (isinstance(entry["kind"], str) and entry["kind"]):
        errors.append("'kind' must be a non-empty string")
    if "detail" in entry and not isinstance(entry["detail"], str):
        errors.append(f"'detail' must be a str, got {type(entry['detail']).__name__!r}")
    return errors
