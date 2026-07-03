from datetime import datetime, timedelta
import pytest
from memory import experience
from learning.evolution import curator


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "exp.db"
    experience._reset_schema_cache()
    experience.init(p)
    yield p
    experience._reset_schema_cache()


def _old_champion(db, target, days):
    cid = experience.register_candidate(kind="skill", target=target, body="B",
                                        provenance={}, db_path=db)
    experience.promote_candidate(cid, db_path=db)
    old = (datetime.now().astimezone() - timedelta(days=days)).isoformat(timespec="seconds")
    with experience._connect(db) as conn:
        conn.execute("UPDATE evolution_candidates SET updated_at=? WHERE id=?", (old, cid))
    return cid


def test_age_out_archives_old_skill_recoverably(db, monkeypatch):
    monkeypatch.setattr(curator.config, "EVOLUTION_ARCHIVE_DAYS", 90, raising=False)
    cid = _old_champion(db, "stale-skill", days=120)
    report = curator.run_curator(db_path=db)
    assert "stale-skill" in report["archived"]
    assert experience.get_candidate(cid, db_path=db)["state"] == "archived"
    # Recoverable -- archive, never delete.
    assert curator.restore_skill("stale-skill", db_path=db)
    assert experience.candidate_champion("skill", "stale-skill", db_path=db)["body"] == "B"


def test_pinned_skill_bypasses_ageout(db, monkeypatch):
    monkeypatch.setattr(curator.config, "EVOLUTION_PINNED_SKILLS", ("create-pr",), raising=False)
    _old_champion(db, "create-pr", days=999)
    report = curator.run_curator(db_path=db)
    assert "create-pr" in report["pinned_skipped"]
    assert "create-pr" not in report["archived"]


def test_dry_run_mutates_nothing(db, monkeypatch):
    monkeypatch.setattr(curator.config, "EVOLUTION_ARCHIVE_DAYS", 90, raising=False)
    cid = _old_champion(db, "s", days=120)
    report = curator.run_curator(dry_run=True, db_path=db)
    assert "s" in report["archived"] and report["dry_run"] is True
    assert experience.get_candidate(cid, db_path=db)["state"] == "champion"


def test_consolidation_off_by_default(db, monkeypatch):
    monkeypatch.setattr(curator.config, "EVOLUTION_CONSOLIDATE", False, raising=False)
    report = curator.run_curator(db_path=db)
    assert report["consolidations"] == []
