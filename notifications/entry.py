"""NotificationEntry — typed schema for entries written to task.data['notifications'].

Required keys: at (ISO-8601), kind (non-empty str), detail (str),
               entry_id (UUID4 str), seq (monotonic int).
Optional keys: any **extra kwargs passed to makeEntry.

entry_id enables idempotent real-time updates (patch by id rather than by index).
seq provides a cross-second ordering guarantee when multiple entries share the same
timestamp — required for correct real-time replay and dashboard ordering.
"""
from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

_LOG = logging.getLogger(__name__)

# Module-level monotonic counter; thread-safe via lock.
_SEQ_LOCK = threading.Lock()
_SEQ_COUNTER: int = 0


def _nextSeq() -> int:
    global _SEQ_COUNTER
    with _SEQ_LOCK:
        _SEQ_COUNTER += 1
        return _SEQ_COUNTER


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

REQUIRED_KEYS: tuple[str, ...] = ("at", "kind", "detail", "entry_id", "seq")

# Schema version surfaced in every entry so consumers can handle upgrades.
SCHEMA_VERSION: str = "2"


def makeEntry(kind: str, detail: str, **extra: Any) -> dict[str, Any]:
    """Build a well-formed notification entry with a UTC ISO-8601 timestamp,
    a unique entry_id, and a monotonic seq for real-time ordering."""
    if not isinstance(kind, str) or not kind:
        raise ValueError("kind must be a non-empty string")
    if not isinstance(detail, str):
        raise TypeError(f"detail must be a str, got {type(detail).__name__!r}")
    validated: dict[str, Any] = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kind": kind,
        "detail": detail,
        "entry_id": str(uuid.uuid4()),
        "seq": _nextSeq(),
        "schema_version": SCHEMA_VERSION,
    }
    for k, v in extra.items():
        if k in validated:
            _LOG.warning("makeEntry: dropping conflicting kwarg %r (would overwrite %r)", k, validated[k])
        else:
            validated[k] = v
    return validated


def isValid(entry: dict[str, Any]) -> bool:
    """Return True iff validate() finds no errors."""
    return validate(entry) == []


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
    if "entry_id" in entry and not (isinstance(entry["entry_id"], str) and entry["entry_id"]):
        errors.append("'entry_id' must be a non-empty string")
    if "seq" in entry and not isinstance(entry["seq"], int):
        errors.append(f"'seq' must be an int, got {type(entry['seq']).__name__!r}")
    return errors
