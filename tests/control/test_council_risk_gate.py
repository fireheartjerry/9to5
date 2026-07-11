from platform_core.runtime.control import GATES


def test_council_risk_is_a_real_control_bus_gate():
    assert "council_risk" in GATES
