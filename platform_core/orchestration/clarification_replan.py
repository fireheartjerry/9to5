"""Clarification-block replanning helpers.

@AI-MAP v1
EXPORTS:
  blockedClarificationDecision(subtask: dict, result: dict) -> dict
DEPENDS-ON: config
SIDE-EFFECTS: none
RUN/TEST: python -m pytest tests/orchestration/test_clarification_replan.py
"""
from __future__ import annotations

import config

LOG = config.getLogger("orchestrator.clarification_replan")


def _question_lines(clarification: dict) -> list[str]:
    lines: list[str] = []
    for rec in (clarification or {}).get("records") or []:
        q = str(rec.get("question_text") or "").strip()
        if not q:
            continue
        labels = ", ".join(str(x) for x in (rec.get("options") or []) if x)
        risk = rec.get("risk") or "unknown"
        decision_id = rec.get("decision_id") or rec.get("question_hash") or "unknown_decision"
        lines.append(f"- {decision_id} [{risk}]: {q}" + (f" Options: {labels}." if labels else ""))
    return lines


def blockedClarificationDecision(subtask: dict, result: dict) -> dict:
    """Create a read-only probe subtask for a high-risk unresolved clarification block."""
    clarification = (result or {}).get("clarification") or {}
    lines = _question_lines(clarification)
    title = "Read-only probe for blocked clarification"
    if subtask.get("title"):
        title += f": {str(subtask.get('title'))[:80]}"
    desc = (
        "Inspect the codebase and available tests to gather evidence for the blocked "
        "clarification decision. Do not modify files. Do not run destructive commands. "
        "Do not implement the follow-up change. Produce a concise evidence summary answering "
        "whether the blocked decision is allowed, what constraints apply, and what acceptance "
        "check should gate the follow-up implementation.\n\n"
        "Blocked clarification:\n"
        + ("\n".join(lines) if lines else "- (no structured questions recorded)")
    )
    return {
        "action": "mutate",
        "add": [{
            "title": title,
            "description": desc,
            "layer": subtask.get("layer", 3),
            "verify": None,
            "files_touched": [],
            "read_only": True,
            "clarification_probe": True,
        }],
        "remove": [],
        "reason": "blocked_clarification -> launch_readonly_probe",
    }
