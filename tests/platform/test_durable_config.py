# tests/test_durable_config.py
"""Epic 1 durable-execution config flags exist with safe CODED defaults.

R12: the registry now genuinely layers .env over the coded defaults, and a
production install .env may legitimately enable these flags -- so the ships-dark
guarantee is asserted on the CODED defaults (env keys scrubbed), while the facade
exposure is asserted on the live values.
"""
import config
from platform_core.app_config.settings import EpicFlags


def test_epic1_flag_defaults(monkeypatch):
    for k in ("TRAJECTORY_ENABLED", "STEP_JOURNAL_ENABLED", "STEP_RESUME_ENABLED",
              "WORKTREE_ISOLATION_ENABLED", "COST_BUDGET_ENABLED", "COST_BUDGET_CEILING_USD"):
        monkeypatch.delenv(k, raising=False)
    flags = EpicFlags()   # coded defaults < (no env)
    # Additive observability: on by default (zero behavior change).
    assert flags.TRAJECTORY_ENABLED is True
    assert flags.STEP_JOURNAL_ENABLED is True
    # Behavior-changing units ship dark: OFF by default.
    assert flags.STEP_RESUME_ENABLED is False
    assert flags.WORKTREE_ISOLATION_ENABLED is False
    assert flags.COST_BUDGET_ENABLED is False
    assert flags.COST_BUDGET_CEILING_USD == 0.0   # 0 = no ceiling


def test_epic1_flags_exposed_via_facade():
    for name in ("TRAJECTORY_ENABLED", "STEP_JOURNAL_ENABLED", "STEP_RESUME_ENABLED",
                 "WORKTREE_ISOLATION_ENABLED", "COST_BUDGET_ENABLED"):
        assert isinstance(getattr(config, name), bool)
    assert isinstance(config.COST_BUDGET_CEILING_USD, float)
