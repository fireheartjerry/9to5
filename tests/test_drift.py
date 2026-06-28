from human_nature.drift import measure_drift, has_drifted

def test_empty_window_is_no_drift():
    assert measure_drift([], 0.5) == 0.0

def test_aligned_window_is_no_drift():
    assert measure_drift([0.5, 0.5, 0.5], 0.5) == 0.0

def test_drift_is_mean_abs_deviation_capped_at_one():
    assert abs(measure_drift([0.2, 0.8], 0.5) - 0.3) < 1e-9
    assert measure_drift([5.0], 0.0) == 1.0  # capped

def test_has_drifted_threshold():
    assert has_drifted([0.9, 0.9], 0.5, threshold=0.3) is True
    assert has_drifted([0.55], 0.5, threshold=0.3) is False
