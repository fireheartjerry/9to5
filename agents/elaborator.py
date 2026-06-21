"""Elaborator (Step 0.5) -- Ollama expands the raw goal into a buildable spec.

This is an Orchestrator-brain step: it runs entirely on the local model and
produces the text a human approves before the autonomous run begins.
"""
from __future__ import annotations

import json

import ollama

import config

LOG = config.getLogger("elaborator")
_OLLAMA = ollama.Client(host=config.OLLAMA_HOST, timeout=config.OLLAMA_TIMEOUT_SECONDS)

ELABORATOR_SYSTEM = (
    "You are the Elaborator for 9TO5, an autonomous engineering orchestrator. "
    "Expand the user's raw goal into a precise, buildable specification a coding agent "
    "can execute without further questions. Use markdown. Include these sections: "
    "Objective; Deliverables (with exact absolute file paths); Acceptance Criteria; "
    "Constraints; Assumptions. Be concrete and concise. Output ONLY the specification, "
    "no preamble, no questions."
)


def elaborate(goal_raw: str) -> str:
    """Return the elaborated specification for ``goal_raw``."""
    LOG.info("Elaborating raw goal via %s", config.OLLAMA_MODEL)
    resp = _OLLAMA.chat(
        model=config.OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": ELABORATOR_SYSTEM},
            {"role": "user", "content": f"Raw goal:\n{goal_raw}\n\nProduce the elaborated specification."},
        ],
    )
    return resp["message"]["content"].strip()


UNIVERSE_SYSTEM = (
    "You define the operating UNIVERSE (scope boundary) for an autonomous engineering run. "
    'Respond with JSON ONLY: {"description": "<one line>", "allowed_paths": ["<files/folders in '
    'scope>"], "allowed_to_expand_to": ["<dependencies that may need touching>"], "hard_boundaries": '
    '["<files/dirs that must NEVER be touched>"]}. allowed_paths = exactly what this goal should '
    "create/edit. hard_boundaries = secrets, VCS internals, and unrelated code (e.g. .env, .git, venv). "
    "Use concrete absolute paths where known. Output ONLY the JSON."
)


def extractUniverse(goal_raw: str, goal_elaborated: str, work_dir: str) -> dict:
    """Extract the operating universe (scope boundary) from the goal (with safe defaults)."""
    user = (f"Goal:\n{goal_raw}\n\nElaborated spec:\n{goal_elaborated[:2000]}\n\n"
            f"Working directory: {work_dir}\n\nReturn the universe JSON.")
    try:
        resp = _OLLAMA.chat(model=config.OLLAMA_MODEL,
                            messages=[{"role": "system", "content": UNIVERSE_SYSTEM},
                                      {"role": "user", "content": user}], format="json")
        u = json.loads(resp["message"]["content"]) or {}
    except Exception as e:  # noqa: BLE001
        LOG.warning("extractUniverse failed (%s); using defaults", e)
        u = {}
    if not isinstance(u, dict):
        u = {}
    u.setdefault("description", goal_raw[:200])
    u.setdefault("allowed_paths", [work_dir])
    u.setdefault("allowed_to_expand_to", [])
    hb = [str(x) for x in (u.get("hard_boundaries") or []) if x]
    for d in config.UNIVERSE_DEFAULT_HARD_BOUNDARIES:   # always enforce the baseline boundaries
        if d not in hb:
            hb.append(d)
    u["hard_boundaries"] = hb
    return u
