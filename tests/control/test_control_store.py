"""control_store (R8): the transactional SQLite backing of the ControlBus.

Covers the structural guarantees the JSON-file bus could only promise: WAL + BEGIN
IMMEDIATE serialization, source_msg_id ingestion dedup, drain-exactly-once ordering,
ledger idempotency/monotonicity (money can never be zeroed by a rebuild), the one-shot
legacy state/control/*.json migration, and the shared waitDecision gate wait."""
import json
import threading
import time

import pytest

import config
from platform_core.runtime import control_store
from platform_core.runtime import autonomy_allowance as al
from platform_core.runtime.control import ControlBus


# ---------------------------------------------------------------------------
# schema / pragmas
# ---------------------------------------------------------------------------
def test_db_is_wal_with_busy_timeout():
    ControlBus("t-schema").isPaused()   # force db creation
    conn = control_store._connect()
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 30000
    finally:
        conn.close()


def test_db_path_derives_from_state_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(control_store, "_DB_OVERRIDE", None, raising=False)
    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "state" / "tasks", raising=False)
    assert control_store._dbPath() == tmp_path / "state" / "control.db"


# ---------------------------------------------------------------------------
# flags / decisions
# ---------------------------------------------------------------------------
def test_flag_roundtrip_types():
    tid = "t-flags"
    control_store.setFlag(tid, "abort", True)
    control_store.setFlag(tid, "seen_discord_id", "12345")
    control_store.setFlag(tid, "pending_gate", None)
    assert control_store.getFlag(tid, "abort") is True
    assert control_store.getFlag(tid, "seen_discord_id") == "12345"
    assert control_store.getFlag(tid, "pending_gate") is None
    assert control_store.getFlag(tid, "missing", "dflt") == "dflt"
    control_store.setFlag(tid, "abort", False)   # overwrite in place (PK upsert)
    assert control_store.getFlag(tid, "abort") is False


def test_decisions_are_per_task_and_clearable():
    control_store.setDecision("t-a", "plan", "approve")
    control_store.setDecision("t-b", "plan", "reject")
    assert control_store.getDecision("t-a", "plan") == "approve"
    assert control_store.getDecision("t-b", "plan") == "reject"
    control_store.clearDecision("t-a", "plan")
    assert control_store.getDecision("t-a", "plan") is None
    assert control_store.getDecision("t-b", "plan") == "reject"


# ---------------------------------------------------------------------------
# ops queue
# ---------------------------------------------------------------------------
def test_pushop_reports_dedup():
    assert control_store.pushOp("t-ops", {"op": "retry"}, "m1") is True
    assert control_store.pushOp("t-ops", {"op": "retry"}, "m1") is False   # same message
    assert control_store.pushOp("t-ops", {"op": "retry"}, "m2") is True    # new message
    assert len(control_store.drainOps("t-ops")) == 2


def test_source_msg_dedup_is_per_task():
    control_store.pushOp("t-x", {"op": "retry"}, "77")
    control_store.pushOp("t-y", {"op": "retry"}, "77")
    assert len(control_store.drainOps("t-x")) == 1
    assert len(control_store.drainOps("t-y")) == 1


def test_drain_removes_and_orders():
    for i in range(5):
        control_store.pushOp("t-drain", {"op": "add", "title": f"t{i}"})
    ops = control_store.drainOps("t-drain")
    assert [o["title"] for o in ops] == [f"t{i}" for i in range(5)]
    assert control_store.drainOps("t-drain") == []


def test_garbage_op_row_is_dropped_not_fatal():
    control_store.pushOp("t-garbage", {"op": "add", "title": "good"})
    conn = control_store._connect()
    try:
        conn.execute("INSERT INTO ops(task_id, op_json, source_msg_id, created_at) "
                     "VALUES ('t-garbage', '{not json', NULL, 'now')")
    finally:
        conn.close()
    assert ControlBus("t-garbage").load()["plan_ops"] == [{"op": "add", "title": "good"}]
    ops = control_store.drainOps("t-garbage")
    assert ops == [{"op": "add", "title": "good"}]


# ---------------------------------------------------------------------------
# spend ledger (Epic 4): idempotent, monotonic, un-zeroable
# ---------------------------------------------------------------------------
def test_ledger_same_attempt_id_charges_once():
    bus = ControlBus("t-ledger")
    al.meterSpend(bus, 0.10, attempt_id="s1:1")
    al.meterSpend(bus, 0.10, attempt_id="s1:1")   # retry double-fire -> ignored
    al.meterSpend(bus, 0.25, attempt_id="s1:2")
    assert abs(al.spent(bus) - 0.35) < 1e-9


def test_ledger_survives_clear_run_start_and_op_churn():
    """clearForRunStart / drain / corrupt op rows can never zero the money (the old
    corrupt-rebuild path reset autonomy_spent_usd to 0.0)."""
    bus = ControlBus("t-ledger2")
    al.meterSpend(bus, 1.50, attempt_id="a1")
    bus.pushOp({"op": "add", "title": "x"})
    bus.clearForRunStart()
    bus.drainOps()
    assert abs(al.spent(bus) - 1.50) < 1e-9
    assert abs(bus.load()["autonomy_spent_usd"] - 1.50) < 1e-9


def test_ledger_wiped_only_by_explicit_full_clear():
    bus = ControlBus("t-ledger3")
    al.meterSpend(bus, 0.42, attempt_id="x")
    bus.clear()
    assert al.spent(bus) == 0.0


# ---------------------------------------------------------------------------
# one-shot legacy JSON migration
# ---------------------------------------------------------------------------
_LEGACY = {
    "abort": True,
    "pause": False,
    "decisions": {"plan": "approve", "pre_pr": None},
    "plan_ops": [{"op": "add", "title": "carried"}],
    "seen_discord_id": "555",
    "pending_gate": "pre_pr",
    "autonomy_spent_usd": 1.25,
    "autonomy_metered_attempts": ["st-001:1", "st-001:2"],
}


def _freshStore(tmp_path, monkeypatch, legacy_files: dict):
    legacy_dir = tmp_path / "legacy_control"
    legacy_dir.mkdir()
    for name, data in legacy_files.items():
        (legacy_dir / name).write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(config, "CONTROL_DIR", legacy_dir, raising=False)
    monkeypatch.setattr(control_store, "_DB_OVERRIDE",
                        tmp_path / "fresh" / "control.db", raising=False)
    return legacy_dir


def test_legacy_json_migrates_into_new_db(tmp_path, monkeypatch):
    legacy_dir = _freshStore(tmp_path, monkeypatch, {"t-legacy.json": _LEGACY})
    d = ControlBus("t-legacy").load()   # first touch creates the db -> migration
    assert d["abort"] is True
    assert d["pause"] is False
    assert d["decisions"]["plan"] == "approve"
    assert d["plan_ops"] == [{"op": "add", "title": "carried"}]
    assert d["seen_discord_id"] == "555"
    assert d["pending_gate"] == "pre_pr"
    assert abs(d["autonomy_spent_usd"] - 1.25) < 1e-9
    # the file was retired exactly once
    assert not (legacy_dir / "t-legacy.json").exists()
    assert (legacy_dir / "t-legacy.json.migrated").exists()


def test_migrated_attempts_stay_idempotent(tmp_path, monkeypatch):
    """An attempt metered under the OLD schema must not double-charge if re-metered
    after the migration (restart mid-run)."""
    _freshStore(tmp_path, monkeypatch, {"t-legacy.json": _LEGACY})
    bus = ControlBus("t-legacy")
    al.meterSpend(bus, 9.99, attempt_id="st-001:1")   # already metered pre-migration
    assert abs(al.spent(bus) - 1.25) < 1e-9


def test_migration_skips_bad_file_and_still_serves(tmp_path, monkeypatch):
    legacy_dir = _freshStore(tmp_path, monkeypatch,
                             {"t-ok.json": {"abort": True}})
    (legacy_dir / "t-bad.json").write_text("{ not valid json :::", encoding="utf-8")
    assert ControlBus("t-ok").isAbort() is True
    assert (legacy_dir / "t-bad.json").exists()   # left in place, never retired


# ---------------------------------------------------------------------------
# load() shape + lifecycle
# ---------------------------------------------------------------------------
def test_fresh_bus_load_is_blank_shape():
    d = ControlBus("t-blank").load()
    assert d["abort"] is False and d["pause"] is False
    assert d["kill_subprocess"] is False and d["force_replan"] is False
    assert d["decisions"] == {"plan": None, "pre_pr": None, "action_risk": None, "council_risk": None}
    assert d["plan_ops"] == [] and d["seen_discord_id"] is None
    assert d["pending_gate"] is None and d["autonomy_spent_usd"] == 0.0


def test_clear_task_resets_everything():
    bus = ControlBus("t-clear")
    bus.requestAbort(); bus.decide("plan", "approve")
    bus.pushOp({"op": "retry"}, source_msg_id="9")
    bus.clear()
    d = bus.load()
    assert d["abort"] is False and d["decisions"]["plan"] is None and d["plan_ops"] == []
    # a cleared source_msg_id can be ingested again (fresh task lifecycle)
    bus.pushOp({"op": "retry"}, source_msg_id="9")
    assert len(bus.drainOps()) == 1


# ---------------------------------------------------------------------------
# waitDecision matrix: decision / abort / timeout / night-mode / escape
# ---------------------------------------------------------------------------
def test_waitdecision_returns_verdict():
    bus = ControlBus("t-wd1")
    threading.Timer(0.05, lambda: bus.decide("pre_pr", "approve")).start()
    assert bus.waitDecision("pre_pr", timeout=5.0, poll=0.01) == "approve"


def test_waitdecision_abort_escapes():
    bus = ControlBus("t-wd2")
    threading.Timer(0.05, bus.requestAbort).start()
    assert bus.waitDecision("pre_pr", timeout=5.0, poll=0.01) == "abort"


def test_waitdecision_timeout_returns_none():
    bus = ControlBus("t-wd3")
    start = time.time()
    assert bus.waitDecision("pre_pr", timeout=0.05, poll=0.01) is None
    assert time.time() - start < 2.0


def test_waitdecision_night_mode_caps_unbounded_wait(monkeypatch):
    monkeypatch.setattr(config, "NIGHT_MODE", True, raising=False)
    monkeypatch.setattr(config, "NIGHT_MODE_PAUSE_TIMEOUT", 0.05, raising=False)
    bus = ControlBus("t-wd4")
    assert bus.waitDecision("pre_pr", timeout=None, poll=0.01) is None


def test_waitdecision_escape_and_on_tick():
    bus = ControlBus("t-wd5")
    ticks = []
    verdict = bus.waitDecision("pre_pr", timeout=None, poll=0.01,
                               on_tick=lambda: ticks.append(1),
                               escape=lambda: len(ticks) >= 3)
    assert verdict is None
    assert len(ticks) >= 3


def test_waitdecision_decision_beats_timeout_on_same_tick():
    bus = ControlBus("t-wd6")
    bus.decide("plan", "reject")
    assert bus.waitDecision("plan", timeout=0.0, poll=0.01) == "reject"
