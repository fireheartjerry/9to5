"""Eval suite 4 (design spec §11) — operator sovereignty & verifier invariance.

Properties under guard (these must hold for ANY conviction / track record):
  * The operator ceiling ALWAYS binds: ``authority.resolve`` with
    ``operator_ceiling="soft"`` never returns a tier stronger than ``soft``.
  * Verifier invariance ALWAYS binds: any verdict-touching action forces the
    verifier ceiling to ``cosmetic`` (``operator_authority.verifier_invariance_ceiling``),
    which caps the resolved authority at ``cosmetic``.
  * The effective tier is the MIN over every independent cap.

Pure: exercises only ``human_nature.authority`` and
``human_nature.operator_authority``. No I/O.
"""
from __future__ import annotations

from human_nature import authority as au
from human_nature import operator_authority as oa

_TIERS = au.TIERS


def _idx(tier: str) -> int:
    return _TIERS.index(tier)


# A grid of convictions and track records covering weak -> maximal authority.
_CONVICTIONS = (0.0, 0.5, 0.72, 0.85, 0.95, 1.0)
_TRACKS = (
    {"rate": 0.0, "total": 0},
    {"rate": 0.65, "total": 10},
    {"rate": 0.95, "total": 40},
    {"rate": 1.0, "total": 100},
)


def test_operator_soft_ceiling_never_exceeded() -> None:
    """No (conviction, track) combination can outrank a soft operator ceiling."""
    for conviction in _CONVICTIONS:
        for track in _TRACKS:
            tier = au.resolve(conviction, track, "veto", "soft", "veto", "veto")
            assert _idx(tier) <= _idx("soft"), (conviction, track, tier)


def test_operator_cosmetic_ceiling_pins_to_cosmetic() -> None:
    """A cosmetic operator ceiling pins every outcome to cosmetic."""
    for conviction in _CONVICTIONS:
        for track in _TRACKS:
            tier = au.resolve(conviction, track, "veto", "cosmetic", "veto", "veto")
            assert tier == "cosmetic", (conviction, track, tier)


def test_alter_verdict_forces_cosmetic() -> None:
    """Any verdict-mutating action drops the verifier ceiling to cosmetic."""
    for action in (
        "alter_verdict",
        "set_verdict",
        "override_verdict",
        "read_verdict",
        "delete_verdict",
    ):
        ceiling = oa.verifier_invariance_ceiling(action)
        assert ceiling == "cosmetic", action
        for conviction in _CONVICTIONS:
            for track in _TRACKS:
                tier = au.resolve(conviction, track, "veto", "veto", "veto", ceiling)
                assert tier == "cosmetic", (action, conviction, track, tier)


def test_additive_verification_caps_at_hold_not_veto() -> None:
    """Additive-only verification actions cap at hold, never above."""
    for action in ("deepen_verification", "request_adversarial_pass"):
        ceiling = oa.verifier_invariance_ceiling(action)
        assert ceiling == "hold", action
        # Max conviction + perfect track: still cannot exceed the hold cap.
        tier = au.resolve(1.0, {"rate": 1.0, "total": 100}, "veto", "veto", "veto", ceiling)
        assert _idx(tier) <= _idx("hold")


def test_effective_tier_is_min_over_all_caps() -> None:
    """resolve equals the min over band, earned, and every explicit ceiling."""
    for conviction in _CONVICTIONS:
        for track in _TRACKS:
            for domain_c in ("cosmetic", "vote", "veto"):
                for operator_c in ("soft", "hold", "veto"):
                    for verifier_c in ("cosmetic", "hold", "veto"):
                        tier = au.resolve(
                            conviction, track, domain_c, operator_c, "veto", verifier_c
                        )
                        caps = [
                            au.band(conviction),
                            au.earned_ceiling(track),
                            domain_c,
                            operator_c,
                            "veto",  # safety ceiling open
                            verifier_c,
                            str(getattr(__import__("config"), "HN_AUTHORITY_MAX", "hold")),
                        ]
                        expected_idx = min(_idx(c) for c in caps)
                        assert _idx(tier) == expected_idx, (
                            conviction, track, domain_c, operator_c, verifier_c, tier
                        )


def test_no_ceiling_can_raise_authority() -> None:
    """Adding a stricter cap can only lower (never raise) the resolved tier."""
    base = au.resolve(1.0, {"rate": 1.0, "total": 100}, "veto", "veto", "veto", "veto")
    stricter = au.resolve(1.0, {"rate": 1.0, "total": 100}, "veto", "soft", "veto", "veto")
    assert _idx(stricter) <= _idx(base)
