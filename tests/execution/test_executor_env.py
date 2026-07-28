"""RED contracts for the closed, backend-native model launch environment."""

from __future__ import annotations

import importlib

import pytest


def _launch_plan():
    return importlib.import_module("platform_core.execution.launch_plan")


def _plan(mod, environment: dict[str, str]):
    return mod.BackendLaunchPlan(
        transaction_id="tx_executor_env",
        driver_argv=("provider-adapter", "--stdio"),
        driver_environment=environment,
        driver_cwd="/driver",
        projection_root="/projection",
        session_root="/session",
        broker_operations=frozenset(
            {"repo_read", "repo_list", "repo_search", "repo_apply_patch", "repo_exec"}
        ),
        resource_ids=("resource_driver", "resource_broker"),
        mounts=(),
        egress_profile_digest="1" * 64,
        resource_profile_digest="2" * 64,
        security_profile_digest="3" * 64,
        capability_receipt_id="capability_executor_env",
        deadline="2099-01-01T00:00:00+00:00",
    )


def test_launch_environment_starts_empty_and_uses_only_plan_values(monkeypatch) -> None:
    mod = _launch_plan()
    monkeypatch.setenv("GIT_DIR", "C:/canonical/.git")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-leak")
    monkeypatch.setenv("PYTHONPATH", "C:/poison")

    environment = mod.buildLaunchEnvironment(
        _plan(
            mod,
            {
                "HOME": "/projection/home",
                "PATH": "/runtime/bin",
                "TMPDIR": "/scratch",
                "LANG": "C.UTF-8",
            },
        )
    )

    assert environment == {
        "HOME": "/projection/home",
        "LANG": "C.UTF-8",
        "PATH": "/runtime/bin",
        "TMPDIR": "/scratch",
    }
    assert not any("KEY" in key or key.startswith(("GIT_", "PYTHON")) for key in environment)


@pytest.mark.parametrize("name", ["GIT_DIR", "PWD", "PYTHONPATH", "VIRTUAL_ENV"])
def test_launch_environment_rejects_forbidden_names(name: str) -> None:
    mod = _launch_plan()
    with pytest.raises(mod.LaunchPlanRefused):
        mod.buildLaunchEnvironment(_plan(mod, {name: "poison"}))
