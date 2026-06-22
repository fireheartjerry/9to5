"""Simulation doubles for a --dry-run: exercise the WHOLE 9TO5 pipeline
(architect -> plan -> execute -> verify -> complete) with NO Ollama, Claude CLI,
Discord, or Obsidian. The orchestrator accepts these via its dependency seams
(``Orchestrator(brain=, obs=, run_claude=, replan=, review=)``).

This is what makes the loop runnable locally and in CI -- the only way to gain
real confidence in the orchestration before a live 9-to-5 run.
"""
from __future__ import annotations

import json

import config

LOG = config.getLogger("simulation")


class SimBrain:
    """Stand-in for ``ollama.Client``. Inspects the prompt to return deterministic,
    schema-correct JSON for each brain act (plan / critique / invocation spec). Subtasks
    carry NO verify so they pass on the simulated executor's exit-zero (no subprocess)."""

    def __init__(self, n_subtasks: int = 3):
        self.n = max(1, n_subtasks)
        self.calls = 0

    def _plan(self) -> dict:
        return {"subtasks": [
            {"title": f"Simulated subtask {i}", "description": f"Do simulated step {i}.",
             "layer": 3, "effort_level": "default", "verify": None}
            for i in range(1, self.n + 1)
        ]}

    def chat(self, *, model=None, messages=None, **kwargs):  # noqa: ANN001
        self.calls += 1
        msgs = messages or []
        user = next((m.get("content", "") for m in reversed(msgs) if m.get("role") == "user"), "")
        u = user.lower()
        if "invocation spec" in u:
            payload = {"prompt": "Simulated implementation work.", "effort_level": "default",
                       "skills_to_invoke": [], "subagent": None,
                       "pre_tool_hooks": [], "post_tool_hooks": []}
        elif "corrected" in u or "plan to fix" in u:
            payload = self._plan()           # critique pass -> echo a valid plan
        else:
            payload = self._plan()           # initial plan (and any other JSON ask)
        return {"message": {"content": json.dumps(payload)}}


def simRunClaude(spec, *, work_dir=None, task_state=None, subtask=None,
                 system_prompt=None, extra=None, timeout=None, resume_session=None):
    """Fake executor. The architect phase (system_prompt set) returns a design doc long
    enough to pass the architect gate; subtask runs return a clean success envelope."""
    if system_prompt is not None:
        doc = ("# Simulated architecture\n\n" + "This is a dry-run design document. " * 20)
        return {"ok": True, "returncode": 0, "stdout": doc, "is_error": False, "session_id": None}
    sid = (subtask or {}).get("subtask_id", "?")
    return {"ok": True, "returncode": 0, "stdout": f"[sim] completed {sid}", "is_error": False,
            "session_id": None}


def simReplan(*args, **kwargs):
    return {"action": "keep", "add": [], "remove": [], "reason": "dry-run"}


def simReview(subtask_title, trigger_reason, executor_output, *, ollama_chat=None, goal=""):
    return {"verdict": "approved", "trigger_reason": trigger_reason, "concerns": [],
            "notes": "dry-run auto-approve", "stub": True}


class SimObs:
    """In-memory Obsidian double: records writes, never touches disk or REST."""

    def __init__(self):
        self.notes: dict[str, str] = {}

    def writeNote(self, rel_path: str, content: str) -> dict:
        self.notes[rel_path] = content
        return {"ok": True, "via": "sim", "rel_path": rel_path}

    def appendNote(self, rel_path: str, content: str) -> dict:
        self.notes[rel_path] = self.notes.get(rel_path, "") + content
        return {"ok": True, "via": "sim", "rel_path": rel_path}

    def readNote(self, rel_path: str):
        return self.notes.get(rel_path)

    def health(self) -> dict:
        return {"rest_ok": False, "authed": False}


def buildOrchestrator(n_subtasks: int = 3):
    """An Orchestrator wired entirely with simulation doubles (no external services)."""
    from orchestrator import Orchestrator
    return Orchestrator(brain=SimBrain(n_subtasks=n_subtasks), obs=SimObs(),
                        run_claude=simRunClaude, replan=simReplan, review=simReview)


# ---------------------------------------------------------------------------
# Higher-fidelity "builder" doubles: produce REAL files in a chosen work_dir and
# verify them for real (real subprocess), so a dry-run exercises the work-dir +
# verification paths against an actual project tree -- not just no-ops.
# ---------------------------------------------------------------------------
import re as _re
from pathlib import Path as _Path


class BuilderBrain:
    """Plans N subtasks, each producing a real file under ``work_dir`` with a REAL
    behavioral verify (``python <file>`` / exit_zero). Captures work_dir so the verify
    paths are absolute and runnable."""

    def __init__(self, work_dir: str, n_subtasks: int = 3):
        self.work = str(work_dir)
        self.n = max(1, n_subtasks)

    def _plan(self) -> dict:
        subs = []
        for i in range(1, self.n + 1):
            target = str(_Path(self.work) / f"feature_{i}.py")
            subs.append({"title": f"build feature {i}", "description": f"create {target}",
                         "layer": 3, "effort_level": "default",
                         "verify": {"cmd": f'python "{target}"', "expect": "exit_zero"}})
        return {"subtasks": subs}

    def chat(self, *, model=None, messages=None, **kwargs):
        user = next((m.get("content", "") for m in (messages or []) if m.get("role") == "user"), "")
        if "invocation spec" in user.lower():
            return {"message": {"content": json.dumps(
                {"prompt": "Write the target file so it runs cleanly.", "effort_level": "default"})}}
        return {"message": {"content": json.dumps(self._plan())}}


def builderRunClaude(spec, *, work_dir=None, task_state=None, subtask=None,
                     system_prompt=None, extra=None, timeout=None, resume_session=None):
    """Fake hands that ACTUALLY write the target file parsed from the subtask's verify cmd,
    so the real verify (`python <file>`) passes. Architect phase returns a design doc."""
    if system_prompt is not None:
        return {"ok": True, "returncode": 0, "stdout": "# design\n" + "doc " * 60,
                "is_error": False, "session_id": None}
    cmd = ((subtask or {}).get("verify") or {}).get("cmd") or ""
    m = _re.search(r'python\s+"([^"]+)"', cmd)
    sid = (subtask or {}).get("subtask_id", "?")
    if m:
        try:
            p = _Path(m.group(1))
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f'"""Built by 9to5 builder-sim for {sid}."""\nprint("{sid} ok")\n',
                         encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "returncode": 1, "stdout": f"write failed: {e}",
                    "is_error": True, "session_id": None}
    return {"ok": True, "returncode": 0, "stdout": f"[builder] wrote artifact for {sid}",
            "is_error": False, "session_id": None}


def buildBuilderOrchestrator(work_dir: str, n_subtasks: int = 3):
    """An Orchestrator that produces real artifacts under work_dir and verifies them for real."""
    from orchestrator import Orchestrator
    return Orchestrator(brain=BuilderBrain(work_dir, n_subtasks), obs=SimObs(),
                        run_claude=builderRunClaude, replan=simReplan, review=simReview)
