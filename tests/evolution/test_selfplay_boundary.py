"""RED contracts for maintenance-authority gating at self-play's deepest boundary."""

from __future__ import annotations

from learning.evolution import selfplay


def test_selfplay_without_maintenance_authority_is_deferred_before_state_or_launch() -> None:
    calls: list[str] = []
    result = selfplay.run(
        launch_fn=lambda goal: calls.append(goal),
        is_busy=lambda: calls.append("busy") or False,
        maintenance_authority=None,
        controller_state_authority=None,
    )

    assert result["status"] == "maintenance_deferred"
    assert result["activation_authority"] is False
    assert calls == []
