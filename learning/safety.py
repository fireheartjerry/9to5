"""Safety invariant enforcement -- X2 of the Self-Improvement Engine.

A system that rewrites its own prompts, policies, and weights must never be able to fail
silently. This module makes the design's invariants (I1-I6) *checkable in code* and wires
the kill switch / panic-to-stock control. Pure-stdlib + ledger; offline-testable.

Invariants:
  I1 base immutability   -- every champion adapter's base_model == OLLAMA_MODEL
  I2 no self-promotion   -- the brain may propose, never crown (guard_promotion)
  I4 monotone/rollback   -- at most one champion per role (prompt + adapter)
  kill switch            -- always one command from stock

See the spec (Alignment & safety deep dive).
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Optional

import config
from learning import prompts
from memory import experience

LOG = config.getLogger("sie.safety")


class SelfPromotionError(RuntimeError):
    """Raised when a non-independent actor (the brain) tries to crown a champion (I2)."""


def guard_promotion(actor: str) -> None:
    """I2: only the independent gate may promote; the brain can only propose."""
    if actor == "brain":
        raise SelfPromotionError("the brain may propose challengers but never promote (I2)")


def verify_invariants(*, db_path: Optional[Path] = None) -> list[str]:
    """Return a list of invariant VIOLATIONS (empty == healthy)."""
    violations: list[str] = []

    adapters = experience.fetch_adapters("champion", db_path=db_path)
    # I1: base immutability.
    for a in adapters:
        if a.get("base_model") and a["base_model"] != config.OLLAMA_MODEL:
            violations.append(f"I1: adapter {a['tag']} base {a['base_model']} != {config.OLLAMA_MODEL}")
    # I4: at most one champion adapter per role.
    for role, c in Counter(a.get("role", "all") for a in adapters).items():
        if c > 1:
            violations.append(f"I4: {c} champion adapters for role '{role}'")
    # I4: at most one champion prompt per role.
    for role in prompts.ROLES:
        champs = experience.fetch_variants(role, "champion", db_path=db_path)
        if len(champs) > 1:
            violations.append(f"I4: {len(champs)} champion prompts for role '{role}'")
    return violations


def kill_switch_active() -> bool:
    return bool(config.SIE_KILL_SWITCH)


def panic_to_stock(*, db_path: Optional[Path] = None) -> dict[str, int]:
    """Hard rollback: retire EVERY champion adapter so the active tag falls back to the
    frozen base for all roles. (Pair with setting SIE_KILL_SWITCH to freeze promotions.)"""
    n = len(experience.fetch_adapters("champion", db_path=db_path))
    experience.retire_champion_adapter(role=None, db_path=db_path)
    LOG.warning("panic_to_stock: retired %d champion adapter(s)", n)
    return {"retired": n}
