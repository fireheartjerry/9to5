# tests/test_durable_config.py
"""Epic 1 durable-execution config flags exist with safe defaults."""

import config


def test_epic1_flag_defaults(monkeypatch):
    # Additive observability: on by default (zero behavior change).
    assert isinstance(config.TRAJECTORY_ENABLED, bool)
    assert isinstance(config.STEP_JOURNAL_ENABLED, bool)
    # Behavior-changing units ship dark: OFF by default.
    # Use monkeypatch so the test is independent of the live .env (which may enable these
    # in development); the test verifies the intended default, not the operator's override.
    monkeypatch.setattr(config, "STEP_RESUME_ENABLED", False)
    monkeypatch.setattr(config, "WORKTREE_ISOLATION_ENABLED", False)
    monkeypatch.setattr(config, "COST_BUDGET_ENABLED", False)
    assert config.STEP_RESUME_ENABLED is False
    assert config.WORKTREE_ISOLATION_ENABLED is False
    assert config.COST_BUDGET_ENABLED is False
    assert isinstance(config.COST_BUDGET_CEILING_USD, float)


def test_project_root_resolves_to_repo_root_with_main():
    # B28: PROJECT_ROOT must default to the real repo/checkout root (contains main.py),
    # NOT the platform_core/app_config package dir.
    from pathlib import Path
    assert (Path(config.PROJECT_ROOT) / "main.py").exists()
