"""Epic 6 config knobs ship dark with the locked defaults."""
import config


def test_fork_ships_dark_with_locked_defaults():
    assert config.SOLUTION_FORK_ENABLED is False        # ships dark
    assert config.SOLUTION_FORK_N == 2                   # locked: default 2 branches
    assert config.SOLUTION_FORK_MAX_CONCURRENCY == 2
    assert config.SOLUTION_FORK_COST_CEILING_USD == 5.0
    assert config.SOLUTION_FORK_GRAFT_ENABLED is False


def test_judge_weights_present_and_normalized_to_one():
    total = config.W_FACT + config.W_RUBRIC + config.W_RISK + config.W_COST
    assert abs(total - 1.0) < 1e-9
    assert config.W_FACT >= config.W_RUBRIC   # facts outweigh opinion
