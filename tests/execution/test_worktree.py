"""Private-clone provisioning and one-use retirement of legacy linked worktrees."""
import hashlib
import json
import shutil
import subprocess
import sys
import threading
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from platform_core.core.galaxy_evidence import canonical_digest
from platform_core.runtime import worktree
from platform_core.execution.credential_broker import (
    CredentialBroker,
    CredentialBrokerRefused,
)
from platform_core.runtime.attempt_journal import (
    AttemptJournal,
    AttemptPhase,
    AttemptRecord,
    IncompleteResourceSet,
    JournalCorruption,
    MissingResourceSet,
    MissingAttempt,
)
from platform_core.runtime.candidate import (
    CredentialResourceState,
    ProcessResourceState,
    ResourceRole,
    RunnerKind,
    RuntimeResourceLease,
    processStartToken,
    runtimeResourceStateDigest,
)
from platform_core.runtime.canonical_repo import attestCanonicalRepository
from platform_core.runtime.git_object_writer import (
    CandidateRepositoryLease,
    ObjectRecord,
    SourceObjectClosure,
)
from platform_core.runtime.object_manifest import ManifestPolicy, ObjectManifest
from platform_core.runtime.worktree import (
    CloneLeaseRecovery,
    CloneRecoveryCheckpoint,
    CloneRecoveryRefused,
    CloneRecoveryResult,
    LegacyWorktreeInspection,
    LegacyWorktreeRefused,
    LegacyWorktreeRetirer,
)


def _git(args, cwd):
    subprocess.run(["git"] + args, cwd=cwd, check=True,
                   capture_output=True, text=True)


def _has_git():
    return shutil.which("git") is not None


def _recovery_attempt(
    tmp_path: Path,
    *,
    transaction_id: str,
    runner_kind: str = "docker",
) -> tuple[AttemptJournal, AttemptRecord]:
    now = datetime.now(timezone.utc).isoformat()
    clone = tmp_path / "clone"
    clone.mkdir()
    record = AttemptRecord(
        transaction_id=transaction_id,
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
        ownership_nonce="2" * 64,
        spec_digest="3" * 64,
        policy_digest="4" * 64,
        canonical_metadata_attestation_digest="5" * 64,
        object_format="sha1",
        oid_length=40,
        ref_backend="files",
        candidate_branch=f"refs/heads/9to5/candidates/{transaction_id}",
        checkpoint_message_digest="6" * 64,
        proposal_message_digest="7" * 64,
        commit_timestamp_seed=now,
        runner_kind=runner_kind,
        candidate_git_dir=str(clone / ".git"),
        canonical_git_common_dir=str(tmp_path / "canonical" / ".git"),
        source_manifest_digest="8" * 64,
        source_object_closure_digest="9" * 64,
        source_snapshot_digest="a" * 64,
        source_parser_receipt_id="b" * 64,
        source_payload_root=str(tmp_path / "source-payloads"),
        created_at=now,
        updated_at=now,
    )
    closure = (
        _local_runtime_closure(record)
        if runner_kind == "local"
        else _docker_runtime_closure(record)
    )
    record = _with_runtime_manifest(record, closure)
    journal = AttemptJournal(tmp_path / "journal")
    journal.create(record)
    return journal, record


def _registered_process_resource(
    record: AttemptRecord,
    *,
    role: ResourceRole,
    backend: str,
) -> RuntimeResourceLease:
    return RuntimeResourceLease(
        resource_id=f"{role.value.replace('_', '-')}-001",
        run_id="run-001",
        transaction_id=record.transaction_id,
        controller_scope_id="controller-001",
        role=role,
        backend=backend,
        ownership_nonce=record.ownership_nonce,
        state=ProcessResourceState.REGISTERED,
        cleanup_locator_digest="c" * 64,
        pid=0,
        process_group_id=0,
        container_id="",
        image_digest="d" * 64 if backend == "docker" else "",
        entrypoint_digest="e" * 64,
        mount_digest="f" * 64,
        environment_digest="1" * 64,
        security_profile_digest="2" * 64,
        created_at=record.created_at,
        updated_at=record.created_at,
    )


def _registered_credential_resource(
    record: AttemptRecord,
) -> RuntimeResourceLease:
    return RuntimeResourceLease(
        resource_id="credential-001",
        run_id="run-001",
        transaction_id=record.transaction_id,
        controller_scope_id="controller-001",
        role=ResourceRole.CREDENTIAL_LEASE,
        backend="credential-broker",
        ownership_nonce=record.ownership_nonce,
        state=CredentialResourceState.REGISTERED,
        cleanup_locator_digest="c" * 64,
        pid=0,
        process_group_id=0,
        container_id="",
        image_digest="",
        entrypoint_digest="",
        mount_digest="",
        environment_digest="",
        security_profile_digest="2" * 64,
        created_at=record.created_at,
        updated_at=record.created_at,
        provider="codex",
        auth_mode="subscription",
        secret_channel_id="channel-001",
        expires_at=(
            datetime.fromisoformat(record.created_at.replace("Z", "+00:00"))
            + timedelta(minutes=5)
        ).isoformat(),
        issuer_id="credential-broker-001",
        revocation_generation=1,
    )


def _local_runtime_closure(record: AttemptRecord) -> tuple[RuntimeResourceLease, ...]:
    watchdog = _registered_process_resource(
        record,
        role=ResourceRole.AUTHORITY_WATCHDOG,
        backend="local",
    )
    driver = replace(
        _registered_process_resource(
            record,
            role=ResourceRole.MODEL_DRIVER,
            backend="local",
        ),
        depends_on=(f"{watchdog.role.value}:{watchdog.resource_id}",),
    )
    parser = replace(
        _registered_process_resource(
            record,
            role=ResourceRole.CANDIDATE_PARSER,
            backend="docker",
        ),
        depends_on=(
            f"{watchdog.role.value}:{watchdog.resource_id}",
            f"{driver.role.value}:{driver.resource_id}",
        ),
    )
    verifier = replace(
        _registered_process_resource(
            record,
            role=ResourceRole.VERIFIER,
            backend="docker",
        ),
        depends_on=(
            f"{watchdog.role.value}:{watchdog.resource_id}",
            f"{parser.role.value}:{parser.resource_id}",
        ),
    )
    return watchdog, driver, parser, verifier


def _docker_runtime_closure(record: AttemptRecord) -> tuple[RuntimeResourceLease, ...]:
    credential = _registered_credential_resource(record)
    watchdog = replace(
        _registered_process_resource(
            record,
            role=ResourceRole.AUTHORITY_WATCHDOG,
            backend="docker",
        )
    )
    driver = replace(
        _registered_process_resource(
            record,
            role=ResourceRole.MODEL_DRIVER,
            backend="docker",
        ),
        depends_on=(f"{watchdog.role.value}:{watchdog.resource_id}",),
    )
    broker = replace(
        _registered_process_resource(
            record,
            role=ResourceRole.BROKER,
            backend="docker",
        ),
        depends_on=(
            f"{watchdog.role.value}:{watchdog.resource_id}",
            f"{driver.role.value}:{driver.resource_id}",
        ),
    )
    sandbox = replace(
        _registered_process_resource(
            record,
            role=ResourceRole.COMMAND_SANDBOX,
            backend="docker",
        ),
        depends_on=(
            f"{watchdog.role.value}:{watchdog.resource_id}",
            f"{broker.role.value}:{broker.resource_id}",
        ),
    )
    parser = replace(
        _registered_process_resource(
            record,
            role=ResourceRole.CANDIDATE_PARSER,
            backend="docker",
        ),
        depends_on=(
            f"{watchdog.role.value}:{watchdog.resource_id}",
            f"{sandbox.role.value}:{sandbox.resource_id}",
        ),
    )
    verifier = replace(
        _registered_process_resource(
            record,
            role=ResourceRole.VERIFIER,
            backend="docker",
        ),
        depends_on=(
            f"{watchdog.role.value}:{watchdog.resource_id}",
            f"{parser.role.value}:{parser.resource_id}",
        ),
    )
    return credential, watchdog, driver, broker, sandbox, parser, verifier


def _runtime_manifest_fields(
    *,
    runner_kind: str,
    resources: tuple[RuntimeResourceLease, ...],
) -> dict[str, str]:
    raw = json.dumps(
        {
            "resources": [
                {
                    "backend": resource.backend,
                    "depends_on": list(resource.depends_on),
                    "resource_identity": (
                        f"{resource.role.value}:{resource.resource_id}"
                    ),
                }
                for resource in sorted(
                    resources,
                    key=lambda item: f"{item.role.value}:{item.resource_id}",
                )
            ],
            "runner_kind": runner_kind,
            "schema": "galaxy.runtime-resource-manifest/v1",
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return {
        "runtime_resource_manifest_json": raw,
        "runtime_resource_manifest_digest": hashlib.sha256(
            raw.encode("utf-8")
        ).hexdigest(),
    }


def _with_runtime_manifest(
    record: AttemptRecord,
    resources: tuple[RuntimeResourceLease, ...],
) -> AttemptRecord:
    return replace(
        record,
        **_runtime_manifest_fields(
            runner_kind=record.runner_kind,
            resources=resources,
        ),
    )


def _running_resources(
    journal: AttemptJournal,
    record: AttemptRecord,
    resources: tuple[RuntimeResourceLease, ...],
) -> tuple[AttemptRecord, tuple[RuntimeResourceLease, ...]]:
    registered = journal.register_resources(record.transaction_id, resources)
    running = journal.transition(
        record.transaction_id,
        AttemptPhase.RUNNING,
        resource_lease_ids=tuple(
            f"{resource.role.value}:{resource.resource_id}"
            for resource in registered
        ),
    )
    return running, registered


class _State:
    def __init__(self, task_id, root):
        self.task_id = task_id
        self.meta = {"work_dir": str(root)}


@pytest.mark.skipif(not _has_git(), reason="git not available")
def test_legacy_worktree_entrypoint_is_retired_without_shared_fallback(
    tmp_path,
    monkeypatch,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-b", "main"], repo)
    _git(["config", "user.email", "t@t"], repo)
    _git(["config", "user.name", "t"], repo)
    (repo / "f.txt").write_text("hi", encoding="utf-8")
    _git(["add", "."], repo)
    _git(["commit", "-m", "init"], repo)
    monkeypatch.setattr(worktree.config, "PROJECT_ROOT", repo)
    monkeypatch.setattr(worktree.config, "STATE_DIR", tmp_path / "state")
    st = _State("abcdef12-task", repo)

    with pytest.raises(LegacyWorktreeRefused, match="retired"):
        worktree.enterWorktree(st, "st-001")
    assert worktree.enterWorktreeLease(st, "st-001") is None
    assert not (tmp_path / "state" / ".sc-worktrees").exists()
    assert worktree.isIsolated(str(repo)) is False


def test_gc_refuses_paths_outside_sc_worktrees(tmp_path, monkeypatch):
    monkeypatch.setattr(worktree.config, "STATE_DIR", tmp_path / "state")
    outside = tmp_path / "important"
    outside.mkdir()
    worktree.removeWorktree(str(outside))    # must refuse: not under state/.sc-worktrees/
    assert outside.exists()


def test_legacy_retirement_checkpoints_dirty_and_moves_every_entry_outside(
    tmp_path,
) -> None:
    legacy = tmp_path / "repo" / "state" / ".sc-worktrees"
    clean = legacy / "task-a" / "clean"
    dirty = legacy / "task-a" / "dirty"
    clean.mkdir(parents=True)
    dirty.mkdir(parents=True)
    (clean / "state.txt").write_bytes(b"clean")
    (dirty / "state.txt").write_bytes(b"dirty")
    archive = tmp_path / "controller" / "legacy"
    archive.mkdir(parents=True)
    checkpointed: list[str] = []

    def inspect(directory, legacy_id):
        entry = directory.listEntries()[0]
        payload = directory.readFile(
            entry.name,
            max_bytes=32,
            expected=entry.identity,
        )
        return LegacyWorktreeInspection(
            legacy_id=legacy_id,
            snapshot_digest=canonical_digest({"legacy_id": legacy_id, "payload": payload.hex()}),
            dirty=payload == b"dirty",
        )

    def checkpoint(inspection):
        checkpointed.append(inspection.legacy_id)
        return (
            f"refs/9to5/legacy-recovery/{inspection.snapshot_digest}",
            "a" * 40,
        )

    results = LegacyWorktreeRetirer(
        legacy_roots=(legacy,),
        archive_root=archive,
        inspect=inspect,
        checkpoint=checkpoint,
    ).retire()

    assert [result.disposition for result in results] == [
        "clean_retired",
        "dirty_checkpointed",
    ]
    assert checkpointed == ["task-a/dirty"]
    assert not clean.exists()
    assert not dirty.exists()
    assert len(list(archive.iterdir())) == 2


def test_legacy_retirement_preserves_dirty_entry_when_checkpoint_fails(tmp_path) -> None:
    legacy = tmp_path / "repo" / "state" / ".sc-worktrees"
    dirty = legacy / "task-a" / "dirty"
    dirty.mkdir(parents=True)
    (dirty / "state.txt").write_bytes(b"dirty")
    archive = tmp_path / "controller" / "legacy"
    archive.mkdir(parents=True)

    def inspect(_directory, legacy_id):
        return LegacyWorktreeInspection(
            legacy_id=legacy_id,
            snapshot_digest="b" * 64,
            dirty=True,
        )

    with pytest.raises(LegacyWorktreeRefused, match="checkpoint"):
        LegacyWorktreeRetirer(
            legacy_roots=(legacy,),
            archive_root=archive,
            inspect=inspect,
            checkpoint=lambda _inspection: (_ for _ in ()).throw(RuntimeError("boom")),
        ).retire()

    assert (dirty / "state.txt").read_bytes() == b"dirty"
    assert list(archive.iterdir()) == []




class _RegistrationWriter:
    def __init__(self, journal: AttemptJournal) -> None:
        self.journal = journal
        self.called = 0

    def createCandidateRepository(
        self,
        *,
        transaction_id,
        checkout_root,
        candidate_branch,
        manifest,
        closure,
        forbidden_roots,
    ):
        del manifest, forbidden_roots
        record = self.journal.load(transaction_id)
        assert record.phase is AttemptPhase.LEASE_REGISTERED
        self.called += 1
        checkout = Path(checkout_root)
        git_dir = checkout / ".git"
        (git_dir / "objects" / "info").mkdir(parents=True, exist_ok=True)
        ref = git_dir.joinpath(*candidate_branch.split("/"))
        ref.parent.mkdir(parents=True, exist_ok=True)
        (git_dir / "config").write_bytes(
            b"[core]\n\trepositoryformatversion = 0\n\tbare = false\n"
        )
        (git_dir / "HEAD").write_bytes(f"ref: {candidate_branch}\n".encode("ascii"))
        ref.write_bytes(f"{closure.revision}\n".encode("ascii"))
        (git_dir / "shallow").write_bytes(f"{closure.revision}\n".encode("ascii"))
        return CandidateRepositoryLease(
            transaction_id=transaction_id,
            checkout_path=str(checkout),
            git_dir=str(git_dir),
            base_revision=closure.revision,
            base_tree=closure.tree_oid,
            candidate_branch=candidate_branch,
            repository_id=closure.repository_id,
            manifest_digest=closure.manifest_digest,
            object_closure_digest=closure.object_closure_digest,
            index_digest="9" * 64,
            shallow_root_revision=closure.revision,
        )


def _source_closure(
    repository_id: str,
    revision: str,
    tree_oid: str,
    manifest_digest: str,
    payload_root: Path,
):
    payload_root.mkdir(parents=True)
    records = tuple(
        sorted(
            (
                ObjectRecord(
                    object_type="commit",
                    oid=revision,
                    payload_sha256="1" * 64,
                    framed_object_sha256="2" * 64,
                    size=1,
                ),
                ObjectRecord(
                    object_type="tree",
                    oid=tree_oid,
                    payload_sha256="3" * 64,
                    framed_object_sha256="4" * 64,
                    size=1,
                ),
            ),
            key=lambda record: record.oid,
        )
    )
    return SourceObjectClosure(
        repository_id=repository_id,
        revision=revision,
        tree_oid=tree_oid,
        manifest_digest=manifest_digest,
        object_closure_digest=canonical_digest(
            [record.toDict() for record in records]
        ),
        source_snapshot_digest="5" * 64,
        parser_receipt_id="6" * 64,
        parser_image_digest="7" * 64,
        parser_runtime_digest="8" * 64,
        parser_security_profile_digest="9" * 64,
        payload_root=str(payload_root.resolve()),
        objects=records,
        intentional_shallow=True,
        parser_network_allowed=False,
    )


@pytest.mark.skipif(not _has_git(), reason="git not available")
def test_clone_provisioner_registers_before_repository_build_and_runtime_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "canonical"
    repo.mkdir()
    _git(["init", "-b", "main"], repo)
    _git(["config", "user.email", "t@t"], repo)
    _git(["config", "user.name", "t"], repo)
    (repo / "f.txt").write_text("base\n", encoding="utf-8")
    _git(["add", "."], repo)
    _git(["commit", "-m", "base"], repo)
    tree_oid = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    attestation = attestCanonicalRepository(repo)
    policy = ManifestPolicy(
        reserved_roots=(),
        max_files=10,
        max_total_bytes=1024,
        max_file_bytes=512,
        max_depth=8,
        max_path_bytes=240,
    )
    manifest = ObjectManifest(
        expected_revision=attestation.head_oid,
        entries=(),
        attribute_rules=(),
        policy=policy,
    )
    closure = _source_closure(
        attestation.repository_id,
        attestation.head_oid,
        tree_oid,
        manifest.manifest_digest,
        tmp_path / "controller" / "source-payloads",
    )
    journal = AttemptJournal(tmp_path / "controller" / "journal")
    writer = _RegistrationWriter(journal)
    capability = object()
    provisioner = worktree.CloneLeaseProvisioner(
        attestation=attestation,
        journal=journal,
        writer=writer,
        candidate_checkout_root=tmp_path / "controller" / "checkouts" / "candidate",
        process_capability=capability,
    )
    now = datetime.now(timezone.utc).isoformat()
    resource_seed = SimpleNamespace(
        transaction_id="tx-clone-001",
        ownership_nonce="a" * 64,
        created_at=now,
    )
    requested = _local_runtime_closure(resource_seed)
    provision_args = dict(
        transaction_id="tx-clone-001",
        task_id="task-001",
        subtask_id="subtask-001",
        attempt_id="attempt-001",
        clone_lease_id="clone-001",
        runner_kind=RunnerKind.LOCAL,
        source_manifest=manifest,
        source_closure=closure,
        ownership_nonce="a" * 64,
        spec_digest="b" * 64,
        checkpoint_message_digest="c" * 64,
        proposal_message_digest="d" * 64,
        commit_timestamp_seed=now,
        **_runtime_manifest_fields(
            runner_kind="local",
            resources=requested,
        ),
        process_capability=capability,
    )
    valid_manifest = provision_args["runtime_resource_manifest_json"]
    missing_role = json.loads(valid_manifest)
    missing_role["resources"] = missing_role["resources"][:-1]
    missing_role_raw = json.dumps(
        missing_role,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    invalid_manifests = (
        ("", ""),
        ("{", hashlib.sha256(b"{").hexdigest()),
        (
            missing_role_raw,
            hashlib.sha256(missing_role_raw.encode("utf-8")).hexdigest(),
        ),
        (valid_manifest, "f" * 64),
    )
    for manifest_json, manifest_digest in invalid_manifests:
        invalid_args = {
            **provision_args,
            "runtime_resource_manifest_json": manifest_json,
            "runtime_resource_manifest_digest": manifest_digest,
        }
        with pytest.raises(
            worktree.PrivateCloneRefused,
            match="runtime resource manifest",
        ):
            provisioner.provision(**invalid_args)
        assert writer.called == 0
        assert not (
            tmp_path / "controller" / "checkouts" / "candidate" / "tx-clone-001"
        ).exists()
        with pytest.raises(MissingAttempt):
            journal.load("tx-clone-001")

    lease = provisioner.provision(**provision_args)
    assert writer.called == 1
    assert worktree.validateCloneLease(lease) is lease
    assert journal.load(lease.transaction_id).phase is AttemptPhase.LEASE_REGISTERED
    assert provisioner.provision(**provision_args) is lease

    for failure in (
        lambda: (),
        lambda: (_ for _ in ()).throw(IncompleteResourceSet("intent only")),
        lambda: (_ for _ in ()).throw(JournalCorruption("bad completion")),
    ):
        with monkeypatch.context() as patch:
            patch.setattr(journal, "load_resources", lambda _transaction_id: failure())
            refused = worktree.CloneLeaseProvisioner(
                attestation=attestation,
                journal=journal,
                writer=writer,
                candidate_checkout_root=(
                    tmp_path / "controller" / "checkouts" / "candidate"
                ),
                process_capability=capability,
            )
            with pytest.raises(worktree.PrivateCloneRefused, match="recovery"):
                refused.provision(**provision_args)
            assert writer.called == 1

    restarted = worktree.CloneLeaseProvisioner(
        attestation=attestation,
        journal=journal,
        writer=writer,
        candidate_checkout_root=tmp_path / "controller" / "checkouts" / "candidate",
        process_capability=capability,
    )
    replayed = restarted.provision(**provision_args)
    assert worktree.validateCloneLease(replayed) is replayed
    assert replayed.toDict() == lease.toDict()
    assert writer.called == 2
    resource = next(
        item for item in requested if item.role is ResourceRole.MODEL_DRIVER
    )
    canonical_requested = tuple(
        sorted(requested, key=lambda item: f"{item.role.value}:{item.resource_id}")
    )
    substituted = (
        replace(canonical_requested[0], security_profile_digest="9" * 64),
        canonical_requested[1],
    )
    extra = tuple(
        sorted(
            (
                *canonical_requested,
                replace(
                    resource,
                    resource_id="broker-001",
                    role=ResourceRole.BROKER,
                ),
            ),
            key=lambda item: f"{item.role.value}:{item.resource_id}",
        )
    )
    for adversarial_return in (substituted, extra):
        with monkeypatch.context() as patch:
            patch.setattr(
                journal,
                "register_resources",
                lambda _transaction_id, _resources: adversarial_return,
            )
            patch.setattr(
                journal,
                "transition",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("mismatched resources must not gain RUNNING authority")
                ),
            )
            with pytest.raises(
                worktree.PrivateCloneRefused,
                match="durable runtime resource registry differs",
            ):
                provisioner.registerRuntimeResources(
                    lease,
                    resources=requested,
                )

    running = provisioner.registerRuntimeResources(
        lease,
        resources=requested,
    )
    assert running.phase is AttemptPhase.RUNNING
    assert running.resource_lease_ids == (
        "authority_watchdog:authority-watchdog-001",
        "candidate_parser:candidate-parser-001",
        "model_driver:model-driver-001",
        "verifier:verifier-001",
    )


@pytest.mark.skipif(not _has_git(), reason="git not available")
def test_clone_provisioning_replays_exact_registered_intent_after_hard_death(
    tmp_path: Path,
) -> None:
    class SimulatedHardDeath(BaseException):
        pass

    class CrashOnceWriter(_RegistrationWriter):
        def __init__(self, journal: AttemptJournal) -> None:
            super().__init__(journal)
            self.crashed = False

        def createCandidateRepository(self, **kwargs):
            if not self.crashed:
                self.crashed = True
                self.called += 1
                transaction_id = kwargs["transaction_id"]
                assert self.journal.load(transaction_id).phase is (
                    AttemptPhase.LEASE_REGISTERED
                )
                checkout = Path(kwargs["checkout_root"])
                (checkout / ".git" / "objects" / "info").mkdir(parents=True)
                raise SimulatedHardDeath("after lease registration")
            return super().createCandidateRepository(**kwargs)

    repo = tmp_path / "canonical"
    repo.mkdir()
    _git(["init", "-b", "main"], repo)
    _git(["config", "user.email", "t@t"], repo)
    _git(["config", "user.name", "t"], repo)
    (repo / "f.txt").write_text("base\n", encoding="utf-8")
    _git(["add", "."], repo)
    _git(["commit", "-m", "base"], repo)
    tree_oid = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    attestation = attestCanonicalRepository(repo)
    manifest = ObjectManifest(
        expected_revision=attestation.head_oid,
        entries=(),
        attribute_rules=(),
        policy=ManifestPolicy(
            reserved_roots=(),
            max_files=10,
            max_total_bytes=1024,
            max_file_bytes=512,
            max_depth=8,
            max_path_bytes=240,
        ),
    )
    closure = _source_closure(
        attestation.repository_id,
        attestation.head_oid,
        tree_oid,
        manifest.manifest_digest,
        tmp_path / "controller" / "source-payloads",
    )
    journal = AttemptJournal(tmp_path / "controller" / "journal")
    writer = CrashOnceWriter(journal)
    capability = object()
    root = tmp_path / "controller" / "checkouts" / "candidate"
    fixed_time = datetime.now(timezone.utc)

    def provisioner() -> worktree.CloneLeaseProvisioner:
        return worktree.CloneLeaseProvisioner(
            attestation=attestation,
            journal=journal,
            writer=writer,
            candidate_checkout_root=root,
            process_capability=capability,
            clock=lambda: fixed_time,
        )

    resource_seed = SimpleNamespace(
        transaction_id="tx-clone-crash-001",
        ownership_nonce="a" * 64,
        created_at=fixed_time.isoformat(),
    )
    runtime_resources = _local_runtime_closure(resource_seed)
    args = dict(
        transaction_id="tx-clone-crash-001",
        task_id="task-001",
        subtask_id="subtask-001",
        attempt_id="attempt-001",
        clone_lease_id="clone-001",
        runner_kind=RunnerKind.LOCAL,
        source_manifest=manifest,
        source_closure=closure,
        ownership_nonce="a" * 64,
        spec_digest="b" * 64,
        checkpoint_message_digest="c" * 64,
        proposal_message_digest="d" * 64,
        commit_timestamp_seed=fixed_time.isoformat(),
        **_runtime_manifest_fields(
            runner_kind="local",
            resources=runtime_resources,
        ),
        process_capability=capability,
    )
    with pytest.raises(SimulatedHardDeath):
        provisioner().provision(**args)
    interrupted = journal.load(args["transaction_id"])
    assert interrupted.phase is AttemptPhase.LEASE_REGISTERED
    with pytest.raises(MissingResourceSet):
        journal.load_resources(args["transaction_id"])

    lease = provisioner().provision(**args)

    assert worktree.validateCloneLease(lease) is lease
    assert lease.transaction_id == args["transaction_id"]
    assert writer.called == 2


def test_hard_death_recovery_quiesces_before_checkpoint_and_is_idempotent(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "canonical"
    repo.mkdir()
    _git(["init", "-b", "main"], repo)
    _git(["config", "user.email", "t@t"], repo)
    _git(["config", "user.name", "t"], repo)
    (repo / "f.txt").write_text("base\n", encoding="utf-8")
    _git(["add", "."], repo)
    _git(["commit", "-m", "base"], repo)
    attestation = attestCanonicalRepository(repo)
    clone = tmp_path / "controller" / "checkouts" / "tx-recovery-001"
    git_dir = clone / ".git"
    (git_dir / "objects" / "info").mkdir(parents=True)
    branch = "refs/heads/9to5/candidates/tx-recovery-001"
    branch_path = git_dir.joinpath(*branch.split("/"))
    branch_path.parent.mkdir(parents=True)
    (git_dir / "config").write_bytes(
        b"[core]\n\trepositoryformatversion = 0\n\tbare = false\n"
    )
    (git_dir / "HEAD").write_bytes(f"ref: {branch}\n".encode("ascii"))
    branch_path.write_bytes(f"{attestation.head_oid}\n".encode("ascii"))
    (git_dir / "shallow").write_bytes(
        f"{attestation.head_oid}\n".encode("ascii")
    )
    payload_root = tmp_path / "controller" / "source-payloads"
    payload_root.mkdir(parents=True)
    now = datetime.now(timezone.utc).isoformat()
    record = AttemptRecord(
        transaction_id="tx-recovery-001",
        task_id="task-001",
        subtask_id="subtask-001",
        attempt_id="attempt-001",
        repository_id=attestation.repository_id,
        canonical_root=attestation.canonical_root,
        canonical_ref=attestation.head_ref,
        base_revision=attestation.head_oid,
        candidate_kind="clone",
        clone_lease_id="clone-001",
        clone_path=str(clone),
        ownership_nonce="a" * 64,
        spec_digest="b" * 64,
        policy_digest="c" * 64,
        canonical_metadata_attestation_digest=attestation.attestation_digest,
        object_format="sha1",
        oid_length=40,
        ref_backend="files",
        candidate_branch=branch,
        checkpoint_message_digest="d" * 64,
        proposal_message_digest="e" * 64,
        commit_timestamp_seed=now,
        runner_kind="local",
        candidate_git_dir=str(git_dir),
        canonical_git_common_dir=attestation.git_common_dir,
        source_manifest_digest="1" * 64,
        source_object_closure_digest="2" * 64,
        source_snapshot_digest="3" * 64,
        source_parser_receipt_id="4" * 64,
        source_payload_root=str(payload_root),
        created_at=now,
        updated_at=now,
    )
    resources = _local_runtime_closure(record)
    record = _with_runtime_manifest(record, resources)
    journal = AttemptJournal(tmp_path / "controller" / "journal")
    journal.create(record)
    resource = next(
        item for item in resources if item.role is ResourceRole.MODEL_DRIVER
    )
    registered = journal.register_resources(record.transaction_id, resources)
    journal.transition(
        record.transaction_id,
        AttemptPhase.RUNNING,
        resource_lease_ids=tuple(
            f"{item.role.value}:{item.resource_id}" for item in registered
        ),
    )
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    process_token = processStartToken(child.pid)
    assert process_token is not None
    journal.transition_resource(
        record.transaction_id,
        resource.resource_id,
        ProcessResourceState.CREATED,
        pid=child.pid,
        process_group_id=child.pid,
        process_start_token=process_token,
    )
    journal.transition_resource(
        record.transaction_id,
        resource.resource_id,
        ProcessResourceState.STARTED,
        pid=child.pid,
        process_group_id=child.pid,
        process_start_token=process_token,
    )
    order: list[str] = []

    def quiesce(runtime: RuntimeResourceLease) -> bool:
        order.append(f"quiesce:{runtime.resource_id}")
        if runtime.resource_id == resource.resource_id:
            child.terminate()
            child.wait(timeout=10)
        return True

    def checkpoint(lease, proof, current) -> CloneRecoveryCheckpoint:
        assert journal.load_resources(current.transaction_id)[0].state is (
            ProcessResourceState.QUIESCED
        )
        assert proof.runtime_token is lease.runtime_token
        assert proof.resource_state_digest == runtimeResourceStateDigest(
            journal.load_resources(current.transaction_id)
        )
        order.append("checkpoint")
        return CloneRecoveryCheckpoint(
            checkpoint_revision="a" * 40,
            checkpoint_ref="refs/9to5/checkpoints/tx-recovery-001",
            candidate_snapshot_digest="b" * 64,
            parser_manifest_digest="c" * 64,
            blob_set_digest="d" * 64,
        )

    capability = object()
    recovery = CloneLeaseRecovery(
        journal=journal,
        recovery_lock_root=tmp_path / "controller" / "recovery-locks",
        process_capability=capability,
        quiesce_resource=quiesce,
        checkpoint_clone=checkpoint,
    )
    try:
        result = recovery.recover(record.transaction_id, process_capability=capability)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
    assert order[-1] == "checkpoint"
    assert f"quiesce:{resource.resource_id}" in order
    assert result.record.phase is AttemptPhase.CANDIDATE_CHECKPOINTED
    assert journal.load_resources(record.transaction_id)[0].state is (
        ProcessResourceState.COLLECTED
    )
    assert recovery.recover(
        record.transaction_id,
        process_capability=capability,
    ) == result
    assert order == [
        "quiesce:verifier-001",
        "quiesce:candidate-parser-001",
        "quiesce:model-driver-001",
        "quiesce:authority-watchdog-001",
        "checkpoint",
    ]


@pytest.mark.parametrize(
    ("role", "backend"),
    (
        (ResourceRole.MODEL_DRIVER, "local"),
        (ResourceRole.COMMAND_SANDBOX, "docker"),
    ),
)
def test_recovery_requires_cleanup_locator_proof_for_registered_partial_process(
    tmp_path: Path,
    role: ResourceRole,
    backend: str,
) -> None:
    journal, record = _recovery_attempt(
        tmp_path,
        transaction_id=f"tx-registered-{backend}",
        runner_kind="local" if backend == "local" else "docker",
    )
    requested = (
        _local_runtime_closure(record)
        if record.runner_kind == "local"
        else _docker_runtime_closure(record)
    )
    resource = next(item for item in requested if item.role is role)
    running, resources = _running_resources(journal, record, requested)
    cleanup_attempts: list[RuntimeResourceLease] = []
    capability = object()
    recovery = CloneLeaseRecovery(
        journal=journal,
        recovery_lock_root=tmp_path / "recovery-locks",
        process_capability=capability,
        quiesce_resource=lambda observed: cleanup_attempts.append(observed)
        or observed.resource_id != resource.resource_id,
        checkpoint_clone=lambda *_args: pytest.fail("checkpoint must not run"),
    )

    with pytest.raises(CloneRecoveryRefused, match="cleanup locator"):
        recovery._quiesce(running, resources)

    assert cleanup_attempts[-1] == resource
    observed_resource = next(
        item
        for item in journal.load_resources(record.transaction_id)
        if item.resource_id == resource.resource_id
    )
    assert observed_resource.state is (
        ProcessResourceState.REGISTERED
    )


def test_recovery_requires_destroy_proof_for_registered_partial_credential(
    tmp_path: Path,
) -> None:
    journal, record = _recovery_attempt(
        tmp_path,
        transaction_id="tx-registered-credential",
    )
    resources = _docker_runtime_closure(record)
    resource = next(
        item for item in resources if item.role is ResourceRole.CREDENTIAL_LEASE
    )
    journal.register_resources(record.transaction_id, resources)
    destroy_attempts: list[CredentialResourceState] = []
    capability = object()
    recovery = CloneLeaseRecovery(
        journal=journal,
        recovery_lock_root=tmp_path / "recovery-locks",
        process_capability=capability,
        quiesce_resource=lambda observed: destroy_attempts.append(
            observed.state
        )
        or False,
        checkpoint_clone=lambda *_args: pytest.fail("checkpoint must not run"),
    )

    with pytest.raises(CloneRecoveryRefused, match="sealed typed broker"):
        recovery._destroyCredential(record, resource)

    assert destroy_attempts == []
    observed_resource = next(
        item
        for item in journal.load_resources(record.transaction_id)
        if item.role is ResourceRole.CREDENTIAL_LEASE
    )
    assert observed_resource.state is (
        CredentialResourceState.REGISTERED
    )


def test_recovery_requires_exact_broker_destroyer_and_fresh_absence_verifier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, record = _recovery_attempt(
        tmp_path,
        transaction_id="tx-exact-credential-evidence",
    )
    resources = _docker_runtime_closure(record)
    resource = next(
        item for item in resources if item.role is ResourceRole.CREDENTIAL_LEASE
    )
    journal.register_resources(record.transaction_id, resources)
    process_capability = object()
    broker = CredentialBroker(
        metadata_root=tmp_path / "credential-store",
        secret_provider=lambda _provider: b"credential-goldstone",
        process_capability=process_capability,
        attempt_journal=journal,
        issuer_id=resource.issuer_id,
    )
    authority = broker.issueAuthority(
        process_capability=process_capability,
        resource=resource,
        transaction_id=resource.transaction_id,
        provider=resource.provider,
        deadline=resource.expires_at,
    )
    lease = broker.issue(resource=resource, authority=authority)
    issued = next(
        item
        for item in journal.load_resources(record.transaction_id)
        if item.resource_id == resource.resource_id
    )
    assert issued.secret_fingerprint == lease.metadata.secret_fingerprint
    destroyer = broker.channelDestroyer(
        process_capability=process_capability,
        resource=issued,
    )
    absence_verifier = broker.freshAbsenceVerifier(
        process_capability=process_capability,
        resource=issued,
    )
    events: list[str] = []
    broker_type = type(broker)
    original_guard = broker_type._channelGuard

    @contextmanager
    def observed_guard(self):
        with original_guard(self):
            events.append("guard-enter")
            try:
                yield
            finally:
                events.append("guard-exit")

    original_transition = AttemptJournal.transition_resource

    def observed_transition(
        self: AttemptJournal,
        transaction_id: str,
        resource_id: str,
        state: object,
        **changes: object,
    ):
        if state is CredentialResourceState.REVOKED_OR_EXPIRED:
            events.append("journal-revoked")
        elif state is CredentialResourceState.DESTROYED:
            events.append("journal-destroyed")
        return original_transition(
            self,
            transaction_id,
            resource_id,
            state,
            **changes,
        )

    monkeypatch.setattr(broker_type, "_channelGuard", observed_guard)
    monkeypatch.setattr(AttemptJournal, "transition_resource", observed_transition)
    recovery = CloneLeaseRecovery(
        journal=journal,
        recovery_lock_root=tmp_path / "recovery-locks",
        process_capability=process_capability,
        quiesce_resource=lambda _resource: pytest.fail(
            "generic process adapter must never receive a credential"
        ),
        credential_channel_destroyer=destroyer,
        credential_absence_verifier=absence_verifier,
        checkpoint_clone=lambda *_args: pytest.fail("checkpoint must not run"),
    )

    destroyed = recovery._destroyCredential(record, issued)

    assert destroyed.state is CredentialResourceState.DESTROYED
    assert destroyed.credential_destruction_receipt_digest
    assert destroyed.credential_destroyed_at
    assert events == [
        "guard-enter",
        "journal-revoked",
        "guard-exit",
        "guard-enter",
        "journal-destroyed",
        "guard-exit",
    ]


def test_registered_credential_recovery_fences_a_racing_stale_issue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, record = _recovery_attempt(
        tmp_path,
        transaction_id="tx-registered-credential-issue-race",
    )
    resources = _docker_runtime_closure(record)
    registered = next(
        item for item in resources if item.role is ResourceRole.CREDENTIAL_LEASE
    )
    journal.register_resources(record.transaction_id, resources)
    capability = object()
    derived: list[str] = []

    def derive(provider: str) -> bytes:
        derived.append(provider)
        return b"credential-goldstone"

    broker = CredentialBroker(
        metadata_root=tmp_path / "credential-store",
        secret_provider=derive,
        process_capability=capability,
        attempt_journal=journal,
        issuer_id=registered.issuer_id,
    )
    authority = broker.issueAuthority(
        process_capability=capability,
        resource=registered,
        transaction_id=registered.transaction_id,
        provider=registered.provider,
        deadline=registered.expires_at,
    )
    destroyer = broker.channelDestroyer(
        process_capability=capability,
        resource=registered,
    )
    recovery = CloneLeaseRecovery(
        journal=journal,
        recovery_lock_root=tmp_path / "recovery-locks",
        process_capability=capability,
        quiesce_resource=lambda _resource: pytest.fail(
            "generic process adapter must never receive a credential"
        ),
        credential_channel_destroyer=destroyer,
        credential_absence_verifier=broker.freshAbsenceVerifier(
            process_capability=capability,
            resource=registered,
        ),
        checkpoint_clone=lambda *_args: pytest.fail("checkpoint must not run"),
    )

    revoked_committed = threading.Event()
    release_recovery = threading.Event()
    issue_attempted_guard = threading.Event()
    issue_acquired_guard = threading.Event()
    original_transition = AttemptJournal.transition_resource
    original_broker_guard = broker._channelGuard

    def blocked_transition(
        self: AttemptJournal,
        transaction_id: str,
        resource_id: str,
        state: object,
        **changes: object,
    ):
        result = original_transition(
            self,
            transaction_id,
            resource_id,
            state,
            **changes,
        )
        if state is CredentialResourceState.REVOKED_OR_EXPIRED:
            revoked_committed.set()
            assert release_recovery.wait(timeout=5)
        return result

    @contextmanager
    def observed_issue_guard():
        if threading.current_thread().name == "stale-credential-issue":
            issue_attempted_guard.set()
        with original_broker_guard():
            if threading.current_thread().name == "stale-credential-issue":
                issue_acquired_guard.set()
            yield

    monkeypatch.setattr(AttemptJournal, "transition_resource", blocked_transition)
    monkeypatch.setattr(broker, "_channelGuard", observed_issue_guard)
    recovery_results: list[RuntimeResourceLease] = []
    recovery_errors: list[BaseException] = []
    issue_errors: list[BaseException] = []
    issued_leases: list[object] = []

    def recover_registered() -> None:
        try:
            recovery_results.append(
                recovery._destroyCredential(record, registered)
            )
        except BaseException as exc:
            recovery_errors.append(exc)

    def issue_stale_registration() -> None:
        try:
            issued_leases.append(
                broker.issue(resource=registered, authority=authority)
            )
        except BaseException as exc:
            issue_errors.append(exc)

    recovery_thread = threading.Thread(
        target=recover_registered,
        name="registered-credential-recovery",
    )
    issue_thread = threading.Thread(
        target=issue_stale_registration,
        name="stale-credential-issue",
    )
    recovery_thread.start()
    assert revoked_committed.wait(timeout=5)
    tombstone = json.loads(
        broker._path(registered.resource_id).read_text(encoding="utf-8")
    )
    assert tombstone["state"] == "revoked_or_expired"
    assert tombstone["secret_fingerprint"] == ""
    issue_thread.start()
    assert issue_attempted_guard.wait(timeout=5)
    acquired_before_recovery_released = issue_acquired_guard.wait(timeout=0.2)
    release_recovery.set()
    recovery_thread.join(timeout=5)
    issue_thread.join(timeout=5)

    assert not recovery_thread.is_alive()
    assert not issue_thread.is_alive()
    assert not acquired_before_recovery_released
    assert recovery_errors == []
    assert issued_leases == []
    assert len(issue_errors) == 1
    assert isinstance(issue_errors[0], CredentialBrokerRefused)
    assert derived == []
    assert recovery_results[0].state is CredentialResourceState.DESTROYED
    observed = next(
        item
        for item in journal.load_resources(record.transaction_id)
        if item.resource_id == registered.resource_id
    )
    assert observed.state is CredentialResourceState.DESTROYED
    assert not broker._channelPath(registered.secret_channel_id).exists()


def test_recovery_reuses_broker_terminal_receipt_after_prejournal_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, record = _recovery_attempt(
        tmp_path,
        transaction_id="tx-credential-prejournal-crash",
    )
    resources = _docker_runtime_closure(record)
    resource = next(
        item for item in resources if item.role is ResourceRole.CREDENTIAL_LEASE
    )
    journal.register_resources(record.transaction_id, resources)
    capability = object()
    broker = CredentialBroker(
        metadata_root=tmp_path / "credential-store",
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
    lease = broker.issue(resource=resource, authority=authority)
    issued = next(
        item
        for item in journal.load_resources(record.transaction_id)
        if item.resource_id == resource.resource_id
    )
    broker.revoke(lease)
    revoked = next(
        item
        for item in journal.load_resources(record.transaction_id)
        if item.resource_id == resource.resource_id
    )
    assert revoked.secret_fingerprint == issued.secret_fingerprint
    recovery = CloneLeaseRecovery(
        journal=journal,
        recovery_lock_root=tmp_path / "recovery-locks",
        process_capability=capability,
        quiesce_resource=lambda _resource: pytest.fail(
            "generic process adapter must never receive a credential"
        ),
        credential_channel_destroyer=broker.channelDestroyer(
            process_capability=capability,
            resource=revoked,
        ),
        credential_absence_verifier=broker.freshAbsenceVerifier(
            process_capability=capability,
            resource=revoked,
        ),
        checkpoint_clone=lambda *_args: pytest.fail("checkpoint must not run"),
    )
    real_transition = AttemptJournal.transition_resource
    crash_receipts = []

    def crash_before_journal_terminal(
        self: AttemptJournal,
        transaction_id: str,
        resource_id: str,
        state: object,
        **changes: object,
    ):
        if state is CredentialResourceState.DESTROYED and not crash_receipts:
            crash_receipts.append(changes["destruction_receipt"])
            raise RuntimeError("crash before journal DESTROYED")
        return real_transition(self, transaction_id, resource_id, state, **changes)

    with monkeypatch.context() as patch:
        patch.setattr(
            AttemptJournal,
            "transition_resource",
            crash_before_journal_terminal,
        )
        with pytest.raises(RuntimeError, match="before journal DESTROYED"):
            recovery._destroyCredential(record, revoked)

    still_revoked = next(
        item
        for item in journal.load_resources(record.transaction_id)
        if item.role is ResourceRole.CREDENTIAL_LEASE
    )
    assert still_revoked.state is CredentialResourceState.REVOKED_OR_EXPIRED
    destroyed = recovery._destroyCredential(record, still_revoked)
    replayed = recovery._destroyCredential(record, destroyed)

    assert destroyed == replayed
    assert (
        destroyed.credential_destruction_receipt_digest
        == crash_receipts[0].receipt_digest
    )
    assert destroyed.credential_destroyed_at == crash_receipts[0].destroyed_at


@pytest.mark.parametrize("untyped", [True, {}, lambda _resource: True])
def test_recovery_constructor_refuses_untyped_credential_evidence_adapters(
    tmp_path: Path,
    untyped: object,
) -> None:
    journal, _record_value = _recovery_attempt(
        tmp_path,
        transaction_id="tx-untyped-credential-evidence",
    )

    with pytest.raises(TypeError, match="credential.*typed|typed.*credential"):
        CloneLeaseRecovery(
            journal=journal,
            recovery_lock_root=tmp_path / "recovery-locks",
            process_capability=object(),
            quiesce_resource=lambda _resource: True,
            credential_channel_destroyer=untyped,  # type: ignore[arg-type]
            credential_absence_verifier=untyped,  # type: ignore[arg-type]
            checkpoint_clone=lambda *_args: pytest.fail("checkpoint must not run"),
        )


def test_cached_recovery_result_reprobes_credential_channel_absence(
    tmp_path: Path,
) -> None:
    journal, record = _recovery_attempt(
        tmp_path,
        transaction_id="tx-cached-credential-reprobe",
    )
    resources = _docker_runtime_closure(record)
    resource = next(
        item for item in resources if item.role is ResourceRole.CREDENTIAL_LEASE
    )
    journal.register_resources(record.transaction_id, resources)
    process_capability = object()
    broker = CredentialBroker(
        metadata_root=tmp_path / "credential-store",
        secret_provider=lambda _provider: b"credential-goldstone",
        process_capability=process_capability,
        attempt_journal=journal,
        issuer_id=resource.issuer_id,
    )
    authority = broker.issueAuthority(
        process_capability=process_capability,
        resource=resource,
        transaction_id=resource.transaction_id,
        provider=resource.provider,
        deadline=resource.expires_at,
    )
    lease = broker.issue(resource=resource, authority=authority)
    issued = next(
        item
        for item in journal.load_resources(record.transaction_id)
        if item.resource_id == resource.resource_id
    )
    broker.revoke(lease)
    revoked = next(
        item
        for item in journal.load_resources(record.transaction_id)
        if item.resource_id == resource.resource_id
    )
    assert revoked.secret_fingerprint == issued.secret_fingerprint
    recovery = CloneLeaseRecovery(
        journal=journal,
        recovery_lock_root=tmp_path / "recovery-locks",
        process_capability=process_capability,
        quiesce_resource=lambda _resource: pytest.fail(
            "generic process adapter must never receive a credential"
        ),
        credential_channel_destroyer=broker.channelDestroyer(
            process_capability=process_capability,
            resource=revoked,
        ),
        credential_absence_verifier=broker.freshAbsenceVerifier(
            process_capability=process_capability,
            resource=revoked,
        ),
        checkpoint_clone=lambda *_args: pytest.fail("checkpoint must not run"),
    )
    destroyed = recovery._destroyCredential(record, revoked)
    for process_resource in resources:
        if process_resource.role is not ResourceRole.CREDENTIAL_LEASE:
            journal.transition_resource(
                record.transaction_id,
                process_resource.resource_id,
                ProcessResourceState.QUIESCED,
            )
    checkpoint = CloneRecoveryCheckpoint(
        checkpoint_revision="a" * 40,
        checkpoint_ref="refs/9to5/checkpoints/tx-cached-credential-reprobe",
        candidate_snapshot_digest="b" * 64,
        parser_manifest_digest="c" * 64,
        blob_set_digest="d" * 64,
    )
    cached = CloneRecoveryResult(
        record=record,
        checkpoint=checkpoint,
        recovered_resource_ids=tuple(
            f"{item.role.value}:{item.resource_id}" for item in resources
        ),
    )
    recovery._results[record.transaction_id] = cached
    broker._channelPath(resource.secret_channel_id).write_bytes(b"recreated")

    with pytest.raises(CloneRecoveryRefused, match="destruction is unproven"):
        recovery.recover(
            record.transaction_id,
            process_capability=process_capability,
        )

    assert recovery._results[record.transaction_id] is cached
    assert destroyed.state is CredentialResourceState.DESTROYED


def test_recovery_proves_credential_destruction_before_destroyed_transition(
    tmp_path: Path,
) -> None:
    journal, record = _recovery_attempt(
        tmp_path,
        transaction_id="tx-issued-credential",
    )
    resources = _docker_runtime_closure(record)
    resource = next(
        item for item in resources if item.role is ResourceRole.CREDENTIAL_LEASE
    )
    journal.register_resources(record.transaction_id, resources)
    issued = journal.transition_resource(
        record.transaction_id,
        resource.resource_id,
        CredentialResourceState.ISSUED,
        secret_fingerprint="d" * 64,
    )
    proof_states: list[CredentialResourceState] = []

    def prove_revoke_but_not_destroy(observed: RuntimeResourceLease) -> bool:
        state = observed.state
        assert isinstance(state, CredentialResourceState)
        proof_states.append(state)
        return state is CredentialResourceState.ISSUED

    capability = object()
    recovery = CloneLeaseRecovery(
        journal=journal,
        recovery_lock_root=tmp_path / "recovery-locks",
        process_capability=capability,
        quiesce_resource=prove_revoke_but_not_destroy,
        checkpoint_clone=lambda *_args: pytest.fail("checkpoint must not run"),
    )

    with pytest.raises(CloneRecoveryRefused, match="sealed typed broker"):
        recovery._destroyCredential(record, issued)

    assert proof_states == []
    observed_resource = next(
        item
        for item in journal.load_resources(record.transaction_id)
        if item.role is ResourceRole.CREDENTIAL_LEASE
    )
    assert observed_resource.state is (
        CredentialResourceState.ISSUED
    )


def test_recovery_marks_registered_credential_destroyed_only_after_proof(
    tmp_path: Path,
) -> None:
    journal, record = _recovery_attempt(
        tmp_path,
        transaction_id="tx-destroyed-credential",
    )
    resources = _docker_runtime_closure(record)
    resource = next(
        item for item in resources if item.role is ResourceRole.CREDENTIAL_LEASE
    )
    journal.register_resources(record.transaction_id, resources)
    capability = object()
    broker = CredentialBroker(
        metadata_root=tmp_path / "credential-store",
        secret_provider=lambda _provider: (_ for _ in ()).throw(
            RuntimeError("crash after registered metadata")
        ),
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
    with pytest.raises(RuntimeError, match="registered metadata"):
        broker.issue(resource=resource, authority=authority)
    recovery = CloneLeaseRecovery(
        journal=journal,
        recovery_lock_root=tmp_path / "recovery-locks",
        process_capability=capability,
        quiesce_resource=lambda _observed: pytest.fail(
            "generic process adapter must never receive a credential"
        ),
        credential_channel_destroyer=broker.channelDestroyer(
            process_capability=capability,
            resource=resource,
        ),
        credential_absence_verifier=broker.freshAbsenceVerifier(
            process_capability=capability,
            resource=resource,
        ),
        checkpoint_clone=lambda *_args: pytest.fail("checkpoint must not run"),
    )

    destroyed = recovery._destroyCredential(record, resource)

    assert destroyed.state is CredentialResourceState.DESTROYED
    observed_resource = next(
        item
        for item in journal.load_resources(record.transaction_id)
        if item.role is ResourceRole.CREDENTIAL_LEASE
    )
    assert observed_resource.state is (
        CredentialResourceState.DESTROYED
    )


def test_recovery_never_destroys_credential_before_dependents_are_quiescent(
    tmp_path: Path,
) -> None:
    journal, record = _recovery_attempt(
        tmp_path,
        transaction_id="tx-live-credential-dependent",
    )
    requested = _docker_runtime_closure(record)
    credential = next(
        item for item in requested if item.role is ResourceRole.CREDENTIAL_LEASE
    )
    running, _resources = _running_resources(journal, record, requested)
    journal.transition_resource(
        record.transaction_id,
        credential.resource_id,
        CredentialResourceState.REVOKED_OR_EXPIRED,
    )
    observed = journal.load_resources(record.transaction_id)
    destroy_attempts: list[RuntimeResourceLease] = []
    capability = object()
    recovery = CloneLeaseRecovery(
        journal=journal,
        recovery_lock_root=tmp_path / "recovery-locks",
        process_capability=capability,
        quiesce_resource=lambda resource: destroy_attempts.append(resource) or True,
        checkpoint_clone=lambda *_args: pytest.fail("checkpoint must not run"),
    )

    with pytest.raises(CloneRecoveryRefused, match="process resource is not terminal"):
        recovery._collect(running, observed)

    assert destroy_attempts == []
    states = {
        resource.role: resource.state
        for resource in journal.load_resources(record.transaction_id)
    }
    assert states[ResourceRole.CREDENTIAL_LEASE] is (
        CredentialResourceState.REVOKED_OR_EXPIRED
    )
    assert states[ResourceRole.MODEL_DRIVER] is ProcessResourceState.REGISTERED


def test_recovery_quiesces_roles_in_exact_reverse_dependency_order(
    tmp_path: Path,
) -> None:
    journal, record = _recovery_attempt(
        tmp_path,
        transaction_id="tx-reverse-dependency-order",
    )
    requested = _docker_runtime_closure(record)
    running, canonical_resources = _running_resources(journal, record, requested)
    observed_roles: list[ResourceRole] = []
    capability = object()
    recovery = CloneLeaseRecovery(
        journal=journal,
        recovery_lock_root=tmp_path / "recovery-locks",
        process_capability=capability,
        quiesce_resource=lambda resource: observed_roles.append(resource.role) or True,
        checkpoint_clone=lambda *_args: pytest.fail("checkpoint must not run"),
    )

    with pytest.raises(CloneRecoveryRefused, match="sealed typed broker"):
        recovery._quiesce(running, canonical_resources)

    assert observed_roles == [
        ResourceRole.VERIFIER,
        ResourceRole.CANDIDATE_PARSER,
        ResourceRole.COMMAND_SANDBOX,
        ResourceRole.BROKER,
        ResourceRole.MODEL_DRIVER,
        ResourceRole.AUTHORITY_WATCHDOG,
    ]
    credential = next(
        item
        for item in journal.load_resources(record.transaction_id)
        if item.role is ResourceRole.CREDENTIAL_LEASE
    )
    assert credential.state is CredentialResourceState.REGISTERED


def test_recovery_teardown_order_follows_declared_dependencies_before_role_order(
    tmp_path: Path,
) -> None:
    _journal, record = _recovery_attempt(
        tmp_path,
        transaction_id="tx-dependency-overrides-role-order",
    )
    parser = _registered_process_resource(
        record,
        role=ResourceRole.CANDIDATE_PARSER,
        backend="local",
    )
    parser_identity = f"{parser.role.value}:{parser.resource_id}"
    driver = replace(
        _registered_process_resource(
            record,
            role=ResourceRole.MODEL_DRIVER,
            backend="local",
        ),
        depends_on=(parser_identity,),
    )

    ordered = worktree._dependencySafeResourceTeardownOrder((parser, driver))

    assert tuple(resource.role for resource in ordered) == (
        ResourceRole.MODEL_DRIVER,
        ResourceRole.CANDIDATE_PARSER,
    )


@pytest.mark.parametrize(
    ("case", "message"),
    (
        ("missing", "incomplete"),
        ("cycle", "cycle"),
        ("credential-child", "credential resource"),
    ),
)
def test_recovery_teardown_refuses_invalid_dependency_closures(
    tmp_path: Path,
    case: str,
    message: str,
) -> None:
    _journal, record = _recovery_attempt(
        tmp_path,
        transaction_id=f"tx-invalid-dependency-{case}",
    )
    parser = _registered_process_resource(
        record,
        role=ResourceRole.CANDIDATE_PARSER,
        backend="local",
    )
    driver = _registered_process_resource(
        record,
        role=ResourceRole.MODEL_DRIVER,
        backend="local",
    )
    parser_identity = f"{parser.role.value}:{parser.resource_id}"
    driver_identity = f"{driver.role.value}:{driver.resource_id}"
    if case == "missing":
        resources = (
            replace(driver, depends_on=("authority_watchdog:missing",)),
        )
    elif case == "cycle":
        resources = (
            replace(parser, depends_on=(driver_identity,)),
            replace(driver, depends_on=(parser_identity,)),
        )
    else:
        credential = replace(
            _registered_credential_resource(record),
            depends_on=(parser_identity,),
        )
        resources = (parser, credential)

    with pytest.raises(CloneRecoveryRefused, match=message):
        worktree._dependencySafeResourceTeardownOrder(resources)


def test_failed_resource_quiescence_preserves_clone_and_blocks_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = AttemptJournal(tmp_path / "journal")
    clone = tmp_path / "clone"
    clone.mkdir()
    goldstone = clone / "dirty.txt"
    goldstone.write_bytes(b"preserve")
    now = datetime.now(timezone.utc).isoformat()
    record = AttemptRecord(
        transaction_id="tx-failed-recovery",
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
        ownership_nonce="2" * 64,
        spec_digest="3" * 64,
        policy_digest="4" * 64,
        canonical_metadata_attestation_digest="5" * 64,
        object_format="sha1",
        oid_length=40,
        ref_backend="files",
        candidate_branch="refs/heads/9to5/candidates/tx-failed-recovery",
        checkpoint_message_digest="6" * 64,
        proposal_message_digest="7" * 64,
        commit_timestamp_seed=now,
        runner_kind="docker",
        candidate_git_dir=str(clone / ".git"),
        canonical_git_common_dir=str(tmp_path / "canonical" / ".git"),
        source_manifest_digest="8" * 64,
        source_object_closure_digest="9" * 64,
        source_snapshot_digest="a" * 64,
        source_parser_receipt_id="b" * 64,
        source_payload_root=str(tmp_path / "source-payloads"),
        created_at=now,
        updated_at=now,
    )
    resources = _docker_runtime_closure(record)
    record = _with_runtime_manifest(record, resources)
    journal.create(record)
    resource = next(
        item for item in resources if item.role is ResourceRole.COMMAND_SANDBOX
    )
    registered = journal.register_resources(record.transaction_id, resources)
    journal.transition(
        record.transaction_id,
        AttemptPhase.RUNNING,
        resource_lease_ids=tuple(
            f"{item.role.value}:{item.resource_id}" for item in registered
        ),
    )
    journal.transition_resource(
        record.transaction_id,
        resource.resource_id,
        ProcessResourceState.CREATED,
        container_id="d" * 64,
    )
    journal.transition_resource(
        record.transaction_id,
        resource.resource_id,
        ProcessResourceState.STARTED,
    )
    capability = object()
    effects: list[str] = []
    incomplete_recovery = CloneLeaseRecovery(
        journal=journal,
        recovery_lock_root=tmp_path / "incomplete-locks",
        process_capability=capability,
        quiesce_resource=lambda _resource: effects.append("quiesce") or True,
        checkpoint_clone=lambda *_args: effects.append("checkpoint"),
    )
    canonical_resources = journal.load_resources(record.transaction_id)
    running_record = journal.load(record.transaction_id)
    reversed_resources = tuple(reversed(canonical_resources))
    assert {
        f"{resource.role.value}:{resource.resource_id}"
        for resource in reversed_resources
    } == set(running_record.resource_lease_ids)
    with pytest.raises(CloneRecoveryRefused, match="differ"):
        incomplete_recovery._quiesce(
            running_record,
            reversed_resources,
        )
    assert effects == []
    with monkeypatch.context() as patch:
        patch.setattr(
            journal,
            "load_resources",
            lambda _transaction_id: (_ for _ in ()).throw(
                IncompleteResourceSet("intent only")
            ),
        )
        with pytest.raises(CloneRecoveryRefused, match="incomplete"):
            incomplete_recovery.recover(
                record.transaction_id,
                process_capability=capability,
            )
    assert effects == []
    assert journal.load(record.transaction_id).phase is AttemptPhase.RUNNING

    recovery = CloneLeaseRecovery(
        journal=journal,
        recovery_lock_root=tmp_path / "locks",
        process_capability=capability,
        quiesce_resource=lambda _resource: False,
        checkpoint_clone=lambda *_args: pytest.fail("checkpoint must not run"),
    )
    with pytest.raises(CloneRecoveryRefused, match="did not quiesce"):
        recovery.recover(record.transaction_id, process_capability=capability)
    assert goldstone.read_bytes() == b"preserve"
    assert journal.load(record.transaction_id).phase is AttemptPhase.RECOVERY_CONFLICT
    observed_resource = next(
        item
        for item in journal.load_resources(record.transaction_id)
        if item.resource_id == resource.resource_id
    )
    assert observed_resource.state is (
        ProcessResourceState.STARTED
    )
    with pytest.raises(CloneRecoveryRefused, match="not recoverable"):
        recovery.recover(record.transaction_id, process_capability=capability)
