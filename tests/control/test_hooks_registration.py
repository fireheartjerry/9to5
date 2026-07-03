"""Hook registration parity + fail-closed dispatch (B8, B10).

Guards against a future strip of ``.claude/settings.json`` (the "hooks": {} regression)
and proves a broken BLOCKING guard import fails CLOSED (exit 2), never OPEN (tool runs).
"""
from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

import pytest

from agents import hooks

_REPO_ROOT = Path(hooks.__file__).resolve().parent.parent
_SETTINGS = _REPO_ROOT / ".claude" / "settings.json"

# Hooks the dispatcher handles that fire on NON-tool events (Notification / UserPromptSubmit /
# Stop) and so are intentionally NOT part of the PreToolUse/PostToolUse tool-hook surface.
_EVENT_ONLY = {"discord_notify", "log_telemetry", "user_prompt_telemetry", "stop_telemetry"}


def _handledHooks() -> set:
    """Every hook name the dispatcher in agents/hooks.py handles."""
    src = Path(hooks.__file__).read_text(encoding="utf-8")
    names = set(hooks._BLOCKING_HOOKS)
    for m in re.finditer(r'hook_name == "([^"]+)"', src):
        names.add(m.group(1))
    for m in re.finditer(r"hook_name in \(([^)]*)\)", src):
        names.update(re.findall(r'"([^"]+)"', m.group(1)))
    return names


def _registeredHooks() -> set:
    """Every hook name registered in .claude/settings.json (last token of each command)."""
    data = json.loads(_SETTINGS.read_text(encoding="utf-8"))
    names: set = set()
    for groups in (data.get("hooks") or {}).values():
        for group in groups:
            for entry in group.get("hooks", []):
                cmd = entry.get("command", "")
                if "hooks.py" in cmd:
                    names.add(cmd.split()[-1])
    return names


def test_settings_json_is_valid_and_hooks_not_empty():
    assert _registeredHooks(), "settings.json has no hook registrations (stripped?)"


def test_no_dead_registration():
    # Every registered hook must be a hook the dispatcher actually handles.
    assert _registeredHooks() <= _handledHooks()


def test_tool_hook_surface_is_bidirectional():
    # Vice-versa: every tool-triggered hook the dispatcher handles is registered, and no extra.
    assert (_handledHooks() - _EVENT_ONLY) == _registeredHooks()


def test_blocking_guards_are_registered():
    reg = _registeredHooks()
    assert {"block_destructive", "self_modification_guard"} <= reg


@pytest.mark.parametrize("hook_name", ["block_destructive", "self_modification_guard"])
def test_broken_blocking_guard_import_fails_closed(monkeypatch, hook_name):
    def _boom(_name):
        raise ImportError("simulated broken guard sub-module")

    monkeypatch.setattr(hooks, "_importBlockingGuard", _boom)
    monkeypatch.setattr(sys, "argv", ["hooks.py", hook_name])
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    with pytest.raises(SystemExit) as ei:
        hooks.main()
    assert ei.value.code == 2  # fail CLOSED: block the tool call, do not exit 0


def test_broken_guard_exec_error_fails_closed(monkeypatch):
    def _explode(_data):
        raise RuntimeError("guard blew up mid-exec")

    monkeypatch.setattr(hooks, "_importBlockingGuard", lambda _n: _explode)
    monkeypatch.setattr(sys, "argv", ["hooks.py", "block_destructive"])
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    with pytest.raises(SystemExit) as ei:
        hooks.main()
    assert ei.value.code == 2


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
