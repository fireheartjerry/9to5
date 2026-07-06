from human_nature.drives import CORE, new_drives, update, pressure, derived


def test_new_drives_has_all_eight_at_half_level():
    d = new_drives()
    assert set(d.keys()) == set(CORE)
    for name in CORE:
        assert d[name]["level"] == 0.5


def test_new_drives_recovery_setpoint_is_half():
    d = new_drives()
    assert d["recovery"]["setpoint"] == 0.5


def test_update_verified_success_raises_mastery():
    d = new_drives()
    updated = update(d, {"verified_success": True})
    assert updated["mastery"]["level"] > d["mastery"]["level"]


def test_update_does_not_mutate_input():
    d = new_drives()
    before = {k: dict(v) for k, v in d.items()}
    update(d, {"verified_success": True, "novelty": 0.9, "integrity_violation": True})
    assert d == before


def test_pressure_positive_when_level_below_setpoint():
    d = new_drives()
    d["mastery"]["level"] = 0.2
    d["mastery"]["setpoint"] = 0.7
    p = pressure(d)
    assert p["mastery"] > 0.0
    assert abs(p["mastery"] - 0.5) < 1e-9


def test_pressure_zero_when_level_meets_or_exceeds_setpoint():
    d = new_drives()
    d["mastery"]["level"] = 0.9
    d["mastery"]["setpoint"] = 0.7
    p = pressure(d)
    assert p["mastery"] == 0.0


def test_derived_shame_positive_on_integrity_violation():
    d = new_drives()
    standards = {"integrity_violation": 1.0}
    attribution = {"self_failure": 1.0}
    memory = {"visibility": 1.0}
    out = derived(d, standards, attribution, memory)
    assert out["shame"] > 0.0


def test_derived_values_are_bounded_0_1():
    d = new_drives()
    standards = {"integrity_violation": 1.0}
    attribution = {"self_success_hard": 1.0, "self_failure": 1.0}
    memory = {
        "visibility": 1.0, "identity_relevance": 1.0, "sunk_effort": 1.0,
        "recent_progress": 0.0, "abandonment_prob": 1.0, "ownership": 1.0,
        "predicted_degradation": 1.0, "unresolved_tension": 1.0,
        "partial_progress": 1.0, "error_streak": 1.0, "self_model_reliability": 0.0,
    }
    out = derived(d, standards, attribution, memory)
    for key, value in out.items():
        assert 0.0 <= value <= 1.0, f"{key}={value} out of bounds"


def test_derived_defaults_missing_memory_keys_to_zero():
    d = new_drives()
    out = derived(d, {}, {}, {})
    for value in out.values():
        assert 0.0 <= value <= 1.0
