from learning import sie


def test_maintenance_steps_includes_insight():
    names = [name for name, _ in sie._maintenance_steps(None)]
    assert "insight" in names
