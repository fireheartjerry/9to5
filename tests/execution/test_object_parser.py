"""Pinned, networkless object-parser projection and result validation tests."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import zlib
from dataclasses import replace
from pathlib import Path

import pytest

from platform_core.core.galaxy_evidence import canonical_digest, canonical_json_bytes
from platform_core.execution import object_parser as object_parser_mod
from platform_core.execution.object_parser import (
    CandidateSnapshot,
    CanonicalObjectSnapshot,
    LooseObjectProof,
    ObjectParser,
    ObjectParserImage,
    ObjectParserProcessResult,
    ObjectParserRefused,
    RawObjectSnapshotEntry,
    SnapshotEntry,
    buildObjectParserRequest,
    buildSourceObjectParserRequest,
    captureCanonicalObjectCatalog,
    captureCanonicalObjectSnapshot,
)
from platform_core.runtime.canonical_repo import attestCanonicalRepository
from platform_core.runtime.git_object_writer import ObjectRecord
from platform_core.runtime.object_manifest import (
    ManifestEntry,
    ManifestPolicy,
    ObjectManifest,
)

ENTRYPOINT = Path("containers/galaxy/object_parser_entrypoint.py").resolve()


def test_closed_content_root_refuses_retained_reparse_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "content"
    bucket = root / "aa"
    bucket.mkdir(parents=True)
    digest = "a" * 64
    (bucket / digest).write_bytes(b"payload")
    real_list = object_parser_mod.NativeDirectoryHandle.listEntries

    def report_reparse(directory):
        return tuple(
            replace(
                entry,
                identity=replace(
                    entry.identity,
                    is_reparse=True,
                    reparse_tag=0xA0000003,
                ),
            )
            if entry.name == "aa"
            else entry
            for entry in real_list(directory)
        )

    monkeypatch.setattr(
        object_parser_mod.NativeDirectoryHandle,
        "listEntries",
        report_reparse,
    )

    with pytest.raises(ObjectParserRefused, match="reparse|escape"):
        ObjectParser._validateClosedContentRoot(root, {f"aa/{digest}"})


def _reviewed_image_digest() -> str:
    lock = json.loads(
        Path("bootstrap/galaxy_launcher/activation_images.lock.json").read_text(
            encoding="utf-8"
        )
    )
    records = [record for record in lock["images"] if record["role"] == "object_parser"]
    assert len(records) == 1
    return records[0]["manifest_digest"]


IMAGE_DIGEST = _reviewed_image_digest()


def _git_executable() -> Path:
    discovered = shutil.which("git")
    assert discovered is not None
    candidate = Path(discovered).resolve()
    if candidate.parent.name.casefold() == "cmd":
        runtime = candidate.parent.parent / "mingw64" / "bin" / "git.exe"
        if runtime.is_file():
            candidate = runtime.resolve()
    return candidate


def _entrypoint_module():
    spec = importlib.util.spec_from_file_location("galaxy_object_parser_test", ENTRYPOINT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_verified_blob_open_preserves_the_original_fdopen_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _entrypoint_module()
    payload = tmp_path / "payload"
    payload.write_bytes(b"payload")
    identity = module._statIdentity(payload.stat())
    blob = module._VerifiedBlob(
        payload,
        digest=hashlib.sha256(b"payload").hexdigest(),
        size=7,
        identity=identity,
    )

    def closed_fdopen(descriptor: int, *_args, **_kwargs):
        os.close(descriptor)
        raise RuntimeError("fdopen failed after taking ownership")

    monkeypatch.setattr(module.os, "fdopen", closed_fdopen)

    with pytest.raises(RuntimeError, match="taking ownership"):
        blob.open()


def _entrypoint_sha1dc(module, root: Path):
    sterile_root = root / "sha1dc-empty"
    sterile_root.mkdir(parents=True, exist_ok=True)
    return module._Sha1dcOracle(
        _git_executable(),
        sterile_root=sterile_root,
    )


def _reviewed_image_has_sha1dc() -> bool:
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network=none",
            "--entrypoint",
            "/opt/galaxy/galaxy-sha1dc",
            f"galaxy-r3/object-parser@sha256:{IMAGE_DIGEST}",
            "--self-test",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    return (
        result.returncode == 0
        and result.stderr == b""
        and result.stdout
        == b"GALAXY_SHA1DC_SELF_TEST/v1 collision-detected normal-sha1-exact\n"
    )


def _candidate_container_name(controller_root: Path, transaction_id: str) -> str:
    return object_parser_mod._scopedContainerName(
        controller_root,
        prefix="galaxy-object-parser",
        operation="candidate-snapshot",
        logical_identity=transaction_id,
    )


def _source_container_name(controller_root: Path, transaction_id: str) -> str:
    return object_parser_mod._scopedContainerName(
        controller_root,
        prefix="galaxy-source-parser",
        operation="source-object-closure",
        logical_identity=transaction_id,
    )


def _put_blob(root: Path, payload: bytes) -> tuple[str, Path]:
    digest = hashlib.sha256(payload).hexdigest()
    path = root / digest[:2] / digest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return digest, path


def _fixture(tmp_path: Path) -> tuple[ObjectManifest, CandidateSnapshot]:
    policy = ManifestPolicy(
        reserved_roots=("state/tasks",),
        max_files=10,
        max_total_bytes=1024,
        max_file_bytes=512,
        max_depth=8,
        max_path_bytes=240,
    )
    old = b"old\n"
    old_raw = hashlib.sha256(old).hexdigest()
    old_frame = b"blob 4\0" + old
    old_oid = hashlib.sha1(old_frame, usedforsecurity=False).hexdigest()
    expected = ObjectManifest(
        expected_revision="a" * 40,
        entries=(
            ManifestEntry(
                path="a.txt",
                mode=0o100644,
                blob_oid=old_oid,
                blob_sha256=old_raw,
                framed_object_sha256=hashlib.sha256(old_frame).hexdigest(),
                size=len(old),
            ),
        ),
        attribute_rules=(),
        policy=policy,
    )
    blobs = tmp_path / "snapshot-blobs"
    new_raw, _ = _put_blob(blobs, b"new\n")
    extra_raw, _ = _put_blob(blobs, b"extra\n")
    snapshot = CandidateSnapshot(
        transaction_id="tx-parser-001",
        blob_root=blobs,
        entries=(
            SnapshotEntry(path="a.txt", mode=0o100644, blob_sha256=new_raw, size=4),
            SnapshotEntry(path="b.txt", mode=0o100644, blob_sha256=extra_raw, size=6),
        ),
        policy=policy,
    )
    return expected, snapshot


def _run_entrypoint(request_path: Path, blob_root: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(ENTRYPOINT),
            "candidate-snapshot",
            "--sha1dc-executable",
            str(_git_executable()),
            "--request",
            str(request_path),
            "--blob-root",
            str(blob_root),
        ],
        cwd=request_path.parent,
        env={},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )


def _run_hash_batch(
    request_path: Path, payload_root: Path
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(ENTRYPOINT),
            "hash-object-batch",
            "--sha1dc-executable",
            str(_git_executable()),
            "--request",
            str(request_path),
            "--payload-root",
            str(payload_root),
        ],
        cwd=request_path.parent,
        env={},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )


def test_hash_object_batch_is_content_addressed_networkless_and_ordered(
    tmp_path: Path,
) -> None:
    payload_root = tmp_path / "payloads"
    first = b"first\n"
    second = b""
    first_digest, _ = _put_blob(payload_root, first)
    second_digest, _ = _put_blob(payload_root, second)
    request = {
        "schema": "galaxy.object-hash-batch-request/v1",
        "operation": "hash-object-batch",
        "batch_id": "hashbatch_" + "a" * 64,
        "records": [
            {
                "sequence": 0,
                "object_type": "blob",
                "payload_sha256": first_digest,
                "size": len(first),
            },
            {
                "sequence": 1,
                "object_type": "tree",
                "payload_sha256": second_digest,
                "size": len(second),
            },
        ],
    }
    request_path = tmp_path / "request.json"
    request_path.write_bytes(canonical_json_bytes(request))

    completed = _run_hash_batch(request_path, payload_root)

    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    assert completed.stderr == b""
    result = json.loads(completed.stdout)
    assert result["schema"] == "galaxy.object-hash-batch-result/v1"
    assert result["batch_id"] == request["batch_id"]
    assert result["request_sha256"] == hashlib.sha256(
        request_path.read_bytes()
    ).hexdigest()
    assert result["network_allowed"] is False
    assert [record["sequence"] for record in result["records"]] == [0, 1]
    for record, payload in zip(result["records"], (first, second), strict=True):
        frame = (
            f"{record['object_type']} {len(payload)}".encode("ascii")
            + b"\0"
            + payload
        )
        assert record["oid"] == hashlib.sha1(
            frame, usedforsecurity=False
        ).hexdigest()
        assert record["frame_sha256"] == hashlib.sha256(frame).hexdigest()


def test_hash_object_batch_refuses_payload_substitution(tmp_path: Path) -> None:
    payload_root = tmp_path / "payloads"
    payload = b"exact\n"
    digest, path = _put_blob(payload_root, payload)
    request = {
        "schema": "galaxy.object-hash-batch-request/v1",
        "operation": "hash-object-batch",
        "batch_id": "hashbatch_" + "b" * 64,
        "records": [
            {
                "sequence": 0,
                "object_type": "commit",
                "payload_sha256": digest,
                "size": len(payload),
            }
        ],
    }
    request_path = tmp_path / "request.json"
    request_path.write_bytes(canonical_json_bytes(request))
    path.write_bytes(b"drift\n")

    completed = _run_hash_batch(request_path, payload_root)

    assert completed.returncode == 78
    assert b"payload" in completed.stderr.lower()


def test_container_name_is_stable_per_controller_and_unique_across_controllers(
    tmp_path: Path,
) -> None:
    expected, snapshot = _fixture(tmp_path)

    def parser(root: Path) -> ObjectParser:
        return ObjectParser(
            controller_root=root,
            image=ObjectParserImage(
                repository="galaxy-r3/object-parser",
                manifest_digest=IMAGE_DIGEST,
                role="object_parser",
            ),
            runtime_entrypoint=ENTRYPOINT,
            process_runner=lambda _invocation: ObjectParserProcessResult(
                returncode=1,
                stdout=b"",
                stderr=b"unused",
            ),
        )

    first = parser(tmp_path / "controller-a")
    replay = parser(tmp_path / "controller-a")
    other = parser(tmp_path / "controller-b")

    first_name = first._prepareInvocation(
        snapshot=snapshot,
        expected=expected,
    ).container_name
    replay_name = replay._prepareInvocation(
        snapshot=snapshot,
        expected=expected,
    ).container_name
    other_name = other._prepareInvocation(
        snapshot=snapshot,
        expected=expected,
    ).container_name

    assert first_name == replay_name
    assert first_name != other_name


def _run_source_entrypoint(
    request_path: Path,
    raw_root: Path,
    output_root: Path,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(ENTRYPOINT),
            "source-object-closure",
            "--sha1dc-executable",
            str(_git_executable()),
            "--request",
            str(request_path),
            "--raw-root",
            str(raw_root),
            "--output-root",
            str(output_root),
        ],
        cwd=request_path.parent,
        env={},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )


def _invocation_mount_source(invocation, target: str) -> Path:
    for index, value in enumerate(invocation.argv[:-1]):
        if value != "--mount":
            continue
        fields = dict(
            field.split("=", 1)
            for field in invocation.argv[index + 1].split(",")
            if "=" in field
        )
        if fields.get("target") == target:
            return Path(fields["source"])
    raise AssertionError(f"invocation has no {target} mount")


def _run_source_protocol_invocation(invocation) -> ObjectParserProcessResult:
    command = invocation.operation
    arguments = [
        sys.executable,
        "-I",
        "-S",
        str(ENTRYPOINT),
        command,
        "--sha1dc-executable",
        str(_git_executable()),
        "--request",
        str(invocation.request_path),
    ]
    if command == "source-object-locate":
        arguments.extend(
            ["--catalog-root", str(_invocation_mount_source(invocation, "/galaxy-catalog"))]
        )
    else:
        assert invocation.output_root is not None
        arguments.extend(
            [
                "--raw-root",
                str(_invocation_mount_source(invocation, "/galaxy-raw")),
                "--output-root",
                str(invocation.output_root),
            ]
        )
    result = subprocess.run(
        arguments,
        cwd=invocation.request_path.parent,
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


def _capture_minimal_source_snapshot(
    *,
    attestation,
    transaction_id: str,
    snapshot_root: Path,
    policy: ManifestPolicy,
    tmp_path: Path,
    max_raw_files: int = 64,
    max_raw_bytes: int = 32 * 1024 * 1024,
    max_raw_file_bytes: int = 32 * 1024 * 1024,
) -> CanonicalObjectSnapshot:
    catalog = captureCanonicalObjectCatalog(
        attestation=attestation,
        transaction_id=transaction_id,
        snapshot_root=snapshot_root,
        policy=policy,
        max_raw_files=max_raw_files,
        max_catalog_bytes=min(max_raw_bytes, 8 * 1024 * 1024),
        max_raw_file_bytes=max_raw_file_bytes,
    )
    module = _entrypoint_module()
    sha1dc = _entrypoint_sha1dc(module, tmp_path)
    selected: set[str] = set()
    missing = [catalog.revision]
    snapshot = None
    output_root = snapshot_root / transaction_id / "test-frontier-output"
    output_root.mkdir(parents=True)
    for _ in range(128):
        located = module.locateSourceObjects(
            catalog.locatorRequest(missing),
            catalog.catalog_root,
        )
        for source in located["sources"]:
            selected.update(source["paths"])
        snapshot = captureCanonicalObjectSnapshot(
            catalog=catalog,
            selected_paths=sorted(selected),
            snapshot_root=snapshot_root,
            previous_snapshot=snapshot,
            max_selected_bytes=max_raw_bytes - catalog.catalog_bytes,
        )
        result = module.parseSourceObjectFrontier(
            buildSourceObjectParserRequest(snapshot),
            snapshot.raw_root,
            output_root,
            sha1dc=sha1dc,
        )
        if result["schema"] == "galaxy.source-object-parser-result/v1":
            return snapshot
        missing = result["missing_oids"]
    raise AssertionError("minimal source fixture exceeded its frontier bound")


def _run_loose_proof_entrypoint(
    request_path: Path,
    raw_object: Path,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(ENTRYPOINT),
            "loose-object-proof",
            "--sha1dc-executable",
            str(_git_executable()),
            "--request",
            str(request_path),
            "--raw-object",
            str(raw_object),
        ],
        cwd=request_path.parent,
        env={},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )


def test_loose_object_proof_is_strongly_bound_and_contained(tmp_path: Path) -> None:
    payload = b"existing canonical blob\n"
    frame = b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload
    oid = hashlib.sha1(frame, usedforsecurity=False).hexdigest()
    raw = zlib.compress(frame, level=6)
    record = ObjectRecord(
        object_type="blob",
        oid=oid,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        framed_object_sha256=hashlib.sha256(frame).hexdigest(),
        size=len(payload),
    )
    raw_path = tmp_path / "raw-object"
    raw_path.write_bytes(raw)
    request = {
        "schema": "galaxy.loose-object-proof-request/v1",
        "transaction_id": "tx-loose-proof-001",
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "expected": record.toDict(),
    }
    request_path = tmp_path / "request.json"
    request_path.write_bytes(canonical_json_bytes(request))

    result = _run_loose_proof_entrypoint(request_path, raw_path)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    output = json.loads(result.stdout)
    assert output == {
        "framed_object_sha256": record.framed_object_sha256,
        "network_allowed": False,
        "object_type": "blob",
        "oid": oid,
        "parser_version_digest": hashlib.sha256(ENTRYPOINT.read_bytes()).hexdigest(),
        "payload_sha256": record.payload_sha256,
        "raw_sha256": request["raw_sha256"],
        "schema": "galaxy.loose-object-proof-result/v1",
        "size": len(payload),
        "transaction_id": "tx-loose-proof-001",
    }

    request["expected"] = {**record.toDict(), "payload_sha256": "f" * 64}
    request_path.write_bytes(canonical_json_bytes(request))
    refused = _run_loose_proof_entrypoint(request_path, raw_path)
    assert refused.returncode == 78
    assert b"object-parser-refused" in refused.stderr


def test_host_loose_object_proof_is_offline_and_exactly_bound(tmp_path: Path) -> None:
    payload = b"existing canonical blob\n"
    frame = b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload
    raw = zlib.compress(frame, level=6)
    record = ObjectRecord(
        object_type="blob",
        oid=hashlib.sha1(frame, usedforsecurity=False).hexdigest(),
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        framed_object_sha256=hashlib.sha256(frame).hexdigest(),
        size=len(payload),
    )
    observed: dict[str, object] = {}

    def run_locally(invocation) -> ObjectParserProcessResult:
        observed["argv"] = invocation.argv
        observed["invocation"] = invocation
        result = _run_loose_proof_entrypoint(
            invocation.request_path,
            invocation.request_path.parent / "raw-object",
        )
        return ObjectParserProcessResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    parser = ObjectParser(
        controller_root=tmp_path / "controller",
        image=ObjectParserImage(
            repository="galaxy-r3/object-parser",
            manifest_digest=IMAGE_DIGEST,
            role="object_parser",
        ),
        runtime_entrypoint=ENTRYPOINT,
        process_runner=run_locally,
    )
    proof = parser.proveLooseObject(raw=raw, expected=record)
    assert isinstance(proof, LooseObjectProof)
    assert proof.object_record == record
    assert proof.raw_sha256 == hashlib.sha256(raw).hexdigest()
    assert proof.parser_image_digest == IMAGE_DIGEST
    expected_profile = canonical_digest(
        {
            "capabilities": "drop-all",
            "cpus": "0.5",
            "memory": 134217728,
            "network": "none",
            "no_new_privileges": True,
            "pids_limit": 32,
            "rootfs": "readonly",
            "user": "65532:65532",
        }
    )
    assert proof.parser_security_profile_digest == expected_profile
    assert proof.receipt_id == canonical_digest(
        {
            "schema": "galaxy.loose-object-proof-receipt/v1",
            "transaction_id": proof.transaction_id,
            "object_record": record.toDict(),
            "raw_sha256": proof.raw_sha256,
            "result_sha256": hashlib.sha256(proof.raw_result).hexdigest(),
            "parser_image_digest": IMAGE_DIGEST,
            "parser_runtime_digest": proof.parser_version_digest,
            "parser_security_profile_digest": expected_profile,
            "network_allowed": False,
        }
    )
    command = tuple(observed["argv"])
    for required in (
        "create",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--pull=never",
        f"galaxy-r3/object-parser@sha256:{IMAGE_DIGEST}",
        "loose-object-proof",
    ):
        assert required in command
    assert "run" not in command
    assert "--env" not in command
    assert "--rm" not in command
    invocation = observed["invocation"]
    assert len(invocation.invocation_id) == 64
    record = json.loads(invocation.record_path.read_bytes())
    assert record["invocation_id"] == invocation.invocation_id
    assert record["request_sha256"] == hashlib.sha256(
        invocation.request_path.read_bytes()
    ).hexdigest()
    assert f"galaxy.invocation_id={invocation.invocation_id}" in command
    assert command.count("--mount") == 3


def test_durable_terminal_parser_result_replays_without_docker(tmp_path: Path) -> None:
    expected, snapshot = _fixture(tmp_path)
    observed: dict[str, object] = {}

    def run_locally(invocation) -> ObjectParserProcessResult:
        observed["invocation"] = invocation
        result = _run_entrypoint(invocation.request_path, snapshot.blob_root)
        return ObjectParserProcessResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    parser = ObjectParser(
        controller_root=tmp_path / "controller",
        image=ObjectParserImage(
            repository="galaxy-r3/object-parser",
            manifest_digest=IMAGE_DIGEST,
            role="object_parser",
        ),
        runtime_entrypoint=ENTRYPOINT,
        process_runner=run_locally,
    )
    parsed = parser.parseCandidateSnapshot(snapshot=snapshot, expected=expected)
    invocation = observed["invocation"]
    result = ObjectParserProcessResult(
        returncode=0,
        stdout=parsed.raw_result,
        stderr=b"",
    )
    parser._persistDockerResult(
        invocation,
        result,
        disposition="completed",
        container_id="a" * 64,
    )
    parser._persistContainerCleanup(invocation, container_id="a" * 64)
    parser._process_runner = None
    parser._verifyImage = lambda: (_ for _ in ()).throw(
        AssertionError("durable result replay must not contact Docker")
    )

    assert parser._runDocker(invocation) == result

    terminal = json.loads(invocation.result_path.read_bytes())
    terminal["stdout_sha256"] = "0" * 64
    invocation.result_path.write_bytes(canonical_json_bytes(terminal))
    with pytest.raises(ObjectParserRefused, match="digest differs"):
        parser._runDocker(invocation)


def test_host_loose_object_proof_rejects_tampered_result(tmp_path: Path) -> None:
    payload = b"existing canonical blob\n"
    frame = b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload
    raw = zlib.compress(frame, level=6)
    record = ObjectRecord(
        object_type="blob",
        oid=hashlib.sha1(frame, usedforsecurity=False).hexdigest(),
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        framed_object_sha256=hashlib.sha256(frame).hexdigest(),
        size=len(payload),
    )

    def tamper(invocation) -> ObjectParserProcessResult:
        result = _run_loose_proof_entrypoint(
            invocation.request_path,
            invocation.request_path.parent / "raw-object",
        )
        value = json.loads(result.stdout)
        value["raw_sha256"] = "f" * 64
        return ObjectParserProcessResult(
            returncode=0,
            stdout=canonical_json_bytes(value) + b"\n",
            stderr=b"",
        )

    parser = ObjectParser(
        controller_root=tmp_path / "controller",
        image=ObjectParserImage(
            repository="galaxy-r3/object-parser",
            manifest_digest=IMAGE_DIGEST,
            role="object_parser",
        ),
        runtime_entrypoint=ENTRYPOINT,
        process_runner=tamper,
    )
    with pytest.raises(ObjectParserRefused, match="binding"):
        parser.proveLooseObject(raw=raw, expected=record)


def test_entrypoint_emits_canonical_complete_proposed_manifest(tmp_path: Path) -> None:
    expected, snapshot = _fixture(tmp_path)
    request = buildObjectParserRequest(snapshot=snapshot, expected=expected)
    request_path = tmp_path / "request.json"
    request_path.write_bytes(canonical_json_bytes(request))
    result = _run_entrypoint(request_path, snapshot.blob_root)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stdout.endswith(b"\n")
    output = json.loads(result.stdout)
    assert canonical_json_bytes(output) + b"\n" == result.stdout
    assert output["transaction_id"] == snapshot.transaction_id
    assert output["snapshot_digest"] == snapshot.snapshot_digest
    assert [entry["path"] for entry in output["proposed_manifest"]["entries"]] == [
        "a.txt",
        "b.txt",
    ]
    assert len(output["diff_digest"]) == 64
    assert len(output["parser_version_digest"]) == 64


def test_candidate_object_ids_are_derived_only_by_sha1dc_oracle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entrypoint = _entrypoint_module()
    expected, snapshot = _fixture(tmp_path)
    request = buildObjectParserRequest(snapshot=snapshot, expected=expected)
    expected_oids = {
        b"new\n": "1" * 40,
        b"extra\n": "2" * 40,
    }
    calls: list[tuple[str, bytes]] = []

    class RecordingSha1dc:
        def hashObject(self, object_type: str, payload: bytes) -> str:
            calls.append((object_type, payload))
            return expected_oids[payload]

    def refuse_ordinary_sha1(*_args, **_kwargs):
        raise AssertionError("ordinary SHA-1 must not derive a Git object identity")

    monkeypatch.setattr(entrypoint.hashlib, "sha1", refuse_ordinary_sha1)

    result = entrypoint.parseCandidateSnapshot(
        request,
        snapshot.blob_root,
        sha1dc=RecordingSha1dc(),
    )

    entries = result["proposed_manifest"]["entries"]
    assert [entry["blob_oid"] for entry in entries] == ["1" * 40, "2" * 40]
    assert calls == [("blob", b"new\n"), ("blob", b"extra\n")]


def test_entrypoint_refuses_unsafe_or_omitted_snapshot_content(tmp_path: Path) -> None:
    expected, snapshot = _fixture(tmp_path)
    request = buildObjectParserRequest(snapshot=snapshot, expected=expected)
    request["snapshot"]["entries"][0]["path"] = "../goldstone"
    request_path = tmp_path / "request.json"
    request_path.write_bytes(canonical_json_bytes(request))
    result = _run_entrypoint(request_path, snapshot.blob_root)
    assert result.returncode == 78
    assert b"refused" in result.stderr
    assert result.stdout == b""

    safe_request = buildObjectParserRequest(snapshot=snapshot, expected=expected)
    request_path.write_bytes(canonical_json_bytes(safe_request))
    first_blob = snapshot.entries[0]
    (snapshot.blob_root / first_blob.blob_sha256[:2] / first_blob.blob_sha256).unlink()
    missing = _run_entrypoint(request_path, snapshot.blob_root)
    assert missing.returncode == 78
    assert b"blob" in missing.stderr


@pytest.mark.parametrize(
    "path",
    (
        "bad<name>.txt",
        "COM1 .txt",
        "LONGNA~10.TXT",
        "cafe\u0301.txt",
    ),
)
def test_entrypoint_path_contract_matches_portable_host_policy(path: str) -> None:
    module = _entrypoint_module()
    with pytest.raises(module.ObjectParserRefused):
        module._safePath(path)


def test_candidate_external_driver_attributes_never_execute_on_host(
    tmp_path: Path,
) -> None:
    expected, snapshot = _fixture(tmp_path)
    poisoned = b"*.txt filter=host-command\n"
    digest, _ = _put_blob(snapshot.blob_root, poisoned)
    snapshot = CandidateSnapshot(
        transaction_id="tx-attribute-poison",
        blob_root=snapshot.blob_root,
        entries=(
            *snapshot.entries,
            SnapshotEntry(
                path=".gitattributes",
                mode=0o100644,
                blob_sha256=digest,
                size=len(poisoned),
            ),
        ),
        policy=snapshot.policy,
    )
    goldstone = tmp_path / "host-command-ran.txt"
    candidate_git = tmp_path / "candidate" / ".git"
    candidate_git.mkdir(parents=True)
    (candidate_git / "config").write_text(
        "[filter \"host-command\"]\n"
        f"\tclean = powershell -NoProfile -Command Set-Content '{goldstone}' owned\n",
        encoding="utf-8",
    )
    request_path = tmp_path / "request.json"
    request_path.write_bytes(
        canonical_json_bytes(
            buildObjectParserRequest(snapshot=snapshot, expected=expected)
        )
    )

    result = _run_entrypoint(request_path, snapshot.blob_root)

    assert result.returncode == 78
    assert b"external driver" in result.stderr
    assert not goldstone.exists()


def test_safe_text_attribute_refuses_noncanonical_crlf_blob(tmp_path: Path) -> None:
    expected, snapshot = _fixture(tmp_path)
    crlf = b"new\r\n"
    crlf_digest, _ = _put_blob(snapshot.blob_root, crlf)
    attributes = b"*.txt text eol=lf\n"
    attributes_digest, _ = _put_blob(snapshot.blob_root, attributes)
    entries = tuple(
        SnapshotEntry(
            path=entry.path,
            mode=entry.mode,
            blob_sha256=crlf_digest,
            size=len(crlf),
        )
        if entry.path == "a.txt"
        else entry
        for entry in snapshot.entries
    )
    snapshot = CandidateSnapshot(
        transaction_id="tx-attribute-crlf",
        blob_root=snapshot.blob_root,
        entries=(
            *entries,
            SnapshotEntry(
                path=".gitattributes",
                mode=0o100644,
                blob_sha256=attributes_digest,
                size=len(attributes),
            ),
        ),
        policy=snapshot.policy,
    )
    request_path = tmp_path / "request.json"
    request_path.write_bytes(
        canonical_json_bytes(
            buildObjectParserRequest(snapshot=snapshot, expected=expected)
        )
    )

    result = _run_entrypoint(request_path, snapshot.blob_root)

    assert result.returncode == 78
    assert b"canonical LF" in result.stderr


def test_safe_text_attribute_is_derived_from_candidate_bytes(tmp_path: Path) -> None:
    expected, snapshot = _fixture(tmp_path)
    attributes = b"*.txt text eol=lf\n"
    digest, _ = _put_blob(snapshot.blob_root, attributes)
    snapshot = CandidateSnapshot(
        transaction_id="tx-attribute-safe",
        blob_root=snapshot.blob_root,
        entries=(
            *snapshot.entries,
            SnapshotEntry(
                path=".gitattributes",
                mode=0o100644,
                blob_sha256=digest,
                size=len(attributes),
            ),
        ),
        policy=snapshot.policy,
    )

    def run_locally(invocation) -> ObjectParserProcessResult:
        result = _run_entrypoint(invocation.request_path, snapshot.blob_root)
        return ObjectParserProcessResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    parser = ObjectParser(
        controller_root=tmp_path / "controller",
        image=ObjectParserImage(
            repository="galaxy-r3/object-parser",
            manifest_digest=IMAGE_DIGEST,
            role="object_parser",
        ),
        runtime_entrypoint=ENTRYPOINT,
        process_runner=run_locally,
    )

    parsed = parser.parseCandidateSnapshot(snapshot=snapshot, expected=expected)

    assert [rule.toDict() for rule in parsed.manifest.attribute_rules] == [
        {"pattern": "*.txt", "attributes": ["text", "eol=lf"]}
    ]
    assert ".gitattributes" in {entry.path for entry in parsed.manifest.entries}


def test_host_never_interprets_candidate_attribute_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected, snapshot = _fixture(tmp_path)
    attributes = b"*.txt text eol=lf\n"
    digest, _ = _put_blob(snapshot.blob_root, attributes)
    snapshot = CandidateSnapshot(
        transaction_id="tx-host-attribute-inert",
        blob_root=snapshot.blob_root,
        entries=(
            *snapshot.entries,
            SnapshotEntry(
                path=".gitattributes",
                mode=0o100644,
                blob_sha256=digest,
                size=len(attributes),
            ),
        ),
        policy=snapshot.policy,
    )

    def run_locally(invocation) -> ObjectParserProcessResult:
        result = _run_entrypoint(invocation.request_path, snapshot.blob_root)
        return ObjectParserProcessResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    def forbidden_host_interpretation(_snapshot):
        raise AssertionError("candidate attributes are inert outside the parser")

    monkeypatch.setattr(
        object_parser_mod,
        "_candidateAttributeRules",
        forbidden_host_interpretation,
        raising=False,
    )
    parser = ObjectParser(
        controller_root=tmp_path / "controller",
        image=ObjectParserImage(
            repository="galaxy-r3/object-parser",
            manifest_digest=IMAGE_DIGEST,
            role="object_parser",
        ),
        runtime_entrypoint=ENTRYPOINT,
        process_runner=run_locally,
    )

    parsed = parser.parseCandidateSnapshot(snapshot=snapshot, expected=expected)

    assert [rule.toDict() for rule in parsed.manifest.attribute_rules] == [
        {"pattern": "*.txt", "attributes": ["text", "eol=lf"]}
    ]


def test_host_boundary_hardens_docker_and_revalidates_output(tmp_path: Path) -> None:
    expected, snapshot = _fixture(tmp_path)
    observed: dict[str, object] = {}

    def run_locally(invocation) -> ObjectParserProcessResult:
        observed["argv"] = invocation.argv
        result = _run_entrypoint(invocation.request_path, snapshot.blob_root)
        return ObjectParserProcessResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    parser = ObjectParser(
        controller_root=tmp_path / "controller",
        image=ObjectParserImage(
            repository="galaxy-r3/object-parser",
            manifest_digest=IMAGE_DIGEST,
            role="object_parser",
        ),
        runtime_entrypoint=ENTRYPOINT,
        process_runner=run_locally,
    )
    parsed = parser.parseCandidateSnapshot(snapshot=snapshot, expected=expected)
    assert parsed.manifest.expected_revision == expected.expected_revision
    assert [entry.path for entry in parsed.manifest.entries] == ["a.txt", "b.txt"]
    assert parsed.receipt_id == hashlib.sha256(parsed.raw_result).hexdigest()
    command = tuple(observed["argv"])
    for required in (
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--pull=never",
        f"galaxy-r3/object-parser@sha256:{IMAGE_DIGEST}",
    ):
        assert required in command
    assert str(snapshot.blob_root) in " ".join(command)
    assert "--env" not in command


def test_host_boundary_rejects_tampered_parser_result(tmp_path: Path) -> None:
    expected, snapshot = _fixture(tmp_path)

    def tamper(invocation) -> ObjectParserProcessResult:
        result = _run_entrypoint(invocation.request_path, snapshot.blob_root)
        value = json.loads(result.stdout)
        value["snapshot_digest"] = "f" * 64
        return ObjectParserProcessResult(
            returncode=0,
            stdout=canonical_json_bytes(value) + b"\n",
            stderr=b"",
        )

    parser = ObjectParser(
        controller_root=tmp_path / "controller",
        image=ObjectParserImage(
            repository="galaxy-r3/object-parser",
            manifest_digest=IMAGE_DIGEST,
            role="object_parser",
        ),
        runtime_entrypoint=ENTRYPOINT,
        process_runner=tamper,
    )
    with pytest.raises(ObjectParserRefused, match="binding"):
        parser.parseCandidateSnapshot(snapshot=snapshot, expected=expected)


@pytest.mark.parametrize("packed", [False, True])
def test_source_object_closure_is_parsed_only_in_contained_boundary(
    tmp_path: Path,
    packed: bool,
) -> None:
    repo = tmp_path / "canonical"
    repo.mkdir()
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Kernel"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "kernel@example.invalid"],
        cwd=repo,
        check=True,
    )
    (repo / "README.md").write_bytes(b"read\n")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "mod.py").write_bytes(b"pass\n")
    (repo / "foo.bar").write_bytes(b"file-before-tree\n")
    (repo / "foo").mkdir()
    (repo / "foo" / "inside.txt").write_bytes(b"tree\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True)
    if packed:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        ).stdout.strip()
        subprocess.run(
            ["git", "-c", "pack.writeReverseIndex=true", "repack", "-ad"],
            cwd=repo,
            check=True,
        )
        subprocess.run(["git", "prune-packed"], cwd=repo, check=True)
        subprocess.run(["git", "multi-pack-index", "write"], cwd=repo, check=True)
        subprocess.run(
            ["git", "commit-graph", "write", "--reachable", "--split"],
            cwd=repo,
            check=True,
        )
        subprocess.run(["git", "update-server-info"], cwd=repo, check=True)
        loose_ref = repo / ".git" / "refs" / "heads" / "main"
        loose_ref.parent.mkdir(parents=True, exist_ok=True)
        loose_ref.write_text(f"{head}\n", encoding="ascii")

    policy = ManifestPolicy(
        reserved_roots=("state/tasks",),
        max_files=10,
        max_total_bytes=1024,
        max_file_bytes=512,
        max_depth=8,
        max_path_bytes=240,
    )
    attestation = attestCanonicalRepository(repo)
    snapshot = _capture_minimal_source_snapshot(
        attestation=attestation,
        transaction_id=f"tx-source-{'pack' if packed else 'loose'}",
        snapshot_root=tmp_path / "controller" / "source-snapshots",
        policy=policy,
        tmp_path=tmp_path,
        max_raw_files=64,
        max_raw_bytes=1024 * 1024,
        max_raw_file_bytes=1024 * 1024,
    )
    assert isinstance(snapshot, CanonicalObjectSnapshot)
    assert snapshot.revision == attestation.head_oid
    assert snapshot.raw_root.is_relative_to(tmp_path / "controller")
    assert all(
        entry.path.startswith(("loose/", "pack/", "pack-header/", "pack-range/"))
        for entry in snapshot.entries
    )
    if packed:
        assert not any(entry.path.endswith(".pack") for entry in snapshot.entries)
        assert any(entry.path.endswith(".idx") for entry in snapshot.entries)
        assert any(entry.path.startswith("pack-header/") for entry in snapshot.entries)
        assert any(entry.path.startswith("pack-range/") for entry in snapshot.entries)

    observed: dict[str, object] = {}

    def run_locally(invocation) -> ObjectParserProcessResult:
        observed["invocation"] = invocation
        assert invocation.output_root is not None
        result = _run_source_entrypoint(
            invocation.request_path,
            snapshot.raw_root,
            invocation.output_root,
        )
        return ObjectParserProcessResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    parser = ObjectParser(
        controller_root=tmp_path / "controller",
        image=ObjectParserImage(
            repository="galaxy-r3/object-parser",
            manifest_digest=IMAGE_DIGEST,
            role="object_parser",
        ),
        runtime_entrypoint=ENTRYPOINT,
        process_runner=run_locally,
    )
    parsed = parser.parseSourceObjectClosure(snapshot=snapshot)

    invocation = observed["invocation"]
    output_mount = next(
        invocation.argv[index + 1]
        for index, value in enumerate(invocation.argv[:-1])
        if value == "--mount" and "target=/galaxy-output" in invocation.argv[index + 1]
    )
    assert "readonly" not in output_mount
    if os.name != "nt":
        assert (invocation.output_root.stat().st_mode & 0o777) == 0o733

    assert parsed.manifest.expected_revision == attestation.head_oid
    assert [(entry.path, entry.blob_sha256) for entry in parsed.manifest.entries] == [
        ("README.md", hashlib.sha256(b"read\n").hexdigest()),
        ("foo.bar", hashlib.sha256(b"file-before-tree\n").hexdigest()),
        ("foo/inside.txt", hashlib.sha256(b"tree\n").hexdigest()),
        ("pkg/mod.py", hashlib.sha256(b"pass\n").hexdigest()),
    ]
    assert parsed.closure.revision == attestation.head_oid
    assert parsed.closure.tree_oid == parsed.tree_oid
    assert parsed.closure.parser_network_allowed is False
    assert parsed.closure.payload_root == str(parsed.payload_root)
    assert {record.object_type for record in parsed.closure.objects} == {
        "blob",
        "tree",
        "commit",
    }

    for record in parsed.closure.objects:
        payload = parsed.payload_root / record.payload_sha256[:2] / record.payload_sha256
        assert payload.read_bytes()


def test_source_capture_streams_raw_objects_without_read_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "canonical"
    repo.mkdir()
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Kernel"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "kernel@example.invalid"],
        cwd=repo,
        check=True,
    )
    payload = os.urandom((3 * 65536) + 137)
    (repo / "large.bin").write_bytes(payload)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "large"], cwd=repo, check=True)
    attestation = attestCanonicalRepository(repo)

    original_read = object_parser_mod.NativeDirectoryHandle.readFile
    original_copy = object_parser_mod.NativeDirectoryHandle.copyFileTo
    streamed: list[str] = []

    def forbid_raw_whole_file_reads(directory, name, *args, **kwargs):
        if re.fullmatch(r"[0-9a-f]{38}|pack-[0-9a-f]{40}\.(?:pack|idx)", name):
            raise AssertionError("raw capture must use the streaming retained-handle API")
        return original_read(directory, name, *args, **kwargs)

    def observe_stream_copy(directory, name, *args, **kwargs):
        streamed.append(name)
        return original_copy(directory, name, *args, **kwargs)

    monkeypatch.setattr(
        object_parser_mod.NativeDirectoryHandle,
        "readFile",
        forbid_raw_whole_file_reads,
    )
    monkeypatch.setattr(
        object_parser_mod.NativeDirectoryHandle,
        "copyFileTo",
        observe_stream_copy,
    )
    snapshot = _capture_minimal_source_snapshot(
        attestation=attestation,
        transaction_id="tx-streamed-source",
        snapshot_root=tmp_path / "controller" / "source-snapshots",
        policy=ManifestPolicy(
            reserved_roots=(),
            max_files=8,
            max_total_bytes=1024 * 1024,
            max_file_bytes=1024 * 1024,
            max_depth=4,
            max_path_bytes=240,
        ),
        tmp_path=tmp_path,
        max_raw_files=32,
        max_raw_bytes=1024 * 1024,
        max_raw_file_bytes=1024 * 1024,
    )

    assert len(streamed) == len(snapshot.entries)
    assert max(entry.size for entry in snapshot.entries) > 65536
    for entry in snapshot.entries:
        captured = snapshot.raw_root / entry.raw_sha256[:2] / entry.raw_sha256
        assert captured.stat().st_size == entry.size
        assert hashlib.sha256(captured.read_bytes()).hexdigest() == entry.raw_sha256


def test_source_parser_resolves_a_real_delta_heavy_pack(tmp_path: Path) -> None:
    repo = tmp_path / "canonical"
    repo.mkdir()
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Kernel"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "kernel@example.invalid"],
        cwd=repo,
        check=True,
    )
    subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=repo, check=True)
    final_payload = b""
    for version in range(18):
        payload = bytearray(b"A" * (64 * 1024))
        marker = f"version-{version:02d}".encode("ascii")
        offset = version * 257
        payload[offset : offset + len(marker)] = marker
        final_payload = bytes(payload)
        (repo / "large.bin").write_bytes(final_payload)
        subprocess.run(["git", "add", "large.bin"], cwd=repo, check=True)
        subprocess.run(
            ["git", "commit", "-m", f"version {version}"],
            cwd=repo,
            check=True,
            stdout=subprocess.DEVNULL,
        )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "repack", "-adf", "--depth=50", "--window=50"],
        cwd=repo,
        check=True,
    )
    index_path = next((repo / ".git" / "objects" / "pack").glob("*.idx"))
    verify_pack = subprocess.run(
        ["git", "verify-pack", "-v", str(index_path)],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.splitlines()
    assert any(
        len(fields := line.split()) == 7 and fields[5].isdigit()
        for line in verify_pack
    ), "fixture must contain at least one deltified object"
    loose_ref = repo / ".git" / "refs" / "heads" / "main"
    loose_ref.parent.mkdir(parents=True, exist_ok=True)
    loose_ref.write_text(f"{head}\n", encoding="ascii")

    policy = ManifestPolicy(
        reserved_roots=(),
        max_files=4,
        max_total_bytes=128 * 1024,
        max_file_bytes=128 * 1024,
        max_depth=4,
        max_path_bytes=240,
    )
    attestation = attestCanonicalRepository(repo)
    snapshot = _capture_minimal_source_snapshot(
        attestation=attestation,
        transaction_id="tx-delta-pack",
        snapshot_root=tmp_path / "controller" / "source-snapshots",
        policy=policy,
        tmp_path=tmp_path,
        max_raw_files=16,
        max_raw_bytes=32 * 1024 * 1024,
        max_raw_file_bytes=32 * 1024 * 1024,
    )

    def run_locally(invocation) -> ObjectParserProcessResult:
        assert invocation.output_root is not None
        result = _run_source_entrypoint(
            invocation.request_path,
            snapshot.raw_root,
            invocation.output_root,
        )
        return ObjectParserProcessResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    parsed = ObjectParser(
        controller_root=tmp_path / "controller",
        image=ObjectParserImage(
            repository="galaxy-r3/object-parser",
            manifest_digest=IMAGE_DIGEST,
            role="object_parser",
        ),
        runtime_entrypoint=ENTRYPOINT,
        process_runner=run_locally,
    ).parseSourceObjectClosure(snapshot=snapshot)

    assert len(parsed.manifest.entries) == 1
    assert parsed.manifest.entries[0].path == "large.bin"
    assert parsed.manifest.entries[0].blob_sha256 == hashlib.sha256(final_payload).hexdigest()

    module = _entrypoint_module()
    store = module._sourceObjects(
        [entry.toDict() for entry in snapshot.entries],
        snapshot.raw_root,
        revision=snapshot.revision,
        sha1dc=_entrypoint_sha1dc(module, tmp_path),
    )
    commit = store.get(snapshot.revision)
    assert commit is not None
    tree_oid = module._commitTree(commit["payload"])
    _manifest, exact_closure = module._sourceManifest(
        revision=snapshot.revision,
        tree_oid=tree_oid,
        objects=store,
        policy=snapshot.policy.toDict(),
    )
    assert len(store) == len(exact_closure)


def test_source_pack_inflates_only_the_intentional_shallow_closure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "canonical"
    repo.mkdir()
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Kernel"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "kernel@example.invalid"],
        cwd=repo,
        check=True,
    )
    (repo / "old.bin").write_bytes(os.urandom(256 * 1024))
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "large history"], cwd=repo, check=True)
    old_blob_oid = subprocess.run(
        ["git", "rev-parse", "HEAD:old.bin"],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()
    (repo / "old.bin").unlink()
    (repo / "current.txt").write_bytes(b"current\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "small current tree"], cwd=repo, check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()
    subprocess.run(["git", "repack", "-adf", "--depth=50"], cwd=repo, check=True)
    loose_ref = repo / ".git" / "refs" / "heads" / "main"
    loose_ref.parent.mkdir(parents=True, exist_ok=True)
    loose_ref.write_text(f"{head}\n", encoding="ascii")
    policy = ManifestPolicy(
        reserved_roots=(),
        max_files=4,
        max_total_bytes=1024,
        max_file_bytes=1024,
        max_depth=4,
        max_path_bytes=240,
    )
    snapshot = _capture_minimal_source_snapshot(
        attestation=attestCanonicalRepository(repo),
        transaction_id="tx-shallow-pack",
        snapshot_root=tmp_path / "controller" / "source-snapshots",
        policy=policy,
        tmp_path=tmp_path,
        max_raw_files=16,
        max_raw_bytes=2 * 1024 * 1024,
        max_raw_file_bytes=2 * 1024 * 1024,
    )
    module = _entrypoint_module()
    monkeypatch.setattr(module, "_MAX_SOURCE_INFLATED_BYTES", 8192)
    store = module._sourceObjects(
        [entry.toDict() for entry in snapshot.entries],
        snapshot.raw_root,
        revision=snapshot.revision,
        sha1dc=_entrypoint_sha1dc(module, tmp_path),
    )
    commit = store[snapshot.revision]
    tree_oid = module._commitTree(commit["payload"])
    manifest, closure = module._sourceManifest(
        revision=snapshot.revision,
        tree_oid=tree_oid,
        objects=store,
        policy=policy.toDict(),
    )

    assert [entry["path"] for entry in manifest["entries"]] == ["current.txt"]
    assert old_blob_oid not in store._objects
    assert set(store._objects) == closure
    assert store._budget._inflated_bytes < 8192


def test_contained_locator_discovers_only_the_loose_shallow_frontier(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "canonical"
    repo.mkdir()
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Kernel"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "kernel@example.invalid"],
        cwd=repo,
        check=True,
    )
    (repo / "old.txt").write_bytes(b"unreachable from the shallow tree\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "history"], cwd=repo, check=True)
    (repo / "old.txt").unlink()
    (repo / "current.txt").write_bytes(b"current\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "current"], cwd=repo, check=True)
    policy = ManifestPolicy(
        reserved_roots=(),
        max_files=4,
        max_total_bytes=1024,
        max_file_bytes=1024,
        max_depth=4,
        max_path_bytes=240,
    )
    catalog = captureCanonicalObjectCatalog(
        attestation=attestCanonicalRepository(repo),
        transaction_id="tx-locator-frontier",
        snapshot_root=tmp_path / "controller" / "selected-source",
        policy=policy,
        max_raw_files=32,
        max_catalog_bytes=1024 * 1024,
        max_raw_file_bytes=1024 * 1024,
    )
    module = _entrypoint_module()
    sha1dc = _entrypoint_sha1dc(module, tmp_path)
    selected: set[str] = set()
    missing = [catalog.revision]
    snapshot = None
    output_root = tmp_path / "frontier-output"
    output_root.mkdir()
    result: dict[str, object] | None = None
    for _ in range(8):
        located = module.locateSourceObjects(
            catalog.locatorRequest(missing),
            catalog.catalog_root,
        )
        for source in located["sources"]:
            selected.update(source["paths"])
        snapshot = captureCanonicalObjectSnapshot(
            catalog=catalog,
            selected_paths=sorted(selected),
            snapshot_root=tmp_path / "controller" / "selected-source",
            previous_snapshot=snapshot,
            max_selected_bytes=1024 * 1024,
        )
        result = module.parseSourceObjectFrontier(
            buildSourceObjectParserRequest(snapshot),
            snapshot.raw_root,
            output_root,
            sha1dc=sha1dc,
        )
        if result["schema"] == "galaxy.source-object-parser-result/v1":
            break
        missing = result["missing_oids"]

    assert result is not None
    assert snapshot is not None
    assert result["schema"] == "galaxy.source-object-parser-result/v1"
    assert result["manifest"]["entries"][0]["path"] == "current.txt"
    assert len(selected) < len(catalog.inventory)
    assert {entry.path for entry in snapshot.entries} == selected
    assert {path.name for path in catalog.catalog_root.rglob("*") if path.is_file()} == set()


@pytest.mark.parametrize("storage_mode", ["loose", "packed", "packed_history"])
def test_object_parser_selects_and_copies_only_the_exact_source_closure(
    tmp_path: Path,
    storage_mode: str,
) -> None:
    repo = tmp_path / "canonical"
    repo.mkdir()
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Kernel"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "kernel@example.invalid"],
        cwd=repo,
        check=True,
    )
    (repo / "history.txt").write_bytes(b"history-only\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "history"], cwd=repo, check=True)
    if storage_mode == "packed_history":
        subprocess.run(["git", "repack", "-adf", "--depth=50"], cwd=repo, check=True)
        subprocess.run(["git", "prune-packed"], cwd=repo, check=True)
    (repo / "history.txt").unlink()
    (repo / "current.txt").write_bytes(b"selected\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "current"], cwd=repo, check=True)
    if storage_mode == "packed":
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        ).stdout.strip()
        subprocess.run(["git", "repack", "-adf", "--depth=50"], cwd=repo, check=True)
        subprocess.run(["git", "prune-packed"], cwd=repo, check=True)
        loose_ref = repo / ".git" / "refs" / "heads" / "main"
        loose_ref.parent.mkdir(parents=True, exist_ok=True)
        loose_ref.write_text(f"{head}\n", encoding="ascii")
    attestation = attestCanonicalRepository(repo)
    source_root = tmp_path / "controller" / "minimal-source"
    observed_invocations = []

    def run_source(invocation):
        observed_invocations.append(invocation)
        return _run_source_protocol_invocation(invocation)

    parser = ObjectParser(
        controller_root=tmp_path / "controller",
        image=ObjectParserImage(
            repository="galaxy-r3/object-parser",
            manifest_digest=IMAGE_DIGEST,
            role="object_parser",
        ),
        runtime_entrypoint=ENTRYPOINT,
        process_runner=run_source,
    )
    parsed = parser.captureAndParseSourceObjectClosure(
        attestation=attestation,
        transaction_id=f"tx-minimal-source-{storage_mode}",
        snapshot_root=source_root,
        policy=ManifestPolicy(
            reserved_roots=(),
            max_files=4,
            max_total_bytes=1024,
            max_file_bytes=1024,
            max_depth=4,
            max_path_bytes=240,
        ),
        max_raw_files=32,
        max_raw_bytes=1024 * 1024,
        max_raw_file_bytes=1024 * 1024,
        wall_timeout_seconds=30,
        idle_timeout_seconds=7,
    )

    transaction_id = f"tx-minimal-source-{storage_mode}"
    selected_raw = source_root / transaction_id / "selected" / "raw"
    selected_files = [path for path in selected_raw.rglob("*") if path.is_file()]
    canonical_raw = [
        path
        for path in (repo / ".git" / "objects").rglob("*")
        if path.is_file()
        and (
            re.fullmatch(r"[0-9a-f]{38}", path.name)
            or re.fullmatch(r"pack-[0-9a-f]{40}\.(?:pack|idx)", path.name)
        )
    ]
    assert [entry.path for entry in parsed.manifest.entries] == ["current.txt"]
    selected_snapshots = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (source_root / transaction_id / "selected" / "snapshots").glob(
            "*.json"
        )
    ]
    final_snapshot = max(selected_snapshots, key=lambda value: len(value["entries"]))
    selected_paths = {entry["path"] for entry in final_snapshot["entries"]}
    if storage_mode == "packed":
        assert not any(path.endswith(".pack") for path in selected_paths)
        assert any(path.startswith("pack-range/") for path in selected_paths)
        canonical_pack_bytes = sum(
            path.stat().st_size
            for path in canonical_raw
            if path.suffix == ".pack"
        )
        selected_range_bytes = sum(
            entry["size"]
            for entry in final_snapshot["entries"]
            if entry["path"].startswith("pack-range/")
        )
        assert selected_range_bytes < canonical_pack_bytes

        refusal_catalog = captureCanonicalObjectCatalog(
            attestation=attestation,
            transaction_id="tx-whole-pack-refusal",
            snapshot_root=source_root,
            policy=parsed.manifest.policy,
            max_raw_files=32,
            max_catalog_bytes=1024 * 1024,
            max_raw_file_bytes=1024 * 1024,
        )
        legacy_whole_pack = [
            record.logical_path
            for record in refusal_catalog.inventory
            if record.logical_path.endswith((".idx", ".pack"))
        ]
        with pytest.raises(ObjectParserRefused, match="whole pack selection"):
            captureCanonicalObjectSnapshot(
                catalog=refusal_catalog,
                selected_paths=legacy_whole_pack,
                snapshot_root=source_root,
                max_selected_bytes=1024 * 1024,
            )

        located = _entrypoint_module().locateSourceObjects(
            refusal_catalog.locatorRequest([refusal_catalog.revision]),
            refusal_catalog.catalog_root,
        )
        exact_paths = list(located["sources"][0]["paths"])
        range_index = next(
            index
            for index, path in enumerate(exact_paths)
            if path.startswith("pack-range/")
        )
        prefix, encoded_range = exact_paths[range_index].rsplit("/", 1)
        source_size, suffix = encoded_range.split("-", 1)
        exact_paths[range_index] = f"{prefix}/{int(source_size) + 1}-{suffix}"
        with pytest.raises(ObjectParserRefused, match="exact source"):
            captureCanonicalObjectSnapshot(
                catalog=refusal_catalog,
                selected_paths=exact_paths,
                snapshot_root=source_root,
                max_selected_bytes=1024 * 1024,
            )
    elif storage_mode == "packed_history":
        assert all(path.startswith("loose/") for path in selected_paths)
    else:
        assert len(selected_files) == 3
    if storage_mode != "packed":
        assert len(selected_files) < len(canonical_raw)
    assert {record.object_type for record in parsed.closure.objects} == {
        "blob",
        "tree",
        "commit",
    }
    observed_walls = [item.wall_timeout_seconds for item in observed_invocations]
    assert observed_walls == sorted(observed_walls, reverse=True)
    assert all(0 < item.wall_timeout_seconds <= 30 for item in observed_invocations)
    assert all(
        0 < item.idle_timeout_seconds <= min(7, item.wall_timeout_seconds)
        for item in observed_invocations
    )

    replayed = parser.captureAndParseSourceObjectClosure(
        attestation=attestation,
        transaction_id=transaction_id,
        snapshot_root=source_root,
        policy=ManifestPolicy(
            reserved_roots=(),
            max_files=4,
            max_total_bytes=1024,
            max_file_bytes=1024,
            max_depth=4,
            max_path_bytes=240,
        ),
        max_raw_files=32,
        max_raw_bytes=1024 * 1024,
        max_raw_file_bytes=1024 * 1024,
    )

    assert replayed == parsed
    assert [path for path in selected_raw.rglob("*") if path.is_file()] == selected_files
    if storage_mode == "loose":
        evidence_path = next(
            (source_root / transaction_id / "selected" / "snapshots").glob("*.json")
        )
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["revision"] = "0" * 40
        evidence_path.write_bytes(canonical_json_bytes(evidence))
        with pytest.raises(ObjectParserRefused, match="evidence binding differs"):
            parser.captureAndParseSourceObjectClosure(
                attestation=attestation,
                transaction_id=transaction_id,
                snapshot_root=source_root,
                policy=ManifestPolicy(
                    reserved_roots=(),
                    max_files=4,
                    max_total_bytes=1024,
                    max_file_bytes=1024,
                    max_depth=4,
                    max_path_bytes=240,
                ),
                max_raw_files=32,
                max_raw_bytes=1024 * 1024,
                max_raw_file_bytes=1024 * 1024,
            )


def test_source_inflation_budget_bounds_aggregate_bytes_and_object_count(
    tmp_path: Path,
) -> None:
    module = _entrypoint_module()
    sha1dc = _entrypoint_sha1dc(module, tmp_path)
    objects = {}
    byte_budget = module._InflationBudget(max_objects=4, max_inflated_bytes=5)
    module._addGitObject(
        objects,
        object_type="blob",
        payload=b"abc",
        budget=byte_budget,
        sha1dc=sha1dc,
    )
    with pytest.raises(module.ObjectParserRefused, match="aggregate inflated-byte"):
        module._addGitObject(
            objects,
            object_type="blob",
            payload=b"def",
            budget=byte_budget,
            sha1dc=sha1dc,
        )

    count_budget = module._InflationBudget(max_objects=1, max_inflated_bytes=64)
    counted = {}
    module._addGitObject(
        counted,
        object_type="blob",
        payload=b"one",
        budget=count_budget,
        sha1dc=sha1dc,
    )
    with pytest.raises(module.ObjectParserRefused, match="object-count"):
        module._addGitObject(
            counted,
            object_type="blob",
            payload=b"two",
            budget=count_budget,
            sha1dc=sha1dc,
        )

    oversized_index = (
        b"\xfftOc"
        + struct.pack(">I", 2)
        + struct.pack(">256I", *([0] * 255), 2)
        + (b"\0" * 40)
    )
    with pytest.raises(module.ObjectParserRefused, match="object-count"):
        module._parsePackIndex(oversized_index, max_objects=1)


def test_source_tree_parser_rejects_noncanonical_modes_and_duplicate_names() -> None:
    module = _entrypoint_module()
    oid = bytes.fromhex("1" * 40)

    with pytest.raises(module.ObjectParserRefused, match="mode is noncanonical"):
        module._treeEntries(b"0100644 file.txt\0" + oid)

    duplicate_name = (
        b"100644 same\0"
        + oid
        + b"40000 same\0"
        + bytes.fromhex("2" * 40)
    )
    with pytest.raises(module.ObjectParserRefused, match="name is duplicated"):
        module._treeEntries(duplicate_name)

    ordered = (
        b"100644 a\0"
        + oid
        + b"100644 b\0"
        + bytes.fromhex("2" * 40)
    )
    with pytest.raises(module.ObjectParserRefused, match="entry-count"):
        module._treeEntries(ordered, max_entries=1)


def test_source_tree_walk_enforces_policy_depth_during_traversal() -> None:
    module = _entrypoint_module()
    blob_oid = "f" * 40
    blob_payload = b"payload"
    objects: dict[str, dict[str, object]] = {
        blob_oid: {
            "object_type": "blob",
            "payload": blob_payload,
            "frame": b"blob 7\0" + blob_payload,
        }
    }
    child_oid = blob_oid
    for index in reversed(range(6)):
        tree_oid = f"{index + 1:040x}"
        if child_oid == blob_oid:
            payload = b"100644 leaf.txt\0" + bytes.fromhex(child_oid)
        else:
            payload = b"40000 nested\0" + bytes.fromhex(child_oid)
        objects[tree_oid] = {
            "object_type": "tree",
            "payload": payload,
            "frame": b"tree " + str(len(payload)).encode("ascii") + b"\0" + payload,
        }
        child_oid = tree_oid
    policy = ManifestPolicy(
        reserved_roots=(),
        max_files=8,
        max_total_bytes=1024,
        max_file_bytes=1024,
        max_depth=3,
        max_path_bytes=240,
    )

    with pytest.raises(module.ObjectParserRefused, match="depth quota"):
        module._sourceManifest(
            revision="a" * 40,
            tree_oid=child_oid,
            objects=objects,
            policy=policy.toDict(),
        )


@pytest.mark.skipif(os.name != "nt", reason="Windows retained-handle boundary")
def test_source_capture_never_reads_a_rebound_git_common_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "canonical"
    repo.mkdir()
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Kernel"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "kernel@example.invalid"],
        cwd=repo,
        check=True,
    )
    (repo / "source.txt").write_bytes(b"original\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "source"], cwd=repo, check=True)
    attestation = attestCanonicalRepository(repo)
    common = Path(attestation.git_common_dir)
    original_raw_digests = {
        hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (common / "objects").rglob("*")
        if path.is_file()
    }
    held = common.with_name("git-common-held")
    malicious_frame = b"blob 8\0attacker"
    malicious_raw = zlib.compress(malicious_frame)
    malicious_digest = hashlib.sha256(malicious_raw).hexdigest()
    real_open = object_parser_mod.openNativeDirectory
    rebound = False

    def open_then_rebind(path):
        nonlocal rebound
        directory = real_open(path)
        if Path(path) == common and not rebound:
            common.rename(held)
            oid = hashlib.sha1(malicious_frame, usedforsecurity=False).hexdigest()
            leaf = common / "objects" / oid[:2] / oid[2:]
            leaf.parent.mkdir(parents=True)
            leaf.write_bytes(malicious_raw)
            rebound = True
        return directory

    monkeypatch.setattr(object_parser_mod, "openNativeDirectory", open_then_rebind)
    snapshot_root = tmp_path / "controller" / "source-snapshots"
    with pytest.raises(ObjectParserRefused, match="drifted"):
        captureCanonicalObjectCatalog(
            attestation=attestation,
            transaction_id="tx-rebound-common",
            snapshot_root=snapshot_root,
            policy=ManifestPolicy(
                reserved_roots=(),
                max_files=8,
                max_total_bytes=1024,
                max_file_bytes=1024,
                max_depth=4,
                max_path_bytes=240,
            ),
            max_raw_files=32,
            max_catalog_bytes=1024 * 1024,
            max_raw_file_bytes=1024 * 1024,
        )

    captured = {
        hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (snapshot_root / "tx-rebound-common" / "catalog" / "raw").rglob("*")
        if path.is_file()
    }
    assert rebound is True
    assert captured <= original_raw_digests
    assert malicious_digest not in captured


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker CLI unavailable")
def test_real_offline_object_parser_image_when_preloaded(tmp_path: Path) -> None:
    inspect = subprocess.run(
        ["docker", "image", "inspect", f"galaxy-r3/object-parser@sha256:{IMAGE_DIGEST}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=15,
        check=False,
    )
    if inspect.returncode != 0:
        pytest.skip("reviewed offline object-parser image is not preloaded")
    if not _reviewed_image_has_sha1dc():
        pytest.skip("preloaded parser image predates the SHA1DC closure")
    expected, snapshot = _fixture(tmp_path)
    parser = ObjectParser(
        controller_root=tmp_path / "controller",
        image=ObjectParserImage(
            repository="galaxy-r3/object-parser",
            manifest_digest=IMAGE_DIGEST,
            role="object_parser",
        ),
        runtime_entrypoint=ENTRYPOINT,
    )
    parsed = parser.parseCandidateSnapshot(snapshot=snapshot, expected=expected)
    assert {entry.path for entry in parsed.manifest.entries} == {"a.txt", "b.txt"}
    assert parsed.container_network_allowed is False


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker CLI unavailable")
def test_real_offline_parser_idle_watchdog_kills_and_reaps_container(
    tmp_path: Path,
) -> None:
    inspect = subprocess.run(
        ["docker", "image", "inspect", f"galaxy-r3/object-parser@sha256:{IMAGE_DIGEST}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=15,
        check=False,
    )
    if inspect.returncode != 0:
        pytest.skip("reviewed offline object-parser image is not preloaded")
    expected, snapshot = _fixture(tmp_path)
    sleeper = tmp_path / "sleeper.py"
    sleeper.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    parser = ObjectParser(
        controller_root=tmp_path / "controller",
        image=ObjectParserImage(
            repository="galaxy-r3/object-parser",
            manifest_digest=IMAGE_DIGEST,
            role="object_parser",
        ),
        runtime_entrypoint=sleeper,
        timeout_seconds=3,
        idle_timeout_seconds=0.5,
    )

    with pytest.raises(ObjectParserRefused, match="idle-time"):
        parser.parseCandidateSnapshot(snapshot=snapshot, expected=expected)

    evidence_root = (
        tmp_path
        / "controller"
        / "object-parser"
        / hashlib.sha256(snapshot.transaction_id.encode("utf-8")).hexdigest()
        / "evidence"
    )
    created = json.loads((evidence_root / "container-created.json").read_bytes())
    started = json.loads((evidence_root / "container-start-intent.json").read_bytes())
    assert created["schema"] == "galaxy.object-parser-container-created/v1"
    assert created["container_id"] == started["container_id"]
    assert started["schema"] == "galaxy.object-parser-container-start-intent/v1"

    container_name = _candidate_container_name(
        tmp_path / "controller",
        snapshot.transaction_id,
    )
    assert subprocess.run(
        ["docker", "container", "inspect", container_name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=15,
        check=False,
    ).returncode != 0


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker CLI unavailable")
def test_real_parser_recovers_exact_container_after_controller_hard_kill(
    tmp_path: Path,
) -> None:
    inspected = subprocess.run(
        ["docker", "image", "inspect", f"galaxy-r3/object-parser@sha256:{IMAGE_DIGEST}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=15,
        check=False,
    )
    if inspected.returncode != 0 or not _reviewed_image_has_sha1dc():
        pytest.skip("reviewed SHA1DC object-parser image is not preloaded")
    expected, snapshot = _fixture(tmp_path)
    delayed = tmp_path / "delayed-object-parser.py"
    source = ENTRYPOINT.read_text(encoding="utf-8")
    marker = "from __future__ import annotations\n"
    assert source.count(marker) == 1
    delayed.write_text(
        source.replace(marker, marker + "import time as _delay_time\n_delay_time.sleep(2.0)\n"),
        encoding="utf-8",
    )
    controller = tmp_path / "controller"
    spec = tmp_path / "child-spec.json"
    spec.write_text(
        json.dumps(
            {
                "controller": str(controller),
                "entrypoint": str(delayed),
                "image": IMAGE_DIGEST,
                "blob_root": str(snapshot.blob_root),
                "transaction_id": snapshot.transaction_id,
                "snapshot_entries": [entry.toDict() for entry in snapshot.entries],
                "expected": expected.toDict(),
            }
        ),
        encoding="utf-8",
    )
    child_script = tmp_path / "crash-parser-controller.py"
    child_script.write_text(
        """
import json
from pathlib import Path
import sys
from platform_core.execution.object_parser import CandidateSnapshot, ObjectParser, ObjectParserImage, SnapshotEntry
from platform_core.runtime.object_manifest import AttributeRule, ManifestEntry, ManifestPolicy, ObjectManifest

value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
policy_value = value["expected"]["policy"]
policy = ManifestPolicy(
    reserved_roots=tuple(policy_value["reserved_roots"]),
    max_files=policy_value["max_files"],
    max_total_bytes=policy_value["max_total_bytes"],
    max_file_bytes=policy_value["max_file_bytes"],
    max_depth=policy_value["max_depth"],
    max_path_bytes=policy_value["max_path_bytes"],
)
expected = ObjectManifest(
    expected_revision=value["expected"]["expected_revision"],
    entries=tuple(ManifestEntry(**item) for item in value["expected"]["entries"]),
    attribute_rules=tuple(
        AttributeRule(pattern=item["pattern"], attributes=tuple(item["attributes"]))
        for item in value["expected"]["attribute_rules"]
    ),
    policy=policy,
)
snapshot = CandidateSnapshot(
    transaction_id=value["transaction_id"],
    blob_root=Path(value["blob_root"]),
    entries=tuple(SnapshotEntry(**item) for item in value["snapshot_entries"]),
    policy=policy,
)
parser = ObjectParser(
    controller_root=Path(value["controller"]),
    image=ObjectParserImage(
        repository="galaxy-r3/object-parser",
        manifest_digest=value["image"],
        role="object_parser",
    ),
    runtime_entrypoint=Path(value["entrypoint"]),
    timeout_seconds=30,
    idle_timeout_seconds=30,
)
parser.parseCandidateSnapshot(snapshot=snapshot, expected=expected)
""".lstrip(),
        encoding="utf-8",
    )
    child = subprocess.Popen(
        [sys.executable, str(child_script), str(spec)],
        cwd=Path.cwd(),
        env={**os.environ, "PYTHONPATH": str(Path.cwd())},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    namespace = hashlib.sha256(snapshot.transaction_id.encode("utf-8")).hexdigest()
    container_name = _candidate_container_name(
        controller,
        snapshot.transaction_id,
    )
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            state = subprocess.run(
                [
                    "docker",
                    "container",
                    "inspect",
                    "--format",
                    "{{json .State.Running}}",
                    container_name,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
            )
            if state.returncode == 0 and state.stdout.strip() == b"true":
                break
            time.sleep(0.1)
        else:
            assert child.stderr is not None
            detail = child.stderr.read().decode("utf-8", errors="replace")
            raise AssertionError(
                f"child controller did not start the exact parser container: {detail}"
            )
        child.kill()
        child.wait(timeout=10)

        parser = ObjectParser(
            controller_root=controller,
            image=ObjectParserImage(
                repository="galaxy-r3/object-parser",
                manifest_digest=IMAGE_DIGEST,
                role="object_parser",
            ),
            runtime_entrypoint=delayed,
            timeout_seconds=15,
            idle_timeout_seconds=5,
        )
        parsed = parser.parseCandidateSnapshot(snapshot=snapshot, expected=expected)

        assert parsed.manifest.expected_revision == expected.expected_revision
        evidence = controller / "object-parser" / namespace / "evidence"
        assert (evidence / "terminal-result.json").is_file()
        assert (evidence / "container-cleaned.json").is_file()
        assert subprocess.run(
            ["docker", "container", "inspect", container_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        ).returncode != 0
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
        subprocess.run(
            ["docker", "container", "rm", "--force", container_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        )


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker CLI unavailable")
def test_real_parser_never_adopts_or_removes_foreign_same_name_container(
    tmp_path: Path,
) -> None:
    inspected = subprocess.run(
        ["docker", "image", "inspect", f"galaxy-r3/object-parser@sha256:{IMAGE_DIGEST}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=15,
        check=False,
    )
    if inspected.returncode != 0:
        pytest.skip("reviewed object-parser image is not preloaded")
    expected, snapshot = _fixture(tmp_path)
    container_name = _candidate_container_name(
        tmp_path / "controller",
        snapshot.transaction_id,
    )
    created = subprocess.run(
        [
            "docker",
            "create",
            "--name",
            container_name,
            f"galaxy-r3/object-parser@sha256:{IMAGE_DIGEST}",
            "--help",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    if created.returncode != 0:
        pytest.skip(f"could not create ownership canary: {created.stderr!r}")
    try:
        parser = ObjectParser(
            controller_root=tmp_path / "controller",
            image=ObjectParserImage(
                repository="galaxy-r3/object-parser",
                manifest_digest=IMAGE_DIGEST,
                role="object_parser",
            ),
            runtime_entrypoint=ENTRYPOINT,
        )

        with pytest.raises(ObjectParserRefused, match="labels differ"):
            parser.parseCandidateSnapshot(snapshot=snapshot, expected=expected)

        assert subprocess.run(
            ["docker", "container", "inspect", container_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        ).returncode == 0
    finally:
        subprocess.run(
            ["docker", "container", "rm", "--force", container_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        )


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker CLI unavailable")
def test_real_offline_image_parses_raw_source_closure_when_preloaded(
    tmp_path: Path,
) -> None:
    inspect = subprocess.run(
        ["docker", "image", "inspect", f"galaxy-r3/object-parser@sha256:{IMAGE_DIGEST}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=15,
        check=False,
    )
    if inspect.returncode != 0:
        pytest.skip("reviewed offline object-parser image is not preloaded")
    if not _reviewed_image_has_sha1dc():
        pytest.skip("preloaded parser image predates the SHA1DC closure")
    repo = tmp_path / "canonical"
    repo.mkdir()
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Kernel"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "kernel@example.invalid"],
        cwd=repo,
        check=True,
    )
    (repo / "source.txt").write_bytes(b"contained\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "source"], cwd=repo, check=True)
    policy = ManifestPolicy(
        reserved_roots=(),
        max_files=10,
        max_total_bytes=1024,
        max_file_bytes=512,
        max_depth=8,
        max_path_bytes=240,
    )
    attestation = attestCanonicalRepository(repo)
    parser = ObjectParser(
        controller_root=tmp_path / "controller",
        image=ObjectParserImage(
            repository="galaxy-r3/object-parser",
            manifest_digest=IMAGE_DIGEST,
            role="object_parser",
        ),
        runtime_entrypoint=ENTRYPOINT,
    )

    parsed = parser.captureAndParseSourceObjectClosure(
        attestation=attestation,
        transaction_id="tx-real-source-parser",
        snapshot_root=tmp_path / "controller" / "source-snapshots",
        policy=policy,
        max_raw_files=32,
        max_raw_bytes=1024 * 1024,
        max_raw_file_bytes=1024 * 1024,
    )
    assert [entry.path for entry in parsed.manifest.entries] == ["source.txt"]
    assert parsed.closure.source_snapshot_digest == parsed.snapshot_digest
    assert parsed.container_network_allowed is False


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker CLI unavailable")
def test_real_offline_parser_contains_a_malformed_pack_without_output_or_escape(
    tmp_path: Path,
) -> None:
    inspect = subprocess.run(
        ["docker", "image", "inspect", f"galaxy-r3/object-parser@sha256:{IMAGE_DIGEST}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=15,
        check=False,
    )
    if inspect.returncode != 0:
        pytest.skip("reviewed offline object-parser image is not preloaded")
    if not _reviewed_image_has_sha1dc():
        pytest.skip("preloaded parser image predates the SHA1DC closure")
    repo = tmp_path / "canonical"
    repo.mkdir()
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Kernel"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "kernel@example.invalid"],
        cwd=repo,
        check=True,
    )
    (repo / "source.txt").write_bytes(b"contained\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "source"], cwd=repo, check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()
    subprocess.run(["git", "gc", "--prune=now"], cwd=repo, check=True)
    loose_ref = repo / ".git" / "refs" / "heads" / "main"
    loose_ref.parent.mkdir(parents=True, exist_ok=True)
    loose_ref.write_text(f"{head}\n", encoding="ascii")
    policy = ManifestPolicy(
        reserved_roots=(),
        max_files=10,
        max_total_bytes=1024,
        max_file_bytes=512,
        max_depth=8,
        max_path_bytes=240,
    )
    clean = _capture_minimal_source_snapshot(
        attestation=attestCanonicalRepository(repo),
        transaction_id="tx-malformed-source",
        snapshot_root=tmp_path / "controller" / "clean-source-snapshots",
        policy=policy,
        tmp_path=tmp_path,
        max_raw_files=32,
        max_raw_bytes=1024 * 1024,
        max_raw_file_bytes=1024 * 1024,
    )
    malicious_root = tmp_path / "controller" / "malicious-raw"
    malicious_root.mkdir(parents=True)
    entries: list[RawObjectSnapshotEntry] = []
    changed = False
    for entry in clean.entries:
        payload = (
            clean.raw_root / entry.raw_sha256[:2] / entry.raw_sha256
        ).read_bytes()
        if entry.path.startswith("pack-range/") and not changed:
            mutated = bytearray(payload)
            mutated[-1] ^= 0x01
            payload = bytes(mutated)
            changed = True
        digest, _ = _put_blob(malicious_root, payload)
        entries.append(
            RawObjectSnapshotEntry(
                path=entry.path,
                raw_sha256=digest,
                size=len(payload),
            )
        )
    assert changed
    malicious = CanonicalObjectSnapshot(
        transaction_id="tx-malformed-pack",
        repository_id=clean.repository_id,
        revision=clean.revision,
        canonical_attestation_digest=clean.canonical_attestation_digest,
        raw_root=malicious_root,
        entries=tuple(entries),
        policy=clean.policy,
    )
    goldstone = tmp_path / "outside-goldstone.txt"
    goldstone.write_bytes(b"outside-unchanged")
    controller = tmp_path / "controller"
    parser = ObjectParser(
        controller_root=controller,
        image=ObjectParserImage(
            repository="galaxy-r3/object-parser",
            manifest_digest=IMAGE_DIGEST,
            role="object_parser",
        ),
        runtime_entrypoint=ENTRYPOINT,
    )

    with pytest.raises(ObjectParserRefused, match="pack object"):
        parser.parseSourceObjectClosure(snapshot=malicious)

    assert goldstone.read_bytes() == b"outside-unchanged"
    namespace = hashlib.sha256(
        ("source\0" + malicious.transaction_id).encode("utf-8")
    ).hexdigest()
    output_root = controller / "source-object-parser" / namespace / "output" / "payloads"
    assert list(output_root.rglob("*")) == []
    container_name = _source_container_name(
        controller,
        malicious.transaction_id,
    )
    assert subprocess.run(
        ["docker", "container", "inspect", container_name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=15,
        check=False,
    ).returncode != 0
