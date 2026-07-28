"""RED contracts for provider launch admission through exact canary evidence."""

from __future__ import annotations

import importlib
import io

import pytest


def _provider_boot():
    return importlib.import_module("platform_core.execution.provider_boot")


def test_missing_capability_receipt_refuses_before_provider_launcher() -> None:
    mod = _provider_boot()
    watchdog_mod = importlib.import_module("platform_core.execution.authority_watchdog")
    calls: list[object] = []
    boot = mod.ProviderSafeBoot(
        launcher=lambda plan: calls.append(plan) or object(),
        watchdog=watchdog_mod.AuthorityWatchdog(
            controller_generation=1,
            watchdog_generation=1,
            revocation_generation=0,
        ),
    )
    plan = mod.ProviderBootPlan(
        provider="codex",
        transaction_id="tx_provider",
        launch_plan_digest="1" * 64,
        image_digest="2" * 64,
        broker_policy_digest="3" * 64,
        credential_policy_digest="4" * 64,
        deadline="2099-01-01T00:00:00+00:00",
    )

    with pytest.raises(mod.ProviderBootUnavailable):
        boot.launch(plan, capability_receipt=None, launch_authority=None)

    assert calls == []


def test_safe_boot_requires_matching_watchdog_launch_authority() -> None:
    boot_mod = _provider_boot()
    watchdog_mod = importlib.import_module("platform_core.execution.authority_watchdog")
    calls: list[object] = []
    watchdog = watchdog_mod.AuthorityWatchdog(
        controller_generation=1,
        watchdog_generation=1,
        revocation_generation=0,
    )
    launch_authority = watchdog.issueExecutionLaunchAuthority(
        transaction_id="tx_provider",
        resource_id="driver_resource",
        clone_root="C:/isolated/clone",
        clone_ownership_nonce="clone_nonce",
        runner_kind="docker",
        capability_receipt_id="cap_provider",
        capability_process_grant_nonce="process_grant",
        trust_receipt_id="trust_provider",
        trust_grant_nonce="trust_grant",
        issuer_generation=1,
        canonical_base="1" * 40,
        journal_phase="ready",
        deadline="2099-01-01T00:00:00+00:00",
    )
    plan = boot_mod.ProviderBootPlan(
        provider="codex",
        transaction_id="tx_provider",
        launch_plan_digest="1" * 64,
        image_digest="2" * 64,
        broker_policy_digest="3" * 64,
        credential_policy_digest="4" * 64,
        deadline="2099-01-01T00:00:00+00:00",
    )
    receipt = boot_mod.CapabilityEnforcementReceipt(
        receipt_id="cap_provider",
        provider="codex",
        launch_plan_digest="1" * 64,
        image_digest="2" * 64,
        broker_policy_digest="3" * 64,
        credential_policy_digest="4" * 64,
        host_fact_digest="5" * 64,
        revocation_generation=0,
        expires_at="2099-01-01T00:00:00+00:00",
    )
    boot = boot_mod.ProviderSafeBoot(
        launcher=lambda value: calls.append(value) or "started",
        watchdog=watchdog,
    )

    assert boot.launch(
        plan,
        capability_receipt=receipt,
        launch_authority=launch_authority,
    ) == "started"
    assert calls == [plan]

    copied_receipt = boot_mod.CapabilityEnforcementReceipt(
        receipt_id="cap_other",
        provider="codex",
        launch_plan_digest="1" * 64,
        image_digest="2" * 64,
        broker_policy_digest="3" * 64,
        credential_policy_digest="4" * 64,
        host_fact_digest="5" * 64,
        revocation_generation=0,
        expires_at="2099-01-01T00:00:00+00:00",
    )
    with pytest.raises(boot_mod.ProviderBootUnavailable):
        boot.launch(
            plan,
            capability_receipt=copied_receipt,
            launch_authority=launch_authority,
        )
    assert calls == [plan]


def test_capability_receipt_must_exact_match_every_launch_digest() -> None:
    mod = _provider_boot()
    receipt = mod.CapabilityEnforcementReceipt(
        receipt_id="cap_provider",
        provider="codex",
        launch_plan_digest="1" * 64,
        image_digest="2" * 64,
        broker_policy_digest="3" * 64,
        credential_policy_digest="4" * 64,
        host_fact_digest="5" * 64,
        revocation_generation=1,
        expires_at="2099-01-01T00:00:00+00:00",
    )
    changed = mod.ProviderBootPlan(
        provider="codex",
        transaction_id="tx_provider",
        launch_plan_digest="9" * 64,
        image_digest="2" * 64,
        broker_policy_digest="3" * 64,
        credential_policy_digest="4" * 64,
        deadline="2099-01-01T00:00:00+00:00",
    )

    with pytest.raises(mod.ProviderBootUnavailable):
        mod.validateCapabilityEnforcement(changed, receipt, current_revocation_generation=1)


@pytest.mark.parametrize("driver_module,driver_name", [
    ("agents.execution.claude_driver", "ClaudeDriver"),
    ("agents.execution.codex_driver", "CodexDriver"),
])
def test_provider_driver_accepts_only_one_contiguous_terminal_stream(
    driver_module: str,
    driver_name: str,
) -> None:
    driver_mod = importlib.import_module(driver_module)
    contracts = importlib.import_module("agents.execution.claude_driver")
    request = contracts.DriverRequest(
        invocation_id="invoke_1",
        transaction_id="transaction_1",
        prompt="Perform the bounded task.",
        model="pinned_model",
        broker_operations=frozenset({"repo_read"}),
        deadline="2099-01-01T00:00:00+00:00",
    )
    stream = (
        contracts.DriverEvent("invoke_1", 1, "started"),
        contracts.DriverEvent("invoke_1", 2, "terminal", {"outcome": "complete"}),
    )
    driver = getattr(driver_mod, driver_name)(transport=lambda _request: stream)

    assert driver.invoke(request) == stream

    broken = getattr(driver_mod, driver_name)(
        transport=lambda _request: (
            contracts.DriverEvent("invoke_1", 1, "started"),
            contracts.DriverEvent("invoke_1", 3, "failure", {"code": "protocol_error"}),
        )
    )
    with pytest.raises(contracts.DriverProtocolRefused):
        broken.invoke(request)


def test_generic_driver_entrypoint_emits_typed_unavailable_without_binary_stream_assumptions() -> None:
    entrypoint = importlib.import_module("containers.galaxy.driver_entrypoint")
    reader = io.StringIO('{"invocation_id":"invoke_1"}\n')
    writer = io.StringIO()

    assert entrypoint.serve(reader, writer) == 0
    lines = writer.getvalue().splitlines()
    assert len(lines) == 2
    assert '"kind":"started"' in lines[0]
    assert '"code":"provider_unavailable"' in lines[1]
