"""Run-liveness stamping has one runtime owner."""
from __future__ import annotations

import os


class _State:
    task_id = "task-1"

    def __init__(self) -> None:
        self.meta: dict = {}
        self.saved = 0

    def save(self) -> None:
        self.saved += 1


def test_mark_run_active_persists_pid_before_heartbeat(monkeypatch):
    from platform_core.runtime import run_lifecycle

    state = _State()
    events: list[tuple] = []

    def save() -> None:
        state.saved += 1
        events.append(("save", state.meta.get("run_pid")))

    state.save = save  # type: ignore[method-assign]
    monkeypatch.setattr(
        run_lifecycle.heartbeat,
        "writeHeartbeat",
        lambda task_id, pid=None: events.append(("heartbeat", task_id, pid)),
    )

    assert run_lifecycle.markRunActive(state) == os.getpid()
    assert events == [
        ("save", os.getpid()),
        ("heartbeat", "task-1", os.getpid()),
    ]


def test_mark_run_active_accepts_an_explicit_pid(monkeypatch):
    from platform_core.runtime import run_lifecycle

    state = _State()
    heartbeats: list[tuple[str, int | None]] = []
    monkeypatch.setattr(
        run_lifecycle.heartbeat,
        "writeHeartbeat",
        lambda task_id, pid=None: heartbeats.append((task_id, pid)),
    )

    assert run_lifecycle.markRunActive(state, pid=4242) == 4242
    assert state.meta["run_pid"] == 4242
    assert heartbeats == [("task-1", 4242)]
