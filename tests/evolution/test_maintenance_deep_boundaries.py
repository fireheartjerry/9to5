"""RED contracts for maintenance/effect authority at deepest public entrypoints."""

from __future__ import annotations

from learning.evolution import evolver, sie
from platform_core.ops import retention, wipe


def _assert_deferred(result: dict) -> None:
    assert result["status"] == "maintenance_deferred"
    assert result["activation_authority"] is False


def test_evolver_refuses_before_brain_spawn_or_state_lookup() -> None:
    calls: list[str] = []
    result = evolver.propose_candidates(
        brain=lambda prompt: calls.append("brain") or "candidate",
        spawn=lambda argv: calls.append("spawn") or {},
        maintenance_authority=None,
        controller_state_authority=None,
    )
    _assert_deferred(result)
    assert calls == []


def test_sie_maintenance_refuses_before_lock_or_database_lookup() -> None:
    result = sie.run_maintenance(
        force=True,
        maintenance_authority=None,
        controller_state_authority=None,
    )
    _assert_deferred(result)


def test_retention_and_wipe_refuse_before_path_or_payload_construction() -> None:
    retention_result = retention.sweepAll(
        effect_authority=None,
        controller_state_authority=None,
    )
    wipe_result = wipe.executeWipe(
        ["tasks"],
        effect_authority=None,
        controller_state_authority=None,
    )
    _assert_deferred(retention_result)
    _assert_deferred(wipe_result)
