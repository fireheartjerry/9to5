"""RED contracts for dependency-safe recovery of every registered runtime resource."""

from __future__ import annotations

import importlib

import pytest


def _recovery():
    return importlib.import_module("platform_core.runtime.recovery")


def test_recovery_order_quiesces_dependants_before_owners() -> None:
    mod = _recovery()
    resources = (
        mod.RecoverableRuntimeResource("credential", "credential", ()),
        mod.RecoverableRuntimeResource("driver", "driver", ("credential",)),
        mod.RecoverableRuntimeResource("broker", "broker", ("driver",)),
        mod.RecoverableRuntimeResource("sandbox", "command_sandbox", ("broker",)),
        mod.RecoverableRuntimeResource("verifier", "verifier", ("sandbox",)),
    )

    ordered = mod.runtimeResourceRecoveryOrder(resources)

    assert tuple(item.resource_id for item in ordered) == (
        "verifier",
        "sandbox",
        "broker",
        "driver",
        "credential",
    )


def test_recovery_refuses_missing_dependency_instead_of_guessing() -> None:
    mod = _recovery()
    with pytest.raises(mod.RecoveryRefused):
        mod.runtimeResourceRecoveryOrder(
            (mod.RecoverableRuntimeResource("driver", "driver", ("missing",)),)
        )
