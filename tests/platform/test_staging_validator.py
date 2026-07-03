"""Tests for staging validator gates."""
from __future__ import annotations

from platform_core.ops import staging_validator


def test_ci_workflow_gate_reports_required_steps():
    results = staging_validator._gateCiWorkflow()
    gates = {row["gate"]: row for row in results}

    assert gates["ci_workflow:exists"]["passed"] is True
    assert gates['ci_workflow:step:validate_workflows.py']["passed"] is True


def test_main_returns_failure_when_any_gate_fails(monkeypatch):
    monkeypatch.setattr(staging_validator, "validate", lambda: [
        {"gate": "x", "passed": False, "detail": "bad"},
    ])

    assert staging_validator.main(quiet=True) == 1
