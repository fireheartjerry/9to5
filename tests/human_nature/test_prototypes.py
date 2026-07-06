"""Tests for human_nature.prototypes — discrete emotion projection with hysteresis."""
from __future__ import annotations

import math

import pytest

from human_nature import prototypes as proto


def _m(**kw) -> dict:
    """Build a full manifold dict (all axes, zero default) with overrides."""
    a = {ax: 0.0 for ax in proto.AXES}
    a.update(kw)
    return a


def _anchor(label: str) -> dict:
    """Materialize a prototype anchor as a full manifold dict."""
    return _m(**proto.PROTOTYPES[label])


# --------------------------------------------------------------------------
# mixture
# --------------------------------------------------------------------------
def test_mixture_sums_to_one():
    a = _m(valence=-0.3, arousal=0.2, tension=0.4)
    mix = proto.mixture(a)
    assert isinstance(mix, dict)
    assert set(mix) == set(proto.PROTOTYPES)
    assert math.isclose(sum(mix.values()), 1.0, rel_tol=0.0, abs_tol=1e-9)
    assert all(v >= 0.0 for v in mix.values())


# --------------------------------------------------------------------------
# dominant — anchor identity
# --------------------------------------------------------------------------
def test_dominant_at_frustration_anchor():
    assert proto.dominant(_anchor("frustration")) == "frustration"


def test_dominant_far_from_all_is_neutral():
    # A point far from every non-neutral anchor: extreme on axes no anchor uses.
    far = _m(social_exposure=1.0, cognitive_load=1.0, agency=1.0)
    assert proto.dominant(far) == "neutral"


# --------------------------------------------------------------------------
# dominant — hysteresis (no flicker)
# --------------------------------------------------------------------------
def test_hysteresis_holds_prev_between_thresholds():
    # Nudge the anxiety anchor partway toward neutral so anxiety's raw
    # activation lands in (theta_off, theta_on): below the switch-on gate but
    # above the release gate.  With prev="anxiety" we must NOT flicker away.
    anchor = _anchor("anxiety")
    nudged = {ax: 0.2 * v for ax, v in anchor.items()}

    # Precondition: fresh classification (no prev) would drop to neutral,
    # because no prototype clears theta_on at this point.
    assert proto.dominant(nudged) == "neutral"

    # With hysteresis, the active label is retained.
    assert proto.dominant(nudged, prev="anxiety") == "anxiety"


def test_hysteresis_switches_when_new_clears_theta_on():
    # Strong frustration signal must override a stale prev.
    assert proto.dominant(_anchor("frustration"), prev="boredom") == "frustration"
