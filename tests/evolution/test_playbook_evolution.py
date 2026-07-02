import pytest
from memory import experience
from agents import playbook


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "exp.db"
    experience._reset_schema_cache()
    experience.init(p)
    yield p
    experience._reset_schema_cache()


def test_build_playbook_uses_constant_with_no_champion(db, monkeypatch):
    monkeypatch.setattr(playbook.config, "EXPERIENCE_DB_PATH", db, raising=False)
    out = playbook.buildPlaybook("implementer")
    # Unchanged behavior: the in-code constant text still appears.
    assert "Implementation discipline" in out


def test_build_playbook_prefers_promoted_champion(db, monkeypatch):
    monkeypatch.setattr(playbook.config, "EXPERIENCE_DB_PATH", db, raising=False)
    cid = experience.register_candidate(kind="playbook", target="implementer",
                                        body="### Evolved discipline\n- do the new thing.",
                                        provenance={}, db_path=db)
    experience.promote_candidate(cid, db_path=db)
    out = playbook.buildPlaybook("implementer")
    assert "Evolved discipline" in out
