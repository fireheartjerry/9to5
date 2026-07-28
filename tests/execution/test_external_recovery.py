"""RED contracts for the anchor-only minimal recovery entrypoint."""

from __future__ import annotations

import importlib

import pytest


def _recovery():
    return importlib.import_module("platform_core.runtime.recovery")


def test_missing_recovery_authority_refuses_before_journal_observation() -> None:
    mod = _recovery()
    observations: list[str] = []
    controller = mod.ExternalRecoveryController(
        journal_lookup=lambda transaction_id: observations.append(transaction_id),
        path_inspector=lambda record: observations.append("inspect"),
    )

    with pytest.raises(mod.RecoveryRefused):
        controller.recover("tx_existing", authority=None)

    assert observations == []


def test_recovery_cannot_create_or_adopt_an_unknown_transaction() -> None:
    mod = _recovery()
    capability = object()
    controller = mod.ExternalRecoveryController(
        journal_lookup=lambda transaction_id: None,
        path_inspector=lambda record: (_ for _ in ()).throw(AssertionError("must not inspect")),
        process_capability=capability,
    )
    authority = controller._issueDiagnosticAuthority(
        transaction_id="tx_missing",
        controller_generation=3,
        process_capability=capability,
        expires_at="2099-01-01T00:00:00+00:00",
    )

    with pytest.raises(mod.RecoveryRefused):
        controller.recover("tx_missing", authority=authority)
