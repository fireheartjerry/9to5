"""Crash-replay and monotonicity tests for the transactional attempt journal."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import threading
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

import pytest
import platform_core.core.fsio as fsio
import platform_core.runtime.attempt_journal as attempt_journal_module
import platform_core.runtime.credential_channel as credential_channel_module

from platform_core.runtime.attempt_journal import (
    AttemptCollision,
    AttemptJournal,
    AttemptPersistenceAuthorityRefused,
    AttemptPhase,
    AttemptRecord,
    IncompleteResourceSet,
    InvalidAttemptTransition,
    JournalCorruption,
    MissingResourceSet,
    validateRuntimeResourceManifest,
)
from platform_core.runtime.candidate import (
    CredentialResourceState,
    ProcessResourceState,
    ResourceRole,
    RuntimeResourceLease,
    processStartToken,
)
from platform_core.runtime.controller_state import (
    issueDiagnosticControllerStateAuthority,
)
from platform_core.execution.credential_broker import CredentialBroker, CredentialLease
from platform_core.runtime.credential_channel import (
    CredentialChannelAbsenceVerifier,
    CredentialChannelDestructionReceipt,
)
from platform_core.runtime.receipts import (
    ArtifactCleanupResult,
    CleanupArtifact,
    CleanupCoordinator,
    CleanupDisposition,
    CleanupReceipt,
    FinalizationReceipt,
    ReceiptStore,
)
from platform_core.runtime.recovery import (
    AttemptPersistenceRequest,
    PromotionPersistencePending,
    RecoveryRefused,
    persistAttemptTransaction,
)
from state import task_io
from state.task import TaskState

SHA_A = "a" * 40
SHA_B = "b" * 40
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64


class _ObservedJournalRoot:
    def __init__(self, value: Path, observations: list[str]) -> None:
        self._value = value
        self._observations = observations

    def __fspath__(self) -> str:
        self._observations.append("fspath")
        return str(self._value)


def _run_installed_journal_case(
    tmp_path: Path,
    body: str,
) -> subprocess.CompletedProcess[str]:
    root = Path(__file__).resolve().parents[2]
    case_root = tmp_path / "installed-journal-case"
    code = f"""
import runpy
import sys
from pathlib import Path

repository_root = Path({str(root)!r})
bootstrap_fixture = runpy.run_path(
    str(repository_root / 'tests' / 'control' / 'test_installed_bootstrap_authority.py')
)
scope, _spawn_result, outer = bootstrap_fixture['_consume_outer'](
    Path({str(case_root)!r})
)
from platform_core.runtime import attempt_journal as journal_mod
from platform_core.runtime import bootstrap_authority as bootstrap
from platform_core.runtime import controller_state as state
bundle = bootstrap.deriveInstalledBootstrapAuthorities(outer_capabilities=outer)

def installed_record(runtime, *, transaction_id='tx-001'):
    case_root = Path(scope.controller_state_root).parent
    return journal_mod.AttemptRecord(
        transaction_id=transaction_id,
        task_id='task-001',
        subtask_id='subtask-001',
        attempt_id='attempt-001',
        repository_id=runtime.authority.repository_id,
        canonical_root=str(case_root / 'canonical'),
        canonical_ref='refs/heads/main',
        base_revision='a' * 40,
        candidate_kind='clone',
        clone_lease_id='clone-001',
        clone_path=str(case_root / 'controller' / 'checkouts' / transaction_id),
        ownership_nonce='b' * 64,
        spec_digest='c' * 64,
        policy_digest='d' * 64,
        canonical_metadata_attestation_digest='e' * 64,
        object_format='sha1',
        oid_length=40,
        ref_backend='files',
        candidate_branch=f'refs/heads/9to5/candidates/{{transaction_id}}',
        checkpoint_message_digest='f' * 64,
        proposal_message_digest='1' * 64,
        commit_timestamp_seed='2026-07-16T12:00:00+00:00',
        runner_kind='local',
        candidate_git_dir=str(
            case_root / 'controller' / 'checkouts' / transaction_id / '.git'
        ),
        canonical_git_common_dir=str(case_root / 'canonical' / '.git'),
        source_manifest_digest='2' * 64,
        source_object_closure_digest='3' * 64,
        source_snapshot_digest='4' * 64,
        source_parser_receipt_id='5' * 64,
        source_payload_root=str(case_root / 'controller' / 'source-payloads'),
        created_at='2026-07-16T12:00:00+00:00',
        updated_at='2026-07-16T12:00:00+00:00',
    )
""" + body
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_installed_persistence_issuer_rejects_caller_generation_inputs_without_observation(
    tmp_path: Path,
) -> None:
    result = _run_installed_journal_case(
        tmp_path,
        """
runtime = state.installControllerRuntimeState(bootstrap_authorities=bundle)
journal_root = Path(scope.controller_state_root) / 'attempt-journal'
journal_root.mkdir(parents=True)
sentinel = journal_root / 'sentinel'
sentinel.write_text('unchanged', encoding='utf-8')
observations = []
probe_calls = []
controller_authority = runtime.authority
watchdog_generation = bundle.run_admission.watchdog_generation
process_capability = state._controllerAuthorityScope(
    controller_authority
).process_capability
persistence_authorities_before = dict(
    journal_mod._PERSISTENCE_ISSUER_REGISTRY
)
persistence_bindings_before = dict(
    journal_mod._PERSISTENCE_ISSUER_BINDINGS
)

class ObservedRoot:
    def __fspath__(self):
        observations.append('journal-root')
        return str(journal_root)

def exploding_observation(name):
    def explode(*args, **kwargs):
        observations.append(name)
        raise RuntimeError(f'{name} must not run')
    return explode

def exploding_controller_probe():
    probe_calls.append('controller')
    raise RuntimeError('controller probe must not run')

def exploding_watchdog_probe():
    probe_calls.append('watchdog')
    raise RuntimeError('watchdog probe must not run')

journal_mod.validateControllerStateAuthority = exploding_observation(
    'controller-validation'
)
journal_mod.validateControllerStateProcessCapability = exploding_observation(
    'process-capability-validation'
)
journal_mod.isDiagnosticControllerStateAuthority = exploding_observation(
    'controller-classification'
)
state.validateControllerStateAuthority = exploding_observation(
    'controller-module-validation'
)
state.validateControllerStateProcessCapability = exploding_observation(
    'controller-module-process-capability'
)
state.isDiagnosticControllerStateAuthority = exploding_observation(
    'controller-module-classification'
)
state._controllerAuthorityScope = exploding_observation(
    'controller-authority-registry'
)
state._controllerRuntimeConsumerPermit = exploding_observation(
    'controller-runtime-permit'
)
bootstrap.validateInstalledBootstrapAuthorities = exploding_observation(
    'installed-bundle-validation'
)
bootstrap._installedBootstrapRuntimePermit = exploding_observation(
    'watchdog-runtime-permit'
)
journal_mod._installedPersistenceAccess = exploding_observation(
    'installed-persistence-access'
)
journal_mod._root_identity = exploding_observation('storage-root-identity')
try:
    journal_mod.AttemptPersistenceAuthorityIssuer(
        journal_root=ObservedRoot(),
        controller_state_authority=controller_authority,
        controller_generation_probe=exploding_controller_probe,
        watchdog_generation=watchdog_generation,
        watchdog_generation_probe=exploding_watchdog_probe,
        process_capability=process_capability,
        bootstrap_authorities=bundle,
    )
except journal_mod.AttemptPersistenceAuthorityRefused as exc:
    assert str(exc) == (
        'installed persistence authority rejects caller generation inputs'
    )
else:
    raise AssertionError('installed caller generation inputs were accepted')
assert probe_calls == []
assert observations == []
assert journal_mod._PERSISTENCE_ISSUER_REGISTRY == persistence_authorities_before
assert journal_mod._PERSISTENCE_ISSUER_BINDINGS == persistence_bindings_before
assert tuple(path.name for path in journal_root.iterdir()) == ('sentinel',)
assert sentinel.read_text(encoding='utf-8') == 'unchanged'
""",
    )

    assert result.returncode == 0, result.stderr


def test_installed_persistence_issuer_derives_exact_runtime_generations(
    tmp_path: Path,
) -> None:
    result = _run_installed_journal_case(
        tmp_path,
        """
from datetime import datetime, timezone

runtime = state.installControllerRuntimeState(bootstrap_authorities=bundle)
journal_root = Path(scope.controller_state_root) / 'attempt-journal'
journal_root.mkdir(parents=True)
journal = journal_mod.AttemptJournal(
    journal_root,
    diagnostic=False,
    bootstrap_authorities=bundle,
)
process_capability = state._controllerAuthorityScope(
    runtime.authority
).process_capability
issuer = journal_mod.AttemptPersistenceAuthorityIssuer(
    journal_root=journal_root,
    controller_state_authority=runtime.authority,
    process_capability=process_capability,
    bootstrap_authorities=bundle,
)
authority = issuer.issueAuthority(
    transaction_id='tx-001',
    task_id='task-001',
    subtask_id='subtask-001',
    process_capability=process_capability,
    deadline=datetime(2098, 1, 1, tzinfo=timezone.utc),
)
issued_scope = issuer._issued[authority.authority_id].scope
assert issued_scope.controller_generation == runtime.authority.controller_generation
assert (
    issued_scope.controller_generation
    == bundle.run_admission.controller_generation
)
assert issued_scope.watchdog_generation == bundle.run_admission.watchdog_generation

bootstrap._revokeInstalledBootstrapAuthorities(bundle, generation=1)
for operation in (
    lambda: issuer.issueAuthority(
        transaction_id='tx-002',
        task_id='task-001',
        subtask_id='subtask-001',
        process_capability=process_capability,
        deadline=datetime(2098, 1, 1, tzinfo=timezone.utc),
    ),
    lambda: journal.validate_persistence_authority(
        authority,
        transaction_id='tx-001',
    ),
):
    try:
        operation()
    except journal_mod.AttemptPersistenceAuthorityRefused as exc:
        assert 'exact live installed runtime bundle' in str(exc)
    else:
        raise AssertionError('revoked installed persistence power remained live')
""",
    )

    assert result.returncode == 0, result.stderr


def test_installed_acknowledgement_operation_first_retains_runtime_epoch_through_append(
    tmp_path: Path,
) -> None:
    result = _run_installed_journal_case(
        tmp_path,
        """
import threading
from datetime import datetime, timezone

runtime = state.installControllerRuntimeState(bootstrap_authorities=bundle)
journal_root = Path(scope.controller_state_root) / 'attempt-journal'
journal_root.mkdir(parents=True)
journal = journal_mod.AttemptJournal(
    journal_root,
    diagnostic=False,
    bootstrap_authorities=bundle,
)
record = installed_record(runtime)
promoted = journal.transition(
    journal.create(record).transaction_id,
    journal_mod.AttemptPhase.REJECTED,
    error='terminal test outcome',
)
process_capability = state._controllerAuthorityScope(
    runtime.authority
).process_capability
issuer = journal_mod.AttemptPersistenceAuthorityIssuer(
    journal_root=journal_root,
    controller_state_authority=runtime.authority,
    process_capability=process_capability,
    bootstrap_authorities=bundle,
)
authority = issuer.issueAuthority(
    transaction_id=promoted.transaction_id,
    task_id=promoted.task_id,
    subtask_id=promoted.subtask_id,
    process_capability=process_capability,
    deadline=datetime(2098, 1, 1, tzinfo=timezone.utc),
)
append_started = threading.Event()
release_append = threading.Event()
append_finished = threading.Event()
revocation_started = threading.Event()
revocation_finished = threading.Event()
original_append = journal._append_event
acknowledged = []
operation_errors = []

def blocking_append(next_record):
    if next_record.task_state_acknowledged:
        append_started.set()
        assert release_append.wait(5)
    result = original_append(next_record)
    if next_record.task_state_acknowledged:
        append_finished.set()
    return result

journal._append_event = blocking_append

def acknowledge():
    try:
        acknowledged.append(
            journal.mark_task_state_acknowledged(
                promoted.transaction_id,
                authority=authority,
            )
        )
    except BaseException as exc:
        operation_errors.append(exc)

def revoke():
    revocation_started.set()
    bootstrap._revokeInstalledBootstrapAuthorities(bundle, generation=1)
    revocation_finished.set()

operation_thread = threading.Thread(target=acknowledge)
operation_thread.start()
assert append_started.wait(5)
revocation_thread = threading.Thread(target=revoke)
revocation_thread.start()
assert revocation_started.wait(5)
assert not revocation_finished.wait(0.2)
release_append.set()
operation_thread.join(5)
revocation_thread.join(5)
assert not operation_thread.is_alive()
assert not revocation_thread.is_alive()
assert operation_errors == []
assert len(acknowledged) == 1
assert acknowledged[0].task_state_acknowledged is True
assert acknowledged[0].terminal_state_persisted is False
assert append_finished.is_set()
assert revocation_finished.is_set()
""",
    )

    assert result.returncode == 0, result.stderr


def test_installed_acknowledgement_revocation_first_refuses_before_lock_replay_or_append(
    tmp_path: Path,
) -> None:
    result = _run_installed_journal_case(
        tmp_path,
        """
from contextlib import contextmanager
from datetime import datetime, timezone

runtime = state.installControllerRuntimeState(bootstrap_authorities=bundle)
journal_root = Path(scope.controller_state_root) / 'attempt-journal'
journal_root.mkdir(parents=True)
journal = journal_mod.AttemptJournal(
    journal_root,
    diagnostic=False,
    bootstrap_authorities=bundle,
)
record = installed_record(runtime)
promoted = journal.transition(
    journal.create(record).transaction_id,
    journal_mod.AttemptPhase.REJECTED,
    error='terminal test outcome',
)
process_capability = state._controllerAuthorityScope(
    runtime.authority
).process_capability
issuer = journal_mod.AttemptPersistenceAuthorityIssuer(
    journal_root=journal_root,
    controller_state_authority=runtime.authority,
    process_capability=process_capability,
    bootstrap_authorities=bundle,
)
authority = issuer.issueAuthority(
    transaction_id=promoted.transaction_id,
    task_id=promoted.task_id,
    subtask_id=promoted.subtask_id,
    process_capability=process_capability,
    deadline=datetime(2098, 1, 1, tzinfo=timezone.utc),
)
bootstrap._revokeInstalledBootstrapAuthorities(bundle, generation=1)
observations = []
original_load = journal._load_chain

@contextmanager
def observed_file_lock(*_args, **_kwargs):
    observations.append('file-lock')
    yield

journal_mod.fileLock = observed_file_lock
journal._load_chain = lambda _transaction_id: observations.append('replay')
journal._append_event = lambda _record: observations.append('append')
try:
    journal.mark_task_state_acknowledged(
        promoted.transaction_id,
        authority=authority,
    )
except journal_mod.AttemptPersistenceAuthorityRefused as exc:
    assert 'exact live installed runtime bundle' in str(exc)
else:
    raise AssertionError('revoked acknowledgement was accepted')
assert observations == []
durable = original_load(promoted.transaction_id).record
assert durable.task_state_acknowledged is False
assert durable.terminal_state_persisted is False
""",
    )

    assert result.returncode == 0, result.stderr


def _record(tmp_path: Path, *, transaction_id: str = "tx-001") -> AttemptRecord:
    return AttemptRecord(
        transaction_id=transaction_id,
        task_id="task-001",
        subtask_id="subtask-001",
        attempt_id="attempt-001",
        repository_id=DIGEST_A,
        canonical_root=str(tmp_path / "canonical"),
        canonical_ref="refs/heads/main",
        base_revision=SHA_A,
        candidate_kind="clone",
        clone_lease_id="clone-001",
        clone_path=str(tmp_path / "controller" / "checkouts" / transaction_id),
        ownership_nonce=DIGEST_B,
        spec_digest=DIGEST_C,
        policy_digest="d" * 64,
        canonical_metadata_attestation_digest="e" * 64,
        object_format="sha1",
        oid_length=40,
        ref_backend="files",
        candidate_branch=f"refs/heads/9to5/candidates/{transaction_id}",
        checkpoint_message_digest="f" * 64,
        proposal_message_digest="1" * 64,
        commit_timestamp_seed="2026-07-16T12:00:00+00:00",
        runner_kind="local",
        candidate_git_dir=str(
            tmp_path / "controller" / "checkouts" / transaction_id / ".git"
        ),
        canonical_git_common_dir=str(tmp_path / "canonical" / ".git"),
        source_manifest_digest="2" * 64,
        source_object_closure_digest="3" * 64,
        source_snapshot_digest="4" * 64,
        source_parser_receipt_id="5" * 64,
        source_payload_root=str(tmp_path / "controller" / "source-payloads"),
        created_at="2026-07-16T12:00:00+00:00",
        updated_at="2026-07-16T12:00:00+00:00",
    )


def test_attempt_journal_root_is_read_only(tmp_path: Path) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    original_root = journal.root
    observations: list[str] = []

    with pytest.raises(AttributeError):
        journal.root = _ObservedJournalRoot(  # type: ignore[misc]
            tmp_path / "retargeted-journal",
            observations,
        )

    assert journal.root == original_root
    assert observations == []
    assert journal.load(record.transaction_id) == record


def test_attempt_journal_mode_and_bundle_cannot_be_retargeted(
    tmp_path: Path,
) -> None:
    result = _run_installed_journal_case(
        tmp_path,
        """
state.installControllerRuntimeState(bootstrap_authorities=bundle)
journal_root = Path(scope.controller_state_root) / 'attempt-journal'
journal_root.mkdir(parents=True)
journal = journal_mod.AttemptJournal(
    journal_root,
    diagnostic=False,
    bootstrap_authorities=bundle,
)
for attribute, replacement in (
    ('_diagnostic', True),
    ('_bootstrap_authorities', object()),
):
    try:
        setattr(journal, attribute, replacement)
    except AttributeError:
        pass
    else:
        raise AssertionError(f'{attribute} was retargeted')
assert journal._diagnostic is False
assert journal._bootstrap_authorities is bundle
assert journal.event_directory('tx-001').is_relative_to(journal_root)
""",
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("tamper", ["binding_field", "binding_replacement"])
def test_attempt_journal_refuses_object_setattr_binding_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    observations: list[str] = []
    replacement_root = _ObservedJournalRoot(
        tmp_path / "retargeted-journal",
        observations,
    )
    if tamper == "binding_field":
        object.__setattr__(journal._binding, "root", replacement_root)
    else:
        object.__setattr__(
            journal,
            "_AttemptJournal__binding",
            replace(journal._binding, root=replacement_root),
        )
    storage_observations: list[str] = []
    monkeypatch.setattr(
        journal,
        "_load_chain",
        lambda _transaction_id: storage_observations.append("load"),
    )

    with pytest.raises(
        AttemptPersistenceAuthorityRefused,
        match="journal binding is invalid",
    ):
        journal.load(record.transaction_id)

    assert observations == []
    assert storage_observations == []


def _registered_process_resource(record: AttemptRecord) -> RuntimeResourceLease:
    return RuntimeResourceLease(
        resource_id="driver-fence-001",
        run_id="run-001",
        transaction_id=record.transaction_id,
        controller_scope_id="controller-001",
        role=ResourceRole.MODEL_DRIVER,
        backend="local",
        ownership_nonce=record.ownership_nonce,
        state=ProcessResourceState.REGISTERED,
        cleanup_locator_digest="2" * 64,
        pid=0,
        process_group_id=0,
        container_id="",
        image_digest="",
        entrypoint_digest="3" * 64,
        mount_digest="4" * 64,
        environment_digest="5" * 64,
        security_profile_digest="6" * 64,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _registered_credential_resource(record: AttemptRecord) -> RuntimeResourceLease:
    return replace(
        _registered_process_resource(record),
        resource_id="credential-001",
        role=ResourceRole.CREDENTIAL_LEASE,
        backend="credential-broker",
        state=CredentialResourceState.REGISTERED,
        image_digest="",
        entrypoint_digest="",
        mount_digest="",
        environment_digest="",
        provider="claude",
        auth_mode="subscription",
        secret_channel_id="secret-channel-001",
        secret_fingerprint="",
        expires_at="2026-07-16T12:05:00+00:00",
        issuer_id="credential-broker-001",
        revocation_generation=1,
    )


def _prepare_credential_broker(
    root: Path,
    resource: RuntimeResourceLease,
    *,
    journal: AttemptJournal,
    materialize: bool,
) -> tuple[CredentialBroker, object, str, list[datetime], CredentialLease | None]:
    process_capability = object()
    clock = [datetime(2026, 7, 16, 12, 1, tzinfo=timezone.utc)]

    def secret_provider(_provider: str) -> bytes:
        if not materialize:
            raise RuntimeError("injected crash before credential materialization")
        return b"credential-goldstone"

    broker = CredentialBroker(
        metadata_root=root,
        secret_provider=secret_provider,
        process_capability=process_capability,
        attempt_journal=journal,
        issuer_id=resource.issuer_id,
        clock=lambda: clock[0],
    )
    if materialize:
        authority = broker.issueAuthority(
            process_capability=process_capability,
            resource=resource,
            transaction_id=resource.transaction_id,
            provider=resource.provider,
            deadline=resource.expires_at,
        )
        lease = broker.issue(resource=resource, authority=authority)
        fingerprint = lease.metadata.secret_fingerprint
    else:
        lease = None
        fingerprint = ""
    return broker, process_capability, fingerprint, clock, lease


def _destroy_credential_with_sealed_evidence(
    broker: CredentialBroker,
    process_capability: object,
    clock: list[datetime],
    resource: RuntimeResourceLease,
) -> tuple[CredentialChannelDestructionReceipt, CredentialChannelAbsenceVerifier]:
    clock[0] = datetime(2099, 1, 1, tzinfo=timezone.utc)
    receipt = broker.channelDestroyer(
        process_capability=process_capability,
        resource=resource,
    ).destroy(resource)
    current = broker._attempt_journal.load_resources(resource.transaction_id)[0]
    verifier = broker.freshAbsenceVerifier(
        process_capability=process_capability,
        resource=current,
    )
    return receipt, verifier


def _local_runtime_closure(
    record: AttemptRecord,
) -> tuple[RuntimeResourceLease, ...]:
    watchdog = replace(
        _registered_process_resource(record),
        resource_id="watchdog-001",
        role=ResourceRole.AUTHORITY_WATCHDOG,
    )
    driver = replace(
        _registered_process_resource(record),
        depends_on=("authority_watchdog:watchdog-001",),
    )
    parser = replace(
        _registered_process_resource(record),
        resource_id="parser-001",
        role=ResourceRole.CANDIDATE_PARSER,
        backend="docker",
        image_digest="7" * 64,
        depends_on=(
            "authority_watchdog:watchdog-001",
            "model_driver:driver-fence-001",
        ),
    )
    verifier = replace(
        _registered_process_resource(record),
        resource_id="verifier-001",
        role=ResourceRole.VERIFIER,
        backend="docker",
        image_digest="8" * 64,
        depends_on=(
            "authority_watchdog:watchdog-001",
            "candidate_parser:parser-001",
        ),
    )
    return watchdog, driver, parser, verifier


def _docker_runtime_closure(
    record: AttemptRecord,
) -> tuple[RuntimeResourceLease, ...]:
    watchdog = replace(
        _registered_process_resource(record),
        resource_id="watchdog-001",
        role=ResourceRole.AUTHORITY_WATCHDOG,
        backend="docker",
        image_digest="7" * 64,
    )
    driver = replace(
        _registered_process_resource(record),
        backend="docker",
        image_digest="8" * 64,
        depends_on=("authority_watchdog:watchdog-001",),
    )
    broker = replace(
        _registered_process_resource(record),
        resource_id="broker-001",
        role=ResourceRole.BROKER,
        backend="docker",
        image_digest="9" * 64,
        depends_on=(
            "authority_watchdog:watchdog-001",
            "model_driver:driver-fence-001",
        ),
    )
    sandbox = replace(
        _registered_process_resource(record),
        resource_id="sandbox-001",
        role=ResourceRole.COMMAND_SANDBOX,
        backend="docker",
        image_digest="a" * 64,
        depends_on=(
            "authority_watchdog:watchdog-001",
            "broker:broker-001",
        ),
    )
    parser = replace(
        _registered_process_resource(record),
        resource_id="parser-001",
        role=ResourceRole.CANDIDATE_PARSER,
        backend="docker",
        image_digest="b" * 64,
        depends_on=(
            "authority_watchdog:watchdog-001",
            "command_sandbox:sandbox-001",
        ),
    )
    verifier = replace(
        _registered_process_resource(record),
        resource_id="verifier-001",
        role=ResourceRole.VERIFIER,
        backend="docker",
        image_digest="c" * 64,
        depends_on=(
            "authority_watchdog:watchdog-001",
            "candidate_parser:parser-001",
        ),
    )
    credential = _registered_credential_resource(record)
    return credential, watchdog, driver, broker, sandbox, parser, verifier


def _with_runtime_manifest(
    record: AttemptRecord,
    resources: tuple[RuntimeResourceLease, ...],
) -> AttemptRecord:
    entries = [
        {
            "backend": resource.backend,
            "depends_on": list(resource.depends_on),
            "resource_identity": f"{resource.role.value}:{resource.resource_id}",
        }
        for resource in sorted(
            resources,
            key=lambda item: f"{item.role.value}:{item.resource_id}",
        )
    ]
    raw = json.dumps(
        {
            "resources": entries,
            "runner_kind": record.runner_kind,
            "schema": "galaxy.runtime-resource-manifest/v1",
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return replace(
        record,
        runtime_resource_manifest_json=raw,
        runtime_resource_manifest_digest=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    )


def _prepare_pending_resource_intent(
    journal: AttemptJournal,
    record: AttemptRecord,
    resources: tuple[RuntimeResourceLease, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[tuple[RuntimeResourceLease, ...], bytes, Path]:
    expected = tuple(
        sorted(resources, key=lambda item: f"{item.role.value}:{item.resource_id}")
    )

    def crash_before_native_publication(*_args, **_kwargs):
        raise RuntimeError("intent native publication crash")

    with monkeypatch.context() as patch:
        patch.setattr(
            journal,
            "_reconcile_resource_publication",
            crash_before_native_publication,
        )
        with pytest.raises(RuntimeError, match="native publication crash"):
            journal.register_resources(record.transaction_id, resources)
    raw = journal._resource_set_intent_bytes(record.transaction_id, expected)
    event_dir = (
        journal.event_directory(record.transaction_id).parent
        / "resources"
        / "closure"
        / "events"
    )
    return expected, raw, event_dir


@pytest.mark.parametrize(
    "operation_name",
    [
        "create",
        "load",
        "load_resources",
        "register_resources",
        "transition_resource",
        "transition",
        "validate_persistence_authority",
        "set_recovery_axes",
        "mark_task_state_acknowledged",
    ],
)
def test_public_journal_operation_enters_one_outer_persistence_fence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation_name: str,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = _record(tmp_path)
    resource = _registered_process_resource(record)
    promoted_operations = {
        "validate_persistence_authority",
        "set_recovery_axes",
        "mark_task_state_acknowledged",
    }
    running_resources: tuple[RuntimeResourceLease, ...] = ()
    if operation_name == "transition" or operation_name in promoted_operations:
        running_resources = _local_runtime_closure(record)
        record = _with_runtime_manifest(record, running_resources)
    authority = None
    if operation_name != "create":
        journal.create(record)
    if operation_name in {"load_resources", "transition_resource"}:
        journal.register_resources(record.transaction_id, (resource,))
    elif operation_name == "transition":
        journal.register_resources(record.transaction_id, running_resources)
    if operation_name in promoted_operations:
        record = _through_promoted(journal, record)
        authority = _persistence_authority(journal, record)

    original_access = attempt_journal_module._diagnosticPersistenceAccess
    entries = 0
    depth = 0
    max_depth = 0

    @contextmanager
    def observed_access(label: str):
        nonlocal entries, depth, max_depth
        entries += 1
        depth += 1
        max_depth = max(max_depth, depth)
        try:
            with original_access(label):
                yield
        finally:
            depth -= 1

    monkeypatch.setattr(
        attempt_journal_module,
        "_diagnosticPersistenceAccess",
        observed_access,
    )
    if operation_name == "create":
        observed = journal.create(record)
        assert observed == record
    elif operation_name == "load":
        assert journal.load(record.transaction_id) == record
    elif operation_name == "load_resources":
        assert journal.load_resources(record.transaction_id) == (resource,)
    elif operation_name == "register_resources":
        assert journal.register_resources(record.transaction_id, (resource,)) == (
            resource,
        )
    elif operation_name == "transition_resource":
        process_token = processStartToken(os.getpid())
        assert process_token is not None
        observed = journal.transition_resource(
            record.transaction_id,
            resource.resource_id,
            ProcessResourceState.CREATED,
            pid=os.getpid(),
            process_group_id=os.getpid(),
            process_start_token=process_token,
        )
        assert observed.state is ProcessResourceState.CREATED
    elif operation_name == "transition":
        observed = journal.transition(
            record.transaction_id,
            AttemptPhase.RUNNING,
            resource_lease_ids=tuple(
                f"{item.role.value}:{item.resource_id}"
                for item in sorted(
                    running_resources,
                    key=lambda item: f"{item.role.value}:{item.resource_id}",
                )
            ),
        )
        assert observed.phase is AttemptPhase.RUNNING
    elif operation_name == "validate_persistence_authority":
        observed = journal.validate_persistence_authority(
            authority,
            transaction_id=record.transaction_id,
        )
        assert observed == record
    elif operation_name == "set_recovery_axes":
        observed = journal.set_recovery_axes(
            record.transaction_id,
            task_state_acknowledged=True,
            authority=authority,
        )
        assert observed.task_state_acknowledged is True
    else:
        observed = journal.mark_task_state_acknowledged(
            record.transaction_id,
            authority=authority,
        )
        assert observed.task_state_acknowledged is True

    assert entries == 1
    assert max_depth == 1


@pytest.mark.parametrize(
    "operation_name",
    [
        "create",
        "register_resources",
        "transition_resource",
        "transition",
        "validate_persistence_authority",
        "set_recovery_axes",
        "mark_task_state_acknowledged",
    ],
)
def test_journal_never_acquires_persistence_access_below_transaction_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation_name: str,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = _record(tmp_path)
    resource = _registered_process_resource(record)
    promoted_operations = {
        "validate_persistence_authority",
        "set_recovery_axes",
        "mark_task_state_acknowledged",
    }
    running_resources: tuple[RuntimeResourceLease, ...] = ()
    if operation_name == "transition" or operation_name in promoted_operations:
        running_resources = _local_runtime_closure(record)
        record = _with_runtime_manifest(record, running_resources)
    authority = None
    if operation_name != "create":
        journal.create(record)
    if operation_name == "transition_resource":
        journal.register_resources(record.transaction_id, (resource,))
    elif operation_name == "transition":
        journal.register_resources(record.transaction_id, running_resources)
    if operation_name in promoted_operations:
        record = _through_promoted(journal, record)
        authority = _persistence_authority(journal, record)

    original_access = attempt_journal_module._diagnosticPersistenceAccess
    original_file_lock = attempt_journal_module.fileLock
    persistence_depth = 0
    transaction_lock_depth = 0
    access_entries_below_lock = 0
    persistence_depth_at_lock_entry: list[int] = []

    @contextmanager
    def observed_access(label: str):
        nonlocal persistence_depth, access_entries_below_lock
        if transaction_lock_depth:
            access_entries_below_lock += 1
        persistence_depth += 1
        try:
            with original_access(label):
                yield
        finally:
            persistence_depth -= 1

    @contextmanager
    def observed_file_lock(path: Path, **kwargs):
        nonlocal transaction_lock_depth
        persistence_depth_at_lock_entry.append(persistence_depth)
        with original_file_lock(path, **kwargs):
            transaction_lock_depth += 1
            try:
                yield
            finally:
                transaction_lock_depth -= 1

    monkeypatch.setattr(
        attempt_journal_module,
        "_diagnosticPersistenceAccess",
        observed_access,
    )
    monkeypatch.setattr(attempt_journal_module, "fileLock", observed_file_lock)
    if operation_name == "create":
        journal.create(record)
    elif operation_name == "register_resources":
        journal.register_resources(record.transaction_id, (resource,))
    elif operation_name == "transition_resource":
        process_token = processStartToken(os.getpid())
        assert process_token is not None
        journal.transition_resource(
            record.transaction_id,
            resource.resource_id,
            ProcessResourceState.CREATED,
            pid=os.getpid(),
            process_group_id=os.getpid(),
            process_start_token=process_token,
        )
    elif operation_name == "transition":
        journal.transition(
            record.transaction_id,
            AttemptPhase.RUNNING,
            resource_lease_ids=tuple(
                f"{item.role.value}:{item.resource_id}"
                for item in sorted(
                    running_resources,
                    key=lambda item: f"{item.role.value}:{item.resource_id}",
                )
            ),
        )
    elif operation_name == "validate_persistence_authority":
        journal.validate_persistence_authority(
            authority,
            transaction_id=record.transaction_id,
        )
    elif operation_name == "set_recovery_axes":
        journal.set_recovery_axes(
            record.transaction_id,
            task_state_acknowledged=True,
            authority=authority,
        )
    else:
        journal.mark_task_state_acknowledged(
            record.transaction_id,
            authority=authority,
        )

    assert persistence_depth_at_lock_entry
    assert all(depth >= 1 for depth in persistence_depth_at_lock_entry)
    assert access_entries_below_lock == 0


@pytest.mark.parametrize(
    "operation_name",
    ["validate_persistence_authority", "set_recovery_axes"],
)
def test_invalid_persistence_authority_refuses_before_lock_or_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation_name: str,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    promoted = _through_promoted(journal, _record(tmp_path))
    authority = _persistence_authority(journal, promoted)
    other_journal = AttemptJournal(tmp_path / "other-controller" / "journals")
    other_journal.root.mkdir(parents=True)
    observations: list[str] = []
    original_root_identity = attempt_journal_module._root_identity

    def observed_root_identity(value):
        observations.append("root-identity")
        return original_root_identity(value)

    @contextmanager
    def observed_file_lock(*_args, **_kwargs):
        observations.append("file-lock")
        yield

    monkeypatch.setattr(
        attempt_journal_module,
        "_root_identity",
        observed_root_identity,
    )
    monkeypatch.setattr(
        attempt_journal_module,
        "fileLock",
        observed_file_lock,
    )
    monkeypatch.setattr(
        other_journal,
        "_load_chain",
        lambda _transaction_id: observations.append("storage-replay"),
    )

    with pytest.raises(
        AttemptPersistenceAuthorityRefused,
        match="journal root differs",
    ):
        if operation_name == "validate_persistence_authority":
            other_journal.validate_persistence_authority(
                authority,
                transaction_id=promoted.transaction_id,
            )
        else:
            other_journal.set_recovery_axes(
                promoted.transaction_id,
                task_state_acknowledged=True,
                authority=authority,
            )

    assert observations == []


def _through_staging(journal: AttemptJournal, record: AttemptRecord) -> AttemptRecord:
    resources = _local_runtime_closure(record)
    if not record.runtime_resource_manifest_json:
        record = _with_runtime_manifest(record, resources)
    journal.create(record)
    journal.register_resources(record.transaction_id, resources)
    journal.transition(
        record.transaction_id,
        AttemptPhase.RUNNING,
        resource_lease_ids=tuple(
            f"{resource.role.value}:{resource.resource_id}"
            for resource in sorted(
                resources,
                key=lambda item: f"{item.role.value}:{item.resource_id}",
            )
        ),
    )
    journal.transition(
        record.transaction_id,
        AttemptPhase.CANDIDATE_CHECKPOINTED,
        checkpoint_revision=SHA_B,
        checkpoint_ref=f"refs/9to5/checkpoints/{record.transaction_id}",
        candidate_snapshot_digest=DIGEST_A,
        parser_manifest_digest=DIGEST_B,
        blob_set_digest=DIGEST_C,
    )
    return journal.transition(
        record.transaction_id,
        AttemptPhase.STAGED_PREPARED,
        staging_receipt_id=DIGEST_A,
        proposed_revision=SHA_B,
        proposed_tree="c" * 40,
        proposed_diff_digest=DIGEST_B,
        staged_ref=f"refs/9to5/staged/{record.transaction_id}",
        staging_manifest_bundle_digest="6" * 64,
        expected_manifest_digest=record.source_manifest_digest,
        proposed_manifest_digest=DIGEST_B,
    )


def _through_promoted(
    journal: AttemptJournal,
    record: AttemptRecord,
    *,
    review_receipt_id: str = DIGEST_C,
    promotion_receipt_id: str = DIGEST_C,
) -> AttemptRecord:
    staged = _through_staging(journal, record)
    journal.transition(
        staged.transaction_id,
        AttemptPhase.VERIFIED,
        verification_receipt_id=DIGEST_B,
        verified_revision=SHA_B,
    )
    journal.transition(
        staged.transaction_id,
        AttemptPhase.PROMOTION_PREPARED,
        review_receipt_id=review_receipt_id,
    )
    canonical_index = Path(record.canonical_root) / ".git" / "index"
    journal.bind_promotion_plan(
        staged.transaction_id,
        intent_ref=f"refs/9to5/promotion-intent/{staged.transaction_id}",
        proposed_index_digest=DIGEST_A,
        proposed_index_path=str(journal.root / "artifacts" / "proposed.index"),
        canonical_index_path=str(canonical_index),
        index_fence_path=str(canonical_index.with_name("index.lock")),
        orig_head_fence_path=str(canonical_index.with_name("ORIG_HEAD.lock")),
        index_fence_nonce=DIGEST_B,
        index_fence_owner_digest=DIGEST_A,
        orig_head_fence_owner_digest=DIGEST_B,
        custom_lock_path=str(journal.root / "locks" / "promotion.lock"),
        custom_lock_owner_digest=DIGEST_B,
        canonical_ref_lock_path=str(
            Path(record.canonical_root) / ".git" / "refs" / "heads" / "main.lock"
        ),
        canonical_ref_lock_owner_digest=DIGEST_A,
        materialization_manifest_digest=DIGEST_C,
        index_install_sibling=str(
            Path(record.canonical_root) / ".git" / "index.galaxy.new"
        ),
    )
    journal.bind_promotion_artifact_identities(
        staged.transaction_id,
        custom_lock_identity_digest=DIGEST_C,
        index_fence_identity_digest=DIGEST_C,
        orig_head_fence_identity_digest=DIGEST_A,
        canonical_ref_lock_identity_digest=DIGEST_B,
    )
    journal.transition(
        staged.transaction_id,
        AttemptPhase.INDEX_FENCED,
    )
    journal.transition(
        staged.transaction_id,
        AttemptPhase.REF_MOVED,
        observed_revision=SHA_A,
        resulting_revision=SHA_B,
    )
    journal.transition(
        staged.transaction_id,
        AttemptPhase.MATERIALIZED,
        canonical_index_digest=DIGEST_B,
        canonical_tree_digest=DIGEST_B,
    )
    return journal.transition(
        staged.transaction_id,
        AttemptPhase.PROMOTED,
        promotion_receipt_id=promotion_receipt_id,
    )


def _real_persistence_transaction(
    tmp_path: Path,
) -> tuple[TaskState, dict, AttemptJournal, AttemptRecord, AttemptPersistenceRequest]:
    state = TaskState.create("transaction persistence", 1.0)
    subtask = state.addSubtask("promote", "persist promoted attempt")
    journal = AttemptJournal(tmp_path / "journals")
    record = replace(
        _record(tmp_path, transaction_id="tx-real-state"),
        task_id=state.task_id,
        subtask_id=subtask["subtask_id"],
    )
    promoted = _through_promoted(
        journal,
        record,
        review_receipt_id="7" * 64,
        promotion_receipt_id="8" * 64,
    )
    finalization_id = "4" * 64
    cleanup_id = "5" * 64
    journal.append_finalization_receipt(promoted.transaction_id, finalization_id)
    journal.append_cleanup_receipt(
        promoted.transaction_id,
        cleanup_id,
        finalization_receipt_id=finalization_id,
        previous_cleanup_receipt_id="",
        complete=True,
    )
    current = journal.load(promoted.transaction_id)
    receipt_ids = (
        current.staging_receipt_id,
        current.verification_receipt_id,
        current.review_receipt_id,
        current.promotion_receipt_id,
        current.finalization_receipt_id,
        *current.cleanup_receipt_ids,
    )
    request = AttemptPersistenceRequest(
        transaction_id=current.transaction_id,
        subtask_id=subtask["subtask_id"],
        outcome="promoted",
        receipt_ids=receipt_ids,
    )
    return state, subtask, journal, current, request


def _persistence_authority(
    journal: AttemptJournal,
    record: AttemptRecord,
    *,
    controller_generation: list[int] | None = None,
    issuer_capture: list[object] | None = None,
):
    from platform_core.runtime.attempt_journal import (
        AttemptPersistenceAuthorityIssuer,
    )

    active_generation = controller_generation or [7]
    process_capability = object()
    controller_authority = issueDiagnosticControllerStateAuthority(
        root=journal.root.parent,
        repository_id=record.repository_id,
        controller_generation=active_generation[0],
        process_capability=process_capability,
        expires_at="2099-01-01T00:00:00+00:00",
    )
    issuer = AttemptPersistenceAuthorityIssuer(
        journal_root=journal.root,
        controller_state_authority=controller_authority,
        controller_generation_probe=lambda: active_generation[0],
        watchdog_generation=3,
        watchdog_generation_probe=lambda: 3,
        process_capability=process_capability,
    )
    if issuer_capture is not None:
        issuer_capture.append(issuer)
    return issuer.issueAuthority(
        transaction_id=record.transaction_id,
        task_id=record.task_id,
        subtask_id=record.subtask_id,
        process_capability=process_capability,
        deadline=datetime(2098, 1, 1, tzinfo=timezone.utc),
    )


def test_attempt_persistence_authority_exposes_only_an_opaque_handle(
    tmp_path: Path,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    promoted = _through_promoted(journal, _record(tmp_path))
    authority = _persistence_authority(journal, promoted)

    assert not hasattr(authority, "_issuer")

    for scope_field in (
        "transaction_id",
        "task_id",
        "subtask_id",
        "repository_id",
        "journal_root",
        "journal_root_device",
        "journal_root_inode",
        "controller_generation",
        "watchdog_generation",
        "deadline",
    ):
        assert not hasattr(authority, scope_field), scope_field


def test_persistence_issuer_binding_cannot_be_retargeted(tmp_path: Path) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    promoted = _through_promoted(journal, _record(tmp_path))
    issuers: list[object] = []
    _persistence_authority(journal, promoted, issuer_capture=issuers)
    issuer = issuers[0]
    retargeted_root = str(tmp_path / "retargeted-journal")

    with pytest.raises(AttributeError):
        issuer._journal_root = retargeted_root

    registered_authorities = set(
        attempt_journal_module._PERSISTENCE_ISSUER_REGISTRY
    )
    object.__setattr__(issuer._binding, "journal_root", retargeted_root)
    with pytest.raises(
        AttemptPersistenceAuthorityRefused,
        match="issuer binding is invalid",
    ):
        issuer.issueAuthority(
            transaction_id="tx-retargeted",
            task_id=promoted.task_id,
            subtask_id=promoted.subtask_id,
            process_capability=issuer._process_capability,
            deadline=datetime(2098, 1, 1, tzinfo=timezone.utc),
        )
    assert set(attempt_journal_module._PERSISTENCE_ISSUER_REGISTRY) == (
        registered_authorities
    )


def test_attempt_persistence_authority_rejects_in_place_token_retargeting(
    tmp_path: Path,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    promoted = _through_promoted(journal, _record(tmp_path))
    authority = _persistence_authority(journal, promoted)
    object.__setattr__(authority, "_token", object())

    with pytest.raises(
        AttemptPersistenceAuthorityRefused,
        match="issuer differs",
    ):
        journal.validate_persistence_authority(
            authority,
            transaction_id=promoted.transaction_id,
        )


def test_attempt_persistence_authority_rejects_a_forged_copy(
    tmp_path: Path,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    promoted = _through_promoted(journal, _record(tmp_path))
    authority = _persistence_authority(journal, promoted)
    forged = replace(authority)

    with pytest.raises(
        AttemptPersistenceAuthorityRefused,
        match="issuer differs",
    ):
        journal.validate_persistence_authority(
            forged,
            transaction_id=promoted.transaction_id,
        )


def test_persistence_issuer_scope_survives_parent_authority_retargeting(
    tmp_path: Path,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    promoted = _through_promoted(journal, _record(tmp_path))
    issuers: list[object] = []
    _persistence_authority(journal, promoted, issuer_capture=issuers)
    issuer = issuers[0]
    object.__setattr__(
        issuer._controller_authority,
        "_token",
        object(),
    )

    with pytest.raises(
        AttemptPersistenceAuthorityRefused,
        match="controller-state authority is invalid",
    ):
        issuer.issueAuthority(
            transaction_id=promoted.transaction_id,
            task_id=promoted.task_id,
            subtask_id=promoted.subtask_id,
            process_capability=issuer._process_capability,
            deadline=datetime(2098, 1, 1, tzinfo=timezone.utc),
        )


def test_diagnostic_persistence_issuer_refuses_after_controller_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    promoted = _through_promoted(journal, _record(tmp_path))
    monkeypatch.setattr(
        attempt_journal_module,
        "_controller_paths_active",
        lambda: True,
    )

    with pytest.raises(
        AttemptPersistenceAuthorityRefused,
        match="diagnostic.*activation",
    ):
        _persistence_authority(journal, promoted)


def test_preexisting_diagnostic_persistence_authority_loses_power_at_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    promoted = _through_promoted(journal, _record(tmp_path))
    authority = _persistence_authority(journal, promoted)
    monkeypatch.setattr(
        attempt_journal_module,
        "_controller_paths_active",
        lambda: True,
    )

    with pytest.raises(
        AttemptPersistenceAuthorityRefused,
        match="diagnostic.*activation",
    ):
        journal.validate_persistence_authority(
            authority,
            transaction_id=promoted.transaction_id,
        )


@pytest.mark.parametrize("tamper", ["task", "receipts"])
def test_attempt_persistence_refuses_unbound_task_or_receipt_chain_before_save(
    tmp_path: Path,
    tamper: str,
) -> None:
    state, subtask, journal, promoted, request = _real_persistence_transaction(
        tmp_path
    )
    if tamper == "task":
        state = TaskState.create("different task", 1.0)
        replacement = state.addSubtask("promote", "wrong task")
        assert replacement["subtask_id"] == subtask["subtask_id"]
    else:
        request = replace(
            request,
            receipt_ids=(*request.receipt_ids[:-1], "9" * 64),
        )

    def forbidden_save(_snapshot: dict) -> None:
        pytest.fail("unbound persistence reached the TaskState store")

    with pytest.raises(RecoveryRefused):
        persistAttemptTransaction(
            state=state,
            request=request,
            journal=journal,
            authority=_persistence_authority(journal, promoted),
            save_snapshot=forbidden_save,
        )


@pytest.mark.parametrize(
    ("failpoint", "expected_status", "expected_ack"),
    [
        ("before_pending_save", "pending", False),
        ("before_ack", "promotion_persistence_pending", False),
        ("before_done_save", "promotion_persistence_pending", True),
    ],
)
def test_real_promotion_persistence_crash_prefix_replays_without_duplicate_receipts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failpoint: str,
    expected_status: str,
    expected_ack: bool,
) -> None:
    state, subtask, journal, promoted, request = _real_persistence_transaction(
        tmp_path
    )
    authority = _persistence_authority(journal, promoted)
    writes = 0

    def crashable_save(snapshot: dict) -> None:
        nonlocal writes
        writes += 1
        if failpoint == "before_pending_save" and writes == 1:
            raise OSError("injected pending save crash")
        if failpoint == "before_done_save" and writes == 2:
            raise OSError("injected done save crash")
        task_io.saveDataSnapshot(state, snapshot)

    if failpoint == "before_ack":

        def crash_ack(
            _transaction_id: str,
            *,
            authority: object = None,
        ) -> AttemptRecord:
            del authority
            raise OSError("injected acknowledgement crash")

        monkeypatch.setattr(journal, "mark_task_state_acknowledged", crash_ack)

    with pytest.raises(PromotionPersistencePending):
        persistAttemptTransaction(
            state=state,
            request=request,
            journal=journal,
            authority=authority,
            save_snapshot=crashable_save,
        )

    durable_state = TaskState.load(state.task_id)
    durable_subtask = durable_state.getSubtask(subtask["subtask_id"])
    assert durable_subtask is not None
    crashed_attempt = AttemptJournal(journal.root).load(promoted.transaction_id)
    assert durable_subtask["status"] == expected_status
    assert crashed_attempt.task_state_acknowledged is expected_ack
    assert crashed_attempt.terminal_state_persisted is False

    replay_journal = AttemptJournal(journal.root)
    result = persistAttemptTransaction(
        state=durable_state,
        request=request,
        journal=replay_journal,
        authority=authority,
    )

    final_state = TaskState.load(state.task_id)
    final_subtask = final_state.getSubtask(subtask["subtask_id"])
    assert final_subtask is not None
    assert final_subtask["status"] == "done"
    assert len(final_subtask["receipts"]) == 1
    assert final_subtask["receipts"][0]["transaction_id"] == promoted.transaction_id
    final_attempt = replay_journal.load(promoted.transaction_id)
    assert final_attempt.task_state_acknowledged is True
    assert final_attempt.terminal_state_persisted is True
    assert replay_journal.pending_recovery() == ()
    assert result.terminal is True


def test_done_subtask_refuses_a_different_promoted_transaction_before_save(
    tmp_path: Path,
) -> None:
    state, subtask, journal, first, first_request = _real_persistence_transaction(
        tmp_path
    )
    persistAttemptTransaction(
        state=state,
        request=first_request,
        journal=journal,
        authority=_persistence_authority(journal, first),
    )
    second_record = replace(
        _record(tmp_path, transaction_id="tx-second-state"),
        task_id=state.task_id,
        subtask_id=subtask["subtask_id"],
    )
    _through_promoted(
        journal,
        second_record,
        review_receipt_id="d" * 64,
        promotion_receipt_id="e" * 64,
    )
    journal.append_finalization_receipt(second_record.transaction_id, "6" * 64)
    journal.append_cleanup_receipt(
        second_record.transaction_id,
        "9" * 64,
        finalization_receipt_id="6" * 64,
        previous_cleanup_receipt_id="",
        complete=True,
    )
    second = journal.load(second_record.transaction_id)
    second_request = AttemptPersistenceRequest(
        transaction_id=second.transaction_id,
        subtask_id=second.subtask_id,
        outcome="promoted",
        receipt_ids=(
            second.staging_receipt_id,
            second.verification_receipt_id,
            second.review_receipt_id,
            second.promotion_receipt_id,
            second.finalization_receipt_id,
            *second.cleanup_receipt_ids,
        ),
    )

    def forbidden_save(_snapshot: dict) -> None:
        pytest.fail("cross-attempt promotion reached the TaskState store")

    with pytest.raises(RecoveryRefused, match="different transaction"):
        persistAttemptTransaction(
            state=state,
            request=second_request,
            journal=journal,
            authority=_persistence_authority(journal, second),
            save_snapshot=forbidden_save,
        )


def test_real_taskstate_attemptjournal_pending_ack_done_terminal_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A terminal-axis crash replays from durable TaskState/journal truth only."""

    state, subtask, journal, promoted, request = _real_persistence_transaction(
        tmp_path
    )
    authority = _persistence_authority(journal, promoted)
    receipt_ids = request.receipt_ids
    observed_writes: list[tuple[str, bool, bool]] = []

    def save_snapshot(snapshot: dict) -> None:
        TaskState(copy.deepcopy(snapshot)).save()
        durable = TaskState.load(state.task_id)
        durable_subtask = durable.getSubtask(subtask["subtask_id"])
        assert durable_subtask is not None
        axes = AttemptJournal(journal.root).load(promoted.transaction_id)
        observed_writes.append(
            (
                durable_subtask["status"],
                axes.task_state_acknowledged,
                axes.terminal_state_persisted,
            )
        )

    def crash_before_terminal(
        _transaction_id: str,
        *,
        authority: object = None,
    ) -> AttemptRecord:
        del authority
        raise OSError("injected terminal flag crash")

    monkeypatch.setattr(
        journal,
        "mark_terminal_state_persisted",
        crash_before_terminal,
    )

    with pytest.raises(PromotionPersistencePending, match="terminal-state"):
        persistAttemptTransaction(
            state=state,
            request=request,
            journal=journal,
            authority=authority,
            save_snapshot=save_snapshot,
        )

    crashed_state = TaskState.load(state.task_id)
    crashed_subtask = crashed_state.getSubtask(subtask["subtask_id"])
    assert crashed_subtask is not None
    crashed_record = AttemptJournal(journal.root).load(promoted.transaction_id)
    assert crashed_subtask["status"] == "done"
    assert crashed_record.task_state_acknowledged is True
    assert crashed_record.terminal_state_persisted is False
    assert AttemptJournal(journal.root).pending_recovery() == (crashed_record,)

    replay_journal = AttemptJournal(journal.root)
    result = persistAttemptTransaction(
        state=crashed_state,
        request=request,
        journal=replay_journal,
        authority=authority,
        save_snapshot=save_snapshot,
    )

    durable = TaskState.load(state.task_id)
    durable_subtask = durable.getSubtask(subtask["subtask_id"])
    assert durable_subtask is not None
    final_record = replay_journal.load(promoted.transaction_id)
    assert observed_writes[:2] == [
        ("promotion_persistence_pending", False, False),
        ("done", True, False),
    ]
    assert all(status == "done" for status, *_ in observed_writes[2:])
    assert durable_subtask["status"] == "done"
    assert durable_subtask["receipts"] == [
        {
            "transaction_id": promoted.transaction_id,
            "outcome": "promoted",
            "receipt_ids": list(receipt_ids),
        }
    ]
    assert final_record.task_state_acknowledged is True
    assert final_record.terminal_state_persisted is True
    assert replay_journal.pending_recovery() == ()
    assert result.terminal is True


def test_create_and_replay_exact_lease_record(tmp_path: Path) -> None:
    journal = AttemptJournal(tmp_path / "controller" / "journals")
    record = _record(tmp_path)
    created = journal.create(record)
    assert created.phase is AttemptPhase.LEASE_REGISTERED
    assert created.sequence == 0
    assert journal.create(record) == created
    assert journal.load(record.transaction_id) == created


@pytest.mark.parametrize("with_empty_events", [False, True])
def test_pre_registration_crash_debris_cannot_hide_other_recovery(
    tmp_path: Path,
    with_empty_events: bool,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    promoted = _through_promoted(journal, _record(tmp_path, transaction_id="tx-live"))
    orphan_id = "tx-crashed-before-event-zero"
    orphan = journal._transaction_directory(orphan_id)
    (orphan / "events" if with_empty_events else orphan).mkdir(
        parents=True,
        exist_ok=True,
    )

    assert journal.pending_recovery() == (promoted,)

    recovered = journal.create(_record(tmp_path, transaction_id=orphan_id))
    assert recovered.phase is AttemptPhase.LEASE_REGISTERED
    assert journal.load(orphan_id) == recovered


def test_phase_transitions_are_direct_monotonic_and_validate_required_truth(tmp_path: Path) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    provisional = _record(tmp_path)
    resources = _local_runtime_closure(provisional)
    record = journal.create(_with_runtime_manifest(provisional, resources))
    registered = journal.register_resources(record.transaction_id, resources)
    identities = tuple(
        f"{resource.role.value}:{resource.resource_id}" for resource in registered
    )
    with pytest.raises(InvalidAttemptTransition, match="lease_registered -> verified"):
        journal.transition(record.transaction_id, AttemptPhase.VERIFIED)
    with pytest.raises(InvalidAttemptTransition, match="resource_lease_ids"):
        journal.transition(record.transaction_id, AttemptPhase.RUNNING)

    running = journal.transition(
        record.transaction_id,
        AttemptPhase.RUNNING,
        resource_lease_ids=identities,
    )
    assert running.sequence == 1
    assert journal.transition(
        record.transaction_id,
        AttemptPhase.RUNNING,
        resource_lease_ids=identities,
    ) == running
    with pytest.raises(
        InvalidAttemptTransition,
        match="write-once|immutable phase fields|completed canonical set",
    ):
        journal.transition(
            record.transaction_id,
            AttemptPhase.RUNNING,
            resource_lease_ids=("driver:other",),
        )


def test_forward_transition_cannot_rewrite_prior_phase_truth(tmp_path: Path) -> None:
    """Receipt/ref/revision evidence is write-once across the whole chain."""

    journal = AttemptJournal(tmp_path / "journals")
    provisional = _record(tmp_path)
    resources = _local_runtime_closure(provisional)
    record = journal.create(_with_runtime_manifest(provisional, resources))
    registered = journal.register_resources(record.transaction_id, resources)
    journal.transition(
        record.transaction_id,
        AttemptPhase.RUNNING,
        resource_lease_ids=tuple(
            f"{resource.role.value}:{resource.resource_id}"
            for resource in registered
        ),
    )
    journal.transition(
        record.transaction_id,
        AttemptPhase.CANDIDATE_CHECKPOINTED,
        checkpoint_revision="a" * 40,
        checkpoint_ref=f"refs/9to5/checkpoints/{record.transaction_id}",
        candidate_snapshot_digest="1" * 64,
        parser_manifest_digest="2" * 64,
        blob_set_digest="3" * 64,
    )

    with pytest.raises(InvalidAttemptTransition, match="checkpoint|write-once|phase"):
        journal.transition(
            record.transaction_id,
            AttemptPhase.STAGED_PREPARED,
            checkpoint_revision="b" * 40,
            staging_receipt_id="4" * 64,
            proposed_revision="c" * 40,
            proposed_tree="d" * 40,
            proposed_diff_digest="5" * 64,
            staged_ref=f"refs/9to5/staged/{record.transaction_id}",
        )


def test_durable_event_survives_head_update_crash_and_retry(tmp_path: Path, monkeypatch) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    provisional = _record(tmp_path)
    resources = _local_runtime_closure(provisional)
    record = journal.create(_with_runtime_manifest(provisional, resources))
    registered = journal.register_resources(record.transaction_id, resources)
    identities = tuple(
        f"{resource.role.value}:{resource.resource_id}" for resource in registered
    )

    def crash_after_event(*args, **kwargs):
        raise OSError("injected head replacement crash")

    monkeypatch.setattr(journal, "_write_head", crash_after_event)
    with pytest.raises(OSError, match="injected"):
        journal.transition(
            record.transaction_id,
            AttemptPhase.RUNNING,
            resource_lease_ids=identities,
        )

    recovered = AttemptJournal(journal.root).load(record.transaction_id)
    assert recovered.phase is AttemptPhase.RUNNING
    assert recovered.sequence == 1
    replay = AttemptJournal(journal.root)
    assert replay.transition(
        record.transaction_id,
        AttemptPhase.RUNNING,
        resource_lease_ids=identities,
    ) == recovered
    head = replay._transaction_directory(record.transaction_id) / "head.json"
    assert f'"sequence":{recovered.sequence}' in head.read_text(encoding="utf-8")


def test_forked_sequence_is_corruption_not_last_writer_wins(tmp_path: Path) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    event_dir = journal.event_directory(record.transaction_id)
    forged = event_dir / ("00000000-" + "f" * 64 + ".json")
    forged.write_text("{}", encoding="utf-8")
    with pytest.raises(JournalCorruption, match="forked sequence"):
        journal.load(record.transaction_id)


def test_promoted_truth_remains_pending_until_all_three_axes_are_durable(tmp_path: Path) -> None:
    journal = AttemptJournal(tmp_path / "journals", diagnostic=True)
    promoted = _through_promoted(journal, _record(tmp_path))
    assert promoted.phase is AttemptPhase.PROMOTED
    assert journal.pending_recovery() == (promoted,)

    journal.mark_task_state_acknowledged(promoted.transaction_id)
    with pytest.raises(InvalidAttemptTransition, match="cannot move backward"):
        journal.set_recovery_axes(
            promoted.transaction_id,
            task_state_acknowledged=False,
        )
    journal.append_finalization_receipt(
        promoted.transaction_id,
        "4" * 64,
    )
    cleaned = journal.append_cleanup_receipt(
        promoted.transaction_id,
        "5" * 64,
        finalization_receipt_id="4" * 64,
        previous_cleanup_receipt_id="",
        complete=True,
    )
    assert cleaned.task_state_acknowledged is True
    assert journal.pending_recovery()
    terminal = journal.mark_terminal_state_persisted(promoted.transaction_id)
    assert terminal.cleanup_complete is True
    assert journal.pending_recovery() == ()


def test_terminal_state_cannot_precede_task_state_acknowledgement(tmp_path: Path) -> None:
    journal = AttemptJournal(tmp_path / "journals", diagnostic=True)
    promoted = _through_promoted(journal, _record(tmp_path))
    with pytest.raises(InvalidAttemptTransition, match="acknowledgement"):
        journal.mark_terminal_state_persisted(promoted.transaction_id)


@pytest.mark.parametrize("construction", ["default", "explicit"])
@pytest.mark.parametrize("runtime_state", ["pending", "live", "poisoned", "inconsistent"])
def test_diagnostic_journal_rejects_runtime_terminal_before_root_observation(
    construction: str,
    runtime_state: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = __import__(
        "platform_core.runtime.controller_state",
        fromlist=["controller_state"],
    )
    paths = __import__("platform_core.app_config.paths", fromlist=["paths"])
    worker = __import__(
        "platform_core.runtime.state_store_worker",
        fromlist=["state_store_worker"],
    )
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", None)
    monkeypatch.setattr(worker, "_INSTALLED_BINDING", None)
    if runtime_state == "pending":
        terminal = controller._PendingControllerRuntimeStateInstallation(
            bootstrap_authorities=object(),
            owner_thread_id=threading.get_ident(),
        )
        binding = None
    elif runtime_state == "poisoned":
        terminal = controller._PoisonedControllerRuntimeStateInstallation(
            bootstrap_id="f" * 64,
            reason="test poison",
        )
        binding = None
    elif runtime_state == "live":
        terminal = object()
        binding = object()
    else:
        terminal = None
        binding = object()
    monkeypatch.setattr(controller, "_RUNTIME_INSTALL_TERMINAL", terminal)
    monkeypatch.setattr(controller, "_RUNTIME_BINDING", binding)
    observations: list[str] = []
    root = _ObservedJournalRoot(tmp_path / "journal", observations)

    with pytest.raises(
        AttemptPersistenceAuthorityRefused,
        match="absent runtime",
    ):
        if construction == "default":
            AttemptJournal(root)
        else:
            AttemptJournal(root, diagnostic=True)
    assert observations == []


def test_unbound_nondiagnostic_journal_refuses_before_root_observation(
    tmp_path: Path,
) -> None:
    observations: list[str] = []
    root = _ObservedJournalRoot(tmp_path / "journal", observations)

    with pytest.raises(
        AttemptPersistenceAuthorityRefused,
        match="installed|bundle|authority",
    ):
        AttemptJournal(root, diagnostic=False)
    assert observations == []


def test_preexisting_diagnostic_journal_rejects_poison_before_storage_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = __import__(
        "platform_core.runtime.controller_state",
        fromlist=["controller_state"],
    )
    paths = __import__("platform_core.app_config.paths", fromlist=["paths"])
    worker = __import__(
        "platform_core.runtime.state_store_worker",
        fromlist=["state_store_worker"],
    )
    monkeypatch.setattr(controller, "_RUNTIME_INSTALL_TERMINAL", None)
    monkeypatch.setattr(controller, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", None)
    monkeypatch.setattr(worker, "_INSTALLED_BINDING", None)
    journal = AttemptJournal(tmp_path / "journal")
    record = journal.create(_record(tmp_path))
    poison = controller._PoisonedControllerRuntimeStateInstallation(
        bootstrap_id="f" * 64,
        reason="test poison",
    )
    monkeypatch.setattr(controller, "_RUNTIME_INSTALL_TERMINAL", poison)
    storage_observed: list[str] = []
    monkeypatch.setattr(
        journal,
        "_load_chain",
        lambda _transaction_id: storage_observed.append("load") or None,
    )

    with pytest.raises(
        AttemptPersistenceAuthorityRefused,
        match="absent runtime",
    ):
        journal.load(record.transaction_id)
    assert storage_observed == []


def test_diagnostic_journal_holds_runtime_fence_through_storage_operation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = __import__(
        "platform_core.runtime.controller_state",
        fromlist=["controller_state"],
    )
    paths = __import__("platform_core.app_config.paths", fromlist=["paths"])
    worker = __import__(
        "platform_core.runtime.state_store_worker",
        fromlist=["state_store_worker"],
    )
    monkeypatch.setattr(controller, "_RUNTIME_INSTALL_TERMINAL", None)
    monkeypatch.setattr(controller, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", None)
    monkeypatch.setattr(worker, "_INSTALLED_BINDING", None)
    journal = AttemptJournal(tmp_path / "journal", diagnostic=True)
    record = journal.create(_record(tmp_path))
    effect_started = threading.Event()
    release_effect = threading.Event()
    runtime_lock_acquired = threading.Event()
    original = journal._load_chain

    def blocking_load(transaction_id: str):
        effect_started.set()
        assert release_effect.wait(5)
        return original(transaction_id)

    monkeypatch.setattr(journal, "_load_chain", blocking_load)
    operation = threading.Thread(
        target=lambda: journal.load(record.transaction_id),
        daemon=True,
    )
    operation.start()
    assert effect_started.wait(5)

    def acquire_runtime_lock() -> None:
        with controller._RUNTIME_BINDING_LOCK:
            runtime_lock_acquired.set()

    contender = threading.Thread(target=acquire_runtime_lock, daemon=True)
    contender.start()
    assert not runtime_lock_acquired.wait(0.2)
    release_effect.set()
    operation.join(5)
    contender.join(5)
    assert not operation.is_alive()
    assert not contender.is_alive()
    assert runtime_lock_acquired.is_set()


def test_diagnostic_persistence_issuer_revalidates_after_generation_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = __import__(
        "platform_core.runtime.controller_state",
        fromlist=["controller_state"],
    )
    paths = __import__("platform_core.app_config.paths", fromlist=["paths"])
    worker = __import__(
        "platform_core.runtime.state_store_worker",
        fromlist=["state_store_worker"],
    )
    monkeypatch.setattr(controller, "_RUNTIME_INSTALL_TERMINAL", None)
    monkeypatch.setattr(controller, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", None)
    monkeypatch.setattr(worker, "_INSTALLED_BINDING", None)
    journal = AttemptJournal(tmp_path / "journal")
    record = journal.create(_record(tmp_path))
    poison = controller._PoisonedControllerRuntimeStateInstallation(
        bootstrap_id="f" * 64,
        reason="probe poison",
    )
    process_capability = object()
    controller_authority = issueDiagnosticControllerStateAuthority(
        root=journal.root.parent,
        repository_id=record.repository_id,
        controller_generation=7,
        process_capability=process_capability,
        expires_at="2099-01-01T00:00:00+00:00",
    )
    probe_calls = 0

    def poison_during_probe() -> int:
        nonlocal probe_calls
        probe_calls += 1
        if probe_calls == 2:
            controller._RUNTIME_INSTALL_TERMINAL = poison
        return 7

    issuer = attempt_journal_module.AttemptPersistenceAuthorityIssuer(
        journal_root=journal.root,
        controller_state_authority=controller_authority,
        controller_generation_probe=poison_during_probe,
        watchdog_generation=3,
        watchdog_generation_probe=lambda: 3,
        process_capability=process_capability,
    )
    registered_authorities = set(
        attempt_journal_module._PERSISTENCE_ISSUER_REGISTRY
    )
    with pytest.raises(
        AttemptPersistenceAuthorityRefused,
        match="absent runtime",
    ):
        issuer.issueAuthority(
            transaction_id=record.transaction_id,
            task_id=record.task_id,
            subtask_id=record.subtask_id,
            process_capability=process_capability,
            deadline=datetime(2098, 1, 1, tzinfo=timezone.utc),
        )
    assert set(attempt_journal_module._PERSISTENCE_ISSUER_REGISTRY) == (
        registered_authorities
    )


def test_cleanup_receipt_chain_is_append_only_retryable_and_finalization_bound(
    tmp_path: Path,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    promoted = _through_promoted(journal, _record(tmp_path))
    finalization_id = "4" * 64
    first_cleanup_id = "5" * 64
    second_cleanup_id = "6" * 64

    finalized = journal.append_finalization_receipt(
        promoted.transaction_id,
        finalization_id,
    )
    assert finalized.finalization_receipt_id == finalization_id
    first = journal.append_cleanup_receipt(
        promoted.transaction_id,
        first_cleanup_id,
        finalization_receipt_id=finalization_id,
        previous_cleanup_receipt_id="",
        complete=False,
    )
    assert first.cleanup_receipt_ids == (first_cleanup_id,)
    assert first.cleanup_receipt_completions == (False,)
    assert first.cleanup_receipt_id == first_cleanup_id
    assert first.cleanup_complete is False

    second = journal.append_cleanup_receipt(
        promoted.transaction_id,
        second_cleanup_id,
        finalization_receipt_id=finalization_id,
        previous_cleanup_receipt_id=first_cleanup_id,
        complete=True,
    )
    assert second.cleanup_receipt_ids == (first_cleanup_id, second_cleanup_id)
    assert second.cleanup_receipt_completions == (False, True)
    assert second.cleanup_receipt_id == second_cleanup_id
    assert second.cleanup_complete is True

    assert journal.append_cleanup_receipt(
        promoted.transaction_id,
        first_cleanup_id,
        finalization_receipt_id=finalization_id,
        previous_cleanup_receipt_id="",
        complete=False,
    ) == second
    with pytest.raises(InvalidAttemptTransition, match="previous cleanup"):
        journal.append_cleanup_receipt(
            promoted.transaction_id,
            "7" * 64,
            finalization_receipt_id=finalization_id,
            previous_cleanup_receipt_id=first_cleanup_id,
            complete=True,
        )
    with pytest.raises(InvalidAttemptTransition, match="cannot become incomplete"):
        journal.append_cleanup_receipt(
            promoted.transaction_id,
            "8" * 64,
            finalization_receipt_id=finalization_id,
            previous_cleanup_receipt_id=second_cleanup_id,
            complete=False,
        )


def test_reconciliation_replay_uses_the_outcome_bound_to_its_own_receipt(
    tmp_path: Path,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    promoted = _through_promoted(journal, _record(tmp_path))
    first_id = "7" * 64
    second_id = "8" * 64
    journal.append_reconciliation_receipt(
        promoted.transaction_id,
        first_id,
        outcome="promoted_recovered",
    )
    latest = journal.append_reconciliation_receipt(
        promoted.transaction_id,
        second_id,
        outcome="historical_promotion_subsequent_revision",
    )
    replay = journal.append_reconciliation_receipt(
        promoted.transaction_id,
        first_id,
        outcome="promoted_recovered",
    )
    assert replay == latest
    assert replay.reconciliation_receipt_outcomes == (
        "promoted_recovered",
        "historical_promotion_subsequent_revision",
    )


def _successful_finalization(promoted: AttemptRecord) -> FinalizationReceipt:
    return FinalizationReceipt(
        backend="clone",
        accepted=True,
        requires_canonical_landing=True,
        collected=True,
        merged=True,
        expected_revision=promoted.base_revision,
        observed_revision=promoted.base_revision,
        resulting_revision=promoted.resulting_revision,
        verification_revision=promoted.resulting_revision,
        promotion_transaction_id=promoted.transaction_id,
        staging_receipt_id=promoted.staging_receipt_id,
        verification_receipt_id=promoted.verification_receipt_id,
        review_receipt_id=promoted.review_receipt_id,
        promotion_receipt_id=promoted.promotion_receipt_id,
        materialized=True,
        journal_phase="promoted",
    )


def _cleanup_artifacts() -> tuple[CleanupArtifact, ...]:
    return (
        CleanupArtifact(
            artifact_id="candidate:tx-001",
            disposition=CleanupDisposition.REMOVE,
            ownership_digest="1" * 64,
            runtime_token=object(),
        ),
        CleanupArtifact(
            artifact_id="checkpoint:tx-001",
            disposition=CleanupDisposition.RETAIN,
            ownership_digest="2" * 64,
            runtime_token=object(),
        ),
        CleanupArtifact(
            artifact_id="verification:tx-001",
            disposition=CleanupDisposition.REMOVE,
            ownership_digest="3" * 64,
            runtime_token=object(),
        ),
    )


def test_cleanup_coordinator_persists_finalization_then_retries_only_failures(
    tmp_path: Path,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    promoted = _through_promoted(journal, _record(tmp_path))
    store = ReceiptStore(tmp_path / "receipts")
    finalization = _successful_finalization(promoted)
    artifacts = _cleanup_artifacts()
    capability = object()
    calls: list[str] = []
    fail_verification = True

    def remove(artifact: CleanupArtifact) -> ArtifactCleanupResult:
        nonlocal fail_verification
        assert store.read(
            finalization.receipt_id,
            expected_type=FinalizationReceipt,
        ) == finalization
        assert (
            journal.load(promoted.transaction_id).finalization_receipt_id
            == finalization.receipt_id
        )
        calls.append(artifact.artifact_id)
        if artifact.artifact_id.startswith("verification:") and fail_verification:
            fail_verification = False
            raise OSError("transient sharing violation")
        return ArtifactCleanupResult(
            artifact_id=artifact.artifact_id,
            ownership_digest=artifact.ownership_digest,
            removed=True,
            warning="",
        )

    coordinator = CleanupCoordinator(
        receipt_store=store,
        journal=journal,
        process_capability=capability,
        remove_artifact=remove,
        clock=lambda: "2026-07-16T12:30:00+00:00",
    )
    first = coordinator.cleanup(
        transaction_id=promoted.transaction_id,
        finalization=finalization,
        artifacts=artifacts,
        process_capability=capability,
    )
    assert first.complete is False
    assert first.failed_artifact_ids == ("verification:tx-001",)
    assert journal.load(promoted.transaction_id).cleanup_complete is False
    assert calls == ["candidate:tx-001", "verification:tx-001"]

    second = coordinator.cleanup(
        transaction_id=promoted.transaction_id,
        finalization=finalization,
        artifacts=artifacts,
        process_capability=capability,
    )
    assert second.complete is True
    assert second.previous_cleanup_receipt_id == first.receipt_id
    assert journal.load(promoted.transaction_id).cleanup_complete is True
    assert calls == [
        "candidate:tx-001",
        "verification:tx-001",
        "verification:tx-001",
    ]
    assert store.read(
        finalization.receipt_id,
        expected_type=FinalizationReceipt,
    ) == finalization


def test_cleanup_recovery_adopts_receipt_persisted_before_journal_link(
    tmp_path: Path,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    promoted = _through_promoted(journal, _record(tmp_path))
    store = ReceiptStore(tmp_path / "receipts")
    finalization = _successful_finalization(promoted)
    artifacts = _cleanup_artifacts()
    capability = object()
    calls: list[str] = []

    def remove(artifact: CleanupArtifact) -> ArtifactCleanupResult:
        calls.append(artifact.artifact_id)
        return ArtifactCleanupResult(
            artifact_id=artifact.artifact_id,
            ownership_digest=artifact.ownership_digest,
            removed=True,
            warning="",
        )

    coordinator = CleanupCoordinator(
        receipt_store=store,
        journal=journal,
        process_capability=capability,
        remove_artifact=remove,
        clock=lambda: "2026-07-16T12:30:00+00:00",
    )

    class HardDeath(BaseException):
        pass

    with pytest.raises(HardDeath):
        coordinator.cleanup(
            transaction_id=promoted.transaction_id,
            finalization=finalization,
            artifacts=artifacts,
            process_capability=capability,
            failpoint=lambda point: (
                (_ for _ in ()).throw(HardDeath(point))
                if point == "after_cleanup_receipt_persisted"
                else None
            ),
        )
    assert journal.load(promoted.transaction_id).cleanup_receipt_ids == ()
    calls_before_recovery = tuple(calls)

    recovered = CleanupCoordinator(
        receipt_store=store,
        journal=journal,
        process_capability=capability,
        remove_artifact=remove,
        clock=lambda: "2026-07-16T12:31:00+00:00",
    ).cleanup(
        transaction_id=promoted.transaction_id,
        finalization=finalization,
        artifacts=artifacts,
        process_capability=capability,
    )
    assert isinstance(recovered, CleanupReceipt)
    assert recovered.complete is True
    assert tuple(calls) == calls_before_recovery
    assert journal.load(promoted.transaction_id).cleanup_receipt_id == recovered.receipt_id


def test_tournament_promotion_requires_prelinked_selection_receipt(tmp_path: Path) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = _record(tmp_path)
    record = AttemptRecord(**(record.__dict__ | {"tournament_batch_id": "batch-001"}))
    staged = _through_staging(journal, record)
    journal.transition(
        staged.transaction_id,
        AttemptPhase.VERIFIED,
        verification_receipt_id=DIGEST_B,
        verified_revision=SHA_B,
    )
    with pytest.raises(InvalidAttemptTransition, match="selection_receipt_id"):
        journal.transition(
            staged.transaction_id,
            AttemptPhase.PROMOTION_PREPARED,
            review_receipt_id=DIGEST_C,
        )


@pytest.mark.parametrize("transaction_id", ["../escape", "bad/name", "bad\\name", "line\nbreak"])
def test_transaction_identifier_cannot_escape_journal_namespace(
    tmp_path: Path, transaction_id: str
) -> None:
    with pytest.raises(ValueError, match="transaction_id"):
        _record(tmp_path, transaction_id=transaction_id)


def test_journal_root_cannot_overlap_canonical_or_candidate_checkout(
    tmp_path: Path,
) -> None:
    record = _record(tmp_path)
    with pytest.raises(InvalidAttemptTransition, match="outside canonical"):
        AttemptJournal(Path(record.canonical_root) / "state").create(record)
    with pytest.raises(InvalidAttemptTransition, match="outside candidate"):
        AttemptJournal(Path(record.clone_path) / "journal").create(record)


def test_runtime_resource_chain_is_durable_monotonic_and_attempt_bound(
    tmp_path: Path,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    resource = RuntimeResourceLease(
        resource_id="driver-001",
        run_id="run-001",
        transaction_id=record.transaction_id,
        controller_scope_id="controller-001",
        role=ResourceRole.MODEL_DRIVER,
        backend="local",
        ownership_nonce=record.ownership_nonce,
        state=ProcessResourceState.REGISTERED,
        cleanup_locator_digest="2" * 64,
        pid=0,
        process_group_id=0,
        container_id="",
        image_digest="",
        entrypoint_digest="3" * 64,
        mount_digest="4" * 64,
        environment_digest="5" * 64,
        security_profile_digest="6" * 64,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )

    registered = journal.register_resources(record.transaction_id, (resource,))
    assert registered == (resource,)
    assert AttemptJournal(journal.root).load_resources(record.transaction_id) == (
        resource,
    )
    process_token = processStartToken(os.getpid())
    assert process_token is not None
    with pytest.raises(InvalidAttemptTransition, match="adjacent"):
        journal.transition_resource(
            record.transaction_id,
            resource.resource_id,
            ProcessResourceState.STARTED,
            pid=os.getpid(),
            process_group_id=os.getpid(),
            process_start_token=process_token,
        )
    created = journal.transition_resource(
        record.transaction_id,
        resource.resource_id,
        ProcessResourceState.CREATED,
        pid=os.getpid(),
        process_group_id=os.getpid(),
        process_start_token=process_token,
    )
    assert created.state is ProcessResourceState.CREATED
    with pytest.raises(InvalidAttemptTransition, match="birth token is write-once"):
        journal.transition_resource(
            record.transaction_id,
            resource.resource_id,
            ProcessResourceState.STARTED,
            pid=os.getpid(),
            process_group_id=os.getpid(),
            process_start_token="0" * 64,
        )
    started = journal.transition_resource(
        record.transaction_id,
        resource.resource_id,
        ProcessResourceState.STARTED,
        pid=os.getpid(),
        process_group_id=os.getpid(),
        process_start_token=process_token,
    )
    assert started.state is ProcessResourceState.STARTED
    assert started.pid == os.getpid()
    assert started.process_start_token == process_token
    assert AttemptJournal(journal.root).load_resources(record.transaction_id) == (
        started,
    )
    with pytest.raises(InvalidAttemptTransition, match="birth token is write-once"):
        journal.transition_resource(
            record.transaction_id,
            resource.resource_id,
            ProcessResourceState.QUIESCED,
            process_start_token="f" * 64,
        )
    with pytest.raises(InvalidAttemptTransition, match="adjacent|recovery-safe"):
        journal.transition_resource(
            record.transaction_id,
            resource.resource_id,
            ProcessResourceState.REGISTERED,
        )

    foreign = RuntimeResourceLease(
        **(
            resource.__dict__
            | {
                "resource_id": "foreign-001",
                "transaction_id": "tx-foreign",
            }
        )
    )
    with pytest.raises(InvalidAttemptTransition, match="another attempt"):
        journal.register_resources(record.transaction_id, (foreign,))


@pytest.mark.parametrize("secret_channel_id", ["", "invalid/channel"])
def test_registered_credential_requires_preallocated_secret_channel(
    tmp_path: Path,
    secret_channel_id: str,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    credential = replace(
        _registered_credential_resource(record),
        secret_channel_id=secret_channel_id,
    )

    with pytest.raises(InvalidAttemptTransition, match="secret channel"):
        journal.register_resources(record.transaction_id, (credential,))

    assert not (
        journal.event_directory(record.transaction_id).parent / "resources"
    ).exists()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("unknown-backend", "backend"),
        ("local-image", "local"),
        ("docker-without-image", "image"),
        ("process-credential-metadata", "credential metadata"),
        ("credential-missing-provider", "provider"),
        ("credential-missing-generation", "revocation_generation"),
    ],
)
def test_registration_contract_is_validated_before_resource_reservation(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    resource = _registered_process_resource(record)
    if mutation == "unknown-backend":
        resource = replace(resource, backend="clone")
    elif mutation == "local-image":
        resource = replace(resource, image_digest="7" * 64)
    elif mutation == "docker-without-image":
        resource = replace(resource, backend="docker")
    elif mutation == "process-credential-metadata":
        resource = replace(resource, provider="claude")
    elif mutation == "credential-missing-provider":
        resource = replace(_registered_credential_resource(record), provider="")
    else:
        resource = replace(
            _registered_credential_resource(record),
            revocation_generation=0,
        )

    with pytest.raises(InvalidAttemptTransition, match=message):
        journal.register_resources(record.transaction_id, (resource,))

    assert not (
        journal.event_directory(record.transaction_id).parent / "resources"
    ).exists()


def test_credential_resource_lifecycle_binds_issued_fingerprint_once(
    tmp_path: Path,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    credential = _registered_credential_resource(record)
    assert journal.register_resources(record.transaction_id, (credential,)) == (
        credential,
    )
    assert AttemptJournal(journal.root).load_resources(record.transaction_id) == (
        credential,
    )
    with pytest.raises(InvalidAttemptTransition, match="fingerprint"):
        journal.transition_resource(
            record.transaction_id,
            credential.resource_id,
            CredentialResourceState.ISSUED,
        )
    broker, process_capability, fingerprint, clock, lease = _prepare_credential_broker(
        tmp_path / "credential-store",
        credential,
        journal=journal,
        materialize=True,
    )
    assert lease is not None
    issued = journal.load_resources(record.transaction_id)[0]
    broker.markInjected(lease)
    injected = journal.load_resources(record.transaction_id)[0]
    broker.revoke(lease)
    revoked = journal.load_resources(record.transaction_id)[0]
    receipt, verifier = _destroy_credential_with_sealed_evidence(
        broker,
        process_capability,
        clock,
        revoked,
    )
    destroyed = journal.load_resources(record.transaction_id)[0]

    assert issued.secret_fingerprint == fingerprint
    assert injected.secret_fingerprint == issued.secret_fingerprint
    assert revoked.secret_fingerprint == issued.secret_fingerprint
    assert destroyed.secret_fingerprint == issued.secret_fingerprint
    assert destroyed.secret_channel_id == credential.secret_channel_id
    assert destroyed.credential_destruction_receipt_digest == receipt.receipt_digest
    assert destroyed.credential_destroyed_at == receipt.destroyed_at
    assert AttemptJournal(journal.root).load_resources(record.transaction_id) == (
        destroyed,
    )


@pytest.mark.parametrize("untyped", [True, {}, None])
def test_credential_destroyed_edge_requires_exact_typed_receipt(
    tmp_path: Path,
    untyped: object,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    credential = _registered_credential_resource(record)
    journal.register_resources(record.transaction_id, (credential,))
    journal.transition_resource(
        record.transaction_id,
        credential.resource_id,
        CredentialResourceState.REVOKED_OR_EXPIRED,
    )

    with pytest.raises((TypeError, InvalidAttemptTransition), match="receipt"):
        journal.transition_resource(
            record.transaction_id,
            credential.resource_id,
            CredentialResourceState.DESTROYED,
            destruction_receipt=untyped,
        )


def test_caller_minted_typed_receipt_without_sealed_verifier_cannot_destroy(
    tmp_path: Path,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    credential = _registered_credential_resource(record)
    journal.register_resources(record.transaction_id, (credential,))
    revoked = journal.transition_resource(
        record.transaction_id,
        credential.resource_id,
        CredentialResourceState.REVOKED_OR_EXPIRED,
    )
    receipt = CredentialChannelDestructionReceipt.issue(
        transaction_id=record.transaction_id,
        resource_id=credential.resource_id,
        secret_channel_id=credential.secret_channel_id,
        issuer_id=credential.issuer_id,
        revocation_generation=revoked.revocation_generation,
        cleanup_locator_digest=credential.cleanup_locator_digest,
        destroyed_at="2099-01-01T00:00:00+00:00",
    )
    resource_root = (
        journal.event_directory(record.transaction_id).parent / "resources"
    )
    before = {
        path.relative_to(resource_root).as_posix(): path.read_bytes()
        for path in resource_root.rglob("*.json")
    }

    with pytest.raises(
        (TypeError, InvalidAttemptTransition),
        match="sealed.*verifier|absence verifier",
    ):
        journal.transition_resource(
            record.transaction_id,
            credential.resource_id,
            CredentialResourceState.DESTROYED,
            destruction_receipt=receipt,
        )

    assert journal.load_resources(record.transaction_id) == (revoked,)
    assert {
        path.relative_to(resource_root).as_posix(): path.read_bytes()
        for path in resource_root.rglob("*.json")
    } == before


def test_attacker_factory_verifier_cannot_authorize_destroyed_journal_truth(
    tmp_path: Path,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    credential = _registered_credential_resource(record)
    journal.register_resources(record.transaction_id, (credential,))
    revoked = journal.transition_resource(
        record.transaction_id,
        credential.resource_id,
        CredentialResourceState.REVOKED_OR_EXPIRED,
    )
    attacker_root = tmp_path / "attacker-owned-credential-root"
    for child in ("channels", "destruction-receipts", "destruction-intents"):
        (attacker_root / child).mkdir(parents=True, exist_ok=True)
    receipt = CredentialChannelDestructionReceipt.issue(
        transaction_id=record.transaction_id,
        resource_id=credential.resource_id,
        secret_channel_id=credential.secret_channel_id,
        issuer_id=credential.issuer_id,
        revocation_generation=credential.revocation_generation,
        cleanup_locator_digest=credential.cleanup_locator_digest,
        destroyed_at="2099-01-01T00:00:00+00:00",
    )
    intent = credential_channel_module.CredentialChannelDestructionIntent.issue(
        revoked
    )
    (attacker_root / "destruction-receipts" / f"{receipt.receipt_digest}.json").write_bytes(
        receipt.toBytes()
    )
    intents = attacker_root / "destruction-intents"
    (intents / credential_channel_module._prepared_intent_name(revoked)).write_bytes(
        intent.toBytes()
    )
    (intents / credential_channel_module._terminal_intent_name(revoked)).write_bytes(
        receipt.toBytes()
    )
    attacker_broker = CredentialBroker(
        metadata_root=attacker_root,
        secret_provider=lambda _provider: pytest.fail(
            "attacker verifier must not derive credentials"
        ),
        process_capability=object(),
        issuer_id=credential.issuer_id,
        clock=lambda: datetime(2099, 1, 1, tzinfo=timezone.utc),
    )
    forged = credential_channel_module._createCredentialChannelAbsenceVerifier(
        broker=attacker_broker,
    )
    resource_root = (
        journal.event_directory(record.transaction_id).parent / "resources"
    )
    before = {
        path.relative_to(resource_root).as_posix(): path.read_bytes()
        for path in resource_root.rglob("*.json")
    }

    with pytest.raises(
        InvalidAttemptTransition,
        match="registered|broker-bound|verifier.*binding",
    ):
        journal.transition_resource(
            record.transaction_id,
            credential.resource_id,
            CredentialResourceState.DESTROYED,
            destruction_receipt=receipt,
            credential_absence_verifier=forged,
        )

    assert journal.load_resources(record.transaction_id) == (revoked,)
    assert {
        path.relative_to(resource_root).as_posix(): path.read_bytes()
        for path in resource_root.rglob("*.json")
    } == before


@pytest.mark.parametrize("forgery", ["copy", "constructor", "object-new"])
def test_credential_verifier_copy_and_reflection_cannot_replay_terminal_truth(
    tmp_path: Path,
    forgery: str,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    credential = _registered_credential_resource(record)
    journal.register_resources(record.transaction_id, (credential,))
    broker, capability, _fingerprint, clock, _lease = _prepare_credential_broker(
        tmp_path / "credential-store",
        credential,
        journal=journal,
        materialize=False,
    )
    receipt, verifier = _destroy_credential_with_sealed_evidence(
        broker,
        capability,
        clock,
        credential,
    )
    destroyed = journal.load_resources(record.transaction_id)[0]
    verifier_type = type(verifier)
    if forgery == "copy":
        forged = copy.copy(verifier)
    elif forgery == "constructor":
        forged = verifier_type(
            broker=verifier._broker,
            _factory=credential_channel_module._FACTORY_TOKEN,
        )
    else:
        forged = object.__new__(verifier_type)
        for slot in verifier_type.__slots__:
            object.__setattr__(forged, slot, getattr(verifier, slot))
    resource_root = journal.event_directory(record.transaction_id).parent / "resources"
    before = {
        path.relative_to(resource_root).as_posix(): path.read_bytes()
        for path in resource_root.rglob("*.json")
    }

    with pytest.raises(
        InvalidAttemptTransition,
        match="registered|broker-bound|verifier.*binding",
    ):
        journal.transition_resource(
            record.transaction_id,
            credential.resource_id,
            CredentialResourceState.DESTROYED,
            destruction_receipt=receipt,
            credential_absence_verifier=forged,
        )

    assert journal.load_resources(record.transaction_id) == (destroyed,)
    assert {
        path.relative_to(resource_root).as_posix(): path.read_bytes()
        for path in resource_root.rglob("*.json")
    } == before


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("transaction_id", "tx-other", "transaction"),
        ("resource_id", "credential-other", "resource"),
        ("secret_channel_id", "channel-other", "channel"),
        ("issuer_id", "issuer-other", "issuer"),
        ("revocation_generation", 2, "revocation"),
        ("cleanup_locator_digest", "8" * 64, "cleanup"),
        ("destroyed_at", "2020-01-01T00:00:00+00:00", "predates"),
    ],
)
def test_credential_destroyed_edge_exactly_binds_receipt_to_live_resource(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    credential = _registered_credential_resource(record)
    journal.register_resources(record.transaction_id, (credential,))
    revoked = journal.transition_resource(
        record.transaction_id,
        credential.resource_id,
        CredentialResourceState.REVOKED_OR_EXPIRED,
    )
    values = {
        "transaction_id": record.transaction_id,
        "resource_id": credential.resource_id,
        "secret_channel_id": credential.secret_channel_id,
        "issuer_id": credential.issuer_id,
        "revocation_generation": revoked.revocation_generation,
        "cleanup_locator_digest": credential.cleanup_locator_digest,
        "destroyed_at": "2099-01-01T00:00:00+00:00",
    }
    values[field] = value
    receipt = CredentialChannelDestructionReceipt.issue(**values)  # type: ignore[arg-type]

    with pytest.raises(InvalidAttemptTransition, match=message):
        journal.transition_resource(
            record.transaction_id,
            credential.resource_id,
            CredentialResourceState.DESTROYED,
            destruction_receipt=receipt,
        )


def test_credential_destroyed_edge_replays_only_the_exact_receipt(
    tmp_path: Path,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    credential = _registered_credential_resource(record)
    journal.register_resources(record.transaction_id, (credential,))
    broker, process_capability, _fingerprint, clock, _lease = _prepare_credential_broker(
        tmp_path / "credential-store",
        credential,
        journal=journal,
        materialize=False,
    )
    destroyer = broker.channelDestroyer(
        process_capability=process_capability,
        resource=credential,
    )
    revoked = destroyer.revoke(credential)
    receipt, verifier = _destroy_credential_with_sealed_evidence(
        broker,
        process_capability,
        clock,
        revoked,
    )
    destroyed = journal.load_resources(record.transaction_id)[0]

    assert journal.transition_resource(
        record.transaction_id,
        credential.resource_id,
        CredentialResourceState.DESTROYED,
        destruction_receipt=receipt,
        credential_absence_verifier=verifier,
    ) == destroyed
    changed = CredentialChannelDestructionReceipt.issue(
        transaction_id=record.transaction_id,
        resource_id=credential.resource_id,
        secret_channel_id=credential.secret_channel_id,
        issuer_id=credential.issuer_id,
        revocation_generation=revoked.revocation_generation,
        cleanup_locator_digest=credential.cleanup_locator_digest,
        destroyed_at="2099-01-01T00:00:01+00:00",
    )
    with pytest.raises(
        InvalidAttemptTransition,
        match="same resource state|receipt|absence verification",
    ):
        journal.transition_resource(
            record.transaction_id,
            credential.resource_id,
            CredentialResourceState.DESTROYED,
            destruction_receipt=changed,
            credential_absence_verifier=verifier,
        )


def test_credential_recovery_can_revoke_before_issuance_without_fingerprint(
    tmp_path: Path,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    credential = _registered_credential_resource(record)
    journal.register_resources(record.transaction_id, (credential,))
    broker, process_capability, _fingerprint, clock, _lease = _prepare_credential_broker(
        tmp_path / "credential-store",
        credential,
        journal=journal,
        materialize=False,
    )

    with pytest.raises(InvalidAttemptTransition, match="only.*issued"):
        journal.transition_resource(
            record.transaction_id,
            credential.resource_id,
            CredentialResourceState.REVOKED_OR_EXPIRED,
            secret_fingerprint="7" * 64,
        )
    destroyer = broker.channelDestroyer(
        process_capability=process_capability,
        resource=credential,
    )
    revoked = destroyer.revoke(credential)
    receipt, verifier = _destroy_credential_with_sealed_evidence(
        broker,
        process_capability,
        clock,
        revoked,
    )
    destroyed = journal.load_resources(record.transaction_id)[0]

    assert revoked.secret_fingerprint == ""
    assert destroyed.secret_fingerprint == ""


def test_credential_replay_rejects_fingerprint_rewrite(tmp_path: Path) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    credential = _registered_credential_resource(record)
    journal.register_resources(record.transaction_id, (credential,))
    issued = journal.transition_resource(
        record.transaction_id,
        credential.resource_id,
        CredentialResourceState.ISSUED,
        secret_fingerprint="7" * 64,
    )
    event_dir = next(
        path.parent
        for path in (
            journal.event_directory(record.transaction_id).parent / "resources"
        ).glob("*/events/00000000-*.json")
        if "closure" not in path.parts
    )
    issued_path = next(event_dir.glob("00000001-*.json"))
    issued_digest = issued_path.stem.split("-", 1)[1]
    forged = replace(
        issued,
        state=CredentialResourceState.INJECTED,
        secret_fingerprint="8" * 64,
        updated_at="2026-07-16T12:00:02+00:00",
    )
    event = {
        "schema": "galaxy.runtime-resource-event/v1",
        "transaction_id": record.transaction_id,
        "resource_id": credential.resource_id,
        "sequence": 2,
        "previous_event_digest": issued_digest,
        "resource": forged.toDict(),
    }
    raw = json.dumps(
        event,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    (event_dir / f"00000002-{hashlib.sha256(raw).hexdigest()}.json").write_bytes(raw)

    with pytest.raises(JournalCorruption, match="fingerprint"):
        AttemptJournal(journal.root).load_resources(record.transaction_id)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"expires_at": "2026-07-16T12:06:00+00:00"}, "expiry"),
        ({"revocation_generation": 0}, "revocation generation"),
    ],
)
def test_credential_transition_cannot_extend_expiry_or_rewind_revocation_generation(
    tmp_path: Path,
    changes: dict[str, object],
    message: str,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    credential = _registered_credential_resource(record)
    journal.register_resources(record.transaction_id, (credential,))

    with pytest.raises(InvalidAttemptTransition, match=message):
        journal.transition_resource(
            record.transaction_id,
            credential.resource_id,
            CredentialResourceState.ISSUED,
            secret_fingerprint="7" * 64,
            **changes,
        )

    assert journal.load_resources(record.transaction_id) == (credential,)


def test_resource_set_intent_precedes_first_resource_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    resource = _registered_process_resource(record)
    closure_events = (
        journal.event_directory(record.transaction_id).parent
        / "resources"
        / "closure"
        / "events"
    )
    append_resource_event = journal._append_resource_event
    observed_intents: list[dict[str, object]] = []

    def append_after_intent(*args, **kwargs):
        intent_paths = tuple(closure_events.glob("*.json"))
        assert len(intent_paths) == 1
        observed_intents.append(json.loads(intent_paths[0].read_text(encoding="utf-8")))
        return append_resource_event(*args, **kwargs)

    monkeypatch.setattr(journal, "_append_resource_event", append_after_intent)

    assert journal.register_resources(record.transaction_id, (resource,)) == (resource,)
    assert observed_intents[0]["schema"] == "galaxy.runtime-resource-set-intent/v1"
    assert observed_intents[0]["sequence"] == 0
    assert observed_intents[0]["previous_event_digest"] == ""


def test_resource_set_reservation_is_first_authority_and_recovers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    resource = _registered_process_resource(record)

    def canonical_bytes(value: object) -> bytes:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    contract_digest = hashlib.sha256(
        canonical_bytes(
            {
                "schema": "galaxy.runtime-resource-registration-contract/v1",
                "resource": resource.toDict(),
            }
        )
    ).hexdigest()
    intent_raw = canonical_bytes(
        {
            "schema": "galaxy.runtime-resource-set-intent/v1",
            "transaction_id": record.transaction_id,
            "sequence": 0,
            "previous_event_digest": "",
            "resources": [
                {
                    "resource_identity": "model_driver:driver-fence-001",
                    "contract_digest": contract_digest,
                }
            ],
        }
    )
    intent_digest = hashlib.sha256(intent_raw).hexdigest()

    def crash_before_intent(*_args, **_kwargs):
        raise RuntimeError("intent publication crash")

    monkeypatch.setattr(
        journal,
        "_append_resource_set_intent",
        crash_before_intent,
    )
    with pytest.raises(RuntimeError, match="intent publication crash"):
        journal.register_resources(record.transaction_id, (resource,))

    closure = journal.event_directory(record.transaction_id).parent / "resources" / "closure"
    reservation = closure / f"reservation-{intent_digest}"
    assert reservation.is_dir()
    assert tuple(reservation.iterdir()) == ()
    assert not (closure / "events").exists()
    with pytest.raises(IncompleteResourceSet, match="resource set is incomplete"):
        AttemptJournal(journal.root).load_resources(record.transaction_id)

    monkeypatch.undo()
    assert AttemptJournal(journal.root).register_resources(
        record.transaction_id,
        (resource,),
    ) == (resource,)
    assert reservation.is_dir()
    assert tuple(reservation.iterdir()) == ()


def test_changed_manifest_cannot_redefine_reservation_only_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    driver = _registered_process_resource(record)
    sandbox = replace(
        driver,
        resource_id="sandbox-001",
        role=ResourceRole.COMMAND_SANDBOX,
    )
    verifier = replace(
        driver,
        resource_id="verifier-001",
        role=ResourceRole.VERIFIER,
    )

    def crash_before_intent(*_args, **_kwargs):
        raise RuntimeError("reservation-only crash")

    monkeypatch.setattr(
        journal,
        "_append_resource_set_intent",
        crash_before_intent,
    )
    with pytest.raises(RuntimeError, match="reservation-only crash"):
        journal.register_resources(record.transaction_id, (driver, sandbox))
    monkeypatch.undo()
    transaction_root = journal.event_directory(record.transaction_id).parent

    def tree_snapshot() -> tuple[tuple[object, ...], ...]:
        observed: list[tuple[object, ...]] = []
        for path in sorted(transaction_root.rglob("*")):
            info = path.stat(follow_symlinks=False)
            observed.append(
                (
                    path.relative_to(transaction_root).as_posix(),
                    path.is_dir(),
                    info.st_ino,
                    info.st_mtime_ns,
                    b"" if path.is_dir() else path.read_bytes(),
                )
            )
        return tuple(observed)

    before = tree_snapshot()
    with pytest.raises(AttemptCollision, match="durable intent reservation"):
        journal.register_resources(record.transaction_id, (driver, verifier))
    assert tree_snapshot() == before

    assert journal.register_resources(record.transaction_id, (driver, sandbox)) == (
        sandbox,
        driver,
    )


@pytest.mark.parametrize(
    "corruption",
    ["missing", "multiple", "malformed", "wrong-digest", "nonempty"],
)
def test_resource_set_replay_rejects_reservation_corruption(
    tmp_path: Path,
    corruption: str,
) -> None:
    case_root = tmp_path / corruption
    journal = AttemptJournal(case_root / "journals")
    record = journal.create(_record(case_root))
    resource = _registered_process_resource(record)
    journal.register_resources(record.transaction_id, (resource,))
    closure = journal.event_directory(record.transaction_id).parent / "resources" / "closure"
    reservation = next(closure.glob("reservation-*"))

    if corruption == "missing":
        reservation.rmdir()
    elif corruption == "multiple":
        (closure / ("reservation-" + "f" * 64)).mkdir()
    elif corruption == "malformed":
        reservation.rename(closure / "reservation-malformed")
    elif corruption == "wrong-digest":
        reservation.rename(closure / ("reservation-" + "f" * 64))
    else:
        (reservation / "smuggled").write_bytes(b"authority")

    with pytest.raises(JournalCorruption, match="reservation"):
        AttemptJournal(journal.root).load_resources(record.transaction_id)


def test_resource_set_intent_is_canonical_sorted_and_contract_exact(
    tmp_path: Path,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    driver = _registered_process_resource(record)
    sandbox = replace(
        driver,
        resource_id="sandbox-001",
        role=ResourceRole.COMMAND_SANDBOX,
    )

    assert journal.register_resources(
        record.transaction_id,
        (driver, sandbox),
    ) == (sandbox, driver)

    closure_events = (
        journal.event_directory(record.transaction_id).parent
        / "resources"
        / "closure"
        / "events"
    )
    intent_path = next(closure_events.glob("00000000-*.json"))
    intent = json.loads(intent_path.read_text(encoding="utf-8"))

    def canonical_bytes(value: object) -> bytes:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    def contract_digest(resource: RuntimeResourceLease) -> str:
        return hashlib.sha256(
            canonical_bytes(
                {
                    "schema": "galaxy.runtime-resource-registration-contract/v1",
                    "resource": resource.toDict(),
                }
            )
        ).hexdigest()

    assert intent == {
        "schema": "galaxy.runtime-resource-set-intent/v1",
        "transaction_id": record.transaction_id,
        "sequence": 0,
        "previous_event_digest": "",
        "resources": [
            {
                "resource_identity": "command_sandbox:sandbox-001",
                "contract_digest": contract_digest(sandbox),
            },
            {
                "resource_identity": "model_driver:driver-fence-001",
                "contract_digest": contract_digest(driver),
            },
        ],
    }
    assert intent_path.name == (
        "00000000-" + hashlib.sha256(canonical_bytes(intent)).hexdigest() + ".json"
    )
    registration_proofs: list[dict[str, str]] = []
    resource_root = journal.event_directory(record.transaction_id).parent / "resources"
    for registration_path in resource_root.glob("*/events/00000000-*.json"):
        if "closure" in registration_path.parts:
            continue
        registration_raw = registration_path.read_bytes()
        registration = json.loads(registration_raw)
        registration_resource = registration["resource"]
        registration_proofs.append(
            {
                "resource_identity": (
                    f"{registration_resource['role']}:"
                    f"{registration_resource['resource_id']}"
                ),
                "registration_event_digest": hashlib.sha256(
                    registration_raw
                ).hexdigest(),
            }
        )
    registration_proofs.sort(key=lambda item: item["resource_identity"])
    completion_path = next(closure_events.glob("00000001-*.json"))
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    expected_completion = {
        "schema": "galaxy.runtime-resource-set-completion/v1",
        "transaction_id": record.transaction_id,
        "sequence": 1,
        "previous_event_digest": hashlib.sha256(canonical_bytes(intent)).hexdigest(),
        "resources": registration_proofs,
    }
    assert completion == expected_completion
    assert completion_path.name == (
        "00000001-"
        + hashlib.sha256(canonical_bytes(expected_completion)).hexdigest()
        + ".json"
    )

    invalid_record = journal.create(_record(tmp_path, transaction_id="tx-invalid"))
    valid_first = _registered_process_resource(invalid_record)
    invalid_later = replace(
        valid_first,
        resource_id="sandbox-invalid",
        role=ResourceRole.COMMAND_SANDBOX,
        ownership_nonce="9" * 64,
    )
    invalid_resource_root = (
        journal.event_directory(invalid_record.transaction_id).parent / "resources"
    )

    with pytest.raises(InvalidAttemptTransition, match="ownership differs"):
        journal.register_resources(
            invalid_record.transaction_id,
            (valid_first, invalid_later),
        )
    assert not invalid_resource_root.exists()


def test_resource_set_over_count_quota_leaves_no_artifacts(tmp_path: Path) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    driver = _registered_process_resource(record)
    resources = tuple(
        replace(driver, resource_id=f"driver-{index:03d}")
        for index in range(129)
    )
    resource_root = journal.event_directory(record.transaction_id).parent / "resources"

    with pytest.raises(InvalidAttemptTransition, match="resource-set count exceeds quota"):
        journal.register_resources(record.transaction_id, resources)

    assert not resource_root.exists()


def test_resource_set_over_aggregate_quota_leaves_no_artifacts(
    tmp_path: Path,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    driver = _registered_process_resource(record)
    resources = (
        replace(driver, resource_id="driver-large-a", error="a" * 140_000),
        replace(driver, resource_id="driver-large-b", error="b" * 140_000),
    )
    resource_root = journal.event_directory(record.transaction_id).parent / "resources"

    with pytest.raises(
        InvalidAttemptTransition,
        match="resource-set aggregate exceeds quota",
    ):
        journal.register_resources(record.transaction_id, resources)

    assert not resource_root.exists()


def test_resource_set_aggregate_preflight_stops_incrementally(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    driver = _registered_process_resource(record)
    resources = tuple(
        replace(
            driver,
            resource_id=f"driver-{index:03d}",
            error="x" * 100_000,
        )
        for index in range(128)
    )
    resource_root = journal.event_directory(record.transaction_id).parent / "resources"
    event_bytes = journal._resource_event_bytes
    calls = 0

    def counted_event_bytes(*args, **kwargs):
        nonlocal calls
        calls += 1
        return event_bytes(*args, **kwargs)

    monkeypatch.setattr(journal, "_resource_event_bytes", counted_event_bytes)

    with pytest.raises(
        InvalidAttemptTransition,
        match="resource-set aggregate exceeds quota",
    ):
        journal.register_resources(record.transaction_id, resources)

    assert calls < len(resources)
    assert not resource_root.exists()


def test_resource_event_over_quota_leaves_no_artifacts(tmp_path: Path) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    resource = replace(
        _registered_process_resource(record),
        error="x" * 1_100_000,
    )
    resource_root = journal.event_directory(record.transaction_id).parent / "resources"

    with pytest.raises(InvalidAttemptTransition, match="resource event exceeds quota"):
        journal.register_resources(record.transaction_id, (resource,))

    assert not resource_root.exists()


def test_resource_set_over_completion_quota_leaves_no_artifacts(
    tmp_path: Path,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    driver = _registered_process_resource(record)
    resources = tuple(
        replace(
            driver,
            resource_id=f"r{index:03d}" + ("x" * 124),
        )
        for index in range(128)
    )
    resource_root = journal.event_directory(record.transaction_id).parent / "resources"

    with pytest.raises(
        InvalidAttemptTransition,
        match="resource-set completion exceeds quota",
    ):
        journal.register_resources(record.transaction_id, resources)

    assert not resource_root.exists()


def test_late_attempt_cannot_acquire_resource_set_intent(tmp_path: Path) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    rejected = journal.transition(
        record.transaction_id,
        AttemptPhase.REJECTED,
        error="refused before resource registration",
    )
    resource = _registered_process_resource(record)
    resource_root = journal.event_directory(record.transaction_id).parent / "resources"

    with pytest.raises(
        InvalidAttemptTransition,
        match="before the attempt starts",
    ):
        journal.register_resources(rejected.transaction_id, (resource,))

    assert not resource_root.exists()


@pytest.mark.parametrize(
    "premature_evidence",
    ["pid", "process-group", "container", "credential-fingerprint"],
)
def test_registered_resource_refuses_materialized_identity_before_intent(
    tmp_path: Path,
    premature_evidence: str,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    resource = _registered_process_resource(record)
    if premature_evidence == "pid":
        token = processStartToken(os.getpid())
        assert token is not None
        resource = replace(
            resource,
            pid=os.getpid(),
            process_start_token=token,
        )
    elif premature_evidence == "process-group":
        resource = replace(resource, process_group_id=os.getpid())
    elif premature_evidence == "container":
        resource = replace(resource, container_id="7" * 64)
    else:
        resource = replace(
            _registered_credential_resource(record),
            secret_fingerprint="7" * 64,
        )
    resource_root = journal.event_directory(record.transaction_id).parent / "resources"

    with pytest.raises(
        InvalidAttemptTransition,
        match="registered resource violates.*(?:materialized process identity|secret fingerprint)",
    ):
        journal.register_resources(record.transaction_id, (resource,))

    assert not resource_root.exists()


def test_load_resources_holds_transaction_lock_for_consistent_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = AttemptJournal(tmp_path / "journals")
    record = writer.create(_record(tmp_path))
    first = _registered_process_resource(record)
    second = replace(
        first,
        resource_id="sandbox-001",
        role=ResourceRole.COMMAND_SANDBOX,
    )
    initial = writer.register_resources(record.transaction_id, (first, second))
    reader = AttemptJournal(writer.root)
    loaded_first = threading.Event()
    release_reader = threading.Event()
    writer_attempted = threading.Event()
    writer_completed = threading.Event()
    first_identity: list[str] = []
    reader_result: list[tuple[RuntimeResourceLease, ...]] = []
    failures: list[BaseException] = []
    load_chain = reader._load_resource_chain_handle

    @contextmanager
    def independent_outer_permits(_label: str):
        yield

    monkeypatch.setattr(
        attempt_journal_module,
        "_diagnosticPersistenceAccess",
        independent_outer_permits,
    )

    def pause_after_first_chain(*args, **kwargs):
        loaded = load_chain(*args, **kwargs)
        if not loaded_first.is_set():
            first_identity.append(loaded.resource.resource_id)
            loaded_first.set()
            if not release_reader.wait(timeout=5):
                raise AssertionError("reader was not released")
        return loaded

    monkeypatch.setattr(reader, "_load_resource_chain_handle", pause_after_first_chain)

    def read_snapshot() -> None:
        try:
            reader_result.append(reader.load_resources(record.transaction_id))
        except BaseException as exc:  # noqa: BLE001 -- asserted below
            failures.append(exc)

    def write_transitions() -> None:
        try:
            if not loaded_first.wait(timeout=5):
                raise AssertionError("reader did not enter resource replay")
            writer_attempted.set()
            first_read = first_identity[0]
            remaining = next(
                resource.resource_id
                for resource in initial
                if resource.resource_id != first_read
            )
            writer.transition_resource(
                record.transaction_id,
                first_read,
                ProcessResourceState.QUIESCED,
            )
            writer.transition_resource(
                record.transaction_id,
                remaining,
                ProcessResourceState.QUIESCED,
            )
            writer_completed.set()
        except BaseException as exc:  # noqa: BLE001 -- asserted below
            failures.append(exc)

    reader_thread = threading.Thread(target=read_snapshot)
    writer_thread = threading.Thread(target=write_transitions)
    reader_thread.start()
    assert loaded_first.wait(timeout=5)
    writer_thread.start()
    assert writer_attempted.wait(timeout=5)
    assert not writer_completed.wait(timeout=0.2)
    release_reader.set()
    reader_thread.join(timeout=5)
    writer_thread.join(timeout=5)

    assert not reader_thread.is_alive()
    assert not writer_thread.is_alive()
    assert failures == []
    assert len(reader_result) == 1
    assert reader_result[0] == initial


def test_load_resources_refuses_missing_resource_set(tmp_path: Path) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))

    with pytest.raises(MissingResourceSet, match="resource set is not registered"):
        journal.load_resources(record.transaction_id)


def test_resource_events_without_intent_are_corruption(tmp_path: Path) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    resource = _registered_process_resource(record)
    journal._append_resource_event(resource, sequence=0, previous_digest="")

    with pytest.raises(
        JournalCorruption,
        match="resources exist without a resource-set intent",
    ):
        journal.load_resources(record.transaction_id)


def test_load_resources_refuses_incomplete_resource_set_without_exposing_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    driver = _registered_process_resource(record)
    sandbox = replace(
        driver,
        resource_id="sandbox-001",
        role=ResourceRole.COMMAND_SANDBOX,
    )
    append_resource_event = journal._append_resource_event
    appends = 0

    def crash_after_first_registration(*args, **kwargs):
        nonlocal appends
        appends += 1
        if appends == 2:
            raise RuntimeError("registration crash")
        return append_resource_event(*args, **kwargs)

    monkeypatch.setattr(
        journal,
        "_append_resource_event",
        crash_after_first_registration,
    )

    with pytest.raises(RuntimeError, match="registration crash"):
        journal.register_resources(record.transaction_id, (driver, sandbox))
    assert appends == 2
    assert tuple(
        path
        for path in (
            journal.event_directory(record.transaction_id).parent / "resources"
        ).glob("*/events/*.json")
        if "closure" not in path.parts
    )
    with pytest.raises(IncompleteResourceSet, match="resource set is incomplete"):
        journal.load_resources(record.transaction_id)


def test_incomplete_resource_set_cannot_transition_or_enter_running(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    provisional = _record(tmp_path)
    resources = _local_runtime_closure(provisional)
    record = journal.create(_with_runtime_manifest(provisional, resources))
    driver = next(
        resource for resource in resources if resource.role is ResourceRole.MODEL_DRIVER
    )
    append_resource_event = journal._append_resource_event
    appends = 0

    def crash_after_first_registration(*args, **kwargs):
        nonlocal appends
        appends += 1
        if appends == 2:
            raise RuntimeError("registration crash")
        return append_resource_event(*args, **kwargs)

    monkeypatch.setattr(
        journal,
        "_append_resource_event",
        crash_after_first_registration,
    )
    with pytest.raises(RuntimeError, match="registration crash"):
        journal.register_resources(record.transaction_id, resources)

    with pytest.raises(IncompleteResourceSet, match="resource set is incomplete"):
        journal.transition_resource(
            record.transaction_id,
            driver.resource_id,
            ProcessResourceState.QUIESCED,
        )
    with pytest.raises(IncompleteResourceSet, match="resource set is incomplete"):
        journal.transition(
            record.transaction_id,
            AttemptPhase.RUNNING,
            resource_lease_ids=tuple(
                f"{resource.role.value}:{resource.resource_id}"
                for resource in sorted(
                    resources,
                    key=lambda item: f"{item.role.value}:{item.resource_id}",
                )
            ),
        )


def test_incomplete_resource_set_remains_discoverable_without_prefix_exposure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    driver = _registered_process_resource(record)
    sandbox = replace(
        driver,
        resource_id="sandbox-001",
        role=ResourceRole.COMMAND_SANDBOX,
    )
    append_resource = journal._append_resource_event
    calls = 0

    def crash_after_first_resource(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("registration crash")
        return append_resource(*args, **kwargs)

    monkeypatch.setattr(journal, "_append_resource_event", crash_after_first_resource)
    with pytest.raises(RuntimeError, match="registration crash"):
        journal.register_resources(record.transaction_id, (driver, sandbox))
    monkeypatch.undo()

    assert AttemptJournal(journal.root).pending_recovery() == (record,)
    with pytest.raises(IncompleteResourceSet, match="resource set is incomplete"):
        AttemptJournal(journal.root).load_resources(record.transaction_id)


def test_identical_resource_manifest_recovers_every_registration_crash_prefix(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    child_source = r"""
import os
import sys
from dataclasses import replace
from pathlib import Path

from platform_core.runtime.attempt_journal import AttemptJournal
from platform_core.runtime.candidate import (
    ProcessResourceState,
    ResourceRole,
    RuntimeResourceLease,
)

journal = AttemptJournal(Path(sys.argv[1]))
record = journal.load(sys.argv[2])
driver = RuntimeResourceLease(
    resource_id="driver-fence-001",
    run_id="run-001",
    transaction_id=record.transaction_id,
    controller_scope_id="controller-001",
    role=ResourceRole.MODEL_DRIVER,
    backend="local",
    ownership_nonce=record.ownership_nonce,
    state=ProcessResourceState.REGISTERED,
    cleanup_locator_digest="2" * 64,
    pid=0,
    process_group_id=0,
    container_id="",
    image_digest="",
    entrypoint_digest="3" * 64,
    mount_digest="4" * 64,
    environment_digest="5" * 64,
    security_profile_digest="6" * 64,
    created_at=record.created_at,
    updated_at=record.updated_at,
)
resources = (
    driver,
    replace(driver, resource_id="sandbox-001", role=ResourceRole.COMMAND_SANDBOX),
    replace(driver, resource_id="verifier-001", role=ResourceRole.VERIFIER),
)
failpoint = sys.argv[3]
if failpoint == "intent":
    original = journal._append_resource_set_intent
    def append_intent(*args, **kwargs):
        result = original(*args, **kwargs)
        os._exit(91)
    journal._append_resource_set_intent = append_intent
elif failpoint.startswith("registration-"):
    target = int(failpoint.rsplit("-", 1)[1])
    original = journal._append_resource_event
    calls = 0
    def append_registration(*args, **kwargs):
        global calls
        calls += 1
        result = original(*args, **kwargs)
        if calls == target:
            os._exit(91)
        return result
    journal._append_resource_event = append_registration
else:
    original = journal._append_resource_set_completion
    def append_completion(*args, **kwargs):
        result = original(*args, **kwargs)
        os._exit(91)
    journal._append_resource_set_completion = append_completion
journal.register_resources(record.transaction_id, resources)
raise SystemExit(92)
"""

    for index, failpoint in enumerate(
        (
            "intent",
            "registration-1",
            "registration-2",
            "registration-3",
            "completion-before-response",
        )
    ):
        case_root = tmp_path / f"case-{index}"
        journal = AttemptJournal(case_root / "journals")
        record = journal.create(_record(case_root, transaction_id=f"tx-crash-{index}"))
        driver = _registered_process_resource(record)
        resources = (
            driver,
            replace(
                driver,
                resource_id="sandbox-001",
                role=ResourceRole.COMMAND_SANDBOX,
            ),
            replace(
                driver,
                resource_id="verifier-001",
                role=ResourceRole.VERIFIER,
            ),
        )
        expected = tuple(sorted(resources, key=lambda item: f"{item.role.value}:{item.resource_id}"))
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(repository_root)
        crashed = subprocess.run(
            [
                sys.executable,
                "-c",
                child_source,
                str(journal.root),
                record.transaction_id,
                failpoint,
            ],
            cwd=repository_root,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        assert crashed.returncode == 91, crashed.stderr
        reopened = AttemptJournal(journal.root)
        if failpoint == "completion-before-response":
            assert reopened.load_resources(record.transaction_id) == expected
        else:
            with pytest.raises(IncompleteResourceSet):
                reopened.load_resources(record.transaction_id)
        before_retry = {
            path.relative_to(journal.root).as_posix(): path.read_bytes()
            for path in journal.root.rglob("*.json")
        }

        assert reopened.register_resources(record.transaction_id, resources) == expected
        completed = {
            path.relative_to(journal.root).as_posix(): path.read_bytes()
            for path in journal.root.rglob("*.json")
        }
        assert before_retry.items() <= completed.items()
        assert reopened.register_resources(record.transaction_id, resources) == expected
        assert {
            path.relative_to(journal.root).as_posix(): path.read_bytes()
            for path in journal.root.rglob("*.json")
        } == completed


@pytest.mark.parametrize(
    "target",
    ["intent", "registration-1", "registration-2", "registration-3", "completion"],
)
@pytest.mark.parametrize(
    "death_edge",
    [
        "after-directory",
        "empty-temp",
        "partial-temp",
        "full-temp",
        "final-before-return",
    ],
)
def test_resource_manifest_recovers_death_inside_native_publication(
    tmp_path: Path,
    target: str,
    death_edge: str,
) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    driver = _registered_process_resource(record)
    resources = (
        driver,
        replace(
            driver,
            resource_id="sandbox-001",
            role=ResourceRole.COMMAND_SANDBOX,
        ),
        replace(
            driver,
            resource_id="verifier-001",
            role=ResourceRole.VERIFIER,
        ),
    )
    expected = tuple(
        sorted(resources, key=lambda item: f"{item.role.value}:{item.resource_id}")
    )
    target_index = {
        "intent": 1,
        "registration-1": 2,
        "registration-2": 3,
        "registration-3": 4,
        "completion": 5,
    }[target]
    child_source = r'''
import os
import sys
from dataclasses import replace
from pathlib import Path

import platform_core.core.fsio as fsio
from platform_core.runtime.attempt_journal import AttemptJournal
from platform_core.runtime.candidate import (
    ProcessResourceState,
    ResourceRole,
    RuntimeResourceLease,
)

journal = AttemptJournal(Path(sys.argv[1]))
record = journal.load(sys.argv[2])
target_index = int(sys.argv[3])
death_edge = sys.argv[4]
driver = RuntimeResourceLease(
    resource_id="driver-fence-001",
    run_id="run-001",
    transaction_id=record.transaction_id,
    controller_scope_id="controller-001",
    role=ResourceRole.MODEL_DRIVER,
    backend="local",
    ownership_nonce=record.ownership_nonce,
    state=ProcessResourceState.REGISTERED,
    cleanup_locator_digest="2" * 64,
    pid=0,
    process_group_id=0,
    container_id="",
    image_digest="",
    entrypoint_digest="3" * 64,
    mount_digest="4" * 64,
    environment_digest="5" * 64,
    security_profile_digest="6" * 64,
    created_at=record.created_at,
    updated_at=record.updated_at,
)
resources = (
    driver,
    replace(driver, resource_id="sandbox-001", role=ResourceRole.COMMAND_SANDBOX),
    replace(driver, resource_id="verifier-001", role=ResourceRole.VERIFIER),
)
original_reconcile = fsio.NativeDirectoryHandle.reconcileCreateOnlyFile
calls = 0

def crash_in_publication(directory, name, payload):
    global calls
    calls += 1
    if calls != target_index:
        return original_reconcile(directory, name, payload)
    if death_edge == "after-directory":
        os._exit(91)
    if death_edge == "final-before-return":
        original_reconcile(directory, name, payload)
        os._exit(91)

    if os.name == "nt":
        if death_edge in {"empty-temp", "partial-temp"}:
            original_write = fsio._winWriteAll

            def crash_write(handle, observed, **_kwargs):
                if death_edge == "partial-temp":
                    original_write(
                        handle,
                        observed[: max(1, len(observed) // 2)],
                        flush=True,
                    )
                os._exit(91)

            fsio._winWriteAll = crash_write
        else:
            def crash_rename(*_args, **_kwargs):
                os._exit(91)

            fsio._winRenameRelative = crash_rename
    else:
        if death_edge in {"empty-temp", "partial-temp"}:
            original_write = fsio._writeAll

            def crash_write(handle, observed):
                if death_edge == "partial-temp":
                    original_write(handle, observed[: max(1, len(observed) // 2)])
                os._exit(91)

            fsio._writeAll = crash_write
        else:
            def crash_rename(*_args, **_kwargs):
                os._exit(91)

            fsio._posixRenameNoReplace = crash_rename
    return original_reconcile(directory, name, payload)

fsio.NativeDirectoryHandle.reconcileCreateOnlyFile = crash_in_publication
journal.register_resources(record.transaction_id, resources)
raise SystemExit(92)
'''
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(repository_root)
    crashed = subprocess.run(
        [
            sys.executable,
            "-c",
            child_source,
            str(journal.root),
            record.transaction_id,
            str(target_index),
            death_edge,
        ],
        cwd=repository_root,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert crashed.returncode == 91, crashed.stderr
    reopened = AttemptJournal(journal.root)
    transaction_root = journal.event_directory(record.transaction_id).parent

    def tree_snapshot() -> tuple[tuple[object, ...], ...]:
        from platform_core.core.fsio import openNativeDirectory

        observed: list[tuple[object, ...]] = []

        def walk(directory, prefix: str) -> None:
            for entry in sorted(directory.listEntries(), key=lambda item: item.name):
                relative = f"{prefix}/{entry.name}" if prefix else entry.name
                identity = entry.identity
                if identity.is_directory:
                    observed.append(
                        (
                            relative,
                            True,
                            identity.volume_id,
                            identity.file_id,
                            identity.write_time,
                            identity.change_time,
                            b"",
                        )
                    )
                    with directory.openDirectory(
                        entry.name,
                        expected=identity,
                    ) as child:
                        walk(child, relative)
                else:
                    payload = directory.readFile(
                        entry.name,
                        max_bytes=4 * 1024 * 1024,
                        expected=identity,
                    )
                    observed.append(
                        (
                            relative,
                            False,
                            identity.volume_id,
                            identity.file_id,
                            identity.write_time,
                            identity.change_time,
                            payload,
                        )
                    )

        with openNativeDirectory(transaction_root) as root:
            walk(root, "")
        return tuple(observed)

    changed = (
        driver,
        resources[1],
        replace(resources[2], mount_digest="9" * 64),
    )
    before_changed_retry = tree_snapshot()
    with pytest.raises(AttemptCollision, match="durable intent reservation"):
        reopened.register_resources(record.transaction_id, changed)
    assert tree_snapshot() == before_changed_retry

    if death_edge == "final-before-return" and target == "completion":
        assert reopened.load_resources(record.transaction_id) == expected
    else:
        with pytest.raises(IncompleteResourceSet):
            reopened.load_resources(record.transaction_id)

    assert reopened.register_resources(record.transaction_id, resources) == expected
    assert reopened.load_resources(record.transaction_id) == expected
    assert not tuple(transaction_root.rglob(".galaxy-publish-v2-*.tmp"))
    completed = tree_snapshot()
    assert reopened.register_resources(record.transaction_id, resources) == expected
    assert tree_snapshot() == completed

    resource_root = transaction_root / "resources"
    reservations = tuple((resource_root / "closure").glob("reservation-*"))
    assert len(reservations) == 1
    assert reservations[0].is_dir()
    assert not tuple(reservations[0].iterdir())
    closure_events = resource_root / "closure" / "events"
    assert len(tuple(closure_events.glob("00000000-*.json"))) == 1
    assert len(tuple(closure_events.glob("00000001-*.json"))) == 1
    registration_events = tuple(
        path
        for path in resource_root.glob("*/events/00000000-*.json")
        if "closure" not in path.parts
    )
    assert len(registration_events) == len(expected)


@pytest.mark.parametrize(
    "debris_kind",
    ["malformed", "wrong-destination", "complete-digest-mismatch"],
)
def test_resource_intent_replay_rejects_structurally_invalid_publication_debris(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    debris_kind: str,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    resource = _registered_process_resource(record)
    expected, raw, event_dir = _prepare_pending_resource_intent(
        journal,
        record,
        (resource,),
        monkeypatch,
    )
    digest = hashlib.sha256(raw).hexdigest()
    expected_name = f"00000000-{digest}.json"
    if debris_kind == "malformed":
        temporary = event_dir / ".galaxy-publish-not-authentic.tmp"
        observed = b"do-not-delete"
    elif debris_kind == "wrong-destination":
        temporary = event_dir / fsio._nativePublishTempName("other.json", raw)
        observed = raw[:17]
    else:
        temporary = event_dir / fsio._nativePublishTempName(expected_name, raw)
        observed = b"x" * len(raw)
    temporary.write_bytes(observed)

    with fsio.openNativeDirectory(event_dir) as directory:
        entry = directory._entry(temporary.name)
        before = (entry.identity, directory.readFile(
            entry.name,
            max_bytes=max(len(raw), len(observed)),
            expected=entry.identity,
        ))

    with pytest.raises(JournalCorruption, match="publication|artifact"):
        journal.load_resources(record.transaction_id)
    with pytest.raises(JournalCorruption, match="publication|artifact"):
        journal.register_resources(record.transaction_id, (resource,))

    with fsio.openNativeDirectory(event_dir) as directory:
        entry = directory._entry(temporary.name)
        after = (entry.identity, directory.readFile(
            entry.name,
            max_bytes=max(len(raw), len(observed)),
            expected=entry.identity,
        ))
    assert after == before
    assert expected == (resource,)
    assert not (event_dir / expected_name).exists()


def test_resource_intent_writer_rejects_nonprefix_partial_debris_untouched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    resource = _registered_process_resource(record)
    _expected, raw, event_dir = _prepare_pending_resource_intent(
        journal,
        record,
        (resource,),
        monkeypatch,
    )
    digest = hashlib.sha256(raw).hexdigest()
    expected_name = f"00000000-{digest}.json"
    temporary = event_dir / fsio._nativePublishTempName(expected_name, raw)
    temporary.write_bytes(b"not-a-prefix")
    before = temporary.read_bytes()

    with pytest.raises(IncompleteResourceSet):
        journal.load_resources(record.transaction_id)
    with pytest.raises(JournalCorruption, match="differs from expected event"):
        journal.register_resources(record.transaction_id, (resource,))

    assert temporary.read_bytes() == before
    assert not (event_dir / expected_name).exists()


@pytest.mark.parametrize("unsafe_kind", ["directory", "hard-link", "symlink"])
def test_resource_intent_replay_rejects_unsafe_publication_debris_untouched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unsafe_kind: str,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    resource = _registered_process_resource(record)
    _expected, raw, event_dir = _prepare_pending_resource_intent(
        journal,
        record,
        (resource,),
        monkeypatch,
    )
    digest = hashlib.sha256(raw).hexdigest()
    expected_name = f"00000000-{digest}.json"
    unsafe = event_dir / fsio._nativePublishTempName(expected_name, raw)
    if unsafe_kind == "directory":
        unsafe.mkdir()
    elif unsafe_kind == "hard-link":
        unsafe.write_bytes(raw[:17])
        os.link(unsafe, tmp_path / "publisher-alias.bin")
    else:
        target = tmp_path / "publisher-target.bin"
        target.write_bytes(raw[:17])
        try:
            unsafe.symlink_to(target)
        except OSError as exc:
            pytest.skip(f"file symlink creation is unavailable: {exc}")

    with pytest.raises(JournalCorruption, match="reparse|unsafe"):
        journal.load_resources(record.transaction_id)
    with pytest.raises(JournalCorruption, match="reparse|unsafe"):
        journal.register_resources(record.transaction_id, (resource,))

    assert unsafe.exists() or unsafe.is_symlink()
    assert not (event_dir / expected_name).exists()


def test_resource_intent_replay_rejects_ambiguous_publication_debris_untouched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    resource = _registered_process_resource(record)
    _expected, raw, event_dir = _prepare_pending_resource_intent(
        journal,
        record,
        (resource,),
        monkeypatch,
    )
    digest = hashlib.sha256(raw).hexdigest()
    expected_name = f"00000000-{digest}.json"
    temporaries = tuple(
        event_dir / fsio._nativePublishTempName(expected_name, raw)
        for _ in range(2)
    )
    for index, temporary in enumerate(temporaries, start=1):
        temporary.write_bytes(raw[: index + 3])
    before = tuple(temporary.read_bytes() for temporary in temporaries)

    with pytest.raises(JournalCorruption, match="ambiguous"):
        journal.load_resources(record.transaction_id)
    with pytest.raises(JournalCorruption, match="ambiguous"):
        journal.register_resources(record.transaction_id, (resource,))

    assert tuple(temporary.read_bytes() for temporary in temporaries) == before
    assert not (event_dir / expected_name).exists()


@pytest.mark.parametrize("owner_state", ["active", "unverifiable"])
def test_resource_intent_replay_rejects_live_or_unverifiable_publication_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    owner_state: str,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    resource = _registered_process_resource(record)
    _expected, raw, event_dir = _prepare_pending_resource_intent(
        journal,
        record,
        (resource,),
        monkeypatch,
    )
    digest = hashlib.sha256(raw).hexdigest()
    expected_name = f"00000000-{digest}.json"
    temporary_name = fsio._nativePublishTempName(expected_name, raw)
    owner_context = nullcontext()
    if owner_state == "active":
        owner_context = fsio._activeNativePublication(temporary_name)
    else:
        temporary_name = temporary_name.replace(
            f"-{os.getpid()}-{fsio._NATIVE_PROCESS_START_TOKEN}-",
            f"-424242-{'a' * 32}-",
            1,
        )

        def unavailable(_pid: int) -> str | None:
            raise OSError("birth identity unavailable")

        monkeypatch.setattr(fsio, "_nativeProcessStartToken", unavailable)
    temporary = event_dir / temporary_name
    temporary.write_bytes(raw[:17])

    with owner_context:
        with pytest.raises(JournalCorruption, match="owner is still live"):
            journal.load_resources(record.transaction_id)
        with pytest.raises(JournalCorruption, match="owner is still live"):
            journal.register_resources(record.transaction_id, (resource,))

    assert temporary.read_bytes() == raw[:17]
    assert not (event_dir / expected_name).exists()


def test_resource_final_with_matching_dead_debris_is_read_only_then_cleaned(
    tmp_path: Path,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    resource = _registered_process_resource(record)
    expected = journal.register_resources(record.transaction_id, (resource,))
    closure_events = (
        journal.event_directory(record.transaction_id).parent
        / "resources"
        / "closure"
        / "events"
    )
    intent_path = next(closure_events.glob("00000000-*.json"))
    raw = intent_path.read_bytes()
    temporary = closure_events / fsio._nativePublishTempName(intent_path.name, raw)
    temporary.write_bytes(raw[:17])

    with fsio.openNativeDirectory(closure_events) as directory:
        final_before = directory._entry(intent_path.name).identity
        temporary_before = directory._entry(temporary.name).identity
    assert journal.load_resources(record.transaction_id) == expected
    with fsio.openNativeDirectory(closure_events) as directory:
        assert directory._entry(intent_path.name).identity == final_before
        assert directory._entry(temporary.name).identity == temporary_before

    assert journal.register_resources(record.transaction_id, (resource,)) == expected
    assert not temporary.exists()
    with fsio.openNativeDirectory(closure_events) as directory:
        cleaned_final = directory._entry(intent_path.name).identity
    assert cleaned_final == final_before
    assert journal.register_resources(record.transaction_id, (resource,)) == expected
    with fsio.openNativeDirectory(closure_events) as directory:
        assert directory._entry(intent_path.name).identity == cleaned_final


@pytest.mark.parametrize("sequence", [0, 1], ids=["intent", "completion"])
def test_resource_closure_publication_debris_enforces_per_sequence_quota(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sequence: int,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    resource = _registered_process_resource(record)
    if sequence == 0:
        _expected, _raw, event_dir = _prepare_pending_resource_intent(
            journal,
            record,
            (resource,),
            monkeypatch,
        )
        oversized = b"x" * (
            attempt_journal_module._MAX_RESOURCE_SET_INTENT_BYTES + 1
        )
    else:
        def crash_before_registration(*_args, **_kwargs):
            raise RuntimeError("registration crash")

        with monkeypatch.context() as patch:
            patch.setattr(journal, "_append_resource_event", crash_before_registration)
            with pytest.raises(RuntimeError, match="registration crash"):
                journal.register_resources(record.transaction_id, (resource,))
        event_dir = (
            journal.event_directory(record.transaction_id).parent
            / "resources"
            / "closure"
            / "events"
        )
        oversized = b"x" * (
            attempt_journal_module._MAX_RESOURCE_SET_COMPLETION_BYTES + 1
        )
    digest = hashlib.sha256(oversized).hexdigest()
    destination = f"{sequence:08d}-{digest}.json"
    temporary = event_dir / fsio._nativePublishTempName(destination, oversized)
    temporary.write_bytes(b"")

    with pytest.raises(JournalCorruption, match="quota|unsafe"):
        journal.load_resources(record.transaction_id)

    assert temporary.exists()
    assert not (event_dir / destination).exists()


@pytest.mark.parametrize("crash_point", ["intent", "partial-prefix"])
def test_different_manifest_cannot_redefine_intent_or_partial_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    crash_point: str,
) -> None:
    case_root = tmp_path / crash_point
    journal = AttemptJournal(case_root / "journals")
    record = journal.create(_record(case_root))
    driver = _registered_process_resource(record)
    sandbox = replace(
        driver,
        resource_id="sandbox-001",
        role=ResourceRole.COMMAND_SANDBOX,
    )
    verifier = replace(
        driver,
        resource_id="verifier-001",
        role=ResourceRole.VERIFIER,
    )
    if crash_point == "intent":
        append_intent = journal._append_resource_set_intent

        def crash_after_intent(*args, **kwargs):
            append_intent(*args, **kwargs)
            raise RuntimeError("intent crash")

        monkeypatch.setattr(
            journal,
            "_append_resource_set_intent",
            crash_after_intent,
        )
    else:
        append_resource = journal._append_resource_event

        def crash_after_first_resource(*args, **kwargs):
            append_resource(*args, **kwargs)
            raise RuntimeError("partial-prefix crash")

        monkeypatch.setattr(
            journal,
            "_append_resource_event",
            crash_after_first_resource,
        )
    with pytest.raises(RuntimeError, match="crash"):
        journal.register_resources(record.transaction_id, (driver, sandbox))
    monkeypatch.undo()
    before = {
        path.relative_to(journal.root).as_posix(): path.read_bytes()
        for path in journal.root.rglob("*.json")
    }

    with pytest.raises(AttemptCollision, match="manifest differs from durable intent"):
        journal.register_resources(record.transaction_id, (driver, verifier))

    assert {
        path.relative_to(journal.root).as_posix(): path.read_bytes()
        for path in journal.root.rglob("*.json")
    } == before
    with pytest.raises(IncompleteResourceSet):
        journal.load_resources(record.transaction_id)


def test_identical_manifest_rejects_mutated_partial_prefix_as_corruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    driver = _registered_process_resource(record)
    sandbox = replace(
        driver,
        resource_id="sandbox-001",
        role=ResourceRole.COMMAND_SANDBOX,
    )
    append_resource = journal._append_resource_event

    def crash_after_first_resource(*args, **kwargs):
        append_resource(*args, **kwargs)
        raise RuntimeError("partial-prefix crash")

    monkeypatch.setattr(journal, "_append_resource_event", crash_after_first_resource)
    with pytest.raises(RuntimeError, match="partial-prefix crash"):
        journal.register_resources(record.transaction_id, (driver, sandbox))
    monkeypatch.undo()

    resource_root = journal.event_directory(record.transaction_id).parent / "resources"
    registration_path = next(
        path
        for path in resource_root.glob("*/events/00000000-*.json")
        if "closure" not in path.parts
    )
    event = json.loads(registration_path.read_text(encoding="utf-8"))
    event["resource"]["mount_digest"] = "9" * 64
    raw = json.dumps(
        event,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    replacement = registration_path.with_name(
        "00000000-" + hashlib.sha256(raw).hexdigest() + ".json"
    )
    registration_path.unlink()
    replacement.write_bytes(raw)
    before = {
        path.relative_to(journal.root).as_posix(): path.read_bytes()
        for path in journal.root.rglob("*.json")
    }

    with pytest.raises(JournalCorruption, match="prefix differs from durable intent"):
        journal.register_resources(record.transaction_id, (driver, sandbox))

    assert {
        path.relative_to(journal.root).as_posix(): path.read_bytes()
        for path in journal.root.rglob("*.json")
    } == before


def test_completed_resource_set_replay_requires_exact_membership_and_digests(
    tmp_path: Path,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    driver = _registered_process_resource(record)
    sandbox = replace(
        driver,
        resource_id="sandbox-001",
        role=ResourceRole.COMMAND_SANDBOX,
    )
    initial_manifest = (driver, sandbox)
    journal.register_resources(record.transaction_id, initial_manifest)
    quiesced_driver = journal.transition_resource(
        record.transaction_id,
        driver.resource_id,
        ProcessResourceState.QUIESCED,
    )
    before_replay = {
        path.relative_to(journal.root).as_posix(): path.read_bytes()
        for path in journal.root.rglob("*.json")
    }

    replayed = journal.register_resources(
        record.transaction_id,
        tuple(reversed(initial_manifest)),
    )

    assert replayed == (sandbox, quiesced_driver)
    assert {
        path.relative_to(journal.root).as_posix(): path.read_bytes()
        for path in journal.root.rglob("*.json")
    } == before_replay
    with pytest.raises(AttemptCollision, match="manifest differs from durable intent"):
        journal.register_resources(
            record.transaction_id,
            (driver, replace(sandbox, mount_digest="9" * 64)),
        )


def test_identical_retry_after_resource_transition_returns_current_without_rewrite(
    tmp_path: Path,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    driver = _registered_process_resource(record)
    journal.register_resources(record.transaction_id, (driver,))
    current = journal.transition_resource(
        record.transaction_id,
        driver.resource_id,
        ProcessResourceState.QUIESCED,
    )
    before = {
        path.relative_to(journal.root).as_posix(): path.read_bytes()
        for path in journal.root.rglob("*.json")
    }

    assert journal.register_resources(record.transaction_id, (driver,)) == (current,)
    assert {
        path.relative_to(journal.root).as_posix(): path.read_bytes()
        for path in journal.root.rglob("*.json")
    } == before


def test_empty_resource_set_is_explicit_complete_and_idempotent(tmp_path: Path) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))

    assert journal.register_resources(record.transaction_id, ()) == ()
    assert AttemptJournal(journal.root).load_resources(record.transaction_id) == ()
    closure_events = (
        journal.event_directory(record.transaction_id).parent
        / "resources"
        / "closure"
        / "events"
    )
    intent_path = next(closure_events.glob("00000000-*.json"))
    completion_path = next(closure_events.glob("00000001-*.json"))
    assert json.loads(intent_path.read_text(encoding="utf-8"))["resources"] == []
    assert json.loads(completion_path.read_text(encoding="utf-8"))["resources"] == []
    before = {
        path.relative_to(journal.root).as_posix(): path.read_bytes()
        for path in journal.root.rglob("*.json")
    }

    assert journal.register_resources(record.transaction_id, ()) == ()
    assert {
        path.relative_to(journal.root).as_posix(): path.read_bytes()
        for path in journal.root.rglob("*.json")
    } == before


def test_empty_resource_set_cannot_be_widened_or_enter_running(tmp_path: Path) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    journal.register_resources(record.transaction_id, ())
    driver = _registered_process_resource(record)

    with pytest.raises(AttemptCollision, match="manifest differs from durable intent"):
        journal.register_resources(record.transaction_id, (driver,))
    with pytest.raises(InvalidAttemptTransition, match="admission manifest|non-empty"):
        journal.transition(
            record.transaction_id,
            AttemptPhase.RUNNING,
            resource_lease_ids=(),
        )
    assert journal.load(record.transaction_id).phase is AttemptPhase.LEASE_REGISTERED
    assert journal.load_resources(record.transaction_id) == ()


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown-root-key",
        "unknown-entry-key",
        "unknown-role",
        "unknown-backend",
        "wrong-role-backend",
        "missing-dependency",
        "dependency-cycle",
        "duplicate-role",
        "missing-watchdog",
        "driver-without-watchdog-dependency",
    ],
)
def test_attempt_admission_rejects_nonclosed_runtime_manifest(
    tmp_path: Path,
    mutation: str,
) -> None:
    record = _record(tmp_path)
    resources = _local_runtime_closure(record)
    watchdog, driver, _parser, _verifier = resources
    valid = _with_runtime_manifest(record, resources)
    payload = json.loads(valid.runtime_resource_manifest_json)
    entries = {
        entry["resource_identity"].split(":", 1)[0]: entry
        for entry in payload["resources"]
    }
    if mutation == "unknown-root-key":
        payload["authority"] = "caller"
    elif mutation == "unknown-entry-key":
        entries["authority_watchdog"]["authority"] = "caller"
    elif mutation == "unknown-role":
        entries["authority_watchdog"]["resource_identity"] = "shell:watchdog-001"
    elif mutation == "unknown-backend":
        entries["authority_watchdog"]["backend"] = "clone"
    elif mutation == "wrong-role-backend":
        entries["candidate_parser"]["backend"] = "local"
    elif mutation == "missing-dependency":
        entries["model_driver"]["depends_on"] = ["broker:missing-001"]
    elif mutation == "dependency-cycle":
        entries["authority_watchdog"]["depends_on"] = [
            "model_driver:driver-fence-001"
        ]
    elif mutation == "duplicate-role":
        duplicate = dict(entries["verifier"])
        duplicate["resource_identity"] = "verifier:verifier-two"
        payload["resources"].append(duplicate)
        payload["resources"].sort(key=lambda entry: entry["resource_identity"])
    elif mutation == "missing-watchdog":
        payload["resources"] = [
            entry
            for entry in payload["resources"]
            if not entry["resource_identity"].startswith("authority_watchdog:")
        ]
    else:
        entries["model_driver"]["depends_on"] = []
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )

    with pytest.raises(ValueError, match="runtime resource manifest"):
        replace(
            record,
            runtime_resource_manifest_json=raw,
            runtime_resource_manifest_digest=hashlib.sha256(
                raw.encode("utf-8")
            ).hexdigest(),
        )


def test_public_runtime_manifest_validator_uses_required_canonical_closure(
    tmp_path: Path,
) -> None:
    valid = _with_runtime_manifest(
        _record(tmp_path),
        _local_runtime_closure(_record(tmp_path)),
    )

    validateRuntimeResourceManifest(
        valid.runtime_resource_manifest_json,
        valid.runtime_resource_manifest_digest,
        runner_kind="local",
    )
    with pytest.raises(ValueError, match="runtime resource manifest is required"):
        validateRuntimeResourceManifest("", "", runner_kind="local")


def test_runtime_manifest_byte_quota_is_checked_before_json_parsing(
    tmp_path: Path,
) -> None:
    record = _record(tmp_path)
    oversized = json.dumps("é" * 33_000, ensure_ascii=False)

    with pytest.raises(ValueError, match="manifest.*byte quota"):
        replace(
            record,
            runtime_resource_manifest_json=oversized,
            runtime_resource_manifest_digest=hashlib.sha256(
                oversized.encode("utf-8")
            ).hexdigest(),
        )


def test_docker_manifest_refuses_credential_dependencies(
    tmp_path: Path,
) -> None:
    record = replace(_record(tmp_path), runner_kind="docker")
    valid = _with_runtime_manifest(record, _docker_runtime_closure(record))
    payload = json.loads(valid.runtime_resource_manifest_json)
    credential = next(
        entry
        for entry in payload["resources"]
        if entry["resource_identity"].startswith("credential_lease:")
    )
    credential["depends_on"] = ["authority_watchdog:watchdog-001"]
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )

    with pytest.raises(ValueError, match="credential.*depend"):
        replace(
            record,
            runtime_resource_manifest_json=raw,
            runtime_resource_manifest_digest=hashlib.sha256(
                raw.encode("utf-8")
            ).hexdigest(),
        )


def test_manifest_registration_mismatch_refuses_before_resource_subtree_write(
    tmp_path: Path,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    provisional = _record(tmp_path)
    resources = _local_runtime_closure(provisional)
    driver = next(resource for resource in resources if resource.role is ResourceRole.MODEL_DRIVER)
    record = journal.create(_with_runtime_manifest(provisional, resources))

    with pytest.raises(InvalidAttemptTransition, match="admission manifest"):
        journal.register_resources(record.transaction_id, (driver,))

    assert not (
        journal.event_directory(record.transaction_id).parent / "resources"
    ).exists()


def test_manifestless_singleton_driver_closure_cannot_enter_running(
    tmp_path: Path,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    driver = _registered_process_resource(record)
    journal.register_resources(record.transaction_id, (driver,))

    with pytest.raises(InvalidAttemptTransition, match="admission manifest"):
        journal.transition(
            record.transaction_id,
            AttemptPhase.RUNNING,
            resource_lease_ids=("model_driver:driver-fence-001",),
        )

    assert journal.load(record.transaction_id).phase is AttemptPhase.LEASE_REGISTERED


def test_dependency_closed_local_manifest_enters_running_with_exact_full_closure(
    tmp_path: Path,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    provisional = _record(tmp_path)
    resources = _local_runtime_closure(provisional)
    record = journal.create(_with_runtime_manifest(provisional, resources))
    registered = journal.register_resources(record.transaction_id, tuple(reversed(resources)))
    identities = tuple(
        f"{resource.role.value}:{resource.resource_id}" for resource in registered
    )

    running = journal.transition(
        record.transaction_id,
        AttemptPhase.RUNNING,
        resource_lease_ids=identities,
    )

    assert running.resource_lease_ids == (
        "authority_watchdog:watchdog-001",
        "candidate_parser:parser-001",
        "model_driver:driver-fence-001",
        "verifier:verifier-001",
    )


def test_dependency_closed_docker_manifest_enters_running_with_exact_seven_roles(
    tmp_path: Path,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    provisional = replace(_record(tmp_path), runner_kind="docker")
    resources = _docker_runtime_closure(provisional)
    record = journal.create(_with_runtime_manifest(provisional, resources))
    registered = journal.register_resources(record.transaction_id, resources)
    identities = tuple(
        f"{resource.role.value}:{resource.resource_id}" for resource in registered
    )

    running = journal.transition(
        record.transaction_id,
        AttemptPhase.RUNNING,
        resource_lease_ids=identities,
    )

    assert len(running.resource_lease_ids) == 7
    assert running.resource_lease_ids == (
        "authority_watchdog:watchdog-001",
        "broker:broker-001",
        "candidate_parser:parser-001",
        "command_sandbox:sandbox-001",
        "credential_lease:credential-001",
        "model_driver:driver-fence-001",
        "verifier:verifier-001",
    )


def test_concurrent_resource_manifests_commit_one_set_without_union(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_journal = AttemptJournal(tmp_path / "journals")
    record = first_journal.create(_record(tmp_path))
    driver = _registered_process_resource(record)
    first_manifest = (
        driver,
        replace(
            driver,
            resource_id="sandbox-001",
            role=ResourceRole.COMMAND_SANDBOX,
        ),
    )
    second_manifest = (
        replace(
            driver,
            resource_id="parser-001",
            role=ResourceRole.CANDIDATE_PARSER,
        ),
        replace(
            driver,
            resource_id="verifier-001",
            role=ResourceRole.VERIFIER,
        ),
    )
    second_journal = AttemptJournal(first_journal.root)
    barrier = threading.Barrier(3)
    successes: list[tuple[RuntimeResourceLease, ...]] = []
    failures: list[BaseException] = []

    @contextmanager
    def independent_outer_permits(_label: str):
        yield

    monkeypatch.setattr(
        attempt_journal_module,
        "_diagnosticPersistenceAccess",
        independent_outer_permits,
    )

    def register(
        journal: AttemptJournal,
        manifest: tuple[RuntimeResourceLease, ...],
    ) -> None:
        barrier.wait(timeout=5)
        try:
            successes.append(
                journal.register_resources(record.transaction_id, manifest)
            )
        except BaseException as exc:  # noqa: BLE001 -- exact winner asserted below
            failures.append(exc)

    first = threading.Thread(target=register, args=(first_journal, first_manifest))
    second = threading.Thread(target=register, args=(second_journal, second_manifest))
    first.start()
    second.start()
    barrier.wait(timeout=5)
    first.join(timeout=10)
    second.join(timeout=10)

    assert not first.is_alive()
    assert not second.is_alive()
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], AttemptCollision)
    expected_sets = {
        tuple(sorted(first_manifest, key=lambda item: f"{item.role.value}:{item.resource_id}")),
        tuple(sorted(second_manifest, key=lambda item: f"{item.role.value}:{item.resource_id}")),
    }
    durable = AttemptJournal(first_journal.root).load_resources(record.transaction_id)
    assert durable == successes[0]
    assert durable in expected_sets


@pytest.mark.parametrize(
    "corruption",
    ["missing", "extra", "changed", "closure-sibling"],
)
def test_completed_resource_set_detects_missing_extra_or_changed_registration(
    tmp_path: Path,
    corruption: str,
) -> None:
    case_root = tmp_path / corruption
    journal = AttemptJournal(case_root / "journals")
    record = journal.create(_record(case_root))
    driver = _registered_process_resource(record)
    assert journal.register_resources(record.transaction_id, (driver,)) == (driver,)
    resource_root = journal.event_directory(record.transaction_id).parent / "resources"
    registration_path = next(
        path
        for path in resource_root.glob("*/events/00000000-*.json")
        if "closure" not in path.parts
    )

    if corruption == "missing":
        registration_path.unlink()
    elif corruption == "extra":
        journal._append_resource_event(
            replace(
                driver,
                resource_id="parser-extra",
                role=ResourceRole.CANDIDATE_PARSER,
            ),
            sequence=0,
            previous_digest="",
        )
    elif corruption == "changed":
        registration_path.unlink()
        journal._append_resource_event(
            replace(driver, mount_digest="9" * 64),
            sequence=0,
            previous_digest="",
        )
    else:
        (resource_root / "closure" / "unexpected").mkdir()

    with pytest.raises(JournalCorruption, match="runtime resource"):
        journal.load_resources(record.transaction_id)


@pytest.mark.parametrize(
    "corruption",
    [
        "fork",
        "wrong-previous",
        "noncanonical-json",
        "wrong-schema",
        "wrong-transaction",
        "unknown-field",
    ],
)
def test_resource_set_closure_replay_rejects_closed_chain_corruption(
    tmp_path: Path,
    corruption: str,
) -> None:
    case_root = tmp_path / corruption
    journal = AttemptJournal(case_root / "journals")
    record = journal.create(_record(case_root))
    driver = _registered_process_resource(record)
    journal.register_resources(record.transaction_id, (driver,))
    closure_events = (
        journal.event_directory(record.transaction_id).parent
        / "resources"
        / "closure"
        / "events"
    )
    completion_path = next(closure_events.glob("00000001-*.json"))

    if corruption == "fork":
        alternate = b"{}"
        (closure_events / f"00000000-{hashlib.sha256(alternate).hexdigest()}.json").write_bytes(
            alternate
        )
    else:
        event = json.loads(completion_path.read_text(encoding="utf-8"))
        if corruption == "wrong-previous":
            event["previous_event_digest"] = "0" * 64
        elif corruption == "wrong-schema":
            event["schema"] = "galaxy.runtime-resource-set-intent/v1"
        elif corruption == "wrong-transaction":
            event["transaction_id"] = "tx-foreign"
        elif corruption == "unknown-field":
            event["authority"] = "smuggled"
        if corruption == "noncanonical-json":
            raw = json.dumps(event, indent=2, ensure_ascii=False).encode("utf-8")
        else:
            raw = json.dumps(
                event,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        replacement = completion_path.with_name(
            "00000001-" + hashlib.sha256(raw).hexdigest() + ".json"
        )
        completion_path.unlink()
        replacement.write_bytes(raw)

    with pytest.raises(JournalCorruption, match="runtime resource-set"):
        journal.load_resources(record.transaction_id)


@pytest.mark.parametrize(
    "forgery",
    [
        "illegal-adjacency",
        "protected-field",
        "created-without-identity",
        "created-local-container",
        "created-docker-pid",
    ],
)
def test_resource_replay_rejects_content_addressed_semantic_forgery(
    tmp_path: Path,
    forgery: str,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    driver = _registered_process_resource(record)
    if forgery == "created-docker-pid":
        driver = replace(driver, backend="docker", image_digest="7" * 64)
    journal.register_resources(record.transaction_id, (driver,))
    event_dir = next(
        path.parent
        for path in (
            journal.event_directory(record.transaction_id).parent / "resources"
        ).glob("*/events/00000000-*.json")
        if "closure" not in path.parts
    )
    registration_path = next(event_dir.glob("00000000-*.json"))
    registration_digest = registration_path.stem.split("-", 1)[1]
    forged_resource = driver.toDict()
    forged_resource["updated_at"] = "2026-07-16T12:00:01+00:00"
    if forgery == "illegal-adjacency":
        forged_resource["state"] = ProcessResourceState.STARTED.value
        forged_resource["container_id"] = "8" * 64
    elif forgery == "protected-field":
        forged_resource["state"] = ProcessResourceState.QUIESCED.value
        forged_resource["backend"] = "docker"
    elif forgery == "created-without-identity":
        forged_resource["state"] = ProcessResourceState.CREATED.value
    elif forgery == "created-local-container":
        forged_resource["state"] = ProcessResourceState.CREATED.value
        forged_resource["container_id"] = "8" * 64
    else:
        forged_resource["state"] = ProcessResourceState.CREATED.value
        forged_resource["pid"] = 123
        forged_resource["process_start_token"] = "7" * 64
    event = {
        "schema": "galaxy.runtime-resource-event/v1",
        "transaction_id": record.transaction_id,
        "resource_id": driver.resource_id,
        "sequence": 1,
        "previous_event_digest": registration_digest,
        "resource": forged_resource,
    }
    raw = json.dumps(
        event,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    (event_dir / f"00000001-{digest}.json").write_bytes(raw)

    with pytest.raises(JournalCorruption, match="runtime resource transition"):
        journal.load_resources(record.transaction_id)


@pytest.mark.parametrize("quota", ["event-count", "chain-bytes"])
def test_resource_transition_quota_refuses_before_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    quota: str,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    driver = _registered_process_resource(record)
    journal.register_resources(record.transaction_id, (driver,))
    event_dir = next(
        path.parent
        for path in (
            journal.event_directory(record.transaction_id).parent / "resources"
        ).glob("*/events/00000000-*.json")
        if "closure" not in path.parts
    )
    registration_path = next(event_dir.glob("00000000-*.json"))
    if quota == "event-count":
        monkeypatch.setattr(
            attempt_journal_module,
            "_MAX_RESOURCE_CHAIN_EVENT_COUNT",
            1,
        )
    else:
        monkeypatch.setattr(
            attempt_journal_module,
            "_MAX_RESOURCE_CHAIN_BYTES",
            len(registration_path.read_bytes()) + 1,
        )
    before = {path.name: path.read_bytes() for path in event_dir.glob("*.json")}

    with pytest.raises(InvalidAttemptTransition, match="resource chain exceeds"):
        journal.transition_resource(
            record.transaction_id,
            driver.resource_id,
            ProcessResourceState.QUIESCED,
        )

    assert {
        path.name: path.read_bytes() for path in event_dir.glob("*.json")
    } == before


def test_resource_replay_rejects_overlong_transition_chain(tmp_path: Path) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    driver = _registered_process_resource(record)
    journal.register_resources(record.transaction_id, (driver,))
    event_dir = next(
        path.parent
        for path in (
            journal.event_directory(record.transaction_id).parent / "resources"
        ).glob("*/events/00000000-*.json")
        if "closure" not in path.parts
    )
    for sequence in range(1, 6):
        raw = b"{}"
        (event_dir / f"{sequence:08d}-{hashlib.sha256(raw).hexdigest()}.json").write_bytes(
            raw
        )

    with pytest.raises(JournalCorruption, match="event-count quota"):
        journal.load_resources(record.transaction_id)


def test_resource_replay_rejects_event_over_byte_quota(tmp_path: Path) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    driver = _registered_process_resource(record)
    journal.register_resources(record.transaction_id, (driver,))
    registration_path = next(
        path
        for path in (
            journal.event_directory(record.transaction_id).parent / "resources"
        ).glob("*/events/00000000-*.json")
        if "closure" not in path.parts
    )
    event = json.loads(registration_path.read_text(encoding="utf-8"))
    event["resource"]["error"] = "x" * 1_100_000
    raw = json.dumps(
        event,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    replacement = registration_path.with_name(
        "00000000-" + hashlib.sha256(raw).hexdigest() + ".json"
    )
    registration_path.unlink()
    replacement.write_bytes(raw)

    with pytest.raises(JournalCorruption, match="resource event raced retained read"):
        journal.load_resources(record.transaction_id)


def test_resource_replay_rejects_transition_chain_over_byte_quota(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    driver = _registered_process_resource(record)
    journal.register_resources(record.transaction_id, (driver,))
    journal.transition_resource(
        record.transaction_id,
        driver.resource_id,
        ProcessResourceState.QUIESCED,
    )
    event_dir = next(
        path.parent
        for path in (
            journal.event_directory(record.transaction_id).parent / "resources"
        ).glob("*/events/00000000-*.json")
        if "closure" not in path.parts
    )
    exact_bytes = sum(len(path.read_bytes()) for path in event_dir.glob("*.json"))
    monkeypatch.setattr(
        attempt_journal_module,
        "_MAX_RESOURCE_CHAIN_BYTES",
        exact_bytes - 1,
    )

    with pytest.raises(JournalCorruption, match="byte quota"):
        AttemptJournal(journal.root).load_resources(record.transaction_id)


@pytest.mark.parametrize(
    "identity",
    [
        "missing",
        "both",
        "local-container",
        "docker-pid",
        "docker-container-with-group",
    ],
)
def test_created_process_requires_exactly_one_durable_identity(
    tmp_path: Path,
    identity: str,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    driver = _registered_process_resource(record)
    if identity.startswith("docker-"):
        driver = replace(driver, backend="docker", image_digest="7" * 64)
    journal.register_resources(record.transaction_id, (driver,))
    event_dir = next(
        path.parent
        for path in (
            journal.event_directory(record.transaction_id).parent / "resources"
        ).glob("*/events/00000000-*.json")
        if "closure" not in path.parts
    )
    before = {path.name: path.read_bytes() for path in event_dir.glob("*.json")}
    changes: dict[str, object] = {}
    if identity == "both":
        token = processStartToken(os.getpid())
        assert token is not None
        changes = {
            "pid": os.getpid(),
            "process_group_id": os.getpid(),
            "process_start_token": token,
            "container_id": "8" * 64,
        }
    elif identity == "local-container":
        changes = {"container_id": "8" * 64}
    elif identity == "docker-pid":
        token = processStartToken(os.getpid())
        assert token is not None
        changes = {
            "pid": os.getpid(),
            "process_start_token": token,
        }
    elif identity == "docker-container-with-group":
        changes = {
            "container_id": "8" * 64,
            "process_group_id": os.getpid(),
        }

    with pytest.raises(
        InvalidAttemptTransition,
        match="exactly one durable process identity",
    ):
        journal.transition_resource(
            record.transaction_id,
            driver.resource_id,
            ProcessResourceState.CREATED,
            **changes,
        )

    assert {
        path.name: path.read_bytes() for path in event_dir.glob("*.json")
    } == before


def test_created_container_process_binds_identity_at_created_transition(
    tmp_path: Path,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    driver = replace(
        _registered_process_resource(record),
        backend="docker",
        image_digest="7" * 64,
    )
    journal.register_resources(record.transaction_id, (driver,))

    created = journal.transition_resource(
        record.transaction_id,
        driver.resource_id,
        ProcessResourceState.CREATED,
        container_id="8" * 64,
    )

    assert created.state is ProcessResourceState.CREATED
    assert created.container_id == "8" * 64
    assert created.pid == 0
    assert AttemptJournal(journal.root).load_resources(record.transaction_id) == (
        created,
    )


@pytest.mark.parametrize(
    "corruption",
    ["attempt-bool", "resource-float", "closure-bool", "resource-nan"],
)
def test_journal_decoders_reject_bool_float_and_nonfinite_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))

    def replace_content_addressed(path: Path, value: object) -> Path:
        raw = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        replacement = path.with_name(
            path.name.split("-", 1)[0]
            + "-"
            + hashlib.sha256(raw).hexdigest()
            + ".json"
        )
        path.unlink()
        replacement.write_bytes(raw)
        return replacement

    if corruption == "attempt-bool":
        event_path = next(journal.event_directory(record.transaction_id).glob("*.json"))
        event = json.loads(event_path.read_text(encoding="utf-8"))
        event["sequence"] = False
        event["record"]["sequence"] = False
        replace_content_addressed(event_path, event)
        operation = partial(journal.load, record.transaction_id)
    elif corruption == "closure-bool":
        resource = _registered_process_resource(record)

        def crash_before_resource(*_args, **_kwargs):
            raise RuntimeError("resource crash")

        monkeypatch.setattr(journal, "_append_resource_event", crash_before_resource)
        with pytest.raises(RuntimeError):
            journal.register_resources(record.transaction_id, (resource,))
        monkeypatch.undo()
        event_path = next(
            (
                journal.event_directory(record.transaction_id).parent
                / "resources"
                / "closure"
                / "events"
            ).glob("00000000-*.json")
        )
        event = json.loads(event_path.read_text(encoding="utf-8"))
        event["sequence"] = False
        replace_content_addressed(event_path, event)
        operation = partial(journal.load_resources, record.transaction_id)
    else:
        resource = _registered_process_resource(record)
        journal.register_resources(record.transaction_id, (resource,))
        event_path = next(
            path
            for path in (
                journal.event_directory(record.transaction_id).parent / "resources"
            ).glob("*/events/00000000-*.json")
            if "closure" not in path.parts
        )
        event = json.loads(event_path.read_text(encoding="utf-8"))
        if corruption == "resource-float":
            event["sequence"] = 0.0
        else:
            event["resource"]["backend"] = float("nan")
        replace_content_addressed(event_path, event)
        operation = partial(
            journal._load_resource_chain,
            record.transaction_id,
            event_path.parent,
            resource_id=resource.resource_id,
        )

    with pytest.raises(JournalCorruption, match="JSON|sequence|contract|inconsistent"):
        operation()


def test_resource_set_decoder_rejects_duplicate_raw_ids_across_roles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    driver = _registered_process_resource(record)
    same_raw_id = replace(driver, role=ResourceRole.VERIFIER)
    with pytest.raises(InvalidAttemptTransition, match="identities must be unique"):
        journal.register_resources(record.transaction_id, (driver, same_raw_id))
    assert not (
        journal.event_directory(record.transaction_id).parent / "resources"
    ).exists()

    def crash_before_resource(*_args, **_kwargs):
        raise RuntimeError("resource crash")

    monkeypatch.setattr(journal, "_append_resource_event", crash_before_resource)
    with pytest.raises(RuntimeError):
        journal.register_resources(
            record.transaction_id,
            (
                driver,
                replace(
                    driver,
                    resource_id="verifier-distinct",
                    role=ResourceRole.VERIFIER,
                ),
            ),
        )
    monkeypatch.undo()
    intent_path = next(
        (
            journal.event_directory(record.transaction_id).parent
            / "resources"
            / "closure"
            / "events"
        ).glob("00000000-*.json")
    )
    intent = json.loads(intent_path.read_text(encoding="utf-8"))
    intent["resources"][1]["resource_identity"] = (
        f"verifier:{driver.resource_id}"
    )
    raw = json.dumps(
        intent,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    replacement = intent_path.with_name(
        "00000000-" + hashlib.sha256(raw).hexdigest() + ".json"
    )
    intent_path.unlink()
    replacement.write_bytes(raw)

    with pytest.raises(JournalCorruption, match="raw identities are duplicated"):
        journal.load_resources(record.transaction_id)


def test_journal_replay_and_discovery_do_not_use_path_based_enumeration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = AttemptJournal(tmp_path / "journals")
    record = journal.create(_record(tmp_path))
    resource = RuntimeResourceLease(
        resource_id="driver-native-enumeration",
        run_id="run-001",
        transaction_id=record.transaction_id,
        controller_scope_id="controller-001",
        role=ResourceRole.MODEL_DRIVER,
        backend="local",
        ownership_nonce=record.ownership_nonce,
        state=ProcessResourceState.REGISTERED,
        cleanup_locator_digest="2" * 64,
        pid=0,
        process_group_id=0,
        container_id="",
        image_digest="",
        entrypoint_digest="3" * 64,
        mount_digest="4" * 64,
        environment_digest="5" * 64,
        security_profile_digest="6" * 64,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )
    journal.register_resources(record.transaction_id, (resource,))

    def forbid_path_enumeration(_self):
        raise AssertionError("journal replay used Path.iterdir")

    monkeypatch.setattr(Path, "iterdir", forbid_path_enumeration)
    reopened = AttemptJournal(journal.root)
    assert reopened.load(record.transaction_id) == record
    assert reopened.load_resources(record.transaction_id) == (resource,)
    assert reopened.pending_recovery() == (record,)
