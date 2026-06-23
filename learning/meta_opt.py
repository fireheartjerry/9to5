"""Meta-optimization -- subsystem Q of the SIE.

Tunes the learner's OWN knobs against the fitness series. Conservative + analysis-first:
it proposes knob changes with reasons; a slow, gated apply path adopts them. Pure-stdlib
+ ledger; offline-testable.

See the spec (subsystem Q).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import config
from learning import curriculum
from memory import experience

LOG = config.getLogger("sie.meta_opt")


def suggest(*, db_path: Optional[Path] = None) -> list[dict[str, Any]]:
    """Heuristic knob suggestions from observed outcomes. Returns a list of
    {knob, current, suggested, reason}."""
    suggestions: list[dict[str, Any]] = []
    fams = curriculum.family_stats(min_support=3, db_path=db_path)
    if fams:
        mean_fp = sum(f["first_pass_rate"] for f in fams) / len(fams)
        # If first-pass is chronically low, the bandit/effort floor is too timid.
        if mean_fp < 0.5:
            suggestions.append({
                "knob": "MAX_SUBTASK_ATTEMPTS", "current": config.MAX_SUBTASK_ATTEMPTS,
                "suggested": config.MAX_SUBTASK_ATTEMPTS + 1,
                "reason": f"mean first-pass {mean_fp:.0%} < 50% — allow one more retry"})
    # If almost nothing is being retrieved, widen K.
    n_emb = len(experience.embedded_subtasks(only_passed=True, db_path=db_path))
    if n_emb > 50 and config.RETRIEVAL_K < 8:
        suggestions.append({
            "knob": "RETRIEVAL_K", "current": config.RETRIEVAL_K, "suggested": config.RETRIEVAL_K + 2,
            "reason": f"{n_emb} embedded successes available — retrieve more context"})
    return suggestions
