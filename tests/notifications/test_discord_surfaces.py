"""Tests for the on-demand Discord surfaces (!logs, !stdout, !arc, !history)."""
import config
from notifications import commands
from notifications.event_bus import get_bus, reset_bus
from platform_core.runtime.control import ControlBus


def _state(tmp_path):
    from state.task import TaskState
    s = TaskState.create("do the thing", 1.0)
    s.addSubtask("first", "do it")
    s.updateSubtask("st-001", status="in_progress")
    s.save()
    return s


def test_parse_new_commands():
    assert commands.parseCommand("!logs") == commands.Command("logs", "")
    assert commands.parseCommand("!logs st-002") == commands.Command("logs", "st-002")
    assert commands.parseCommand("!arc") == commands.Command("arc", "")
    assert commands.parseCommand("!history") == commands.Command("history", "")
    assert commands.parseCommand("!stdout") == commands.Command("stdout", "")


def test_logs_pulls_raw_from_bus(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    reset_bus()
    bus = get_bus()
    state = _state(tmp_path)
    bus.emit_raw("st-001", "compiling module X")
    out = commands.applyCommand(ControlBus(state.task_id), state, commands.Command("logs", ""))
    assert "compiling module X" in out
    assert "st-001" in out


def test_stdout_uses_explicit_sid(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    reset_bus()
    bus = get_bus()
    state = _state(tmp_path)
    bus.emit_raw("st-002", "line for two")
    out = commands.applyCommand(ControlBus(state.task_id), state, commands.Command("stdout", "st-002"))
    assert "line for two" in out


def test_arc_renders(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    from notifications import run_arc
    state = _state(tmp_path)
    run_arc.append_beat(state, "Chapter 1 — the beginning")
    out = commands.applyCommand(ControlBus(state.task_id), state, commands.Command("arc", ""))
    assert "the beginning" in out


def test_history_pulls_events(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    reset_bus()
    bus = get_bus()
    from notifications.event_bus import Event
    state = _state(tmp_path)
    bus.emit(Event(kind="phase", sid="system", text="executing now"))
    out = commands.applyCommand(ControlBus(state.task_id), state, commands.Command("history", ""))
    assert "executing now" in out


def test_logs_no_subtask_is_graceful(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    reset_bus()
    from state.task import TaskState
    state = TaskState.create("empty", 1.0)
    state.save()
    out = commands.applyCommand(ControlBus(state.task_id), state, commands.Command("logs", ""))
    assert isinstance(out, str)  # no subtask -> graceful message, no crash
