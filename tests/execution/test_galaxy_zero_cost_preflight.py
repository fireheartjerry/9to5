from __future__ import annotations

from unittest import mock

from agents.execution import executor
from agents.execution.executor_preflight import preflightClaudeLaunch


def test_api_key_billing_is_rejected_even_during_shadow_policy() -> None:
    result = preflightClaudeLaunch(
        {"ANTHROPIC_API_KEY": "secret"}, policy_enforced=False
    )
    assert result.allowed is False
    assert result.reason == "external-spend-forbidden"
    assert result.billing_mode == "api-key"
    assert result.external_spend_allowed is False


def test_unknown_quota_and_capacity_fail_closed_when_enforced() -> None:
    result = preflightClaudeLaunch({}, policy_enforced=True)
    assert result.allowed is False
    assert result.reason == "quota-unknown"
    assert result.quota_state == "unknown"
    assert result.capacity_state == "unknown"


def test_known_subscription_capacity_is_admitted_at_zero_incremental_cost() -> None:
    result = preflightClaudeLaunch(
        {
            "NINE_TO_FIVE_CLAUDE_QUOTA_STATE": "available",
            "NINE_TO_FIVE_CLAUDE_CAPACITY_STATE": "available",
        },
        policy_enforced=True,
    )
    assert result.allowed is True
    assert result.reason == "admitted-zero-cost"
    assert result.billing_mode == "subscription"


def test_invalid_resource_truth_is_unknown_not_available() -> None:
    result = preflightClaudeLaunch(
        {
            "NINE_TO_FIVE_CLAUDE_QUOTA_STATE": "probably",
            "NINE_TO_FIVE_CLAUDE_CAPACITY_STATE": "yes-ish",
        },
        policy_enforced=True,
    )
    assert result.allowed is False
    assert result.reason == "quota-unknown"


def test_shadow_policy_observes_unknowns_without_changing_incumbent_launch() -> None:
    result = preflightClaudeLaunch({}, policy_enforced=False)
    assert result.allowed is True
    assert result.reason == "incumbent-baseline"
    assert result.observed_reason == "quota-unknown"
    assert result.shadow_only is True


def test_run_claude_preflight_blocks_before_any_workdir_or_context_write(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "paid-key")
    prepare = mock.Mock(side_effect=AssertionError("must not prepare before preflight"))
    monkeypatch.setattr(executor, "_prepareEnv", prepare)

    result = executor.runClaude({"prompt": "do work"})

    assert result["ok"] is False
    assert result["blocked"] is True
    assert result["subtype"] == "zero_cost_preflight"
    assert result["zero_cost_preflight"]["reason"] == "external-spend-forbidden"
    prepare.assert_not_called()


def test_enforced_unknown_capacity_blocks_before_launcher_resolution(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("NINE_TO_FIVE_CLAUDE_QUOTA_STATE", raising=False)
    monkeypatch.delenv("NINE_TO_FIVE_CLAUDE_CAPACITY_STATE", raising=False)
    monkeypatch.setattr("config.GALAXY_R3_POLICY_ENFORCEMENT_ENABLED", True, raising=False)
    prepare = mock.Mock(side_effect=AssertionError("must not prepare before preflight"))
    monkeypatch.setattr(executor, "_prepareEnv", prepare)

    result = executor.runClaude({"prompt": "do work"})

    assert result["blocked"] is True
    assert result["zero_cost_preflight"]["reason"] == "quota-unknown"
    prepare.assert_not_called()


def test_enforced_build_strips_budget_and_billing_overrides(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CLAUDE_MAX_BUDGET_USD", "99")
    monkeypatch.setattr("config.GALAXY_R3_POLICY_ENFORCEMENT_ENABLED", True, raising=False)
    monkeypatch.setattr(executor, "_resolveClaudeLauncher", lambda: ["claude"])
    monkeypatch.setattr(executor, "composeRunSettings", lambda: tmp_path / "settings.json")

    fresh, _resume, child_env, _flags, _model = executor._buildRunConfig(
        {"max_budget_usd": 99},
        None,
        None,
        None,
        work=str(tmp_path),
        effort="default",
        flag=None,
        charter="",
        claude_md_path=None,
    )

    assert "--max-budget-usd" not in fresh
    assert "CLAUDE_MAX_BUDGET_USD" not in child_env
