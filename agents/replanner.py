"""Replanner -- Ollama decides whether to mutate the subtask list.

Called after every subtask with the executor output plus the full task state.
Returns a decision dict; the Orchestrator applies any mutation and logs the diff
to ``replan-log.md``.
"""
from __future__ import annotations

import json

import ollama

import config

LOG = config.getLogger("replanner")
_OLLAMA = ollama.Client(host=config.OLLAMA_HOST)

REPLANNER_SYSTEM = (
    "You are the Replanner for 9TO5. Given the goal, the current subtask list, "
    "the subtask that just finished, and its executor output, decide whether the remaining "
    "plan should change. Prefer keeping the plan stable; only mutate when the output clearly "
    "reveals a missing or obsolete step. "
    "CRITICAL: honor the goal's stated constraints. Never add steps that install "
    "dependencies, create virtualenvs, or use tools the goal forbids -- e.g. if the goal says "
    "'standard library only', do NOT add a 'pip install' or 'add pytest' step. "
    "Do NOT add subtasks to FIX a failed verification -- the executor already retries failures "
    "automatically. Only add a subtask for genuinely MISSING scope, and keep the total tiny. "
    "Verify commands must use ONLY the Python standard library (no pycodestyle/pytest/etc). "
    "Strongly prefer action 'keep'. "
    'Respond with JSON ONLY in this exact shape: '
    '{"action": "keep" | "mutate", '
    '"add": [{"title": "...", "description": "...", '
    '"verify": {"cmd": "<shell command run in the work dir>", "expect": "exit_zero"}}], '
    '"remove": ["st-00X"], "reason": "..."}. '
    "Every added subtask MUST include a verify block; expect is one of "
    "exit_zero | stdout_contains:<text> | stdout_regex:<pattern>. Make verify commands "
    "PORTABLE: prefer `python -c \"...\"`; never use bash-only syntax such as <(...) or "
    "`echo -n` (the host shell is Windows cmd.exe)."
)


def replan(goal_elaborated: str, subtasks: list[dict], last_subtask: dict, executor_output: str) -> dict:
    """Return the replan decision dict (always well-formed)."""
    brief = [{k: s.get(k) for k in ("subtask_id", "title", "status")} for s in subtasks]
    user = (
        f"Goal:\n{goal_elaborated}\n\n"
        f"Current subtasks:\n{json.dumps(brief, indent=2)}\n\n"
        f"Just-finished: {last_subtask.get('subtask_id')} - {last_subtask.get('title')}\n"
        f"Executor output (truncated):\n{(executor_output or '')[:2000]}\n\n"
        "Return the replan JSON."
    )
    try:
        resp = _OLLAMA.chat(
            model=config.OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": REPLANNER_SYSTEM},
                {"role": "user", "content": user},
            ],
            format="json",
        )
        data = json.loads(resp["message"]["content"])
        data.setdefault("action", "keep")
        data.setdefault("add", [])
        data.setdefault("remove", [])
        data.setdefault("reason", "")
        return data
    except Exception as e:  # noqa: BLE001
        LOG.warning("replan failed/unparseable (%s); keeping plan", e)
        return {"action": "keep", "add": [], "remove": [], "reason": f"replan-error: {e}"}
