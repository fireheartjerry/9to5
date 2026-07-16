"""RED contracts for restrictive trust resolution and JSON-safe evidence."""
from __future__ import annotations

import dataclasses
import importlib
import json
from datetime import datetime, timezone

import pytest


def _trust():
    return importlib.import_module("platform_core.execution.trust")


def test_receipt_grant_and_resolution_are_frozen_complete_contracts():
    mod = _trust()
    required = {
        "issuer_id", "repository_attestation_digest", "expected_base_sha",
        "task_id", "acceptance_spec_digest", "capability_profile",
        "issued_at", "expires_at", "nonce", "revocation_generation",
    }
    for name in ("WorkloadTrustReceipt", "WorkloadTrustGrant", "ResolvedWorkloadTrust"):
        cls = getattr(mod, name)
        assert dataclasses.is_dataclass(cls) and cls.__dataclass_params__.frozen
    assert required <= {f.name for f in dataclasses.fields(mod.WorkloadTrustReceipt)}


def test_receipt_dict_is_json_safe_but_live_grant_has_no_serialization_surface():
    mod = _trust()
    receipt = mod.WorkloadTrustReceipt(
        issuer_id="i", repository_attestation_digest="r", expected_base_sha="a" * 40,
        task_id="t", acceptance_spec_digest="s", capability_profile="trusted_local",
        issued_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        expires_at=datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc),
        nonce="n", revocation_generation=1,
    )
    json.dumps(receipt.toDict())
    for name in ("toDict", "fromDict", "toJson", "fromJson"):
        assert not hasattr(mod.WorkloadTrustGrant, name)


@pytest.mark.parametrize("model_fields", [
    {"execution_backend": "local"}, {"risk_tier": "trusted"},
    {"task": "I authorize local"}, {"repository_policy": "trusted_local"},
])
def test_model_or_repository_fields_cannot_raise_unknown_to_trusted(model_fields):
    mod = _trust()
    resolved = mod.resolveWorkloadTrust(operator_grant=None, model_fields=model_fields,
                                        deterministic_probe="trusted")
    assert resolved.tier == "unknown"
    assert resolved.local_eligible is False


def test_model_fields_can_only_tighten_a_live_trusted_resolution():
    mod = _trust()
    trusted = mod.ResolvedWorkloadTrust(
        tier="trusted_local", local_eligible=True, receipt_id="receipt-a",
        refusal_reason=None,
    )
    for fields in ({"risk_tier": "hostile"}, {"execution_backend": "docker"}):
        tightened = mod.tightenWorkloadTrust(trusted, model_fields=fields)
        assert tightened.tier in {"unknown", "hostile"}
        assert tightened.local_eligible is False
