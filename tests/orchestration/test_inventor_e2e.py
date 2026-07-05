"""End-to-end inventor pipeline: lenses -> synthesis -> bridge -> QD archive -> report -> gate.

Runs the whole chain offline (LLM seam + embeddings faked), proving the pieces compose:
feature findings become ledger seeds, verified inventions become fact-backed report entries,
and the autonomy gate makes the final auto-run/proposal call.
"""
import hashlib
import re
from types import SimpleNamespace

import pytest

import config
from agents.discovery import lenses, synthesis, ledger_bridge
from memory import experience
from memory import experience_evolution as ee
from memory.novelty_store import MemoryNoveltyStore
from platform_core.orchestration import innovation_report as ir
from platform_core.orchestration import invention_gate as ig
from platform_core.orchestration import qd_archive as qd
from platform_core.orchestration.invention_types import QDCell, QDElite


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "exp.db"
    experience._reset_schema_cache()
    experience.init(p)
    yield p
    experience._reset_schema_cache()


def _fake_embed(text):
    toks = re.findall(r"[a-z]+", (text or "").lower())
    if not toks:
        return None
    v = [0.0] * 64
    for t in toks:
        v[int(hashlib.md5(t.encode()).hexdigest(), 16) % 64] += 1.0
    return v


_FEATURE = {"title": "Self-refreshing invention corpus", "type": "new_capability",
            "candidate_kind": "new_capability", "impact": 5, "specificity": 5, "innovation": 5,
            "confidence": 0.9, "risk": "low", "target_subsystems": ["agents/discovery/corpus.py"],
            "design_sketch": "write a corpus card from each shipped invention",
            "verification_plan": "assert a card is produced and retrievable"}


def test_full_inventor_pipeline(db, monkeypatch):
    # 1. Discovery lenses (transformative) produce a concrete new-capability finding.
    monkeypatch.setattr(lenses, "_brain_call", lambda system, user, retries=2, chat=None: [_FEATURE])
    monkeypatch.setattr(lenses, "_corpus_for", lambda d: "PRIOR ART")
    findings = lenses.run_lens_panel({"architecture": "x"}, None, transformative=True)
    assert any(f.candidate_kind == "new_capability" for f in findings)

    # 2. Synthesis ranks them; simulate a novelty-measured environment (Ollama absent offline).
    def _measured(fs):
        for f in fs:
            f.measured_novelty = 0.9
        return True
    monkeypatch.setattr(synthesis, "_apply_measured_novelty", _measured)
    monkeypatch.setattr(synthesis, "_get_theme", lambda fs, chat=None: "invention layer")
    report = synthesis.synthesize(findings)
    assert report.findings and report.findings[0].design_sketch
    assert report.findings[0].measured_novelty == 0.9

    # 3. Bridge routes findings into the ledger as feature seeds.
    store = MemoryNoveltyStore()
    out = ledger_bridge.bridge_report(report, run_id="r1", db_path=db,
                                      embed_fn=_fake_embed, store=store)
    assert out["counts"]["auto_run_eligible"] >= 1
    feats = ee.fetch_candidates(kind="feature", db_path=db)
    assert feats and feats[0]["measured_novelty"] >= 0.0

    # 4. QD archive accepts a verified elite for this invention.
    archive = qd.QDArchive()
    elite = QDElite(id="e1", candidate_id="e1", cell=QDCell(subsystem="agents/discovery/corpus.py"),
                    metrics={"verification_score": 1.0, "impact_score": 0.9,
                             "maintainability_score": 0.6, "adoption_score": 0.5,
                             "cost_efficiency_score": 0.6, "reversibility_score": 0.8,
                             "measured_novelty": 0.9, "risk_inverse": 0.9},
                    evidence_refs=["test_pass:passed@1"])
    assert archive.add(elite) is True
    assert archive.coverage() == 1 and archive.qd_score() > 0

    # 5. Innovation report: a verified invention subtask + the proposed ledger seed.
    state = SimpleNamespace(meta={"task_id": "r1"}, task_id="r1", subtasks=[{
        "status": "done", "candidate_kind": "new_capability", "measured_novelty": 0.9,
        "title": "Self-refreshing invention corpus", "risk": "low", "blast_bin": "low",
        "affected_files": ["agents/discovery/corpus.py"],
        "verify_result": {"passed": True, "stdout": "=== 4 passed in 0.2s ==="}}])
    entries = ir.compileInnovativeChanges(state, db_path=db)
    shipped = [e for e in entries if e.status == "shipped"]
    proposed = [e for e in entries if e.status == "proposed"]
    assert shipped and shipped[0].evidence_refs
    assert proposed                                       # the bridged seed shows as a proposal
    assert ir.persist(state, entries, db_path=db) >= 1
    assert ee.fetch_innovations(run_id="r1", db_path=db)

    # 6. Autonomy gate: the ideal shipped invention would auto-run only if explicitly enabled.
    monkeypatch.setattr(config, "INVENTION_AUTO_RUN_ENABLED", True, raising=False)
    monkeypatch.setattr(config, "INVENTION_AUTONOMY", "hybrid", raising=False)
    decision = ig.routeInvention({"id": "e1", "measured_novelty": 0.9, "confidence": 0.9,
                                  "risk": "low", "blast_bin": "low", "reversible": True,
                                  "target_subsystems": ["agents/discovery/corpus.py"]})
    assert decision["decision"] == "auto_run"
