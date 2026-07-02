import pytest
from memory import experience
from learning.evolution import promote, candidate


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "exp.db"
    experience._reset_schema_cache()
    experience.init(p)
    yield p
    experience._reset_schema_cache()


def _runner(good_body):
    def runner(goal, body):
        ok = (body == good_body)
        checks = {c: (ok or not c.startswith("hidden_")) for c in goal["checks"]}
        return {"attempts": 1 if ok else 3, "checks": checks}
    return runner


def test_good_candidate_is_promoted_end_to_end(db, monkeypatch):
    monkeypatch.setattr(promote.config, "PROMPT_PROMOTE_MIN_USES", 1, raising=False)
    cid = experience.register_candidate(kind="playbook", target="generalist", body="GOOD",
                                        provenance={"insights": [1]}, db_path=db)
    out = promote.run_evolution_promotions(runner=_runner("GOOD"), db_path=db,
                                           suite_dir="state/evolution/eval_suite")
    assert out[cid]["verdict"] == "promote"
    assert candidate.champion_body("playbook", "generalist", db_path=db) == "GOOD"


def test_kill_switch_freezes_promotion(db, monkeypatch):
    monkeypatch.setattr(promote.safety, "kill_switch_active", lambda: True)
    experience.register_candidate(kind="playbook", target="g", body="X",
                                  provenance={}, db_path=db)
    assert promote.run_evolution_promotions(runner=_runner("X"), db_path=db) == \
        {"skipped": "kill_switch"}


def test_brain_actor_cannot_self_promote(db, monkeypatch):
    monkeypatch.setattr(promote.config, "PROMPT_PROMOTE_MIN_USES", 1, raising=False)
    cid = experience.register_candidate(kind="playbook", target="g", body="GOOD",
                                        provenance={"insights": [1]}, db_path=db)
    out = promote.run_evolution_promotions(runner=_runner("GOOD"), actor="brain", db_path=db,
                                           suite_dir="state/evolution/eval_suite")
    assert out[cid]["verdict"] == "blocked"
    assert candidate.champion_body("playbook", "g", db_path=db) != "GOOD"


def test_rollback_retires_champion(db, monkeypatch):
    monkeypatch.setattr(promote.config, "PROMPT_PROMOTE_MIN_USES", 1, raising=False)
    cid = experience.register_candidate(kind="playbook", target="g", body="GOOD",
                                        provenance={"insights": [1]}, db_path=db)
    promote.run_evolution_promotions(runner=_runner("GOOD"), db_path=db,
                                     suite_dir="state/evolution/eval_suite")
    assert promote.rollback(cid, db_path=db)
    assert experience.candidate_champion("playbook", "g", db_path=db) is None
