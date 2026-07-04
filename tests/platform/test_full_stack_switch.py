"""FULL_STACK master switch: the default SOURCE for every dark epic flag + Human-Nature.
Tested at the default_factory level so a live env file pinning a flag can't mask the mechanism."""

from platform_core.app_config import _env
from platform_core.app_config.settings import EpicFlags


def _f(name):
    return EpicFlags.__dataclass_fields__[name].default_factory


def test_fullstack_defaults_on(monkeypatch):
    monkeypatch.delenv("FULL_STACK", raising=False)
    assert _env._fullStack() is True


def test_fullstack_off(monkeypatch):
    monkeypatch.setenv("FULL_STACK", "0")
    assert _env._fullStack() is False


def test_master_enables_dark_flags(monkeypatch):
    monkeypatch.setenv("FULL_STACK", "1")
    for k in (
        "WORKTREE_ISOLATION_ENABLED",
        "EXECUTION_FABRIC_ENABLED",
        "SOCIETY_ENABLED",
        "SOLUTION_FORK_ENABLED",
        "DUAL_LEDGER_PLANNER_ENABLED",
        "HUMAN_NATURE_ENABLED",
    ):
        monkeypatch.delenv(k, raising=False)
        assert _f(k)() is True, k


def test_master_off_reverts_dark_flags(monkeypatch):
    monkeypatch.setenv("FULL_STACK", "0")
    for k in ("WORKTREE_ISOLATION_ENABLED", "EXECUTION_FABRIC_ENABLED", "SOCIETY_ENABLED"):
        monkeypatch.delenv(k, raising=False)
        assert _f(k)() is False, k


def test_individual_env_overrides_master(monkeypatch):
    monkeypatch.setenv("FULL_STACK", "1")
    monkeypatch.setenv("SOCIETY_ENABLED", "0")
    assert _f("SOCIETY_ENABLED")() is False


def test_backend_defaults_worktree_under_master(monkeypatch):
    monkeypatch.setenv("FULL_STACK", "1")
    monkeypatch.delenv("EXECUTION_BACKEND", raising=False)
    assert _f("EXECUTION_BACKEND")() == "worktree"
    monkeypatch.setenv("FULL_STACK", "0")
    assert _f("EXECUTION_BACKEND")() == "local"
