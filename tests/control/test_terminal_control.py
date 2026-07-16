"""Terminal control is a testable runtime adapter over the shared ControlBus."""
from __future__ import annotations

import importlib.util
from io import StringIO


class _Bus:
    def __init__(self) -> None:
        self.abort = 0
        self.pause = 0
        self.resume = 0
        self.ops: list[dict] = []
        self.decisions: list[tuple[str, str]] = []
        self.pending_gate: str | None = "plan"

    def requestAbort(self) -> None:
        self.abort += 1

    def requestPause(self) -> None:
        self.pause += 1

    def clearPause(self) -> None:
        self.resume += 1

    def getPendingGate(self) -> str | None:
        return self.pending_gate

    def decide(self, gate: str, verdict: str) -> None:
        self.decisions.append((gate, verdict))

    def pushOp(self, op: dict) -> None:
        self.ops.append(op)


class _State:
    def __init__(self, meta: dict | None = None) -> None:
        self.meta = meta or {}

    def progress(self) -> tuple[int, int]:
        return 2, 5


def test_terminal_control_runtime_module_exists():
    assert importlib.util.find_spec("platform_core.runtime.terminal_control") is not None


def test_controller_normalizes_prefixes_and_preserves_payload_case():
    from platform_core.runtime.terminal_control import TerminalController

    bus = _Bus()
    output = StringIO()
    controller = TerminalController(
        "task-1",
        bus=bus,
        state_loader=lambda _task_id: _State({"status": "running"}),
        input_stream=StringIO("  !SKIP ST-007  \n!add Keep This Case\nstatus\n"),
        output_stream=output,
    )

    controller.run()

    assert bus.ops == [
        {"op": "skip", "subtask_id": "ST-007"},
        {"op": "add", "title": "Keep This Case", "description": "Keep This Case"},
    ]
    assert "running" in output.getvalue()
    assert "2/5 subtasks" in output.getvalue()


def test_status_tolerates_legacy_state_without_status_metadata():
    from platform_core.runtime.terminal_control import TerminalController

    output = StringIO()
    TerminalController(
        "task-1",
        bus=_Bus(),
        state_loader=lambda _task_id: _State(),
        input_stream=StringIO("status\n"),
        output_stream=output,
    ).run()

    assert "unknown" in output.getvalue()


def test_missing_command_payload_does_not_queue_an_operation():
    from platform_core.runtime.terminal_control import TerminalController

    bus = _Bus()
    output = StringIO()
    TerminalController(
        "task-1",
        bus=bus,
        state_loader=lambda _task_id: _State(),
        input_stream=StringIO("!skip\n!add   \n"),
        output_stream=output,
    ).run()

    assert bus.ops == []
    assert "commands:" in output.getvalue()
