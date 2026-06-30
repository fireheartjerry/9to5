from pathlib import Path
import pytest
from memory import experience
from learning.evolution import validate

SUITE = Path("state/evolution/eval_suite")


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "exp.db"
    experience._reset_schema_cache()
    experience.init(p)
    yield p
    experience._reset_schema_cache()


def _runner_factory(good_body):
    """Deterministic runner: a body == good_body passes every check first try; else fails."""
    def runner(goal, body):
        ok = (body == good_body)
        checks = {c: (ok or not c.startswith("hidden_")) for c in goal["checks"]}
        return {"attempts": 1 if ok else 3, "checks": checks}
    return runner


def test_good_candidate_promotes(db, monkeypatch):
    monkeypatch.setattr(validate.config, "PROMPT_PROMOTE_MIN_USES", 1, raising=False)
    cid = experience.register_candidate(kind="playbook", target="p", body="GOOD",
                                        provenance={"insights": [1]}, db_path=db)
    receipt = validate.validate_candidate(cid, runner=_runner_factory("GOOD"),
                                          db_path=db, suite_dir=SUITE)
    assert receipt["verdict"] == "promote"
    assert receipt["facts"]["cand_fitness"] >= receipt["facts"]["champ_fitness"]


def test_worse_candidate_is_rejected(db, monkeypatch):
    monkeypatch.setattr(validate.config, "PROMPT_PROMOTE_MIN_USES", 1, raising=False)
    cid = experience.register_candidate(kind="playbook", target="p", body="WORSE",
                                        provenance={"insights": [1]}, db_path=db)
    # incumbent ("") is the good body; candidate "WORSE" loses.
    receipt = validate.validate_candidate(cid, runner=_runner_factory(""),
                                          db_path=db, suite_dir=SUITE)
    assert receipt["verdict"] == "reject"
