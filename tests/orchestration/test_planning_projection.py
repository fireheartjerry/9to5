"""RED contracts for receipt-bound, repo-relative planning context."""

from __future__ import annotations

import importlib

import pytest


def _pre_execution():
    return importlib.import_module("platform_core.execution.pre_execution")


def test_planning_projection_rejects_absolute_or_provider_visible_host_paths() -> None:
    mod = _pre_execution()
    with pytest.raises(mod.PreExecutionUnavailable):
        mod.normalizePlanningProjection(
            {
                "allowed_paths": ["src/main.py", "C:/canonical/secret.py"],
                "verify_targets": ["python -m pytest C:/canonical/tests"],
            }
        )


def test_context_receipt_contains_only_bounded_repo_relative_facts() -> None:
    mod = _pre_execution()
    receipt = mod.PreExecutionContextReceipt.create(
        base_revision="1" * 40,
        snapshot_digest="2" * 64,
        spec_digest="3" * 64,
        facts={
            "modules": ["platform_core/execution/environment.py"],
            "verify_targets": ["tests/execution/test_execution_environment.py"],
        },
        max_bytes=4096,
    )
    assert receipt.base_revision == "1" * 40
    assert "C:/" not in receipt.canonical_bytes.decode("utf-8")
    assert "\\\\" not in receipt.canonical_bytes.decode("utf-8")
