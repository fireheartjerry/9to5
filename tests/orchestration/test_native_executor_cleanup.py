"""Native executor: terminate the launched app on failure + mkdir screenshot dir (B12)."""

from __future__ import annotations

import sys
import types
from unittest import mock

import pytest

from agents import native_executor as ne


def test_run_native_actions_terminates_app_on_failure(monkeypatch):
    monkeypatch.setitem(sys.modules, "pywinauto", types.ModuleType("pywinauto"))
    fake_app = mock.Mock()

    def fake_exec(act, i, app, window, *, timeout_ms, screenshot_dir):
        if act.get("action") == "launch":
            return fake_app, window, "launch", True, False
        raise RuntimeError("boom")

    monkeypatch.setattr(ne, "_execNativeAction", fake_exec)
    with pytest.raises(RuntimeError):
        ne._run_native_actions([{"action": "launch", "app": "x"}, {"action": "boom"}])
    fake_app.kill.assert_called_once()


def test_run_native_actions_kills_launched_app_on_success_without_close(monkeypatch):
    """Happy-path leak fix: launch + other actions with no explicit close must still
    terminate the launched app once the action loop finishes successfully."""
    monkeypatch.setitem(sys.modules, "pywinauto", types.ModuleType("pywinauto"))
    fake_app = mock.Mock()

    def fake_exec(act, i, app, window, *, timeout_ms, screenshot_dir):
        if act.get("action") == "launch":
            return fake_app, window, "launch", True, False
        return fake_app, window, act.get("action"), False, False

    monkeypatch.setattr(ne, "_execNativeAction", fake_exec)
    transcript = ne._run_native_actions(
        [{"action": "launch", "app": "x"}, {"action": "type", "text": "hi"}, {"action": "extract"}]
    )
    assert "launch" in transcript
    fake_app.kill.assert_called_once()


def test_run_native_actions_does_not_kill_explicit_close(monkeypatch):
    """When the spec already includes a 'close' action, the finally block must not
    call kill() a second time."""
    monkeypatch.setitem(sys.modules, "pywinauto", types.ModuleType("pywinauto"))
    fake_app = mock.Mock()

    def fake_exec(act, i, app, window, *, timeout_ms, screenshot_dir):
        action = act.get("action")
        if action == "launch":
            return fake_app, window, "launch", True, False
        if action == "close":
            fake_app.kill()
            return fake_app, window, "close", False, True
        return fake_app, window, action, False, False

    monkeypatch.setattr(ne, "_execNativeAction", fake_exec)
    ne._run_native_actions([{"action": "launch", "app": "x"}, {"action": "close", "app": "x"}])
    fake_app.kill.assert_called_once()


def test_run_native_actions_never_kills_connect_attached_app(monkeypatch):
    """An app this call only CONNECTS to (pre-existing, user-owned) must never be
    killed, even though the action loop completes with no explicit close."""
    monkeypatch.setitem(sys.modules, "pywinauto", types.ModuleType("pywinauto"))
    fake_app = mock.Mock()

    def fake_exec(act, i, app, window, *, timeout_ms, screenshot_dir):
        if act.get("action") == "connect":
            return fake_app, window, "connect", False, False
        return fake_app, window, act.get("action"), False, False

    monkeypatch.setattr(ne, "_execNativeAction", fake_exec)
    ne._run_native_actions([{"action": "connect", "app": "x"}, {"action": "extract"}])
    fake_app.kill.assert_not_called()


def test_screenshot_creates_missing_dir(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "pywinauto", types.ModuleType("pywinauto"))
    monkeypatch.setattr("notifications.lane_feed.laneTap", lambda *a, **k: None)

    img = mock.Mock()
    win = mock.Mock()
    win.capture_as_image.return_value = img
    app = mock.Mock()
    app.top_window.return_value = win

    target = tmp_path / "shots" / "nested"
    assert not target.exists()
    ne._execNativeAction(
        {"action": "screenshot", "path": "s.png"}, 0, app, win, timeout_ms=1000, screenshot_dir=str(target)
    )

    assert target.exists()
    img.save.assert_called_once()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
