"""Run-scoped monotonic spend ledger over ControlBus (Epic 4 unit b)."""
import config
from platform_core.runtime.control import ControlBus
from platform_core.runtime import autonomy_allowance as al


def _bus(tmp_path, monkeypatch, tid="task-ledger"):
    monkeypatch.setattr(config, "CONTROL_DIR", tmp_path, raising=False)
    return ControlBus(tid)


def test_fresh_ledger_is_zero(tmp_path, monkeypatch):
    assert al.spent(_bus(tmp_path, monkeypatch)) == 0.0


def test_meter_accumulates(tmp_path, monkeypatch):
    bus = _bus(tmp_path, monkeypatch)
    al.meterSpend(bus, 0.10, attempt_id="s1:1")
    al.meterSpend(bus, 0.25, attempt_id="s1:2")
    assert abs(al.spent(bus) - 0.35) < 1e-9


def test_meter_is_idempotent_per_attempt(tmp_path, monkeypatch):
    bus = _bus(tmp_path, monkeypatch)
    al.meterSpend(bus, 0.10, attempt_id="s1:1")
    al.meterSpend(bus, 0.10, attempt_id="s1:1")  # retry double-fire -> ignored
    assert abs(al.spent(bus) - 0.10) < 1e-9


def test_meter_never_lowers_total_monotonic(tmp_path, monkeypatch):
    bus = _bus(tmp_path, monkeypatch)
    al.meterSpend(bus, 0.50, attempt_id="a")
    al.meterSpend(bus, -5.0, attempt_id="b")   # negative/garbage cost clamped to 0
    assert al.spent(bus) >= 0.50


def test_survives_restart_via_bus_file(tmp_path, monkeypatch):
    bus = _bus(tmp_path, monkeypatch)
    al.meterSpend(bus, 0.42, attempt_id="x")
    reopened = ControlBus("task-ledger")  # new object, same backing file
    assert abs(al.spent(reopened) - 0.42) < 1e-9


def test_none_cost_is_noop(tmp_path, monkeypatch):
    bus = _bus(tmp_path, monkeypatch)
    al.meterSpend(bus, None, attempt_id="n")
    assert al.spent(bus) == 0.0
