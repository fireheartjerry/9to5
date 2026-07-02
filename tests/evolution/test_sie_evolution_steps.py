from learning import sie


def test_weekly_steps_include_evolution_steps():
    names = [name for name, _ in sie._weekly_steps(None)]
    for n in ("evolve", "evolve_promote", "curate"):
        assert n in names
