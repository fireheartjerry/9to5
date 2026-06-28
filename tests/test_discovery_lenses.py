import json
from unittest import mock
import pytest

from agents.discovery import lenses as lenses_mod
from agents.discovery.models import Finding


SAMPLE_DIGEST = {
    "repo_map": {},
    "architecture": "# Architecture\nOrchestrator runs subtasks.",
    "module_signatures": "orchestrator.py: runFull",
    "dependency_graph": "",
    "dead_code_signals": "",
    "static_signals": {"todos": "# TODO: fix this", "size_violations": ""},
    "quality": {"coverage": ""},
    "git_signals": {"churn": ""},
    "github": {"open_issues": ""},
    "institutional_memory": {"recent_lessons": [], "recent_failures": []},
    "innovation_seeds": {"vision_vs_reality": "", "parked_plans": ""},
    "leverage_signals": {"slowest_phases": ""},
    "skills_hooks": "",
    "config_signals": "",
}

VALID_FINDING = {
    "title": "Rewrite orchestrator",
    "type": "reimagining",
    "impact": 5,
    "specificity": 4,
    "innovation": 5,
    "rationale": "current approach is tightly coupled",
    "affected_files": ["orchestrator.py"],
}


def _make_ollama_response(findings: list) -> dict:
    return {"message": {"content": json.dumps({"findings": findings})}}


def test_run_lens_panel_returns_findings():
    with mock.patch.object(lenses_mod, "_getOllama") as mock_oll:
        mock_oll.return_value.chat.return_value = _make_ollama_response([VALID_FINDING])
        results = lenses_mod.run_lens_panel(SAMPLE_DIGEST)
    assert isinstance(results, list)
    assert len(results) > 0
    assert all(isinstance(f, Finding) for f in results)


def test_run_lens_panel_survives_partial_failure():
    call_count = {"n": 0}

    def flaky_chat(*a, **kw):
        call_count["n"] += 1
        if call_count["n"] % 2 == 0:
            raise RuntimeError("ollama down")
        return _make_ollama_response([VALID_FINDING])

    with mock.patch.object(lenses_mod, "_getOllama") as mock_oll:
        mock_oll.return_value.chat.side_effect = flaky_chat
        results = lenses_mod.run_lens_panel(SAMPLE_DIGEST)
    assert isinstance(results, list)


def test_brain_call_returns_empty_on_bad_json():
    with mock.patch.object(lenses_mod, "_getOllama") as mock_oll:
        mock_oll.return_value.chat.return_value = {"message": {"content": "not json"}}
        result = lenses_mod._brain_call("sys", "usr")
    assert result == []


def test_finding_with_invalid_type_is_corrected():
    bad = dict(VALID_FINDING, type="garbage")
    with mock.patch.object(lenses_mod, "_getOllama") as mock_oll:
        mock_oll.return_value.chat.return_value = _make_ollama_response([bad])
        results = lenses_mod.run_lens_panel(SAMPLE_DIGEST)
    for f in results:
        assert f.type in ("new_capability", "reimagining", "health", "memory", "ux")
