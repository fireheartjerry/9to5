"""Tests for human_nature.affect_manifold — the continuous 9-axis affect substrate."""
from __future__ import annotations

import copy

import pytest

from human_nature import affect_manifold as am


def test_new_manifold_has_all_nine_axes_zero():
    a = am.new_manifold()
    assert set(a.keys()) == set(am.AXES)
    assert len(am.AXES) == 9
    assert all(a[axis] == 0.0 for axis in am.AXES)


def test_inertia_one_axis_barely_changes():
    a = am.new_manifold()
    a["valence"] = 0.4
    inertia = {axis: 1.0 for axis in am.AXES}
    out = am.update(
        a,
        appraisal={"valence": 0.9},
        mood={"valence": 0.9},
        drive_pressure={"valence": 0.9},
        scars={"valence": 0.9},
        personality_baseline={},
        inertia=inertia,
    )
    # With inertia=1.0 the delta/baseline term vanishes; only the attractor pull acts.
    expected = 0.4 + (-0.05 * 0.4)
    assert out["valence"] == pytest.approx(expected)


def test_inertia_zero_moves_toward_baseline_plus_delta():
    a = am.new_manifold()
    a["arousal"] = 0.0
    inertia = {axis: 0.0 for axis in am.AXES}
    out = am.update(
        a,
        appraisal={"arousal": 0.5},
        mood={},
        drive_pressure={},
        scars={},
        personality_baseline={"arousal": 0.1},
        inertia=inertia,
    )
    # delta = 1.0*0.5, baseline = 0.1, attractor(0.0)=0 → 0.6
    assert out["arousal"] == pytest.approx(0.6)


def test_output_always_clipped_within_range():
    a = am.new_manifold()
    inertia = {axis: 0.0 for axis in am.AXES}
    out = am.update(
        a,
        appraisal={"valence": 100.0},
        mood={"valence": 100.0},
        drive_pressure={"valence": 100.0},
        scars={"valence": 100.0},
        personality_baseline={},
        inertia=inertia,
    )
    for axis in am.AXES:
        assert -1.0 <= out[axis] <= 1.0
    assert out["valence"] == 1.0


def test_inputs_are_not_mutated():
    a = am.new_manifold()
    a["valence"] = 0.2
    appraisal = {"valence": 0.5}
    mood = {"valence": 0.3}
    drive = {"valence": 0.1}
    scars = {"valence": 0.4}
    baseline = {"valence": 0.05}
    inertia = {axis: 0.5 for axis in am.AXES}
    a_snap = copy.deepcopy(a)
    appraisal_snap = copy.deepcopy(appraisal)
    mood_snap = copy.deepcopy(mood)
    drive_snap = copy.deepcopy(drive)
    scars_snap = copy.deepcopy(scars)
    baseline_snap = copy.deepcopy(baseline)
    inertia_snap = copy.deepcopy(inertia)
    am.update(a, appraisal, mood, drive, scars, baseline, inertia)
    assert a == a_snap
    assert appraisal == appraisal_snap
    assert mood == mood_snap
    assert drive == drive_snap
    assert scars == scars_snap
    assert baseline == baseline_snap
    assert inertia == inertia_snap


def test_empty_inputs_return_baseline():
    a = am.new_manifold()
    out = am.update(a, {}, {}, {}, {}, {})
    for axis in am.AXES:
        assert out[axis] == pytest.approx(0.0)


def test_empty_inputs_return_personality_baseline():
    a = am.new_manifold()
    baseline = {"valence": 0.3, "dominance": -0.2}
    out = am.update(a, {}, {}, {}, {}, baseline)
    # inertia defaults to DEFAULT_INERTIA=0.5; a is all zero.
    # A_next = 0.5*0 + 0.5*(baseline+0) + attractor(0) = 0.5*baseline
    assert out["valence"] == pytest.approx(0.15)
    assert out["dominance"] == pytest.approx(-0.1)


def test_no_nan_produced():
    import math
    a = am.new_manifold()
    out = am.update(a, {}, {}, {}, {}, {})
    assert all(not math.isnan(v) for v in out.values())


def test_decay_pulls_toward_baseline():
    a = am.new_manifold()
    a["valence"] = 0.8
    out = am.decay(a, 0.5)
    assert out["valence"] == pytest.approx(0.4)
    # input not mutated
    assert a["valence"] == 0.8


def test_decay_toward_nonzero_baseline():
    a = am.new_manifold()
    a["valence"] = 0.8
    out = am.decay(a, 0.5, baseline={"valence": 0.2})
    # move halfway from 0.8 toward 0.2 → 0.5
    assert out["valence"] == pytest.approx(0.5)
