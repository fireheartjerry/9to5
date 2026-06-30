import pytest
from memory import experience
from learning import safety


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "exp.db"
    experience._reset_schema_cache()
    experience.init(p)
    yield p
    experience._reset_schema_cache()


def test_guard_promotion_blocks_brain_and_evolver():
    with pytest.raises(safety.SelfPromotionError):
        safety.guard_promotion("brain")
    with pytest.raises(safety.SelfPromotionError):
        safety.guard_promotion("evolver")
    safety.guard_promotion("gate")  # the independent gate is allowed


def test_verify_invariants_flags_two_skill_champions(db, monkeypatch):
    monkeypatch.setattr(safety.config, "EXPERIENCE_DB_PATH", db, raising=False)
    a = experience.register_candidate(kind="skill", target="s", body="A",
                                      provenance={}, db_path=db)
    experience.set_candidate_state(a, "champion", db_path=db)
    b = experience.register_candidate(kind="skill", target="s", body="B",
                                      provenance={}, db_path=db)
    experience.set_candidate_state(b, "champion", db_path=db)
    violations = safety.verify_invariants(db_path=db)
    assert any("I4" in v and "skill" in v for v in violations)


def test_panic_to_stock_retires_champion_skills(db):
    cid = experience.register_candidate(kind="skill", target="s", body="A",
                                        provenance={}, db_path=db)
    experience.promote_candidate(cid, db_path=db)
    safety.panic_to_stock(db_path=db)
    assert experience.candidate_champion("skill", "s", db_path=db) is None
