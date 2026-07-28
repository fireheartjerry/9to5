"""Frozen candidate, staged-revision, and runtime-resource lease contracts."""
from __future__ import annotations

import os
import subprocess
from itertools import count
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

from platform_core.runtime import candidate as candidate_mod
from platform_core.runtime.candidate import (
    CandidateResult,
    CloneLease,
    CloneQuiescenceProof,
    CredentialResourceState,
    ProcessResourceState,
    PromotionRefused,
    ResourceRole,
    RunnerKind,
    RuntimeResourceLease,
    StagedRevisionLease,
    StagedRevisionRefused,
    processStartToken,
    runtimeResourceIsQuiescent,
    snapshotCloneTree,
)
from platform_core.runtime.object_manifest import ManifestPolicy, ObjectManifest
from tests.execution import test_execution_clone as snapshot_support

SHA_A = "a" * 40
SHA_B = "b" * 40
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
_ADMISSION_SEQUENCE = count()
_ADMISSION_SUPPORT: dict[CloneLease, tuple[Any, ManifestPolicy]] = {}


def _clone(tmp_path: Path, *, runner: RunnerKind = RunnerKind.LOCAL) -> CloneLease:
    checkout = tmp_path / "controller" / "checkouts" / "tx-001"
    return CloneLease(
        transaction_id="tx-001",
        task_id="task-001",
        subtask_id="subtask-001",
        attempt_id="attempt-001",
        checkout_path=str(checkout),
        expected_base_revision=SHA_A,
        runner_kind=runner,
        candidate_branch="refs/heads/9to5/candidates/tx-001",
        repository_id=DIGEST_A,
        ownership_nonce=DIGEST_B,
        git_dir=str(checkout / ".git"),
        git_common_dir=str(checkout / ".git"),
        canonical_git_common_dir=str(tmp_path / "canonical" / ".git"),
        closure_manifest_digest="c" * 64,
        shallow_root_revision=SHA_A,
        hardlink_count_verified=True,
        alternates_absent=True,
        remote_absent=True,
        linked_worktree_pointer_absent=True,
        registered_at="2026-07-16T12:00:00+00:00",
        runtime_token=object(),
    )


def test_clone_lease_is_frozen_json_safe_and_omits_process_token(tmp_path: Path) -> None:
    lease = _clone(tmp_path)
    with pytest.raises(FrozenInstanceError):
        lease.checkout_path = "changed"  # type: ignore[misc]
    value = lease.toDict()
    assert value["runner_kind"] == "local"
    assert "runtime_token" not in value
    assert value["git_dir"].startswith(value["checkout_path"])


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("git_common_dir", "canonical", "inside the private clone"),
        ("alternates_absent", False, "alternates"),
        ("remote_absent", False, "remote"),
        ("linked_worktree_pointer_absent", False, "linked-worktree"),
        ("hardlink_count_verified", False, "hardlink"),
    ],
)
def test_clone_lease_refuses_any_link_back_to_canonical(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    lease = _clone(tmp_path)
    values = lease.__dict__ | {field: value}
    if field == "git_common_dir":
        values[field] = lease.canonical_git_common_dir
    with pytest.raises(ValueError, match=message):
        CloneLease(**values)


def test_staged_revision_lease_binds_checkpoint_snapshot_and_receipt(
    tmp_path: Path,
) -> None:
    clone = _clone(tmp_path, runner=RunnerKind.DOCKER)
    lease = StagedRevisionLease(
        transaction_id=clone.transaction_id,
        task_id=clone.task_id,
        subtask_id=clone.subtask_id,
        attempt_id=clone.attempt_id,
        runner_kind=clone.runner_kind,
        candidate_snapshot_digest=DIGEST_A,
        parser_manifest_digest=DIGEST_B,
        blob_set_digest="c" * 64,
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
    assert lease.toDict()["runner_kind"] == "docker"
    assert "cleanup_token" not in lease.toDict()


def test_candidate_result_never_conflates_cleanup_warning_with_promotion() -> None:
    result = CandidateResult(
        entered=True,
        staged=True,
        promoted=True,
        removed=False,
        expected_revision=SHA_A,
        observed_revision=SHA_A,
        resulting_revision=SHA_B,
        checkpoint_revision=SHA_B,
        candidate_snapshot_digest=DIGEST_A,
        parser_manifest_digest=DIGEST_B,
        staged_tree_digest="c" * 64,
        checkpoint_ref="refs/9to5/checkpoints/tx-001",
        staged_ref="refs/9to5/staged/tx-001",
        quarantine_ref="",
        error="",
        cleanup_error="checkout remained for recovery",
    )
    assert result.succeeded is True
    assert result.toDict()["cleanup_error"]


def test_owned_fence_release_never_deletes_a_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fence = tmp_path / "index.lock"
    owned = candidate_mod._acquireOwnedFile(fence, b"owned")
    displaced = tmp_path / "owned-displaced"
    real_remove = candidate_mod.NativeDirectoryHandle.removeFile

    def replace_before_remove(directory, name, *, expected=None):
        fence.rename(displaced)
        fence.write_bytes(b"foreign")
        return real_remove(directory, name, expected=expected)

    monkeypatch.setattr(
        candidate_mod.NativeDirectoryHandle,
        "removeFile",
        replace_before_remove,
    )

    with pytest.raises(PromotionRefused, match="changed ownership"):
        candidate_mod._releaseOwnedFile(owned)

    assert fence.read_bytes() == b"foreign"
    assert displaced.read_bytes() == b"owned"


def test_runtime_resource_lease_is_role_tagged_and_state_typed() -> None:
    lease = RuntimeResourceLease(
        resource_id="driver-001",
        run_id="run-001",
        transaction_id="tx-001",
        controller_scope_id="controller-001",
        role=ResourceRole.MODEL_DRIVER,
        backend="docker",
        ownership_nonce=DIGEST_A,
        state=ProcessResourceState.REGISTERED,
        cleanup_locator_digest=DIGEST_B,
        pid=0,
        process_group_id=0,
        container_id="",
        image_digest="c" * 64,
        entrypoint_digest="d" * 64,
        mount_digest="e" * 64,
        environment_digest="f" * 64,
        security_profile_digest="1" * 64,
        created_at="2026-07-16T12:00:00+00:00",
        updated_at="2026-07-16T12:00:00+00:00",
    )
    assert lease.toDict()["role"] == "model_driver"
    with pytest.raises(ValueError, match="credential state"):
        RuntimeResourceLease(
            **(lease.__dict__ | {"role": ResourceRole.CREDENTIAL_LEASE})
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pid", True),
        ("process_group_id", False),
        ("revocation_generation", True),
        ("backend", None),
        ("provider", 1),
        ("auth_mode", object()),
        ("secret_channel_id", []),
        ("issuer_id", {}),
        ("error", 7),
    ],
)
def test_runtime_resource_lease_rejects_scalar_type_confusion(
    field: str,
    value: object,
) -> None:
    base = RuntimeResourceLease(
        resource_id="driver-001",
        run_id="run-001",
        transaction_id="tx-001",
        controller_scope_id="controller-001",
        role=ResourceRole.MODEL_DRIVER,
        backend="docker",
        ownership_nonce=DIGEST_A,
        state=ProcessResourceState.REGISTERED,
        cleanup_locator_digest=DIGEST_B,
        pid=0,
        process_group_id=0,
        container_id="",
        image_digest="c" * 64,
        entrypoint_digest="d" * 64,
        mount_digest="e" * 64,
        environment_digest="f" * 64,
        security_profile_digest="1" * 64,
        created_at="2026-07-16T12:00:00+00:00",
        updated_at="2026-07-16T12:00:00+00:00",
    )

    with pytest.raises((TypeError, ValueError)):
        RuntimeResourceLease(**(base.__dict__ | {field: value}))


def test_runtime_resource_lease_requires_nonempty_backend() -> None:
    lease = RuntimeResourceLease(
        resource_id="driver-001",
        run_id="run-001",
        transaction_id="tx-001",
        controller_scope_id="controller-001",
        role=ResourceRole.MODEL_DRIVER,
        backend="docker",
        ownership_nonce=DIGEST_A,
        state=ProcessResourceState.REGISTERED,
        cleanup_locator_digest=DIGEST_B,
        pid=0,
        process_group_id=0,
        container_id="",
        image_digest="c" * 64,
        entrypoint_digest="d" * 64,
        mount_digest="e" * 64,
        environment_digest="f" * 64,
        security_profile_digest="1" * 64,
        created_at="2026-07-16T12:00:00+00:00",
        updated_at="2026-07-16T12:00:00+00:00",
    )

    with pytest.raises(ValueError, match="backend"):
        RuntimeResourceLease(**(lease.__dict__ | {"backend": ""}))


def _registered_resource_for_validation(
    *,
    role: ResourceRole = ResourceRole.MODEL_DRIVER,
    backend: str = "local",
) -> RuntimeResourceLease:
    values: dict[str, object] = {
        "resource_id": "driver-001",
        "run_id": "run-001",
        "transaction_id": "tx-001",
        "controller_scope_id": "controller-001",
        "role": role,
        "backend": backend,
        "ownership_nonce": DIGEST_A,
        "state": ProcessResourceState.REGISTERED,
        "cleanup_locator_digest": DIGEST_B,
        "pid": 0,
        "process_group_id": 0,
        "container_id": "",
        "image_digest": "" if backend == "local" else "c" * 64,
        "entrypoint_digest": "d" * 64,
        "mount_digest": "e" * 64,
        "environment_digest": "f" * 64,
        "security_profile_digest": "1" * 64,
        "created_at": "2026-07-16T12:00:00+00:00",
        "updated_at": "2026-07-16T12:00:00+00:00",
        "depends_on": (),
    }
    if role is ResourceRole.CREDENTIAL_LEASE:
        values.update(
            resource_id="credential-001",
            backend="credential-broker",
            state=CredentialResourceState.REGISTERED,
            image_digest="",
            entrypoint_digest="",
            mount_digest="",
            environment_digest="",
            provider="claude",
            auth_mode="subscription",
            secret_channel_id="channel-001",
            expires_at="2026-07-16T12:05:00+00:00",
            issuer_id="credential-broker-001",
            revocation_generation=1,
        )
    return RuntimeResourceLease(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("backend", ["clone", "remote", "LOCAL"])
def test_registration_validator_rejects_open_backend_kinds(backend: str) -> None:
    resource = _registered_resource_for_validation()
    if backend:
        resource = RuntimeResourceLease(**(resource.__dict__ | {"backend": backend}))

    validator = getattr(candidate_mod, "validateRuntimeResourceRegistration")
    with pytest.raises(ValueError, match="backend"):
        validator(resource)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("provider", "", "provider"),
        ("auth_mode", "", "auth_mode"),
        ("secret_channel_id", "", "secret channel"),
        ("expires_at", "", "expires_at"),
        ("issuer_id", "", "issuer_id"),
        ("revocation_generation", 0, "revocation_generation"),
        ("cleanup_locator_digest", "", "cleanup"),
        ("security_profile_digest", "", "security"),
        ("entrypoint_digest", "2" * 64, "process plan"),
    ],
)
def test_credential_registration_requires_complete_nonsecret_metadata_only(
    field: str,
    value: object,
    message: str,
) -> None:
    resource = _registered_resource_for_validation(
        role=ResourceRole.CREDENTIAL_LEASE,
        backend="credential-broker",
    )
    changes = resource.__dict__ | {field: value}
    validator = getattr(candidate_mod, "validateRuntimeResourceRegistration")
    with pytest.raises(ValueError, match=message):
        validator(RuntimeResourceLease(**changes))


def test_credential_registration_expiry_must_follow_registration() -> None:
    resource = _registered_resource_for_validation(
        role=ResourceRole.CREDENTIAL_LEASE,
        backend="credential-broker",
    )
    validator = getattr(candidate_mod, "validateRuntimeResourceRegistration")

    with pytest.raises(ValueError, match="strictly after"):
        validator(
            RuntimeResourceLease(
                **(resource.__dict__ | {"expires_at": resource.created_at})
            )
        )


def test_runtime_resource_dependencies_require_canonical_sorted_order() -> None:
    resource = _registered_resource_for_validation()

    with pytest.raises(ValueError, match="canonical sorted"):
        RuntimeResourceLease(
            **(
                resource.__dict__
                | {
                    "depends_on": (
                        "model_driver:z-driver",
                        "authority_watchdog:a-watchdog",
                    )
                }
            )
        )


@pytest.mark.parametrize(
    ("backend", "field", "value", "message"),
    [
        ("local", "image_digest", "2" * 64, "local"),
        ("local", "entrypoint_digest", "", "entrypoint"),
        ("local", "provider", "claude", "credential"),
        ("docker", "image_digest", "", "image"),
        ("docker", "pid", 7, "process"),
        ("docker", "secret_channel_id", "channel-001", "credential"),
    ],
)
def test_process_registration_enforces_backend_specific_plan_fields(
    backend: str,
    field: str,
    value: object,
    message: str,
) -> None:
    resource = _registered_resource_for_validation(backend=backend)
    changes = resource.__dict__ | {field: value}
    if field == "pid":
        changes["process_start_token"] = "2" * 64
    malformed = RuntimeResourceLease(**changes)

    validator = getattr(candidate_mod, "validateRuntimeResourceRegistration")
    with pytest.raises(ValueError, match=message):
        validator(malformed)


def test_process_resource_identity_binds_pid_birth_and_detects_reuse() -> None:
    token = processStartToken(os.getpid())
    assert token is not None
    lease = RuntimeResourceLease(
        resource_id="driver-live",
        run_id="run-001",
        transaction_id="tx-001",
        controller_scope_id="controller-001",
        role=ResourceRole.MODEL_DRIVER,
        backend="local",
        ownership_nonce=DIGEST_A,
        state=ProcessResourceState.STARTED,
        cleanup_locator_digest=DIGEST_B,
        pid=os.getpid(),
        process_group_id=os.getpid(),
        container_id="",
        image_digest="",
        entrypoint_digest="c" * 64,
        mount_digest="d" * 64,
        environment_digest="e" * 64,
        security_profile_digest="f" * 64,
        created_at="2026-07-16T12:00:00+00:00",
        updated_at="2026-07-16T12:00:00+00:00",
        process_start_token=token,
    )

    assert runtimeResourceIsQuiescent(lease) is False
    reused = RuntimeResourceLease(
        **(
            lease.__dict__
            | {
                "state": ProcessResourceState.QUIESCED,
                "process_start_token": "0" * 64,
            }
        )
    )
    assert runtimeResourceIsQuiescent(reused) is True

    with pytest.raises(ValueError, match="process_start_token"):
        RuntimeResourceLease(
            **(lease.__dict__ | {"process_start_token": ""})
        )


def _snapshot_policy() -> ManifestPolicy:
    return ManifestPolicy(
        reserved_roots=("state/tasks",),
        max_files=20,
        max_total_bytes=4096,
        max_file_bytes=2048,
        max_depth=8,
        max_path_bytes=240,
    )


def _quiescence(lease: CloneLease) -> CloneQuiescenceProof:
    return CloneQuiescenceProof(
        transaction_id=lease.transaction_id,
        attempt_id=lease.attempt_id,
        resource_ids=("model_driver:driver-001",),
        resource_state_digest=DIGEST_A,
        all_quiesced=True,
        observed_at="2026-07-16T12:05:00+00:00",
        runtime_token=lease.runtime_token,
    )


def _snapshot_admission(
    lease: CloneLease,
    policy: ManifestPolicy,
) -> tuple[object, CloneQuiescenceProof]:
    checkout = Path(lease.checkout_path)
    git_dir = Path(lease.git_dir)
    canonical_git = Path(lease.canonical_git_common_dir)
    canonical_git.mkdir(parents=True, exist_ok=True)
    (git_dir / "objects" / "info").mkdir(parents=True, exist_ok=True)
    candidate_ref = git_dir / lease.candidate_branch
    candidate_ref.parent.mkdir(parents=True, exist_ok=True)
    (git_dir / "config").write_bytes(
        b"[core]\n\trepositoryformatversion = 0\n\tbare = false\n"
    )
    (git_dir / "HEAD").write_bytes(
        f"ref: {lease.candidate_branch}\n".encode("ascii")
    )
    candidate_ref.write_bytes(f"{lease.expected_base_revision}\n".encode("ascii"))
    (git_dir / "shallow").write_bytes(
        f"{lease.expected_base_revision}\n".encode("ascii")
    )
    cached = _ADMISSION_SUPPORT.get(lease)
    if cached is None:
        support_root = (
            checkout.parents[1]
            / "snapshot-admission-tests"
            / f"case-{next(_ADMISSION_SEQUENCE):08d}"
        )
        expected = ObjectManifest(
            expected_revision=lease.expected_base_revision,
            entries=(),
            attribute_rules=(),
            policy=policy,
        )
        coordinator = snapshot_support._FlowCoordinator(
            lease,
            expected,
            support_root / "controller",
        )
        kernel = snapshot_support._flow_kernel(
            support_root,
            lease,
            expected,
            coordinator,
            observed_at="2099-01-01T00:00:00+00:00",
        )
        _ADMISSION_SUPPORT[lease] = (kernel, policy)
    else:
        kernel, cached_policy = cached
        if cached_policy != policy:
            raise AssertionError("snapshot test admission policy changed")
    patch = pytest.MonkeyPatch()
    try:
        return snapshot_support._capture_legitimate_snapshot_admission(
            patch,
            kernel,
            lease,
        )
    finally:
        patch.undo()


def _snapshot_with_admission(
    lease: CloneLease,
    **kwargs,
):
    policy = kwargs.get("policy")
    if not isinstance(policy, ManifestPolicy):
        raise TypeError("snapshot test helper requires a typed policy")
    admission, exact_quiescence = _snapshot_admission(lease, policy)
    return snapshotCloneTree(
        lease,
        quiescence=exact_quiescence,
        admission=admission,
        **kwargs,
    )


def test_snapshot_requires_exact_one_use_process_local_admission(
    tmp_path: Path,
) -> None:
    lease = _clone(tmp_path)
    checkout = Path(lease.checkout_path)
    (checkout / ".git").mkdir(parents=True)
    (checkout / "tracked.txt").write_bytes(b"changed\n")
    quiescence = _quiescence(lease)

    with pytest.raises(StagedRevisionRefused, match="one-use.*admission"):
        snapshotCloneTree(
            lease,
            quiescence=quiescence,
            admission=None,
            policy=_snapshot_policy(),
            snapshot_root=tmp_path / "controller" / "missing-admission",
        )
    with pytest.raises(StagedRevisionRefused, match="one-use.*admission"):
        snapshotCloneTree(
            lease,
            quiescence=quiescence,
            admission=object(),
            policy=_snapshot_policy(),
            snapshot_root=tmp_path / "controller" / "forged-admission",
        )

    admission, exact_quiescence = _snapshot_admission(
        lease,
        _snapshot_policy(),
    )
    snapshot = snapshotCloneTree(
        lease,
        quiescence=exact_quiescence,
        admission=admission,
        policy=_snapshot_policy(),
        snapshot_root=tmp_path / "controller" / "accepted-admission",
    )
    assert snapshot.entries[0].path == "tracked.txt"
    with pytest.raises(StagedRevisionRefused, match="consumed"):
        snapshotCloneTree(
            lease,
            quiescence=exact_quiescence,
            admission=admission,
            policy=_snapshot_policy(),
            snapshot_root=tmp_path / "controller" / "replayed-admission",
        )


def test_snapshot_clone_tree_is_complete_immutable_and_content_addressed(
    tmp_path: Path,
) -> None:
    lease = _clone(tmp_path)
    checkout = Path(lease.checkout_path)
    (checkout / ".git").mkdir(parents=True)
    (checkout / "tracked.txt").write_bytes(b"changed\n")
    (checkout / "nested").mkdir()
    (checkout / "nested" / "new.txt").write_bytes(b"new\n")

    snapshot = _snapshot_with_admission(
        lease,
        policy=_snapshot_policy(),
        snapshot_root=tmp_path / "controller" / "snapshots",
    )

    assert [entry.path for entry in snapshot.entries] == [
        "nested/new.txt",
        "tracked.txt",
    ]
    for entry in snapshot.entries:
        blob = snapshot.blob_root / entry.blob_sha256[:2] / entry.blob_sha256
        assert blob.is_file()
        assert len(blob.read_bytes()) == entry.size
    manifest = (
        tmp_path
        / "controller"
        / "snapshots"
        / lease.transaction_id
        / "snapshot.json"
    )
    assert manifest.is_file()
    replay = _snapshot_with_admission(
        lease,
        policy=_snapshot_policy(),
        snapshot_root=tmp_path / "controller" / "snapshots",
    )
    assert replay.toDict() == snapshot.toDict()


@pytest.mark.skipif(os.name != "nt", reason="Windows retained-handle boundary")
def test_snapshot_reads_retained_root_when_candidate_path_is_rebound(
    tmp_path: Path,
    monkeypatch,
) -> None:
    lease = _clone(tmp_path)
    checkout = Path(lease.checkout_path)
    (checkout / ".git").mkdir(parents=True)
    (checkout / "original.txt").write_bytes(b"original\n")
    held = checkout.with_name("candidate-held")
    opened = False
    real_open = candidate_mod.openNativeDirectory

    def open_then_rebind(path):
        nonlocal opened
        directory = real_open(path)
        checkout.rename(held)
        checkout.mkdir()
        (checkout / ".git").mkdir()
        (checkout / "replacement.txt").write_bytes(b"replacement\n")
        opened = True
        return directory

    monkeypatch.setattr(candidate_mod, "openNativeDirectory", open_then_rebind)
    snapshot = _snapshot_with_admission(
        lease,
        policy=_snapshot_policy(),
        snapshot_root=tmp_path / "controller" / "snapshots",
    )

    assert opened is True
    assert [entry.path for entry in snapshot.entries] == ["original.txt"]
    assert (checkout / "replacement.txt").read_bytes() == b"replacement\n"


def test_snapshot_refuses_live_or_hardlinked_candidate_bytes(tmp_path: Path) -> None:
    lease = _clone(tmp_path)
    checkout = Path(lease.checkout_path)
    (checkout / ".git").mkdir(parents=True)
    outside = tmp_path / "outside-goldstone.txt"
    outside.write_bytes(b"outside\n")
    linked = checkout / "linked.txt"
    linked.parent.mkdir(parents=True, exist_ok=True)
    linked.hardlink_to(outside)

    with pytest.raises(StagedRevisionRefused, match="link"):
        _snapshot_with_admission(
            lease,
            policy=_snapshot_policy(),
            snapshot_root=tmp_path / "controller" / "snapshots",
        )
    assert outside.read_bytes() == b"outside\n"


@pytest.mark.skipif(os.name != "nt", reason="Windows junction canary")
def test_snapshot_refuses_a_junction_without_reading_its_target(tmp_path: Path) -> None:
    lease = _clone(tmp_path)
    checkout = Path(lease.checkout_path)
    (checkout / ".git").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    goldstone = outside / "goldstone.txt"
    goldstone.write_bytes(b"outside\n")
    junction = checkout / "escape"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=15,
    )
    if created.returncode != 0:
        pytest.skip("junction creation is unavailable")

    with pytest.raises(StagedRevisionRefused, match="reparse"):
        _snapshot_with_admission(
            lease,
            policy=_snapshot_policy(),
            snapshot_root=tmp_path / "controller" / "snapshots",
        )
    assert goldstone.read_bytes() == b"outside\n"


@pytest.mark.skipif(os.name != "nt", reason="Windows short-name alias canary")
def test_snapshot_refuses_a_long_short_name_alias_collision(
    tmp_path: Path,
    monkeypatch,
) -> None:
    lease = _clone(tmp_path)
    checkout = Path(lease.checkout_path)
    (checkout / ".git").mkdir(parents=True)
    (checkout / "alpha.txt").write_bytes(b"alpha\n")
    (checkout / "beta.txt").write_bytes(b"beta\n")
    real_open = candidate_mod.openNativeDirectory

    class AliasRoot:
        def __init__(self, inner):
            self.inner = inner

        @property
        def identity(self):
            return self.inner.identity

        def listEntries(self):
            entries = []
            for entry in self.inner.listEntries():
                entries.append(
                    candidate_mod.NativeDirectoryEntry(
                        name=entry.name,
                        identity=entry.identity,
                        short_name="alpha.txt" if entry.name == "beta.txt" else entry.short_name,
                    )
                )
            return tuple(entries)

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
    with pytest.raises(StagedRevisionRefused, match="alias"):
        _snapshot_with_admission(
            lease,
            policy=_snapshot_policy(),
            snapshot_root=tmp_path / "controller" / "snapshots",
        )


def test_snapshot_replay_refuses_changed_candidate_and_preserves_first_evidence(
    tmp_path: Path,
) -> None:
    lease = _clone(tmp_path)
    checkout = Path(lease.checkout_path)
    (checkout / ".git").mkdir(parents=True)
    candidate = checkout / "tracked.txt"
    candidate.write_bytes(b"first\n")
    root = tmp_path / "controller" / "snapshots"

    first = _snapshot_with_admission(
        lease,
        policy=_snapshot_policy(),
        snapshot_root=root,
    )
    first_manifest = (root / lease.transaction_id / "snapshot.json").read_bytes()
    first_blob = first.blob_root / first.entries[0].blob_sha256[:2] / first.entries[0].blob_sha256
    candidate.write_bytes(b"second\n")

    with pytest.raises(StagedRevisionRefused, match="collision"):
        _snapshot_with_admission(
            lease,
            policy=_snapshot_policy(),
            snapshot_root=root,
        )
    assert (root / lease.transaction_id / "snapshot.json").read_bytes() == first_manifest
    assert first_blob.read_bytes() == b"first\n"


@pytest.mark.parametrize("unsafe_kind", ["reserved", "quota", "inside"])
def test_snapshot_refuses_unsafe_tree_or_storage_boundary(
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    lease = _clone(tmp_path)
    checkout = Path(lease.checkout_path)
    (checkout / ".git").mkdir(parents=True)
    policy = _snapshot_policy()
    root = tmp_path / "controller" / "snapshots"
    if unsafe_kind == "reserved":
        target = checkout / "state" / "tasks" / "run.json"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"{}")
    elif unsafe_kind == "quota":
        (checkout / "large.bin").write_bytes(b"x" * (policy.max_file_bytes + 1))
    else:
        (checkout / "tracked.txt").write_bytes(b"content")
        root = checkout / "snapshot"

    with pytest.raises(StagedRevisionRefused, match="reserved|quota|outside"):
        _snapshot_with_admission(
            lease,
            policy=policy,
            snapshot_root=root,
        )
