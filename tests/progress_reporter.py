"""Pytest progress heartbeat for long-running CI and agent-observed test runs."""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import pytest

_REPORTER: "ProgressReporter | None" = None


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _env_disabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"0", "false", "no", "off"}


def interval_from_env(default: float = 30.0) -> float:
    raw = os.getenv("NINE_TO_FIVE_TEST_HEARTBEAT_SECONDS", "").strip()
    if not raw:
        return default
    try:
        return max(1.0, float(raw))
    except ValueError:
        return default


def should_enable(config) -> bool:
    if _env_disabled("NINE_TO_FIVE_TEST_PROGRESS"):
        return False
    if _env_truthy("NINE_TO_FIVE_TEST_PROGRESS") or _env_truthy("CI"):
        return True
    markexpr = str(getattr(config.option, "markexpr", "") or "")
    args = [str(a) for a in getattr(config, "args", [])]
    # Local default: full/slow runs get heartbeats; focused file/node runs stay quiet.
    return "slow" in markexpr or args == ["tests"]


@dataclass
class ProgressState:
    total: int = 0
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    started_at: float = field(default_factory=time.monotonic)
    active: dict[str, str] = field(default_factory=dict)

    def collect(self, total: int) -> None:
        self.total = total

    def start(self, nodeid: str, worker: str = "main") -> None:
        self.active[worker] = nodeid

    def finish(self, nodeid: str, worker: str = "main") -> None:  # noqa: ARG002
        self.active.pop(worker, None)

    def report(self, report) -> None:
        if getattr(report, "when", None) != "call":
            return
        self.completed += 1
        if getattr(report, "failed", False):
            self.failed += 1
        if getattr(report, "skipped", False):
            self.skipped += 1
        worker = str(getattr(report, "worker_id", "") or "main")
        self.finish(str(getattr(report, "nodeid", "") or ""), worker)

    def line(self, now: float | None = None) -> str:
        elapsed = int((now if now is not None else time.monotonic()) - self.started_at)
        total = max(self.total, self.completed)
        active = " ".join(f"{worker} {nodeid}" for worker, nodeid in sorted(self.active.items()))
        if not active:
            active = "none"
        return (f"[pytest-progress] elapsed={elapsed}s completed={self.completed}/{total} "
                f"failed={self.failed} skipped={self.skipped} active={active}")


class ProgressReporter:
    def __init__(self, config, *, interval: float | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.config = config
        self.interval = interval if interval is not None else interval_from_env()
        self.clock = clock
        self.state = ProgressState(started_at=clock())
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _write(self, line: str) -> None:
        terminal = self.config.pluginmanager.get_plugin("terminalreporter")
        if terminal is not None:
            terminal.write_line(line)
        else:
            print(line, flush=True)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="pytest-progress", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            self._write(self.state.line(self.clock()))


def pytest_configure(config) -> None:
    global _REPORTER
    if should_enable(config):
        _REPORTER = ProgressReporter(config)
        config._nine_to_five_progress = _REPORTER  # noqa: SLF001


def pytest_collection_modifyitems(config, items) -> None:
    if _REPORTER is not None:
        _REPORTER.state.collect(len(items))


@pytest.hookimpl(optionalhook=True)
def pytest_xdist_node_collection_finished(node, ids) -> None:  # noqa: ARG001
    if _REPORTER is not None:
        _REPORTER.state.collect(max(_REPORTER.state.total, len(ids)))


def pytest_sessionstart(session) -> None:
    if _REPORTER is not None:
        _REPORTER.start()


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ARG001
    global _REPORTER
    if _REPORTER is not None:
        _REPORTER._write(_REPORTER.state.line(_REPORTER.clock()))  # noqa: SLF001
        _REPORTER.stop()
        _REPORTER = None


def pytest_runtest_logstart(nodeid, location) -> None:  # noqa: ARG001
    # Filled by pytest_configure through module-level plugin registration.
    # The active map is updated by pytest_runtest_logreport where worker IDs are available.
    return None


def pytest_runtest_logreport(report) -> None:
    if _REPORTER is None:
        return
    worker = str(getattr(report, "worker_id", "") or "main")
    if getattr(report, "when", None) == "setup":
        _REPORTER.state.start(str(getattr(report, "nodeid", "") or ""), worker)
    _REPORTER.state.report(report)
