"""Deterministic loose-object construction from inert blob manifests."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import zlib
from dataclasses import replace
from pathlib import Path

import pytest

import platform_core.runtime.git_object_writer as object_writer_module
from platform_core.runtime.canonical_repo import attestCanonicalRepository
from platform_core.runtime.git_object_writer import (
    CandidateRepositoryLease,
    CommitMetadata,
    GitObjectWriter,
    ObjectWriterRefused,
    SourceObjectClosure,
    VerificationRepositoryLease,
    readLooseObject,
)
from platform_core.runtime.object_manifest import ManifestEntry, ManifestPolicy, ObjectManifest
from platform_core.runtime.sha1dc import qualifyGitSha1dc


def _fixture(tmp_path: Path):
    git = shutil.which("git")
    assert git is not None
    evidence, oracle = qualifyGitSha1dc(
        executable=git,
        sterile_root=tmp_path / "sha1dc",
    )
    blob_root = tmp_path / "blobs"
    values = {"README.md": b"read\n", "pkg/mod.py": b"pass\n"}
    entries = []
    for index, (path, payload) in enumerate(values.items(), 1):
        raw_digest = hashlib.sha256(payload).hexdigest()
        framed = b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload
        oid = oracle.hashObject("blob", payload)
        location = blob_root / raw_digest[:2] / raw_digest
        location.parent.mkdir(parents=True, exist_ok=True)
        location.write_bytes(payload)
        entries.append(
            ManifestEntry(
                path=path,
                mode=0o100755 if path.endswith(".py") else 0o100644,
                blob_oid=oid,
                blob_sha256=raw_digest,
                framed_object_sha256=hashlib.sha256(framed).hexdigest(),
                size=len(payload),
            )
        )
    manifest = ObjectManifest(
        expected_revision="a" * 40,
        entries=tuple(entries),
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
    metadata = CommitMetadata(
        author_name="GALAXY Kernel",
        author_email="kernel@example.invalid",
        committer_name="GALAXY Kernel",
        committer_email="kernel@example.invalid",
        timestamp=1_700_000_000,
        timezone="+0000",
        message="transaction tx-001\n",
    )
    return evidence, oracle, blob_root, manifest, metadata


def test_writer_builds_deterministic_complete_loose_object_closure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence, oracle, blobs, manifest, metadata = _fixture(tmp_path)
    writer = GitObjectWriter(
        object_root=tmp_path / "shadow" / "objects",
        blob_root=blobs,
        sha1dc_oracle=oracle,
        sha1dc_evidence=evidence,
        writer_version_digest="f" * 64,
        forbidden_roots=(tmp_path / "canonical",),
    )
    first = writer.writeRevision(manifest=manifest, metadata=metadata)
    second = writer.writeRevision(manifest=manifest, metadata=metadata)
    assert second == first
    assert first.parent_oid == manifest.expected_revision
    assert len(first.tree_oid) == 40
    assert len(first.commit_oid) == 40
    assert len(first.object_closure_digest) == 64
    assert len(first.proposed_index_digest) == 64
    assert {record.object_type for record in first.objects} == {"blob", "tree", "commit"}

    def refuse_ordinary_sha1(*_args, **_kwargs):
        raise AssertionError("ordinary SHA-1 must not validate a Git object identity")

    monkeypatch.setattr(object_writer_module.hashlib, "sha1", refuse_ordinary_sha1)
    commit_type, commit_payload = readLooseObject(
        writer.object_root,
        first.commit_oid,
        sha1dc_oracle=oracle,
    )
    assert commit_type == "commit"
    assert f"tree {first.tree_oid}\n".encode() in commit_payload
    assert f"parent {manifest.expected_revision}\n".encode() in commit_payload
    assert commit_payload.endswith(b"\n\ntransaction tx-001\n")


def test_writer_plans_every_manifest_tree_oid_without_reading_blob_storage(
    tmp_path: Path,
) -> None:
    evidence, oracle, blobs, manifest, metadata = _fixture(tmp_path)
    writer = GitObjectWriter(
        object_root=tmp_path / "shadow" / "objects",
        blob_root=blobs,
        sha1dc_oracle=oracle,
        sha1dc_evidence=evidence,
        writer_version_digest="f" * 64,
    )
    receipt = writer.planRevision(manifest=manifest, metadata=metadata)
    shutil.rmtree(blobs)

    planned = writer.planTreeOids(manifest)

    pkg_entry = next(entry for entry in manifest.entries if entry.path == "pkg/mod.py")
    pkg_payload = (
        b"100755 mod.py\0" + bytes.fromhex(pkg_entry.blob_oid)
    )
    assert planned == {
        "": receipt.tree_oid,
        "pkg": oracle.hashObject("tree", pkg_payload),
    }


def test_written_objects_are_readable_by_repo_less_git_cat_file(tmp_path: Path) -> None:
    evidence, oracle, blobs, manifest, metadata = _fixture(tmp_path)
    writer = GitObjectWriter(
        object_root=tmp_path / "shadow" / "objects",
        blob_root=blobs,
        sha1dc_oracle=oracle,
        sha1dc_evidence=evidence,
        writer_version_digest="f" * 64,
    )
    receipt = writer.writeRevision(manifest=manifest, metadata=metadata)
    git_dir = tmp_path / "shadow"
    (git_dir / "HEAD").write_text("ref: refs/heads/unused\n", encoding="ascii")
    (git_dir / "refs" / "heads").mkdir(parents=True)
    (git_dir / "config").write_text(
        "[core]\n\trepositoryformatversion = 0\n\tbare = true\n", encoding="ascii"
    )
    result = subprocess.run(
        [str(Path(evidence.executable_path)), "cat-file", "-p", receipt.commit_oid],
        cwd=tmp_path,
        env={
            "GIT_DIR": str(git_dir),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_NO_LAZY_FETCH": "1",
            "SystemRoot": os.environ.get("SystemRoot", ""),
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stdout.startswith(f"tree {receipt.tree_oid}\n".encode())


def test_blob_or_manifest_drift_refuses_before_object_install(tmp_path: Path) -> None:
    evidence, oracle, blobs, manifest, metadata = _fixture(tmp_path)
    first = manifest.entries[0]
    blob_path = blobs / first.blob_sha256[:2] / first.blob_sha256
    blob_path.write_bytes(b"drift")
    writer = GitObjectWriter(
        object_root=tmp_path / "shadow" / "objects",
        blob_root=blobs,
        sha1dc_oracle=oracle,
        sha1dc_evidence=evidence,
        writer_version_digest="f" * 64,
    )
    with pytest.raises(ObjectWriterRefused, match="blob digest"):
        writer.writeRevision(manifest=manifest, metadata=metadata)
    assert not writer.object_root.exists()


def test_existing_loose_object_collision_is_preserved_and_refused(tmp_path: Path) -> None:
    evidence, oracle, blobs, manifest, metadata = _fixture(tmp_path)
    object_root = tmp_path / "shadow" / "objects"
    first = manifest.entries[0]
    collision = object_root / first.blob_oid[:2] / first.blob_oid[2:]
    collision.parent.mkdir(parents=True)
    collision.write_bytes(zlib.compress(b"blob 1\0x", level=9))
    before = collision.read_bytes()
    writer = GitObjectWriter(
        object_root=object_root,
        blob_root=blobs,
        sha1dc_oracle=oracle,
        sha1dc_evidence=evidence,
        writer_version_digest="f" * 64,
    )
    with pytest.raises(ObjectWriterRefused, match="existing loose object"):
        writer.writeRevision(manifest=manifest, metadata=metadata)
    assert collision.read_bytes() == before


def test_synthetic_duplicate_oid_with_different_strong_bytes_refuses_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence, oracle, blobs, manifest, metadata = _fixture(tmp_path)
    duplicate_oid = "e" * 40
    colliding_manifest = ObjectManifest(
        expected_revision=manifest.expected_revision,
        entries=tuple(
            ManifestEntry(
                path=entry.path,
                mode=entry.mode,
                blob_oid=duplicate_oid,
                blob_sha256=entry.blob_sha256,
                framed_object_sha256=entry.framed_object_sha256,
                size=entry.size,
            )
            for entry in manifest.entries
        ),
        attribute_rules=manifest.attribute_rules,
        policy=manifest.policy,
    )
    monkeypatch.setattr(
        oracle,
        "hashObject",
        lambda object_type, payload: duplicate_oid,
    )
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    goldstone = canonical / "goldstone.txt"
    goldstone.write_bytes(b"unchanged\n")
    object_root = tmp_path / "shadow" / "objects"
    writer = GitObjectWriter(
        object_root=object_root,
        blob_root=blobs,
        sha1dc_oracle=oracle,
        sha1dc_evidence=evidence,
        writer_version_digest="f" * 64,
        forbidden_roots=(canonical,),
    )

    with pytest.raises(ObjectWriterRefused, match="collision"):
        writer.writeRevision(manifest=colliding_manifest, metadata=metadata)

    assert not object_root.exists()
    assert goldstone.read_bytes() == b"unchanged\n"


def test_writer_roots_cannot_overlap_each_other_or_forbidden_repository(
    tmp_path: Path,
) -> None:
    evidence, oracle, blobs, _, _ = _fixture(tmp_path)
    with pytest.raises(ObjectWriterRefused, match="must not overlap"):
        GitObjectWriter(
            object_root=blobs / "objects",
            blob_root=blobs,
            sha1dc_oracle=oracle,
            sha1dc_evidence=evidence,
            writer_version_digest="f" * 64,
        )
    with pytest.raises(ObjectWriterRefused, match="forbidden"):
        GitObjectWriter(
            object_root=tmp_path / "canonical" / ".git" / "objects",
            blob_root=blobs,
            sha1dc_oracle=oracle,
            sha1dc_evidence=evidence,
            writer_version_digest="f" * 64,
            forbidden_roots=(tmp_path / "canonical",),
        )


def test_writer_rejects_aggregate_manifest_before_object_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence, oracle, blobs, manifest, metadata = _fixture(tmp_path)
    writer = GitObjectWriter(
        object_root=tmp_path / "shadow" / "objects",
        blob_root=blobs,
        sha1dc_oracle=oracle,
        sha1dc_evidence=evidence,
        writer_version_digest="f" * 64,
    )
    monkeypatch.setattr(object_writer_module, "_MAX_CLOSURE_BYTES", 5)
    with pytest.raises(ObjectWriterRefused, match="aggregate"):
        writer.writeRevision(manifest=manifest, metadata=metadata)

    monkeypatch.setattr(object_writer_module, "_MAX_CLOSURE_BYTES", 1024)
    monkeypatch.setattr(object_writer_module, "_MAX_CLOSURE_OBJECTS", 1)
    with pytest.raises(ObjectWriterRefused, match="object-count"):
        writer.writeRevision(manifest=manifest, metadata=metadata)


def test_validated_closure_installs_create_only_into_attested_canonical_store(
    tmp_path: Path,
) -> None:
    evidence, oracle, blobs, manifest, metadata = _fixture(tmp_path)
    repo = tmp_path / "canonical"
    repo.mkdir()
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Kernel"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "kernel@example.invalid"], cwd=repo, check=True
    )
    (repo / "base.txt").write_bytes(b"base\n")
    subprocess.run(["git", "add", "base.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True)
    attestation = attestCanonicalRepository(repo)
    manifest = ObjectManifest(
        expected_revision=attestation.head_oid,
        entries=manifest.entries,
        attribute_rules=manifest.attribute_rules,
        policy=manifest.policy,
    )
    proof_calls: list[tuple[bytes, object]] = []

    def prove_existing(raw: bytes, record) -> str:
        proof_calls.append((raw, record))
        frame = zlib.decompress(raw)
        header, payload = frame.split(b"\0", 1)
        object_type, size_text = header.split(b" ", 1)
        assert object_type.decode("ascii") == record.object_type
        assert int(size_text) == len(payload) == record.size
        assert hashlib.sha256(payload).hexdigest() == record.payload_sha256
        assert hashlib.sha256(frame).hexdigest() == record.framed_object_sha256
        return hashlib.sha256(raw + record.oid.encode("ascii")).hexdigest()

    writer = GitObjectWriter(
        object_root=tmp_path / "shadow" / "objects",
        blob_root=blobs,
        sha1dc_oracle=oracle,
        sha1dc_evidence=evidence,
        writer_version_digest="f" * 64,
        forbidden_roots=(repo,),
        canonical_object_verifier=prove_existing,
    )
    receipt = writer.writeRevision(manifest=manifest, metadata=metadata)
    first = writer.installClosureIntoCanonical(
        receipt=receipt,
        attestation=attestation,
    )
    assert set(first.installed_oids) == {record.oid for record in receipt.objects}
    assert first.reused_oids == ()
    assert first.reuse_proof_receipts == ()
    original_decompress = object_writer_module._boundedDecompress
    decompress_calls = 0

    def counted_decompress(raw: bytes, *, max_output: int) -> bytes:
        nonlocal decompress_calls
        decompress_calls += 1
        return original_decompress(raw, max_output=max_output)

    object_writer_module._boundedDecompress = counted_decompress
    try:
        second = writer.installClosureIntoCanonical(
            receipt=receipt,
            attestation=attestation,
        )
    finally:
        object_writer_module._boundedDecompress = original_decompress
    assert second.installed_oids == ()
    assert set(second.reused_oids) == {record.oid for record in receipt.objects}
    assert {oid for oid, _ in second.reuse_proof_receipts} == set(second.reused_oids)
    assert len(proof_calls) == len(receipt.objects)
    assert decompress_calls == len(receipt.objects)

    victim = receipt.objects[0]
    external = writer.object_root / victim.oid[:2] / victim.oid[2:]
    canonical = repo / ".git" / "objects" / victim.oid[:2] / victim.oid[2:]
    canonical.write_bytes(zlib.compress(zlib.decompress(external.read_bytes()), level=1))
    before_proof = canonical.read_bytes()
    proof = writer.proveClosureInCanonical(
        receipt=receipt,
        attestation=attestation,
    )
    assert proof.installed_oids == ()
    assert set(proof.reused_oids) == {record.oid for record in receipt.objects}
    assert canonical.read_bytes() == before_proof
    shown = subprocess.run(
        ["git", "cat-file", "-p", receipt.commit_oid],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert shown.returncode == 0
    assert shown.stdout.startswith(f"tree {receipt.tree_oid}\n".encode())

    canonical.unlink()
    with pytest.raises(ObjectWriterRefused, match="missing"):
        writer.proveClosureInCanonical(
            receipt=receipt,
            attestation=attestation,
        )
    assert not canonical.exists()


def test_existing_canonical_loose_object_requires_contained_proof(tmp_path: Path) -> None:
    evidence, oracle, blobs, manifest, metadata = _fixture(tmp_path)
    repo = tmp_path / "canonical"
    repo.mkdir()
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Kernel"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "kernel@example.invalid"], cwd=repo, check=True
    )
    (repo / "base.txt").write_bytes(b"base\n")
    subprocess.run(["git", "add", "base.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True)
    attestation = attestCanonicalRepository(repo)
    manifest = ObjectManifest(
        expected_revision=attestation.head_oid,
        entries=manifest.entries,
        attribute_rules=manifest.attribute_rules,
        policy=manifest.policy,
    )
    writer = GitObjectWriter(
        object_root=tmp_path / "shadow" / "objects",
        blob_root=blobs,
        sha1dc_oracle=oracle,
        sha1dc_evidence=evidence,
        writer_version_digest="f" * 64,
        forbidden_roots=(repo,),
    )
    receipt = writer.writeRevision(manifest=manifest, metadata=metadata)
    writer.installClosureIntoCanonical(receipt=receipt, attestation=attestation)
    with pytest.raises(ObjectWriterRefused, match="contained proof"):
        writer.installClosureIntoCanonical(receipt=receipt, attestation=attestation)


def test_canonical_loose_object_collision_is_preserved_and_refused(tmp_path: Path) -> None:
    evidence, oracle, blobs, manifest, metadata = _fixture(tmp_path)
    repo = tmp_path / "canonical"
    repo.mkdir()
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Kernel"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "kernel@example.invalid"], cwd=repo, check=True
    )
    (repo / "base.txt").write_bytes(b"base\n")
    subprocess.run(["git", "add", "base.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True)
    attestation = attestCanonicalRepository(repo)
    manifest = ObjectManifest(
        expected_revision=attestation.head_oid,
        entries=manifest.entries,
        attribute_rules=manifest.attribute_rules,
        policy=manifest.policy,
    )
    writer = GitObjectWriter(
        object_root=tmp_path / "shadow" / "objects",
        blob_root=blobs,
        sha1dc_oracle=oracle,
        sha1dc_evidence=evidence,
        writer_version_digest="f" * 64,
        forbidden_roots=(repo,),
    )
    receipt = writer.writeRevision(manifest=manifest, metadata=metadata)
    victim = receipt.objects[0]
    target = repo / ".git" / "objects" / victim.oid[:2] / victim.oid[2:]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(zlib.compress(b"blob 1\0x"))
    before = target.read_bytes()
    with pytest.raises(ObjectWriterRefused, match="canonical loose object"):
        writer.installClosureIntoCanonical(receipt=receipt, attestation=attestation)
    assert target.read_bytes() == before


@pytest.mark.skipif(os.name != "nt", reason="Windows retained-handle boundary")
def test_canonical_object_install_refuses_a_rebound_object_store(
    tmp_path: Path,
) -> None:
    evidence, oracle, blobs, manifest, metadata = _fixture(tmp_path)
    repo = tmp_path / "canonical"
    repo.mkdir()
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Kernel"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "kernel@example.invalid"], cwd=repo, check=True
    )
    (repo / "base.txt").write_bytes(b"base\n")
    subprocess.run(["git", "add", "base.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True)
    attestation = attestCanonicalRepository(repo)
    manifest = ObjectManifest(
        expected_revision=attestation.head_oid,
        entries=manifest.entries,
        attribute_rules=manifest.attribute_rules,
        policy=manifest.policy,
    )
    writer = GitObjectWriter(
        object_root=tmp_path / "shadow" / "objects",
        blob_root=blobs,
        sha1dc_oracle=oracle,
        sha1dc_evidence=evidence,
        writer_version_digest="f" * 64,
        forbidden_roots=(repo,),
    )
    receipt = writer.writeRevision(manifest=manifest, metadata=metadata)
    objects = repo / ".git" / "objects"
    held = repo / ".git" / "objects-held"

    def rebind(stage: str) -> None:
        if stage != "after_object_root_open":
            return
        objects.rename(held)
        objects.mkdir()
        (objects / "goldstone.txt").write_bytes(b"replacement\n")

    with pytest.raises(ObjectWriterRefused, match="identity|drift"):
        writer.installClosureIntoCanonical(
            receipt=receipt,
            attestation=attestation,
            failpoint=rebind,
        )

    assert (objects / "goldstone.txt").read_bytes() == b"replacement\n"
    assert not any(
        (held / record.oid[:2] / record.oid[2:]).exists()
        for record in receipt.objects
    )


def test_canonical_object_install_refuses_a_fanout_volume_escape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence, oracle, blobs, manifest, metadata = _fixture(tmp_path)
    repo = tmp_path / "canonical"
    repo.mkdir()
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Kernel"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "kernel@example.invalid"],
        cwd=repo,
        check=True,
    )
    (repo / "base.txt").write_bytes(b"base\n")
    subprocess.run(["git", "add", "base.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True)
    attestation = attestCanonicalRepository(repo)
    manifest = ObjectManifest(
        expected_revision=attestation.head_oid,
        entries=manifest.entries,
        attribute_rules=manifest.attribute_rules,
        policy=manifest.policy,
    )
    writer = GitObjectWriter(
        object_root=tmp_path / "shadow" / "objects",
        blob_root=blobs,
        sha1dc_oracle=oracle,
        sha1dc_evidence=evidence,
        writer_version_digest="f" * 64,
        forbidden_roots=(repo,),
    )
    receipt = writer.writeRevision(manifest=manifest, metadata=metadata)
    handle_type = object_writer_module.NativeDirectoryHandle
    real_create = handle_type.createDirectory
    real_open = handle_type.openDirectory

    class OtherVolume:
        def __init__(self, inner) -> None:
            self.inner = inner

        @property
        def identity(self):
            return replace(
                self.inner.identity,
                volume_id=self.inner.identity.volume_id + 1,
            )

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.inner.close()

    def wrap_fanout(directory, name, *args, **kwargs):
        child = real_open(directory, name, *args, **kwargs)
        return OtherVolume(child) if re.fullmatch(r"[0-9a-f]{2}", name) else child

    def create_fanout(directory, name):
        child = real_create(directory, name)
        return OtherVolume(child) if re.fullmatch(r"[0-9a-f]{2}", name) else child

    monkeypatch.setattr(handle_type, "openDirectory", wrap_fanout)
    monkeypatch.setattr(handle_type, "createDirectory", create_fanout)

    with pytest.raises(ObjectWriterRefused, match="volume"):
        writer.installClosureIntoCanonical(receipt=receipt, attestation=attestation)


def test_verification_repository_is_private_shallow_and_no_checkout(
    tmp_path: Path,
) -> None:
    evidence, oracle, blobs, manifest, metadata = _fixture(tmp_path)
    writer = GitObjectWriter(
        object_root=tmp_path / "shadow" / "objects",
        blob_root=blobs,
        sha1dc_oracle=oracle,
        sha1dc_evidence=evidence,
        writer_version_digest="f" * 64,
        forbidden_roots=(tmp_path / "canonical",),
    )
    receipt = writer.writeRevision(manifest=manifest, metadata=metadata)
    checkout = tmp_path / "controller" / "verification" / "tx-001"

    lease = writer.createVerificationRepository(
        transaction_id="tx-001",
        checkout_root=checkout,
        manifest=manifest,
        receipt=receipt,
        forbidden_roots=(tmp_path / "canonical",),
    )

    assert isinstance(lease, VerificationRepositoryLease)
    assert lease.proposed_revision == receipt.commit_oid
    assert lease.shallow_root_revision == receipt.commit_oid
    assert list(path for path in checkout.iterdir() if path.name != ".git") == []
    assert not (checkout / ".git" / "objects" / "info" / "alternates").exists()
    assert not (checkout / ".git" / "commondir").exists()
    assert "remote" not in (checkout / ".git" / "config").read_text(encoding="ascii")
    for record in receipt.objects:
        object_path = checkout / ".git" / "objects" / record.oid[:2] / record.oid[2:]
        assert object_path.is_file()
        assert object_path.stat().st_nlink == 1
    shown = subprocess.run(
        [str(Path(evidence.executable_path)), "rev-parse", "HEAD"],
        cwd=checkout,
        env={
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_NO_LAZY_FETCH": "1",
            "SystemRoot": os.environ.get("SystemRoot", ""),
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    assert shown.returncode == 0, shown.stderr.decode(errors="replace")
    assert shown.stdout.strip().decode("ascii") == receipt.commit_oid
    replay = writer.createVerificationRepository(
        transaction_id="tx-001",
        checkout_root=checkout,
        manifest=manifest,
        receipt=receipt,
        forbidden_roots=(tmp_path / "canonical",),
    )
    assert replay == lease


def test_verification_repository_collision_is_preserved(tmp_path: Path) -> None:
    evidence, oracle, blobs, manifest, metadata = _fixture(tmp_path)
    writer = GitObjectWriter(
        object_root=tmp_path / "shadow" / "objects",
        blob_root=blobs,
        sha1dc_oracle=oracle,
        sha1dc_evidence=evidence,
        writer_version_digest="f" * 64,
    )
    receipt = writer.writeRevision(manifest=manifest, metadata=metadata)
    checkout = tmp_path / "verification" / "tx-001"
    writer.createVerificationRepository(
        transaction_id="tx-001",
        checkout_root=checkout,
        manifest=manifest,
        receipt=receipt,
    )
    config = checkout / ".git" / "config"
    config.write_bytes(b"goldstone")

    with pytest.raises(ObjectWriterRefused, match="collision|exact"):
        writer.createVerificationRepository(
            transaction_id="tx-001",
            checkout_root=checkout,
            manifest=manifest,
            receipt=receipt,
        )
    assert config.read_bytes() == b"goldstone"


def test_candidate_repository_is_built_without_clone_remote_or_host_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence, oracle, blobs, manifest, metadata = _fixture(tmp_path)
    writer = GitObjectWriter(
        object_root=tmp_path / "source" / "objects",
        blob_root=blobs,
        sha1dc_oracle=oracle,
        sha1dc_evidence=evidence,
        writer_version_digest="f" * 64,
        forbidden_roots=(tmp_path / "canonical",),
    )
    built = writer.writeRevision(manifest=manifest, metadata=metadata)
    base_manifest = ObjectManifest(
        expected_revision=built.commit_oid,
        entries=manifest.entries,
        attribute_rules=manifest.attribute_rules,
        policy=manifest.policy,
    )
    closure = SourceObjectClosure(
        repository_id="1" * 64,
        revision=built.commit_oid,
        tree_oid=built.tree_oid,
        manifest_digest=base_manifest.manifest_digest,
        object_closure_digest=built.object_closure_digest,
        source_snapshot_digest="2" * 64,
        parser_receipt_id="3" * 64,
        parser_image_digest="4" * 64,
        parser_runtime_digest="5" * 64,
        parser_security_profile_digest="6" * 64,
        payload_root=str(blobs.resolve()),
        objects=built.objects,
        intentional_shallow=True,
        parser_network_allowed=False,
    )
    checkout = tmp_path / "controller" / "candidate" / "tx-001"
    monkeypatch.setattr(
        object_writer_module,
        "readLooseObject",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("source clone construction must not decompress loose objects")
        ),
    )

    lease = writer.createCandidateRepository(
        transaction_id="tx-001",
        checkout_root=checkout,
        candidate_branch="refs/heads/9to5/candidates/tx-001",
        manifest=base_manifest,
        closure=closure,
        forbidden_roots=(tmp_path / "canonical",),
    )

    assert isinstance(lease, CandidateRepositoryLease)
    assert lease.base_revision == built.commit_oid
    assert (checkout / "README.md").read_bytes() == b"read\n"
    assert (checkout / "pkg" / "mod.py").read_bytes() == b"pass\n"
    assert not (checkout / ".git" / "commondir").exists()
    assert not (checkout / ".git" / "objects" / "info" / "alternates").exists()
    assert "remote" not in (checkout / ".git" / "config").read_text(encoding="ascii")
    replay = writer.createCandidateRepository(
        transaction_id="tx-001",
        checkout_root=checkout,
        candidate_branch="refs/heads/9to5/candidates/tx-001",
        manifest=base_manifest,
        closure=closure,
        forbidden_roots=(tmp_path / "canonical",),
    )
    assert replay == lease
    status = subprocess.run(
        [str(Path(evidence.executable_path)), "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=checkout,
        env={
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_NO_LAZY_FETCH": "1",
            "SystemRoot": os.environ.get("SystemRoot", ""),
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    assert status.returncode == 0, status.stderr.decode(errors="replace")
    assert status.stdout == b""
