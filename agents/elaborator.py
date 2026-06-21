"""Elaborator (Step 0.5) -- Ollama expands the raw goal into a buildable spec.

This is an Orchestrator-brain step: it runs entirely on the local model and
produces the text a human approves before the autonomous run begins.
"""
from __future__ import annotations

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
