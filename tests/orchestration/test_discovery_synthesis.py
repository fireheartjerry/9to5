import json
from unittest import mock

from agents.discovery import synthesis as syn_mod
from agents.discovery.models import Finding, DiscoveryReport


def _make_finding(title, impact=3, specificity=3, innovation=3,
                  ftype="health", source="lens_1"):
    return Finding(title=title, type=ftype, impact=impact, specificity=specificity,
                   innovation=innovation, rationale="r", affected_files=[], source_lens=source)


def _mock_ollama(theme="Harden the orchestrator"):
    resp = {"message": {"content": json.dumps({
        "theme_suggestion": theme,
    })}}
    return mock.Mock(chat=mock.Mock(return_value=resp))


def test_synthesize_returns_discovery_report():
    findings = [_make_finding(f"Finding {i}", innovation=4) for i in range(5)]
    with mock.patch.object(syn_mod.llm_io, "getClient", return_value=_mock_ollama()):
        report = syn_mod.synthesize(findings)
    assert isinstance(report, DiscoveryReport)
    assert report.theme_suggestion


def test_innovation_floor_enforced():
    """If <40% innovative, report must still have >=40% after re-ranking."""
    findings = (
        [_make_finding(f"Trivial {i}", innovation=1) for i in range(7)] +
        [_make_finding(f"Bold {i}", innovation=5, ftype="reimagining") for i in range(3)]
    )
    with mock.patch.object(syn_mod.llm_io, "getClient", return_value=_mock_ollama()):
        report = syn_mod.synthesize(findings)
    assert report.innovation_ratio >= 0.4


def test_low_specificity_filtered_out():
    findings = [
        _make_finding("Too vague", specificity=1),
        _make_finding("Concrete fix", specificity=4),
    ]
    with mock.patch.object(syn_mod.llm_io, "getClient", return_value=_mock_ollama()):
        report = syn_mod.synthesize(findings)
    titles = [f.title for f in report.findings]
    assert "Too vague" not in titles


def test_empty_findings_returns_empty_report():
    with mock.patch.object(syn_mod.llm_io, "getClient", return_value=_mock_ollama()):
        report = syn_mod.synthesize([])
    assert report.findings == []


def test_dedup_near_identical_titles():
    findings = [
        _make_finding("Fix the run loop", specificity=4, innovation=3),
        _make_finding("Fix the run loop", specificity=4, innovation=3),
        _make_finding("Fix the run loop (duplicate)", specificity=4, innovation=3),
    ]
    with mock.patch.object(syn_mod.llm_io, "getClient", return_value=_mock_ollama()):
        report = syn_mod.synthesize(findings)
    titles = [f.title for f in report.findings]
    assert len(titles) <= 2
