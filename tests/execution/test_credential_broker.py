"""RED contracts for non-secret durable credential lifecycle metadata."""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import importlib
import inspect
import json
import os
import subprocess
import sys
import threading
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from platform_core.runtime.candidate import (
    CredentialResourceState,
    ResourceRole,
    RuntimeResourceLease,
    RuntimeResourceProbeRefused,
    processStartToken,
    runtimeResourceIsQuiescent,
)
from platform_core.runtime.attempt_journal import (
    AttemptJournal,
    AttemptRecord,
)


def _credentials():
    return importlib.import_module("platform_core.execution.credential_broker")


def _registered_resource(*, transaction_id: str = "tx_credential") -> RuntimeResourceLease:
    return RuntimeResourceLease(
        resource_id="credential_lease",
        run_id="run_001",
        transaction_id=transaction_id,
        controller_scope_id="controller_001",
        role=ResourceRole.CREDENTIAL_LEASE,
        backend="credential-broker",
        ownership_nonce="a" * 64,
        state=CredentialResourceState.REGISTERED,
        cleanup_locator_digest="b" * 64,
        pid=0,
        process_group_id=0,
        container_id="",
        image_digest="",
        entrypoint_digest="",
        mount_digest="",
        environment_digest="",
        security_profile_digest="c" * 64,
        created_at="2026-07-20T09:00:00+00:00",
        updated_at="2026-07-20T09:00:00+00:00",
        provider="codex",
        auth_mode="subscription",
        secret_channel_id="secret_channel_001",
        expires_at="2099-01-01T00:00:00+00:00",
        issuer_id="credential_broker_001",
        revocation_generation=7,
    )


def _clock() -> datetime:
    return datetime(2098, 1, 1, 0, 0, tzinfo=timezone.utc)


def _metadata_path(root: Path, resource_id: str) -> Path:
    digest = hashlib.sha256(resource_id.encode("utf-8")).hexdigest()
    return root / f"{digest}.json"


def _journaled_resource(
    tmp_path: Path,
    resource: RuntimeResourceLease,
) -> AttemptJournal:
    clone = tmp_path / "clone"
    clone.mkdir(parents=True, exist_ok=True)
    record = AttemptRecord(
        transaction_id=resource.transaction_id,
        task_id="task-001",
        subtask_id="subtask-001",
        attempt_id="attempt-001",
        repository_id="1" * 64,
        canonical_root=str(tmp_path / "canonical"),
        canonical_ref="refs/heads/main",
        base_revision="a" * 40,
        candidate_kind="clone",
        clone_lease_id="clone-001",
        clone_path=str(clone),
        ownership_nonce=resource.ownership_nonce,
        spec_digest="3" * 64,
        policy_digest="4" * 64,
        canonical_metadata_attestation_digest="5" * 64,
        object_format="sha1",
        oid_length=40,
        ref_backend="files",
        candidate_branch=(
            f"refs/heads/9to5/candidates/{resource.transaction_id}"
        ),
        checkpoint_message_digest="6" * 64,
        proposal_message_digest="7" * 64,
        commit_timestamp_seed=resource.created_at,
        runner_kind="docker",
        candidate_git_dir=str(clone / ".git"),
        canonical_git_common_dir=str(tmp_path / "canonical" / ".git"),
        source_manifest_digest="8" * 64,
        source_object_closure_digest="9" * 64,
        source_snapshot_digest="a" * 64,
        source_parser_receipt_id="b" * 64,
        source_payload_root=str(tmp_path / "source-payloads"),
        created_at=resource.created_at,
        updated_at=resource.updated_at,
    )
    journal = AttemptJournal(tmp_path / "journal")
    journal.create(record)
    journal.register_resources(resource.transaction_id, (resource,))
    return journal


def _issue_and_revoke(
    *,
    root: Path,
    clock=_clock,
    resource: RuntimeResourceLease | None = None,
):
    mod = _credentials()
    process_capability = object()
    resource = resource or _registered_resource()
    journal = _journaled_resource(root.parent / f"{root.name}-attempt", resource)
    broker = mod.CredentialBroker(
        metadata_root=root,
        secret_provider=lambda _provider: b"credential-goldstone",
        process_capability=process_capability,
        attempt_journal=journal,
        issuer_id=resource.issuer_id,
        clock=clock,
    )
    authority = broker.issueAuthority(
        process_capability=process_capability,
        resource=resource,
        transaction_id=resource.transaction_id,
        provider=resource.provider,
        deadline=resource.expires_at,
    )
    lease = broker.issue(resource=resource, authority=authority)
    broker.revoke(lease)
    revoked = journal.load_resources(resource.transaction_id)[0]
    return mod, resource, revoked, broker, process_capability, journal


def test_destruction_receipt_is_closed_content_addressed_and_frozen() -> None:
    channel = importlib.import_module("platform_core.runtime.credential_channel")
    receipt = channel.CredentialChannelDestructionReceipt.issue(
        transaction_id="tx_credential",
        resource_id="credential_lease",
        secret_channel_id="secret_channel_001",
        issuer_id="credential_broker_001",
        revocation_generation=7,
        cleanup_locator_digest="1" * 64,
        destroyed_at="2026-07-20T10:00:00+00:00",
    )

    assert set(receipt.toDict()) == {
        "cleanup_locator_digest",
        "destroyed_at",
        "issuer_id",
        "receipt_digest",
        "resource_id",
        "revocation_generation",
        "schema",
        "secret_channel_id",
        "transaction_id",
    }
    assert channel.CredentialChannelDestructionReceipt.fromBytes(
        receipt.toBytes()
    ) == receipt
    with pytest.raises(FrozenInstanceError):
        receipt.resource_id = "rewritten"  # type: ignore[misc]
    with pytest.raises(channel.CredentialChannelEvidenceRefused, match="digest"):
        replace(receipt, receipt_digest="f" * 64)


@pytest.mark.parametrize(
    "destroyed_at",
    [
        "2026-07-20T10:00:00Z",
        "2026-07-20T06:00:00-04:00",
        "2026-07-20T10:00:00.000000+00:00",
    ],
)
def test_destruction_receipt_requires_one_canonical_utc_timestamp(
    destroyed_at: str,
) -> None:
    channel = importlib.import_module("platform_core.runtime.credential_channel")

    with pytest.raises(channel.CredentialChannelEvidenceRefused, match="canonical UTC"):
        channel.CredentialChannelDestructionReceipt.issue(
            transaction_id="tx_credential",
            resource_id="credential_lease",
            secret_channel_id="secret_channel_001",
            issuer_id="credential_broker_001",
            revocation_generation=7,
            cleanup_locator_digest="1" * 64,
            destroyed_at=destroyed_at,
        )


def test_destruction_receipt_uses_the_runtime_resource_identifier_bound() -> None:
    channel = importlib.import_module("platform_core.runtime.credential_channel")

    with pytest.raises(channel.CredentialChannelEvidenceRefused, match="resource_id"):
        channel.CredentialChannelDestructionReceipt.issue(
            transaction_id="tx_credential",
            resource_id="r" * 129,
            secret_channel_id="secret_channel_001",
            issuer_id="credential_broker_001",
            revocation_generation=7,
            cleanup_locator_digest="1" * 64,
            destroyed_at="2026-07-20T10:00:00+00:00",
        )


def test_missing_authority_refuses_before_secret_derivation(tmp_path: Path) -> None:
    mod = _credentials()
    derived: list[str] = []

    def derive(provider: str) -> bytes:
        derived.append(provider)
        return b"credential-goldstone"

    broker = mod.CredentialBroker(
        metadata_root=tmp_path / "metadata",
        secret_provider=derive,
    )

    with pytest.raises(mod.CredentialBrokerRefused):
        broker.issue(
            transaction_id="tx_credential",
            provider="codex",
            deadline="2099-01-01T00:00:00+00:00",
            authority=None,
        )

    assert derived == []
    assert not (tmp_path / "metadata").exists()


def test_nonjournaled_resource_cannot_receive_credential_issue_authority(
    tmp_path: Path,
) -> None:
    mod = _credentials()
    resource = _registered_resource()
    capability = object()
    root = tmp_path / "metadata"
    broker = mod.CredentialBroker(
        metadata_root=root,
        secret_provider=lambda _provider: pytest.fail(
            "secret derivation must not run"
        ),
        process_capability=capability,
        issuer_id=resource.issuer_id,
        clock=_clock,
    )

    with pytest.raises(mod.CredentialBrokerRefused, match="journal|preregister"):
        broker.issueAuthority(
            process_capability=capability,
            resource=resource,
            transaction_id=resource.transaction_id,
            provider=resource.provider,
            deadline=resource.expires_at,
        )

    assert not root.exists()


def test_channel_lifecycle_retains_exact_broker_not_generic_callback_authority(
    tmp_path: Path,
) -> None:
    mod = _credentials()
    resource = _registered_resource()
    capability = object()
    journal = _journaled_resource(tmp_path / "attempt", resource)
    broker = mod.CredentialBroker(
        metadata_root=tmp_path / "credential-store",
        secret_provider=lambda _provider: b"credential-goldstone",
        process_capability=capability,
        attempt_journal=journal,
        issuer_id=resource.issuer_id,
        clock=_clock,
    )
    destroyer = broker.channelDestroyer(
        process_capability=capability,
        resource=resource,
    )
    verifier = broker.freshAbsenceVerifier(
        process_capability=capability,
        resource=resource,
    )

    assert not hasattr(destroyer, "revokeWithStateCommit")
    assert not hasattr(destroyer, "destroyWithTerminalCommit")
    assert destroyer._broker is broker
    assert verifier._broker is broker
    for callback_slot in (
        "_zero_secret",
        "_mark_revoked",
        "_mark_destroyed",
        "_load_terminal_receipt",
        "_destruction_guard",
        "_terminal_metadata_exact",
        "_terminal_metadata_absent",
        "_clock",
    ):
        assert not hasattr(destroyer, callback_slot)
        assert not hasattr(verifier, callback_slot)
    channel = importlib.import_module("platform_core.runtime.credential_channel")
    assert set(
        inspect.signature(channel._createCredentialChannelDestroyer).parameters
    ) == {"broker", "absence_verifier", "coordinator", "resource"}
    assert set(
        inspect.signature(channel._createCredentialChannelAbsenceVerifier).parameters
    ) == {"broker"}


def test_copied_channel_lifecycle_objects_cannot_destroy_or_prove_absence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "credential-store"
    _mod, resource, revoked, broker, capability, journal = _issue_and_revoke(
        root=root
    )
    destroyer = broker.channelDestroyer(
        process_capability=capability,
        resource=revoked,
    )
    forged_destroyer = copy.copy(destroyer)
    channel_path = broker._channelPath(resource.secret_channel_id)

    with pytest.raises(Exception, match="copied|reflected|broker-issued"):
        forged_destroyer.destroy(revoked)

    assert channel_path.is_file()
    assert journal.load_resources(resource.transaction_id)[0].state is (
        CredentialResourceState.REVOKED_OR_EXPIRED
    )
    destroyer.destroy(revoked)
    destroyed = journal.load_resources(resource.transaction_id)[0]
    verifier = broker.freshAbsenceVerifier(
        process_capability=capability,
        resource=destroyed,
    )

    with pytest.raises(RuntimeResourceProbeRefused, match="could not be proven"):
        runtimeResourceIsQuiescent(
            destroyed,
            credential_absence_verifier=copy.copy(verifier),
        )


def test_unissued_verifier_cannot_be_composed_into_a_destroyer(
    tmp_path: Path,
) -> None:
    root = tmp_path / "credential-store"
    _mod, resource, revoked, broker, capability, journal = _issue_and_revoke(
        root=root
    )
    channel = importlib.import_module("platform_core.runtime.credential_channel")
    issued = broker.freshAbsenceVerifier(
        process_capability=capability,
        resource=revoked,
    )
    forged = type(issued)(
        broker=broker,
        _factory=channel._FACTORY_TOKEN,
    )

    with pytest.raises(
        channel.CredentialChannelEvidenceRefused,
        match="broker-issued|copied|reflected",
    ):
        channel._createCredentialChannelDestroyer(
            broker=broker,
            absence_verifier=forged,
            coordinator=broker._coordinator(revoked),
            resource=revoked,
        )

    assert broker._channelPath(resource.secret_channel_id).is_file()
    assert journal.load_resources(resource.transaction_id)[0].state is (
        CredentialResourceState.REVOKED_OR_EXPIRED
    )


@pytest.mark.parametrize("forgery", ["replace", "constructor", "object-new"])
def test_credential_issue_authority_copy_and_reflection_refuse_before_secret(
    tmp_path: Path,
    forgery: str,
) -> None:
    mod = _credentials()
    resource = _registered_resource()
    capability = object()
    derived: list[str] = []
    root = tmp_path / forgery
    journal = _journaled_resource(tmp_path / f"{forgery}-attempt", resource)
    broker = mod.CredentialBroker(
        metadata_root=root,
        secret_provider=lambda provider: derived.append(provider)
        or b"credential-goldstone",
        process_capability=capability,
        attempt_journal=journal,
        issuer_id=resource.issuer_id,
        clock=_clock,
    )
    authority = broker.issueAuthority(
        process_capability=capability,
        resource=resource,
        transaction_id=resource.transaction_id,
        provider=resource.provider,
        deadline=resource.expires_at,
    )
    authority_type = type(authority)
    if forgery == "replace":
        forged = replace(authority)
    elif forgery == "constructor":
        forged = authority_type(
            **{
                field.name: getattr(authority, field.name)
                for field in dataclasses.fields(authority)
            }
        )
    else:
        forged = object.__new__(authority_type)
        for field in dataclasses.fields(authority):
            object.__setattr__(forged, field.name, getattr(authority, field.name))

    with pytest.raises(mod.CredentialBrokerRefused, match="authority.*binding|exact"):
        broker.issue(resource=resource, authority=forged)

    assert derived == []
    assert not root.exists()


def test_credential_issue_authority_cannot_move_to_a_second_resource(
    tmp_path: Path,
) -> None:
    mod = _credentials()
    resource = _registered_resource()
    second = replace(
        resource,
        resource_id="credential_lease_second",
        secret_channel_id="secret_channel_002",
    )
    capability = object()
    derived: list[str] = []
    journal = _journaled_resource(tmp_path / "attempt", resource)
    broker = mod.CredentialBroker(
        metadata_root=tmp_path / "credential-store",
        secret_provider=lambda provider: derived.append(provider)
        or b"credential-goldstone",
        process_capability=capability,
        attempt_journal=journal,
        issuer_id=resource.issuer_id,
        clock=_clock,
    )
    authority = broker.issueAuthority(
        process_capability=capability,
        resource=resource,
        transaction_id=resource.transaction_id,
        provider=resource.provider,
        deadline=resource.expires_at,
    )

    with pytest.raises(mod.CredentialBrokerRefused, match="resource|scope|binding"):
        broker.issue(resource=second, authority=authority)

    assert derived == []


@pytest.mark.parametrize("operation", ["mark-injected", "revoke"])
def test_nonterminal_lease_mutation_cannot_overwrite_concurrent_destruction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    mod = _credentials()
    process_capability = object()
    root = tmp_path / "credential-store"
    resource = _registered_resource()
    journal = _journaled_resource(tmp_path / "attempt", resource)
    broker = mod.CredentialBroker(
        metadata_root=root,
        secret_provider=lambda _provider: b"credential-goldstone",
        process_capability=process_capability,
        attempt_journal=journal,
        issuer_id=resource.issuer_id,
        clock=_clock,
    )
    authority = broker.issueAuthority(
        process_capability=process_capability,
        resource=resource,
        transaction_id=resource.transaction_id,
        provider=resource.provider,
        deadline=resource.expires_at,
    )
    lease = broker.issue(resource=resource, authority=authority)
    revoked = replace(
        resource,
        state=CredentialResourceState.REVOKED_OR_EXPIRED,
        secret_fingerprint=lease.metadata.secret_fingerprint,
        updated_at="2026-07-20T09:30:00+00:00",
    )
    destroyer = broker.channelDestroyer(
        process_capability=process_capability,
        resource=revoked,
    )

    mutation_entered_persist = threading.Event()
    release_mutation = threading.Event()
    destruction_persisted_terminal = threading.Event()
    original_persist = broker._persist
    broker_type = type(broker)
    original_mark_destroyed = broker_type._markDestroyed

    def blocked_persist(metadata, *, create: bool = False) -> None:
        if threading.current_thread().name == "nonterminal-mutation":
            mutation_entered_persist.set()
            assert release_mutation.wait(timeout=5)
        original_persist(metadata, create=create)

    def observed_mark_destroyed(self, resource, receipt) -> None:
        original_mark_destroyed(self, resource, receipt)
        destruction_persisted_terminal.set()

    monkeypatch.setattr(broker, "_persist", blocked_persist)
    monkeypatch.setattr(broker_type, "_markDestroyed", observed_mark_destroyed)

    failures: list[BaseException] = []
    receipts = []

    def mutate() -> None:
        try:
            if operation == "mark-injected":
                broker.markInjected(lease)
            else:
                broker.revoke(lease)
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    def destroy() -> None:
        try:
            receipts.append(destroyer.destroy(revoked))
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    mutation_thread = threading.Thread(target=mutate, name="nonterminal-mutation")
    destruction_thread = threading.Thread(target=destroy, name="terminal-destruction")
    mutation_thread.start()
    assert mutation_entered_persist.wait(timeout=5)
    destruction_thread.start()
    destruction_persisted_terminal.wait(timeout=0.5)
    release_mutation.set()
    mutation_thread.join(timeout=5)
    destruction_thread.join(timeout=5)

    assert not mutation_thread.is_alive()
    assert not destruction_thread.is_alive()
    assert failures == []
    assert len(receipts) == 1
    metadata = json.loads(
        _metadata_path(root, resource.resource_id).read_text(encoding="utf-8")
    )
    assert metadata["state"] == "destroyed"
    assert metadata["destruction_receipt_digest"] == receipts[0].receipt_digest


def test_destroyer_revoke_holds_the_same_destruction_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mod, _resource, revoked, broker, process_capability, _journal = _issue_and_revoke(
        root=tmp_path / "credential-store"
    )
    destroyer = broker.channelDestroyer(
        process_capability=process_capability,
        resource=revoked,
    )
    events: list[str] = []
    broker_type = type(broker)
    original_guard = broker_type._channelGuard
    original_zero = broker_type._zeroSecret

    @contextmanager
    def observed_guard(self):
        events.append("guard-enter")
        with original_guard(self):
            try:
                yield
            finally:
                events.append("guard-exit")

    def observed_zero(self, resource_id: str) -> None:
        events.append("zero-secret")
        original_zero(self, resource_id)

    monkeypatch.setattr(broker_type, "_channelGuard", observed_guard)
    monkeypatch.setattr(broker_type, "_zeroSecret", observed_zero)

    destroyer.revoke(revoked)

    assert events == ["guard-enter", "zero-secret", "guard-exit"]


@pytest.mark.parametrize("operation", ["mark-injected", "revoke"])
def test_terminal_destruction_refuses_stale_nonterminal_mutation_without_rewrite(
    tmp_path: Path,
    operation: str,
) -> None:
    mod = _credentials()
    process_capability = object()
    root = tmp_path / "credential-store"
    resource = _registered_resource()
    journal = _journaled_resource(tmp_path / "attempt", resource)
    broker = mod.CredentialBroker(
        metadata_root=root,
        secret_provider=lambda _provider: b"credential-goldstone",
        process_capability=process_capability,
        attempt_journal=journal,
        issuer_id=resource.issuer_id,
        clock=_clock,
    )
    authority = broker.issueAuthority(
        process_capability=process_capability,
        resource=resource,
        transaction_id=resource.transaction_id,
        provider=resource.provider,
        deadline=resource.expires_at,
    )
    lease = broker.issue(resource=resource, authority=authority)
    revoked = replace(
        resource,
        state=CredentialResourceState.REVOKED_OR_EXPIRED,
        secret_fingerprint=lease.metadata.secret_fingerprint,
        updated_at="2026-07-20T09:30:00+00:00",
    )
    receipt = broker.channelDestroyer(
        process_capability=process_capability,
        resource=revoked,
    ).destroy(revoked)
    metadata_path = _metadata_path(root, resource.resource_id)
    receipt_path = root / "destruction-receipts" / f"{receipt.receipt_digest}.json"
    terminal_intent_path = next(
        (root / "destruction-intents").glob("*.terminal.json")
    )
    before = (
        metadata_path.read_bytes(),
        receipt_path.read_bytes(),
        terminal_intent_path.read_bytes(),
    )

    with pytest.raises(mod.CredentialBrokerRefused, match="ownership|issuable"):
        if operation == "mark-injected":
            broker.markInjected(lease)
        else:
            broker.revoke(lease)

    assert (
        metadata_path.read_bytes(),
        receipt_path.read_bytes(),
        terminal_intent_path.read_bytes(),
    ) == before
    assert not broker._channelPath(resource.secret_channel_id).exists()
    assert resource.resource_id not in broker._leases
    with pytest.raises(mod.CredentialBrokerRefused, match="no longer live"):
        lease.secretView()


def test_credential_metadata_schema_cannot_serialize_secret_bytes(tmp_path: Path) -> None:
    mod = _credentials()
    lease = mod.CredentialLeaseMetadata(
        lease_id="credential_lease",
        transaction_id="tx_credential",
        provider="codex",
        state="registered",
        channel_locator_digest="1" * 64,
        issued_at="2098-01-01T00:00:00+00:00",
        expires_at="2099-01-01T00:00:00+00:00",
        auth_mode="subscription",
        secret_channel_id="secret_channel_001",
        issuer_id="credential_broker_001",
        revocation_generation=1,
    )

    encoded = json.dumps(lease.toDict(), sort_keys=True)
    assert "credential-goldstone" not in encoded
    assert set(lease.toDict()) == {
        "channel_locator_digest",
        "auth_mode",
        "destruction_receipt_digest",
        "destroyed_at",
        "expires_at",
        "issued_at",
        "issuer_id",
        "holder_pid",
        "holder_start_token",
        "lease_id",
        "provider",
        "revocation_generation",
        "secret_channel_id",
        "secret_fingerprint",
        "state",
        "transaction_id",
    }


def test_credential_lease_metadata_is_broker_owned_and_forged_leases_refuse(
    tmp_path: Path,
) -> None:
    mod = _credentials()
    process_capability = object()
    resource = _registered_resource()
    journal = _journaled_resource(tmp_path / "attempt", resource)
    broker = mod.CredentialBroker(
        metadata_root=tmp_path / "credential-store",
        secret_provider=lambda _provider: b"credential-goldstone",
        process_capability=process_capability,
        attempt_journal=journal,
        issuer_id=resource.issuer_id,
        clock=_clock,
    )
    authority = broker.issueAuthority(
        process_capability=process_capability,
        resource=resource,
        transaction_id=resource.transaction_id,
        provider=resource.provider,
        deadline=resource.expires_at,
    )
    lease = broker.issue(resource=resource, authority=authority)

    with pytest.raises(AttributeError):
        lease.metadata = replace(lease.metadata, state="injected")
    for forged in (
        copy.copy(lease),
        mod.CredentialLease(lease.metadata, b"credential-goldstone"),
    ):
        with pytest.raises(mod.CredentialBrokerRefused, match="binding|ownership"):
            broker.markInjected(forged)


def test_retained_secret_view_is_zeroed_without_blocking_terminal_lifecycle(
    tmp_path: Path,
) -> None:
    mod = _credentials()
    process_capability = object()
    resource = _registered_resource()
    journal = _journaled_resource(tmp_path / "attempt", resource)
    broker = mod.CredentialBroker(
        metadata_root=tmp_path / "credential-store",
        secret_provider=lambda _provider: b"credential-goldstone",
        process_capability=process_capability,
        attempt_journal=journal,
        issuer_id=resource.issuer_id,
        clock=_clock,
    )
    authority = broker.issueAuthority(
        process_capability=process_capability,
        resource=resource,
        transaction_id=resource.transaction_id,
        provider=resource.provider,
        deadline=resource.expires_at,
    )
    lease = broker.issue(resource=resource, authority=authority)
    retained = lease.secretView()

    broker.revoke(lease)

    assert retained.tobytes() == b"\x00" * len(b"credential-goldstone")
    assert lease.metadata.state == "revoked_or_expired"
    with pytest.raises(mod.CredentialBrokerRefused, match="no longer live"):
        lease.secretView()


def test_issue_lost_response_reconciles_exactly_without_second_derivation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _credentials()
    capability = object()
    resource = _registered_resource()
    journal = _journaled_resource(tmp_path / "attempt", resource)
    derived: list[str] = []
    broker = mod.CredentialBroker(
        metadata_root=tmp_path / "credential-store",
        secret_provider=lambda provider: derived.append(provider)
        or b"credential-goldstone",
        process_capability=capability,
        attempt_journal=journal,
        issuer_id=resource.issuer_id,
        clock=_clock,
    )
    authority = broker.issueAuthority(
        process_capability=capability,
        resource=resource,
        transaction_id=resource.transaction_id,
        provider=resource.provider,
        deadline=resource.expires_at,
    )
    coordinator = broker._authorities[id(authority)].coordinator
    coordinator_type = type(coordinator)
    original_commit = coordinator_type.commitIssued
    crashed = False

    def crash_after_broker_commit(self, bound_resource, *, secret_fingerprint):
        nonlocal crashed
        if self is coordinator and not crashed:
            crashed = True
            raise mod.AttemptPersistenceAuthorityRefused("lost response")
        return original_commit(
            self,
            bound_resource,
            secret_fingerprint=secret_fingerprint,
        )

    monkeypatch.setattr(coordinator_type, "commitIssued", crash_after_broker_commit)
    with pytest.raises(mod.CredentialBrokerRefused, match="reconciliation"):
        broker.issue(resource=resource, authority=authority)

    assert journal.load_resources(resource.transaction_id)[0].state is (
        CredentialResourceState.REGISTERED
    )
    retained = broker._leases[resource.resource_id]
    retained_view = retained.secretView()
    replay = broker.issue(resource=resource, authority=authority)

    assert replay is retained
    assert derived == [resource.provider]
    assert journal.load_resources(resource.transaction_id)[0].state is (
        CredentialResourceState.ISSUED
    )
    broker.revoke(replay)
    assert retained_view.tobytes() == b"\x00" * len(b"credential-goldstone")


def test_second_broker_recovers_issued_prefix_and_zeroes_all_process_views(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _credentials()
    resource = _registered_resource()
    journal = _journaled_resource(tmp_path / "attempt", resource)
    root = tmp_path / "credential-store"
    first_capability = object()
    first = mod.CredentialBroker(
        metadata_root=root,
        secret_provider=lambda _provider: b"credential-goldstone",
        process_capability=first_capability,
        attempt_journal=journal,
        issuer_id=resource.issuer_id,
        clock=_clock,
    )
    first_authority = first.issueAuthority(
        process_capability=first_capability,
        resource=resource,
        transaction_id=resource.transaction_id,
        provider=resource.provider,
        deadline=resource.expires_at,
    )
    coordinator = first._authorities[id(first_authority)].coordinator
    coordinator_type = type(coordinator)
    original_commit = coordinator_type.commitIssued

    def crash_before_journal(self, bound_resource, *, secret_fingerprint):
        if self is coordinator:
            raise mod.AttemptPersistenceAuthorityRefused("hard-death prefix")
        return original_commit(
            self,
            bound_resource,
            secret_fingerprint=secret_fingerprint,
        )

    monkeypatch.setattr(coordinator_type, "commitIssued", crash_before_journal)
    with pytest.raises(mod.CredentialBrokerRefused, match="reconciliation"):
        first.issue(resource=resource, authority=first_authority)
    first_lease = first._leases[resource.resource_id]
    first_view = first_lease.secretView()
    monkeypatch.setattr(coordinator_type, "commitIssued", original_commit)

    second_capability = object()
    second = mod.CredentialBroker(
        metadata_root=root,
        secret_provider=lambda _provider: pytest.fail(
            "durable issued prefix must not derive a second secret"
        ),
        process_capability=second_capability,
        attempt_journal=journal,
        issuer_id=resource.issuer_id,
        clock=_clock,
    )
    second_authority = second.issueAuthority(
        process_capability=second_capability,
        resource=resource,
        transaction_id=resource.transaction_id,
        provider=resource.provider,
        deadline=resource.expires_at,
    )
    second_lease = second.issue(resource=resource, authority=second_authority)
    second_view = second_lease.secretView()
    second.revoke(second_lease)

    assert first_view.tobytes() == b"\x00" * len(b"credential-goldstone")
    assert second_view.tobytes() == b"\x00" * len(b"credential-goldstone")
    assert journal.load_resources(resource.transaction_id)[0].state is (
        CredentialResourceState.REVOKED_OR_EXPIRED
    )


def test_real_hard_death_after_broker_issue_recovers_without_secret_rederivation(
    tmp_path: Path,
) -> None:
    mod = _credentials()
    resource = _registered_resource(transaction_id="tx_hard_death_issue")
    journal = _journaled_resource(tmp_path / "attempt", resource)
    root = tmp_path / "credential-store"
    script = r"""
import os
import sys

from platform_core.execution.credential_broker import CredentialBroker
from platform_core.runtime.attempt_journal import AttemptJournal

root, journal_root, transaction_id = sys.argv[1:]
journal = AttemptJournal(journal_root)
resource = journal.load_resources(transaction_id)[0]
capability = object()
broker = CredentialBroker(
    metadata_root=root,
    secret_provider=lambda _provider: b"credential-goldstone",
    process_capability=capability,
    attempt_journal=journal,
    issuer_id=resource.issuer_id,
)
authority = broker.issueAuthority(
    process_capability=capability,
    resource=resource,
    transaction_id=resource.transaction_id,
    provider=resource.provider,
    deadline=resource.expires_at,
)
coordinator = broker._authorities[id(authority)].coordinator
type(coordinator).commitIssued = lambda *_args, **_kwargs: os._exit(79)
broker.issue(resource=resource, authority=authority)
raise AssertionError("credential issue failpoint did not terminate")
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path.cwd())

    crashed = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            os.fspath(root),
            os.fspath(journal.root),
            resource.transaction_id,
        ],
        cwd=Path.cwd(),
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )

    assert crashed.returncode == 79, crashed.stderr.decode(errors="replace")
    assert journal.load_resources(resource.transaction_id)[0].state is (
        CredentialResourceState.REGISTERED
    )
    issued_prefix = json.loads(
        _metadata_path(root, resource.resource_id).read_text(encoding="utf-8")
    )
    assert issued_prefix["state"] == "issued"
    assert processStartToken(issued_prefix["holder_pid"]) != issued_prefix[
        "holder_start_token"
    ]

    capability = object()
    recovered = mod.CredentialBroker(
        metadata_root=root,
        secret_provider=lambda _provider: pytest.fail(
            "hard-death recovery must reuse the registered secret channel"
        ),
        process_capability=capability,
        attempt_journal=journal,
        issuer_id=resource.issuer_id,
        clock=_clock,
    )
    authority = recovered.issueAuthority(
        process_capability=capability,
        resource=resource,
        transaction_id=resource.transaction_id,
        provider=resource.provider,
        deadline=resource.expires_at,
    )
    lease = recovered.issue(resource=resource, authority=authority)
    retained = lease.secretView()

    assert journal.load_resources(resource.transaction_id)[0].state is (
        CredentialResourceState.ISSUED
    )
    recovered.revoke(lease)
    assert retained.tobytes() == b"\x00" * len(b"credential-goldstone")


def test_injected_and_revoked_prefixes_reconcile_without_state_rewrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _credentials()
    resource = _registered_resource()
    journal = _journaled_resource(tmp_path / "attempt", resource)
    capability = object()
    broker = mod.CredentialBroker(
        metadata_root=tmp_path / "credential-store",
        secret_provider=lambda _provider: b"credential-goldstone",
        process_capability=capability,
        attempt_journal=journal,
        issuer_id=resource.issuer_id,
        clock=_clock,
    )
    authority = broker.issueAuthority(
        process_capability=capability,
        resource=resource,
        transaction_id=resource.transaction_id,
        provider=resource.provider,
        deadline=resource.expires_at,
    )
    lease = broker.issue(resource=resource, authority=authority)
    coordinator = broker._authorities[id(authority)].coordinator
    coordinator_type = type(coordinator)
    original_injected = coordinator_type.commitInjected

    def lose_injected_response(self, bound_resource):
        if self is coordinator:
            raise mod.AttemptPersistenceAuthorityRefused("injected prefix")
        return original_injected(self, bound_resource)

    monkeypatch.setattr(coordinator_type, "commitInjected", lose_injected_response)
    with pytest.raises(mod.CredentialBrokerRefused, match="reconciliation"):
        broker.markInjected(lease)
    assert broker._loadMetadata(resource.resource_id).state == "injected"
    assert journal.load_resources(resource.transaction_id)[0].state is (
        CredentialResourceState.ISSUED
    )
    monkeypatch.setattr(coordinator_type, "commitInjected", original_injected)
    broker.markInjected(lease)
    assert journal.load_resources(resource.transaction_id)[0].state is (
        CredentialResourceState.INJECTED
    )

    original_revoked = coordinator_type.commitRevoked

    def lose_revoked_response(self, bound_resource):
        if self is coordinator:
            raise mod.AttemptPersistenceAuthorityRefused("revoked prefix")
        return original_revoked(self, bound_resource)

    retained = lease.secretView()
    monkeypatch.setattr(coordinator_type, "commitRevoked", lose_revoked_response)
    with pytest.raises(mod.CredentialBrokerRefused, match="reconciliation"):
        broker.revoke(lease)
    assert broker._loadMetadata(resource.resource_id).state == "revoked_or_expired"
    assert retained.tobytes() == b"\x00" * len(b"credential-goldstone")
    assert journal.load_resources(resource.transaction_id)[0].state is (
        CredentialResourceState.INJECTED
    )
    monkeypatch.setattr(coordinator_type, "commitRevoked", original_revoked)
    broker.revoke(lease)
    assert journal.load_resources(resource.transaction_id)[0].state is (
        CredentialResourceState.REVOKED_OR_EXPIRED
    )


def test_live_foreign_holder_blocks_terminal_truth_until_process_death(
    tmp_path: Path,
) -> None:
    mod = _credentials()
    resource = _registered_resource()
    journal = _journaled_resource(tmp_path / "attempt", resource)
    root = tmp_path / "credential-store"
    capability = object()
    broker = mod.CredentialBroker(
        metadata_root=root,
        secret_provider=lambda _provider: b"credential-goldstone",
        process_capability=capability,
        attempt_journal=journal,
        issuer_id=resource.issuer_id,
        clock=_clock,
    )
    authority = broker.issueAuthority(
        process_capability=capability,
        resource=resource,
        transaction_id=resource.transaction_id,
        provider=resource.provider,
        deadline=resource.expires_at,
    )
    lease = broker.issue(resource=resource, authority=authority)
    retained = lease.secretView()
    foreign = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        foreign_token = processStartToken(foreign.pid)
        assert foreign_token
        metadata = replace(
            broker._loadMetadata(resource.resource_id),
            holder_pid=foreign.pid,
            holder_start_token=foreign_token,
        )
        broker._persist(metadata)
        journal_before = {
            path.relative_to(journal.root).as_posix(): path.read_bytes()
            for path in journal.root.rglob("*.json")
        }
        current = journal.load_resources(resource.transaction_id)[0]
        destroyer = broker.channelDestroyer(
            process_capability=capability,
            resource=current,
        )

        channel = importlib.import_module("platform_core.runtime.credential_channel")
        with pytest.raises(
            channel.CredentialChannelEvidenceRefused,
            match="broker destruction lifecycle",
        ):
            destroyer.destroy(current)

        assert {
            path.relative_to(journal.root).as_posix(): path.read_bytes()
            for path in journal.root.rglob("*.json")
        } == journal_before
    finally:
        foreign.terminate()
        foreign.wait(timeout=10)

    receipt = destroyer.destroy(current)
    assert receipt.resource_id == resource.resource_id
    assert retained.tobytes() == b"\x00" * len(b"credential-goldstone")
    assert journal.load_resources(resource.transaction_id)[0].state is (
        CredentialResourceState.DESTROYED
    )


def test_broker_destroy_persists_receipt_and_fresh_restart_proves_absence(
    tmp_path: Path,
) -> None:
    mod = _credentials()
    process_capability = object()
    root = tmp_path / "credential-store"
    resource = _registered_resource()
    journal = _journaled_resource(tmp_path / "attempt", resource)
    broker = mod.CredentialBroker(
        metadata_root=root,
        secret_provider=lambda _provider: b"credential-goldstone",
        process_capability=process_capability,
        attempt_journal=journal,
        issuer_id=resource.issuer_id,
        clock=_clock,
    )
    authority = broker.issueAuthority(
        process_capability=process_capability,
        resource=resource,
        transaction_id=resource.transaction_id,
        provider=resource.provider,
        deadline=resource.expires_at,
    )
    lease = broker.issue(resource=resource, authority=authority)
    broker.markInjected(lease)
    broker.revoke(lease)
    revoked = journal.load_resources(resource.transaction_id)[0]
    destroyer = broker.channelDestroyer(
        process_capability=process_capability,
        resource=revoked,
    )
    receipt = destroyer.destroy(revoked)
    terminal_metadata = json.loads(
        _metadata_path(root, resource.resource_id).read_text(encoding="utf-8")
    )
    assert terminal_metadata["state"] == "destroyed"
    assert terminal_metadata["destruction_receipt_digest"] == receipt.receipt_digest
    assert terminal_metadata["destroyed_at"] == receipt.destroyed_at
    destroyed = journal.load_resources(resource.transaction_id)[0]

    restarted_capability = object()
    restarted = mod.CredentialBroker(
        metadata_root=root,
        secret_provider=lambda _provider: pytest.fail("restart must not derive a secret"),
        process_capability=restarted_capability,
        attempt_journal=journal,
        issuer_id=resource.issuer_id,
        clock=_clock,
    )
    verifier = restarted.freshAbsenceVerifier(
        process_capability=restarted_capability,
        resource=destroyed,
    )
    observation = verifier.verify(destroyed)

    assert observation.receipt_digest == receipt.receipt_digest
    assert observation.secret_channel_id == resource.secret_channel_id
    assert observation.toDict()["absent"] is True
    assert b"credential-goldstone" not in receipt.toBytes()
    assert runtimeResourceIsQuiescent(
        destroyed,
        credential_absence_verifier=verifier,
    ) is True

    terminal_metadata["state"] = "revoked_or_expired"
    _metadata_path(root, resource.resource_id).write_text(
        json.dumps(terminal_metadata, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    with pytest.raises(Exception, match="metadata|terminal|absence"):
        restarted.freshAbsenceVerifier(
            process_capability=restarted_capability,
            resource=destroyed,
        ).verify(destroyed)


def test_credential_absence_refuses_untyped_or_forged_authority(
    tmp_path: Path,
) -> None:
    resource = _registered_resource()
    destroyed = replace(
        resource,
        state=CredentialResourceState.DESTROYED,
        updated_at="2026-07-20T10:00:00+00:00",
        credential_destruction_receipt_digest="d" * 64,
        credential_destroyed_at="2026-07-20T10:00:00+00:00",
    )

    untyped_values: tuple[object, ...] = (True, {}, lambda _resource: True)
    for untyped in untyped_values:
        with pytest.raises(Exception, match="typed|sealed|verifier"):
            runtimeResourceIsQuiescent(
                destroyed,
                credential_absence_verifier=untyped,  # type: ignore[arg-type]
            )

    assert runtimeResourceIsQuiescent(destroyed) is False


def test_fresh_verifier_refuses_a_recreated_channel_after_receipt(
    tmp_path: Path,
) -> None:
    mod = _credentials()
    process_capability = object()
    resource = _registered_resource()
    root = tmp_path / "credential-store"
    journal = _journaled_resource(tmp_path / "attempt", resource)
    broker = mod.CredentialBroker(
        metadata_root=root,
        secret_provider=lambda _provider: b"credential-goldstone",
        process_capability=process_capability,
        attempt_journal=journal,
        issuer_id=resource.issuer_id,
        clock=_clock,
    )
    authority = broker.issueAuthority(
        process_capability=process_capability,
        resource=resource,
        transaction_id=resource.transaction_id,
        provider=resource.provider,
        deadline=resource.expires_at,
    )
    lease = broker.issue(resource=resource, authority=authority)
    broker.revoke(lease)
    broker.channelDestroyer(
        process_capability=process_capability,
        resource=journal.load_resources(resource.transaction_id)[0],
    ).destroy(
        replace(
            resource,
            state=CredentialResourceState.REVOKED_OR_EXPIRED,
            secret_fingerprint=lease.metadata.secret_fingerprint,
        )
    )
    destroyed = journal.load_resources(resource.transaction_id)[0]
    broker._channelPath(resource.secret_channel_id).write_bytes(b"recreated")
    verifier = broker.freshAbsenceVerifier(
        process_capability=process_capability,
        resource=destroyed,
    )

    with pytest.raises(Exception, match="present|absence"):
        verifier.verify(destroyed)


def test_destroy_replay_reuses_broker_terminal_receipt_after_journal_crash(
    tmp_path: Path,
) -> None:
    root = tmp_path / "credential-store"
    mod, resource, revoked, broker, process_capability, journal = _issue_and_revoke(
        root=root
    )
    first = broker.channelDestroyer(
        process_capability=process_capability,
        resource=revoked,
    ).destroy(revoked)

    def later() -> datetime:
        return _clock() + timedelta(minutes=5)
    restarted_capability = object()
    restarted = mod.CredentialBroker(
        metadata_root=root,
        secret_provider=lambda _provider: pytest.fail("replay must not derive a secret"),
        process_capability=restarted_capability,
        attempt_journal=journal,
        issuer_id=resource.issuer_id,
        clock=later,
    )
    destroyer = restarted.channelDestroyer(
        process_capability=restarted_capability,
        resource=journal.load_resources(resource.transaction_id)[0],
    )

    assert destroyer.destroy(revoked) == first
    assert destroyer.destroy(revoked) == first
    assert len(tuple((root / "destruction-receipts").glob("*.json"))) == 1
    assert len(tuple((root / "destruction-intents").glob("*.json"))) == 2


def test_destroy_replay_adopts_receipt_persisted_before_broker_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "credential-store"
    mod, resource, revoked, broker, process_capability, journal = _issue_and_revoke(
        root=root
    )

    broker_type = type(broker)

    def crash_before_metadata(*_args: object) -> None:
        raise RuntimeError("crash after receipt persistence")

    monkeypatch.setattr(broker_type, "_markDestroyed", crash_before_metadata)
    destroyer = broker.channelDestroyer(
        process_capability=process_capability,
        resource=revoked,
    )
    with pytest.raises(RuntimeError, match="after receipt persistence"):
        destroyer.destroy(revoked)
    monkeypatch.undo()

    channel = importlib.import_module("platform_core.runtime.credential_channel")
    intent_paths = tuple(
        (root / "destruction-intents").glob("*.terminal.json")
    )
    assert len(intent_paths) == 1
    intended = channel.CredentialChannelDestructionReceipt.fromBytes(
        intent_paths[0].read_bytes()
    )
    assert not broker._channelPath(resource.secret_channel_id).exists()
    assert json.loads(
        _metadata_path(root, resource.resource_id).read_text(encoding="utf-8")
    )["state"] == "revoked_or_expired"

    def later() -> datetime:
        return _clock() + timedelta(minutes=5)
    restarted_capability = object()
    restarted = mod.CredentialBroker(
        metadata_root=root,
        secret_provider=lambda _provider: pytest.fail("replay must not derive a secret"),
        process_capability=restarted_capability,
        attempt_journal=journal,
        issuer_id=resource.issuer_id,
        clock=later,
    )
    recovered = restarted.channelDestroyer(
        process_capability=restarted_capability,
        resource=journal.load_resources(resource.transaction_id)[0],
    ).destroy(revoked)

    assert recovered == intended
    assert len(tuple((root / "destruction-receipts").glob("*.json"))) == 1


def test_prepared_intent_never_claims_destruction_before_exact_delete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "credential-store"
    _mod, resource, revoked, broker, process_capability, _journal = _issue_and_revoke(
        root=root
    )
    destroyer = broker.channelDestroyer(
        process_capability=process_capability,
        resource=revoked,
    )

    def crash_before_delete(_self: object, _channel_id: str) -> None:
        raise RuntimeError("crash before exact delete")

    monkeypatch.setattr(type(destroyer), "_remove_channel", crash_before_delete)
    with pytest.raises(RuntimeError, match="before exact delete"):
        destroyer.destroy(revoked)

    assert broker._channelPath(resource.secret_channel_id).is_file()
    assert tuple((root / "destruction-receipts").glob("*.json")) == ()
    assert tuple((root / "destruction-intents").glob("*.terminal.json")) == ()
    prepared = tuple((root / "destruction-intents").glob("*.prepared.json"))
    assert len(prepared) == 1
    prepared_payload = json.loads(prepared[0].read_text(encoding="utf-8"))
    assert prepared_payload["schema"].endswith("destruction-intent/v1")
    assert "destroyed_at" not in prepared_payload
    assert "receipt_digest" not in prepared_payload


def test_terminal_receipt_timestamp_follows_exact_channel_absence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "credential-store"
    _mod, resource, revoked, broker, process_capability, _journal = _issue_and_revoke(
        root=root
    )
    observed_absence_at = _clock() + timedelta(minutes=2)

    def absence_clock() -> datetime:
        assert not broker._channelPath(resource.secret_channel_id).exists()
        return observed_absence_at

    broker._clock = absence_clock
    receipt = broker.channelDestroyer(
        process_capability=process_capability,
        resource=revoked,
    ).destroy(revoked)

    assert receipt.destroyed_at == observed_absence_at.isoformat()


def test_channel_rebind_between_delete_and_absence_refuses_before_terminal_truth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "credential-store"
    _mod, resource, revoked, broker, process_capability, journal = _issue_and_revoke(
        root=root
    )
    destroyer = broker.channelDestroyer(
        process_capability=process_capability,
        resource=revoked,
    )
    original_remove = type(destroyer)._remove_channel

    def remove_then_rebind(self: object, channel_id: str) -> None:
        original_remove(self, channel_id)
        channels = root / "channels"
        channels.rename(root / "channels-rebound")
        channels.mkdir()

    monkeypatch.setattr(type(destroyer), "_remove_channel", remove_then_rebind)

    with pytest.raises(Exception, match="identity changed|rebound|absence"):
        destroyer.destroy(revoked)

    assert tuple((root / "destruction-receipts").glob("*.json")) == ()
    assert tuple((root / "destruction-intents").glob("*.terminal.json")) == ()
    assert len(tuple((root / "destruction-intents").glob("*.prepared.json"))) == 1
    assert json.loads(
        _metadata_path(root, resource.resource_id).read_text(encoding="utf-8")
    )["state"] == "revoked_or_expired"

    monkeypatch.setattr(type(destroyer), "_remove_channel", original_remove)
    restarted_capability = object()
    restarted = _credentials().CredentialBroker(
        metadata_root=root,
        secret_provider=lambda _provider: pytest.fail(
            "rebind recovery must not derive a secret"
        ),
        process_capability=restarted_capability,
        attempt_journal=journal,
        issuer_id=resource.issuer_id,
        clock=lambda: _clock() + timedelta(minutes=3),
    )
    recovered = restarted.channelDestroyer(
        process_capability=restarted_capability,
        resource=journal.load_resources(resource.transaction_id)[0],
    ).destroy(revoked)

    metadata = json.loads(
        _metadata_path(root, resource.resource_id).read_text(encoding="utf-8")
    )
    assert metadata["state"] == "destroyed"
    assert metadata["destruction_receipt_digest"] == recovered.receipt_digest


def test_clock_rollback_cannot_seal_an_unjournalable_terminal_receipt(
    tmp_path: Path,
) -> None:
    root = tmp_path / "credential-store"
    _mod, resource, revoked, broker, process_capability, _journal = _issue_and_revoke(
        root=root
    )
    broker._clock = lambda: datetime(
        2026,
        7,
        20,
        9,
        15,
        tzinfo=timezone.utc,
    )

    with pytest.raises(Exception, match="predates|rollback|clock"):
        broker.channelDestroyer(
            process_capability=process_capability,
            resource=revoked,
        ).destroy(revoked)

    assert not broker._channelPath(resource.secret_channel_id).exists()
    assert tuple((root / "destruction-receipts").glob("*.json")) == ()
    assert tuple((root / "destruction-intents").glob("*.terminal.json")) == ()
    metadata = json.loads(
        _metadata_path(root, resource.resource_id).read_text(encoding="utf-8")
    )
    assert metadata["state"] == "revoked_or_expired"

    recovered_at = _clock() + timedelta(minutes=3)
    broker._clock = lambda: recovered_at
    receipt = broker.channelDestroyer(
        process_capability=process_capability,
        resource=revoked,
    ).destroy(revoked)

    assert receipt.destroyed_at == recovered_at.isoformat()


@pytest.mark.parametrize(
    "child_name",
    ["channels", "destruction-receipts", "destruction-intents"],
)
def test_fresh_verifier_refuses_rebound_protected_child_directory(
    tmp_path: Path,
    child_name: str,
) -> None:
    root = tmp_path / "credential-store"
    mod, resource, revoked, broker, process_capability, journal = _issue_and_revoke(
        root=root
    )
    receipt = broker.channelDestroyer(
        process_capability=process_capability,
        resource=revoked,
    ).destroy(revoked)
    destroyed = replace(
        revoked,
        state=CredentialResourceState.DESTROYED,
        updated_at=receipt.destroyed_at,
        credential_destruction_receipt_digest=receipt.receipt_digest,
        credential_destroyed_at=receipt.destroyed_at,
    )
    verifier = broker.freshAbsenceVerifier(
        process_capability=process_capability,
        resource=journal.load_resources(resource.transaction_id)[0],
    )
    original = root / child_name
    replacement_source = root / f"{child_name}-original"
    original.rename(replacement_source)
    original.mkdir()
    for item in replacement_source.iterdir():
        if item.is_file():
            (original / item.name).write_bytes(item.read_bytes())

    with pytest.raises(Exception, match="identity changed"):
        verifier.verify(destroyed)


def test_metadata_filename_is_content_addressed_not_a_raw_logical_id(
    tmp_path: Path,
) -> None:
    resource = replace(_registered_resource(), resource_id="credential:lease")
    root = tmp_path / "credential-store"
    _mod, _resource, _revoked, _broker, _capability, _journal = _issue_and_revoke(
        root=root,
        resource=resource,
    )

    expected = hashlib.sha256(resource.resource_id.encode("utf-8")).hexdigest()
    assert (root / f"{expected}.json").is_file()
    assert not (root / f"{resource.resource_id}.json").exists()
