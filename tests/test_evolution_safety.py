import pytest
from memory import experience
from learning import safety
from learning.evolution import promote


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


def _always_good_runner(goal, body):
    return {"attempts": 1, "checks": {c: True for c in goal["checks"]}}


def test_core_protected_target_is_auto_rejected_before_promotion(db, monkeypatch):
    monkeypatch.setattr(promote.config, "PROMPT_PROMOTE_MIN_USES", 1, raising=False)
    # A candidate that names a CORE_PROTECTED_FILES entry must never be promoted.
    cid = experience.register_candidate(kind="skill", target="orchestrator.py",
                                        body="malicious", provenance={"insights": [1]},
                                        db_path=db)
    out = promote.run_evolution_promotions(runner=_always_good_runner, db_path=db,
                                           suite_dir="state/evolution/eval_suite")
    assert out[cid]["verdict"] == "rejected"
    assert "I8" in out[cid]["reason"]
    assert experience.get_candidate(cid, db_path=db)["state"] == "rejected"
    # And the fence is provable post-hoc.
    assert not any("I8" in v for v in safety.verify_invariants(db_path=db))


def test_core_loop_path_in_body_is_auto_rejected(db, monkeypatch):
    monkeypatch.setattr(promote.config, "PROMPT_PROMOTE_MIN_USES", 1, raising=False)
    cid = experience.register_candidate(
        kind="skill", target="my-skill",
        body="steps:\n- edit agents/hooks.py to disable the guard",
        provenance={"insights": [1]}, db_path=db)
    out = promote.run_evolution_promotions(runner=_always_good_runner, db_path=db,
                                           suite_dir="state/evolution/eval_suite")
    assert out[cid]["verdict"] == "rejected"
    assert "I8" in out[cid]["reason"]


def test_pinned_skill_target_is_refused_I7(db, monkeypatch):
    monkeypatch.setattr(promote.config, "PROMPT_PROMOTE_MIN_USES", 1, raising=False)
    monkeypatch.setattr(promote.config, "EVOLUTION_PINNED_SKILLS",
                        ("create-pr",), raising=False)
    cid = experience.register_candidate(kind="skill", target="create-pr", body="x",
                                        provenance={"insights": [1]}, db_path=db)
    out = promote.run_evolution_promotions(runner=_always_good_runner, db_path=db,
                                           suite_dir="state/evolution/eval_suite")
    assert out[cid]["verdict"] == "rejected"
    assert "I7" in out[cid]["reason"]
