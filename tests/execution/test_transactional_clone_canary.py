"""Real offline clone -> snapshot -> parse -> object-only checkpoint canary."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from platform_core.core.galaxy_evidence import canonical_digest
from platform_core.execution.backends.clone import TransactionalCloneKernel
from platform_core.execution.object_parser import (
    ObjectParser,
    objectParserImageFromRepositoryLock,
)
from platform_core.runtime.attempt_journal import AttemptJournal
from platform_core.runtime.candidate import (
    CloneQuiescenceProof,
    ProcessResourceState,
    ResourceRole,
    RunnerKind,
    RuntimeResourceLease,
    StagingCoordinator,
    runtimeResourceStateDigest,
)
from platform_core.runtime.canonical_repo import attestCanonicalRepository
from platform_core.runtime.git_object_writer import CommitMetadata, GitObjectWriter
from platform_core.runtime.loose_refs import LooseRefStore
from platform_core.runtime.object_manifest import ManifestPolicy
from platform_core.runtime.receipts import ReceiptStore
from platform_core.runtime.sha1dc import qualifyGitSha1dc
from platform_core.runtime.worktree import CloneLeaseProvisioner

ENTRYPOINT = Path("containers/galaxy/object_parser_entrypoint.py").resolve()
IMAGE_LOCK = Path("bootstrap/galaxy_launcher/activation_images.lock.json").resolve()


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


@pytest.mark.skipif(
    shutil.which("docker") is None or shutil.which("git") is None,
    reason="Docker and Git are required for the offline canary",
)
def test_real_private_clone_edit_delete_untracked_reaches_object_only_checkpoint(
    tmp_path: Path,
) -> None:
    image = objectParserImageFromRepositoryLock(IMAGE_LOCK)
    inspect = subprocess.run(
        ["docker", "image", "inspect", image.reference],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=15,
        check=False,
    )
    if inspect.returncode != 0:
        pytest.skip("reviewed offline object-parser image is not preloaded")

    canonical = tmp_path / "canonical"
    canonical.mkdir()
    _git(canonical, "-c", "init.defaultBranch=main", "init")
    _git(canonical, "config", "user.name", "Kernel")
    _git(canonical, "config", "user.email", "kernel@example.invalid")
    _git(canonical, "config", "core.autocrlf", "false")
    (canonical / "edit.txt").write_bytes(b"before\n")
    (canonical / "delete.txt").write_bytes(b"delete-me\n")
    _git(canonical, "add", ".")
    _git(canonical, "commit", "-m", "base")

    attestation = attestCanonicalRepository(canonical)
    canonical_head = (canonical / ".git" / "refs" / "heads" / "main").read_bytes()
    canonical_index = (canonical / ".git" / "index").read_bytes()
    canonical_files = {
        "edit.txt": (canonical / "edit.txt").read_bytes(),
        "delete.txt": (canonical / "delete.txt").read_bytes(),
    }
    policy = ManifestPolicy(
        reserved_roots=("state/tasks",),
        max_files=16,
        max_total_bytes=4096,
        max_file_bytes=2048,
        max_depth=8,
        max_path_bytes=240,
    )
    controller = tmp_path / "controller"
    parser = ObjectParser(
        controller_root=controller / "parsers",
        image=image,
        runtime_entrypoint=ENTRYPOINT,
    )
    source = parser.captureAndParseSourceObjectClosure(
        attestation=attestation,
        transaction_id="tx-source-canary",
        snapshot_root=controller / "source-snapshots",
        policy=policy,
        max_raw_files=64,
        max_raw_bytes=4 * 1024 * 1024,
        max_raw_file_bytes=4 * 1024 * 1024,
    )
    evidence, oracle = qualifyGitSha1dc(
        executable=shutil.which("git") or "git",
        sterile_root=controller / "sha1dc",
    )
    source_object_root = controller / "source-writer" / "objects"
    source_object_root.mkdir(parents=True)
    source_writer = GitObjectWriter(
        object_root=source_object_root,
        blob_root=source.payload_root,
        sha1dc_oracle=oracle,
        sha1dc_evidence=evidence,
        writer_version_digest="1" * 64,
        forbidden_roots=(canonical,),
    )
    journal = AttemptJournal(controller / "journal")
    process_capability = object()
    ownership_nonce = "2" * 64
    provisioner = CloneLeaseProvisioner(
        attestation=attestation,
        journal=journal,
        writer=source_writer,
        candidate_checkout_root=controller / "candidates",
        process_capability=process_capability,
    )
    now = datetime.now(timezone.utc).isoformat()
    def runtime_resource(
        role: ResourceRole,
        backend: str,
        *,
        depends_on: tuple[str, ...] = (),
    ) -> RuntimeResourceLease:
        resource_id = f"{role.value.replace('_', '-')}-canary"
        return RuntimeResourceLease(
            resource_id=resource_id,
            run_id="run-canary",
            transaction_id="tx-clone-canary",
            controller_scope_id="scope-canary",
            role=role,
            backend=backend,
            ownership_nonce=ownership_nonce,
            state=ProcessResourceState.REGISTERED,
            cleanup_locator_digest="6" * 64,
            pid=0,
            process_group_id=0,
            container_id="",
            image_digest="7" * 64 if backend == "docker" else "",
            entrypoint_digest="8" * 64,
            mount_digest="9" * 64,
            environment_digest="a" * 64,
            security_profile_digest="b" * 64,
            created_at=now,
            updated_at=now,
            depends_on=depends_on,
        )

    watchdog = runtime_resource(ResourceRole.AUTHORITY_WATCHDOG, "local")
    watchdog_identity = f"{watchdog.role.value}:{watchdog.resource_id}"
    runtime = runtime_resource(
        ResourceRole.MODEL_DRIVER,
        "local",
        depends_on=(watchdog_identity,),
    )
    runtime_identity = f"{runtime.role.value}:{runtime.resource_id}"
    candidate_parser = runtime_resource(
        ResourceRole.CANDIDATE_PARSER,
        "docker",
        depends_on=(watchdog_identity, runtime_identity),
    )
    parser_identity = (
        f"{candidate_parser.role.value}:{candidate_parser.resource_id}"
    )
    verifier = runtime_resource(
        ResourceRole.VERIFIER,
        "docker",
        depends_on=(watchdog_identity, parser_identity),
    )
    runtime_resources = (watchdog, runtime, candidate_parser, verifier)
    runtime_manifest = json.dumps(
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
                    runtime_resources,
                    key=lambda item: f"{item.role.value}:{item.resource_id}",
                )
            ],
            "runner_kind": "local",
            "schema": "galaxy.runtime-resource-manifest/v1",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    lease = provisioner.provision(
        transaction_id="tx-clone-canary",
        task_id="task-canary",
        subtask_id="subtask-canary",
        attempt_id="attempt-canary",
        clone_lease_id="clone-canary",
        runner_kind=RunnerKind.LOCAL,
        source_manifest=source.manifest,
        source_closure=source.closure,
        ownership_nonce=ownership_nonce,
        spec_digest="3" * 64,
        checkpoint_message_digest="4" * 64,
        proposal_message_digest=hashlib.sha256(
            b"transaction tx-clone-canary\n"
        ).hexdigest(),
        commit_timestamp_seed=datetime.fromtimestamp(
            1_700_000_000,
            timezone.utc,
        ).isoformat(),
        runtime_resource_manifest_json=runtime_manifest,
        runtime_resource_manifest_digest=hashlib.sha256(
            runtime_manifest.encode("utf-8")
        ).hexdigest(),
        process_capability=process_capability,
    )
    provisioner.registerRuntimeResources(lease, resources=runtime_resources)

    checkout = Path(lease.checkout_path)
    assert (checkout / "edit.txt").read_bytes() == b"before\n"
    _git(checkout, "update-ref", "refs/heads/main", lease.expected_base_revision)
    assert (checkout / ".git" / "refs" / "heads" / "main").is_file()
    assert (canonical / ".git" / "refs" / "heads" / "main").read_bytes() == canonical_head
    goldstone = tmp_path / "host-goldstone.txt"
    goldstone.write_bytes(b"untouched\n")
    (checkout / ".git" / "hooks").mkdir()
    (checkout / ".git" / "hooks" / "post-checkout").write_text(
        f"touch {goldstone}\n",
        encoding="utf-8",
    )
    (checkout / ".git" / "info" / "attributes").write_text(
        "* filter=host-command\n",
        encoding="utf-8",
    )
    (checkout / "edit.txt").write_bytes(b"after\n")
    (checkout / "delete.txt").unlink()
    (checkout / "untracked.txt").write_bytes(b"new\n")
    for runtime_resource_lease in runtime_resources:
        journal.transition_resource(
            lease.transaction_id,
            runtime_resource_lease.resource_id,
            ProcessResourceState.QUIESCED,
        )
    quiesced_resources = journal.load_resources(lease.transaction_id)
    quiescence = CloneQuiescenceProof(
        transaction_id=lease.transaction_id,
        attempt_id=lease.attempt_id,
        resource_ids=tuple(
            f"{resource.role.value}:{resource.resource_id}"
            for resource in quiesced_resources
        ),
        resource_state_digest=runtimeResourceStateDigest(quiesced_resources),
        all_quiesced=True,
        observed_at=datetime.now(timezone.utc).isoformat(),
        runtime_token=lease.runtime_token,
    )
    snapshot_root = controller / "candidate-snapshots"
    snapshot_blob_root = snapshot_root / lease.transaction_id / "blobs"
    snapshot_blob_root.mkdir(parents=True)
    candidate_object_root = controller / "candidate-writer" / "objects"
    candidate_object_root.mkdir(parents=True)
    candidate_writer = GitObjectWriter(
        object_root=candidate_object_root,
        blob_root=snapshot_blob_root,
        sha1dc_oracle=oracle,
        sha1dc_evidence=evidence,
        writer_version_digest="7" * 64,
        forbidden_roots=(canonical, checkout),
        canonical_object_verifier=lambda raw, object_record: parser.proveLooseObject(
            raw=raw,
            expected=object_record,
        ).receipt_id,
    )
    ref_store = LooseRefStore(attestation)
    coordinator = StagingCoordinator(
        attestation=attestation,
        journal=journal,
        receipt_store=ReceiptStore(
            controller / "receipts",
            forbidden_roots=(canonical, checkout),
        ),
        ref_store=ref_store,
        writer=candidate_writer,
        parser_image_digest=image.manifest_digest,
        parser_security_profile_digest=canonical_digest(
            {
                "network": "none",
                "rootfs": "readonly",
                "capabilities": "drop-all",
                "user": "65532:65532",
            }
        ),
    )
    metadata = CommitMetadata(
        author_name="GALAXY Kernel",
        author_email="kernel@example.invalid",
        committer_name="GALAXY Kernel",
        committer_email="kernel@example.invalid",
        timestamp=1_700_000_000,
        timezone="+0000",
        message="transaction tx-clone-canary\n",
    )
    kernel = TransactionalCloneKernel(
        parser=parser,
        snapshot_root=snapshot_root,
        verification_root=controller / "verification",
        expected_manifest_provider=lambda *_args: source.manifest,
        quiescence_provider=lambda *_args: quiescence,
        commit_metadata_provider=lambda *_args: metadata,
        coordinator_factory=lambda _lease: coordinator,
    )
    artifacts = kernel.prepare(lease, task_state=object(), subtask={})
    context = kernel._contexts[lease.transaction_id]
    parsed = context.request.parsed
    staged = artifacts.staged

    assert [(entry.path, entry.size) for entry in parsed.manifest.entries] == [
        ("edit.txt", len(b"after\n")),
        ("untracked.txt", len(b"new\n")),
    ]

    assert ref_store.readRef(staged.checkpoint_ref) == staged.proposed_revision
    assert ref_store.readRef(staged.staged_ref) == staged.proposed_revision
    assert (canonical / ".git" / "refs" / "heads" / "main").read_bytes() == canonical_head
    assert (canonical / ".git" / "index").read_bytes() == canonical_index
    assert (canonical / "edit.txt").read_bytes() == canonical_files["edit.txt"]
    assert (canonical / "delete.txt").read_bytes() == canonical_files["delete.txt"]
    assert not (canonical / "untracked.txt").exists()
    assert goldstone.read_bytes() == b"untouched\n"
