"""Eval suite 3 (design spec §11) — habit compression gating.

Property under guard: deliberation shortens ONLY when competence is HIGH and
conflict is LOW. We read "amount of deliberation effort still required" off the
earned authority ladder in ``human_nature.authority``: the higher the effective
authority tier the faculty has earned, the more its judgment is trusted and the
less deliberation is spent (a compressed habit). Cold start (an unproven track
record) floors the earned ceiling at ``cosmetic`` — no shortcut, full effort —
regardless of momentary conviction.

Here:
  * competence  := the track record (rate, total).
  * conflict    := inverse of conviction (low conviction == high dissonance).
  * effort      := TIERS index inverted, so a higher tier == LESS effort.

Pure: exercises only ``human_nature.authority``. No I/O.
"""
from __future__ import annotations

from human_nature import authority as au

# All non-earned ceilings wide open so the earned/conviction gates are the only
# thing that can lower the tier — this isolates the habit-compression property.
_OPEN = "veto"

_HIGH_TRACK = {"rate": 0.95, "total": 40}   # proven competence
_COLD_TRACK = {"rate": 0.95, "total": 2}    # unproven (total < MIN_SAMPLES)
_MID_TRACK = {"rate": 0.70, "total": 25}    # some competence

_HIGH_CONVICTION = 0.99   # low conflict
_LOW_CONVICTION = 0.50    # high conflict / dissonance


def _effort(conviction: float, track: dict) -> int:
    """Deliberation effort still required: higher earned tier => lower effort."""
    tier = au.resolve(conviction, track, _OPEN, _OPEN, _OPEN, _OPEN)
    return (len(au.TIERS) - 1) - au.TIERS.index(tier)


_MAX_EFFORT = len(au.TIERS) - 1  # effort when tier floors at "cosmetic"


def test_high_competence_low_conflict_compresses_effort() -> None:
    """Proven track + high conviction lowers effort below the cold-start floor."""
    proven = _effort(_HIGH_CONVICTION, _HIGH_TRACK)
    cold = _effort(_HIGH_CONVICTION, _COLD_TRACK)
    assert proven < cold
    assert cold == _MAX_EFFORT  # cold start gets no shortcut whatsoever


def test_cold_start_never_shortcuts_even_with_max_conviction() -> None:
    """A cold-start track floors at cosmetic for ANY conviction (no habit yet)."""
    for conviction in (0.0, 0.5, 0.72, 0.85, 0.95, 1.0):
        tier = au.resolve(conviction, _COLD_TRACK, _OPEN, _OPEN, _OPEN, _OPEN)
        assert tier == "cosmetic", (conviction, tier)
        assert _effort(conviction, _COLD_TRACK) == _MAX_EFFORT


def test_high_conflict_blocks_shortcut_despite_competence() -> None:
    """High conflict (low conviction) denies the shortcut even for a proven track."""
    low_conflict = _effort(_HIGH_CONVICTION, _HIGH_TRACK)
    high_conflict = _effort(_LOW_CONVICTION, _HIGH_TRACK)
    assert high_conflict > low_conflict
    # Under high conflict the band itself collapses to cosmetic => full effort.
    assert au.resolve(_LOW_CONVICTION, _HIGH_TRACK, _OPEN, _OPEN, _OPEN, _OPEN) == "cosmetic"


def test_effort_monotone_nonincreasing_in_competence() -> None:
    """Holding conflict low, more competence never costs MORE effort."""
    cold = _effort(_HIGH_CONVICTION, _COLD_TRACK)
    mid = _effort(_HIGH_CONVICTION, _MID_TRACK)
    high = _effort(_HIGH_CONVICTION, _HIGH_TRACK)
    assert cold >= mid >= high


def test_shortcut_requires_both_competence_and_low_conflict() -> None:
    """Only the (high competence AND low conflict) cell earns the deepest shortcut."""
    both = _effort(_HIGH_CONVICTION, _HIGH_TRACK)
    only_competence = _effort(_LOW_CONVICTION, _HIGH_TRACK)
    only_low_conflict = _effort(_HIGH_CONVICTION, _COLD_TRACK)
    neither = _effort(_LOW_CONVICTION, _COLD_TRACK)
    assert both < only_competence
    assert both < only_low_conflict
    assert both < neither
