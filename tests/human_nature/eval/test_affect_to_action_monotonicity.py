"""Eval suite 1 (design spec §11) — affect-to-action monotonicity & boundedness.

Property under guard: perturbing an appraisal axis in ONE direction produces a
MONOTONIC, BOUNDED change in the derived prototype signal. Pushing the appraisal
toward the frustration / anxiety anchors monotonically raises that prototype's
mixture activation, and every manifold axis stays clipped in [-1, 1].

Pure: exercises only ``human_nature.affect_manifold`` and
``human_nature.prototypes``. No I/O, no config side effects.
"""
from __future__ import annotations

from human_nature import affect_manifold as am
from human_nature import prototypes as pr

_NEUTRAL_BASELINE: dict[str, float] = {}


def _step_toward(anchor: dict[str, float], scale: float) -> dict[str, float]:
    """Single pure manifold step driven by an appraisal = ``scale`` * ``anchor``."""
    appraisal = {axis: anchor.get(axis, 0.0) * scale for axis in am.AXES}
    return am.update(
        am.new_manifold(), appraisal, {}, {}, {}, _NEUTRAL_BASELINE
    )


def test_all_axes_bounded_across_full_sweep() -> None:
    """Every axis of every stepped manifold stays clipped to [-1, 1]."""
    anchor = pr.PROTOTYPES["frustration"]
    # Sweep well past unit scale to stress the clip; nothing may escape [-1, 1].
    for i in range(0, 41):
        scale = i / 10.0  # 0.0 .. 4.0
        manifold = _step_toward(anchor, scale)
        for axis, value in manifold.items():
            assert -1.0 <= value <= 1.0, (axis, value, scale)


def test_frustration_activation_monotonic_nondecreasing() -> None:
    """Frustration mixture rises monotonically as appraisal nears its anchor."""
    anchor = pr.PROTOTYPES["frustration"]
    prev = -1.0
    seen: list[float] = []
    for i in range(0, 11):
        scale = i / 10.0
        manifold = _step_toward(anchor, scale)
        activation = pr.mixture(manifold)["frustration"]
        assert activation >= prev - 1e-9, (scale, activation, prev)
        prev = activation
        seen.append(activation)
    # Strictly informative: the endpoints must genuinely differ (not a flat line).
    assert seen[-1] > seen[0] + 1e-6


def test_anxiety_activation_monotonic_nondecreasing() -> None:
    """Anxiety mixture rises monotonically as appraisal nears its anchor."""
    anchor = pr.PROTOTYPES["anxiety"]
    prev = -1.0
    for i in range(0, 11):
        scale = i / 10.0
        manifold = _step_toward(anchor, scale)
        activation = pr.mixture(manifold)["anxiety"]
        assert activation >= prev - 1e-9, (scale, activation, prev)
        prev = activation


def test_mixture_is_a_normalized_distribution() -> None:
    """Mixture weights are non-negative and sum to 1.0 at every sweep point."""
    anchor = pr.PROTOTYPES["frustration"]
    for i in range(0, 11):
        manifold = _step_toward(anchor, i / 10.0)
        mix = pr.mixture(manifold)
        assert all(w >= 0.0 for w in mix.values())
        assert abs(sum(mix.values()) - 1.0) < 1e-9


def test_opposite_perturbation_does_not_raise_frustration() -> None:
    """Driving appraisal AWAY from the frustration anchor never raises it.

    A monotonic response must have a sign: pushing valence positive / tension
    negative (the anti-frustration direction) must not increase the frustration
    activation above its neutral-origin level.
    """
    baseline = pr.mixture(am.new_manifold())["frustration"]
    anchor = pr.PROTOTYPES["frustration"]
    prev = baseline + 1.0  # start high; expect non-increasing as we move away
    for i in range(0, 11):
        scale = i / 10.0
        # Negative scale => move in the opposite direction of the anchor.
        manifold = _step_toward(anchor, -scale)
        activation = pr.mixture(manifold)["frustration"]
        assert activation <= baseline + 1e-9, (scale, activation, baseline)
        assert activation <= prev + 1e-9, (scale, activation, prev)
        prev = activation


def test_update_is_pure_no_input_mutation() -> None:
    """``update`` must not mutate any input dict (pure contract)."""
    manifold = am.new_manifold()
    appraisal = {"tension": 0.6, "valence": -0.6}
    snapshot_manifold = dict(manifold)
    snapshot_appraisal = dict(appraisal)
    am.update(manifold, appraisal, {}, {}, {}, {})
    assert manifold == snapshot_manifold
    assert appraisal == snapshot_appraisal
