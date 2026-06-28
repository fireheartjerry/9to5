import pytest
from agents.discovery.models import Finding, DiscoveryReport


def test_finding_roundtrip():
    f = Finding(
        title="Rewrite orchestrator",
        type="reimagining",
        impact=5, specificity=4, innovation=5,
        rationale="Current approach is deeply coupled",
        affected_files=["orchestrator.py"],
        source_lens="lens_3",
    )
    d = f.to_dict()
    assert d["title"] == "Rewrite orchestrator"
    assert d["innovation"] == 5
    assert d["composes_with"] == []


def test_finding_defaults():
    f = Finding(title="Fix TODOs", type="health", impact=2, specificity=3,
                innovation=1, rationale="r", affected_files=[], source_lens="lens_1")
    assert f.composes_with == []
    assert f.rank is None


def test_discovery_report_innovation_ratio():
    findings = [
        Finding("A", "reimagining", 5, 4, 5, "r", [], "lens_3"),
        Finding("B", "health", 3, 3, 1, "r", [], "lens_1"),
        Finding("C", "new_capability", 4, 4, 4, "r", [], "lens_4"),
    ]
    report = DiscoveryReport(theme_suggestion="bold theme", findings=findings)
    # 2 out of 3 have innovation >= 3 -> ratio = 0.67
    assert abs(report.innovation_ratio - 2/3) < 0.01


def test_discovery_report_to_dict():
    report = DiscoveryReport(theme_suggestion="t", findings=[])
    d = report.to_dict()
    assert d["theme_suggestion"] == "t"
    assert d["findings"] == []
    assert "innovation_ratio" in d
