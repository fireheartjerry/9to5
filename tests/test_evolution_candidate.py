import pytest
from memory import experience
from learning.evolution import candidate
from agents import playbook


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "exp.db"
    experience._reset_schema_cache()
    experience.init(p)
    yield p
    experience._reset_schema_cache()


def test_playbook_champion_body_is_constant_until_promotion(db):
    # No champion yet -> byte-for-byte the in-code PROFILES constant (prompts.get property).
    assert candidate.champion_body("playbook", "implementer", db_path=db) == \
        playbook.PROFILES["implementer"]["playbook"]


def test_playbook_champion_body_after_promotion(db):
    cid = experience.register_candidate(kind="playbook", target="implementer",
                                        body="NEW PLAYBOOK BODY", provenance={}, db_path=db)
    experience.promote_candidate(cid, db_path=db)
    assert candidate.champion_body("playbook", "implementer", db_path=db) == "NEW PLAYBOOK BODY"


def test_constitution_champion_body_round_trips_through_prompts(db):
    # Constitution candidates reach prompts.py, not the new table.
    body = candidate.champion_body("constitution", "orchestrator", db_path=db,
                                   default="STOCK CONSTITUTION")
    assert body == "STOCK CONSTITUTION"
