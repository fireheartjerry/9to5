"""RED runtime contracts for the Task 1/2 zero-inference embargo."""
from __future__ import annotations

import importlib

import pytest


def _guard():
    return importlib.import_module("platform_core.execution.launch_guard")


@pytest.mark.parametrize("label", [
    "run", "resume", "read_only", "verifier", "architect",
    "clarification", "health", "analysis",
])
@pytest.mark.parametrize("backend", [None, "local", "docker", "worktree", "remote"])
def test_intermediate_kernel_refuses_every_label_backend_and_forged_input(label, backend, monkeypatch):
    mod = _guard()
    for key in ("GALAXY_ACTIVE", "TRANSACTIONAL_KERNEL_ACTIVE", "RUN_ADMISSION_ACTIVE"):
        monkeypatch.setenv(key, "1")
    forged = {"active": True, "receipt": {"status": "active"},
              "trust_grant": object(), "backend": backend, "label": label}
    with pytest.raises(mod.TransactionalKernelInactive):
        mod.requireTransactionalKernelActive(**forged)


def test_guard_has_no_runtime_activation_mutator():
    mod = _guard()
    for name in ("activate", "setActive", "enable", "installReceipt"):
        assert not hasattr(mod, name)
