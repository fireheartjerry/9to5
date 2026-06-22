"""Prompt registry -- Layer 3 substrate of the Self-Improvement Engine.

The brain's system prompts stop being frozen module constants and become *versioned
variants* the system can evolve and promote. Safety/zero-risk property: ``get(role,
default)`` returns the in-code constant byte-for-byte until a challenger is actually
promoted to champion -- so wiring this in changes nothing until the evidence says to.

See the spec (Layer 3) + learning/promotion.py for the champion/challenger gate.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import config
from memory import experience

LOG = config.getLogger("sie.prompts")

# Roles whose system prompts can evolve. Names are stable keys, not import paths.
ROLES = ("orchestrator", "planner", "replanner", "elaborator", "adversary", "architect")


def get(role: str, default: str, *, db_path: Optional[Path] = None) -> str:
    """Return the champion body for ``role``, or ``default`` if none is promoted yet.

    On first sight of a role we seed ``default`` as champion v1 (a versioned baseline),
    then return it -- guaranteeing byte-identical behavior until a real promotion happens.
    """
    try:
        champ = experience.get_champion_body(role, db_path=db_path)
        if champ is not None:
            return champ
        experience.register_variant(role, default, state="champion", db_path=db_path)
    except Exception as e:  # noqa: BLE001 -- registry must never break the brain
        LOG.debug("prompts.get fell back to default for %s: %s", role, e)
    return default


def champion_id(role: str, default: Optional[str] = None,
                db_path: Optional[Path] = None) -> Optional[int]:
    """The current champion variant id for ``role`` (seeding ``default`` if needed)."""
    try:
        champ = experience.get_champion(role, db_path=db_path)
        if champ:
            return int(champ["id"])
        if default is not None:
            return experience.register_variant(role, default, state="champion", db_path=db_path)
    except Exception as e:  # noqa: BLE001
        LOG.debug("champion_id failed for %s: %s", role, e)
    return None


def propose(role: str, body: str, *, db_path: Optional[Path] = None) -> Optional[int]:
    """Register a new challenger variant (child of the current champion)."""
    parent = experience.get_champion(role, db_path=db_path)
    return experience.register_variant(
        role, body, state="challenger",
        parent_id=parent["id"] if parent else None, db_path=db_path)


def promote(role: str, variant_id: int, *, db_path: Optional[Path] = None) -> bool:
    """Make a variant the champion (called only by the gated promotion path)."""
    return experience.promote_variant(role, variant_id, db_path=db_path)


def challengers(role: str, db_path: Optional[Path] = None) -> list[dict]:
    return experience.fetch_variants(role, state="challenger", db_path=db_path)
