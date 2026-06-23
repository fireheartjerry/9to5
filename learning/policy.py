"""Policy Learning -- Layer 4 of the Self-Improvement Engine.

A pure-Python contextual bandit over the Experience Ledger that learns which effort
level (and, later, model/skills) tends to pass for a given task family, and exposes that
as a *prior* the brain may override. Arms are rebuilt deterministically from the ledger
(idempotent; no hot-path writes, no double-counting), so this never touches the run loop.

Selection is Gaussian Thompson sampling: each candidate action samples from its reward
posterior, the max sample wins, and unseen actions get an optimistic prior so the system
keeps exploring. See the spec (Layer 4).
"""
from __future__ import annotations

import json
import math
import random
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

import config
from learning.lessons import family_of
from memory import experience

LOG = config.getLogger("sie.policy")

# Optimistic prior for never-tried actions -> encourages exploration of new arms.
_OPTIMISTIC_MEAN = 1.0
_OPTIMISTIC_STD = 1.0
_COST_CAP = 1.0  # USD at which norm_cost saturates


def compute_reward(row: dict[str, Any]) -> float:
    """Composite reward for one subtask outcome (higher is better).

    reward = w_fp·first_pass − w_att·(attempts−1) − w_cost·norm_cost − w_wall·norm_wallclock
    """
    w = config.POLICY_REWARD_WEIGHTS
    first_pass = 1.0 if row.get("verify_passed") == 1 else 0.0
    attempts = row.get("attempt_count") or 1
    try:
        attempts = max(1, int(attempts))
    except (TypeError, ValueError):
        attempts = 1
    norm_cost = min(1.0, float(row.get("cost_usd") or 0.0) / _COST_CAP)
    norm_wall = min(1.0, float(row.get("_norm_wallclock") or 0.0))
    return (w["first_pass"] * first_pass
            - w["attempts"] * (attempts - 1)
            - w["cost"] * norm_cost
            - w["wallclock"] * norm_wall)


def context_key(title: str, signature_tags: Optional[str] = None) -> str:
    """The bandit context -- the task family (coarse bucket the action is chosen within)."""
    return family_of(title, signature_tags)


def action_of(row: dict[str, Any]) -> dict[str, Any]:
    """The action a past subtask took (what the policy chooses among)."""
    return {"effort": row.get("effort") or "default"}


def _action_json(action: dict[str, Any]) -> str:
    return json.dumps(action, sort_keys=True)


def rebuild_from_ledger(db_path: Optional[Path] = None) -> dict[str, int]:
    """Recompute every arm's reward statistics from the full ledger (idempotent)."""
    acc: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])  # pulls, sum, sqsum
    for r in experience.fetch_subtasks(db_path=db_path):
        if not r.get("effort"):
            continue
        ck = context_key(r.get("title") or "", r.get("signature_tags"))
        aj = _action_json(action_of(r))
        reward = compute_reward(r)
        a = acc[(ck, aj)]
        a[0] += 1
        a[1] += reward
        a[2] += reward * reward

    experience.clear_arms(db_path=db_path)
    for (ck, aj), (pulls, rsum, rsq) in acc.items():
        experience.set_arm(ck, aj, pulls=int(pulls), reward_sum=rsum,
                           reward_sq_sum=rsq, db_path=db_path)
    LOG.info("policy rebuild: %d arms", len(acc))
    return {"arms": len(acc)}


def _sample_arm(stats: Optional[dict[str, Any]], rng: random.Random) -> float:
    """Thompson sample of an arm's mean reward (optimistic prior for unseen arms)."""
    if not stats or not stats.get("pulls"):
        return rng.gauss(_OPTIMISTIC_MEAN, _OPTIMISTIC_STD)
    n = stats["pulls"]
    mean = stats["reward_sum"] / n
    var = max(0.0, stats["reward_sq_sum"] / n - mean * mean)
    std = math.sqrt(var / n) + 0.05  # posterior std of the mean + a small floor
    return rng.gauss(mean, std)


def select(ck: str, actions: list[dict[str, Any]], *, rng: Optional[random.Random] = None,
           db_path: Optional[Path] = None) -> dict[str, Any]:
    """Thompson-pick the best action for context ``ck`` among ``actions``."""
    rng = rng or random
    arms = {a["action_json"]: a for a in experience.fetch_arms(ck, db_path=db_path)}
    best_action, best_sample = actions[0], -math.inf
    for action in actions:
        s = _sample_arm(arms.get(_action_json(action)), rng)
        if s > best_sample:
            best_action, best_sample = action, s
    return best_action


def hint(goal: str, title: str, *, rng: Optional[random.Random] = None,
         db_path: Optional[Path] = None) -> str:
    """Orchestrator-facing best-effort one-liner: the learned effort prior, or "".

    Returns "" when there is no evidence yet (the chosen arm was never pulled), so the
    spec author only sees a hint once the policy has actually learned something.
    """
    try:
        ck = context_key(title or goal)
        actions = [{"effort": e} for e in config.EFFORT_LEVELS]
        chosen = select(ck, actions, rng=rng, db_path=db_path)
        arms = {a["action_json"]: a for a in experience.fetch_arms(ck, db_path=db_path)}
        if not arms.get(_action_json(chosen), {}).get("pulls"):
            return ""  # nothing learned for this family yet
        return f"## POLICY HINT (learned): prefer effort={chosen['effort']} for this kind of task.\n\n"
    except Exception as e:  # noqa: BLE001 -- never break authoring
        LOG.debug("policy hint failed (ignored): %s", e)
        return ""


if __name__ == "__main__":  # pragma: no cover
    experience.init()
    print(rebuild_from_ledger())
