"""Elaborator (Step 0.5) -- Ollama expands the raw goal into a buildable spec.

This is an Orchestrator-brain step: it runs entirely on the local model and
produces the text a human approves before the autonomous run begins.
"""
from __future__ import annotations

import json
import time

import ollama

import config
import knowledge

LOG = config.getLogger("elaborator")
_OLLAMA = ollama.Client(host=config.OLLAMA_HOST, timeout=config.OLLAMA_TIMEOUT_SECONDS)


def _chat(system: str, user: str, *, want_json: bool = False, retries: int = 3) -> str:
    """Resilient local-Ollama call with exponential backoff. Returns the content string,
    or "" after all retries fail -- so the caller can degrade instead of crashing the run
    before it even starts (this is the very first brain touch)."""
    delay = 2.0
    for attempt in range(1, retries + 1):
        try:
            kwargs = {"options": {"num_ctx": config.OLLAMA_NUM_CTX}}
            if want_json:
                kwargs["format"] = "json"
            resp = _OLLAMA.chat(model=config.OLLAMA_MODEL,
                                messages=[{"role": "system", "content": system},
                                          {"role": "user", "content": user}], **kwargs)
            return ((resp.get("message") or {}).get("content") or "").strip()
        except Exception as e:  # noqa: BLE001
            LOG.warning("elaborator Ollama call failed (%d/%d): %s", attempt, retries, e)
            if attempt < retries:
                time.sleep(delay)
                delay *= 2
    return ""


def _fallbackSpec(goal_raw: str) -> str:
    """A minimal but valid spec so the run proceeds even if elaboration is unavailable."""
    return (f"# Objective\n{goal_raw}\n\n"
            "# Deliverables\n- Implement the goal exactly as stated.\n\n"
            "# Acceptance Criteria\n- The goal is satisfied and verified.\n\n"
            "# Constraints\n- Keep changes surgical and on-scope.\n\n"
            "# Assumptions\n- (elaboration brain was unavailable; using the raw goal)\n")

ELABORATOR_SYSTEM = (
    "You are the Elaborator for 9TO5, an autonomous engineering orchestrator. "
    "Expand the user's raw goal into a precise, buildable specification a coding agent "
    "can execute without further questions. Use markdown. Include these sections: "
    "Objective; Deliverables (with exact absolute file paths); Acceptance Criteria; "
    "Constraints; Assumptions. Be concrete and concise. Output ONLY the specification, "
    "no preamble, no questions."
)


def elaborate(goal_raw: str) -> str:
    """Return the elaborated specification for ``goal_raw`` (never raises -- degrades to a
    minimal spec built from the raw goal if the brain is unavailable)."""
    LOG.info("Elaborating raw goal via %s", config.OLLAMA_MODEL)
    out = _chat(knowledge.injectCapabilities(ELABORATOR_SYSTEM),
                f"Raw goal:\n{goal_raw}\n\nProduce the elaborated specification.")
    if not out:
        LOG.warning("elaboration unavailable after retries; using raw goal as spec")
        return _fallbackSpec(goal_raw)
    return out


UNIVERSE_SYSTEM = (
    "You define the operating UNIVERSE for an autonomous engineering run. The universe is about "
    "PRECISION, not permission: the agent may freely create or modify whatever files the goal needs "
    "-- the universe just keeps its edits surgical and on-scope so they don't sprawl into unrelated "
    "code. "
    'Respond with JSON ONLY: {"description": "<one line>", "allowed_paths": ["<files/folders the work '
    'is EXPECTED to focus on>"], "allowed_to_expand_to": ["<related code/deps it may also touch if '
    'needed>"], "hard_boundaries": ["<files/dirs that must NEVER be touched>"]}. '
    "allowed_paths = the expected focus area (a precision hint, NOT a hard allowlist -- creating or "
    "editing other in-scope files to achieve the goal is fine). hard_boundaries = the ONLY hard stop: "
    "secrets, VCS internals, virtualenvs, task state (e.g. .env, .git, venv, state/tasks). "
    "Use concrete absolute paths where known. Output ONLY the JSON."
)


def extractUniverse(goal_raw: str, goal_elaborated: str, work_dir: str) -> dict:
    """Extract the operating universe (scope boundary) from the goal (with safe defaults)."""
    user = (f"Goal:\n{goal_raw}\n\nElaborated spec:\n{goal_elaborated[:2000]}\n\n"
            f"Working directory: {work_dir}\n\nReturn the universe JSON.")
    raw = _chat(knowledge.injectCapabilities(UNIVERSE_SYSTEM), user, want_json=True)
    try:
        u = json.loads(raw) if raw else {}
    except Exception as e:  # noqa: BLE001
        LOG.warning("extractUniverse parse failed (%s); using defaults", e)
        u = {}
    if not isinstance(u, dict):
        u = {}
    u["description"] = str(u.get("description") or goal_raw[:200])
    u["allowed_paths"] = [str(x) for x in (u.get("allowed_paths") or []) if x] or [work_dir]
    u["allowed_to_expand_to"] = [str(x) for x in (u.get("allowed_to_expand_to") or []) if x]
    hb = [str(x) for x in (u.get("hard_boundaries") or []) if x]
    for d in config.UNIVERSE_DEFAULT_HARD_BOUNDARIES:   # always enforce the baseline boundaries
        if d not in hb:
            hb.append(d)
    u["hard_boundaries"] = hb
    return u
