"""RED contracts for contained, non-mutating analysis launches."""

from __future__ import annotations

import importlib

import pytest


def _plans():
    return importlib.import_module("platform_core.execution.launch_plan")


@pytest.mark.parametrize(
    "operation",
    ["repo_apply_patch", "repo_exec", "shell", "task", "mcp", "notebook"],
)
def test_trusted_local_analysis_rejects_every_mutating_or_delegating_operation(
    operation: str,
) -> None:
    mod = _plans()
    plan = mod.AnalysisLaunchPlan(
        transaction_id="analysis_tx",
        trust_tier="trusted_local",
        allowed_operations=frozenset({"repo_read", operation}),
        snapshot_digest="1" * 64,
        spec_digest="2" * 64,
        capability_receipt_id="cap_analysis",
        deadline="2099-01-01T00:00:00+00:00",
    )
    with pytest.raises(mod.LaunchPlanRefused):
        mod.validateAnalysisLaunchPlan(plan)


def test_unknown_analysis_cannot_fallback_to_trusted_local() -> None:
    mod = _plans()
    with pytest.raises(mod.LaunchPlanRefused):
        mod.resolveAnalysisRunner(
            trust_tier="unknown",
            docker_capability_receipt=None,
            trusted_local_capability_receipt="cap_local",
        )
