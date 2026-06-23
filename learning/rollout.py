"""Shadow -> canary -> champion rollout -- subsystem E of the Self-Improvement Engine.

No challenger flips straight to champion. It is promoted through stages, each gated by
the harness/field fitness vs the incumbent baseline, with **auto-rollback at any stage on
regression** (invariant I4). Pure state machine -- offline-testable; the caller supplies
observed fitness + sample counts.

  shadow   -- authored in parallel, output unused (scored counterfactually)
  canary   -- used for a small fraction of real subtasks behind the bandit
  champion -- promoted only after canary clears the gate
  rolled_back -- regressed at any stage; the prior champion stays live

See the spec (subsystem E) + learning/promotion.py + learning/finetune.py.
"""
from __future__ import annotations

import random
from typing import Optional

STAGES = ("shadow", "canary", "champion")
ROLLED_BACK = "rolled_back"


def next_stage(stage: str, *, fitness: float, baseline: float, n: int,
               min_samples: int, tolerance: float = 0.0) -> str:
    """Advance one stage, hold, or roll back.

    - Regression (``fitness < baseline - tolerance``) at any stage -> ``rolled_back``.
    - Not enough samples yet -> stay in the current stage.
    - Otherwise advance shadow -> canary -> champion (champion is terminal).
    """
    if stage in (ROLLED_BACK, "champion"):
        return stage
    if fitness < baseline - tolerance:
        return ROLLED_BACK
    if n < min_samples:
        return stage
    idx = STAGES.index(stage) if stage in STAGES else 0
    return STAGES[min(idx + 1, len(STAGES) - 1)]


def should_use_candidate(stage: str, *, rng: Optional[random.Random] = None,
                         canary_fraction: float = 0.1) -> bool:
    """Whether a given run should actually USE the candidate's output.

    Shadow/rolled_back never use it (shadow only scores counterfactually); canary uses it
    for a fraction of runs; champion always uses it.
    """
    if stage == "champion":
        return True
    if stage == "canary":
        return (rng or random).random() < canary_fraction
    return False


def is_terminal(stage: str) -> bool:
    return stage in ("champion", ROLLED_BACK)
