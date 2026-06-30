import pytest
from memory import experience


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "exp.db"
    experience._reset_schema_cache()
    experience.init(p)
    yield p
    experience._reset_schema_cache()


def test_insight_roundtrip_with_provenance(db):
    iid = experience.record_insight(
        scope="family:auth", text="Read the schema before writing a migration.",
        poignancy=0.7, support_count=2, win_rate=0.5,
        provenance={"runs": ["r1"], "subtasks": [11]}, db_path=db)
    assert iid
    rows = experience.fetch_insights(scope="family:auth", db_path=db)
    assert rows and rows[0]["provenance_json"]
    assert "r1" in rows[0]["provenance_json"]


def test_candidate_state_machine(db):
    cid = experience.register_candidate(
        kind="playbook", target="implementer", body="BODY-A",
        provenance={"insights": [1]}, db_path=db)
    assert experience.get_candidate(cid, db_path=db)["state"] == "proposed"
    assert experience.set_candidate_state(cid, "validating", db_path=db)
    assert experience.get_candidate(cid, db_path=db)["state"] == "validating"


def test_promote_candidate_retires_prior_champion(db):
    a = experience.register_candidate(kind="playbook", target="p", body="A",
                                      provenance={}, db_path=db)
    experience.promote_candidate(a, db_path=db)
    b = experience.register_candidate(kind="playbook", target="p", body="B",
                                      provenance={}, db_path=db)
    experience.promote_candidate(b, db_path=db)
    champ = experience.candidate_champion("playbook", "p", db_path=db)
    assert champ["body"] == "B"
    assert experience.get_candidate(a, db_path=db)["state"] == "retired"


def test_candidate_field_stats_shape(db):
    cid = experience.register_candidate(kind="skill", target="s", body="X",
                                        provenance={}, db_path=db)
    stats = experience.candidate_field_stats(cid, db_path=db)
    assert set(stats) == {"n", "first_pass"}
