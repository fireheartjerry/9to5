"""Solution memoization / warm-start -- subsystem O of the SIE.

Lessons are advice; this reuses *work*. On a near-duplicate subtask signature, return the
prior PASSING spec to warm-start or short-circuit instead of re-deriving it. Gated by
"did it still verify". Pure-stdlib + ledger; offline-testable.

See the spec (subsystem O).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

import config
from memory import experience

LOG = config.getLogger("sie.solution_cache")


def signature_of(title: str) -> str:
    """A coarse, normalized signature for matching near-duplicate subtasks."""
    return re.sub(r"\s+", " ", (title or "").strip().lower())


def build_from_ledger(*, db_path: Optional[Path] = None) -> dict[str, int]:
    """Populate the cache from gold (first-pass, approved) subtasks that carry a spec."""
    cached = 0
    for r in experience.gold_examples(db_path=db_path):
        spec = r.get("invocation_spec_json")
        if not spec:
            continue
        if experience.upsert_solution(signature_of(r.get("title") or ""), spec,
                                      verify_passed=True, db_path=db_path):
            cached += 1
    return {"cached": cached}


def warm_start(title: str, *, db_path: Optional[Path] = None) -> Optional[str]:
    """Return a cached PASSING spec for a near-duplicate subtask, or None. Best-effort."""
    try:
        sol = experience.get_solution(signature_of(title), db_path=db_path)
        return sol["spec_json"] if sol else None
    except Exception as e:  # noqa: BLE001
        LOG.debug("warm_start failed (ignored): %s", e)
        return None
