import pytest
from human_nature.conviction import recalibrate, track_weight, compute_conviction

def test_recalibrate_pulls_extremes_toward_center():
    # temperature scaling (T>1) reduces overconfidence: 0.95 -> lower
    assert recalibrate(0.95, temperature=2.5) < 0.95
    assert abs(recalibrate(0.5, temperature=2.5) - 0.5) < 1e-9  # 0.5 stays 0.5

def test_cold_start_gives_no_teeth():
    # below MIN_SAMPLES, track contributes zero weight
    assert track_weight({"rate": 0.9, "total": 3}) == 0.0

def test_track_weight_uses_rate_when_seasoned():
    assert track_weight({"rate": 0.8, "total": 50}) == 0.8

def test_compute_conviction_is_momentary_times_track():
    track = {"rate": 1.0, "total": 50}      # full track, no recal scaling on history
    c = compute_conviction(0.5, track, recal=False)  # 0.5 * 1.0
    assert abs(c - 0.5) < 1e-9

def test_compute_conviction_zero_on_cold_start():
    assert compute_conviction(0.99, {"rate": 0.99, "total": 1}) == 0.0

def test_recalibrate_rejects_nonpositive_temperature():
    with pytest.raises(ValueError):
        recalibrate(0.5, temperature=0.0)
    with pytest.raises(ValueError):
        recalibrate(0.5, temperature=-1.0)
