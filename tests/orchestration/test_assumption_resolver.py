import json

import pytest

from agents.planning import assumption_resolver


def _q(**kw):
    base = {
        "decision_id": "public_api_compatibility",
        "decision_kind": "api",
        "question": "Should public API compatibility be preserved?",
        "options": [
            {"label": "Preserve compatibility", "description": "Patch internals only."},
            {"label": "Allow breaking changes", "description": "Update all call sites."},
        ],
        "risk": "high",
    }
    base.update(kw)
    return base


def test_extracts_cli_question_block():
    text = "x\nQUESTION_BLOCK_START\n" + json.dumps([_q()]) + "\nQUESTION_BLOCK_END\ny"
    out = assumption_resolver.extractQuestionBlock(text)
    assert out[0]["question"].startswith("Should public")


def test_rejects_multiselect_v1():
    valid, errors = assumption_resolver.validateQuestions([_q(multiSelect=True)])
    assert valid == []
    assert any("multiSelect" in e for e in errors)


def test_accepts_sdk_shape_without_recommended_default():
    valid, errors = assumption_resolver.validateQuestions([_q()])
    assert len(valid) == 1
    assert not [e for e in errors if "recommended" in e]


def test_exact_option_label_mismatch_blocks_answer(monkeypatch):
    monkeypatch.setattr("config.CLARIFICATION_REQUIRE_OPTION_LABEL_MATCH", True, raising=False)

    def chat(_system, _user, **_kw):
        return {"message": {"content": json.dumps({"answers": [{
            "question_text": "Should public API compatibility be preserved?",
            "decision_id": "public_api_compatibility",
            "type": "resolved",
            "selected_label": "Keep API stable",
            "confidence": 0.9,
            "risk": "high",
            "risk_source": ["public_api_compatibility"],
            "basis": "x",
            "source": "acceptance_check",
            "requires_human": False,
        }]})}}

    out = assumption_resolver.resolveQuestions(chat, "goal", {"verify": {}}, [_q()])
    assert out["blocked"] is True
    assert out["records"][0]["source"] == "validation"
    assert out["records"][0]["selected_label"] is None


def test_unknown_high_risk_blocks(monkeypatch):
    monkeypatch.setattr("config.CLARIFICATION_HIGH_RISK_UNKNOWN", "block", raising=False)
    out = assumption_resolver.resolveQuestions(lambda *_a, **_k: None, "goal", {}, [
        _q(question="Can this migration drop existing rows?",
           options=[{"label": "Drop rows", "description": "Destructive."},
                    {"label": "Rewrite schema", "description": "May lose data."}],
           risk="high")
    ])
    assert out["blocked"] is True
    assert out["reason"] == "high_risk_unknown"


def test_high_risk_no_brain_answer_does_not_pick_generic_compat_heuristic(monkeypatch):
    monkeypatch.setattr("config.CLARIFICATION_HIGH_RISK_UNKNOWN", "block", raising=False)
    out = assumption_resolver.resolveQuestions(lambda *_a, **_k: None, "goal", {}, [
        _q(question="May this security API migration break compatibility?", risk="high")
    ])
    assert out["blocked"] is True
    assert out["records"][0]["selected_label"] is None
    assert out["records"][0]["risk"] == "high"


def test_high_risk_heuristic_only_when_explicitly_enabled(monkeypatch):
    monkeypatch.setattr("config.CLARIFICATION_HIGH_RISK_HEURISTIC_ASSUMPTIONS", True, raising=False)
    out = assumption_resolver.resolveQuestions(lambda *_a, **_k: None, "goal", {}, [
        _q(question="How should this migration handle existing rows?",
           options=[{"label": "No destructive changes", "description": "Preserve existing rows."},
                    {"label": "Drop rows", "description": "Destructive."}],
           risk="high")
    ])
    assert out["blocked"] is False
    assert out["records"][0]["selected_label"] == "No destructive changes"
    assert out["records"][0]["decision_id"]


def test_decision_id_required_when_configured(monkeypatch):
    monkeypatch.setattr("config.CLARIFICATION_DECISION_ID_REQUIRED", True, raising=False)
    q = _q()
    q.pop("decision_id")
    valid, errors = assumption_resolver.validateQuestions([q])
    assert valid == []
    assert any("decision_id" in e for e in errors)


def test_build_resume_feedback_includes_basis():
    resolved = {"records": [{
        "question_text": "Q?", "selected_label": "A", "basis": "Because tests",
        "confidence": 0.8, "risk": "low", "risk_source": [], "type": "resolved",
    }]}
    feedback = assumption_resolver.buildResumeFeedback(resolved)
    assert "Because tests" in feedback
    assert "Do not ask duplicate" in feedback


def test_probe_evidence_memory_unblocks_current_exact_question_key():
    session = {
        "clarification_memory": [{
            "decision_id": "migration_destructive_allowed",
            "question_text": "Can this migration drop existing rows?",
            "selected_label": "No destructive changes",
            "confidence": 0.88,
            "risk": "high",
            "risk_source": ["readonly_probe"],
            "basis": "Read-only probe found existing tests require row preservation.",
            "source": "readonly_probe",
            "requires_human": False,
            "type": "resolved",
        }]
    }

    def chat(*_a, **_k):
        raise AssertionError("prior probe evidence should be reused before brain fallback")

    out = assumption_resolver.resolveQuestions(chat, "goal", {}, [
        _q(decision_id="migration_destructive_allowed",
           question="Should existing rows be preserved during this migration?",
           options=[{"label": "No destructive changes", "description": "Preserve rows."},
                    {"label": "Drop rows", "description": "Destructive."}],
           risk="high")
    ], memory=session)
    assert out["blocked"] is False
    assert out["answers"] == {"Should existing rows be preserved during this migration?": "No destructive changes"}
    assert out["reused"] == 1
