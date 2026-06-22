"""Replanner -- Ollama decides whether to mutate the subtask list.

Called after every subtask with the executor output plus the full task state.
Returns a decision dict; the Orchestrator applies any mutation and logs the diff
to ``replan-log.md``. Internalizes the self-improvement philosophy: the question
is not "what is next on the list" but "what is the highest-impact thing to do
right now given what we just learned".
"""
from __future__ import annotations

import json

import ollama

import config
import knowledge

LOG = config.getLogger("replanner")
_OLLAMA = ollama.Client(host=config.OLLAMA_HOST, timeout=config.OLLAMA_TIMEOUT_SECONDS)

REPLANNER_SYSTEM = (
    "You are the Replanner for 9TO5. After each subtask, decide whether the remaining plan should "
    "change. Frame EVERY decision as: what is the HIGHEST-IMPACT thing to do right now given what we "
    "just learned -- NOT 'what is next on a list'. Prefer keeping the plan stable; only mutate when the "
    "output clearly reveals a missing, obsolete, or newly-discovered higher-impact step. "
    "Honor the goal's constraints (e.g. 'standard library only' => no installs). Do NOT add subtasks to "
    "FIX a failed verification (the executor already retries). Keep the total small. "
    'Respond with JSON ONLY: {"action": "keep" | "mutate", "add": [{"title": "...", "description": "...", '
    '"verify": {"cmd": "python <ABSOLUTE path>", "expect": "exit_zero"}}], "remove": ["st-00X"], '
    '"reason": "..."}. Every added verify must be BEHAVIORAL with ABSOLUTE paths: '
    "'python <abs>' (exit_zero), 'python <abs>' (stdout_contains:<a certain string>), or an "
    "os.path.getsize non-empty check. NEVER import a project module or guess an internal symbol; "
    "NEVER use grep/cat/test/findstr/type."
)


def replan(goal_elaborated: str, subtasks: list[dict], last_subtask: dict, executor_output: str,
           self_referential: bool = False, remaining_hours: "float | None" = None) -> dict:
    """Return the replan decision dict (always well-formed)."""
    brief = [{k: s.get(k) for k in ("subtask_id", "title", "status")} for s in subtasks]
    # Time-budget awareness: near the deadline, adding work just produces subtasks that never run
    # (the execution loop stops at deadline_at). Tell the brain to wind down.
    budget = ""
    if remaining_hours is not None:
        budget = (f"Time budget: ~{remaining_hours:.2f}h remain before the deadline. "
                  + ("UNDER 30 MIN LEFT: prefer action='keep' and finalize; do NOT add subtasks.\n\n"
                     if remaining_hours < 0.5 else "Only add a subtask if it clearly fits in the remaining time.\n\n"))
    user = (
        f"Goal:\n{goal_elaborated}\n\n"
        f"{budget}"
        f"Current subtasks:\n{json.dumps(brief, indent=2)}\n\n"
        f"Just-finished: {last_subtask.get('subtask_id')} - {last_subtask.get('title')}\n"
        f"Executor output (truncated):\n{(executor_output or '')[:2000]}\n\n"
        "Return the replan JSON."
    )
    system = REPLANNER_SYSTEM
    if self_referential:
        # self-improvement runs replan by impact, not by checklist
        system = config.SELF_IMPROVEMENT_PHILOSOPHY + "\n\n" + REPLANNER_SYSTEM
    try:
        resp = _OLLAMA.chat(
            model=config.OLLAMA_MODEL,
            messages=[{"role": "system", "content": knowledge.injectCapabilities(system)},
                      {"role": "user", "content": user}],
            format="json",
            options={"num_ctx": config.OLLAMA_NUM_CTX},
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
