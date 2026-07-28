"""Transactional CloneEnvironment never exposes a linked canonical checkout."""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from platform_core.core.galaxy_evidence import canonical_digest
from platform_core.runtime import candidate as candidate_mod
from platform_core.execution.backends import clone as clone_mod
from platform_core.execution.backends.clone import (
    CloneEnvironment,
    ClonePreparationArtifacts,
    TransactionalCloneKernel,
)
from platform_core.execution.environment import EnvironmentUnavailable
from platform_core.execution.object_parser import ParsedCandidateSnapshot
from platform_core.runtime.attempt_journal import (
    AttemptJournal,
    AttemptPhase,
    AttemptRecord,
    IncompleteResourceSet,
    JournalCorruption,
    MissingResourceSet,
)
from platform_core.runtime.candidate import (
    CandidateResult,
    CloneLease,
    CloneQuiescenceProof,
    ProcessResourceState,
    ResourceRole,
    RunnerKind,
    RuntimeResourceLease,
    StagingCoordinator,
    StagedRevisionLease,
    StagedRevisionRefused,
    runtimeResourceStateDigest,
)
from platform_core.runtime.git_object_writer import (
    CommitMetadata,
    VerificationRepositoryLease,
)
from platform_core.runtime.object_manifest import (
    ManifestEntry,
    ManifestPolicy,
    ObjectManifest,
)
from platform_core.runtime.receipts import PromotionAuthorization, PromotionReceipt

SHA_A = "a" * 40
SHA_B = "b" * 40
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64


def test_snapshot_admission_issuer_is_not_a_public_compatibility_surface() -> None:
    assert not hasattr(candidate_mod, "CloneSnapshotAdmissionIssuer")
    assert "CloneSnapshotAdmissionIssuer" not in candidate_mod.__all__


def test_reflection_cannot_compose_snapshot_issuer_without_kernel_initialization() -> None:
    reflected_kernel = object.__new__(TransactionalCloneKernel)

    with pytest.raises(StagedRevisionRefused, match="composition"):
        candidate_mod._createCloneSnapshotAdmissionIssuer(
            owner=reflected_kernel,
            process_capability=object(),
        )


def test_reflected_kernel_private_fields_cannot_forge_snapshot_authority(
    tmp_path: Path,
) -> None:
    lease = _private_clone(tmp_path)
    expected = ObjectManifest(
        expected_revision=lease.expected_base_revision,
        entries=(),
        attribute_rules=(),
        policy=_policy(),
    )
    coordinator = _FlowCoordinator(lease, expected, tmp_path / "controller")
    legitimate = _flow_kernel(tmp_path, lease, expected, coordinator)
    proof = legitimate.quiescence_provider(lease, _State(), {})
    reflected = object.__new__(TransactionalCloneKernel)
    capability = object()
    validation_seal = object()
    reflected._snapshot_process_capability = capability
    reflected._snapshot_composition_seal = object()
    reflected._snapshot_validation_seal = validation_seal
    reflected._snapshot_validations = {}
    reflected._lock = legitimate._lock
    validation = clone_mod._SnapshotJournalValidation(
        kernel=reflected,
        lease=lease,
        quiescence=proof,
        seal=validation_seal,
        _factory=clone_mod._SNAPSHOT_VALIDATION_FACTORY,
    )
    reflected._snapshot_validations[id(validation)] = (
        validation,
        lease,
        proof,
    )
    snapshot_root = tmp_path / "forged-reflected-snapshot"

    with pytest.raises(StagedRevisionRefused, match="composition|initialized"):
        issuer = candidate_mod._createCloneSnapshotAdmissionIssuer(
            owner=reflected,
            process_capability=capability,
        )
        admission = issuer.issue(
            lease,
            proof,
            owner=reflected,
            process_capability=capability,
            journal_validation=validation,
        )
        candidate_mod.snapshotCloneTree(
            lease,
            quiescence=proof,
            admission=admission,
            policy=expected.policy,
            snapshot_root=snapshot_root,
            expected=expected,
        )

    assert not snapshot_root.exists()


def test_snapshot_issuer_constructor_and_copied_kernel_are_not_composition(
    tmp_path: Path,
) -> None:
    lease = _private_clone(tmp_path)
    expected = ObjectManifest(
        expected_revision=lease.expected_base_revision,
        entries=(),
        attribute_rules=(),
        policy=_policy(),
    )
    coordinator = _FlowCoordinator(lease, expected, tmp_path / "controller")
    kernel = _flow_kernel(tmp_path, lease, expected, coordinator)
    copied_kernel = copy.copy(kernel)

    with pytest.raises(StagedRevisionRefused, match="composition|initialized"):
        candidate_mod._createCloneSnapshotAdmissionIssuer(
            owner=copied_kernel,
            process_capability=kernel._snapshot_process_capability,
        )
    with pytest.raises(StagedRevisionRefused, match="composition|issuer"):
        candidate_mod._CloneSnapshotAdmissionIssuer(
            owner=kernel,
            process_capability=kernel._snapshot_process_capability,
            _factory=candidate_mod._SNAPSHOT_ISSUER_FACTORY,
        )


def _private_clone(tmp_path: Path) -> CloneLease:
    canonical_git = tmp_path / "canonical" / ".git"
    canonical_git.mkdir(parents=True)
    checkout = tmp_path / "controller" / "checkouts" / "candidate" / "tx-001"
    git_dir = checkout / ".git"
    (git_dir / "objects" / "info").mkdir(parents=True)
    candidate_ref = git_dir / "refs" / "heads" / "9to5" / "candidates" / "tx-001"
    candidate_ref.parent.mkdir(parents=True)
    (git_dir / "config").write_text(
        "[core]\n\trepositoryformatversion = 0\n\tbare = false\n",
        encoding="utf-8",
    )
    (git_dir / "HEAD").write_bytes(
        b"ref: refs/heads/9to5/candidates/tx-001\n"
    )
    candidate_ref.write_bytes((SHA_A + "\n").encode("ascii"))
    (git_dir / "shallow").write_bytes((SHA_A + "\n").encode("ascii"))
    return CloneLease(
        transaction_id="tx-001",
        task_id="task-001",
        subtask_id="subtask-001",
        attempt_id="attempt-001",
        checkout_path=str(checkout),
        expected_base_revision=SHA_A,
        runner_kind=RunnerKind.LOCAL,
        candidate_branch="refs/heads/9to5/candidates/tx-001",
        repository_id=DIGEST_A,
        ownership_nonce=DIGEST_B,
        git_dir=str(git_dir),
        git_common_dir=str(git_dir),
        canonical_git_common_dir=str(canonical_git),
        closure_manifest_digest=DIGEST_C,
        shallow_root_revision=SHA_A,
        hardlink_count_verified=True,
        alternates_absent=True,
        remote_absent=True,
        linked_worktree_pointer_absent=True,
        registered_at=datetime.now(timezone.utc).isoformat(),
        runtime_token=object(),
    )


def _staged() -> StagedRevisionLease:
    return StagedRevisionLease(
        transaction_id="tx-001",
        task_id="task-001",
        subtask_id="subtask-001",
        attempt_id="attempt-001",
        runner_kind=RunnerKind.LOCAL,
        candidate_snapshot_digest=DIGEST_A,
        parser_manifest_digest=DIGEST_B,
        blob_set_digest=DIGEST_C,
        checkpoint_ref="refs/9to5/checkpoints/tx-001",
        checkpoint_revision=SHA_B,
        expected_target_revision=SHA_A,
        staged_ref="refs/9to5/staged/tx-001",
        proposed_revision=SHA_B,
        proposed_tree="c" * 40,
        proposed_diff_digest="d" * 64,
        staging_receipt_id="e" * 64,
        object_closure_digest="f" * 64,
        cleanup_token=object(),
    )


def _authorization() -> PromotionAuthorization:
    return PromotionAuthorization(
        transaction_id="tx-001",
        task_id="task-001",
        subtask_id="subtask-001",
        staging_receipt_id="e" * 64,
        verification_receipt_id="1" * 64,
        review_receipt_id="2" * 64,
        proposed_revision=SHA_B,
        proposed_tree="c" * 40,
        proposed_diff_digest="d" * 64,
        spec_digest="6" * 64,
        policy_digest="7" * 64,
    )


class _Kernel:
    def __init__(self, verification_dir: Path) -> None:
        self.staged = _staged()
        self.verification_dir = verification_dir
        self.released = False
        self.finalization = None

    def prepare(self, lease, *, task_state, subtask):
        del lease, task_state, subtask
        self.verification_dir.mkdir(parents=True)
        return ClonePreparationArtifacts(
            staged=self.staged,
            verification_dir=str(self.verification_dir),
            verification_backend="credentialless-container",
        )

    def intact(self, staged):
        return staged is self.staged

    def promote(self, staged, authorization, landing_authority):
        del authorization, landing_authority
        assert staged is self.staged
        return PromotionReceipt(
            transaction_id="tx-001",
            staging_receipt_id="e" * 64,
            verification_receipt_id="1" * 64,
            review_receipt_id="2" * 64,
            expected_revision=SHA_A,
            observed_revision=SHA_A,
            proposed_revision=SHA_B,
            resulting_revision=SHA_B,
            canonical_index_revision="c" * 40,
            canonical_tree_revision="c" * 40,
            custom_lock_owner_digest="3" * 64,
            index_fence_owner_digest="4" * 64,
            cas_result="moved",
            intent_ref="refs/9to5/promotion-intent/tx-001",
            intent_oid=SHA_B,
            materialization_result="exact",
            postcondition_digest="5" * 64,
        )

    def reject(self, staged):
        assert staged is self.staged
        return CandidateResult(
            entered=True,
            staged=True,
            promoted=False,
            removed=True,
            expected_revision=SHA_A,
            observed_revision=SHA_A,
            resulting_revision=SHA_A,
            checkpoint_revision=SHA_B,
            candidate_snapshot_digest=DIGEST_A,
            parser_manifest_digest=DIGEST_B,
            staged_tree_digest=DIGEST_C,
            checkpoint_ref="refs/9to5/checkpoints/tx-001",
            staged_ref="refs/9to5/staged/tx-001",
            quarantine_ref="refs/9to5/quarantine/tx-001",
            error="rejected",
            cleanup_error="",
        )

    def checkpoint(self, lease, *, task_state, subtask):
        del lease, task_state, subtask
        return {"available": True, "checkpoint_ref": self.staged.checkpoint_ref}

    def finalize(self, staged, finalization):
        assert staged is self.staged
        self.finalization = finalization
        return object()

    def release(self, lease):
        del lease
        self.released = True


class _State:
    task_id = "task-001"


def test_clone_environment_fails_closed_without_an_owned_lease_factory(tmp_path: Path) -> None:
    env = CloneEnvironment()
    assert env.healthCheck() is False
    with pytest.raises(EnvironmentUnavailable):
        env.provision(
            task_state=_State(),
            subtask={"subtask_id": "subtask-001"},
            base_dir=str(tmp_path),
            policy=None,
        )


def test_clone_handle_is_self_contained_and_staged_completion_is_uniform(
    tmp_path: Path,
) -> None:
    lease = _private_clone(tmp_path)
    kernel = _Kernel(tmp_path / "controller" / "verification" / "tx-001")
    env = CloneEnvironment(clone_factory=lambda **_: lease, kernel=kernel)

    handle = env.provision(
        task_state=_State(),
        subtask={"subtask_id": "subtask-001"},
        base_dir=str(tmp_path / "canonical"),
        policy=None,
    )
    assert handle.work_dir == lease.checkout_path
    assert handle.backend == "clone"
    assert handle.requires_canonical_landing
    assert handle.meta["linked_worktree"] is False
    assert handle.runtime_token is lease

    prepared = env.prepareChanges(
        handle,
        task_state=_State(),
        subtask={"subtask_id": "subtask-001"},
    )
    assert prepared.accepted
    assert prepared.proposed_revision == SHA_B
    assert env.preparedChangesIntact(prepared)

    final = env.completeChanges(
        prepared,
        promote=True,
        authorization=_authorization(),
        landing_authority=object(),
    )
    assert final.succeeded
    assert final.promotion_transaction_id == "tx-001"
    assert final.resulting_revision == SHA_B
    assert final.journal_phase == "promoted"
    assert kernel.finalization is final

    env.teardown(handle)
    assert kernel.released


def test_handle_from_lease_rejects_base_revision_substitution(tmp_path: Path) -> None:
    lease = _private_clone(tmp_path)
    env = CloneEnvironment(clone_factory=lambda **_: lease, kernel=_Kernel(tmp_path / "v"))
    with pytest.raises(EnvironmentUnavailable, match="revision"):
        env.handleFromLease(
            lease,
            base_dir=str(tmp_path / "canonical"),
            expected_target_revision=SHA_B,
        )


def _policy() -> ManifestPolicy:
    return ManifestPolicy(
        reserved_roots=("state/tasks",),
        max_files=10,
        max_total_bytes=4096,
        max_file_bytes=2048,
        max_depth=8,
        max_path_bytes=240,
    )


class _FlowParser:
    def parseCandidateSnapshot(self, *, snapshot, expected):
        entries = []
        for item in snapshot.entries:
            payload = (
                snapshot.blob_root / item.blob_sha256[:2] / item.blob_sha256
            ).read_bytes()
            frame = b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload
            entries.append(
                ManifestEntry(
                    path=item.path,
                    mode=item.mode,
                    blob_oid=hashlib.sha1(frame, usedforsecurity=False).hexdigest(),
                    blob_sha256=item.blob_sha256,
                    framed_object_sha256=hashlib.sha256(frame).hexdigest(),
                    size=item.size,
                )
            )
        proposed = ObjectManifest(
            expected_revision=expected.expected_revision,
            entries=tuple(entries),
            attribute_rules=expected.attribute_rules,
            policy=expected.policy,
        )
        return ParsedCandidateSnapshot(
            transaction_id=snapshot.transaction_id,
            manifest=proposed,
            snapshot_digest=snapshot.snapshot_digest,
            blob_set_digest=snapshot.blob_set_digest,
            diff_digest="4" * 64,
            parser_version_digest="5" * 64,
            receipt_id="6" * 64,
            raw_result=b"result\n",
            container_network_allowed=False,
        )


class _FlowWriter:
    def __init__(self, verification_root: Path) -> None:
        self.verification_root = verification_root

    def writeRevision(self, *, manifest, metadata):
        del metadata
        return SimpleNamespace(
            commit_oid=SHA_B,
            tree_oid="c" * 40,
            object_closure_digest="f" * 64,
            proposed_index_digest="7" * 64,
            manifest_digest=manifest.manifest_digest,
        )

    def createVerificationRepository(
        self,
        *,
        transaction_id,
        checkout_root,
        manifest,
        receipt,
        forbidden_roots,
    ):
        del forbidden_roots
        checkout = Path(checkout_root)
        (checkout / ".git").mkdir(parents=True)
        return VerificationRepositoryLease(
            transaction_id=transaction_id,
            checkout_path=str(checkout),
            git_dir=str(checkout / ".git"),
            proposed_revision=receipt.commit_oid,
            proposed_tree=receipt.tree_oid,
            manifest_digest=manifest.manifest_digest,
            object_closure_digest=receipt.object_closure_digest,
            proposed_index_digest=receipt.proposed_index_digest,
            shallow_root_revision=receipt.commit_oid,
            verification_branch=f"refs/heads/9to5/verification/{transaction_id}",
            runtime_token=object(),
        )


class _FlowCoordinator:
    def __init__(self, lease: CloneLease, expected: ObjectManifest, root: Path) -> None:
        policy_digest = canonical_digest(
            {"attribute_rules": [], "policy": expected.policy.toDict()}
        )
        self.attestation = SimpleNamespace(
            repository_id=lease.repository_id,
            canonical_root=str(Path(lease.canonical_git_common_dir).parent),
            head_oid=lease.expected_base_revision,
        )
        now = datetime.now(timezone.utc).isoformat()
        watchdog = RuntimeResourceLease(
            resource_id="watchdog-001",
            run_id="run-001",
            transaction_id=lease.transaction_id,
            controller_scope_id="controller-001",
            role=ResourceRole.AUTHORITY_WATCHDOG,
            backend="local",
            ownership_nonce=lease.ownership_nonce,
            state=ProcessResourceState.REGISTERED,
            cleanup_locator_digest="1" * 64,
            pid=0,
            process_group_id=0,
            container_id="",
            image_digest="",
            entrypoint_digest="2" * 64,
            mount_digest="3" * 64,
            environment_digest="4" * 64,
            security_profile_digest="5" * 64,
            created_at=now,
            updated_at=now,
        )
        driver = RuntimeResourceLease(
            **(
                watchdog.__dict__
                | {
                    "resource_id": "driver-001",
                    "role": ResourceRole.MODEL_DRIVER,
                    "cleanup_locator_digest": "6" * 64,
                    "depends_on": ("authority_watchdog:watchdog-001",),
                }
            )
        )
        parser = RuntimeResourceLease(
            **(
                watchdog.__dict__
                | {
                    "resource_id": "parser-001",
                    "role": ResourceRole.CANDIDATE_PARSER,
                    "backend": "docker",
                    "cleanup_locator_digest": "7" * 64,
                    "image_digest": "8" * 64,
                    "depends_on": (
                        "authority_watchdog:watchdog-001",
                        "model_driver:driver-001",
                    ),
                }
            )
        )
        verifier = RuntimeResourceLease(
            **(
                watchdog.__dict__
                | {
                    "resource_id": "verifier-001",
                    "role": ResourceRole.VERIFIER,
                    "backend": "docker",
                    "cleanup_locator_digest": "9" * 64,
                    "image_digest": "a" * 64,
                    "depends_on": ("candidate_parser:parser-001",),
                }
            )
        )
        registered = tuple(
            sorted(
                (watchdog, driver, parser, verifier),
                key=lambda item: f"{item.role.value}:{item.resource_id}",
            )
        )
        manifest_json = json.dumps(
            {
                "resources": [
                    {
                        "backend": resource.backend,
                        "depends_on": list(resource.depends_on),
                        "resource_identity": (
                            f"{resource.role.value}:{resource.resource_id}"
                        ),
                    }
                    for resource in registered
                ],
                "runner_kind": "local",
                "schema": "galaxy.runtime-resource-manifest/v1",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        record = AttemptRecord(
            transaction_id=lease.transaction_id,
            task_id=lease.task_id,
            subtask_id=lease.subtask_id,
            attempt_id=lease.attempt_id,
            repository_id=lease.repository_id,
            canonical_root=str(Path(lease.canonical_git_common_dir).parent),
            canonical_ref="refs/heads/main",
            base_revision=lease.expected_base_revision,
            candidate_kind="clone",
            clone_lease_id="clone-001",
            clone_path=lease.checkout_path,
            ownership_nonce=lease.ownership_nonce,
            spec_digest="b" * 64,
            policy_digest=policy_digest,
            canonical_metadata_attestation_digest="c" * 64,
            object_format="sha1",
            oid_length=40,
            ref_backend="files",
            candidate_branch=lease.candidate_branch,
            checkpoint_message_digest="d" * 64,
            proposal_message_digest="e" * 64,
            commit_timestamp_seed=now,
            runner_kind="local",
            candidate_git_dir=lease.git_dir,
            canonical_git_common_dir=lease.canonical_git_common_dir,
            source_manifest_digest="f" * 64,
            source_object_closure_digest="1" * 64,
            source_snapshot_digest="2" * 64,
            source_parser_receipt_id="3" * 64,
            source_payload_root=str(root / "source-payload"),
            created_at=now,
            updated_at=now,
            runtime_resource_manifest_json=manifest_json,
            runtime_resource_manifest_digest=hashlib.sha256(
                manifest_json.encode("utf-8")
            ).hexdigest(),
        )
        journal = AttemptJournal(root / "journal")
        journal.create(record)
        journal.register_resources(lease.transaction_id, registered)
        for resource in registered:
            journal.transition_resource(
                lease.transaction_id,
                resource.resource_id,
                ProcessResourceState.QUIESCED,
            )
        self.resources = journal.load_resources(lease.transaction_id)
        resource_ids = tuple(
            f"{resource.role.value}:{resource.resource_id}"
            for resource in self.resources
        )
        journal.transition(
            lease.transaction_id,
            AttemptPhase.RUNNING,
            resource_lease_ids=resource_ids,
        )
        self.journal = journal
        self.writer = _FlowWriter(root / "verification")
        self.request = None
        self.staged = None

    def prepareStagedRevision(self, request):
        self.request = request
        self.staged = StagedRevisionLease(
            transaction_id=request.transaction_id,
            task_id=request.task_id,
            subtask_id=request.subtask_id,
            attempt_id=request.attempt_id,
            runner_kind=request.runner_kind,
            candidate_snapshot_digest=request.snapshot.snapshot_digest,
            parser_manifest_digest=request.parsed.manifest.manifest_digest,
            blob_set_digest=request.snapshot.blob_set_digest,
            checkpoint_ref=f"refs/9to5/checkpoints/{request.transaction_id}",
            checkpoint_revision=SHA_B,
            expected_target_revision=request.expected_manifest.expected_revision,
            staged_ref=f"refs/9to5/staged/{request.transaction_id}",
            proposed_revision=SHA_B,
            proposed_tree="c" * 40,
            proposed_diff_digest=request.parsed.diff_digest,
            staging_receipt_id="e" * 64,
            object_closure_digest="f" * 64,
            cleanup_token=request.cleanup_token,
        )
        return self.staged

    def stagedRevisionIntact(self, request, staged):
        return request is self.request and staged is self.staged

    def promoteStagedRevision(self, staged, authorization, landing_authority):
        del staged, authorization, landing_authority
        raise AssertionError("promotion is covered by staged-revision tests")

    def rejectStagedRevision(self, staged, *, reason):
        del staged, reason
        raise AssertionError("rejection is covered by staged-revision tests")


def _flow_kernel(
    tmp_path: Path,
    lease: CloneLease,
    expected: ObjectManifest,
    coordinator: _FlowCoordinator,
    *,
    resource_state_digest: str | None = None,
    observed_at: str | None = None,
    all_quiesced: bool = True,
) -> TransactionalCloneKernel:
    metadata = CommitMetadata(
        author_name="GALAXY Kernel",
        author_email="kernel@example.invalid",
        committer_name="GALAXY Kernel",
        committer_email="kernel@example.invalid",
        timestamp=1_700_000_000,
        timezone="+0000",
        message="transaction tx-001\n",
    )
    return TransactionalCloneKernel(
        parser=_FlowParser(),
        snapshot_root=tmp_path / "controller" / "snapshots",
        verification_root=tmp_path / "controller" / "verification",
        expected_manifest_provider=lambda *_: expected,
        quiescence_provider=lambda candidate, *_: CloneQuiescenceProof(
            transaction_id=candidate.transaction_id,
            attempt_id=candidate.attempt_id,
            resource_ids=tuple(
                f"{resource.role.value}:{resource.resource_id}"
                for resource in coordinator.resources
            ),
            resource_state_digest=(
                resource_state_digest
                or runtimeResourceStateDigest(coordinator.resources)
            ),
            all_quiesced=all_quiesced,
            observed_at=(
                observed_at or datetime.now(timezone.utc).isoformat()
            ),
            runtime_token=candidate.runtime_token,
        ),
        commit_metadata_provider=lambda *_: metadata,
        coordinator_factory=lambda *_: cast(StagingCoordinator, coordinator),
    )


class _AdmissionCaptured(RuntimeError):
    pass


def _capture_legitimate_snapshot_admission(
    monkeypatch: pytest.MonkeyPatch,
    kernel: TransactionalCloneKernel,
    lease: CloneLease,
) -> tuple[Any, CloneQuiescenceProof]:
    captured: dict[str, object] = {}

    def capture(
        observed_lease,
        *,
        quiescence,
        admission,
        **_kwargs,
    ):
        captured["lease"] = observed_lease
        captured["quiescence"] = quiescence
        captured["admission"] = admission
        raise _AdmissionCaptured("admission captured before snapshot I/O")

    with monkeypatch.context() as patch:
        patch.setattr(clone_mod, "snapshotCloneTree", capture)
        with pytest.raises(_AdmissionCaptured, match="before snapshot I/O"):
            kernel.prepare(lease, task_state=_State(), subtask={})
    assert captured["lease"] is lease
    return (
        cast(Any, captured["admission"]),
        cast(CloneQuiescenceProof, captured["quiescence"]),
    )


def test_reflection_cannot_issue_snapshot_without_fresh_journal_validation(
    tmp_path: Path,
) -> None:
    lease = _private_clone(tmp_path)
    expected = ObjectManifest(
        expected_revision=lease.expected_base_revision,
        entries=(),
        attribute_rules=(),
        policy=_policy(),
    )
    coordinator = _FlowCoordinator(lease, expected, tmp_path / "controller")
    kernel = _flow_kernel(tmp_path, lease, expected, coordinator)
    proof = kernel.quiescence_provider(lease, _State(), {})

    with pytest.raises(StagedRevisionRefused, match="journal validation"):
        kernel._snapshot_admission_issuer.issue(
            lease,
            proof,
            owner=kernel,
            process_capability=kernel._snapshot_process_capability,
        )


def test_snapshot_issuer_refuses_a_nonquiesced_kernel_proof(
    tmp_path: Path,
) -> None:
    lease = _private_clone(tmp_path)
    expected = ObjectManifest(
        expected_revision=lease.expected_base_revision,
        entries=(),
        attribute_rules=(),
        policy=_policy(),
    )
    coordinator = _FlowCoordinator(lease, expected, tmp_path / "controller")
    kernel = _flow_kernel(
        tmp_path,
        lease,
        expected,
        coordinator,
        all_quiesced=False,
    )

    with pytest.raises(StagedRevisionRefused, match="quiescence"):
        kernel.prepare(lease, task_state=_State(), subtask={})


def test_snapshot_validation_reloads_an_exact_attempt_journal(
    tmp_path: Path,
) -> None:
    lease = _private_clone(tmp_path)
    expected = ObjectManifest(
        expected_revision=lease.expected_base_revision,
        entries=(),
        attribute_rules=(),
        policy=_policy(),
    )
    coordinator = _FlowCoordinator(lease, expected, tmp_path / "controller")
    exact_journal = coordinator.journal
    setattr(
        coordinator,
        "journal",
        SimpleNamespace(
            root=exact_journal.root,
            load=exact_journal.load,
            load_resources=exact_journal.load_resources,
        ),
    )
    kernel = _flow_kernel(tmp_path, lease, expected, coordinator)

    with pytest.raises(EnvironmentUnavailable, match="exact.*journal"):
        kernel.prepare(lease, task_state=_State(), subtask={})


def test_snapshot_admission_rejects_construction_copy_replace_and_reflection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lease = _private_clone(tmp_path)
    expected = ObjectManifest(
        expected_revision=lease.expected_base_revision,
        entries=(),
        attribute_rules=(),
        policy=_policy(),
    )
    coordinator = _FlowCoordinator(lease, expected, tmp_path / "controller")
    kernel = _flow_kernel(tmp_path, lease, expected, coordinator)
    admission, quiescence = _capture_legitimate_snapshot_admission(
        monkeypatch,
        kernel,
        lease,
    )
    admission_type = type(admission)

    with pytest.raises(StagedRevisionRefused, match="sealed issuer"):
        admission_type(
            lease=lease,
            quiescence=quiescence,
            issuer=admission._issuer,
            _factory=object(),
        )
    with pytest.raises(TypeError):
        dataclasses.replace(admission)

    constructed = admission_type(
        lease=lease,
        quiescence=quiescence,
        issuer=admission._issuer,
        _factory=candidate_mod._SNAPSHOT_ADMISSION_FACTORY,
    )
    reflected = object.__new__(admission_type)
    for slot in admission_type.__slots__:
        object.__setattr__(reflected, slot, getattr(admission, slot))
    for label, forged in (
        ("constructor-bypass", constructed),
        ("shallow-copy", copy.copy(admission)),
        ("reflected-copy", reflected),
    ):
        with pytest.raises(StagedRevisionRefused, match="binding differs"):
            candidate_mod.snapshotCloneTree(
                lease,
                quiescence=quiescence,
                admission=forged,
                policy=expected.policy,
                snapshot_root=tmp_path / "controller" / label,
                expected=expected,
            )

    snapshot = candidate_mod.snapshotCloneTree(
        lease,
        quiescence=quiescence,
        admission=admission,
        policy=expected.policy,
        snapshot_root=tmp_path / "controller" / "accepted-admission",
        expected=expected,
    )
    assert snapshot.transaction_id == lease.transaction_id
    with pytest.raises(StagedRevisionRefused, match="consumed"):
        candidate_mod.snapshotCloneTree(
            lease,
            quiescence=quiescence,
            admission=admission,
            policy=expected.policy,
            snapshot_root=tmp_path / "controller" / "replayed-admission",
            expected=expected,
        )


def test_snapshot_validation_freshly_probes_every_journaled_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lease = _private_clone(tmp_path)
    expected = ObjectManifest(
        expected_revision=lease.expected_base_revision,
        entries=(),
        attribute_rules=(),
        policy=_policy(),
    )
    coordinator = _FlowCoordinator(lease, expected, tmp_path / "controller")
    observed: list[str] = []
    real_probe = clone_mod.runtimeResourceIsQuiescent

    def observe_probe(resource, **kwargs):
        observed.append(f"{resource.role.value}:{resource.resource_id}")
        return real_probe(resource, **kwargs)

    monkeypatch.setattr(clone_mod, "runtimeResourceIsQuiescent", observe_probe)
    kernel = _flow_kernel(tmp_path, lease, expected, coordinator)

    kernel.prepare(lease, task_state=_State(), subtask={})

    assert observed == [
        f"{resource.role.value}:{resource.resource_id}"
        for resource in coordinator.resources
    ]


def test_transactional_kernel_orders_quiesced_snapshot_parse_stage_and_verify(
    tmp_path: Path,
) -> None:
    lease = _private_clone(tmp_path)
    checkout = Path(lease.checkout_path)
    (checkout / "changed.txt").write_bytes(b"changed\n")
    expected = ObjectManifest(
        expected_revision=lease.expected_base_revision,
        entries=(),
        attribute_rules=(),
        policy=_policy(),
    )
    coordinator = _FlowCoordinator(lease, expected, tmp_path / "controller")
    kernel = _flow_kernel(tmp_path, lease, expected, coordinator)

    artifacts = kernel.prepare(lease, task_state=_State(), subtask={})

    assert artifacts.staged.candidate_snapshot_digest
    assert coordinator.request is not None
    assert artifacts.staged.parser_manifest_digest == coordinator.request.parsed.manifest.manifest_digest
    assert artifacts.verification_dir == str(
        tmp_path / "controller" / "verification" / lease.transaction_id
    )
    assert kernel.intact(artifacts.staged)


@pytest.mark.parametrize(
    ("digest", "observed_at", "message"),
    [
        ("0" * 64, None, "exact runtime resource states"),
        (
            None,
            "2000-01-01T00:00:00+00:00",
            "predates a runtime resource state",
        ),
    ],
)
def test_transactional_kernel_rejects_self_asserted_quiescence(
    tmp_path: Path,
    digest: str | None,
    observed_at: str | None,
    message: str,
) -> None:
    lease = _private_clone(tmp_path)
    expected = ObjectManifest(
        expected_revision=lease.expected_base_revision,
        entries=(),
        attribute_rules=(),
        policy=_policy(),
    )
    coordinator = _FlowCoordinator(lease, expected, tmp_path / "controller")
    kernel = _flow_kernel(
        tmp_path,
        lease,
        expected,
        coordinator,
        resource_state_digest=digest,
        observed_at=observed_at,
    )

    with pytest.raises(EnvironmentUnavailable, match=message):
        kernel.prepare(lease, task_state=_State(), subtask={})


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (MissingResourceSet("missing"), "resource closure is missing"),
        (IncompleteResourceSet("intent only"), "resource closure is incomplete"),
        (JournalCorruption("bad completion"), "resource closure is corrupt"),
    ],
)
def test_transactional_kernel_distinguishes_resource_closure_failure_before_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    message: str,
) -> None:
    lease = _private_clone(tmp_path)
    expected = ObjectManifest(
        expected_revision=lease.expected_base_revision,
        entries=(),
        attribute_rules=(),
        policy=_policy(),
    )
    coordinator = _FlowCoordinator(lease, expected, tmp_path / "controller")
    original_load_resources = AttemptJournal.load_resources

    def failed_load_resources(journal, transaction_id):
        if journal is coordinator.journal:
            raise failure
        return original_load_resources(journal, transaction_id)

    monkeypatch.setattr(AttemptJournal, "load_resources", failed_load_resources)
    kernel = _flow_kernel(tmp_path, lease, expected, coordinator)

    with pytest.raises(EnvironmentUnavailable, match=message):
        kernel.prepare(lease, task_state=_State(), subtask={})
    assert coordinator.request is None
