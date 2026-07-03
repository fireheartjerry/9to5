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
            return fake_app, window, "launch"
        raise RuntimeError("boom")

    monkeypatch.setattr(ne, "_execNativeAction", fake_exec)
    with pytest.raises(RuntimeError):
        ne._run_native_actions(
            [{"action": "launch", "app": "x"}, {"action": "boom"}])
    fake_app.kill.assert_called_once()


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
        {"action": "screenshot", "path": "s.png"}, 0, app, win,
        timeout_ms=1000, screenshot_dir=str(target))

    assert target.exists()
    img.save.assert_called_once()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
