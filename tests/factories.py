"""factories -- canonical builders for the objects tests construct constantly.

Writing a test should be one call, not 15 lines of hand-assembled state. Every builder takes
``**overrides`` to tweak just the fields a test cares about. Mirrors the ad-hoc fakes already
scattered across the suite (FakePage, lambda brains) so they can be centralized over time.

  make_subtask(**o)     -> a plan subtask dict
  make_spec(**o)        -> an executor InvocationSpec dict
  make_verify(**o)      -> a verification {cmd, expect} dict
  make_verdict(**o)     -> an adversary Verdict dict
  fake_brain(reply)     -> an ollama_chat callable (system, user, *, want_json=False) -> resp
  fake_page(present)    -> a Playwright-page stand-in (locator(css).count()/inner_text())
  make_task_state(...)  -> a TaskState (in-memory; does not touch disk)
"""
from __future__ import annotations

import json
from typing import Any, Callable, Optional


def make_subtask(**o: Any) -> dict[str, Any]:
    base = {
        "subtask_id": "st-001", "title": "Do the thing", "description": "...",
        "assigned_to": "executor", "layer": 3, "status": "pending",
        "depends_on": [], "started_at": None, "completed_at": None,
        "output_ref": None, "github_pr": None, "session": None,
    }
    base.update(o)
    return base


def make_spec(**o: Any) -> dict[str, Any]:
    base = {
        "prompt": "do it", "claude_md_inject": "", "skills_to_invoke": [],
        "effort_level": "default", "subagent": None, "pre_tool_hooks": [],
        "post_tool_hooks": [], "use_workflow": False, "workflow_definition": None,
        "surface": "terminal", "browser_actions": [],
    }
    base.update(o)
    return base


def make_verify(**o: Any) -> dict[str, str]:
    base = {"cmd": "python -c \"print('ok')\"", "expect": "exit_zero"}
    base.update(o)
    return base


def make_verdict(**o: Any) -> dict[str, Any]:
    base = {
        "verdict": "approved", "trigger_reason": "heartbeat", "concerns": [],
        "notes": "", "stub": False, "severity": "none", "must_fix": [],
        "suggested_fix": "", "confidence": None, "surface": "ollama",
        "review_type": "subtask", "tier": "ollama", "session_dead": False,
    }
    base.update(o)
    return base


def fake_brain(reply: Any = "", *, as_json: Optional[dict] = None) -> Callable:
    """Return an ``ollama_chat``-shaped callable. ``as_json`` (a dict) is JSON-encoded into the
    message content; otherwise ``reply`` (str) is the content verbatim. Matches the resp shape
    code reads via llm_io (``resp['message']['content']``)."""
    content = json.dumps(as_json) if as_json is not None else str(reply)

    def _chat(system: str, user: str, *, want_json: bool = False):  # noqa: ARG001
        return {"message": {"content": content}}

    return _chat


class _FakeLoc:
    def __init__(self, n: int, text: str = "", attr: Optional[str] = None) -> None:
        self._n, self._text, self._attr = n, text, attr

    def count(self) -> int:
        return self._n

    @property
    def last(self) -> "_FakeLoc":
        return self

    def inner_text(self) -> str:
        return self._text

    def get_attribute(self, name: str) -> Optional[str]:
        return self._attr

    def click(self, *a: Any, **k: Any) -> None: ...
    def press(self, *a: Any, **k: Any) -> None: ...
    def fill(self, *a: Any, **k: Any) -> None: ...
    def type(self, *a: Any, **k: Any) -> None: ...


class _FakePage:
    """Playwright-page stand-in: ``present`` maps css -> (count, text); everything else is absent."""
    def __init__(self, present: dict[str, tuple[int, str]], url: str = "https://chatgpt.com/c/x") -> None:
        self.present = present
        self.url = url

    def locator(self, css: str) -> _FakeLoc:
        n, text = self.present.get(css, (0, ""))
        return _FakeLoc(n, text)

    def wait_for_timeout(self, ms: int) -> None: ...
    def goto(self, url: str, **k: Any) -> None:
        self.url = url

    def screenshot(self, **k: Any) -> bytes:
        return b""

    def content(self) -> str:
        return "<html></html>"


def fake_page(present: Optional[dict[str, tuple[int, str]]] = None, **k: Any) -> _FakePage:
    return _FakePage(present or {}, **k)


def make_task_state(goal: str = "test goal", hours: float = 1.0):
    """A TaskState built in memory (TaskState.create does not write to disk)."""
    from state.task import TaskState
    return TaskState.create(goal, hours)
