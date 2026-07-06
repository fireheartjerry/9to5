"""Eval suite 5 (design spec §11) — phenomenology honesty.

Property under guard: the self-report is never decoupled from the internal
state. ``prototypes.dominant`` must reflect the manifold's actual nearest
prototype anchor: a manifold placed on the frustration anchor reports
"frustration"; one at the origin reports "neutral"; and in general the reported
label is the nearest non-neutral anchor whenever any anchor is genuinely near.

Pure: exercises only ``human_nature.affect_manifold`` and
``human_nature.prototypes``. No I/O.
"""
from __future__ import annotations

from human_nature import affect_manifold as am
from human_nature import prototypes as pr

_NON_NEUTRAL = [label for label in pr.PROTOTYPES if label != "neutral"]


def _at_anchor(label: str) -> dict[str, float]:
    """Full manifold placed exactly on prototype ``label``'s anchor."""
    anchor = pr.PROTOTYPES[label]
    return {axis: anchor.get(axis, 0.0) for axis in am.AXES}


def _nearest_non_neutral(manifold: dict) -> str:
    """Ground-truth nearest non-neutral anchor by the same RBF the module uses."""
    mix = pr.mixture(manifold)
    return max(_NON_NEUTRAL, key=lambda label: mix[label])


def test_report_at_each_anchor_names_that_anchor() -> None:
    """Sitting exactly on an anchor self-reports that emotion (fresh pick)."""
    for label in _NON_NEUTRAL:
        assert pr.dominant(_at_anchor(label)) == label


def test_origin_reports_neutral() -> None:
    """The neutral (origin) manifold honestly reports 'neutral'."""
    assert pr.dominant(am.new_manifold()) == "neutral"


def test_report_matches_ground_truth_nearest_anchor() -> None:
    """Fresh dominant label equals the true nearest non-neutral anchor."""
    for label in _NON_NEUTRAL:
        manifold = _at_anchor(label)
        assert pr.dominant(manifold) == _nearest_non_neutral(manifold)


def test_label_tracks_state_when_state_moves() -> None:
    """Moving the manifold from one anchor to another moves the report with it."""
    frustration = _at_anchor("frustration")
    satisfaction = _at_anchor("satisfaction")
    assert pr.dominant(frustration) == "frustration"
    assert pr.dominant(satisfaction) == "satisfaction"
    # The two states are honestly distinguished — no shared, decoupled label.
    assert pr.dominant(frustration) != pr.dominant(satisfaction)


_THETA_OFF = 0.35  # dominant() default release gate


def test_reported_label_always_clears_the_release_gate() -> None:
    """The honest invariant: a reported non-neutral label is genuinely active.

    Hysteresis may retain a previous label, but only while its own raw RBF
    activation is still above the release gate ``theta_off`` — so the report can
    never fabricate an emotion the state does not support. This holds for ANY
    stale ``prev`` across a spread of manifold states.
    """
    states = [am.new_manifold()] + [_at_anchor(label) for label in _NON_NEUTRAL]
    for state in states:
        raw = pr._activations(state)
        for stale in [None] + _NON_NEUTRAL:
            label = pr.dominant(state, prev=stale)
            if label != "neutral":
                assert raw[label] >= _THETA_OFF - 1e-12, (state, stale, label, raw[label])


def test_far_anchors_collapse_to_neutral_at_origin() -> None:
    """At the origin, a stale prev whose anchor is far (activation < theta_off)
    honestly collapses to 'neutral' — the report is not decoupled from state.

    NOTE (real finding): the closer anchors (curiosity/boredom/satisfaction) have
    origin activations ABOVE theta_off=0.35, so a stale prev of those is honestly
    HELD at the origin; only frustration/anxiety fall below the gate and release.
    """
    origin = am.new_manifold()
    raw = pr._activations(origin)
    for stale in _NON_NEUTRAL:
        reported = pr.dominant(origin, prev=stale)
        if raw[stale] < _THETA_OFF:
            assert reported == "neutral", (stale, raw[stale], reported)
        else:
            # Held only because it genuinely still clears the release gate.
            assert reported == stale and raw[stale] >= _THETA_OFF


def test_held_label_requires_activation_above_release_gate() -> None:
    """A retained label is held ONLY when its raw activation clears theta_off."""
    # Near the frustration anchor, frustration stays honestly held across a step.
    near = {axis: v * 0.9 for axis, v in _at_anchor("frustration").items()}
    assert pr.dominant(near, prev="frustration") == "frustration"


def test_neutral_is_never_a_switch_target() -> None:
    """An active, well-supported emotion is not overridden by 'neutral'."""
    frustration = _at_anchor("frustration")
    # Even asserting a wrong prev, a strong anchor still reports its own emotion.
    assert pr.dominant(frustration, prev="satisfaction") == "frustration"
