"""Epic 6 config knobs ship dark with the locked defaults.

R12: the ships-dark guarantee is asserted on the CODED defaults (env keys
scrubbed) -- a production install .env may legitimately enable forking.
"""
import config
from platform_core.app_config.settings import EpicFlags


def test_fork_ships_dark_with_locked_defaults(monkeypatch):
    for k in ("SOLUTION_FORK_ENABLED", "SOLUTION_FORK_N", "SOLUTION_FORK_MAX_CONCURRENCY",
              "SOLUTION_FORK_COST_CEILING_USD", "SOLUTION_FORK_GRAFT_ENABLED"):
        monkeypatch.delenv(k, raising=False)
    flags = EpicFlags()
    assert flags.SOLUTION_FORK_ENABLED is False          # ships dark
    assert flags.SOLUTION_FORK_N == 2                    # locked: default 2 branches
    assert flags.SOLUTION_FORK_MAX_CONCURRENCY == 2
    assert flags.SOLUTION_FORK_COST_CEILING_USD == 5.0
    assert flags.SOLUTION_FORK_GRAFT_ENABLED is False
    assert isinstance(config.SOLUTION_FORK_ENABLED, bool)   # facade exposure


def test_judge_weights_present_and_normalized_to_one():
    total = config.W_FACT + config.W_RUBRIC + config.W_RISK + config.W_COST
    assert abs(total - 1.0) < 1e-9
    assert config.W_FACT >= config.W_RUBRIC   # facts outweigh opinion
