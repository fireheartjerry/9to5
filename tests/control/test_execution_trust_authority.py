"""RED behavioral contracts for exact, live, process-local trusted-Local grants."""
from __future__ import annotations

import dataclasses
import hashlib
import importlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest


SCOPE = dict(
    repository_attestation_digest="repo-a", expected_base_sha="a" * 40,
    task_id="task-a", acceptance_spec_digest="spec-a",
    capability_profile="trusted_local",
)


def _mod():
    return importlib.import_module("platform_core.runtime.execution_trust")


def _authority(tmp_path, *, issuer="operator-1", generation=7, capability=None):
    mod = _mod()
    return mod.OperatorTrustAuthority(
        issuer_id=issuer, revocation_generation=generation,
        process_capability=capability if capability is not None else object(),
        evidence_store=tmp_path / "trust.sqlite",
    )


def _issue(authority, **changes):
    scope = dict(SCOPE)
    scope.update(changes)
    expires_at = scope.pop("expires_at", datetime.now(timezone.utc) + timedelta(minutes=5))
    return authority.issueWorkloadGrant(
        **scope,
        expires_at=expires_at,
    )


def test_exact_scope_live_grant_resolves_trusted_local(tmp_path):
    authority = _authority(tmp_path)
    grant = _issue(authority)
    resolved = authority.resolve(grant=grant, **SCOPE)
    assert resolved.tier == "trusted_local"
    assert resolved.local_eligible is True
    assert resolved.receipt_id == grant.receipt.id


@pytest.mark.parametrize(("field", "value"), [
    ("repository_attestation_digest", "repo-b"),
    ("expected_base_sha", "b" * 40),
    ("task_id", "task-b"),
    ("acceptance_spec_digest", "spec-b"),
    ("capability_profile", "read_only"),
])
def test_every_scope_substitution_resolves_unknown_without_side_effect(tmp_path, field, value):
    authority = _authority(tmp_path)
    grant = _issue(authority)
    requested = dict(SCOPE)
    requested[field] = value
    launched = []
    resolved = authority.resolve(grant=grant, on_local_eligible=lambda: launched.append(True),
                                 **requested)
    assert resolved.tier == "unknown"
    assert resolved.local_eligible is False
    assert launched == []


def test_wrong_issuer_is_unknown_for_a_fresh_live_grant(tmp_path):
    authority = _authority(tmp_path)
    live = _issue(authority)
    wrong_issuer = _authority(tmp_path / "wrong-issuer", issuer="operator-2")
    assert wrong_issuer.resolve(grant=live, **SCOPE).tier == "unknown"


def test_expired_grant_is_unknown_without_revoking_a_live_grant(tmp_path):
    authority = _authority(tmp_path)
    expired = _issue(authority, expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    assert authority.resolve(grant=expired, **SCOPE).tier == "unknown"


def test_revoked_fresh_grant_is_unknown(tmp_path):
    authority = _authority(tmp_path)
    live = _issue(authority)
    authority.revoke(live)
    assert authority.resolve(grant=live, **SCOPE).tier == "unknown"


def test_restart_cannot_replay_a_fresh_still_live_process_local_grant(tmp_path):
    authority = _authority(tmp_path)
    live = _issue(authority)
    assert authority.resolve(grant=live, **SCOPE).tier == "trusted_local"
    restarted = _authority(tmp_path, capability=object())
    assert restarted.resolve(grant=live, **SCOPE).tier == "unknown"


@pytest.mark.parametrize("attack", ["replace_row", "forge_row", "rollback_generation"])
def test_receipt_copy_store_forgery_replacement_and_generation_rollback_never_reissue(
        tmp_path, attack):
    mod = _mod()
    root = tmp_path / attack
    authority = _authority(root)
    grant = _issue(authority)
    copied = mod.WorkloadTrustReceipt.fromDict(grant.receipt.toDict())
    assert authority.resolve(grant=copied, **SCOPE).tier == "unknown"
    store_path = root / "trust.sqlite"
    forged = grant.receipt.toDict()
    forged["expected_base_sha"] = "b" * 40
    canonical = json.dumps(forged, sort_keys=True, separators=(",", ":"))
    with sqlite3.connect(store_path) as db:
        if attack == "replace_row":
            db.execute(
                "UPDATE trust_receipts SET receipt_json=? WHERE receipt_id=?",
                (canonical, grant.receipt.id),
            )
        elif attack == "forge_row":
            db.execute(
                "UPDATE trust_receipts SET receipt_json=?, receipt_digest=? WHERE receipt_id=?",
                (canonical, hashlib.sha256(canonical.encode()).hexdigest(), grant.receipt.id),
            )
        else:
            db.execute(
                "UPDATE trust_metadata SET value=? WHERE key='revocation_generation'",
                (str(grant.receipt.revocation_generation - 1),),
            )
        db.commit()
    restarted = _authority(root, capability=object())
    assert restarted.resolve(grant=grant, **SCOPE).tier == "unknown"


def test_grant_is_frozen_and_post_issue_mutation_is_impossible(tmp_path):
    grant = _issue(_authority(tmp_path))
    with pytest.raises(dataclasses.FrozenInstanceError):
        grant.receipt.expected_base_sha = "b" * 40
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError, TypeError)):
        grant.capability_profile = "trusted_local_plus"
