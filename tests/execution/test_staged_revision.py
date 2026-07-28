"""Object-only staged revision preparation and integrity tests."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest

from platform_core.core.galaxy_evidence import canonical_digest
from platform_core.core.fsio import NativeDirectoryHandle
from platform_core.execution.authority_watchdog import AuthorityWatchdog
from platform_core.execution.object_parser import (
    CandidateSnapshot,
    ObjectParser,
    ObjectParserImage,
    ObjectParserProcessResult,
    SnapshotEntry,
)
from platform_core.runtime import candidate as candidate_mod
from platform_core.runtime.bootstrap_scope import CapsuleBootstrapScope
from platform_core.runtime.attempt_journal import (
    AttemptJournal,
    AttemptPhase,
    AttemptRecord,
)
from platform_core.runtime.candidate import (
    ProcessResourceState,
    PromotionCrashInjected,
    PromotionRecoveryRequired,
    PromotionRefused,
    ResourceRole,
    RunnerKind,
    RuntimeResourceLease,
    StagedRevisionRefused,
    StagingCoordinator,
    StagingRequest,
)
from platform_core.runtime.canonical_repo import attestCanonicalRepository
from platform_core.runtime.git_object_writer import CommitMetadata, GitObjectWriter
from platform_core.runtime.loose_refs import LooseRefStore, RefError
from platform_core.runtime.object_manifest import (
    ManifestEntry,
    ManifestPolicy,
    ObjectManifest,
)
from platform_core.runtime.receipts import (
    PromotionAuthorization,
    PromotionReceipt,
    ReceiptStore,
    ReconciliationReceipt,
    ReviewDecision,
    ReviewReceipt,
    RevisionVerificationReceipt,
    StagingReceipt,
)
from platform_core.runtime.sha1dc import qualifyGitSha1dc

ENTRYPOINT = Path("containers/galaxy/object_parser_entrypoint.py").resolve()
IMAGE_DIGEST = "c8943a7221ca6a2850f8ef60ce9bcfb8da5caff2e4d4b48cee5dec2005a102a3"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    return result.stdout.strip()


def _blob_entry(path: str, payload: bytes) -> ManifestEntry:
    frame = b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload
    return ManifestEntry(
        path=path,
        mode=0o100644,
        blob_oid=hashlib.sha1(frame, usedforsecurity=False).hexdigest(),
        blob_sha256=hashlib.sha256(payload).hexdigest(),
        framed_object_sha256=hashlib.sha256(frame).hexdigest(),
        size=len(payload),
    )


def _put(root: Path, payload: bytes) -> str:
    digest = hashlib.sha256(payload).hexdigest()
    target = root / digest[:2] / digest
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return digest


def _with_runtime_manifest(
    record: AttemptRecord,
    resources: tuple[RuntimeResourceLease, ...],
) -> AttemptRecord:
    """Bind the admission manifest RUNNING requires, matching the journal form."""

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
        runtime_resource_manifest_digest=hashlib.sha256(
            raw.encode("utf-8")
        ).hexdigest(),
    )


def _fixture(
    tmp_path: Path,
    *,
    expected_values: dict[str, bytes] | None = None,
    proposed_values: dict[str, bytes] | None = None,
    info_exclude_pattern: str | None = None,
    existing_repo: Path | None = None,
    transaction_id: str = "tx-stage-001",
    attempt_id: str = "attempt-001",
    proposed_modes: dict[str, int] | None = None,
    landing_authority_issuer: candidate_mod.LandingAuthorityIssuer | None = None,
    run_admission: candidate_mod.RunAdmissionAuthority | None = None,
    authority_clock: Callable[[], datetime] | None = None,
    authority_deadline: datetime | None = None,
):
    tmp_path.mkdir(parents=True, exist_ok=True)
    base_values = (
        expected_values
        if expected_values is not None
        else {"tracked.txt": b"base\n"}
    )
    repo = existing_repo if existing_repo is not None else tmp_path / "canonical"
    if existing_repo is None:
        repo.mkdir()
        _git(repo, "-c", "init.defaultBranch=main", "init")
        _git(repo, "config", "user.name", "Kernel")
        _git(repo, "config", "user.email", "kernel@example.invalid")
        for path, payload in base_values.items():
            target = repo / Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        _git(repo, "add", "--all")
        _git(repo, "commit", "-m", "base")
        if info_exclude_pattern is not None:
            with (repo / ".git" / "info" / "exclude").open(
                "a",
                encoding="utf-8",
            ) as stream:
                stream.write(f"\n{info_exclude_pattern}\n")
    elif info_exclude_pattern is not None:
        raise ValueError("info_exclude_pattern is only valid for a new fixture repository")
    controller = tmp_path / "controller" / transaction_id
    attestation = attestCanonicalRepository(repo)
    policy = ManifestPolicy(
        reserved_roots=("state/tasks",),
        max_files=20,
        max_total_bytes=4096,
        max_file_bytes=2048,
        max_depth=8,
        max_path_bytes=240,
    )
    expected = ObjectManifest(
        expected_revision=attestation.head_oid,
        entries=tuple(
            _blob_entry(path, payload) for path, payload in base_values.items()
        ),
        attribute_rules=(),
        policy=policy,
    )
    blobs = controller / "blobs"
    values = (
        proposed_values
        if proposed_values is not None
        else {"tracked.txt": b"changed\n", "added.txt": b"added\n"}
    )
    snapshot_entries = []
    for path, payload in values.items():
        digest = _put(blobs, payload)
        snapshot_entries.append(
            SnapshotEntry(
                path=path,
                mode=(proposed_modes or {}).get(path, 0o100644),
                blob_sha256=digest,
                size=len(payload),
            )
        )
    snapshot = CandidateSnapshot(
        transaction_id=transaction_id,
        blob_root=blobs,
        entries=tuple(snapshot_entries),
        policy=policy,
    )
    git = shutil.which("git")
    assert git is not None

    def run_locally(invocation) -> ObjectParserProcessResult:
        if "loose-object-proof" in invocation.argv:
            command = [
                sys.executable,
                "-I",
                "-S",
                str(ENTRYPOINT),
                "loose-object-proof",
                "--sha1dc-executable",
                git,
                "--request",
                str(invocation.request_path),
                "--raw-object",
                str(invocation.request_path.parent / "raw-object"),
            ]
        else:
            command = [
                sys.executable,
                "-I",
                "-S",
                str(ENTRYPOINT),
                "candidate-snapshot",
                "--sha1dc-executable",
                git,
                "--request",
                str(invocation.request_path),
                "--blob-root",
                str(blobs),
            ]
        result = subprocess.run(
            command,
            cwd=tmp_path,
            env={},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
        return ObjectParserProcessResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    parser = ObjectParser(
        controller_root=controller / "parser",
        image=ObjectParserImage(
            repository="galaxy-r3/object-parser",
            manifest_digest=IMAGE_DIGEST,
            role="object_parser",
        ),
        runtime_entrypoint=ENTRYPOINT,
        process_runner=run_locally,
    )
    parsed = parser.parseCandidateSnapshot(snapshot=snapshot, expected=expected)
    evidence, oracle = qualifyGitSha1dc(
        executable=git,
        sterile_root=controller / "sha1dc",
    )
    writer = GitObjectWriter(
        object_root=controller / "objects",
        blob_root=blobs,
        sha1dc_oracle=oracle,
        sha1dc_evidence=evidence,
        writer_version_digest="d" * 64,
        forbidden_roots=(repo,),
        canonical_object_verifier=lambda raw, object_record: parser.proveLooseObject(
            raw=raw,
            expected=object_record,
        ).receipt_id,
    )
    journal = AttemptJournal(controller / "journal")
    now = datetime.now(timezone.utc).isoformat()
    proposal_message = f"transaction {transaction_id}\n"
    proposal_timestamp_seed = datetime.fromtimestamp(
        1_700_000_000,
        timezone.utc,
    ).isoformat()
    policy_digest = canonical_digest(
        {"attribute_rules": [], "policy": policy.toDict()}
    )
    record = AttemptRecord(
        transaction_id=snapshot.transaction_id,
        task_id="task-001",
        subtask_id="subtask-001",
        attempt_id=attempt_id,
        repository_id=attestation.repository_id,
        canonical_root=attestation.canonical_root,
        canonical_ref=attestation.head_ref,
        base_revision=attestation.head_oid,
        candidate_kind="clone",
        clone_lease_id=f"clone-{attempt_id}",
        clone_path=str(controller / "clone"),
        ownership_nonce="b" * 64,
        spec_digest="c" * 64,
        policy_digest=policy_digest,
        canonical_metadata_attestation_digest=attestation.attestation_digest,
        object_format="sha1",
        oid_length=40,
        ref_backend="files",
        candidate_branch=f"refs/heads/9to5/candidates/{snapshot.transaction_id}",
        checkpoint_message_digest="1" * 64,
        proposal_message_digest=hashlib.sha256(
            proposal_message.encode("utf-8")
        ).hexdigest(),
        commit_timestamp_seed=proposal_timestamp_seed,
        runner_kind="local",
        candidate_git_dir=str(controller / "clone" / ".git"),
        canonical_git_common_dir=attestation.git_common_dir,
        source_manifest_digest=expected.manifest_digest,
        source_object_closure_digest=expected.object_closure_digest,
        source_snapshot_digest=snapshot.snapshot_digest,
        source_parser_receipt_id=parsed.receipt_id,
        source_payload_root=str(snapshot.blob_root),
        created_at=now,
        updated_at=now,
    )
    def _resource(
        resource_id: str,
        role: ResourceRole,
        backend: str,
        depends_on: tuple[str, ...] = (),
    ) -> RuntimeResourceLease:
        return RuntimeResourceLease(
            resource_id=resource_id,
            run_id="run-001",
            transaction_id=record.transaction_id,
            controller_scope_id="controller-001",
            role=role,
            backend=backend,
            ownership_nonce=record.ownership_nonce,
            state=ProcessResourceState.REGISTERED,
            cleanup_locator_digest="3" * 64,
            pid=0,
            process_group_id=0,
            container_id="",
            image_digest="c" * 64 if backend == "docker" else "",
            entrypoint_digest="4" * 64,
            mount_digest="5" * 64,
            environment_digest="6" * 64,
            security_profile_digest="7" * 64,
            depends_on=depends_on,
            created_at=record.created_at,
            updated_at=record.created_at,
        )

    # A local runner admits exactly the closed four-role runtime closure, with
    # the model driver depending on the authority watchdog.
    runtime_resources = (
        _resource("watchdog-001", ResourceRole.AUTHORITY_WATCHDOG, "local"),
        _resource(
            "driver-001",
            ResourceRole.MODEL_DRIVER,
            "local",
            depends_on=("authority_watchdog:watchdog-001",),
        ),
        _resource("parser-001", ResourceRole.CANDIDATE_PARSER, "docker"),
        _resource("verifier-001", ResourceRole.VERIFIER, "docker"),
    )
    # RUNNING now requires the admission manifest to be present on the stored
    # record, so it must be bound before create() rather than after.
    record = _with_runtime_manifest(record, runtime_resources)
    journal.create(record)
    registered_resources = journal.register_resources(
        record.transaction_id,
        runtime_resources,
    )
    journal.transition(
        snapshot.transaction_id,
        AttemptPhase.RUNNING,
        # Derived from the returned canonical tuple, not re-composed locally.
        resource_lease_ids=tuple(
            f"{resource.role.value}:{resource.resource_id}"
            for resource in registered_resources
        ),
    )
    receipts = ReceiptStore(
        controller / "receipts",
        forbidden_roots=(repo,),
    )
    if landing_authority_issuer is None:
        landing_authority_issuer = (
            candidate_mod._buildDiagnosticLandingAuthorityIssuer(
                run_id="run-001",
                controller_generation=7,
                watchdog_generation=11,
                process_capability=object(),
                canonical_repository_id=attestation.repository_id,
                repository_attestation_digest=attestation.attestation_digest,
                expected_base_sha=attestation.head_oid,
                clock=authority_clock,
                recovery_quiescence_probe=lambda _transaction_id: True,
            )
        )
    if run_admission is None:
        observed_now = (
            authority_clock()
            if authority_clock is not None
            else datetime.now(timezone.utc)
        )
        run_admission = landing_authority_issuer.issueRunAdmission(
            process_capability=landing_authority_issuer._process_capability,
            deadline=authority_deadline or observed_now + timedelta(minutes=5),
        )
    coordinator = StagingCoordinator(
        attestation=attestation,
        journal=journal,
        receipt_store=receipts,
        ref_store=LooseRefStore(attestation),
        writer=writer,
        parser_image_digest=IMAGE_DIGEST,
        parser_security_profile_digest="f" * 64,
        landing_authority_issuer=landing_authority_issuer,
        run_admission=run_admission,
    )
    request = StagingRequest(
        transaction_id=snapshot.transaction_id,
        task_id="task-001",
        subtask_id="subtask-001",
        attempt_id=attempt_id,
        runner_kind=RunnerKind.LOCAL,
        snapshot=snapshot,
        parsed=parsed,
        expected_manifest=expected,
        commit_metadata=CommitMetadata(
            author_name="GALAXY Kernel",
            author_email="kernel@example.invalid",
            committer_name="GALAXY Kernel",
            committer_email="kernel@example.invalid",
            timestamp=1_700_000_000,
            timezone="+0000",
            message=proposal_message,
        ),
        cleanup_token=object(),
    )
    return repo, coordinator, request, journal, receipts, blobs


def test_staging_coordinator_requires_exact_issuer_admission_pair(
    tmp_path: Path,
) -> None:
    _, coordinator, _, _, _, _ = _fixture(tmp_path)
    issuer = coordinator._landing_authority_issuer
    assert issuer is not None

    with pytest.raises(TypeError, match="issuer.*run_admission|pair"):
        StagingCoordinator(
            attestation=coordinator.attestation,
            journal=coordinator.journal,
            receipt_store=coordinator.receipt_store,
            ref_store=coordinator.ref_store,
            writer=coordinator.writer,
            parser_image_digest=coordinator.parser_image_digest,
            parser_security_profile_digest=(
                coordinator.parser_security_profile_digest
            ),
            landing_authority_issuer=issuer,
        )


def test_prepare_refuses_commit_metadata_outside_registered_attempt_plan(
    tmp_path: Path,
) -> None:
    _, coordinator, request, journal, _, _ = _fixture(tmp_path)
    changed = replace(
        request,
        commit_metadata=replace(
            request.commit_metadata,
            message="different proposal\n",
        ),
    )

    with pytest.raises(StagedRevisionRefused, match="message|metadata|attempt plan"):
        coordinator.prepareStagedRevision(changed)

    changed_time = replace(
        request,
        commit_metadata=replace(
            request.commit_metadata,
            timestamp=request.commit_metadata.timestamp + 1,
        ),
    )
    with pytest.raises(StagedRevisionRefused, match="metadata|attempt plan"):
        coordinator.prepareStagedRevision(changed_time)

    record = journal.load(request.transaction_id)
    assert record.phase is AttemptPhase.RUNNING
    assert not record.commit_metadata_digest


def test_prepare_is_object_only_durable_and_canonical_worktree_inert(tmp_path: Path) -> None:
    repo, coordinator, request, journal, receipts, _ = _fixture(tmp_path)
    head_before = _git(repo, "rev-parse", "HEAD")
    index_before = (repo / ".git" / "index").read_bytes()
    worktree_before = {path.name: path.read_bytes() for path in repo.glob("*.txt")}
    lease = coordinator.prepareStagedRevision(request)
    assert _git(repo, "rev-parse", "HEAD") == head_before
    assert (repo / ".git" / "index").read_bytes() == index_before
    assert {path.name: path.read_bytes() for path in repo.glob("*.txt")} == worktree_before
    assert coordinator.ref_store.readRef(lease.checkpoint_ref) == lease.proposed_revision
    assert coordinator.ref_store.readRef(lease.staged_ref) == lease.proposed_revision
    assert _git(repo, "show", f"{lease.staged_ref}:tracked.txt") == "changed"
    assert _git(repo, "show", f"{lease.staged_ref}:added.txt") == "added"
    record = journal.load(request.transaction_id)
    assert record.phase is AttemptPhase.STAGED_PREPARED
    assert record.staging_receipt_id == lease.staging_receipt_id
    receipt = receipts.read(lease.staging_receipt_id, expected_type=StagingReceipt)
    assert receipt.proposed_commit == lease.proposed_revision
    assert coordinator.stagedRevisionIntact(request, lease) is True
    journal.transition(
        request.transaction_id,
        AttemptPhase.VERIFIED,
        verification_receipt_id="9" * 64,
        verified_revision=lease.proposed_revision,
    )
    assert coordinator.stagedRevisionIntact(request, lease) is True


def test_prepare_replay_is_exact_and_does_not_move_private_refs(tmp_path: Path) -> None:
    _, coordinator, request, journal, _, _ = _fixture(tmp_path)
    first = coordinator.prepareStagedRevision(request)
    sequence = journal.load(request.transaction_id).sequence
    second = coordinator.prepareStagedRevision(request)
    assert second.toDict() == first.toDict()
    assert second.cleanup_token is request.cleanup_token
    assert journal.load(request.transaction_id).sequence == sequence
    assert coordinator.stagedRevisionIntact(request, second)


def test_hard_death_after_commit_object_creation_replays_identical_metadata_oid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SimulatedHardDeath(BaseException):
        pass

    repo, coordinator, request, journal, _, _ = _fixture(tmp_path)
    real_write = coordinator.writer.writeRevision
    real_install = coordinator.writer.installClosureIntoCanonical
    written = []
    crashed = False

    def record_write(*, manifest, metadata):
        receipt = real_write(manifest=manifest, metadata=metadata)
        written.append(receipt)
        return receipt

    def crash_once_after_write(*, receipt, attestation, failpoint=None):
        nonlocal crashed
        if not crashed:
            crashed = True
            raise SimulatedHardDeath("after deterministic commit-object creation")
        return real_install(
            receipt=receipt,
            attestation=attestation,
            failpoint=failpoint,
        )

    monkeypatch.setattr(coordinator.writer, "writeRevision", record_write)
    monkeypatch.setattr(
        coordinator.writer,
        "installClosureIntoCanonical",
        crash_once_after_write,
    )

    with pytest.raises(SimulatedHardDeath):
        coordinator.prepareStagedRevision(request)
    interrupted = journal.load(request.transaction_id)
    assert interrupted.phase is AttemptPhase.RUNNING
    assert interrupted.commit_metadata_digest
    assert not (repo / ".git" / "refs" / "9to5" / "staged").exists()

    lease = coordinator.prepareStagedRevision(request)

    assert len(written) == 2
    assert written[0] == written[1]
    assert lease.proposed_revision == written[0].commit_oid
    assert journal.load(request.transaction_id).commit_metadata_digest == (
        interrupted.commit_metadata_digest
    )


def test_integrity_probe_never_repairs_missing_external_object(tmp_path: Path) -> None:
    _, coordinator, request, _, _, _ = _fixture(tmp_path)
    lease = coordinator.prepareStagedRevision(request)
    before = {
        path.relative_to(coordinator.writer.object_root).as_posix(): path.read_bytes()
        for path in coordinator.writer.object_root.rglob("*")
        if path.is_file()
    }
    victim_relative = sorted(before)[0]
    victim = coordinator.writer.object_root / victim_relative
    victim.unlink()

    assert coordinator.stagedRevisionIntact(request, lease) is False
    assert not victim.exists(), "a read-only integrity probe repaired missing evidence"
    assert {
        path.relative_to(coordinator.writer.object_root).as_posix(): path.read_bytes()
        for path in coordinator.writer.object_root.rglob("*")
        if path.is_file()
    } == {name: payload for name, payload in before.items() if name != victim_relative}


def test_commit_metadata_substitution_is_refused_before_object_creation(
    tmp_path: Path,
) -> None:
    _, coordinator, request, journal, _, _ = _fixture(tmp_path)
    changed = replace(
        request,
        commit_metadata=replace(
            request.commit_metadata,
            author_email="substituted@example.invalid",
        ),
    )

    coordinator.prepareStagedRevision(request)
    before = journal.load(request.transaction_id)
    with pytest.raises(StagedRevisionRefused, match="metadata|journal"):
        coordinator.prepareStagedRevision(changed)
    assert journal.load(request.transaction_id) == before


def test_blob_drift_or_staged_ref_drift_refuses_without_canonical_head_move(
    tmp_path: Path,
) -> None:
    repo, coordinator, request, _, _, blobs = _fixture(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    first = request.snapshot.entries[0]
    path = blobs / first.blob_sha256[:2] / first.blob_sha256
    path.write_bytes(b"drift")
    with pytest.raises(StagedRevisionRefused, match="blob|snapshot"):
        coordinator.prepareStagedRevision(request)
    assert _git(repo, "rev-parse", "HEAD") == head
    assert not (repo / ".git" / "refs" / "9to5" / "staged" / request.transaction_id).exists()

    # Fresh evidence, followed by an explicit staged-ref substitution.
    repo, coordinator, request, _, _, _ = _fixture(tmp_path / "fresh")
    lease = coordinator.prepareStagedRevision(request)
    staged_path = repo / ".git" / Path(lease.staged_ref)
    staged_path.write_bytes((request.expected_manifest.expected_revision + "\n").encode("ascii"))
    assert coordinator.stagedRevisionIntact(request, lease) is False
    assert _git(repo, "rev-parse", "HEAD") == request.expected_manifest.expected_revision


def _promotion_chain(
    *,
    coordinator: StagingCoordinator,
    request: StagingRequest,
    journal: AttemptJournal,
    receipts: ReceiptStore,
    authority_issuer: candidate_mod.LandingAuthorityIssuer | None = None,
    run_admission: candidate_mod.RunAdmissionAuthority | None = None,
):
    lease = coordinator.prepareStagedRevision(request)
    staging = receipts.read(lease.staging_receipt_id, expected_type=StagingReceipt)
    verification = RevisionVerificationReceipt(
        transaction_id=request.transaction_id,
        staging_receipt_id=staging.receipt_id,
        passed=True,
        proposed_revision=lease.proposed_revision,
        verified_revision=lease.proposed_revision,
        verification_clone_revision=lease.proposed_revision,
        execution_origin_tier="hostile-docker",
        verification_clone_id="verify-clone-001",
        container_resource_id="container-001",
        verifier_image_digest="1" * 64,
        verifier_sbom_digest="2" * 64,
        watchdog_generation=3,
        verification_command_authority_receipt_id="3" * 64,
        command_evidence_digest="4" * 64,
        evidence_id="evidence-001",
        tracked_tree_before_digest="5" * 64,
        tracked_tree_after_digest="5" * 64,
    )
    review = ReviewReceipt(
        transaction_id=request.transaction_id,
        staging_receipt_id=staging.receipt_id,
        proposed_revision=lease.proposed_revision,
        target_evidence_digest="6" * 64,
        reviewer_id="reviewer-001",
        reviewer_provider="codex",
        clean_room_context_digest="7" * 64,
        findings_digest="8" * 64,
        contamination_controls_digest="9" * 64,
        decision=ReviewDecision.PERMIT,
        policy_id="kernel-review-v1",
        policy_version="1",
        policy_inputs_digest="a" * 64,
        independent=True,
    )
    receipts.put(verification)
    receipts.put(review)
    journal.transition(
        request.transaction_id,
        AttemptPhase.VERIFIED,
        verification_receipt_id=verification.receipt_id,
        verified_revision=lease.proposed_revision,
    )
    journal.transition(
        request.transaction_id,
        AttemptPhase.PROMOTION_PREPARED,
        review_receipt_id=review.receipt_id,
    )
    authorization = PromotionAuthorization(
        transaction_id=request.transaction_id,
        task_id=request.task_id,
        subtask_id=request.subtask_id,
        staging_receipt_id=staging.receipt_id,
        verification_receipt_id=verification.receipt_id,
        review_receipt_id=review.receipt_id,
        proposed_revision=lease.proposed_revision,
        proposed_tree=lease.proposed_tree,
        proposed_diff_digest=lease.proposed_diff_digest,
        spec_digest="c" * 64,
        policy_digest=staging.policy_manifest_digest,
    )
    now = datetime.now(timezone.utc)
    issuer = authority_issuer or coordinator._landing_authority_issuer
    assert issuer is not None
    process_capability = issuer._process_capability
    admission = run_admission
    if admission is None and issuer is coordinator._landing_authority_issuer:
        admission = coordinator._run_admission
    if admission is None:
        admission = issuer.issueRunAdmission(
            process_capability=process_capability,
            deadline=now + timedelta(minutes=5),
        )
    authority = issuer.issueLandingAuthority(
        admission=admission,
        authorization=authorization,
    )
    return lease, authorization, authority, issuer, admission


def test_fenced_promotion_materializes_exact_revision_and_receipt(tmp_path: Path) -> None:
    repo, coordinator, request, journal, receipts, _ = _fixture(tmp_path)
    lease, authorization, authority, _, _ = _promotion_chain(
        coordinator=coordinator,
        request=request,
        journal=journal,
        receipts=receipts,
    )

    receipt = coordinator.promoteStagedRevision(
        lease,
        authorization,
        authority,
    )

    assert isinstance(receipt, PromotionReceipt)
    assert receipt.succeeded
    assert _git(repo, "rev-parse", "HEAD") == lease.proposed_revision
    assert (repo / "tracked.txt").read_bytes() == b"changed\n"
    assert (repo / "added.txt").read_bytes() == b"added\n"
    assert _git(repo, "status", "--porcelain=v1") == ""
    record = journal.load(request.transaction_id)
    assert record.phase is AttemptPhase.PROMOTED
    assert record.promotion_receipt_id == receipt.receipt_id
    assert not (repo / ".git" / "index.lock").exists()


def test_promotion_refuses_authority_from_an_unbound_issuer(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    repo, coordinator, request, journal, receipts, _ = _fixture(tmp_path)
    foreign_capability = object()
    foreign_issuer = candidate_mod._buildDiagnosticLandingAuthorityIssuer(
        run_id="run-foreign",
        controller_generation=7,
        watchdog_generation=11,
        process_capability=foreign_capability,
        clock=lambda: now,
    )
    lease, authorization, foreign_authority, _, _ = _promotion_chain(
        coordinator=coordinator,
        request=request,
        journal=journal,
        receipts=receipts,
        authority_issuer=foreign_issuer,
    )
    head_before = _git(repo, "rev-parse", "HEAD")

    with pytest.raises(PromotionRefused, match="issuer.*bound|bound.*issuer"):
        coordinator.promoteStagedRevision(
            lease,
            authorization,
            foreign_authority,
        )

    assert _git(repo, "rev-parse", "HEAD") == head_before
    assert not (repo / ".git" / "index.lock").exists()


def test_promotion_refuses_if_native_identity_map_drifts_after_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, coordinator, request, journal, receipts, _ = _fixture(tmp_path)
    lease, authorization, authority, _, _ = _promotion_chain(
        coordinator=coordinator,
        request=request,
        journal=journal,
        receipts=receipts,
    )
    real_verify = candidate_mod._verifyCanonicalWorktree
    injected = False

    def verify_with_drift(root: Path, manifest: ObjectManifest) -> str:
        nonlocal injected
        digest = real_verify(root, manifest)
        if manifest == request.parsed.manifest and (repo / "added.txt").exists():
            injected = True
            return "f" * 64
        return digest

    monkeypatch.setattr(
        candidate_mod,
        "_verifyCanonicalWorktree",
        verify_with_drift,
    )

    with pytest.raises(PromotionRecoveryRequired, match="identity map drifted"):
        coordinator.promoteStagedRevision(
            lease,
            authorization,
            authority,
        )

    assert injected is True
    assert coordinator.ref_store.readRef(coordinator.attestation.head_ref) == (
        lease.proposed_revision
    )
    assert journal.load(request.transaction_id).phase is AttemptPhase.REF_MOVED


def test_disjoint_changes_require_fresh_revision_bound_attempts(
    tmp_path: Path,
) -> None:
    base = {"tracked.txt": b"base\n"}
    after_a = {**base, "a.txt": b"change-a\n"}
    after_ab = {**after_a, "b.txt": b"change-b\n"}
    repo, coordinator_a, request_a, journal_a, receipts_a, _ = _fixture(
        tmp_path,
        expected_values=base,
        proposed_values=after_a,
        transaction_id="tx-disjoint-a",
        attempt_id="attempt-a",
    )
    (
        _,
        coordinator_b0,
        request_b0,
        journal_b0,
        receipts_b0,
        _,
    ) = _fixture(
        tmp_path,
        existing_repo=repo,
        expected_values=base,
        proposed_values={**base, "b.txt": b"change-b\n"},
        transaction_id="tx-disjoint-b0",
        attempt_id="attempt-b0",
    )
    lease_a, authorization_a, authority_a, _, _ = _promotion_chain(
        coordinator=coordinator_a,
        request=request_a,
        journal=journal_a,
        receipts=receipts_a,
    )
    receipt_a = coordinator_a.promoteStagedRevision(
        lease_a,
        authorization_a,
        authority_a,
    )
    with pytest.raises(StagedRevisionRefused, match="attestation|canonical|staged"):
        coordinator_b0.prepareStagedRevision(request_b0)
    assert (repo / "a.txt").read_bytes() == b"change-a\n"
    assert not (repo / "b.txt").exists()
    assert journal_b0.load(request_b0.transaction_id).phase is AttemptPhase.RUNNING
    assert receipts_b0.root.is_dir()

    (
        _,
        coordinator_b1,
        request_b1,
        journal_b1,
        receipts_b1,
        _,
    ) = _fixture(
        tmp_path,
        existing_repo=repo,
        expected_values=after_a,
        proposed_values=after_ab,
        transaction_id="tx-disjoint-b1",
        attempt_id="attempt-b1",
    )
    assert request_b1.expected_manifest.expected_revision == receipt_a.resulting_revision
    lease_b1, authorization_b1, authority_b1, _, _ = _promotion_chain(
        coordinator=coordinator_b1,
        request=request_b1,
        journal=journal_b1,
        receipts=receipts_b1,
    )

    receipt_b = coordinator_b1.promoteStagedRevision(
        lease_b1,
        authorization_b1,
        authority_b1,
    )

    assert receipt_b.expected_revision == receipt_a.resulting_revision
    assert (repo / "a.txt").read_bytes() == b"change-a\n"
    assert (repo / "b.txt").read_bytes() == b"change-b\n"
    assert _git(repo, "status", "--porcelain=v1") == ""


def test_owned_index_fence_blocks_cooperative_checkout_reset_and_merge(
    tmp_path: Path,
) -> None:
    repo, coordinator, request, journal, receipts, _ = _fixture(tmp_path)
    lease, authorization, authority, _, _ = _promotion_chain(
        coordinator=coordinator,
        request=request,
        journal=journal,
        receipts=receipts,
    )
    exercised = False

    def failpoint(name: str) -> None:
        nonlocal exercised
        if name != "after_index_fence":
            return
        exercised = True
        head_before = (repo / ".git" / "HEAD").read_bytes()
        main_before = (repo / ".git" / "refs" / "heads" / "main").read_bytes()
        orig_head = repo / ".git" / "ORIG_HEAD"
        orig_head_before = orig_head.read_bytes() if orig_head.exists() else None
        index_before = (repo / ".git" / "index").read_bytes()
        files_before = {
            path.relative_to(repo).as_posix(): path.read_bytes()
            for path in repo.rglob("*")
            if path.is_file() and ".git" not in path.parts
        }
        refs_before = {
            path.relative_to(repo / ".git" / "refs").as_posix(): path.read_bytes()
            for path in (repo / ".git" / "refs").rglob("*")
            if path.is_file()
        }
        commands = (
            ("checkout", "--detach", lease.proposed_revision),
            ("reset", "--hard", lease.proposed_revision),
            ("merge", "--no-edit", lease.staged_ref),
        )
        for command in commands:
            result = subprocess.run(
                ["git", *command],
                cwd=repo,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                check=False,
                env={
                    **os.environ,
                    "GIT_TERMINAL_PROMPT": "0",
                    "GIT_NO_LAZY_FETCH": "1",
                },
            )
            assert result.returncode != 0
            assert (repo / ".git" / "HEAD").read_bytes() == head_before
            assert (repo / ".git" / "refs" / "heads" / "main").read_bytes() == main_before
            assert (orig_head.read_bytes() if orig_head.exists() else None) == orig_head_before
            assert (repo / ".git" / "index").read_bytes() == index_before
            assert {
                path.relative_to(repo).as_posix(): path.read_bytes()
                for path in repo.rglob("*")
                if path.is_file() and ".git" not in path.parts
            } == files_before
            assert {
                path.relative_to(repo / ".git" / "refs").as_posix(): path.read_bytes()
                for path in (repo / ".git" / "refs").rglob("*")
                if path.is_file()
            } == refs_before

    receipt = coordinator.promoteStagedRevision(
        lease,
        authorization,
        authority,
        failpoint=failpoint,
    )

    assert exercised is True
    assert receipt.succeeded is True
    assert not (repo / ".git" / "ORIG_HEAD.lock").exists()


def test_same_byte_worktree_identity_replacement_under_fence_refuses(
    tmp_path: Path,
) -> None:
    repo, coordinator, request, journal, receipts, _ = _fixture(tmp_path)
    lease, authorization, authority, _, _ = _promotion_chain(
        coordinator=coordinator,
        request=request,
        journal=journal,
        receipts=receipts,
    )
    target = repo / "tracked.txt"
    original = target.read_bytes()
    head_before = _git(repo, "rev-parse", "HEAD")
    replaced = False

    def failpoint(name: str) -> None:
        nonlocal replaced
        if name == "after_custom_lock":
            target.unlink()
            target.write_bytes(original)
            replaced = True

    with pytest.raises(PromotionRefused, match="identity|drift|worktree"):
        coordinator.promoteStagedRevision(
            lease,
            authorization,
            authority,
            failpoint=failpoint,
        )

    assert replaced is True
    assert _git(repo, "rev-parse", "HEAD") == head_before
    assert target.read_bytes() == original
    assert not (repo / ".git" / "index.lock").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows short-name identity boundary")
def test_one_to_one_short_alias_for_same_long_name_identity_is_accepted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, _, request, _, _, _ = _fixture(
        tmp_path,
        proposed_values={"tracked.txt": b"base\n"},
    )
    real_open = candidate_mod.openNativeDirectory

    class AliasRoot:
        def __init__(self, inner):
            self.inner = inner

        @property
        def identity(self):
            return self.inner.identity

        def listEntries(self):
            return tuple(
                candidate_mod.NativeDirectoryEntry(
                    name=entry.name,
                    identity=entry.identity,
                    short_name=(
                        "TRACKE~1.TXT"
                        if entry.name == "tracked.txt"
                        else entry.short_name
                    ),
                )
                for entry in self.inner.listEntries()
            )

        def readFile(self, *args, **kwargs):
            return self.inner.readFile(*args, **kwargs)

        def openDirectory(self, *args, **kwargs):
            return self.inner.openDirectory(*args, **kwargs)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            self.inner.close()

    monkeypatch.setattr(
        candidate_mod,
        "openNativeDirectory",
        lambda path: AliasRoot(real_open(path)),
    )

    digest = candidate_mod._verifyCanonicalWorktree(
        repo,
        request.expected_manifest,
    )

    assert len(digest) == 64


@pytest.mark.skipif(os.name != "nt", reason="Windows short-name creation boundary")
def test_promotion_refuses_unproven_generated_short_alias_before_ref_move(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, coordinator, request, journal, receipts, _ = _fixture(
        tmp_path,
        proposed_values={
            "tracked.txt": b"changed\n",
            "name-requiring-generated-short-alias.txt": b"new\n",
        },
    )
    lease, authorization, authority, _, _ = _promotion_chain(
        coordinator=coordinator,
        request=request,
        journal=journal,
        receipts=receipts,
    )
    head_before = _git(repo, "rev-parse", "HEAD")
    monkeypatch.setattr(
        candidate_mod,
        "_windowsShortNamesMayBeGenerated",
        lambda _root: True,
    )

    with pytest.raises(PromotionRefused, match="short-name|represent"):
        coordinator.promoteStagedRevision(
            lease,
            authorization,
            authority,
        )

    assert _git(repo, "rev-parse", "HEAD") == head_before
    assert not (repo / "name-requiring-generated-short-alias.txt").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows retained-handle boundary")
def test_native_materializer_never_reopens_rebound_canonical_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo, coordinator, request, _, _, _ = _fixture(tmp_path)
    held = repo.with_name("canonical-held")
    opened = False
    real_open = candidate_mod.openNativeDirectory

    def open_then_rebind(path):
        nonlocal opened
        directory = real_open(path)
        if Path(path) == repo and not opened:
            repo.rename(held)
            repo.mkdir()
            (repo / "goldstone.txt").write_bytes(b"outside\n")
            opened = True
        return directory

    monkeypatch.setattr(candidate_mod, "openNativeDirectory", open_then_rebind)
    digest = candidate_mod._materializeCanonicalWorktree(
        canonical_root=repo,
        git_common=repo / ".git",
        transaction_id=request.transaction_id,
        fence_nonce="f" * 64,
        expected=request.expected_manifest,
        proposed=request.parsed.manifest,
        writer=coordinator.writer,
        failpoint=None,
    )

    assert opened is True
    assert len(digest) == 64
    assert (held / "tracked.txt").read_bytes() == b"changed\n"
    assert (held / "added.txt").read_bytes() == b"added\n"
    assert (repo / "goldstone.txt").read_bytes() == b"outside\n"


def test_native_materializer_never_replaces_a_foreign_addition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, coordinator, request, _, _, _ = _fixture(tmp_path)
    real_create = candidate_mod.NativeDirectoryHandle.createFile
    injected = False

    def create_then_collide(directory, name, payload):
        nonlocal injected
        identity = real_create(directory, name, payload)
        if not injected and name.startswith(".added.txt.galaxy-"):
            (repo / "added.txt").write_bytes(b"foreign\n")
            injected = True
        return identity

    monkeypatch.setattr(
        candidate_mod.NativeDirectoryHandle,
        "createFile",
        create_then_collide,
    )

    with pytest.raises(PromotionRecoveryRequired, match="materialization write failed"):
        candidate_mod._materializeCanonicalWorktree(
            canonical_root=repo,
            git_common=repo / ".git",
            transaction_id=request.transaction_id,
            fence_nonce="f" * 64,
            expected=request.expected_manifest,
            proposed=request.parsed.manifest,
            writer=coordinator.writer,
            failpoint=None,
        )

    assert injected is True
    assert (repo / "added.txt").read_bytes() == b"foreign\n"


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable-mode boundary")
def test_native_materializer_applies_manifest_executable_modes(tmp_path: Path) -> None:
    values = {
        "ordinary.txt": b"ordinary\n",
        "program.sh": b"#!/bin/sh\nexit 0\n",
    }
    repo, coordinator, request, _, _, _ = _fixture(
        tmp_path,
        expected_values={},
        proposed_values=values,
        proposed_modes={"ordinary.txt": 0o100644, "program.sh": 0o100755},
    )

    candidate_mod._materializeCanonicalWorktree(
        canonical_root=repo,
        git_common=repo / ".git",
        transaction_id=request.transaction_id,
        fence_nonce="f" * 64,
        expected=request.expected_manifest,
        proposed=request.parsed.manifest,
        writer=coordinator.writer,
        failpoint=None,
    )

    assert (repo / "ordinary.txt").stat().st_mode & 0o777 == 0o644
    assert (repo / "program.sh").stat().st_mode & 0o777 == 0o755


@pytest.mark.skipif(os.name != "nt", reason="Windows retained-handle boundary")
def test_native_index_install_never_reopens_rebound_git_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo, _, request, _, _, _ = _fixture(tmp_path)
    git_dir = repo / ".git"
    held = repo / ".git-held"
    external = tmp_path / "proposed.index"
    raw = candidate_mod.GitIndex.build(request.parsed.manifest)
    external.write_bytes(raw)
    opened = False
    real_open = candidate_mod.openNativeDirectory

    def open_then_rebind(path):
        nonlocal opened
        directory = real_open(path)
        if Path(path) == git_dir and not opened:
            git_dir.rename(held)
            git_dir.mkdir()
            (git_dir / "goldstone.txt").write_bytes(b"outside\n")
            opened = True
        return directory

    monkeypatch.setattr(candidate_mod, "openNativeDirectory", open_then_rebind)
    digest = candidate_mod._installCanonicalIndex(
        external_index=external,
        canonical_index=git_dir / "index",
        sibling=git_dir / "index.galaxy-test.new",
        expected_digest=hashlib.sha256(raw).hexdigest(),
        proposed=request.parsed.manifest,
        failpoint=None,
    )

    assert opened is True
    assert digest == hashlib.sha256(raw).hexdigest()
    assert (held / "index").read_bytes() == raw
    assert (git_dir / "goldstone.txt").read_bytes() == b"outside\n"


def test_fenced_promotion_handles_deletion_and_nested_directory_creation(
    tmp_path: Path,
) -> None:
    repo, coordinator, request, journal, receipts, _ = _fixture(
        tmp_path,
        proposed_values={"nested/deeper/new.txt": b"new\n"},
    )
    lease, authorization, authority, _, _ = _promotion_chain(
        coordinator=coordinator,
        request=request,
        journal=journal,
        receipts=receipts,
    )

    receipt = coordinator.promoteStagedRevision(
        lease,
        authorization,
        authority,
    )

    assert receipt.succeeded
    assert not (repo / "tracked.txt").exists()
    assert (repo / "nested" / "deeper" / "new.txt").read_bytes() == b"new\n"
    assert _git(repo, "status", "--porcelain=v1") == ""
    assert not (repo / ".git" / "9to5-tombstones" / request.transaction_id).exists()


@pytest.mark.parametrize(
    ("expected_values", "proposed_values", "result_path", "result_payload"),
    (
        ({"node/child.txt": b"old\n"}, {"node": b"file\n"}, "node", b"file\n"),
        ({"node": b"old\n"}, {"node/child.txt": b"new\n"}, "node/child.txt", b"new\n"),
    ),
)
def test_fenced_promotion_handles_directory_file_replacements(
    tmp_path: Path,
    expected_values: dict[str, bytes],
    proposed_values: dict[str, bytes],
    result_path: str,
    result_payload: bytes,
) -> None:
    repo, coordinator, request, journal, receipts, _ = _fixture(
        tmp_path,
        expected_values=expected_values,
        proposed_values=proposed_values,
    )
    lease, authorization, authority, _, _ = _promotion_chain(
        coordinator=coordinator,
        request=request,
        journal=journal,
        receipts=receipts,
    )

    receipt = coordinator.promoteStagedRevision(
        lease,
        authorization,
        authority,
    )

    assert receipt.succeeded
    assert (repo / Path(result_path)).read_bytes() == result_payload
    assert _git(repo, "status", "--porcelain=v1") == ""


def test_promotion_rejects_invalid_or_revoked_power_before_ref_move(
    tmp_path: Path,
) -> None:
    repo, coordinator, request, journal, receipts, _ = _fixture(tmp_path)
    lease, authorization, authority, issuer, _ = _promotion_chain(
        coordinator=coordinator,
        request=request,
        journal=journal,
        receipts=receipts,
    )
    head = _git(repo, "rev-parse", "HEAD")

    with pytest.raises((TypeError, PromotionRefused)):
        coordinator.promoteStagedRevision(lease, True, authority)
    assert _git(repo, "rev-parse", "HEAD") == head
    assert not (repo / ".git" / "index.lock").exists()
    assert not (
        repo / ".git" / "refs" / "9to5" / "promotion-intent" / request.transaction_id
    ).exists()

    issuer.revokeLandingAuthority(authority)
    with pytest.raises(PromotionRefused, match="authority"):
        coordinator.promoteStagedRevision(lease, authorization, authority)
    assert _git(repo, "rev-parse", "HEAD") == head
    assert not (repo / ".git" / "index.lock").exists()


def test_landing_liveness_is_rechecked_after_final_reads_before_ref_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
    observed = [now]
    repo, coordinator, request, journal, receipts, _ = _fixture(
        tmp_path,
        authority_clock=lambda: observed[0],
        authority_deadline=now + timedelta(seconds=1),
    )
    issuer = coordinator._landing_authority_issuer
    assert issuer is not None
    admission = coordinator._run_admission
    if admission is None:
        admission = issuer.issueRunAdmission(
            process_capability=issuer._process_capability,
            deadline=now + timedelta(seconds=1),
        )
    lease, authorization, landing, _, _ = _promotion_chain(
        coordinator=coordinator,
        request=request,
        journal=journal,
        receipts=receipts,
        authority_issuer=issuer,
        run_admission=admission,
    )
    head_before = _git(repo, "rev-parse", "HEAD")
    armed = [False]
    advanced = [False]
    original_read = NativeDirectoryHandle.readFile

    def advance_after_read(
        directory: NativeDirectoryHandle,
        name: str,
        *,
        max_bytes: int,
        expected=None,
    ) -> bytes:
        payload = original_read(
            directory,
            name,
            max_bytes=max_bytes,
            expected=expected,
        )
        if armed[0] and not advanced[0]:
            observed[0] = now + timedelta(seconds=2)
            advanced[0] = True
        return payload

    monkeypatch.setattr(NativeDirectoryHandle, "readFile", advance_after_read)

    def arm_after_existing_precommit_probe(name: str) -> None:
        if name == "before_ref_rename":
            armed[0] = True

    with pytest.raises(PromotionRefused, match="canonical|authority|expired"):
        coordinator.promoteStagedRevision(
            lease,
            authorization,
            landing,
            failpoint=arm_after_existing_precommit_probe,
        )

    assert advanced == [True]
    assert _git(repo, "rev-parse", "HEAD") == head_before


def test_shared_bootstrap_revoke_waits_for_installed_landing_canonical_cas(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "canonical"
    repo.mkdir(parents=True)
    _git(repo, "-c", "init.defaultBranch=main", "init")
    _git(repo, "config", "user.name", "Kernel")
    _git(repo, "config", "user.email", "kernel@example.invalid")
    (repo / "tracked.txt").write_bytes(b"base\n")
    _git(repo, "add", "--all")
    _git(repo, "commit", "-m", "base")
    attestation = attestCanonicalRepository(repo)

    def digest(label: str) -> str:
        return hashlib.sha256(label.encode("ascii")).hexdigest()

    scope = CapsuleBootstrapScope(
        installed_repository_identity=digest("installed-repository"),
        canonical_repository_id=attestation.repository_id,
        run_id="run-installed-cas-race",
        run_revision=0,
        controller_state_root=str((tmp_path / "controller-state").resolve()),
        source_root=str((tmp_path / "controller-source").resolve()),
        installed_controller_root=str((tmp_path / "controller-install").resolve()),
        external_roots_manifest_digest=digest("external-roots"),
        repository_attestation_digest=attestation.attestation_digest,
        expected_base_sha=attestation.head_oid,
        source_snapshot_receipt_digest=digest("source-snapshot"),
        anchor_receipt_digest=digest("anchor"),
        boot_receipt_digest=digest("boot"),
        controller_activation_receipt_digest=digest("controller-activation"),
        recovery_receipt_digest=digest("recovery"),
        activation_generation=3,
        boot_generation=5,
        controller_generation=7,
        watchdog_generation=11,
        revocation_generation=0,
        capability_expires_at="2099-01-01T01:00:00+00:00",
        run_deadline="2099-01-01T00:30:00+00:00",
    )
    outer_scope_digest = digest("outer-scope")
    process_capability = object()
    outer = SimpleNamespace(
        bootstrap_scope=scope,
        scope_digest=outer_scope_digest,
        process_capability=process_capability,
        task_id="task-001",
        raw_intent_digest=digest("raw-intent"),
        spec_digest="c" * 64,
        child_pid=os.getpid(),
    )
    watchdog = AuthorityWatchdog(
        controller_generation=scope.controller_generation,
        watchdog_generation=scope.watchdog_generation,
        revocation_generation=scope.revocation_generation,
        bootstrap_outer_scope_digest=outer_scope_digest,
        bootstrap_capsule_scope_digest=scope.digest(),
        bootstrap_child_pid=os.getpid(),
        bootstrap_expires_at=scope.run_deadline,
        bootstrap_activation_generation=scope.activation_generation,
        bootstrap_boot_generation=scope.boot_generation,
    )

    class BoundaryRLock:
        """Expose whether revocation found the bootstrap epoch lock held."""

        def __init__(self) -> None:
            self._lock = threading.RLock()
            self.revoker_attempted = threading.Event()
            self.revoker_observed_contention: bool | None = None

        def acquire(
            self,
            blocking: bool = True,
            timeout: float = -1.0,
        ) -> bool:
            if threading.current_thread().name != "bootstrap-revoker":
                return self._lock.acquire(blocking, timeout)
            acquired = self._lock.acquire(blocking=False)
            self.revoker_observed_contention = not acquired
            self.revoker_attempted.set()
            if acquired:
                return True
            return self._lock.acquire(blocking, timeout)

        def release(self) -> None:
            self._lock.release()

        def __enter__(self) -> BoundaryRLock:
            self.acquire()
            return self

        def __exit__(self, *args: object) -> None:
            self.release()

    boundary_lock = BoundaryRLock()
    setattr(watchdog, "_lock", boundary_lock)
    issuer, admission = candidate_mod._buildInstalledLandingAuthorityIssuer(
        resolved_outer_capabilities=outer,
        bootstrap_guard=watchdog,
    )
    repo, coordinator, request, journal, receipts, _ = _fixture(
        tmp_path,
        existing_repo=repo,
        landing_authority_issuer=issuer,
        run_admission=admission,
    )
    lease, authorization, landing, _, _ = _promotion_chain(
        coordinator=coordinator,
        request=request,
        journal=journal,
        receipts=receipts,
        authority_issuer=issuer,
        run_admission=admission,
    )
    cas_entered = threading.Event()
    release_cas = threading.Event()
    revocation_returned = threading.Event()
    receipts_out: list[PromotionReceipt] = []
    errors: list[BaseException] = []

    def block_before_ref_rename(name: str) -> None:
        if name != "before_ref_rename":
            return
        cas_entered.set()
        if not release_cas.wait(timeout=5):
            raise AssertionError("canonical CAS was not released")

    def promote() -> None:
        try:
            receipts_out.append(
                coordinator.promoteStagedRevision(
                    lease,
                    authorization,
                    landing,
                    failpoint=block_before_ref_rename,
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    def revoke() -> None:
        watchdog.revoke(1)
        revocation_returned.set()

    promoter = threading.Thread(target=promote, name="bootstrap-promoter")
    revoker = threading.Thread(target=revoke, name="bootstrap-revoker")
    promoter.start()
    assert cas_entered.wait(timeout=10)
    revoker.start()

    # The installed landing permit retains the one shared bootstrap epoch lock
    # across the irreversible canonical compare-and-swap.  Probe the exact
    # acquisition boundary so the proof does not depend on scheduler delay.
    assert boundary_lock.revoker_attempted.wait(timeout=5)
    assert boundary_lock.revoker_observed_contention is True
    assert not revocation_returned.is_set()
    release_cas.set()
    promoter.join(timeout=10)
    revoker.join(timeout=10)

    assert not promoter.is_alive()
    assert not revoker.is_alive()
    assert errors == []
    assert len(receipts_out) == 1
    assert receipts_out[0].succeeded
    assert _git(repo, "rev-parse", "HEAD") == lease.proposed_revision
    assert revocation_returned.is_set()
    with pytest.raises(
        candidate_mod.LandingAuthorityRefused,
        match="bootstrap|live|revok|generation",
    ):
        issuer.validateLandingAuthority(landing, authorization)


def test_dirty_canonical_refuses_before_intent_or_index_fence(tmp_path: Path) -> None:
    repo, coordinator, request, journal, receipts, _ = _fixture(tmp_path)
    lease, authorization, authority, _, _ = _promotion_chain(
        coordinator=coordinator,
        request=request,
        journal=journal,
        receipts=receipts,
    )
    (repo / "untracked.txt").write_bytes(b"user data\n")
    head = _git(repo, "rev-parse", "HEAD")

    with pytest.raises(PromotionRefused, match="worktree|untracked"):
        coordinator.promoteStagedRevision(lease, authorization, authority)

    assert _git(repo, "rev-parse", "HEAD") == head
    assert (repo / "untracked.txt").read_bytes() == b"user data\n"
    assert not (repo / ".git" / "index.lock").exists()
    assert not (
        repo / ".git" / "refs" / "9to5" / "promotion-intent" / request.transaction_id
    ).exists()


def test_info_exclude_cannot_hide_untracked_canonical_collision(tmp_path: Path) -> None:
    repo, coordinator, request, journal, receipts, _ = _fixture(
        tmp_path,
        info_exclude_pattern="ignored-by-user.txt",
    )
    lease, authorization, authority, _, _ = _promotion_chain(
        coordinator=coordinator,
        request=request,
        journal=journal,
        receipts=receipts,
    )
    hidden = repo / "ignored-by-user.txt"
    hidden.write_bytes(b"user data\n")
    assert _git(repo, "status", "--porcelain=v1") == ""
    head_before = _git(repo, "rev-parse", "HEAD")

    with pytest.raises(PromotionRefused, match="untracked|worktree"):
        coordinator.promoteStagedRevision(lease, authorization, authority)

    assert _git(repo, "rev-parse", "HEAD") == head_before
    assert hidden.read_bytes() == b"user data\n"


@pytest.mark.parametrize(
    "crash_point",
    (
        "after_ref_moved_journal",
        "after_tombstone:tracked.txt",
        "after_materialize:added.txt",
        "after_index_replace",
    ),
)
def test_recovery_finishes_only_an_already_moved_exact_revision(
    tmp_path: Path,
    crash_point: str,
) -> None:
    repo, coordinator, request, journal, receipts, _ = _fixture(tmp_path)
    lease, authorization, authority, issuer, admission = _promotion_chain(
        coordinator=coordinator,
        request=request,
        journal=journal,
        receipts=receipts,
    )

    def crash(name: str) -> None:
        if name == crash_point:
            raise RuntimeError(f"crash:{name}")

    with pytest.raises(PromotionRecoveryRequired):
        coordinator.promoteStagedRevision(
            lease,
            authorization,
            authority,
            failpoint=crash,
        )
    assert _git(repo, "rev-parse", "HEAD") == lease.proposed_revision
    assert journal.load(request.transaction_id).phase is AttemptPhase.REF_MOVED
    assert (repo / ".git" / "index.lock").exists()

    recovery = issuer.issueRecoveryAuthority(
        admission=admission,
        repository_id=coordinator.attestation.repository_id,
        transaction_id=request.transaction_id,
    )
    receipt = coordinator.recoverPromotionConsistency(
        recovery,
        request.transaction_id,
    )

    assert receipt.succeeded
    assert journal.load(request.transaction_id).phase is AttemptPhase.PROMOTED
    assert (repo / "tracked.txt").read_bytes() == b"changed\n"
    assert (repo / "added.txt").read_bytes() == b"added\n"
    assert _git(repo, "status", "--porcelain=v1") == ""
    assert not (repo / ".git" / "index.lock").exists()


def test_rejection_quarantines_before_retiring_staged_ref_without_landing(
    tmp_path: Path,
) -> None:
    repo, coordinator, request, journal, _, _ = _fixture(tmp_path)
    lease = coordinator.prepareStagedRevision(request)
    head = _git(repo, "rev-parse", "HEAD")
    index = (repo / ".git" / "index").read_bytes()
    journal.transition(
        request.transaction_id,
        AttemptPhase.VERIFIED,
        verification_receipt_id="9" * 64,
        verified_revision=lease.proposed_revision,
    )

    result = coordinator.rejectStagedRevision(
        lease,
        reason="verification denied",
    )

    assert not result.promoted
    assert result.quarantine_ref == f"refs/9to5/quarantine/{request.transaction_id}"
    assert coordinator.ref_store.readRef(result.quarantine_ref) == lease.proposed_revision
    assert coordinator.ref_store.readRef(lease.checkpoint_ref) == lease.proposed_revision
    with pytest.raises(RefError):
        coordinator.ref_store.readRef(lease.staged_ref)
    assert _git(repo, "show", f"{result.quarantine_ref}:added.txt") == "added"
    assert _git(repo, "rev-parse", "HEAD") == head
    assert (repo / ".git" / "index").read_bytes() == index
    assert journal.load(request.transaction_id).phase is AttemptPhase.REJECTED

    replay = coordinator.rejectStagedRevision(lease, reason="verification denied")
    assert replay.quarantine_ref == result.quarantine_ref
    assert _git(repo, "rev-parse", "HEAD") == head


@pytest.mark.parametrize(
    ("crash_point", "expected_phase"),
    (
        ("after_custom_lock", AttemptPhase.NOT_PROMOTED),
        ("after_promotion_intent", AttemptPhase.NOT_PROMOTED),
        ("after_index_lock_create", AttemptPhase.NOT_PROMOTED),
        ("after_index_fence", AttemptPhase.NOT_PROMOTED),
        ("after_ref_rename", AttemptPhase.PROMOTED),
    ),
)
def test_hard_crash_reconciliation_classifies_the_single_ref_truth(
    tmp_path: Path,
    crash_point: str,
    expected_phase: AttemptPhase,
) -> None:
    repo, coordinator, request, journal, receipts, _ = _fixture(tmp_path)
    lease, authorization, authority, issuer, admission = _promotion_chain(
        coordinator=coordinator,
        request=request,
        journal=journal,
        receipts=receipts,
    )

    def crash(name: str) -> None:
        if name == crash_point:
            raise PromotionCrashInjected(name)

    with pytest.raises(PromotionRecoveryRequired):
        coordinator.promoteStagedRevision(
            lease,
            authorization,
            authority,
            failpoint=crash,
        )
    crashed = journal.load(request.transaction_id)
    assert crashed.promotion_plan_digest
    if crash_point in {
        "after_custom_lock",
        "after_promotion_intent",
        "after_index_lock_create",
    }:
        assert crashed.phase is AttemptPhase.PROMOTION_PREPARED
    else:
        assert crashed.phase is AttemptPhase.INDEX_FENCED
    assert (repo / ".git" / "index.lock").exists() is (
        crash_point
        in {"after_index_lock_create", "after_index_fence", "after_ref_rename"}
    )
    recovery = issuer.issueRecoveryAuthority(
        admission=admission,
        repository_id=coordinator.attestation.repository_id,
        transaction_id=request.transaction_id,
    )

    coordinator.reconcileAttempt(recovery, request.transaction_id)

    assert journal.load(request.transaction_id).phase is expected_phase
    assert not (repo / ".git" / "index.lock").exists()
    if expected_phase is AttemptPhase.NOT_PROMOTED:
        assert _git(repo, "rev-parse", "HEAD") == lease.expected_target_revision
        assert (repo / "tracked.txt").read_bytes() == b"base\n"
        assert not (repo / "added.txt").exists()
    else:
        assert _git(repo, "rev-parse", "HEAD") == lease.proposed_revision
        assert (repo / "tracked.txt").read_bytes() == b"changed\n"
        assert (repo / "added.txt").read_bytes() == b"added\n"


@pytest.mark.parametrize(
    ("crash_point", "expected_phase"),
    (
        ("after_custom_lock", AttemptPhase.NOT_PROMOTED),
        ("after_promotion_intent", AttemptPhase.NOT_PROMOTED),
        ("after_index_lock_create", AttemptPhase.NOT_PROMOTED),
        ("after_index_fence", AttemptPhase.NOT_PROMOTED),
        ("before_ref_rename", AttemptPhase.NOT_PROMOTED),
        ("after_ref_rename", AttemptPhase.PROMOTED),
        ("after_ref_moved_journal", AttemptPhase.PROMOTED),
        ("after_tombstone:tracked.txt", AttemptPhase.PROMOTED),
        ("after_materialize:added.txt", AttemptPhase.PROMOTED),
        ("before_index_replace", AttemptPhase.PROMOTED),
        ("after_index_replace", AttemptPhase.PROMOTED),
        ("after_promoted_journal", AttemptPhase.PROMOTED),
    ),
)
def test_real_process_death_recovers_in_a_fresh_process(
    tmp_path: Path,
    crash_point: str,
    expected_phase: AttemptPhase,
) -> None:
    repo, coordinator, request, journal, receipts, _ = _fixture(tmp_path)
    lease, authorization, _, _, _ = _promotion_chain(
        coordinator=coordinator,
        request=request,
        journal=journal,
        receipts=receipts,
    )
    case = {
        "attestation": coordinator.attestation.toDict(),
        "journal_root": str(journal.root),
        "receipt_root": str(receipts.root),
        "object_root": str(coordinator.writer.object_root),
        "blob_root": str(coordinator.writer.blob_root),
        "writer_version_digest": coordinator.writer.writer_version_digest,
        "parser_image_digest": coordinator.parser_image_digest,
        "parser_security_profile_digest": (
            coordinator.parser_security_profile_digest
        ),
        "git_executable": shutil.which("git"),
        "request": {
            "transaction_id": request.transaction_id,
            "task_id": request.task_id,
            "subtask_id": request.subtask_id,
            "attempt_id": request.attempt_id,
            "runner_kind": request.runner_kind.value,
            "snapshot": {
                "transaction_id": request.snapshot.transaction_id,
                "blob_root": str(request.snapshot.blob_root),
                "entries": [entry.toDict() for entry in request.snapshot.entries],
                "policy": request.snapshot.policy.toDict(),
            },
            "parsed": {
                "transaction_id": request.parsed.transaction_id,
                "manifest": request.parsed.manifest.toDict(),
                "snapshot_digest": request.parsed.snapshot_digest,
                "blob_set_digest": request.parsed.blob_set_digest,
                "diff_digest": request.parsed.diff_digest,
                "parser_version_digest": request.parsed.parser_version_digest,
                "receipt_id": request.parsed.receipt_id,
                "raw_result_base64": base64.b64encode(
                    request.parsed.raw_result
                ).decode("ascii"),
                "container_network_allowed": False,
            },
            "expected_manifest": request.expected_manifest.toDict(),
            "commit_metadata": asdict(request.commit_metadata),
        },
        "lease": lease.toDict(),
        "authorization": asdict(authorization),
    }
    case_path = tmp_path / "fresh-process-case.json"
    case_path.write_text(
        json.dumps(case, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    worker = Path("tests/execution/kernel_crash_worker.py").resolve()

    crashed = subprocess.run(
        [sys.executable, "-I", str(worker), "crash", str(case_path), crash_point],
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        check=False,
    )
    assert crashed.returncode == 97, crashed.stderr.decode(errors="replace")

    recovered = subprocess.run(
        [sys.executable, "-I", str(worker), "recover", str(case_path)],
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        check=False,
    )
    assert recovered.returncode == 0, recovered.stderr.decode(errors="replace")
    result = json.loads(recovered.stdout)
    assert result["phase"] == expected_phase.value
    assert journal.load(request.transaction_id).phase is expected_phase
    assert not (repo / ".git" / "index.lock").exists()
    if expected_phase is AttemptPhase.PROMOTED:
        assert _git(repo, "rev-parse", "HEAD") == lease.proposed_revision
        assert (repo / "tracked.txt").read_bytes() == b"changed\n"
        assert (repo / "added.txt").read_bytes() == b"added\n"
        assert _git(repo, "status", "--porcelain=v1") == ""
    else:
        assert _git(repo, "rev-parse", "HEAD") == lease.expected_target_revision
        assert (repo / "tracked.txt").read_bytes() == b"base\n"
        assert not (repo / "added.txt").exists()


def test_proposed_index_creation_is_preceded_by_a_durable_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, coordinator, request, journal, receipts, _ = _fixture(tmp_path)
    lease, authorization, authority, issuer, admission = _promotion_chain(
        coordinator=coordinator,
        request=request,
        journal=journal,
        receipts=receipts,
    )
    persist = coordinator._persistProposedIndex

    def crash_after_persist(*args, **kwargs):
        persist(*args, **kwargs)
        raise PromotionCrashInjected("after_proposed_index_create")

    monkeypatch.setattr(coordinator, "_persistProposedIndex", crash_after_persist)
    with pytest.raises(PromotionRecoveryRequired):
        coordinator.promoteStagedRevision(
            lease,
            authorization,
            authority,
        )

    crashed = journal.load(request.transaction_id)
    assert crashed.promotion_plan_digest
    proposed_index = Path(crashed.proposed_index_path)
    assert proposed_index.is_file()
    assert hashlib.sha256(proposed_index.read_bytes()).hexdigest() == (
        crashed.proposed_index_digest
    )
    recovery = issuer.issueRecoveryAuthority(
        admission=admission,
        repository_id=coordinator.attestation.repository_id,
        transaction_id=request.transaction_id,
    )

    coordinator.reconcileAttempt(recovery, request.transaction_id)

    assert journal.load(request.transaction_id).phase is AttemptPhase.NOT_PROMOTED
    assert _git(repo, "rev-parse", "HEAD") == lease.expected_target_revision


@pytest.mark.parametrize("identity_append_ordinal", (1, 2, 3))
def test_recovery_adopts_only_exact_planned_fences_created_before_identity_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    identity_append_ordinal: int,
) -> None:
    repo, coordinator, request, journal, receipts, _ = _fixture(tmp_path)
    lease, authorization, authority, issuer, admission = _promotion_chain(
        coordinator=coordinator,
        request=request,
        journal=journal,
        receipts=receipts,
    )
    append_identity = journal.bind_promotion_artifact_identities
    calls = 0

    def crash_before_identity_append(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == identity_append_ordinal:
            raise PromotionCrashInjected(
                f"before_identity_append_{identity_append_ordinal}"
            )
        return append_identity(*args, **kwargs)

    monkeypatch.setattr(
        journal,
        "bind_promotion_artifact_identities",
        crash_before_identity_append,
    )
    with pytest.raises(PromotionRecoveryRequired):
        coordinator.promoteStagedRevision(
            lease,
            authorization,
            authority,
        )
    monkeypatch.setattr(
        journal,
        "bind_promotion_artifact_identities",
        append_identity,
    )
    recovery = issuer.issueRecoveryAuthority(
        admission=admission,
        repository_id=coordinator.attestation.repository_id,
        transaction_id=request.transaction_id,
    )

    coordinator.reconcileAttempt(recovery, request.transaction_id)

    recovered = journal.load(request.transaction_id)
    assert recovered.phase is AttemptPhase.NOT_PROMOTED
    assert recovered.custom_lock_identity_digest
    if identity_append_ordinal >= 2:
        assert recovered.index_fence_identity_digest
        assert recovered.orig_head_fence_identity_digest
    if identity_append_ordinal == 3:
        assert recovered.canonical_ref_lock_identity_digest
    assert not Path(recovered.custom_lock_path).exists()
    assert not Path(recovered.index_fence_path).exists()
    assert not Path(recovered.orig_head_fence_path).exists()
    assert not Path(recovered.canonical_ref_lock_path).exists()
    assert _git(repo, "rev-parse", "HEAD") == lease.expected_target_revision


def test_recovery_adopts_an_exact_first_git_fence_when_power_fails_before_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, coordinator, request, journal, receipts, _ = _fixture(tmp_path)
    lease, authorization, authority, issuer, admission = _promotion_chain(
        coordinator=coordinator,
        request=request,
        journal=journal,
        receipts=receipts,
    )
    acquire = candidate_mod._acquireOwnedFile

    def crash_after_first_git_fence(path: Path, payload: bytes):
        owned = acquire(path, payload)
        if path.name == "index.lock":
            raise PromotionCrashInjected("after_first_git_fence_create")
        return owned

    monkeypatch.setattr(candidate_mod, "_acquireOwnedFile", crash_after_first_git_fence)
    with pytest.raises(PromotionRecoveryRequired):
        coordinator.promoteStagedRevision(
            lease,
            authorization,
            authority,
        )
    monkeypatch.setattr(candidate_mod, "_acquireOwnedFile", acquire)
    recovery = issuer.issueRecoveryAuthority(
        admission=admission,
        repository_id=coordinator.attestation.repository_id,
        transaction_id=request.transaction_id,
    )

    coordinator.reconcileAttempt(recovery, request.transaction_id)

    recovered = journal.load(request.transaction_id)
    assert recovered.phase is AttemptPhase.NOT_PROMOTED
    assert recovered.index_fence_identity_digest
    assert not recovered.orig_head_fence_identity_digest
    assert not (repo / ".git" / "index.lock").exists()
    assert not (repo / ".git" / "ORIG_HEAD.lock").exists()
    assert _git(repo, "rev-parse", "HEAD") == lease.expected_target_revision


def test_promoted_journal_crash_recovery_releases_every_owned_fence(
    tmp_path: Path,
) -> None:
    repo, coordinator, request, journal, receipts, _ = _fixture(tmp_path)
    lease, authorization, authority, issuer, admission = _promotion_chain(
        coordinator=coordinator,
        request=request,
        journal=journal,
        receipts=receipts,
    )

    def crash(name: str) -> None:
        if name == "after_promoted_journal":
            raise PromotionCrashInjected(name)

    with pytest.raises(PromotionRecoveryRequired):
        coordinator.promoteStagedRevision(
            lease,
            authorization,
            authority,
            failpoint=crash,
        )
    assert journal.load(request.transaction_id).phase is AttemptPhase.PROMOTED
    assert (repo / ".git" / "index.lock").exists()
    assert (repo / ".git" / "ORIG_HEAD.lock").exists()

    recovery = issuer.issueRecoveryAuthority(
        admission=admission,
        repository_id=coordinator.attestation.repository_id,
        transaction_id=request.transaction_id,
    )
    receipt = coordinator.reconcileAttempt(recovery, request.transaction_id)

    assert receipt.succeeded
    assert not (repo / ".git" / "index.lock").exists()
    assert not (repo / ".git" / "ORIG_HEAD.lock").exists()
    assert not Path(journal.load(request.transaction_id).custom_lock_path).exists()


def test_live_promotion_process_lease_blocks_concurrent_recovery(
    tmp_path: Path,
) -> None:
    repo, coordinator, request, journal, receipts, _ = _fixture(tmp_path)
    lease, authorization, authority, issuer, admission = _promotion_chain(
        coordinator=coordinator,
        request=request,
        journal=journal,
        receipts=receipts,
    )
    recovery = issuer.issueRecoveryAuthority(
        admission=admission,
        repository_id=coordinator.attestation.repository_id,
        transaction_id=request.transaction_id,
    )
    checked = False

    def probe(name: str) -> None:
        nonlocal checked
        if name != "after_custom_lock":
            return
        checked = True
        with pytest.raises(PromotionRecoveryRequired, match="still active"):
            coordinator.reconcileAttempt(recovery, request.transaction_id)

    receipt = coordinator.promoteStagedRevision(
        lease,
        authorization,
        authority,
        failpoint=probe,
    )

    assert checked
    assert receipt.succeeded
    assert _git(repo, "rev-parse", "HEAD") == lease.proposed_revision


def test_noncooperative_ref_move_after_cas_is_durable_divergence_not_done(
    tmp_path: Path,
) -> None:
    repo, coordinator, request, journal, receipts, _ = _fixture(tmp_path)
    lease, authorization, authority, _, _ = _promotion_chain(
        coordinator=coordinator,
        request=request,
        journal=journal,
        receipts=receipts,
    )
    divergent = "f" * 40
    target_ref = repo / ".git" / Path(coordinator.attestation.head_ref)

    def move_outside_fences(name: str) -> None:
        if name == "after_ref_rename":
            target_ref.write_bytes(f"{divergent}\n".encode("ascii"))

    with pytest.raises(PromotionRecoveryRequired, match="diverg"):
        coordinator.promoteStagedRevision(
            lease,
            authorization,
            authority,
            failpoint=move_outside_fences,
        )

    record = journal.load(request.transaction_id)
    assert record.phase is AttemptPhase.POST_PROMOTION_DIVERGENCE
    assert record.observed_revision == divergent
    assert not record.promotion_receipt_id
    assert not record.task_state_acknowledged
    assert target_ref.read_text(encoding="ascii").strip() == divergent
    assert (repo / "tracked.txt").read_bytes() == b"base\n"
    assert not (repo / "added.txt").exists()


def test_same_oid_symbolic_head_switch_under_ref_fence_refuses_main_move(
    tmp_path: Path,
) -> None:
    repo, coordinator, request, journal, receipts, _ = _fixture(tmp_path)
    lease, authorization, authority, _, _ = _promotion_chain(
        coordinator=coordinator,
        request=request,
        journal=journal,
        receipts=receipts,
    )
    main_ref = repo / ".git" / Path(coordinator.attestation.head_ref)
    other_ref = repo / ".git" / "refs" / "heads" / "other"
    other_ref.parent.mkdir(parents=True, exist_ok=True)
    other_ref.write_bytes(f"{lease.expected_target_revision}\n".encode("ascii"))

    def switch_head(name: str) -> None:
        if name == "after_lock_before_head_check":
            (repo / ".git" / "HEAD").write_bytes(b"ref: refs/heads/other\n")

    with pytest.raises(PromotionRefused, match="CAS|refused"):
        coordinator.promoteStagedRevision(
            lease,
            authorization,
            authority,
            failpoint=switch_head,
        )

    assert main_ref.read_text(encoding="ascii").strip() == lease.expected_target_revision
    assert other_ref.read_text(encoding="ascii").strip() == lease.expected_target_revision
    assert journal.load(request.transaction_id).phase is AttemptPhase.CAS_REFUSED
    assert (repo / "tracked.txt").read_bytes() == b"base\n"
    assert not (repo / "added.txt").exists()
    assert not (repo / ".git" / "index.lock").exists()


def test_promoted_history_remains_monotonic_after_later_canonical_advance(
    tmp_path: Path,
) -> None:
    repo, coordinator, request, journal, receipts, _ = _fixture(tmp_path)
    lease, authorization, authority, issuer, admission = _promotion_chain(
        coordinator=coordinator,
        request=request,
        journal=journal,
        receipts=receipts,
    )
    promoted = coordinator.promoteStagedRevision(
        lease,
        authorization,
        authority,
    )
    original_bytes = receipts.path_for(promoted.receipt_id).read_bytes()
    (repo / "later.txt").write_bytes(b"later\n")
    _git(repo, "add", "later.txt")
    _git(repo, "commit", "-m", "later cooperative advance")
    later_revision = _git(repo, "rev-parse", "HEAD")
    assert later_revision != promoted.resulting_revision
    recovery = issuer.issueRecoveryAuthority(
        admission=admission,
        repository_id=coordinator.attestation.repository_id,
        transaction_id=request.transaction_id,
    )

    recovered = coordinator.reconcileAttempt(recovery, request.transaction_id)

    assert recovered == promoted
    record = journal.load(request.transaction_id)
    assert record.phase is AttemptPhase.PROMOTED
    assert record.promotion_receipt_id == promoted.receipt_id
    assert len(record.reconciliation_receipt_ids) == 1
    observation = receipts.read(
        record.reconciliation_receipt_ids[0],
        expected_type=ReconciliationReceipt,
    )
    assert observation.classification == "historical_promotion_subsequent_revision"
    assert observation.subsequent_canonical_revision == later_revision
    assert receipts.path_for(promoted.receipt_id).read_bytes() == original_bytes
    assert coordinator.reconcileAttempt(recovery, request.transaction_id) == promoted
    assert journal.load(request.transaction_id).reconciliation_receipt_ids == (
        observation.receipt_id,
    )
