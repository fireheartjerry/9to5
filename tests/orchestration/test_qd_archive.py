"""MAP-Elites QD archive: cell competition, Pareto frontier, hard gates, determinism."""
import config
from platform_core.orchestration.invention_types import QDCell, QDElite
from platform_core.orchestration import qd_archive as qd


def _elite(cell, eid="e", verification=1.0, novelty=0.5, refs=("r1",), **over):
    m = {"verification_score": verification, "impact_score": 0.5, "maintainability_score": 0.5,
         "adoption_score": 0.5, "cost_efficiency_score": 0.5, "reversibility_score": 0.5,
         "measured_novelty": novelty, "risk_inverse": 0.5}
    m.update(over)
    return QDElite(id=eid, candidate_id=eid, cell=cell, metrics=m, evidence_refs=list(refs))


CELL_A = QDCell(subsystem="a")
CELL_B = QDCell(subsystem="b")


def test_novelty_bin_thirds():
    assert qd.novelty_bin(0.1) == "low"
    assert qd.novelty_bin(0.5) == "medium"
    assert qd.novelty_bin(0.9) == "high"


def test_cell_for_derives_coordinate():
    c = qd.cell_for({"capability_type": "workflow_acceleration", "subsystem": "memory",
                     "measured_novelty": 0.9, "risk": "low"})
    assert c.capability_type == "workflow_acceleration"
    assert c.novelty_bin == "high" and c.risk_bin == "low"


def test_same_cell_candidates_compete_by_fitness():
    a = qd.QDArchive()
    assert a.add(_elite(CELL_A, "hi", verification=1.0))
    assert a.add(_elite(CELL_A, "lo", verification=0.2))
    assert a.champion(CELL_A.key()).id == "hi"      # higher fitness wins the cell
    assert a.coverage() == 1                          # still one cell


def test_distinct_cells_preserve_distinct_champions():
    a = qd.QDArchive()
    a.add(_elite(CELL_A, "a"))
    a.add(_elite(CELL_B, "b"))
    assert a.coverage() == 2
    assert a.champion(CELL_A.key()).id == "a"
    assert a.champion(CELL_B.key()).id == "b"


def test_pareto_preserves_non_dominated_tradeoffs():
    a = qd.QDArchive()
    a.add(_elite(CELL_A, "impactful", impact_score=0.9, maintainability_score=0.1))
    a.add(_elite(CELL_A, "clean", impact_score=0.1, maintainability_score=0.9))
    ids = {e.id for e in a.pareto(CELL_A.key())}
    assert ids == {"impactful", "clean"}             # neither dominates the other


def test_dominated_candidate_rejected_from_frontier():
    a = qd.QDArchive()
    a.add(_elite(CELL_A, "strong", impact_score=0.9, maintainability_score=0.9))
    a.add(_elite(CELL_A, "weak", impact_score=0.1, maintainability_score=0.1))
    ids = {e.id for e in a.pareto(CELL_A.key())}
    assert "weak" not in ids                          # dominated on all metrics


def test_pareto_cap_enforced():
    a = qd.QDArchive(pareto_cap=4)
    for i in range(7):                                # a mutually non-dominated tradeoff curve
        a.add(_elite(CELL_A, f"e{i}", impact_score=i / 10.0, maintainability_score=(10 - i) / 10.0))
    assert len(a.pareto(CELL_A.key())) == 4


def test_failing_verification_cannot_win():
    a = qd.QDArchive()
    assert a.add(_elite(CELL_A, "bad", verification=0.0)) is False
    assert a.coverage() == 0


def test_factless_claim_cannot_win():
    a = qd.QDArchive()
    assert a.add(_elite(CELL_A, "nofacts", refs=())) is False
    assert a.coverage() == 0


def test_explicitly_unknown_metrics_cannot_steer_enforced_archive(monkeypatch):
    monkeypatch.setattr(config, "GALAXY_R3_POLICY_ENFORCEMENT_ENABLED", True, raising=False)
    elite = _elite(CELL_A, "synthetic")
    elite.unknown_metrics = ("impact_score", "measured_novelty")
    a = qd.QDArchive()
    assert a.add(elite) is False
    assert a.coverage() == 0


def test_shadow_policy_preserves_incumbent_archive_selection(monkeypatch):
    monkeypatch.setattr(config, "GALAXY_R3_POLICY_ENFORCEMENT_ENABLED", False, raising=False)
    elite = _elite(CELL_A, "legacy")
    elite.unknown_metrics = ("impact_score", "measured_novelty")
    a = qd.QDArchive()
    assert a.add(elite) is True
    assert a.champion(CELL_A.key()).id == "legacy"


def test_coverage_and_qd_score_are_deterministic():
    def build():
        a = qd.QDArchive()
        a.add(_elite(CELL_A, "a", impact_score=0.8))
        a.add(_elite(CELL_B, "b", impact_score=0.6))
        return a
    a1, a2 = build(), build()
    assert a1.coverage() == a2.coverage() == 2
    assert a1.qd_score() == a2.qd_score()


def test_diverse_elites_from_distinct_cells():
    a = qd.QDArchive()
    a.add(_elite(CELL_A, "a"))
    a.add(_elite(CELL_B, "b"))
    elites = a.diverse_elites(5)
    assert {e.id for e in elites} == {"a", "b"}
