"""Counterfactual offline replay -- subsystem D of the Self-Improvement Engine.

Because verifies are deterministic and zero-API, a challenger (prompt or adapter) can be
re-run against *logged* past subtasks to estimate its uplift BEFORE any live exposure.
The actual re-authoring + re-verification is an injectable ``replay_fn`` seam (live wires
the challenger brain + the verifier; tests inject a deterministic function), so this
module is pure and offline-testable.

See the spec (subsystem D) + learning/rollout.py.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

import config
from memory import experience

LOG = config.getLogger("sie.counterfactual")

# replay_fn(subtask_row) -> bool : would the challenger PASS this subtask's held-out verify?
ReplayFn = Callable[[dict[str, Any]], bool]


def estimate_uplift(rows: list[dict[str, Any]], replay_fn: ReplayFn, *,
                    label_key: str = "verify_passed") -> dict[str, Any]:
    """Compare the challenger's replayed pass rate against the logged champion rate.

    Returns {n, champion_rate, challenger_rate, uplift}. A replay_fn error counts as a
    fail (conservative). ``uplift`` > 0 means the challenger looks better offline.
    """
    n = champ = chall = 0
    for r in rows:
        n += 1
        if r.get(label_key) == 1:
            champ += 1
        try:
            if replay_fn(r):
                chall += 1
        except Exception as e:  # noqa: BLE001 -- a replay blow-up scores as a fail
            LOG.debug("replay_fn failed on %s (counted as fail): %s", r.get("st_id"), e)
    if n == 0:
        return {"n": 0, "champion_rate": 0.0, "challenger_rate": 0.0, "uplift": 0.0}
    cr, hr = champ / n, chall / n
    return {"n": n, "champion_rate": cr, "challenger_rate": hr, "uplift": hr - cr}


def replay_over_ledger(replay_fn: ReplayFn, *, limit: Optional[int] = None,
                       db_path: Optional[Path] = None) -> dict[str, Any]:
    """Estimate uplift over recent logged subtasks that carry a real verify result."""
    rows = [r for r in experience.fetch_subtasks(db_path=db_path)
            if r.get("verify_passed") is not None]
    if limit:
        rows = rows[-limit:]
    return estimate_uplift(rows, replay_fn)
