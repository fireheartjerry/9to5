# tests/test_cost_budget.py
"""Per-run rolling cost sum -> 80%-warn + hard-ceiling event (config-gated, fail-open)."""
from platform_core.runtime import cost_budget


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


def test_disabled_is_noop_and_failopen(monkeypatch):
    monkeypatch.setattr(cost_budget.config, "COST_BUDGET_ENABLED", False)
    bus = _FakeBus()
    cb = cost_budget.CostBudget("run-2", bus=bus)
    cb.add(999.0)                     # disabled -> never emits, never raises
    cb.add(None)                      # tolerate junk input
    assert bus.events == []
