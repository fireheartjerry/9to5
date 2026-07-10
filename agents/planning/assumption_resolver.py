"""AssumptionResolver -- grounded answers for Claude clarification questions.

@AI-MAP v1
EXPORTS:
  extractQuestionBlock(text: str) -> list[dict]
  validateQuestions(questions: list[dict]) -> tuple[list[dict], list[str]]
  resolveQuestions(chat, goal: str, subtask: dict, questions: list[dict], memory=None) -> dict
  buildResumeFeedback(resolved: dict) -> str
DEPENDS-ON: config, llm_io
SIDE-EFFECTS: none
RUN/TEST: python -m pytest tests/orchestration/test_assumption_resolver.py
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Callable

import config
import llm_io
from agents.planning import question_memory

LOG = config.getLogger("clarification.resolver")

START = "QUESTION_BLOCK_START"
END = "QUESTION_BLOCK_END"


def questionHash(question_text: str) -> str:
    norm = re.sub(r"\s+", " ", (question_text or "").strip().lower())
    return "sha256:" + hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def decisionId(question: dict, answer: dict | None = None) -> str:
    raw = (question or {}).get("decision_id") or (answer or {}).get("decision_id") or ""
    norm = re.sub(r"[^a-z0-9_]+", "_", str(raw).strip().lower()).strip("_")
    return norm[:96]


def extractQuestionBlock(text: str) -> list[dict]:
    if not text or START not in text or END not in text:
        return []
    raw = text.split(START, 1)[1].split(END, 1)[0].strip()
    try:
        data = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        LOG.info("invalid clarification question block: %s", e)
        return []
    if isinstance(data, dict) and isinstance(data.get("questions"), list):
        data = data["questions"]
    return [q for q in data if isinstance(q, dict)] if isinstance(data, list) else []


def _labels(q: dict) -> list[str]:
    return [str(o.get("label")) for o in (q.get("options") or []) if isinstance(o, dict) and o.get("label")]


def validateQuestions(questions: list[dict]) -> tuple[list[dict], list[str]]:
    valid: list[dict] = []
    errors: list[str] = []
    for i, q in enumerate((questions or [])[: config.CLARIFICATION_MAX_QUESTIONS], 1):
        text = str(q.get("question") or "").strip()
        labels = _labels(q)
        if q.get("multiSelect") is True:
            errors.append(f"q{i}: multiSelect is not supported in v1")
            continue
        if not text or re.search(r"\bshould i proceed\b|\bdo you want me to proceed\b", text, re.I):
            errors.append(f"q{i}: non-material question")
            continue
        if config.CLARIFICATION_DECISION_ID_REQUIRED and not decisionId(q):
            errors.append(f"q{i}: decision_id is required")
            continue
        if not (2 <= len(labels) <= 4):
            errors.append(f"q{i}: expected 2-4 labeled options")
            continue
        if len(set(labels)) != len(labels):
            errors.append(f"q{i}: duplicate option labels")
            continue
        valid.append(q)
    if len(questions or []) > config.CLARIFICATION_MAX_QUESTIONS:
        errors.append("question cap exceeded; extra questions ignored")
    return valid, errors


_RESOLVER_SYSTEM = (
    "You are 9to5's AssumptionResolver. Select an answer ONLY when grounded in the goal, "
    "subtask, acceptance check, repo conventions, or prior failures. You are not the user. "
    "Return JSON only: {\"answers\":[{\"question_text\":...,\"decision_id\":...,\"decision_kind\":...,"
    "\"type\":\"resolved|assumption|unresolved\",\"selected_label\":...,\"confidence\":0..1,"
    "\"risk\":\"low|medium|high\",\"risk_source\":[...],"
    "\"basis\":...,\"source\":...,\"requires_human\":bool}]}. selected_label must be one of the provided labels, "
    "or null for unresolved."
)


def _heuristic(q: dict) -> dict:
    text = (q.get("question") or "").lower()
    labels = _labels(q)
    risk = str(q.get("risk") or "medium").lower()
    high = risk == "high" or any(w in text for w in ("delete", "drop", "migration", "breaking", "security", "api"))
    if high and not config.CLARIFICATION_HIGH_RISK_HEURISTIC_ASSUMPTIONS:
        return {
            "type": "unresolved", "selected_label": None, "confidence": 0.0,
            "risk": "high", "risk_source": ["high_risk_unknown"],
            "basis": "High-risk decision has no grounded resolver answer.",
            "source": "unknown", "requires_human": True,
        }
    for label in labels:
        low = label.lower()
        if any(w in low for w in ("preserve", "compat", "no destructive", "adapter", "internal")):
            return {
                "type": "assumption", "selected_label": label, "confidence": 0.62,
                "risk": risk if risk in ("low", "medium", "high") else "medium",
                "risk_source": ["conservative_option"], "basis": "Conservative compatible option available.",
                "source": "repo_convention", "requires_human": False,
            }
    return {
        "type": "unresolved", "selected_label": None, "confidence": 0.0,
        "risk": "high" if high else risk, "risk_source": ["unknown"],
        "basis": "No grounded source determines this decision.", "source": "unknown",
        "requires_human": bool(high),
    }


def _parseBrainAnswers(resp) -> list[dict]:
    text = llm_io.responseText(resp).strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except Exception:
            return []
    answers = data.get("answers") if isinstance(data, dict) else None
    return [a for a in answers if isinstance(a, dict)] if isinstance(answers, list) else []


def resolveQuestions(chat: Callable, goal: str, subtask: dict, questions: list[dict],
                     memory: dict | None = None) -> dict:
    valid, errors = validateQuestions(questions)
    records: list[dict] = []
    reused = 0
    unresolved_high = False
    answer_map: dict[str, str] = {}
    brain_answers: list[dict] = []
    if valid:
        user = json.dumps({
            "goal": (goal or "")[:1500],
            "subtask": {
                "id": subtask.get("subtask_id"),
                "title": subtask.get("title"),
                "description": (subtask.get("description") or "")[:1200],
                "verify": subtask.get("verify") or {},
            },
            "questions": valid,
            "prior_answers": (memory or {}).get("clarification_memory", []),
        }, ensure_ascii=False)
        try:
            brain_answers = _parseBrainAnswers(chat(_RESOLVER_SYSTEM, user, act="clarification_resolve", want_json=True))
        except TypeError:
            try:
                brain_answers = _parseBrainAnswers(chat(_RESOLVER_SYSTEM, user))
            except Exception as e:  # noqa: BLE001
                LOG.info("assumption resolver chat failed: %s", e)
        except Exception as e:  # noqa: BLE001
            LOG.info("assumption resolver chat failed: %s", e)
    by_text = {str(a.get("question_text") or ""): a for a in brain_answers}
    for q in valid:
        qtext = str(q.get("question") or "")
        labels = _labels(q)
        prior = question_memory.findReusable(memory or {}, q)
        if prior:
            ans = dict(prior)
            ans["question_text"] = qtext
            ans["selected_label"] = question_memory.mapLabel(ans.get("selected_label"), labels)
            reused += 1
        else:
            ans = dict(by_text.get(qtext) or _heuristic(q))
        selected = ans.get("selected_label")
        if selected not in labels:
            if config.CLARIFICATION_REQUIRE_OPTION_LABEL_MATCH or ans.get("type") != "unresolved":
                ans = {
                    "type": "unresolved", "selected_label": None, "confidence": 0.0,
                    "risk": ans.get("risk") or q.get("risk") or "medium",
                    "risk_source": ["option_label_mismatch"],
                    "basis": "Resolver selected_label did not exactly match current option labels.",
                    "source": "validation", "requires_human": True,
                }
        rec = {
            "decision_id": decisionId(q, ans),
            "decision_kind": q.get("decision_kind") or ans.get("decision_kind") or "",
            "question_hash": questionHash(qtext),
            "question_text": qtext,
            "selected_label": ans.get("selected_label"),
            "confidence": float(ans.get("confidence") or 0.0),
            "risk": ans.get("risk") or q.get("risk") or "medium",
            "risk_source": ans.get("risk_source") or [],
            "basis": ans.get("basis") or "",
            "source": ans.get("source") or "unknown",
            "requires_human": bool(ans.get("requires_human")),
            "type": ans.get("type") or "unresolved",
            "options": labels,
        }
        if rec["type"] == "unresolved" and rec["risk"] == "high":
            unresolved_high = True
        if rec["selected_label"]:
            answer_map[qtext] = rec["selected_label"]
        records.append(rec)
    return {
        "ok": bool(records) and not unresolved_high,
        "blocked": bool(unresolved_high and config.CLARIFICATION_HIGH_RISK_UNKNOWN == "block"),
        "reason": "high_risk_unknown" if unresolved_high else None,
        "answers": answer_map,
        "records": records,
        "errors": errors,
        "reused": reused,
    }


def buildResumeFeedback(resolved: dict) -> str:
    lines = ["Resolved clarification answers:"]
    for i, rec in enumerate(resolved.get("records") or [], 1):
        lines += [
            f"{i}. {rec.get('question_text')}",
            f"Answer: {rec.get('selected_label')}",
            f"Basis: {rec.get('basis')}",
            f"Confidence: {rec.get('confidence')}",
            f"Risk: {rec.get('risk')} ({', '.join(rec.get('risk_source') or [])})",
            f"Assumption: {str(rec.get('type') == 'assumption').lower()}",
            "",
        ]
    lines.append("Proceed using these decisions. Do not ask duplicate questions.")
    return "\n".join(lines).strip()
