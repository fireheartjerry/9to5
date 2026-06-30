"""appendStep/loadSteps/lastStepIdx round-trip + idempotent upsert + fail-open."""
from memory import experience, experience_journal as ej
from memory import experience_schema as es


def _db(tmp_path, monkeypatch):
    db = tmp_path / "experience.db"
    monkeypatch.setattr(es.config, "EXPERIENCE_DB_PATH", db)
    es._reset_schema_cache()
    es.init(db)
    return db


def test_append_load_roundtrip(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    ej.appendStep("run-1", "st-001", 1, 0, "tool", "Edit", "edit a.py",
                  {"file_path": "a.py"}, "sig-1", "sess-9", db_path=db)
    ej.appendStep("run-1", "st-001", 1, 1, "tool", "Bash", "pytest",
                  {"command": "pytest"}, "sig-1", "sess-9", db_path=db)
    steps = ej.loadSteps("run-1", "st-001", 1, db_path=db)
    assert [s["step_idx"] for s in steps] == [0, 1]
    assert steps[0]["tool"] == "Edit" and steps[0]["plan_sig"] == "sig-1"
    assert ej.lastStepIdx("run-1", "st-001", 1, db_path=db) == 1
    es._reset_schema_cache()


def test_upsert_is_idempotent_across_resume(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    # Same natural key written twice (a crash-resume re-journals step 0) -> ONE row, latest wins.
    ej.appendStep("run-1", "st-001", 1, 0, "tool", "Edit", "v1", {}, "sig", "s1", db_path=db)
    ej.appendStep("run-1", "st-001", 1, 0, "tool", "Edit", "v2", {}, "sig", "s2", db_path=db)
    steps = ej.loadSteps("run-1", "st-001", 1, db_path=db)
    assert len(steps) == 1 and steps[0]["summary"] == "v2"
    es._reset_schema_cache()


def test_last_step_idx_empty_is_minus_one(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    assert ej.lastStepIdx("run-1", "nope", 1, db_path=db) == -1
    es._reset_schema_cache()


def test_mark_attempt_superseded_clears_rows(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    ej.appendStep("run-1", "st-001", 1, 0, "tool", "Edit", "x", {}, "sig", "s", db_path=db)
    ej.markAttemptSuperseded("run-1", "st-001", 1, db_path=db)
    assert ej.lastStepIdx("run-1", "st-001", 1, db_path=db) == -1
    es._reset_schema_cache()


def test_append_is_failopen(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    # Force the DB call to raise; appendStep must swallow and return None.
    monkeypatch.setattr(ej, "_connect", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert ej.appendStep("run-1", "st-001", 1, 0, "tool", "Edit", "x", {}, "sig", "s",
                         db_path=db) is None
    es._reset_schema_cache()


def test_facade_reexports():
    assert experience.appendStep is ej.appendStep
    assert experience.lastStepIdx is ej.lastStepIdx
