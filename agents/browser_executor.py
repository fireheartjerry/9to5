"""Browser execution backend -- Layer 1 (CDP) "hands" for 9TO5.

A peer to the Claude-CLI executor (agents/executor.py): same call signature, same result-
dict contract, so the orchestrator's dispatcher can route a subtask to the browser when the
brain authors ``surface="browser"``. It drives Chromium via Playwright (real CDP) to run a
list of structured actions (goto/click/type/extract/screenshot/wait). When Playwright is
not installed the call degrades cleanly (ok=False, is_error=True) so the run continues --
exactly like a failed terminal subtask -- rather than crashing.

Deterministic + offline-testable: the Playwright work is isolated behind ``_run_actions``
(mockable); URL-only prompts auto-expand to a fetch+extract so simple "look at this page"
goals work without the brain hand-authoring actions.

See docs (Layer 1 browser) + surfaces.py + the orchestrator dispatcher.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

import config
from agents import executor

LOG = config.getLogger("browser_executor")

_URL_RE = re.compile(r"https?://[^\s\"'<>)]+")


class BrowserUnavailable(RuntimeError):
    """Raised when no browser backend (Playwright/Chromium) is installed."""


def _result(spec: dict, *, ok: bool, is_error: bool, stdout: str = "", stderr: str = "") -> dict:
    """A runClaude-shaped result so the orchestrator treats browser output identically."""
    return {
        "ok": ok, "returncode": 0 if ok else 1, "stdout": stdout, "stderr": stderr,
        "is_error": is_error, "effort": spec.get("effort_level", "default"),
        "effort_flag": None, "spec": spec, "claude_md_path": None,
        "profile": "browser_navigator", "blocked": False, "surface": "browser",
    }


def _actions_from_prompt(prompt: str) -> list[dict[str, Any]]:
    """Auto-derive simple actions from a URL-bearing prompt: visit each URL + extract text."""
    actions: list[dict[str, Any]] = []
    for url in _URL_RE.findall(prompt or ""):
        actions.append({"action": "goto", "url": url})
        actions.append({"action": "extract"})
    return actions


def _run_actions(actions: list[dict[str, Any]], *, timeout_ms: int = 30000) -> str:
    """Execute structured CDP actions via Playwright; return a transcript. Raises
    BrowserUnavailable if Playwright/Chromium is not installed (caller degrades)."""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as e:  # noqa: BLE001 -- not installed -> caller degrades cleanly
        raise BrowserUnavailable(
            "browser layer unavailable: `pip install playwright && playwright install chromium`") from e

    lines: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_default_timeout(timeout_ms)
            for act in actions:
                kind = (act.get("action") or "").lower()
                if kind == "goto":
                    page.goto(act["url"])
                    lines.append(f"goto {act['url']} -> {page.title()!r}")
                elif kind == "click":
                    page.click(act["selector"])
                    lines.append(f"click {act['selector']}")
                elif kind == "type":
                    page.fill(act["selector"], act.get("text", ""))
                    lines.append(f"type into {act['selector']}")
                elif kind == "wait":
                    page.wait_for_selector(act["selector"])
                    lines.append(f"wait {act['selector']}")
                elif kind == "extract":
                    sel = act.get("selector")
                    text = (page.inner_text(sel) if sel else page.inner_text("body"))[:2000]
                    lines.append(f"extract {sel or 'body'}:\n{text}")
                elif kind == "screenshot":
                    path = act.get("path") or "screenshot.png"
                    page.screenshot(path=path)
                    lines.append(f"screenshot -> {path}")
                else:
                    lines.append(f"(skipped unknown action {kind!r})")
        finally:
            browser.close()
    return "\n".join(lines)


def runBrowser(spec_or_prompt, *, work_dir: Optional[str] = None, task_state=None,
               subtask: Optional[dict] = None, resume_session: Optional[str] = None,
               **_kw) -> dict:
    """Execute a browser subtask. Matches executor.runClaude's signature + result shape."""
    spec = executor.normalizeSpec(spec_or_prompt)
    actions = spec.get("browser_actions") or _actions_from_prompt(spec.get("prompt", ""))
    if not actions:
        return _result(spec, ok=False, is_error=True,
                       stderr="browser surface needs 'browser_actions' or a URL in the prompt")
    try:
        transcript = _run_actions(actions)
        LOG.info("browser run: %d actions ok", len(actions))
        return _result(spec, ok=True, is_error=False, stdout=transcript)
    except BrowserUnavailable as e:
        LOG.warning("%s", e)
        return _result(spec, ok=False, is_error=True, stderr=str(e))
    except Exception as e:  # noqa: BLE001 -- a browser failure is a failed subtask, not a crash
        LOG.warning("browser run failed (ignored): %s", e)
        return _result(spec, ok=False, is_error=True, stderr=f"browser run failed: {e}")
