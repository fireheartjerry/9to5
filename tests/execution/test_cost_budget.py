# tests/test_cost_budget.py
"""Per-run rolling cost sum -> 80%-warn + hard-ceiling event (config-gated, fail-open)."""
import threading
import time

from platform_core.runtime import cost_budget


class _SlowFloat:
    """Widens the add()'s read-modify-write window so an UNGUARDED self._total += float(x)
    deterministically loses concurrent increments; the lock serializes it (no loss)."""

    def __init__(self, v):
        self.v = v

    def __float__(self):
        time.sleep(0.01)
        return self.v


class _FakeBus:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)


def test_warn_then_ceiling(monkeypatch):
    monkeypatch.setattr(cost_budget.config, "COST_BUDGET_ENABLED", True)
    monkeypatch.setattr(cost_budget.config, "COST_BUDGET_CEILING_USD", 1.0)
    bus = _FakeBus()
    cb = cost_budget.CostBudget("run-1", bus=bus)
    cb.add(0.50)                      # 50% -> no event
    assert bus.events == []
    cb.add(0.35)                      # 85% -> one warn
    kinds = [e.data.get("level") for e in bus.events]
    assert "warn" in kinds
    cb.add(0.30)                      # 115% -> hard ceiling
    assert "ceiling" in [e.data.get("level") for e in bus.events]


def test_concurrent_adds_no_lost_total_no_double_fire(monkeypatch):
    monkeypatch.setattr(cost_budget.config, "COST_BUDGET_ENABLED", True)
    monkeypatch.setattr(cost_budget.config, "COST_BUDGET_CEILING_USD", 1.0)
    bus = _FakeBus()
    cb = cost_budget.CostBudget("run-c", bus=bus)

    # 20 threads each add 0.1 (slow-converting) -> total must be exactly 2.0; crosses 80% + ceiling.
    def _worker():
        cb.add(_SlowFloat(0.1))

    threads = [threading.Thread(target=_worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert abs(cb._total - 2.0) < 1e-9                 # no lost increments under contention
    levels = [e.data.get("level") for e in bus.events]
    assert levels.count("warn") <= 1                   # one-shot warn (no double-fire)
    assert levels.count("ceiling") == 1                # one-shot ceiling (no double-fire)


def test_disabled_is_noop_and_failopen(monkeypatch):
    monkeypatch.setattr(cost_budget.config, "COST_BUDGET_ENABLED", False)
    bus = _FakeBus()
    cb = cost_budget.CostBudget("run-2", bus=bus)
    cb.add(999.0)                     # disabled -> never emits, never raises
    cb.add(None)                      # tolerate junk input
    assert bus.events == []
