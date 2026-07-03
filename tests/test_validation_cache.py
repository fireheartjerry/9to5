from __future__ import annotations

from unittest import mock

import config
from platform_core.orchestration import validation_cache as vc


def _cp(returncode: int = 0, stdout: str = "", stderr: str = ""):
    return mock.Mock(returncode=returncode, stdout=stdout, stderr=stderr)


def test_shared_prefix_is_reused_between_self_ref_and_pre_pr(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "VALIDATION_CACHE_DB_PATH", tmp_path / "validation.db", raising=False)
    monkeypatch.setattr(vc, "_state_key", lambda _wd: ("wd", "head", "root", "diff"))
    calls: list[list[str]] = []

    def fake_run(cmd, **_kwargs):  # noqa: ANN001
        calls.append(cmd)
        if cmd[1:] == ["tools\\affected_tests.py"]:
            return _cp(stdout="")
        return _cp(stdout="ok")

    monkeypatch.setattr(vc.subprocess, "run", fake_run)
    assert vc.run_validation_suite("self_ref_incremental", str(tmp_path)).ok
    assert vc.run_validation_suite("pre_pr_full", str(tmp_path)).ok

    suffixes = [cmd[1:] for cmd in calls]
    assert suffixes.count(["tools\\repo_map.py"]) == 1
    assert suffixes.count(["tools\\repo_map.py", "--check"]) == 1
    assert suffixes.count(["validate_workflows.py"]) == 1
    assert any(cmd[1:4] == ["-m", "pytest", "-m"] for cmd in calls)


def test_diff_change_invalidates_validation_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "VALIDATION_CACHE_DB_PATH", tmp_path / "validation.db", raising=False)
    diffs = iter(["diff-a", "diff-a", "diff-b"])
    monkeypatch.setattr(vc, "_state_key", lambda _wd: ("wd", "head", "root", next(diffs)))
    calls = 0

    def fake_run(cmd, **_kwargs):  # noqa: ANN001
        nonlocal calls
        calls += 1
        return _cp(stdout="")

    monkeypatch.setattr(vc.subprocess, "run", fake_run)
    assert vc.run_validation_suite("self_ref_incremental", str(tmp_path)).ok
    assert vc.run_validation_suite("self_ref_incremental", str(tmp_path)).ok
    first_state_calls = calls
    assert vc.run_validation_suite("self_ref_incremental", str(tmp_path)).ok
    assert calls > first_state_calls


def test_failed_node_preserves_detail(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "VALIDATION_CACHE_DB_PATH", tmp_path / "validation.db", raising=False)
    monkeypatch.setattr(vc, "_state_key", lambda _wd: ("wd", "head", "root", "diff"))
    monkeypatch.setattr(vc.subprocess, "run", lambda *_a, **_k: _cp(1, "repo map stale"))

    result = vc.run_validation_suite("self_ref_incremental", str(tmp_path))

    assert not result.ok
    assert "repo map stale" in result.detail
