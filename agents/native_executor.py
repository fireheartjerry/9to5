"""Native UI execution backend -- Layer 2 (UIA/pywinauto) "hands" for 9TO5.

A peer to browser_executor.py (L1) and executor.py (L3): same call signature, same
result-dict contract so the orchestrator's dispatcher can route a subtask to native
Windows UI automation when the brain authors ``surface="native"``. Drives any native
Windows application that exposes the UIA tree via pywinauto. When pywinauto is not
installed the call degrades cleanly (ok=False, is_error=True) so the run continues
rather than crashing -- exactly like a failed terminal subtask.

Deterministic + offline-testable: pywinauto is isolated behind ``_run_native_actions``
(mockable); all tests in tests/test_phase_3_architecture.py mock that function so CI
never requires a real Windows display session or pywinauto install.

See docs/phase_3_architecture.md + orchestrator._selectExecutor for the wiring spec.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import config
from agents import executor

LOG = config.getLogger("native_executor")

# These will eventually live in config.py (see docs/phase_3_architecture.md).
# Defined here with sensible defaults until the core file is updated for Phase 3.
NATIVE_ACTION_TIMEOUT_MS: int = int(
    getattr(config, "NATIVE_ACTION_TIMEOUT_MS", 10000))
NATIVE_SCREENSHOT_DIR: "Path" = getattr(
    config, "NATIVE_SCREENSHOT_DIR", config.PROJECT_ROOT / "state" / "native_screenshots")


class NativeUnavailable(RuntimeError):
    """Raised when pywinauto is not installed; caller degrades to ok=False result."""


def _result(spec: dict, *, ok: bool, is_error: bool, stdout: str = "", stderr: str = "") -> dict:
    """runClaude-shaped result so the orchestrator treats native output identically."""
    return {
        "ok": ok, "returncode": 0 if ok else 1, "stdout": stdout, "stderr": stderr,
        "is_error": is_error, "effort": spec.get("effort_level", "default"),
        "effort_flag": None, "spec": spec, "claude_md_path": None,
        "profile": "native_ui_operator", "blocked": False, "surface": "native",
    }


def _run_native_actions(actions: list[dict[str, Any]], *,
                        timeout_ms: int = NATIVE_ACTION_TIMEOUT_MS,
                        screenshot_dir: Optional[str] = None) -> str:
    """Execute structured UIA actions via pywinauto; return a transcript. Raises
    NativeUnavailable if pywinauto is not installed (caller degrades cleanly).

    Supported actions: launch, connect, find, click, type, press, extract,
    screenshot, close. Each transcript line records the action + observable result."""
    try:
        import pywinauto  # type: ignore
    except Exception as e:  # noqa: BLE001
        raise NativeUnavailable(
            "native layer unavailable: `pip install pywinauto`") from e

    lines: list[str] = []
    app = None
    window = None
    for i, act in enumerate(actions):
        kind = (act.get("action") or "").lower()
        try:
            if kind == "launch":
                app = pywinauto.Application(backend="uia").start(act["app"])
                lines.append(f"launch {act['app']!r}")
            elif kind == "connect":
                app = pywinauto.Application(backend="uia").connect(title_re=act.get("app", ".*"))
                lines.append(f"connect to {act.get('app')!r}")
            elif kind == "find":
                if app is None:
                    raise RuntimeError("no app connected; use 'launch' or 'connect' first")
                window = app.window(title=act.get("title"), control_type=act.get("control_type"))
                window.wait("ready", timeout=timeout_ms / 1000)
                lines.append(f"find {act.get('title')!r} [{act.get('control_type')}]")
            elif kind == "click":
                ctrl = window.child_window(title=act.get("title"), control_type=act.get("control_type"))
                ctrl.click_input()
                lines.append(f"click {act.get('title')!r}")
            elif kind == "type":
                ctrl = window or app.top_window()
                ctrl.type_keys(act.get("text", ""), with_spaces=True)
                text_preview = repr(act.get("text", ""))[:40]
                lines.append(f"type {text_preview}")
            elif kind == "press":
                ctrl = window or app.top_window()
                ctrl.type_keys(act.get("key", ""), with_spaces=True)
                lines.append(f"press {act.get('key')!r}")
            elif kind == "extract":
                ctrl = window or app.top_window()
                text = ctrl.window_text()[:2000]
                lines.append(f"extract:\n{text}")
            elif kind == "screenshot":
                name = act.get("path") or f"native-screenshot-{i}.png"
                sd = screenshot_dir or str(NATIVE_SCREENSHOT_DIR)
                path = str(Path(sd) / name)
                (window or app.top_window()).capture_as_image().save(path)
                lines.append(f"screenshot -> {path}")
            elif kind == "close":
                target = app or pywinauto.Application(backend="uia").connect(title_re=act.get("app", ".*"))
                target.kill()
                lines.append(f"close {act.get('app')!r}")
            else:
                lines.append(f"(skipped unknown action {kind!r})")
        except Exception as e:  # noqa: BLE001
            lines.append(f"ERROR in action {i} ({kind!r}): {e}")
            raise
    return "\n".join(lines)


def nativeActions(app: str, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build a canonical action list from a high-level recipe. Prepends launch/find
    and appends close so callers only specify the middle interaction steps."""
    return [{"action": "launch", "app": app}] + steps + [{"action": "close", "app": app}]


def runNative(spec_or_prompt, *, work_dir: Optional[str] = None, task_state=None,
              subtask: Optional[dict] = None, resume_session: Optional[str] = None,
              **_kw) -> dict:
    """Execute a native UI subtask. Matches executor.runClaude's signature + result shape."""
    spec = executor.normalizeSpec(spec_or_prompt)
    actions: list[dict[str, Any]] = spec.get("native_actions") or []
    if not actions:
        return _result(spec, ok=False, is_error=True,
                       stderr="native surface needs 'native_actions' in the spec")
    try:
        transcript = _run_native_actions(actions, screenshot_dir=work_dir)
        LOG.info("native run: %d actions ok", len(actions))
        return _result(spec, ok=True, is_error=False, stdout=transcript)
    except NativeUnavailable as e:
        LOG.warning("%s", e)
        return _result(spec, ok=False, is_error=True, stderr=str(e))
    except Exception as e:  # noqa: BLE001 -- a native failure is a failed subtask, not a crash
        LOG.warning("native run failed: %s", e)
        return _result(spec, ok=False, is_error=True, stderr=f"native run failed: {e}")


def selectForSurface(terminal_fn, spec: dict):
    """Routing helper: return runNative when surface=native and NATIVE_LAYER_ENABLED,
    else return terminal_fn (L3 Claude CLI fallback).

    This encapsulates the routing logic so orchestrator._selectExecutor can delegate:
        from agents import native_executor
        return native_executor.selectForSurface(self._run_claude, spec)
    """
    if spec.get("surface") == "native" and config.NATIVE_LAYER_ENABLED:
        return runNative
    return terminal_fn
