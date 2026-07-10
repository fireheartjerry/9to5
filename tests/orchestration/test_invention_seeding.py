"""Live invention-seeding seam: algorithms affect ledger-admission provenance."""
from agents.discovery.models import Finding
from agents.discovery import ledger_bridge
from memory import experience
from memory import experience_evolution as ee
from platform_core.orchestration import invention_seeding as seeds


def _candidate(title, target, **overrides):
    data = dict(title=title, type="new_capability", impact=5, specificity=5, innovation=5,
                rationale="A concrete proposal", affected_files=[], source_lens="moonshot",
                candidate_kind="new_capability", design_sketch="implement the capability",
                verification_plan="pytest reports passed", target_subsystems=[target],
                measured_novelty=0.9, confidence=0.9, risk="low")
    data.update(overrides)
    return Finding(**data)


class _Report:
    def __init__(self, findings):
        self.findings = findings


def test_plan_seeds_runs_graph_evidence_flow_conflict_and_matching(monkeypatch):
    graph = {"a.py": ["core.py"], "b.py": ["core.py"], "core.py": []}
    monkeypatch.setattr(seeds.code_graph, "build_import_graph", lambda: graph)
    first = ledger_bridge.finding_to_candidate(_candidate("First", "core.py"))
    second = ledger_bridge.finding_to_candidate(_candidate("Second", "core.py"))
    third = ledger_bridge.finding_to_candidate(_candidate("Third", "a.py"))
    result = seeds.plan_seeds([first, second, third], ["proposal", "proposal", "proposal"])

    # Shared target is a real conflict group (rollback DSU); max-flow selects one of them.
    assert len({"seed-0", "seed-1"} & set(result["selected_ids"])) == 1
    winner = first if first.provenance["seeding"]["selected"] else second
    assert winner.provenance["blast_radius"]["bin"] == "medium"
    assert winner.provenance["seeding_evidence"]["supported"] is True
    assert winner.provenance["seeding"]["emitter_allocations"]
    assert winner.provenance["seeding"]["portfolio"]["conflicts_repaired"]
    assert result["recombination"] is not None


def test_bridge_persists_only_the_selected_invention_seed(tmp_path, monkeypatch):
    db = tmp_path / "experience.db"
    experience._reset_schema_cache()
    experience.init(db)
    monkeypatch.setattr(seeds.code_graph, "build_import_graph", lambda: {})
    report = _Report([_candidate("First", "shared.py"), _candidate("Second", "shared.py")])

    out = ledger_bridge.bridge_report(report, run_id="seed-run", db_path=db, record=False)

    assert len(out["seeding"]["selected_ids"]) == 1
    assert len(ee.fetch_candidates(kind="feature", db_path=db)) == 1
    experience._reset_schema_cache()
