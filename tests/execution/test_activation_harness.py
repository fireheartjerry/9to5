"""RED contracts for the sealed external GALAXY activation harness.

The immutable plan supplies requirements, but not execution truth.  This test
therefore builds a pinned executable matrix, starts the harness in a separate
sealed process, and retains all canary secrets and observations in the parent.
No target-supplied Python adapter or expected result enters the harness.
"""
from __future__ import annotations

import ast
import base64
import ctypes
import dataclasses
import hashlib
import hmac
import importlib
import json
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import threading
import time
from ctypes import wintypes
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import psutil
import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

CAMPAIGN_TIMEOUT_SECONDS = 1800


def test_docker_command_uses_a_fresh_empty_cli_configuration(tmp_path, monkeypatch):
    mod = importlib.import_module("bootstrap.galaxy_launcher.activation_harness")
    ambient = tmp_path / "ambient-docker-config"
    ambient.mkdir()
    (ambient / "config.json").write_text('{"credsStore":"poison"}', encoding="utf-8")
    monkeypatch.setenv("DOCKER_CONFIG", str(ambient))
    observed: dict[str, object] = {}

    def fake_run(argv, **kwargs):
        environment = kwargs["env"]
        config_root = Path(environment["DOCKER_CONFIG"])
        observed["config_root"] = config_root
        observed["environment"] = dict(environment)
        assert config_root.is_dir()
        assert not any(config_root.iterdir())
        kwargs["stdout"].write(b"[]")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    runtime = SimpleNamespace(
        docker_path=tmp_path / "docker.exe",
        external_root=tmp_path,
    )

    completed = mod._docker_command(runtime, ["image", "inspect", "sha256:" + "a" * 64], timeout=3)

    assert completed.returncode == 0
    assert observed["config_root"] != ambient
    assert not Path(observed["config_root"]).exists()
    assert observed["environment"]["DOCKER_HOST"] == "npipe:////./pipe/dockerDesktopLinuxEngine"


def test_docker_command_spools_and_refuses_output_above_quota(tmp_path, monkeypatch):
    mod = importlib.import_module("bootstrap.galaxy_launcher.activation_harness")
    monkeypatch.setattr(mod, "_MAX_DOCKER_COMMAND_OUTPUT_BYTES", 32)

    def fake_run(argv, **kwargs):
        kwargs["stdout"].write(b"x" * 33)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    runtime = SimpleNamespace(
        docker_path=tmp_path / "docker.exe",
        external_root=tmp_path,
    )

    with pytest.raises(mod.ActivationInvariantFailed, match="output exceeds quota"):
        mod._docker_command(runtime, ["logs", "container"], timeout=3)


def test_inert_role_runner_uses_digest_only_offline_container_boundary(tmp_path):
    mod = importlib.import_module("bootstrap.galaxy_launcher.activation_harness")
    external = tmp_path / "installed"
    controller = external / "generations" / "00000007" / "controller"
    images = external / "generations" / "00000007" / "images"
    admin = external / "admin" / "repo"
    input_root = admin / "input"
    output_root = admin / "output"
    for directory in (controller, images, input_root, output_root):
        directory.mkdir(parents=True)
    entrypoint = controller / "object_parser_entrypoint.py"
    entrypoint.write_bytes(b"print('sealed')\n")
    docker = controller / "docker.exe"
    docker.write_bytes(b"sealed-docker")
    archive = images / "object-parser.oci.tar"
    archive.write_bytes(b"offline-image")
    image_digest = "a" * 64
    runtime = SimpleNamespace(
        external_root=external.resolve(),
        docker_path=docker.resolve(),
        docker_digest=hashlib.sha256(docker.read_bytes()).hexdigest(),
        object_parser_entrypoint_path=entrypoint.resolve(),
        object_parser_entrypoint_digest=hashlib.sha256(
            entrypoint.read_bytes()
        ).hexdigest(),
        reviewer_entrypoint=(controller / "activation_reviewer.py").resolve(),
        reviewer_digest="b" * 64,
        image_digests={"object_parser": image_digest, "reviewer": "c" * 64},
        image_archive_paths={
            "object_parser": archive.resolve(),
            "reviewer": archive.resolve(),
        },
        runtime_digest="d" * 64,
    )
    calls: list[tuple[str, ...]] = []
    observed_control: dict[str, object] = {}
    container_id = "e" * 64
    result_body = b'{"network_allowed":false,"schema":"example/v1"}\n'

    def command_runner(actual_runtime, arguments, *, timeout):
        assert actual_runtime is runtime
        assert timeout > 0
        argv = tuple(arguments)
        calls.append(argv)
        if argv[:2] == ("image", "inspect"):
            return subprocess.CompletedProcess(
                argv,
                0,
                json.dumps([{"Id": "sha256:" + image_digest}]),
                "",
            )
        if argv[0] == "create":
            control_mount = next(
                argv[index + 1]
                for index, value in enumerate(argv[:-1])
                if value == "--mount" and "target=/galaxy-control" in argv[index + 1]
            )
            control_source = control_mount.removeprefix("type=bind,source=").split(
                ",target=/galaxy-control", 1
            )[0]
            observed_control.update(
                json.loads((Path(control_source) / "activation.json").read_bytes())
            )
            return subprocess.CompletedProcess(argv, 0, container_id + "\n", "")
        if argv[:2] == ("wait", container_id):
            return subprocess.CompletedProcess(argv, 0, "0\n", "")
        if argv[:2] == ("logs", container_id):
            return subprocess.CompletedProcess(
                argv, 0, result_body.decode("ascii"), ""
            )
        return subprocess.CompletedProcess(argv, 0, "", "")

    result = mod.run_inert_role(
        runtime,
        role="object_parser",
        runtime_argv=(
            "source-object-closure",
            "--request",
            "/galaxy-input/request.json",
        ),
        input_mounts=((input_root, "/galaxy-input"),),
        writable_mounts=((output_root, "/galaxy-output"),),
        invocation_root=admin / "contained-runtime",
        command_runner=command_runner,
    )

    assert result.stdout == result_body
    assert result.stderr == b""
    assert result.image_digest == image_digest
    create = next(call for call in calls if call[0] == "create")
    assert "--pull=never" in create
    assert "--network=none" in create
    assert "--read-only" in create
    assert "--cap-drop=ALL" in create
    assert "--security-opt=no-new-privileges:true" in create
    assert "--user=65532:65532" in create
    assert "sha256:" + image_digest in create
    assert not any("latest" in value for value in create)
    assert observed_control["argv"] == [
        "source-object-closure",
        "--request",
        "/galaxy-input/request.json",
    ]
    assert "source-object-closure" not in create
    assert "--request" not in create
    assert "/galaxy-input/request.json" not in create
    input_mount = next(
        create[index + 1]
        for index, value in enumerate(create[:-1])
        if value == "--mount" and "target=/galaxy-input" in create[index + 1]
    )
    output_mount = next(
        create[index + 1]
        for index, value in enumerate(create[:-1])
        if value == "--mount" and "target=/galaxy-output" in create[index + 1]
    )
    assert input_mount.endswith(",readonly")
    assert not output_mount.endswith(",readonly")
    assert ("rm", "-f", container_id) in calls


def test_inert_role_runner_refuses_mount_outside_installed_root(tmp_path):
    mod = importlib.import_module("bootstrap.galaxy_launcher.activation_harness")
    external = tmp_path / "installed"
    controller = external / "controller"
    controller.mkdir(parents=True)
    entrypoint = controller / "object_parser_entrypoint.py"
    entrypoint.write_bytes(b"pass\n")
    docker = controller / "docker.exe"
    docker.write_bytes(b"sealed-docker")
    archive = controller / "object-parser.oci.tar"
    archive.write_bytes(b"offline")
    runtime = SimpleNamespace(
        external_root=external.resolve(),
        docker_path=docker,
        docker_digest=hashlib.sha256(docker.read_bytes()).hexdigest(),
        object_parser_entrypoint_path=entrypoint,
        object_parser_entrypoint_digest=hashlib.sha256(
            entrypoint.read_bytes()
        ).hexdigest(),
        reviewer_entrypoint=controller / "activation_reviewer.py",
        reviewer_digest="b" * 64,
        image_digests={"object_parser": "a" * 64, "reviewer": "c" * 64},
        image_archive_paths={"object_parser": archive, "reviewer": archive},
        runtime_digest="d" * 64,
    )
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(mod.ActivationInvariantFailed, match="outside installed root"):
        mod.run_inert_role(
            runtime,
            role="object_parser",
            runtime_argv=(),
            input_mounts=((outside, "/galaxy-input"),),
            writable_mounts=(),
            invocation_root=external / "admin",
            command_runner=lambda *_args, **_kwargs: None,
        )


def test_kernel_artifact_qualification_payload_is_staging_only_and_closed(tmp_path):
    mod = importlib.import_module("bootstrap.galaxy_launcher.activation_harness")
    generation = tmp_path / "generations" / "00000007"
    controller = generation / "controller"
    images = generation / "images"
    controller.mkdir(parents=True)
    images.mkdir()
    runtime_lock = controller / "runtime.lock.json"
    runtime_lock.write_bytes(b"sealed-runtime-lock")
    docker = controller / "docker.exe"
    docker.write_bytes(b"sealed-docker")
    parser_source = controller / "object_parser_entrypoint.py"
    parser_source.write_bytes(b"sealed parser\n")
    writer_source = controller / "git_object_writer.py"
    writer_source.write_bytes(b"sealed writer\n")
    archive = images / "object-parser.oci.tar"
    archive.write_bytes(b"sealed oci")
    runtime = SimpleNamespace(
        generation=7,
        runtime_digest="1" * 64,
        runtime_lock_path=runtime_lock,
        docker_path=docker,
        docker_digest=hashlib.sha256(docker.read_bytes()).hexdigest(),
        object_parser_entrypoint_path=parser_source,
        object_parser_entrypoint_digest=hashlib.sha256(
            parser_source.read_bytes()
        ).hexdigest(),
        git_object_writer_source_path=writer_source,
        git_object_writer_source_digest=hashlib.sha256(
            writer_source.read_bytes()
        ).hexdigest(),
    )
    sha1dc_binding = {"schema": "galaxy.sha1dc-runtime-binding/v1"}
    inspection = SimpleNamespace(
        manifest_digest="2" * 64,
        config_digest="3" * 64,
        closure_digests={
            "toolchain": "4" * 64,
            "runtime": "5" * 64,
            "security_profile": "6" * 64,
        },
        closure_documents={"runtime": {"sha1dc_oracle": sha1dc_binding}},
    )
    image_record = {
        "role": "object_parser",
        "manifest_digest": inspection.manifest_digest,
        "config_digest": inspection.config_digest,
        "toolchain_digest": inspection.closure_digests["toolchain"],
        "runtime_digest": inspection.closure_digests["runtime"],
        "security_profile_digest": inspection.closure_digests["security_profile"],
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
    }
    host_sha1dc = {
        "schema": "galaxy.sha1dc-standalone-evidence/v1",
        "executable_path": str(controller / "galaxy-sha1dc.exe"),
        "executable_sha256": "7" * 64,
        "executable_link_count": 1,
        "runtime_attestation_digest": "8" * 64,
        "build_evidence_path": str(
            generation / "build-evidence" / "sha1dc-build-evidence.json"
        ),
        "build_evidence_sha256": "9" * 64,
        "source_revision": "855827c583bc30645ba427885caa40c5b81764d2",
        "protocol": "galaxy.sha1dc-object-oracle/v1",
        "collision_detection": "SHA1_DC",
        "network_allowed": False,
    }

    payload = mod._kernel_artifact_qualification_payload(
        runtime=runtime,
        controller_source_revision="a" * 40,
        issued_at="2026-07-16T18:00:00Z",
        expires_at="2026-07-17T18:00:00Z",
        revocation_generation=3,
        docker_server_identity_digest="b" * 64,
        object_parser_record=image_record,
        object_parser_archive=archive,
        inspection=inspection,
        host_sha1dc=host_sha1dc,
    )

    assert payload["status"] == "qualified_staging_only"
    assert payload["authority_ceiling"] == "staging_only"
    assert "activation" not in payload
    assert payload["writer"] == {
        "source_path": str(writer_source),
        "source_sha256": runtime.git_object_writer_source_digest,
        "version_digest": runtime.git_object_writer_source_digest,
        "host_sha1dc": host_sha1dc,
    }
    identity = dict(payload)
    qualification_id = identity.pop("qualification_id")
    assert qualification_id == hashlib.sha256(_canonical_json(identity)).hexdigest()


def test_kernel_artifact_qualification_is_signed_durable_and_idempotent(
    tmp_path, monkeypatch
):
    mod = importlib.import_module("bootstrap.galaxy_launcher.activation_harness")
    external_root = tmp_path / "installed"
    generation_root = external_root / "generations" / "00000007"
    controller = generation_root / "controller"
    controller.mkdir(parents=True)
    runtime_lock = controller / "runtime.lock.json"
    runtime_lock.write_bytes(b"sealed-runtime-lock")
    runtime = SimpleNamespace(
        external_root=external_root,
        generation=7,
        runtime_lock_path=runtime_lock,
    )
    seed = bytes(range(32))
    payload = {
        "schema": "galaxy.kernel-artifact-qualification/v1",
        "status": "qualified_staging_only",
        "authority_ceiling": "staging_only",
        "qualification_id": "",
    }
    identity = dict(payload)
    identity.pop("qualification_id")
    payload["qualification_id"] = hashlib.sha256(_canonical_json(identity)).hexdigest()
    monkeypatch.setattr(mod, "load_sealed_acceptance", lambda: object())
    monkeypatch.setattr(
        mod, "resolve_sealed_harness_runtime", lambda _acceptance: runtime
    )
    monkeypatch.setattr(mod, "_receipt_seed", lambda _runtime: seed)
    monkeypatch.setattr(
        mod,
        "_load_kernel_artifact_inputs",
        lambda _runtime: (object(), tmp_path / "object-parser.oci.tar", object()),
        raising=False,
    )
    monkeypatch.setattr(
        mod,
        "_docker_server_identity_digest",
        lambda _runtime: "b" * 64,
        raising=False,
    )
    monkeypatch.setattr(
        mod,
        "_attest_standalone_sha1dc",
        lambda _runtime: {"schema": "galaxy.sha1dc-standalone-evidence/v1"},
        raising=False,
    )
    monkeypatch.setattr(
        mod,
        "_kernel_artifact_qualification_payload",
        lambda **_kwargs: dict(payload),
    )

    pointer = mod.issueKernelArtifactQualification(
        controller_source_revision="c" * 40,
        issued_at="2026-07-16T18:00:00Z",
        expires_at="2026-07-17T18:00:00Z",
        revocation_generation=3,
    )
    pointer_path = external_root / "kernel-artifacts.current.json"
    qualification_path = Path(pointer["qualification_path"])
    before = (pointer_path.read_bytes(), qualification_path.read_bytes())
    receipt = json.loads(before[1])

    assert json.loads(before[0]) == pointer
    assert receipt["signed_payload"] == payload
    signature = base64.urlsafe_b64decode(receipt["signature_base64url"] + "==")
    assert mod._crypto_module().verify(
        mod._crypto_module().public_key_from_seed(seed),
        _canonical_json(payload),
        signature,
    )
    assert pointer["status"] == "qualified_staging_only"
    assert pointer["qualification_sha256"] == hashlib.sha256(before[1]).hexdigest()

    assert mod.issueKernelArtifactQualification(
        controller_source_revision="c" * 40,
        issued_at="2026-07-16T18:00:00Z",
        expires_at="2026-07-17T18:00:00Z",
        revocation_generation=3,
    ) == pointer
    assert (pointer_path.read_bytes(), qualification_path.read_bytes()) == before


def test_installed_harness_attests_sha1dc_through_the_sealed_runtime_source(
    tmp_path, monkeypatch
):
    mod = importlib.import_module("bootstrap.galaxy_launcher.activation_harness")
    source = tmp_path / "controller" / "sha1dc.py"
    executable = tmp_path / "controller" / "galaxy-sha1dc.exe"
    build_evidence = tmp_path / "build-evidence" / "sha1dc-build-evidence.json"
    source.parent.mkdir(parents=True)
    build_evidence.parent.mkdir()
    source.write_bytes(b"sealed sha1dc module")
    executable.write_bytes(b"sealed sha1dc executable")
    build_evidence.write_bytes(b"sealed build evidence")
    runtime = SimpleNamespace(
        sha1dc_runtime_source_path=source,
        sha1dc_runtime_source_digest=hashlib.sha256(source.read_bytes()).hexdigest(),
        sha1dc_oracle_path=executable,
        sha1dc_oracle_digest=hashlib.sha256(executable.read_bytes()).hexdigest(),
        sha1dc_build_evidence_path=build_evidence,
        sha1dc_build_evidence_digest=hashlib.sha256(
            build_evidence.read_bytes()
        ).hexdigest(),
    )
    expected = {
        "schema": "galaxy.sha1dc-standalone-evidence/v1",
        "executable_path": str(executable),
        "executable_sha256": runtime.sha1dc_oracle_digest,
        "executable_link_count": 1,
        "runtime_attestation_digest": "1" * 64,
        "build_evidence_path": str(build_evidence),
        "build_evidence_sha256": runtime.sha1dc_build_evidence_digest,
        "source_revision": "855827c583bc30645ba427885caa40c5b81764d2",
        "protocol": "galaxy.sha1dc-object-oracle/v1",
        "collision_detection": "SHA1_DC",
        "network_allowed": False,
    }
    calls: list[dict[str, object]] = []

    class Oracle:
        def revalidate(self):
            calls.append({"revalidated": True})

    class Evidence:
        def toDict(self):
            return dict(expected)

    class SealedModule:
        @staticmethod
        def qualifyStandaloneSha1dc(**kwargs):
            calls.append(kwargs)
            return Evidence(), Oracle()

    monkeypatch.setattr(
        mod,
        "_load_adjacent_module",
        lambda name, path: (
            calls.append({"module": name, "path": path}) or SealedModule
        ),
    )

    assert mod._attest_standalone_sha1dc(runtime) == expected
    assert calls[1]["executable"] == executable
    assert calls[1]["build_evidence"] == build_evidence
    assert calls[2] == {"revalidated": True}


class _JobBasicLimits(ctypes.Structure):
    _fields_ = [
        ("per_process_time", ctypes.c_longlong),
        ("per_job_time", ctypes.c_longlong),
        ("limit_flags", wintypes.DWORD),
        ("minimum_working_set", ctypes.c_size_t),
        ("maximum_working_set", ctypes.c_size_t),
        ("active_process_limit", wintypes.DWORD),
        ("affinity", ctypes.c_size_t),
        ("priority_class", wintypes.DWORD),
        ("scheduling_class", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("read_operations", ctypes.c_ulonglong),
        ("write_operations", ctypes.c_ulonglong),
        ("other_operations", ctypes.c_ulonglong),
        ("read_bytes", ctypes.c_ulonglong),
        ("write_bytes", ctypes.c_ulonglong),
        ("other_bytes", ctypes.c_ulonglong),
    ]


class _ExtendedJobLimits(ctypes.Structure):
    _fields_ = [
        ("basic", _JobBasicLimits),
        ("io", _IoCounters),
        ("process_memory", ctypes.c_size_t),
        ("job_memory", ctypes.c_size_t),
        ("peak_process_memory", ctypes.c_size_t),
        ("peak_job_memory", ctypes.c_size_t),
    ]


class KillOnCloseJob:
    """Parent-owned non-breakaway process boundary for the harness tree."""

    def __init__(self):
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        )
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.IsProcessInJob.argtypes = (
            wintypes.HANDLE,
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.BOOL),
        )
        kernel32.IsProcessInJob.restype = wintypes.BOOL
        kernel32.OpenThread.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenThread.restype = wintypes.HANDLE
        kernel32.ResumeThread.argtypes = (wintypes.HANDLE,)
        kernel32.ResumeThread.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        self._kernel32 = kernel32
        self.handle: int | None = kernel32.CreateJobObjectW(None, None)
        assert self.handle
        limits = _ExtendedJobLimits()
        limits.basic.limit_flags = 0x00002000 | 0x00000400
        ok = kernel32.SetInformationJobObject(
            self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        )
        assert ok, ctypes.get_last_error()

    def assign(self, process: subprocess.Popen[str]) -> None:
        process_handle = self._kernel32.OpenProcess(0x0100 | 0x0001, False, process.pid)
        assert process_handle, ctypes.get_last_error()
        try:
            ok = self._kernel32.AssignProcessToJobObject(self.handle, process_handle)
            assert ok, ctypes.get_last_error()
        finally:
            self._kernel32.CloseHandle(process_handle)

    def resume_suspended(self, process: subprocess.Popen[str]) -> None:
        threads = psutil.Process(process.pid).threads()
        assert len(threads) == 1
        thread_handle = self._kernel32.OpenThread(0x0002, False, threads[0].id)
        assert thread_handle, ctypes.get_last_error()
        try:
            previous_count = self._kernel32.ResumeThread(thread_handle)
            assert previous_count == 1, ctypes.get_last_error()
        finally:
            self._kernel32.CloseHandle(thread_handle)

    def contains(self, process_id: int) -> bool:
        process_handle = self._kernel32.OpenProcess(0x1000, False, process_id)
        assert process_handle, ctypes.get_last_error()
        try:
            result = wintypes.BOOL()
            ok = self._kernel32.IsProcessInJob(
                process_handle, self.handle, ctypes.byref(result)
            )
            assert ok, ctypes.get_last_error()
            return bool(result.value)
        finally:
            self._kernel32.CloseHandle(process_handle)

    def close(self) -> None:
        if self.handle:
            self._kernel32.CloseHandle(self.handle)
            self.handle = None


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "superpowers"
    / "plans"
    / "2026-07-13-galaxy-r3-transactional-kernel.md"
)
PINNED_REQUIREMENTS_DIGEST = (
    "5266e7a77718e30db79b06f30e609fa104e2f6282267ca6c860ecc7e08a85b47"
)

# This pins the canonical executable ledger bytes, including every explicit
# precondition, argument, fault, broker result, outcome, receipt field, and
# security probe.  Requirement prose is never expanded heuristically.
ACCEPTANCE_PATH = (
    REPOSITORY_ROOT
    / "bootstrap"
    / "galaxy_launcher"
    / "activation_acceptance.json"
)
PINNED_ACCEPTANCE_LEDGER_DIGEST = (
    "5c8f7ce7d1b6a6f95167d778e170eeaee020a6486f83a1dd16f78fdba597cbc5"
)
RUNTIME_PROFILE_LEDGER_PATH = ACCEPTANCE_PATH.with_name(
    "activation_runtime_profiles.json"
)
PINNED_RUNTIME_PROFILE_LEDGER_DIGEST = (
    "180574de31f4269eb2c0fee3738b1cc622c15a099c84a49f764289d4621ecce0"
)

_SECTIONS = (
    (
        "T1",
        "### Step 1: Add failing contract tests",
        "### Step 2: Implement the dataclasses",
    ),
    (
        "T2",
        "### Step 1: Add real-repository failing tests",
        "### Step 2: Define lease and receipt types",
    ),
    (
        "T3",
        "### Step 1: Add ordering and state-truth tests",
        "### Step 2: Resolve once",
    ),
    (
        "T4A",
        "### Step 1: Add parallel-chain failing tests",
        "### Step 2: Migrate outer parallel finalization",
    ),
    (
        "T4B",
        "### Step 4: Add solution-space environment-preservation tests",
        "### Step 5: Migrate solution-space branch contracts",
    ),
)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_signed_record(record: dict[str, Any], public_key_hex: str) -> None:
    assert set(record) == {"signed_payload", "signature_base64url"}
    signature_text = record["signature_base64url"]
    assert "=" not in signature_text
    signature = base64.urlsafe_b64decode(
        signature_text + "=" * (-len(signature_text) % 4)
    )
    try:
        public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        public_key.verify(signature, _canonical_json(record["signed_payload"]))
    except (InvalidSignature, ValueError) as error:
        raise AssertionError("receipt signature did not verify") from error


def _assert_signed_report(raw_report: dict[str, Any], public_key_hex: str) -> None:
    for collection in ("subcase_results", "probe_results"):
        for record in raw_report[collection]:
            _verify_signed_record(record["receipt"], public_key_hex)


def _extract_numbered_requirements() -> tuple[tuple[str, int, str], ...]:
    text = PLAN_PATH.read_text(encoding="utf-8")
    extracted: list[tuple[str, int, str]] = []
    for label, start_heading, end_heading in _SECTIONS:
        assert text.count(start_heading) == 1, start_heading
        section = text.split(start_heading, 1)[1].split(end_heading, 1)[0]
        # Each approved invariant is one physical Markdown list line.  Reading
        # only that line prevents the final item swallowing Run/prose blocks.
        for number, body in re.findall(r"(?m)^(\d+)\.\s+([^\r\n]+)$", section):
            extracted.append((label, int(number), body.strip()))
    counts = tuple(
        sum(label == expected_label for label, _, _ in extracted)
        for expected_label, _, _ in _SECTIONS
    )
    assert counts == (31, 74, 66, 14, 7)
    assert hashlib.sha256(_canonical_json(extracted)).hexdigest() == (
        PINNED_REQUIREMENTS_DIGEST
    )
    return tuple(extracted)


@dataclasses.dataclass(frozen=True)
class StepSpec:
    step: str
    args: dict[str, Any]

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical_json(dataclasses.asdict(self))).hexdigest()


@dataclasses.dataclass(frozen=True)
class OperationSpec:
    api: str
    args: dict[str, Any]

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical_json(dataclasses.asdict(self))).hexdigest()


@dataclasses.dataclass(frozen=True)
class BrokerCallSpec:
    operation: str
    args: dict[str, Any]
    expected_result: Any

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical_json(dataclasses.asdict(self))).hexdigest()


@dataclasses.dataclass(frozen=True)
class FaultSpec:
    edge: str
    kind: str
    args: dict[str, Any]

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical_json(dataclasses.asdict(self))).hexdigest()


@dataclasses.dataclass(frozen=True)
class ExpectedOutcomeSpec:
    status: str
    state: Any
    forbidden_effects: tuple[str, ...]

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical_json(dataclasses.asdict(self))).hexdigest()


@dataclasses.dataclass(frozen=True)
class SubcaseSpec:
    invariant_id: str
    subcase_id: str
    fault: FaultSpec
    broker_calls: tuple[BrokerCallSpec, ...]
    expected: ExpectedOutcomeSpec
    source_digest: str

    @property
    def observation_id(self) -> str:
        return f"{self.invariant_id}.subcase.{self.subcase_id}"

    @property
    def executable_digest(self) -> str:
        return self.source_digest


@dataclasses.dataclass(frozen=True)
class ProbeSpec:
    invariant_id: str
    probe_id: str
    runtime_role: str
    broker_operations: tuple[BrokerCallSpec, ...]
    expected_enforcement: str
    source_digest: str

    @property
    def observation_id(self) -> str:
        return self.probe_id

    @property
    def executable_digest(self) -> str:
        return self.source_digest


@dataclasses.dataclass(frozen=True)
class ReceiptSpec:
    type: str
    required_fields: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class RuntimeProfileSpec:
    profile_id: str
    execution_kind: str
    image_role: str | None
    identity_class: str
    network_mode: str
    credential_mode: str
    filesystem_mode: str
    process_mode: str
    state_store_mode: str
    required_attestations: tuple[str, ...]

    @property
    def profile_digest(self) -> str:
        return hashlib.sha256(_canonical_json(dataclasses.asdict(self))).hexdigest()


@dataclasses.dataclass(frozen=True)
class ScenarioSpec:
    task: int
    family: str
    invariant_id: str
    requirement_digest: str
    preconditions: tuple[StepSpec, ...]
    operation: OperationSpec
    subcases: tuple[SubcaseSpec, ...]
    probes: tuple[ProbeSpec, ...]
    required_receipts: tuple[ReceiptSpec, ...]
    source_digest: str

    @property
    def key(self) -> tuple[int, str, str]:
        return self.task, self.invariant_id, self.source_digest

    @property
    def executable_digest(self) -> str:
        return self.source_digest


_TOP_LEVEL_KEYS = frozenset(
    {
        "invariant_id",
        "requirement_sha256",
        "preconditions",
        "operation",
        "subcases",
        "required_receipts",
        "security_probes",
    }
)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_non_integral_number(value: str) -> Any:
    raise ValueError(f"non-integral JSON number or constant: {value}")


def _parse_bounded_int(value: str) -> int:
    parsed = int(value)
    if not -(2**63) <= parsed < 2**63:
        raise ValueError("JSON integer is outside the signed 64-bit boundary")
    return parsed


def _strict_json_bytes(raw: bytes) -> Any:
    return json.loads(
        raw.decode("utf-8", errors="strict"),
        object_pairs_hook=_reject_duplicate_keys,
        parse_float=_reject_non_integral_number,
        parse_int=_parse_bounded_int,
        parse_constant=_reject_non_integral_number,
    )


def _exact_keys(
    value: dict[str, Any], expected: set[str] | frozenset[str], at: str
) -> None:
    if not isinstance(value, dict) or set(value) != set(expected):
        raise AssertionError(f"{at}: expected exact keys {sorted(expected)}")


def _nonempty_text(value: Any, at: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise AssertionError(f"{at}: expected non-empty NUL-free text")
    return value


def _json_object(value: Any, at: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AssertionError(f"{at}: expected JSON object")
    return value


def _broker_call(value: dict[str, Any], at: str) -> BrokerCallSpec:
    _exact_keys(value, {"operation", "args", "expected_result"}, at)
    return BrokerCallSpec(
        operation=_nonempty_text(value["operation"], f"{at}.operation"),
        args=_json_object(value["args"], f"{at}.args"),
        expected_result=value["expected_result"],
    )


def _build_scenarios_from_closed_ledger(path: Path) -> tuple[ScenarioSpec, ...]:
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == PINNED_ACCEPTANCE_LEDGER_DIGEST
    records = _strict_json_bytes(raw)
    assert isinstance(records, list) and len(records) == 192
    assert raw == _canonical_json(records), "acceptance ledger is not canonical JSON"
    requirement_bodies = {
        f"{label}-{number:02d}": body
        for label, number, body in _extract_numbered_requirements()
    }
    scenarios: list[ScenarioSpec] = []
    invariant_ids: set[str] = set()
    subcase_ids: set[str] = set()
    probe_ids: set[str] = set()
    for record_index, record in enumerate(records):
        at = f"records[{record_index}]"
        _exact_keys(record, _TOP_LEVEL_KEYS, at)
        invariant_id = _nonempty_text(record["invariant_id"], f"{at}.invariant_id")
        assert invariant_id in requirement_bodies, f"{at}: unknown invariant {invariant_id}"
        assert invariant_id not in invariant_ids, f"duplicate invariant {invariant_id}"
        invariant_ids.add(invariant_id)
        family = invariant_id.split("-", 1)[0]
        task = int(family[1])
        requirement_digest = hashlib.sha256(
            requirement_bodies[invariant_id].encode("utf-8")
        ).hexdigest()
        assert record["requirement_sha256"] == requirement_digest

        assert isinstance(record["preconditions"], list) and record["preconditions"]
        preconditions = []
        for index, value in enumerate(record["preconditions"]):
            where = f"{at}.preconditions[{index}]"
            _exact_keys(value, {"step", "args"}, where)
            preconditions.append(
                StepSpec(
                    step=_nonempty_text(value["step"], f"{where}.step"),
                    args=_json_object(value["args"], f"{where}.args"),
                )
            )

        operation_value = record["operation"]
        _exact_keys(operation_value, {"api", "args"}, f"{at}.operation")
        operation = OperationSpec(
            api=_nonempty_text(operation_value["api"], f"{at}.operation.api"),
            args=_json_object(operation_value["args"], f"{at}.operation.args"),
        )

        assert isinstance(record["subcases"], list) and record["subcases"]
        subcases = []
        for index, value in enumerate(record["subcases"]):
            where = f"{at}.subcases[{index}]"
            _exact_keys(value, {"id", "fault", "broker_calls", "expected"}, where)
            subcase_id = _nonempty_text(value["id"], f"{where}.id")
            assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,191}", subcase_id)
            assert subcase_id not in subcase_ids, f"duplicate subcase ID {subcase_id}"
            subcase_ids.add(subcase_id)
            fault_value = value["fault"]
            _exact_keys(fault_value, {"edge", "kind", "args"}, f"{where}.fault")
            fault = FaultSpec(
                edge=_nonempty_text(fault_value["edge"], f"{where}.fault.edge"),
                kind=_nonempty_text(fault_value["kind"], f"{where}.fault.kind"),
                args=_json_object(fault_value["args"], f"{where}.fault.args"),
            )
            assert isinstance(value["broker_calls"], list) and value["broker_calls"]
            calls = tuple(
                _broker_call(call, f"{where}.broker_calls[{call_index}]")
                for call_index, call in enumerate(value["broker_calls"])
            )
            expected_value = value["expected"]
            _exact_keys(
                expected_value,
                {"status", "state", "forbidden_effects"},
                f"{where}.expected",
            )
            assert expected_value["state"] is not None
            assert isinstance(expected_value["forbidden_effects"], list)
            forbidden = tuple(
                _nonempty_text(item, f"{where}.expected.forbidden_effects")
                for item in expected_value["forbidden_effects"]
            )
            assert len(forbidden) == len(set(forbidden))
            expected = ExpectedOutcomeSpec(
                status=_nonempty_text(
                    expected_value["status"], f"{where}.expected.status"
                ),
                state=expected_value["state"],
                forbidden_effects=forbidden,
            )
            subcases.append(
                SubcaseSpec(
                    invariant_id=invariant_id,
                    subcase_id=subcase_id,
                    fault=fault,
                    broker_calls=calls,
                    expected=expected,
                    source_digest=hashlib.sha256(_canonical_json(value)).hexdigest(),
                )
            )

        assert isinstance(record["required_receipts"], list) and record[
            "required_receipts"
        ]
        receipts = []
        receipt_types: set[str] = set()
        for index, value in enumerate(record["required_receipts"]):
            where = f"{at}.required_receipts[{index}]"
            _exact_keys(value, {"type", "required_fields"}, where)
            receipt_type = _nonempty_text(value["type"], f"{where}.type")
            assert receipt_type not in receipt_types
            receipt_types.add(receipt_type)
            assert isinstance(value["required_fields"], list) and value[
                "required_fields"
            ]
            required_fields = tuple(
                _nonempty_text(item, f"{where}.required_fields")
                for item in value["required_fields"]
            )
            assert len(required_fields) == len(set(required_fields))
            receipts.append(ReceiptSpec(receipt_type, required_fields))

        assert isinstance(record["security_probes"], list) and record[
            "security_probes"
        ]
        probes = []
        for index, value in enumerate(record["security_probes"]):
            where = f"{at}.security_probes[{index}]"
            _exact_keys(
                value,
                {"runtime_role", "broker_operations", "expected_enforcement"},
                where,
            )
            assert isinstance(value["broker_operations"], list) and value[
                "broker_operations"
            ]
            source_digest = hashlib.sha256(_canonical_json(value)).hexdigest()
            probe_id = f"{invariant_id}.probe.{index + 1:02d}.{source_digest[:16]}"
            assert probe_id not in probe_ids
            probe_ids.add(probe_id)
            probes.append(
                ProbeSpec(
                    invariant_id=invariant_id,
                    probe_id=probe_id,
                    runtime_role=_nonempty_text(
                        value["runtime_role"], f"{where}.runtime_role"
                    ),
                    broker_operations=tuple(
                        _broker_call(call, f"{where}.broker_operations[{call_index}]")
                        for call_index, call in enumerate(value["broker_operations"])
                    ),
                    expected_enforcement=_nonempty_text(
                        value["expected_enforcement"],
                        f"{where}.expected_enforcement",
                    ),
                    source_digest=source_digest,
                )
            )

        scenarios.append(
            ScenarioSpec(
                task=task,
                family=family,
                invariant_id=invariant_id,
                requirement_digest=requirement_digest,
                preconditions=tuple(preconditions),
                operation=operation,
                subcases=tuple(subcases),
                probes=tuple(probes),
                required_receipts=tuple(receipts),
                source_digest=hashlib.sha256(_canonical_json(record)).hexdigest(),
            )
        )
    assert len(scenarios) == 192
    assert len(subcase_ids) == 5230
    assert len(probe_ids) == 552
    assert len({scenario.key for scenario in scenarios}) == 192
    return tuple(scenarios)


SCENARIOS = _build_scenarios_from_closed_ledger(ACCEPTANCE_PATH)
SCENARIO_BY_ID = {scenario.invariant_id: scenario for scenario in SCENARIOS}
PROBE_BY_ID = {
    probe.probe_id: (scenario, probe)
    for scenario in SCENARIOS
    for probe in scenario.probes
}
SUBCASE_BY_ID = {
    subcase.subcase_id: (scenario, subcase)
    for scenario in SCENARIOS
    for subcase in scenario.subcases
}
EXPECTED_CASES = frozenset(
    (scenario.task, scenario.invariant_id, subcase.subcase_id)
    for scenario in SCENARIOS
    for subcase in scenario.subcases
)
EXECUTABLE_MATRIX_DIGEST = PINNED_ACCEPTANCE_LEDGER_DIGEST


def _load_runtime_profile_ledger(
    path: Path,
) -> tuple[dict[str, RuntimeProfileSpec], dict[str, str]]:
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == PINNED_RUNTIME_PROFILE_LEDGER_DIGEST
    value = _strict_json_bytes(raw)
    assert raw == _canonical_json(value), "runtime profile ledger is not canonical JSON"
    _exact_keys(
        value,
        {"schema", "acceptance_sha256", "profiles", "role_assignments"},
        "runtime_profile_ledger",
    )
    assert value["schema"] == "galaxy.activation.runtime-profile-ledger/v1"
    assert value["acceptance_sha256"] == PINNED_ACCEPTANCE_LEDGER_DIGEST
    assert isinstance(value["profiles"], list) and value["profiles"]
    profiles: dict[str, RuntimeProfileSpec] = {}
    profile_keys = {
        "profile_id",
        "execution_kind",
        "image_role",
        "identity_class",
        "network_mode",
        "credential_mode",
        "filesystem_mode",
        "process_mode",
        "state_store_mode",
        "required_attestations",
    }
    for index, record in enumerate(value["profiles"]):
        at = f"runtime_profile_ledger.profiles[{index}]"
        _exact_keys(record, profile_keys, at)
        profile_id = _nonempty_text(record["profile_id"], f"{at}.profile_id")
        assert profile_id not in profiles
        assert record["execution_kind"] in {
            "restricted_os_process",
            "hardened_container",
        }
        image_role = record["image_role"]
        if record["execution_kind"] == "hardened_container":
            _nonempty_text(image_role, f"{at}.image_role")
        else:
            assert image_role is None
        assert isinstance(record["required_attestations"], list) and record[
            "required_attestations"
        ]
        attestations = tuple(
            _nonempty_text(item, f"{at}.required_attestations")
            for item in record["required_attestations"]
        )
        assert len(attestations) == len(set(attestations))
        profiles[profile_id] = RuntimeProfileSpec(
            profile_id=profile_id,
            execution_kind=record["execution_kind"],
            image_role=image_role,
            identity_class=_nonempty_text(
                record["identity_class"], f"{at}.identity_class"
            ),
            network_mode=_nonempty_text(record["network_mode"], f"{at}.network_mode"),
            credential_mode=_nonempty_text(
                record["credential_mode"], f"{at}.credential_mode"
            ),
            filesystem_mode=_nonempty_text(
                record["filesystem_mode"], f"{at}.filesystem_mode"
            ),
            process_mode=_nonempty_text(record["process_mode"], f"{at}.process_mode"),
            state_store_mode=_nonempty_text(
                record["state_store_mode"], f"{at}.state_store_mode"
            ),
            required_attestations=attestations,
        )
    assert len(profiles) == 11
    assignments = value["role_assignments"]
    assert isinstance(assignments, dict)
    expected_roles = {
        probe.runtime_role for scenario in SCENARIOS for probe in scenario.probes
    }
    assert set(assignments) == expected_roles
    assert len(assignments) == 498
    for role, profile_id in assignments.items():
        _nonempty_text(role, "runtime_profile_ledger.role")
        assert profile_id in profiles
    return profiles, assignments


RUNTIME_PROFILES, ROLE_PROFILE_ASSIGNMENTS = _load_runtime_profile_ledger(
    RUNTIME_PROFILE_LEDGER_PATH
)
PROBE_PROFILE_BY_ID = {
    probe.probe_id: RUNTIME_PROFILES[ROLE_PROFILE_ASSIGNMENTS[probe.runtime_role]]
    for scenario in SCENARIOS
    for probe in scenario.probes
}
OBSERVATION_BY_ID: dict[str, tuple[str, ScenarioSpec, SubcaseSpec | ProbeSpec]] = {}
for _scenario in SCENARIOS:
    for _subcase in _scenario.subcases:
        OBSERVATION_BY_ID[_subcase.observation_id] = (
            "subcase",
            _scenario,
            _subcase,
        )
    for _probe in _scenario.probes:
        OBSERVATION_BY_ID[_probe.observation_id] = (
            "security_probe",
            _scenario,
            _probe,
        )
assert len(OBSERVATION_BY_ID) == 5230 + 552


def _observation_calls(observation: SubcaseSpec | ProbeSpec) -> tuple[BrokerCallSpec, ...]:
    if isinstance(observation, SubcaseSpec):
        return observation.broker_calls
    return observation.broker_operations


def _expected_observed_outcome(
    kind: str, observation: SubcaseSpec | ProbeSpec
) -> dict[str, Any]:
    if kind == "subcase":
        assert isinstance(observation, SubcaseSpec)
        return {
            "status": observation.expected.status,
            "state": observation.expected.state,
            "forbidden_effects_observed": [],
        }
    assert isinstance(observation, ProbeSpec)
    return {
        "expected_enforcement": observation.expected_enforcement,
        "enforced": True,
        "forbidden_effects_observed": [],
    }


class IndependentCapabilityBroker:
    """Parent-owned authority: every active attempt must cross this boundary."""

    def __init__(self, root: Path, *, run_nonce: str):
        self.run_nonce = run_nonce
        self.challenge_digest = ""
        self.hmac_key = secrets.token_bytes(32)
        self.root = root / "capability-broker"
        self.root.mkdir()
        self.expected = OBSERVATION_BY_ID
        request_root = self.root / "requests"
        response_root = self.root / "responses"
        request_root.mkdir()
        response_root.mkdir()
        self.channels = {
            "request_root": request_root,
            "response_root": response_root,
        }
        self.tokens: dict[str, str] = {}
        self.runtime_identities: dict[str, str] = {}
        self.case_runtime_identity = ""
        self.violations: list[str] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._seen_requests: set[Path] = set()
        self.database_path = self.root / "broker-evidence.sqlite3"
        self.database = sqlite3.connect(self.database_path, check_same_thread=False)
        self.database.execute("PRAGMA journal_mode=WAL")
        self.database.execute("PRAGMA synchronous=FULL")
        self.database.execute(
            "CREATE TABLE observations ("
            "observation_id TEXT PRIMARY KEY, observation_kind TEXT NOT NULL, "
            "invariant_id TEXT NOT NULL, observation_digest TEXT NOT NULL, "
            "preconditions_json BLOB NOT NULL, operation_json BLOB NOT NULL, "
            "fault_json BLOB, runtime_role TEXT NOT NULL, "
            "runtime_profile_id TEXT NOT NULL, runtime_profile_digest TEXT NOT NULL, "
            "calls_json BLOB NOT NULL, "
            "expected_outcome_json BLOB NOT NULL, state TEXT NOT NULL) WITHOUT ROWID"
        )
        self.database.execute(
            "CREATE TABLE evidence ("
            "run_nonce TEXT NOT NULL, observation_id TEXT NOT NULL, "
            "sequence INTEGER NOT NULL, request_digest TEXT NOT NULL, "
            "event_json BLOB NOT NULL, response_json BLOB NOT NULL, "
            "event_hmac TEXT NOT NULL, "
            "PRIMARY KEY (run_nonce, observation_id, sequence)) WITHOUT ROWID"
        )
        self.database.execute(
            "CREATE TABLE completions ("
            "run_nonce TEXT NOT NULL, observation_id TEXT NOT NULL, "
            "request_digest TEXT NOT NULL, event_json BLOB NOT NULL, "
            "response_json BLOB NOT NULL, event_hmac TEXT NOT NULL, "
            "PRIMARY KEY (run_nonce, observation_id)) WITHOUT ROWID"
        )
        for observation_id, (kind, scenario, observation) in self.expected.items():
            calls = _observation_calls(observation)
            if isinstance(observation, ProbeSpec):
                runtime_role = observation.runtime_role
                profile = PROBE_PROFILE_BY_ID[observation.probe_id]
                fault_json = None
            else:
                runtime_role = "activation_case_adapter"
                profile = RUNTIME_PROFILES["controller_restricted_win32"]
                fault_json = _canonical_json(dataclasses.asdict(observation.fault))
            self.database.execute(
                "INSERT INTO observations VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'prepared')",
                (
                    observation_id,
                    kind,
                    scenario.invariant_id,
                    observation.executable_digest,
                    _canonical_json(
                        [dataclasses.asdict(item) for item in scenario.preconditions]
                    ),
                    _canonical_json(dataclasses.asdict(scenario.operation)),
                    fault_json,
                    runtime_role,
                    profile.profile_id,
                    profile.profile_digest,
                    _canonical_json([dataclasses.asdict(call) for call in calls]),
                    _canonical_json(_expected_observed_outcome(kind, observation)),
                ),
            )
        self.database.commit()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def bind_challenge(self, challenge_digest: str) -> None:
        assert re.fullmatch(r"[0-9a-f]{64}", challenge_digest)
        assert not self.challenge_digest
        self.challenge_digest = challenge_digest

    def authorize(self, probe_id: str, token: str) -> None:
        assert probe_id in PROBE_BY_ID
        assert probe_id not in self.tokens
        self.tokens[probe_id] = token

    def bind_case_runtime(self, process_id: int) -> None:
        assert not self.case_runtime_identity
        assert process_id > 0
        self.case_runtime_identity = f"win32-pid:{process_id}"

    def bind_probe_runtime(self, probe_id: str, runtime_identity: str) -> None:
        assert probe_id in PROBE_BY_ID
        assert probe_id not in self.runtime_identities
        profile = PROBE_PROFILE_BY_ID[probe_id]
        if profile.execution_kind == "hardened_container":
            assert re.fullmatch(r"container:[0-9a-f]{12,64}", runtime_identity)
        else:
            assert re.fullmatch(r"win32-pid:[1-9][0-9]{0,9}", runtime_identity)
        self.runtime_identities[probe_id] = runtime_identity

    @staticmethod
    def _idempotency_key(
        run_nonce: str, observation_id: str, sequence: int, call_digest: str
    ) -> str:
        return hashlib.sha256(
            _canonical_json(
                {
                    "call_digest": call_digest,
                    "observation_id": observation_id,
                    "run_nonce": run_nonce,
                    "sequence": sequence,
                }
            )
        ).hexdigest()

    def _serve(self) -> None:
        while not self._stop.is_set():
            for request_path in self.channels["request_root"].glob("*.request.json"):
                if request_path in self._seen_requests:
                    continue
                self._seen_requests.add(request_path)
                try:
                    request = _strict_json_bytes(request_path.read_bytes())
                    response = self.accept_request(request)
                except Exception as error:  # pragma: no cover - child sees refusal
                    response = {"status": "refused", "error": type(error).__name__}
                response_path = self.channels["response_root"] / request_path.name.replace(
                    ".request.json", ".response.json"
                )
                response_path.write_bytes(_canonical_json(response))
            self._stop.wait(0.005)

    def _refusal(self, *reasons: str) -> dict[str, Any]:
        ordered = sorted(set(reasons))
        self.violations.extend(ordered)
        return {"status": "refused", "reason": ordered}

    def _runtime_binding(
        self,
        kind: str,
        observation: SubcaseSpec | ProbeSpec,
    ) -> tuple[str, RuntimeProfileSpec, str, str]:
        if kind == "security_probe":
            assert isinstance(observation, ProbeSpec)
            return (
                observation.runtime_role,
                PROBE_PROFILE_BY_ID[observation.probe_id],
                self.runtime_identities.get(observation.probe_id, ""),
                self.tokens.get(observation.probe_id, ""),
            )
        return (
            "activation_case_adapter",
            RUNTIME_PROFILES["controller_restricted_win32"],
            self.case_runtime_identity,
            "",
        )

    def accept_request(self, request: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if not isinstance(request, dict):
                return self._refusal("request_not_object")
            message_type = request.get("message_type")
            if message_type == "call":
                return self._accept_call(request)
            if message_type == "complete":
                return self._accept_completion(request)
            return self._refusal("unknown_message_type")

    def _common_checks(
        self,
        request: dict[str, Any],
        *,
        kind: str,
        scenario: ScenarioSpec,
        observation: SubcaseSpec | ProbeSpec,
    ) -> dict[str, bool]:
        role, profile, runtime_identity, release_token = self._runtime_binding(
            kind, observation
        )
        preconditions_digest = hashlib.sha256(
            _canonical_json([dataclasses.asdict(item) for item in scenario.preconditions])
        ).hexdigest()
        fault_digest = (
            observation.fault.digest if isinstance(observation, SubcaseSpec) else None
        )
        return {
            "schema": request.get("schema") == 2,
            "run_nonce": request.get("run_nonce") == self.run_nonce,
            "challenge": request.get("challenge_digest") == self.challenge_digest,
            "kind": request.get("observation_kind") == kind,
            "invariant": request.get("invariant_id") == scenario.invariant_id,
            "observation_digest": request.get("observation_digest")
            == observation.executable_digest,
            "case_digest": request.get("case_digest") == scenario.executable_digest,
            "operation_api": request.get("operation_api") == scenario.operation.api,
            "operation_digest": request.get("operation_digest")
            == scenario.operation.digest,
            "preconditions_digest": request.get("preconditions_digest")
            == preconditions_digest,
            "fault_digest": request.get("fault_digest") == fault_digest,
            "runtime_role": request.get("runtime_role") == role,
            "runtime_profile_id": request.get("runtime_profile_id")
            == profile.profile_id,
            "runtime_profile_digest": request.get("runtime_profile_digest")
            == profile.profile_digest,
            "runtime_identity": bool(runtime_identity)
            and request.get("runtime_identity") == runtime_identity,
            "release_token": hmac.compare_digest(
                str(request.get("release_token", "")), release_token
            ),
        }

    def _accept_call(self, request: dict[str, Any]) -> dict[str, Any]:
        required_keys = {
            "schema",
            "message_type",
            "run_nonce",
            "challenge_digest",
            "observation_id",
            "observation_kind",
            "invariant_id",
            "observation_digest",
            "case_digest",
            "operation_api",
            "operation_digest",
            "preconditions_digest",
            "fault_digest",
            "sequence",
            "idempotency_key",
            "operation",
            "args",
            "call_digest",
            "runtime_role",
            "runtime_profile_id",
            "runtime_profile_digest",
            "runtime_identity",
            "release_token",
        }
        if set(request) != required_keys:
            return self._refusal("call_schema")
        observation_id = request["observation_id"]
        sequence = request["sequence"]
        if observation_id not in self.expected or type(sequence) is not int:
            return self._refusal("unknown_observation_or_sequence")
        kind, scenario, observation = self.expected[observation_id]
        calls = _observation_calls(observation)
        checks = self._common_checks(
            request, kind=kind, scenario=scenario, observation=observation
        )
        checks["sequence"] = 0 <= sequence < len(calls)
        if 0 <= sequence < len(calls):
            expected_call = calls[sequence]
            checks.update(
                {
                    "operation": request["operation"] == expected_call.operation,
                    "args": _canonical_json(request["args"])
                    == _canonical_json(expected_call.args),
                    "call_digest": request["call_digest"] == expected_call.digest,
                    "idempotency_key": request["idempotency_key"]
                    == self._idempotency_key(
                        self.run_nonce, observation_id, sequence, expected_call.digest
                    ),
                }
            )
        failed = sorted(name for name, passed in checks.items() if not passed)
        if failed:
            return self._refusal(*failed)
        expected_call = calls[sequence]
        request_bytes = _canonical_json(request)
        request_digest = hashlib.sha256(request_bytes).hexdigest()
        existing = self.database.execute(
            "SELECT request_digest, response_json FROM evidence "
            "WHERE run_nonce=? AND observation_id=? AND sequence=?",
            (self.run_nonce, observation_id, sequence),
        ).fetchone()
        if existing:
            if existing[0] != request_digest:
                return self._refusal("idempotency_collision")
            response = _strict_json_bytes(existing[1])
            response["replayed"] = True
            return response
        prior_count = self.database.execute(
            "SELECT COUNT(*) FROM evidence WHERE run_nonce=? AND observation_id=?",
            (self.run_nonce, observation_id),
        ).fetchone()[0]
        if prior_count != sequence:
            return self._refusal("out_of_order_call")
        result_digest = hashlib.sha256(
            _canonical_json(expected_call.expected_result)
        ).hexdigest()
        event = {
            "schema": 2,
            "run_nonce": self.run_nonce,
            "challenge_digest": self.challenge_digest,
            "observation_id": observation_id,
            "observation_kind": kind,
            "invariant_id": scenario.invariant_id,
            "observation_digest": observation.executable_digest,
            "case_digest": scenario.executable_digest,
            "sequence": sequence,
            "idempotency_key": request["idempotency_key"],
            "operation": expected_call.operation,
            "args_digest": hashlib.sha256(_canonical_json(expected_call.args)).hexdigest(),
            "call_digest": expected_call.digest,
            "result_digest": result_digest,
            "runtime_profile_digest": request["runtime_profile_digest"],
            "runtime_identity": request["runtime_identity"],
            "disposition": "reference_result_committed",
        }
        event_bytes = _canonical_json(event)
        event_id = hashlib.sha256(event_bytes).hexdigest()
        signature = hmac.new(self.hmac_key, event_bytes, hashlib.sha256).hexdigest()
        response = {
            "status": "committed",
            "result": expected_call.expected_result,
            "result_digest": result_digest,
            "event_id": event_id,
            "event_hmac": signature,
            "replayed": False,
        }
        self.database.execute(
            "INSERT INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                self.run_nonce,
                observation_id,
                sequence,
                request_digest,
                event_bytes,
                _canonical_json(response),
                signature,
            ),
        )
        self.database.execute(
            "UPDATE observations SET state='running' WHERE observation_id=?",
            (observation_id,),
        )
        self.database.commit()
        return response

    def _accept_completion(self, request: dict[str, Any]) -> dict[str, Any]:
        required_keys = {
            "schema",
            "message_type",
            "run_nonce",
            "challenge_digest",
            "observation_id",
            "observation_kind",
            "invariant_id",
            "observation_digest",
            "case_digest",
            "operation_api",
            "operation_digest",
            "preconditions_digest",
            "fault_digest",
            "runtime_role",
            "runtime_profile_id",
            "runtime_profile_digest",
            "runtime_identity",
            "release_token",
            "completed_call_count",
            "observed_outcome",
            "result_digest",
        }
        if set(request) != required_keys:
            return self._refusal("completion_schema")
        observation_id = request["observation_id"]
        if observation_id not in self.expected:
            return self._refusal("unknown_completion_observation")
        kind, scenario, observation = self.expected[observation_id]
        calls = _observation_calls(observation)
        checks = self._common_checks(
            request, kind=kind, scenario=scenario, observation=observation
        )
        expected_outcome = _expected_observed_outcome(kind, observation)
        checks.update(
            {
                "call_count": request["completed_call_count"] == len(calls),
                "observed_outcome": _canonical_json(request["observed_outcome"])
                == _canonical_json(expected_outcome),
                "result_digest": request["result_digest"]
                == hashlib.sha256(_canonical_json(expected_outcome)).hexdigest(),
                "durable_calls": self.database.execute(
                    "SELECT COUNT(*) FROM evidence "
                    "WHERE run_nonce=? AND observation_id=?",
                    (self.run_nonce, observation_id),
                ).fetchone()[0]
                == len(calls),
            }
        )
        failed = sorted(name for name, passed in checks.items() if not passed)
        if failed:
            return self._refusal(*failed)
        request_bytes = _canonical_json(request)
        request_digest = hashlib.sha256(request_bytes).hexdigest()
        existing = self.database.execute(
            "SELECT request_digest, response_json FROM completions "
            "WHERE run_nonce=? AND observation_id=?",
            (self.run_nonce, observation_id),
        ).fetchone()
        if existing:
            if existing[0] != request_digest:
                return self._refusal("completion_idempotency_collision")
            response = _strict_json_bytes(existing[1])
            response["replayed"] = True
            return response
        event = {
            "schema": 2,
            "run_nonce": self.run_nonce,
            "challenge_digest": self.challenge_digest,
            "observation_id": observation_id,
            "observation_kind": kind,
            "invariant_id": scenario.invariant_id,
            "observation_digest": observation.executable_digest,
            "case_digest": scenario.executable_digest,
            "call_count": len(calls),
            "result_digest": request["result_digest"],
            "runtime_profile_digest": request["runtime_profile_digest"],
            "runtime_identity": request["runtime_identity"],
            "disposition": "exact_outcome_observed",
        }
        event_bytes = _canonical_json(event)
        event_id = hashlib.sha256(event_bytes).hexdigest()
        signature = hmac.new(self.hmac_key, event_bytes, hashlib.sha256).hexdigest()
        response = {
            "status": "accepted",
            "event_id": event_id,
            "event_hmac": signature,
            "replayed": False,
        }
        self.database.execute(
            "INSERT INTO completions VALUES (?, ?, ?, ?, ?, ?)",
            (
                self.run_nonce,
                observation_id,
                request_digest,
                event_bytes,
                _canonical_json(response),
                signature,
            ),
        )
        self.database.execute(
            "UPDATE observations SET state='completed' WHERE observation_id=?",
            (observation_id,),
        )
        self.database.commit()
        return response

    def evidence(self) -> dict[tuple[str, int], dict[str, Any]]:
        rows = self.database.execute(
            "SELECT observation_id, sequence, event_json, event_hmac FROM evidence "
            "WHERE run_nonce=? ORDER BY observation_id, sequence",
            (self.run_nonce,),
        ).fetchall()
        evidence = {}
        for observation_id, sequence, event_bytes, signature in rows:
            event = _strict_json_bytes(event_bytes)
            assert hmac.compare_digest(
                signature,
                hmac.new(self.hmac_key, event_bytes, hashlib.sha256).hexdigest(),
            )
            event["event_id"] = hashlib.sha256(event_bytes).hexdigest()
            event["event_hmac"] = signature
            evidence[(observation_id, sequence)] = event
        return evidence

    def completion_evidence(self) -> dict[str, dict[str, Any]]:
        rows = self.database.execute(
            "SELECT observation_id, event_json, event_hmac FROM completions "
            "WHERE run_nonce=? ORDER BY observation_id",
            (self.run_nonce,),
        ).fetchall()
        evidence = {}
        for observation_id, event_bytes, signature in rows:
            event = _strict_json_bytes(event_bytes)
            assert hmac.compare_digest(
                signature,
                hmac.new(self.hmac_key, event_bytes, hashlib.sha256).hexdigest(),
            )
            event["event_id"] = hashlib.sha256(event_bytes).hexdigest()
            event["event_hmac"] = signature
            evidence[observation_id] = event
        return evidence

    def durable_states(self) -> dict[str, str]:
        return dict(
            self.database.execute(
                "SELECT observation_id, state FROM observations ORDER BY observation_id"
            ).fetchall()
        )

    def reference_state_root(self) -> str:
        rows = self.database.execute(
            "SELECT observation_id, observation_kind, invariant_id, "
            "observation_digest, preconditions_json, operation_json, fault_json, "
            "runtime_role, runtime_profile_id, runtime_profile_digest, calls_json, "
            "expected_outcome_json FROM observations ORDER BY observation_id"
        ).fetchall()
        records = []
        for row in rows:
            records.append(
                {
                    "observation_id": row[0],
                    "observation_kind": row[1],
                    "invariant_id": row[2],
                    "observation_digest": row[3],
                    "preconditions": _strict_json_bytes(row[4]),
                    "operation": _strict_json_bytes(row[5]),
                    "fault": _strict_json_bytes(row[6]) if row[6] is not None else None,
                    "runtime_role": row[7],
                    "runtime_profile_id": row[8],
                    "runtime_profile_digest": row[9],
                    "calls": _strict_json_bytes(row[10]),
                    "expected_outcome": _strict_json_bytes(row[11]),
                }
            )
        return hashlib.sha256(_canonical_json(records)).hexdigest()

    def close(self) -> None:
        self._stop.set()
        self.thread.join(timeout=5)
        assert not self.thread.is_alive()
        self.database.close()


class ParentEvidenceObserver:
    """Own secrets and observe raw effects without entering the harness process."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir()
        self.run_nonce = secrets.token_hex(32)
        self.broker = IndependentCapabilityBroker(self.root, run_nonce=self.run_nonce)
        self.challenge_digest = ""
        self.broker_evidence: dict[tuple[str, int], dict[str, Any]] = {}
        self.completion_evidence: dict[str, dict[str, Any]] = {}
        self.ready = self.root / "ready"
        self.release = self.root / "release"
        self.markers = self.root / "markers"
        for path in (self.ready, self.release, self.markers):
            path.mkdir()
        self.release_roots = {}
        self.marker_roots = {}
        for probe_id in PROBE_BY_ID:
            release_root = self.release / probe_id
            marker_root = self.markers / probe_id
            release_root.mkdir()
            marker_root.mkdir()
            self.release_roots[probe_id] = release_root
            self.marker_roots[probe_id] = marker_root
        self.poison_cwd = self.root / "poison-cwd"
        self.poison_cwd.mkdir()
        (self.poison_cwd / "sitecustomize.py").write_text(
            "raise RuntimeError('poison sitecustomize imported')\n", encoding="utf-8"
        )
        (self.poison_cwd / ".env").write_text("GALAXY_POISON=1\n", encoding="utf-8")
        (self.poison_cwd / "main.py").write_text(
            "raise RuntimeError('poison target main imported')\n", encoding="utf-8"
        )
        self.expected_bytes = {
            "goldstone": secrets.token_bytes(64),
            "credential": secrets.token_hex(48).encode("ascii"),
            "parser_bomb": b'\xff\xfe{"duplicate":1,"duplicate":2}\x00..\\escape',
            "git_authority": secrets.token_bytes(64),
        }
        self.paths = {
            name: self.root / f"{name}.canary" for name in self.expected_bytes
        }
        self.paths.update(
            {
                "forbidden_write": self.root / "forbidden-write.created",
                "descendant": self.root / "descendant.created",
                "outside_state": self.root / "outside-state.created",
            }
        )
        for name, content in self.expected_bytes.items():
            self.paths[name].write_bytes(content)

        self.store_path = self.root / "sibling-store.sqlite3"
        self.store = sqlite3.connect(self.store_path)
        self.store.execute("PRAGMA journal_mode=WAL")
        self.store.execute("CREATE TABLE authority (id TEXT PRIMARY KEY, value TEXT)")
        self.store.execute("INSERT INTO authority VALUES ('owner', ?)", (secrets.token_hex(32),))
        self.store.commit()
        self.expected_store_rows = self.store.execute(
            "SELECT id, value FROM authority ORDER BY id"
        ).fetchall()

        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(16)
        self.listener.setblocking(False)
        self.releases: dict[str, str] = {}

    def write_public_challenge(self, path: Path) -> None:
        challenge = {
            "schema": 2,
            "run_nonce": self.run_nonce,
            "acceptance_ledger_digest": PINNED_ACCEPTANCE_LEDGER_DIGEST,
            "runtime_profile_ledger_digest": PINNED_RUNTIME_PROFILE_LEDGER_DIGEST,
            "ready_root": str(self.ready),
            "release_roots": {
                probe_id: str(root) for probe_id, root in self.release_roots.items()
            },
            "marker_roots": {
                probe_id: str(root) for probe_id, root in self.marker_roots.items()
            },
            "poison_cwd": str(self.poison_cwd),
            "goldstone_path": str(self.paths["goldstone"]),
            "credential_path": str(self.paths["credential"]),
            "parser_bomb_path": str(self.paths["parser_bomb"]),
            "git_authority_path": str(self.paths["git_authority"]),
            "sibling_store_path": str(self.store_path),
            "forbidden_write_path": str(self.paths["forbidden_write"]),
            "descendant_marker_path": str(self.paths["descendant"]),
            "outside_state_path": str(self.paths["outside_state"]),
            "observer_host": "127.0.0.1",
            "observer_port": self.listener.getsockname()[1],
            "capability_broker_channels": {
                name: str(channel_path)
                for name, channel_path in self.broker.channels.items()
            },
            "expected_probe_ids": sorted(PROBE_BY_ID),
            "expected_observation_ids": sorted(OBSERVATION_BY_ID),
            "runtime_profile_digests": {
                profile_id: profile.profile_digest
                for profile_id, profile in sorted(RUNTIME_PROFILES.items())
            },
        }
        self.challenge_digest = hashlib.sha256(_canonical_json(challenge)).hexdigest()
        challenge["challenge_digest"] = self.challenge_digest
        self.broker.bind_challenge(self.challenge_digest)
        path.write_bytes(_canonical_json(challenge))

    def release_live_probe(self, probe_id: str) -> str:
        token = secrets.token_hex(32)
        self.releases[probe_id] = token
        self.broker.authorize(probe_id, token)
        (self.release_roots[probe_id] / "release.token").write_text(
            token, encoding="ascii"
        )
        return token

    def snapshot(self) -> dict[str, Any]:
        connections = 0
        try:
            while True:
                connection, _ = self.listener.accept()
                connections += 1
                connection.close()
        except BlockingIOError:
            pass
        contents = {name: path.read_bytes() for name, path in self.paths.items()
                    if name in self.expected_bytes}
        store_rows = self.store.execute(
            "SELECT id, value FROM authority ORDER BY id"
        ).fetchall()
        snapshot = {
            "schema": 2,
            "run_nonce": self.run_nonce,
            "challenge_digest": self.challenge_digest,
            "acceptance_ledger_digest": PINNED_ACCEPTANCE_LEDGER_DIGEST,
            "runtime_profile_ledger_digest": PINNED_RUNTIME_PROFILE_LEDGER_DIGEST,
            "reference_state_root": self.broker.reference_state_root(),
            "network_connections": connections,
            "changed_canaries": sorted(
                name for name, expected in self.expected_bytes.items()
                if contents[name] != expected
            ),
            "created_forbidden_paths": sorted(
                name for name in ("forbidden_write", "descendant", "outside_state")
                if self.paths[name].exists()
            ),
            "sibling_store_unchanged": store_rows == self.expected_store_rows,
            "sibling_wal_present": Path(f"{self.store_path}-wal").exists(),
            "canary_digests": {
                name: hashlib.sha256(content).hexdigest()
                for name, content in sorted(contents.items())
            },
        }
        broker_evidence = self.broker.evidence()
        completion_evidence = self.broker.completion_evidence()
        durable_states = self.broker.durable_states()
        self.broker_evidence = broker_evidence
        self.completion_evidence = completion_evidence
        snapshot["broker_event_count"] = len(broker_evidence)
        snapshot["broker_evidence_root"] = hashlib.sha256(
            _canonical_json(
                [broker_evidence[key] for key in sorted(broker_evidence)]
            )
        ).hexdigest()
        snapshot["completion_count"] = len(completion_evidence)
        snapshot["completion_evidence_root"] = hashlib.sha256(
            _canonical_json(
                [completion_evidence[key] for key in sorted(completion_evidence)]
            )
        ).hexdigest()
        snapshot["incomplete_observations"] = sorted(
            observation_id
            for observation_id, state in durable_states.items()
            if state != "completed"
        )
        snapshot["broker_violations"] = tuple(self.broker.violations)
        snapshot["observation_digest"] = hashlib.sha256(
            _canonical_json(snapshot)
        ).hexdigest()
        return snapshot

    def close(self) -> None:
        self.listener.close()
        self.store.close()
        self.broker.close()


def _mod():
    return importlib.import_module("bootstrap.galaxy_launcher.activation_harness")


def _assert_runtime_is_external_and_exact(runtime, acceptance) -> None:
    executable_paths = (
        runtime.interpreter,
        runtime.powershell_path,
        runtime.harness_entrypoint,
        runtime.probe_entrypoint,
        runtime.adapter_entrypoint,
    )
    for path in executable_paths:
        resolved = Path(path).resolve(strict=True)
        assert not resolved.is_relative_to(REPOSITORY_ROOT.resolve())
        assert not Path(path).is_symlink()
    assert _sha256(Path(runtime.interpreter)) == runtime.interpreter_digest
    assert _sha256(Path(runtime.powershell_path)) == runtime.powershell_digest
    assert _sha256(Path(runtime.harness_entrypoint)) == runtime.harness_digest
    assert _sha256(Path(runtime.probe_entrypoint)) == runtime.probe_digest
    assert _sha256(Path(runtime.adapter_entrypoint)) == runtime.adapter_digest
    assert _sha256(Path(runtime.acceptance_path)) == PINNED_ACCEPTANCE_LEDGER_DIGEST
    assert _sha256(Path(runtime.runtime_profile_ledger_path)) == (
        PINNED_RUNTIME_PROFILE_LEDGER_DIGEST
    )
    assert runtime.runtime_digest == acceptance.runtime_digest
    assert runtime.image_digests == acceptance.image_digests
    assert acceptance.ledger_digest == PINNED_ACCEPTANCE_LEDGER_DIGEST
    assert acceptance.runtime_profile_ledger_digest == (
        PINNED_RUNTIME_PROFILE_LEDGER_DIGEST
    )
    assert acceptance.adapter_digest == runtime.adapter_digest
    _assert_tofu_receipt_pins_runtime(runtime, acceptance)


def _leaf_root(domain: str, leaves: list[dict[str, Any]]) -> str:
    leaf_hashes = []
    for leaf in sorted(leaves, key=lambda item: item["logical_path"]):
        installed = Path(leaf["installed_path"])
        assert installed.resolve(strict=True) == installed.absolute()
        assert not installed.is_symlink()
        raw = installed.read_bytes()
        assert len(raw) == leaf["size"]
        assert hashlib.sha256(raw).hexdigest() == leaf["sha256"]
        record = {
            "logical_path": leaf["logical_path"],
            "sha256": leaf["sha256"],
            "size": leaf["size"],
        }
        leaf_hashes.append(hashlib.sha256(_canonical_json(record)).digest())
    return hashlib.sha256(
        domain.encode("ascii") + b"\0" + b"".join(sorted(leaf_hashes))
    ).hexdigest()


def _assert_tofu_receipt_pins_runtime(runtime, acceptance) -> None:
    receipt_path = Path(runtime.tofu_receipt_path).resolve(strict=True)
    external_root = Path(runtime.external_root).resolve(strict=True)
    assert receipt_path.is_relative_to(external_root)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["schema"] == "galaxy.trust-on-first-install/v1"
    assert receipt["status"] == "installed_inactive"
    source_root = _leaf_root("source", receipt["source_leaves"])
    artifact_root = _leaf_root("artifact", receipt["artifact_leaves"])
    assert source_root == receipt["source_root"]
    assert artifact_root == receipt["artifact_root"]
    merkle_root = hashlib.sha256(
        b"galaxy-tofu-v1\0"
        + bytes.fromhex(source_root)
        + bytes.fromhex(artifact_root)
    ).hexdigest()
    assert merkle_root == receipt["merkle_root"] == runtime.tofu_merkle_root
    assert receipt["challenge"] == (
        f"TRUST SINGULARITY BOOTSTRAP {merkle_root} NONCE {receipt['nonce']}"
    )
    assert receipt["approval_response_sha256"] == hashlib.sha256(
        receipt["challenge"].encode("utf-8")
    ).hexdigest()
    leaves = receipt["source_leaves"] + receipt["artifact_leaves"]
    installed_paths = {Path(leaf["installed_path"]).resolve() for leaf in leaves}
    required_paths = {
        Path(runtime.interpreter).resolve(),
        Path(runtime.powershell_path).resolve(),
        Path(runtime.harness_entrypoint).resolve(),
        Path(runtime.probe_entrypoint).resolve(),
        Path(runtime.adapter_entrypoint).resolve(),
        Path(runtime.acceptance_path).resolve(),
        Path(runtime.runtime_profile_ledger_path).resolve(),
        Path(runtime.runtime_lock_path).resolve(),
        Path(runtime.receipt_public_key_path).resolve(),
        *(Path(path).resolve() for path in runtime.image_archive_paths.values()),
    }
    assert required_paths <= installed_paths
    assert receipt["runtime_digest"] == acceptance.runtime_digest
    assert receipt["image_digests"] == acceptance.image_digests
    assert receipt["activation_acceptance_sha256"] == (
        PINNED_ACCEPTANCE_LEDGER_DIGEST
    )
    assert receipt["activation_runtime_profiles_sha256"] == (
        PINNED_RUNTIME_PROFILE_LEDGER_DIGEST
    )
    assert receipt["activation_adapter_sha256"] == runtime.adapter_digest
    public_key = Path(runtime.receipt_public_key_path).read_bytes()
    assert len(public_key) == 32
    assert public_key.hex() == receipt["activation_receipt_public_key"]
    assert hashlib.sha256(public_key).hexdigest() == receipt[
        "activation_receipt_public_key_digest"
    ]
    assert acceptance.receipt_public_key == public_key.hex()
    assert receipt["monotone_generation"] == runtime.generation
    live_acl = _read_live_acl(runtime, external_root)
    assert live_acl["protected"] is True
    assert all(rule["inherited"] is False for rule in live_acl["rules"])
    assert live_acl["sddl"] == receipt["dacl_sddl"]
    privileged = {
        "S-1-5-18",  # LocalSystem
        "S-1-5-32-544",  # Builtin Administrators
        receipt["service_sid"],
    }
    assert live_acl["owner_sid"] in privileged
    operator_sid = receipt["operator_sid"]
    write_mask = 2 | 4 | 16 | 256 | 65536 | 262144 | 524288
    for rule in live_acl["rules"]:
        if rule["type"] != "Allow":
            continue
        if rule["sid"] in privileged:
            continue
        assert rule["sid"] == operator_sid
        assert int(rule["rights"]) & write_mask == 0


def _read_live_acl(runtime, path: Path) -> dict[str, Any]:
    script = (
        "param([string]$Path);"
        "$a=Get-Acl -LiteralPath $Path;"
        "$rules=@($a.Access|ForEach-Object {"
        "$sid=$_.IdentityReference.Translate("
        "[System.Security.Principal.SecurityIdentifier]).Value;"
        "[pscustomobject]@{sid=$sid;rights=[int]$_.FileSystemRights;"
        "type=$_.AccessControlType.ToString();inherited=$_.IsInherited}});"
        "$owner=(New-Object System.Security.Principal.NTAccount($a.Owner)).Translate("
        "[System.Security.Principal.SecurityIdentifier]).Value;"
        "[pscustomobject]@{sddl=$a.Sddl;protected=$a.AreAccessRulesProtected;"
        "owner_sid=$owner;rules=$rules}|ConvertTo-Json -Depth 5 -Compress"
    )
    completed = subprocess.run(
        [
            str(runtime.powershell_path),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
            "-Path",
            str(path),
        ],
        cwd=path,
        env={},
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _call_name(node: ast.Call) -> str:
    parts: list[str] = []
    value: ast.expr = node.func
    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value
    if isinstance(value, ast.Name):
        parts.append(value.id)
    return ".".join(reversed(parts))


def _assert_adapter_cannot_consume_expectations(runtime, acceptance) -> None:
    path = Path(runtime.adapter_entrypoint)
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == acceptance.adapter_digest
    source = raw.decode("utf-8", errors="strict")
    tree = ast.parse(source, filename=str(path))
    dispatchers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "dispatch_activation_operation"
    ]
    assert len(dispatchers) == 1
    dispatcher = dispatchers[0]
    assert [argument.arg for argument in dispatcher.args.args[:4]] == [
        "api",
        "args",
        "fault",
        "broker",
    ]
    forbidden_identifiers = {
        "expected_result",
        "expected_enforcement",
        "required_receipts",
        "forbidden_effects",
        "activation_acceptance",
        "acceptance_path",
        "requirements_digest",
    }
    identifiers = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    assert not (forbidden_identifiers & identifiers)
    string_literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert PINNED_ACCEPTANCE_LEDGER_DIGEST not in string_literals
    assert "activation_acceptance.json" not in string_literals
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    assert not any(
        name.startswith("tests")
        or name.startswith("bootstrap.galaxy_launcher.activation_harness")
        for name in imported_modules
    )
    calls = {_call_name(node) for node in ast.walk(dispatcher) if isinstance(node, ast.Call)}
    assert any(call.endswith("broker.call") for call in calls)


def _assert_restricted_win32_probe(
    process_id: int, *, job: KillOnCloseJob, runtime, empty_cwd: Path
) -> None:
    process = psutil.Process(process_id)
    assert process.is_running()
    assert job.contains(process_id)
    assert Path(process.exe()).resolve() == Path(runtime.interpreter).resolve()
    assert Path(process.cwd()).resolve() == empty_cwd.resolve()
    command = process.cmdline()
    assert command[:3] == [
        str(runtime.interpreter),
        "-I",
        "-S",
    ]
    assert str(runtime.probe_entrypoint) in command
    environment = process.environ()
    assert not {
        "PYTHONPATH",
        "PYTHONHOME",
        "VIRTUAL_ENV",
        "GALAXY_POISON",
        "CLAUDE_CONFIG_DIR",
        "OPENAI_API_KEY",
    } & set(environment)

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    advapi32.OpenProcessToken.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    )
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.IsTokenRestricted.argtypes = (wintypes.HANDLE,)
    advapi32.IsTokenRestricted.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    process_handle = kernel32.OpenProcess(0x1000, False, process_id)
    assert process_handle, ctypes.get_last_error()
    token_handle = wintypes.HANDLE()
    try:
        assert advapi32.OpenProcessToken(
            process_handle, 0x0008, ctypes.byref(token_handle)
        ), ctypes.get_last_error()
        assert advapi32.IsTokenRestricted(token_handle), (
            "OS-native probe did not run with a restricted token"
        )
        elevated = wintypes.DWORD()
        returned = wintypes.DWORD()
        assert advapi32.GetTokenInformation(
            token_handle,
            20,  # TokenElevation
            ctypes.byref(elevated),
            ctypes.sizeof(elevated),
            ctypes.byref(returned),
        ), ctypes.get_last_error()
        assert elevated.value == 0
    finally:
        if token_handle:
            kernel32.CloseHandle(token_handle)
        kernel32.CloseHandle(process_handle)


def _assert_live_probe_identity(
    event, *, harness, job, runtime, acceptance, observer, empty_cwd
) -> None:
    scenario, probe = PROBE_BY_ID[event["probe_id"]]
    profile = PROBE_PROFILE_BY_ID[probe.probe_id]
    assert event["scenario_id"] == scenario.invariant_id
    assert event["scenario_digest"] == scenario.executable_digest
    assert event["operation_api"] == scenario.operation.api
    assert event["probe_digest"] == probe.executable_digest
    assert event["runtime_role"] == probe.runtime_role
    assert event["runtime_profile_id"] == profile.profile_id
    assert event["runtime_profile_digest"] == profile.profile_digest
    assert event["broker_operation_count"] == len(probe.broker_operations)
    assert event["run_nonce"] == observer.run_nonce
    assert event["challenge_digest"] == observer.challenge_digest
    assert event["execution_kind"] == profile.execution_kind
    if profile.execution_kind == "restricted_os_process":
        process_id = event["process_id"]
        assert event["runtime_identity"] == f"win32-pid:{process_id}"
        assert event["image_digest"] is None
        _assert_restricted_win32_probe(
            process_id, job=job, runtime=runtime, empty_cwd=empty_cwd
        )
        observer.broker.bind_probe_runtime(probe.probe_id, event["runtime_identity"])
        return

    docker = shutil.which("docker")
    assert docker, "Docker client is required for independent container observation"
    assert profile.image_role
    assert event["image_digest"] == acceptance.image_digests[profile.image_role]
    inspected = subprocess.run(
        [docker, "inspect", event["container_id"]],
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert inspected.returncode == 0, inspected.stderr
    record = json.loads(inspected.stdout)[0]
    config = record["Config"]
    host = record["HostConfig"]
    security = acceptance.security_profiles[profile.profile_id]
    assert record["State"]["Running"] is True
    assert record["Image"].removeprefix("sha256:") == event["image_digest"]
    assert event["runtime_identity"] == f"container:{event['container_id']}"
    assert config["Labels"]["galaxy.probe_id"] == probe.probe_id
    assert config["Labels"]["galaxy.scenario_digest"] == scenario.executable_digest
    assert config["Labels"]["galaxy.run_nonce"] == observer.run_nonce
    assert config["Labels"]["galaxy.challenge_digest"] == observer.challenge_digest
    assert config["Labels"]["galaxy.security_profile_digest"] == (
        security.profile_digest
    )
    assert security.semantic_profile_digest == profile.profile_digest
    assert security.image_role == profile.image_role
    assert config["User"] == security.user
    assert config["Entrypoint"] == list(security.entrypoint)
    assert config["Cmd"] == list(security.command_prefix) + [
        probe.probe_id,
        probe.executable_digest,
    ]
    assert sorted(config["Env"] or ()) == sorted(security.allowed_environment)
    assert host["ReadonlyRootfs"] is True
    assert host["Privileged"] is False
    assert host["NetworkMode"] == security.docker_network_mode == "none"
    assert host["PidMode"] == ""
    assert host["IpcMode"] in ("", "private")
    assert host["CapAdd"] in (None, [])
    assert set(host["CapDrop"] or ()) == {"ALL"}
    assert "no-new-privileges" in set(host["SecurityOpt"] or ())
    assert host["PidsLimit"] == security.pids_limit
    assert host["Memory"] == security.memory_bytes
    assert host["RestartPolicy"]["Name"] == "no"
    actual_mounts = {mount["Destination"]: mount for mount in record["Mounts"]}
    assert set(actual_mounts) == {mount.target for mount in security.mounts}
    dynamic_sources = {
        "broker_request": observer.broker.channels["request_root"],
        "broker_response": observer.broker.channels["response_root"],
        "release": observer.release_roots[probe.probe_id],
        "marker": observer.marker_roots[probe.probe_id],
    }
    for expected_mount in security.mounts:
        actual = actual_mounts[expected_mount.target]
        assert actual["Type"] == expected_mount.kind
        assert actual["RW"] is expected_mount.read_write
        if expected_mount.source_class in dynamic_sources:
            assert Path(actual["Source"]).resolve() == dynamic_sources[
                expected_mount.source_class
            ].resolve()
        else:
            assert expected_mount.source_class == "sealed_runtime"
            assert Path(actual["Source"]).resolve() == Path(
                expected_mount.sealed_source
            ).resolve()
            assert _sha256(Path(actual["Source"])) == expected_mount.source_digest
    observer.broker.bind_probe_runtime(probe.probe_id, event["runtime_identity"])


def _assert_report_matches_parent_broker(raw_report, observer) -> None:
    results = {
        result["observation_id"]: result
        for collection in ("subcase_results", "probe_results")
        for result in raw_report[collection]
    }
    assert set(results) == set(OBSERVATION_BY_ID)
    for observation_id, (_, _, observation) in OBSERVATION_BY_ID.items():
        calls = _observation_calls(observation)
        attempts = results[observation_id]["broker_evidence"]
        assert len(attempts) == len(calls)
        for sequence, attempt in enumerate(attempts):
            expected_call = calls[sequence]
            event = observer.broker_evidence[(observation_id, sequence)]
            assert attempt["operation"] == event["operation"] == expected_call.operation
            assert attempt["call_digest"] == event["call_digest"] == expected_call.digest
            assert attempt["args_digest"] == event["args_digest"]
            assert attempt["result_digest"] == event["result_digest"]
            assert attempt["broker_event_id"] == event["event_id"]
            assert hmac.compare_digest(
                attempt["broker_event_hmac"], event["event_hmac"]
            )
            assert attempt["disposition"] == event["disposition"]
            assert attempt["run_nonce"] == observer.run_nonce
            assert attempt["challenge_digest"] == observer.challenge_digest
        completion = observer.completion_evidence[observation_id]
        assert results[observation_id]["completion_event_id"] == completion["event_id"]
        assert hmac.compare_digest(
            results[observation_id]["completion_event_hmac"],
            completion["event_hmac"],
        )


def test_reviewed_source_lock_does_not_shadow_installed_runtime_pointer(
    tmp_path, monkeypatch
):
    mod = _mod()
    local = tmp_path / "local"
    root = local / "9to5" / "singularity"
    installed_lock = root / "generations" / "00000001" / "activation-runtime.lock.json"
    installed_lock.parent.mkdir(parents=True)
    installed_lock.write_bytes(b"{}")
    pointer = {
        "generation": 1,
        "runtime_lock_path": str(installed_lock),
        "runtime_lock_sha256": hashlib.sha256(installed_lock.read_bytes()).hexdigest(),
        "schema": "galaxy.activation.runtime-pointer/v1",
        "status": "installed_inactive",
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "activation-runtime.json").write_bytes(_canonical_json(pointer))
    monkeypatch.setenv("LOCALAPPDATA", str(local))

    assert mod._runtime_pointer_path() == installed_lock.resolve(strict=True)


@pytest.fixture(scope="module")
def external_run(tmp_path_factory):
    mod = _mod()
    acceptance = mod.load_sealed_acceptance()
    runtime = mod.resolve_sealed_harness_runtime(acceptance)
    _assert_runtime_is_external_and_exact(runtime, acceptance)
    assert 1 <= acceptance.max_probe_concurrency <= 8
    root = tmp_path_factory.mktemp("activation-harness-parent")
    observer = ParentEvidenceObserver(root / "observer")
    challenge_path = root / "challenge.json"
    report_path = root / "report.json"
    observer.write_public_challenge(challenge_path)
    empty_cwd = root / "empty-cwd"
    empty_cwd.mkdir()
    command = [
        str(runtime.interpreter),
        "-I",
        "-S",
        str(runtime.harness_entrypoint),
        "--run-closed-acceptance",
        "--acceptance",
        str(runtime.acceptance_path),
        "--runtime-profiles",
        str(runtime.runtime_profile_ledger_path),
        "--challenge",
        str(challenge_path),
        "--report",
        str(report_path),
    ]
    job = KillOnCloseJob()
    harness = subprocess.Popen(
        command,
        cwd=empty_cwd,
        env={},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=0x00000004,  # CREATE_SUSPENDED; assign job before first byte runs.
    )
    try:
        job.assign(harness)
        observer.broker.bind_case_runtime(harness.pid)
        job.resume_suspended(harness)
    except BaseException:
        job.close()
        harness.wait(timeout=10)
        observer.close()
        raise
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []

    def drain(stream, destination):
        try:
            for line in stream:
                destination.append(line)
        finally:
            stream.close()

    stdout_thread = threading.Thread(
        target=drain, args=(harness.stdout, stdout_parts), daemon=True
    )
    stderr_thread = threading.Thread(
        target=drain, args=(harness.stderr, stderr_parts), daemon=True
    )
    stdout_thread.start()
    stderr_thread.start()
    seen: set[str] = set()
    observed_runtimes: set[str] = set()
    deadline = time.monotonic() + CAMPAIGN_TIMEOUT_SECONDS
    try:
        while len(seen) != len(PROBE_BY_ID):
            assert harness.poll() is None, "harness exited before every live probe was observed"
            for ready_path in sorted(observer.ready.glob("*.json")):
                event = json.loads(ready_path.read_text(encoding="utf-8"))
                probe_id = event["probe_id"]
                if probe_id in seen:
                    continue
                assert probe_id in PROBE_BY_ID
                _assert_live_probe_identity(
                    event,
                    harness=harness,
                    job=job,
                    runtime=runtime,
                    acceptance=acceptance,
                    observer=observer,
                    empty_cwd=empty_cwd,
                )
                observed_runtimes.add(event["runtime_identity"])
                observer.release_live_probe(probe_id)
                seen.add(probe_id)
            if time.monotonic() >= deadline:
                raise AssertionError(
                    f"timed out observing sealed probes: {len(seen)}/{len(PROBE_BY_ID)}"
                )
            time.sleep(0.01)
        assert len(observed_runtimes) == len(PROBE_BY_ID)
        remaining = max(1, deadline - time.monotonic())
        harness.wait(timeout=remaining)
        stdout_thread.join(timeout=10)
        stderr_thread.join(timeout=10)
        assert not stdout_thread.is_alive() and not stderr_thread.is_alive()
        stdout = "".join(stdout_parts)
        stderr = "".join(stderr_parts)
        assert harness.returncode == 0, f"stdout={stdout}\nstderr={stderr}"
        assert report_path.is_file()
        raw_report = json.loads(report_path.read_text(encoding="utf-8"))
        snapshot = observer.snapshot()
    finally:
        job.close()
        if harness.poll() is None:
            harness.wait(timeout=10)
        docker = shutil.which("docker")
        if docker:
            listed = subprocess.run(
                [
                    docker,
                    "ps",
                    "-aq",
                    "--filter",
                    f"label=galaxy.run_nonce={observer.run_nonce}",
                ],
                text=True,
                capture_output=True,
                timeout=20,
                check=False,
            )
            container_ids = {
                value.strip() for value in listed.stdout.splitlines() if value.strip()
            }
            if container_ids:
                removed = subprocess.run(
                    [docker, "rm", "-f", *sorted(container_ids)],
                    text=True,
                    capture_output=True,
                    timeout=60,
                    check=False,
                )
                assert removed.returncode == 0, removed.stderr
        observer.close()
    docker = shutil.which("docker")
    assert docker
    post = subprocess.run(
        [
            docker,
            "ps",
            "-aq",
            "--filter",
            f"label=galaxy.run_nonce={observer.run_nonce}",
        ],
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert post.returncode == 0 and not post.stdout.strip()
    return mod, acceptance, runtime, raw_report, snapshot, observer


def test_parent_reference_broker_is_exact_durable_and_idempotent(tmp_path):
    scenario = SCENARIOS[0]
    subcase = scenario.subcases[0]
    broker = IndependentCapabilityBroker(tmp_path, run_nonce="1" * 64)
    try:
        broker.bind_challenge("2" * 64)
        broker.bind_case_runtime(4242)
        profile = RUNTIME_PROFILES["controller_restricted_win32"]
        preconditions_digest = hashlib.sha256(
            _canonical_json(
                [dataclasses.asdict(item) for item in scenario.preconditions]
            )
        ).hexdigest()

        def common() -> dict[str, Any]:
            return {
                "schema": 2,
                "run_nonce": "1" * 64,
                "challenge_digest": "2" * 64,
                "observation_id": subcase.observation_id,
                "observation_kind": "subcase",
                "invariant_id": scenario.invariant_id,
                "observation_digest": subcase.executable_digest,
                "case_digest": scenario.executable_digest,
                "operation_api": scenario.operation.api,
                "operation_digest": scenario.operation.digest,
                "preconditions_digest": preconditions_digest,
                "fault_digest": subcase.fault.digest,
                "runtime_role": "activation_case_adapter",
                "runtime_profile_id": profile.profile_id,
                "runtime_profile_digest": profile.profile_digest,
                "runtime_identity": "win32-pid:4242",
                "release_token": "",
            }

        responses = []
        for sequence, call in enumerate(subcase.broker_calls):
            request = {
                **common(),
                "message_type": "call",
                "sequence": sequence,
                "idempotency_key": broker._idempotency_key(
                    "1" * 64, subcase.observation_id, sequence, call.digest
                ),
                "operation": call.operation,
                "args": call.args,
                "call_digest": call.digest,
            }
            response = broker.accept_request(request)
            assert response["status"] == "committed"
            assert _canonical_json(response["result"]) == _canonical_json(
                call.expected_result
            )
            responses.append((request, response))
        replay = broker.accept_request(responses[0][0])
        assert replay["status"] == "committed" and replay["replayed"] is True
        assert len(broker.evidence()) == len(subcase.broker_calls)

        substituted = json.loads(json.dumps(responses[0][0]))
        substituted["args"]["target_controlled"] = True
        refusal = broker.accept_request(substituted)
        assert refusal["status"] == "refused"
        assert "args" in refusal["reason"]

        outcome = _expected_observed_outcome("subcase", subcase)
        completion = broker.accept_request(
            {
                **common(),
                "message_type": "complete",
                "completed_call_count": len(subcase.broker_calls),
                "observed_outcome": outcome,
                "result_digest": hashlib.sha256(_canonical_json(outcome)).hexdigest(),
            }
        )
        assert completion["status"] == "accepted"
        assert broker.durable_states()[subcase.observation_id] == "completed"
        assert re.fullmatch(r"[0-9a-f]{64}", broker.reference_state_root())
    finally:
        broker.close()


def test_closed_ledger_is_exact_requirement_specific_and_adapter_cannot_see_expectations(
    external_run,
):
    _, acceptance, runtime, _, _, _ = external_run
    assert acceptance.task_contracts == (1, 2, 3, 4)
    assert acceptance.case_count == 192
    assert acceptance.subcase_count == 5230
    assert acceptance.probe_count == 552
    assert acceptance.observation_count == 5782
    assert acceptance.broker_call_count == 16294
    assert acceptance.requirements_digest == PINNED_REQUIREMENTS_DIGEST
    assert acceptance.ledger_digest == PINNED_ACCEPTANCE_LEDGER_DIGEST
    assert acceptance.runtime_profile_ledger_digest == (
        PINNED_RUNTIME_PROFILE_LEDGER_DIGEST
    )
    assert set(acceptance.case_ids) == set(SCENARIO_BY_ID)
    assert set(acceptance.subcase_ids) == set(SUBCASE_BY_ID)
    assert set(acceptance.probe_ids) == set(PROBE_BY_ID)
    assert acceptance.role_profile_assignments == ROLE_PROFILE_ASSIGNMENTS
    assert {
        profile_id: profile.profile_digest
        for profile_id, profile in RUNTIME_PROFILES.items()
    } == acceptance.semantic_profile_digests
    actual = {case.invariant_id: case for case in acceptance.cases}
    for scenario in SCENARIOS:
        case = actual[scenario.invariant_id]
        assert case.requirement_digest == scenario.requirement_digest
        assert _canonical_json(dataclasses.asdict(case.operation)) == _canonical_json(
            dataclasses.asdict(scenario.operation)
        )
        for actual_items, expected_items in (
            (case.preconditions, scenario.preconditions),
            (case.subcases, scenario.subcases),
            (case.probes, scenario.probes),
            (case.required_receipts, scenario.required_receipts),
        ):
            assert _canonical_json(
                [dataclasses.asdict(item) for item in actual_items]
            ) == _canonical_json(
                [dataclasses.asdict(item) for item in expected_items]
            )
        assert case.executable_digest == scenario.executable_digest
    _assert_adapter_cannot_consume_expectations(runtime, acceptance)


def test_every_exact_subcase_and_probe_ran_through_parent_reference_broker(external_run):
    mod, acceptance, _, raw_report, snapshot, observer = external_run
    _assert_report_matches_parent_broker(raw_report, observer)
    report = mod.validate_external_report(
        raw_report,
        acceptance=acceptance,
        independent_observation=snapshot,
    )
    assert report.executed_subcase_keys == EXPECTED_CASES
    assert set(report.executed_probe_ids) == set(PROBE_BY_ID)
    assert snapshot["network_connections"] == 0
    assert snapshot["changed_canaries"] == []
    assert snapshot["created_forbidden_paths"] == []
    assert snapshot["sibling_store_unchanged"] is True
    assert snapshot["sibling_wal_present"] is True
    assert snapshot["run_nonce"] == observer.run_nonce
    assert snapshot["challenge_digest"] == observer.challenge_digest
    assert snapshot["broker_violations"] == ()
    assert snapshot["broker_event_count"] == sum(
        len(_observation_calls(observation))
        for _, _, observation in OBSERVATION_BY_ID.values()
    )
    assert snapshot["broker_event_count"] == 16294
    assert snapshot["completion_count"] == len(OBSERVATION_BY_ID) == 5782
    assert snapshot["incomplete_observations"] == []
    assert re.fullmatch(r"[0-9a-f]{64}", snapshot["reference_state_root"])
    assert raw_report["reference_state_root"] == snapshot["reference_state_root"]
    assert set(report.subcase_results) == {
        subcase.observation_id
        for scenario in SCENARIOS
        for subcase in scenario.subcases
    }
    for probe_id, (scenario, probe) in PROBE_BY_ID.items():
        result = report.probe_results[probe_id]
        release = observer.releases[probe_id]
        marker = observer.marker_roots[probe_id] / "completed.marker"
        expected_marker = hashlib.sha256(
            f"{release}:{probe_id}:{probe.executable_digest}".encode("ascii")
        ).hexdigest()
        assert marker.read_text(encoding="ascii") == expected_marker
        assert result.operation_api == scenario.operation.api
        assert result.probe_digest == probe.executable_digest
        assert result.runtime_role == probe.runtime_role
        profile = PROBE_PROFILE_BY_ID[probe_id]
        assert result.runtime_profile_digest == profile.profile_digest
        assert len(result.broker_evidence) == len(probe.broker_operations)
        for sequence, attempt in enumerate(result.broker_evidence):
            event = observer.broker_evidence[(probe_id, sequence)]
            expected_call = probe.broker_operations[sequence]
            assert attempt.operation == expected_call.operation
            assert attempt.call_digest == expected_call.digest
            assert attempt.broker_event_id == event["event_id"]
            assert hmac.compare_digest(attempt.broker_event_hmac, event["event_hmac"])
            assert attempt.disposition == event["disposition"]
            assert attempt.run_nonce == observer.run_nonce
            assert attempt.challenge_digest == observer.challenge_digest
        expected_image = (
            acceptance.image_digests[profile.image_role]
            if profile.execution_kind == "hardened_container"
            else None
        )
        assert result.image_digest == expected_image
    serialized = json.dumps(raw_report, sort_keys=True)
    assert observer.expected_bytes["credential"].decode("ascii") not in serialized


def test_every_explicit_outcome_and_required_receipt_is_signed_and_bound(external_run):
    mod, acceptance, _, raw_report, snapshot, _ = external_run
    _assert_signed_report(raw_report, acceptance.receipt_public_key)
    for collection in ("subcase_results", "probe_results"):
        for raw_result in raw_report[collection]:
            _verify_signed_record(raw_result["receipt"], acceptance.receipt_public_key)
            payload = raw_result["receipt"]["signed_payload"]
            assert payload["schema"] == "galaxy.activation.observation-receipt/v2"
            assert payload["run_nonce"] == snapshot["run_nonce"]
            assert payload["challenge_digest"] == snapshot["challenge_digest"]
            assert payload["acceptance_ledger_digest"] == (
                PINNED_ACCEPTANCE_LEDGER_DIGEST
            )
            assert payload["runtime_profile_ledger_digest"] == (
                PINNED_RUNTIME_PROFILE_LEDGER_DIGEST
            )
            assert payload["reference_state_root"] == snapshot[
                "reference_state_root"
            ]
            assert payload["observation_id"] == raw_result["observation_id"]
            assert re.fullmatch(r"[0-9a-f]{64}", payload["result_digest"])
            assert re.fullmatch(r"[0-9a-f]{64}", payload["broker_evidence_root"])
            assert re.fullmatch(r"[0-9a-f]{64}", payload["completion_event_id"])
            assert payload["completion_event_id"] == raw_result[
                "completion_event_id"
            ]
    report = mod.validate_external_report(
        raw_report,
        acceptance=acceptance,
        independent_observation=snapshot,
    )
    for scenario in SCENARIOS:
        for subcase in scenario.subcases:
            result = report.subcase_results[subcase.observation_id]
            assert result.invariant_id == scenario.invariant_id
            assert result.subcase_id == subcase.subcase_id
            assert result.case_digest == scenario.executable_digest
            assert result.subcase_digest == subcase.executable_digest
            assert result.operation_digest == scenario.operation.digest
            assert result.fault_digest == subcase.fault.digest
            assert result.status == subcase.expected.status
            assert _canonical_json(result.state) == _canonical_json(
                subcase.expected.state
            )
            assert tuple(result.forbidden_effects_observed) == ()
            assert result.receipt.authentication_verified is True
            assert result.receipt.runtime_digest == acceptance.runtime_digest
            assert result.receipt.acceptance_ledger_digest == (
                PINNED_ACCEPTANCE_LEDGER_DIGEST
            )
            bindings = {
                binding.type: binding for binding in result.receipt.required_receipts
            }
            assert set(bindings) == {
                receipt.type for receipt in scenario.required_receipts
            }
            for required in scenario.required_receipts:
                binding = bindings[required.type]
                assert re.fullmatch(r"[0-9a-f]{64}", binding.receipt_id)
                assert set(binding.fields) == set(required.required_fields)
                assert all(value is not None for value in binding.fields.values())
                assert re.fullmatch(r"[0-9a-f]{64}", binding.content_digest)
    for raw_probe in raw_report["probe_results"]:
        payload = raw_probe["receipt"]["signed_payload"]
        assert payload["run_nonce"] == snapshot["run_nonce"]
        assert payload["challenge_digest"] == snapshot["challenge_digest"]


def test_in_process_adapter_expected_result_and_target_acceptance_are_not_apis(tmp_path):
    mod = _mod()
    assert not hasattr(mod, "run_closed_harness_with_adapter")
    assert not hasattr(mod, "accept_expected_results")
    assert not hasattr(mod, "load_target_acceptance")
    parsed = mod.parse_closed_acceptance(
        ACCEPTANCE_PATH.read_bytes(),
        expected_ledger_digest=PINNED_ACCEPTANCE_LEDGER_DIGEST,
        requirements_digest=PINNED_REQUIREMENTS_DIGEST,
    )
    assert parsed.case_count == 192
    assert parsed.subcase_count == 5230
    parsed_profiles = mod.parse_runtime_profile_ledger(
        RUNTIME_PROFILE_LEDGER_PATH.read_bytes(),
        expected_ledger_digest=PINNED_RUNTIME_PROFILE_LEDGER_DIGEST,
        acceptance_ledger_digest=PINNED_ACCEPTANCE_LEDGER_DIGEST,
    )
    assert len(parsed_profiles.role_assignments) == 498
    target = tmp_path / "activation_acceptance.json"
    target.write_text('{"allow":true,"cases":[]}', encoding="utf-8")
    with pytest.raises(mod.ActivationAcceptanceRefused):
        mod.verify_acceptance_candidate(
            target,
            requirements_digest=PINNED_REQUIREMENTS_DIGEST,
            acceptance_ledger_digest=PINNED_ACCEPTANCE_LEDGER_DIGEST,
            runtime_profile_ledger_digest=PINNED_RUNTIME_PROFILE_LEDGER_DIGEST,
        )
    malformed = (
        b'{"invariant_id":"T1-01","invariant_id":"T1-02"}',
        b"[1.25]",
        b"[NaN]",
        b"[Infinity]",
        b'["\xff"]',
        b" " + ACCEPTANCE_PATH.read_bytes(),
    )
    for raw in malformed:
        with pytest.raises(mod.ActivationAcceptanceRefused):
            mod.parse_closed_acceptance(
                raw,
                expected_ledger_digest=PINNED_ACCEPTANCE_LEDGER_DIGEST,
                requirements_digest=PINNED_REQUIREMENTS_DIGEST,
            )


def test_ledger_reduction_duplicate_ids_and_any_exact_field_drift_are_refused():
    mod = _mod()
    records = _strict_json_bytes(ACCEPTANCE_PATH.read_bytes())
    attacks = []
    reduced = json.loads(json.dumps(records))
    reduced.pop()
    attacks.append(reduced)
    duplicate = json.loads(json.dumps(records))
    duplicate[-1] = duplicate[-2]
    attacks.append(duplicate)
    wrong_requirement = json.loads(json.dumps(records))
    wrong_requirement[0]["requirement_sha256"] = "0" * 64
    attacks.append(wrong_requirement)
    missing_subcase = json.loads(json.dumps(records))
    missing_subcase[0]["subcases"].pop()
    attacks.append(missing_subcase)
    changed_argument = json.loads(json.dumps(records))
    changed_argument[0]["subcases"][0]["broker_calls"][0]["args"]["forged"] = True
    attacks.append(changed_argument)
    changed_result = json.loads(json.dumps(records))
    changed_result[0]["subcases"][0]["broker_calls"][0]["expected_result"] = (
        "forged"
    )
    attacks.append(changed_result)
    unknown_field = json.loads(json.dumps(records))
    unknown_field[0]["unknown_authority"] = True
    attacks.append(unknown_field)
    for records_attack in attacks:
        with pytest.raises(mod.ActivationAcceptanceRefused):
            mod.parse_closed_acceptance(
                _canonical_json(records_attack),
                expected_ledger_digest=PINNED_ACCEPTANCE_LEDGER_DIGEST,
                requirements_digest=PINNED_REQUIREMENTS_DIGEST,
            )

    profiles = _strict_json_bytes(RUNTIME_PROFILE_LEDGER_PATH.read_bytes())
    profile_attacks = []
    missing_role = json.loads(json.dumps(profiles))
    missing_role["role_assignments"].pop(next(iter(missing_role["role_assignments"])))
    profile_attacks.append(missing_role)
    unknown_profile = json.loads(json.dumps(profiles))
    first_role = next(iter(unknown_profile["role_assignments"]))
    unknown_profile["role_assignments"][first_role] = "target_declared_profile"
    profile_attacks.append(unknown_profile)
    weakened_profile = json.loads(json.dumps(profiles))
    weakened_profile["profiles"][0]["network_mode"] = "host"
    profile_attacks.append(weakened_profile)
    for profile_attack in profile_attacks:
        with pytest.raises(mod.ActivationAcceptanceRefused):
            mod.parse_runtime_profile_ledger(
                _canonical_json(profile_attack),
                expected_ledger_digest=PINNED_RUNTIME_PROFILE_LEDGER_DIGEST,
                acceptance_ledger_digest=PINNED_ACCEPTANCE_LEDGER_DIGEST,
            )


def test_all_receipt_bindings_swaps_fabrication_and_replay_are_refused(external_run):
    mod, acceptance, _, raw_report, snapshot, observer = external_run

    def attacked_at(path, value):
        attacked = json.loads(json.dumps(raw_report))
        cursor = attacked
        for component in path[:-1]:
            cursor = cursor[component]
        cursor[path[-1]] = value
        return attacked

    mutations = (
        (("subcase_results", 0, "observation_id"), "forged-observation"),
        (("subcase_results", 0, "case_digest"), "0" * 64),
        (("subcase_results", 0, "subcase_digest"), "0" * 64),
        (("subcase_results", 0, "operation_digest"), "0" * 64),
        (("subcase_results", 0, "fault_digest"), "0" * 64),
        (("subcase_results", 0, "result_digest"), "0" * 64),
        (("subcase_results", 0, "status"), "fabricated-success"),
        (("subcase_results", 0, "completion_event_id"), "0" * 64),
        (("subcase_results", 0, "receipt", "signature_base64url"), "A" * 86),
        (
            ("subcase_results", 0, "receipt", "signed_payload", "run_nonce"),
            "0" * 64,
        ),
        (("probe_results", 0, "image_digest"), "0" * 64),
        (("probe_results", 0, "runtime_profile_digest"), "0" * 64),
        (("probe_results", 0, "broker_evidence", 0, "broker_event_id"), "0" * 64),
        (
            (
                "probe_results",
                0,
                "broker_evidence",
                0,
                "broker_event_hmac",
            ),
            "0" * 64,
        ),
        (("probe_results", 0, "broker_evidence", 0, "run_nonce"), "0" * 64),
        (
            ("probe_results", 0, "broker_evidence", 0, "challenge_digest"),
            "0" * 64,
        ),
    )
    for path, value in mutations:
        attacked = attacked_at(path, value)
        with pytest.raises((mod.ActivationInvariantFailed, AssertionError)):
            mod.validate_external_report(
                attacked,
                acceptance=acceptance,
                independent_observation=snapshot,
            )
            _assert_report_matches_parent_broker(attacked, observer)
            _assert_signed_report(attacked, acceptance.receipt_public_key)
    swapped = json.loads(json.dumps(raw_report))
    swapped["subcase_results"][0]["receipt"], swapped["subcase_results"][1]["receipt"] = (
        swapped["subcase_results"][1]["receipt"],
        swapped["subcase_results"][0]["receipt"],
    )
    with pytest.raises(mod.ActivationInvariantFailed):
        mod.validate_external_report(
            swapped,
            acceptance=acceptance,
            independent_observation=snapshot,
        )
    for observation_attack in (
        {**snapshot, "network_connections": 1},
        {**snapshot, "sibling_store_unchanged": False},
        {**snapshot, "completion_count": 5781},
        {**snapshot, "incomplete_observations": [next(iter(OBSERVATION_BY_ID))]},
        {**snapshot, "broker_evidence_root": "0" * 64},
        {**snapshot, "observation_digest": "0" * 64},
    ):
        with pytest.raises(mod.ActivationInvariantFailed):
            mod.validate_external_report(
                raw_report,
                acceptance=acceptance,
                independent_observation=observation_attack,
            )
    replay_guard = mod.EvidenceReplayGuard()
    mod.validate_external_report(
        raw_report,
        acceptance=acceptance,
        independent_observation=snapshot,
        replay_guard=replay_guard,
    )
    with pytest.raises(mod.ActivationInvariantFailed):
        mod.validate_external_report(
            raw_report,
            acceptance=acceptance,
            independent_observation=snapshot,
            replay_guard=replay_guard,
        )


def test_replay_is_durable_across_fresh_validator_processes(external_run):
    _, _, runtime, raw_report, snapshot, observer = external_run
    root = observer.root / "fresh-validator"
    root.mkdir()
    report_path = root / "report.json"
    observation_path = root / "observation.json"
    replay_store = root / "durable-replay.sqlite3"
    report_path.write_bytes(_canonical_json(raw_report))
    observation_path.write_bytes(_canonical_json(snapshot))
    command = [
        str(runtime.interpreter),
        "-I",
        "-S",
        str(runtime.harness_entrypoint),
        "--validate-closed-report",
        "--acceptance",
        str(runtime.acceptance_path),
        "--runtime-profiles",
        str(runtime.runtime_profile_ledger_path),
        "--report",
        str(report_path),
        "--observation",
        str(observation_path),
        "--replay-store",
        str(replay_store),
    ]
    first = subprocess.run(
        command,
        cwd=root,
        env={},
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert first.returncode == 0, f"stdout={first.stdout}\nstderr={first.stderr}"
    replay = subprocess.run(
        command,
        cwd=root,
        env={},
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert replay.returncode != 0
    assert "EvidenceReplay" in replay.stderr

    transplanted = dict(snapshot)
    transplanted["run_nonce"] = "0" * 64
    transplanted["observation_digest"] = hashlib.sha256(
        _canonical_json(
            {key: value for key, value in transplanted.items()
             if key != "observation_digest"}
        )
    ).hexdigest()
    observation_path.write_bytes(_canonical_json(transplanted))
    substituted = subprocess.run(
        [*command[:-1], str(root / "substitution-replay.sqlite3")],
        cwd=root,
        env={},
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert substituted.returncode != 0
    assert "ChallengeBindingMismatch" in substituted.stderr
