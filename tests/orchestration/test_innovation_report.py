"""Fact-grounded innovation report: shipped needs evidence, failed/factless excluded, proposals separate."""
from types import SimpleNamespace

import pytest

from memory import experience
from memory import experience_evolution as ee
from platform_core.orchestration import innovation_report as ir


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "exp.db"
    experience._reset_schema_cache()
    experience.init(p)
    yield p
    experience._reset_schema_cache()


def _state(subtasks, task_id="r1"):
    return SimpleNamespace(subtasks=subtasks, meta={"task_id": task_id}, task_id=task_id)


def _shipped_st(**kw):
    d = dict(status="done", candidate_kind="new_capability", measured_novelty=0.9, title="Feat X",
             verify_result={"passed": True, "stdout": "=== 3 passed in 0.1s ==="},
             affected_files=["memory/x.py"], risk="low", blast_bin="low")
    d.update(kw)
    return d


def test_verified_invention_is_shipped_with_evidence():
    entries = ir.compileInnovativeChanges(_state([_shipped_st()]))
    shipped = [e for e in entries if e.status == "shipped"]
    assert len(shipped) == 1
    assert shipped[0].title == "Feat X"
    assert any(r.startswith("test_pass") for r in shipped[0].evidence_refs)
    assert shipped[0].why_innovative["measured_novelty"] == 0.9


def test_factless_claim_is_dropped():
    st = _shipped_st(verify_result={"passed": True, "stdout": "did some stuff"})
    entries = ir.compileInnovativeChanges(_state([st]))
    assert [e for e in entries if e.status == "shipped"] == []


def test_failed_verify_is_never_shipped():
    st = _shipped_st(verify_result={"passed": False, "stdout": "=== 3 passed ==="})
    entries = ir.compileInnovativeChanges(_state([st]))
    assert [e for e in entries if e.status == "shipped"] == []


def test_non_invention_subtask_excluded():
    normal = dict(status="done", title="fix typo", measured_novelty=0.0,
                  verify_result={"passed": True, "stdout": "3 passed"})
    entries = ir.compileInnovativeChanges(_state([normal]))
    assert entries == []                          # ordinary passed subtask is not an innovation


def test_proposed_from_ledger_is_separate(db):
    ee.register_invention(target="memory/y", body="sketch", measured_novelty=0.8, risk="medium",
                          provenance={"run_id": "r1", "route": "proposal", "title": "Prop Y"},
                          db_path=db)
    entries = ir.compileInnovativeChanges(_state([]), db_path=db)
    proposed = [e for e in entries if e.status == "proposed"]
    assert len(proposed) == 1
    assert proposed[0].title == "Prop Y"
    assert proposed[0].why_innovative["measured_novelty"] == 0.8


def test_proposed_filters_other_runs(db):
    ee.register_invention(target="memory/z", body="sketch2",
                          provenance={"run_id": "OTHER", "title": "Other"}, db_path=db)
    entries = ir.compileInnovativeChanges(_state([]), db_path=db)
    assert [e for e in entries if e.status == "proposed"] == []


def test_persist_writes_to_ledger(db):
    entries = ir.compileInnovativeChanges(_state([_shipped_st()]))
    n = ir.persist(_state([_shipped_st()]), entries, db_path=db)
    assert n == 1
    rows = ee.fetch_innovations(run_id="r1", db_path=db)
    assert len(rows) == 1 and rows[0]["status"] == "shipped"


def test_render_markdown_separates_shipped_and_proposed(db):
    ee.register_invention(target="memory/y", body="s", measured_novelty=0.8,
                          provenance={"run_id": "r1", "title": "Prop Y"}, db_path=db)
    entries = ir.compileInnovativeChanges(_state([_shipped_st()]), db_path=db)
    md = ir.render_markdown(entries)
    assert "## Innovative Changes" in md
    assert "Shipped (verified)" in md
    assert "Proposed" in md
    assert "Feat X" in md and "Prop Y" in md
