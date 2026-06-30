"""Importance-triggered consolidation: OFF by default, writes cited principles when ON."""
import pytest

import config
from memory import experience, experience_content, reflection_consolidate


@pytest.fixture()
def db(tmp_path, monkeypatch):
    p = tmp_path / "experience.db"
    monkeypatch.setattr(config, "EXPERIENCE_DB_PATH", p, raising=False)
    monkeypatch.setattr(config, "EXPERIENCE_LEDGER_ENABLED", True, raising=False)
    experience._reset_schema_cache()
    experience.init(db_path=p)
    yield p
    experience._reset_schema_cache()


def test_disabled_by_default_is_noop(db, monkeypatch):
    monkeypatch.setattr(config, "REFLECTION_CONSOLIDATE_ENABLED", False, raising=False)
    out = reflection_consolidate.maybeConsolidate(db_path=db)
    assert out == {"consolidated": 0}
    assert experience.fetch_reflections(db_path=db) == []


def test_below_budget_does_not_fire(db, monkeypatch):
    monkeypatch.setattr(config, "REFLECTION_CONSOLIDATE_ENABLED", True, raising=False)
    experience_content.recordSolutionContent("r1", "st-1", solution_content="small",
                                             post_mortem="", importance=0.5, model_id="m", db_path=db)
    out = reflection_consolidate.maybeConsolidate(db_path=db, importance_budget=10.0)
    assert out == {"consolidated": 0}


def test_crossing_budget_writes_cited_principle(db, monkeypatch):
    monkeypatch.setattr(config, "REFLECTION_CONSOLIDATE_ENABLED", True, raising=False)
    for i in range(5):
        experience_content.recordSolutionContent(
            "r1", f"st-{i}", solution_content=f"used pattern P{i}",
            post_mortem=f"lesson {i}", importance=3.0, model_id="m", db_path=db)
    out = reflection_consolidate.maybeConsolidate(db_path=db, importance_budget=5.0)
    assert out["consolidated"] >= 1
    refl = experience.fetch_reflections(db_path=db)
    assert refl and refl[0]["role"] == "consolidator"
    assert "st-" in (refl[0]["reusable_recipe"] or "")   # source-cited
