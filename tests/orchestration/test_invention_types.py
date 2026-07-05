"""Inventor pipeline dataclasses: coercion, clamping, fitness, and JSON round-trips.

These are the shared types every Track (A finders, B QD archive, C report, D optimizers)
passes around, so their normalization + round-trip contract is load-bearing.
"""
from platform_core.orchestration import invention_types as t


def test_clamp01_bounds():
    assert t.clamp01(-3) == 0.0
    assert t.clamp01(0.4) == 0.4
    assert t.clamp01(9) == 1.0
    assert t.clamp01("nope") == 0.0   # never raises


def test_norm_risk_and_blast():
    assert t.norm_risk("med") == "medium"
    assert t.norm_risk("HIGH") == "high"
    assert t.norm_risk("garbage") == "medium"
    assert t.norm_blast("Large") == "large"
    assert t.norm_blast("") == "medium"


def test_fitness_weights_sum_to_one():
    assert abs(sum(t.FITNESS_WEIGHTS.values()) - 1.0) < 1e-9
    perfect = {k: 1.0 for k in t.FITNESS_WEIGHTS}
    assert t.fitness_of(perfect) == 1.0
    assert t.fitness_of({}) == 0.0
    # verification dominates: a verify-only elite outscores an adoption-only one.
    assert t.fitness_of({"verification_score": 1.0}) > t.fitness_of({"adoption_score": 1.0})


def test_finding_candidate_coerces_and_clamps():
    fc = t.FindingCandidate.from_dict({
        "id": "f1", "kind": "bogus", "title": "T", "risk": "med",
        "impact": 5.0, "confidence": -1, "design_sketch": "do X",
        "target_subsystems": ["memory"], "junk_key": 1,
    })
    assert fc.kind == "feature"         # unknown kind -> default
    assert fc.risk == "medium"
    assert fc.impact == 1.0             # clamped
    assert fc.confidence == 0.0
    assert fc.has_sketch() is True


def test_finding_without_sketch_is_not_routable():
    assert t.FindingCandidate(id="x", title="T", design_sketch="", target_subsystems=[]).has_sketch() is False
    assert t.FindingCandidate(id="x", title="T", design_sketch="plan", target_subsystems=[]).has_sketch() is False


def test_qd_cell_key_is_deterministic():
    c1 = t.QDCell(capability_type="workflow_acceleration", subsystem="memory")
    c2 = t.QDCell(capability_type="workflow_acceleration", subsystem="memory")
    assert c1.key() == c2.key()
    assert c1.key() != t.QDCell(subsystem="notifications").key()
    assert hash(c1) == hash(c2)         # frozen + hashable


def test_qd_elite_roundtrip_preserves_nested_cell():
    e = t.QDElite(id="e1", candidate_id="f1", cell=t.QDCell(subsystem="explore"),
                  fitness=0.7, metrics={"verification_score": 1.0}, evidence_refs=["r1"])
    back = t.QDElite.from_dict(e.to_dict())
    assert back.cell.subsystem == "explore"
    assert back.fitness == 0.7
    assert back.evidence_refs == ["r1"]


def test_emitter_allocation_normalizes_emitter():
    assert t.EmitterAllocation(emitter="bogus").emitter == "ollama"
    assert t.EmitterAllocation(emitter="claude").emitter == "claude"


def test_portfolio_selection_roundtrip():
    p = t.PortfolioSelection(selected_candidate_ids=["a", "b"],
                             dependency_edges=[["b", "a"]], objective_value=3.5)
    back = t.PortfolioSelection.from_dict(p.to_dict())
    assert back.selected_candidate_ids == ["a", "b"]
    assert back.dependency_edges == [["b", "a"]]
    assert back.objective_value == 3.5


def test_report_entry_roundtrip():
    r = t.InnovativeChangeReportEntry(title="T", claim="C", status="proposed",
                                      why_innovative={"measured_novelty": 0.8},
                                      evidence_refs=["diff:abc"])
    back = t.InnovativeChangeReportEntry.from_dict(r.to_dict())
    assert back.status == "proposed"
    assert back.why_innovative["measured_novelty"] == 0.8
    assert back.evidence_refs == ["diff:abc"]
