"""Tests for society batch gate helpers."""
from __future__ import annotations

from society import society_batch


def test_society_gate_requires_flag_and_multiple_ready(monkeypatch):
    monkeypatch.setattr("config.SOCIETY_ENABLED", False)
    assert society_batch.societyGate([1, 2]) is False

    monkeypatch.setattr("config.SOCIETY_ENABLED", True)
    assert society_batch.societyGate([1]) is False
    assert society_batch.societyGate([1, 2]) is True


def test_prior_spend_sums_result_costs_only():
    class Board:
        def readAll(self):
            return [
                {"kind": "claim", "value": {"value": {"cost_usd": 9}}},
                {"kind": "result", "value": {"value": {"cost_usd": 1.25}}},
                {"kind": "result", "value": {"value": {"cost_usd": 0.75}}},
            ]

    assert society_batch._priorSpend(Board()) == 2.0
