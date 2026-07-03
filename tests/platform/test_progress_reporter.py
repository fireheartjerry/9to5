"""Tests for the first-party pytest progress heartbeat reporter."""
from __future__ import annotations

from types import SimpleNamespace

from tests import progress_reporter


class _Config:
    def __init__(self, *, markexpr: str = "", args: list[str] | None = None) -> None:
        self.option = SimpleNamespace(markexpr=markexpr)
        self.args = args or []
        self.rootpath = "."


def _report(nodeid: str = "tests/test_x.py::test_y", *, when: str = "call",
            failed: bool = False, skipped: bool = False, worker_id=None):
    data = {"nodeid": nodeid, "when": when, "failed": failed, "skipped": skipped}
    if worker_id is not None:
        data["worker_id"] = worker_id
    return SimpleNamespace(**data)


def test_state_line_includes_progress_counts_and_active_worker():
    state = progress_reporter.ProgressState(started_at=10.0)
    state.collect(3)
    state.start("tests/test_x.py::test_y", "gw0")

    line = state.line(now=100.0)

    assert line == ("[pytest-progress] elapsed=90s completed=0/3 failed=0 skipped=0 "
                    "active=gw0 tests/test_x.py::test_y")


def test_reports_increment_completed_failed_and_skipped_counts():
    state = progress_reporter.ProgressState(started_at=0.0)
    state.collect(2)

    state.report(_report(failed=True, worker_id="gw0"))
    state.report(_report("tests/test_z.py::test_skip", skipped=True))

    assert state.completed == 2
    assert state.failed == 1
    assert state.skipped == 1


def test_line_uses_completed_as_floor_for_subtest_heavy_runs():
    state = progress_reporter.ProgressState(total=1, completed=3, started_at=0.0)

    assert "completed=3/3" in state.line(now=1.0)


def test_setup_report_without_xdist_worker_metadata_does_not_crash():
    state = progress_reporter.ProgressState(started_at=0.0)

    state.start("tests/test_x.py::test_y")
    state.report(_report(when="setup"))

    assert "main tests/test_x.py::test_y" in state.line(now=1.0)


def test_progress_can_be_disabled_by_env(monkeypatch):
    monkeypatch.setenv("NINE_TO_FIVE_TEST_PROGRESS", "0")

    assert progress_reporter.should_enable(_Config(markexpr="slow")) is False


def test_progress_enables_for_ci_slow_and_full_runs(monkeypatch):
    monkeypatch.delenv("NINE_TO_FIVE_TEST_PROGRESS", raising=False)
    monkeypatch.setenv("CI", "1")
    assert progress_reporter.should_enable(_Config()) is True

    monkeypatch.delenv("CI", raising=False)
    assert progress_reporter.should_enable(_Config(markexpr="slow")) is True
    assert progress_reporter.should_enable(_Config(args=["tests"])) is True
    assert progress_reporter.should_enable(_Config(args=["tests/test_one.py"])) is False


def test_bad_interval_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("NINE_TO_FIVE_TEST_HEARTBEAT_SECONDS", "not-a-number")

    assert progress_reporter.interval_from_env(default=12.0) == 12.0


def test_xdist_collection_hook_sets_controller_total(monkeypatch):
    reporter = SimpleNamespace(state=progress_reporter.ProgressState(started_at=0.0))
    monkeypatch.setattr(progress_reporter, "_REPORTER", reporter)

    progress_reporter.pytest_xdist_node_collection_finished(None, ["a", "b", "c"])

    assert reporter.state.total == 3


def test_history_recorder_captures_ci_metadata(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_RUN_ID", "run-1")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    monkeypatch.setenv("GITHUB_JOB", "fast")
    monkeypatch.setenv("GITHUB_SHA", "abc123")
    monkeypatch.setenv("NINE_TO_FIVE_TEST_SHARD", "3")
    monkeypatch.setenv("NINE_TO_FIVE_TEST_HISTORY_DIR", str(tmp_path))
    recorder = progress_reporter.TestHistoryRecorder(_Config(), clock=lambda: 123.0)

    recorder.report(_report(worker_id="gw1"))

    rec = recorder.records["tests/test_x.py::test_y"]
    assert rec["run_id"] == "run-1"
    assert rec["run_attempt"] == "2"
    assert rec["job"] == "fast"
    assert rec["sha"] == "abc123"
    assert rec["shard"] == "3"
    assert rec["worker"] == "gw1"
