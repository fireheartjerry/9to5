"""ClarificationGate -- decide when executor questions are worth the cost.

@AI-MAP v1
EXPORTS:
  scoreAttempt(state, subtask, spec=None, attempt=1, context_chars=0) -> dict
  questionPolicyBlock(decision: dict) -> str
DEPENDS-ON: config
SIDE-EFFECTS: none
RUN/TEST: python -m pytest tests/orchestration/test_clarification_gate.py
"""
from __future__ import annotations

import re
from typing import Any

import config

LOG = config.getLogger("clarification.gate")

_HIGH_RISK_TERMS = (
    "delete", "drop", "remove existing", "migration", "migrate", "destructive",
    "security", "auth", "permission", "secret", "token", "public api", "breaking",
    "schema", "database", "executor", "planner", "verifier", "orchestrator",
)
_MECHANICAL_TERMS = ("typo", "copy", "comment", "single file", "one file", "rename")


def _blob(state, subtask: dict, spec: dict | None = None) -> str:
    meta = getattr(state, "meta", {}) or {}
    return " ".join(
        str(x or "") for x in (
            meta.get("goal_elaborated"), meta.get("goal_raw"),
            subtask.get("title"), subtask.get("description"),
            (subtask.get("verify") or {}).get("cmd"),
            (spec or {}).get("prompt"), (spec or {}).get("claude_md_inject"),
        )
    ).lower()


def _signal(signals: list[dict[str, Any]], name: str, delta: int) -> None:
    if delta:
        signals.append({"name": name, "delta": int(delta)})


def scoreAttempt(state, subtask: dict, spec: dict | None = None, *,
                 attempt: int = 1, context_chars: int = 0) -> dict:
    """Return an observable skip/enable/force decision with score signals."""
    signals: list[dict[str, Any]] = []
    text = _blob(state, subtask, spec)
    verify = subtask.get("verify") or {}
    meta = getattr(state, "meta", {}) or {}

    high_risk_hits = [t for t in _HIGH_RISK_TERMS if t in text]
    if high_risk_hits:
        _signal(signals, "high_risk_terms", 3)
    if meta.get("is_self_referential"):
        _signal(signals, "self_referential", 3)
    if any(t in text for t in ("executor", "planner", "verifier", "orchestrator")):
        _signal(signals, "core_agent_work", 3)
    if not verify or not verify.get("cmd"):
        _signal(signals, "missing_verify_command", 2)
    if attempt >= 2:
        _signal(signals, "retry_attempt", 2)
    if re.search(r"\b(multiple|several|many|broad|repo-wide|cross-module)\b", text):
        _signal(signals, "broad_multi_file_edit", 2)
    effort = str((spec or {}).get("effort_level") or subtask.get("effort_level") or "").lower()
    if effort in ("xhigh", "ultracode"):
        _signal(signals, "expensive_effort", 2)
    if any(t in text for t in _MECHANICAL_TERMS) and verify.get("cmd"):
        _signal(signals, "mechanical_clear_verify", -3)
    if context_chars and context_chars > 60000:
        _signal(signals, "context_payload_large", -2)

    score = sum(int(s["delta"]) for s in signals)
    if score >= config.CLARIFICATION_SCORE_FORCE_THRESHOLD:
        decision = "force"
    elif score >= config.CLARIFICATION_SCORE_ENABLE_THRESHOLD:
        decision = "enable"
    else:
        decision = "skip"
    out = {
        "decision": decision,
        "score": score,
        "signals": signals,
        "risk": "high" if high_risk_hits else ("medium" if score >= 4 else "low"),
        "risk_source": high_risk_hits,
    }
    if config.CLARIFICATION_LOG_DECISIONS:
        LOG.info("clarification gate: %s score=%s signals=%s",
                 decision, score, ",".join(s["name"] for s in signals) or "-")
    return out


def questionPolicyBlock(decision: dict) -> str:
    """Compact executor instruction for gated question use."""
    mode = (decision or {}).get("decision")
    if mode not in ("enable", "force"):
        return ""
    lead = "You MUST" if mode == "force" else "You MAY"
    return (
        "## ClarificationGate question policy\n"
        f"{lead} ask clarification questions only when the answer materially changes "
        "implementation, safety, scope, or verification. Prefer a conservative stated "
        "assumption and proceed when safe.\n"
        "If asking in CLI mode, emit exactly one JSON block between QUESTION_BLOCK_START "
        "and QUESTION_BLOCK_END. Ask at most 3 single-select questions. Each question must "
        "include `decision_id`, `decision_kind`, `question`, `options` "
        "(2-4 objects with `label` and `description`), "
        "`risk` (`low`, `medium`, or `high`), and optional `recommended_default`. "
        "Options must be mutually exclusive and implementation-actionable. Do not ask "
        "\"Should I proceed?\" or other process questions.\n"
    )
