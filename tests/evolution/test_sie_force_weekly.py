"""SIE_FORCE_WEEKLY (set by FULL_STACK): the weekly self-evolution tier runs every maintenance
pass instead of only in its weekly window. The per-day/idle spawn caps inside the steps are
untouched (runaway guard) -- this only tests the gate."""

import config
from learning import sie


def _base_mocks(monkeypatch, tmp_path, *, due, weekly_due):
    monkeypatch.setattr(config, "SIE_KILL_SWITCH", False, raising=False)
    monkeypatch.setattr(config, "SIE_BOOTSTRAP", False, raising=False)
    monkeypatch.setattr(sie, "_read_state", lambda: {})
    monkeypatch.setattr(sie, "_write_state", lambda st: None)
    monkeypatch.setattr(sie, "_acquire_lock", lambda: str(tmp_path / "lock"))
    monkeypatch.setattr(sie.experience, "init", lambda db=None: None)
    monkeypatch.setattr(sie, "_due", lambda *a, **k: due)
    monkeypatch.setattr(sie, "_weekly_due", lambda *a, **k: weekly_due)
    monkeypatch.setattr(sie, "_maintenance_steps", lambda db: [])


def test_force_weekly_runs_weekly_steps_off_window(monkeypatch, tmp_path):
    _base_mocks(monkeypatch, tmp_path, due=False, weekly_due=False)
    monkeypatch.setattr(config, "SIE_FORCE_WEEKLY", True)
    ran = {}

    def _sentinel():
        ran["hit"] = True
        return {"ok": True}

    monkeypatch.setattr(sie, "_weekly_steps", lambda db: [("_sentinel", _sentinel)])
    summary = sie.run_maintenance(reason="test", db_path=tmp_path / "x.db")
    assert ran.get("hit") is True, "forced weekly did not run the weekly tier off-window"
    assert summary["steps"]["_sentinel"] == {"ok": True}


def test_no_force_no_weekly_off_window(monkeypatch, tmp_path):
    _base_mocks(monkeypatch, tmp_path, due=True, weekly_due=False)
    monkeypatch.setattr(config, "SIE_FORCE_WEEKLY", False)
    called = {}
    monkeypatch.setattr(
        sie, "_weekly_steps", lambda db: [("_sentinel", lambda: called.setdefault("hit", True))]
    )
    sie.run_maintenance(reason="test", db_path=tmp_path / "x.db")
    assert called.get("hit") is None, "weekly tier ran without force or its window"
