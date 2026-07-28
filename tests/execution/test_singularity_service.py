"""Inactive-by-default contracts for the installed Windows service host."""

from __future__ import annotations

import base64
import ctypes
import hashlib
import importlib
import json
import os
import shutil
import subprocess
import sys
import threading
from ctypes import wintypes
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "bootstrap" / "galaxy_launcher" / "singularity_service.py"
CLIENT = ROOT / "bootstrap" / "galaxy_launcher" / "singularity_admin_client.ps1"

_WAIT_OBJECT_0 = 0
_WAIT_ABANDONED = 0x80
_PIPE_TEST_MUTEX = "Local\\9to5-singularity-fixed-pipe-tests-v1"


@pytest.fixture
def fixed_pipe_lease():
    """Serialize tests that exercise the create-first production pipe name.

    The fixed pipe is a security property: a second server must fail instead of
    silently becoming another instance.  Xdist may otherwise schedule these
    integration tests on separate workers and make them race for that one name.
    A Windows mutex preserves the production invariant and is released by the
    OS even if a worker exits unexpectedly.
    """

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.ReleaseMutex.argtypes = (wintypes.HANDLE,)
    kernel32.ReleaseMutex.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.CreateMutexW(None, False, _PIPE_TEST_MUTEX)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    acquired = False
    try:
        wait_result = kernel32.WaitForSingleObject(handle, 55_000)
        if wait_result not in {_WAIT_OBJECT_0, _WAIT_ABANDONED}:
            raise TimeoutError("timed out waiting for the fixed-pipe test lease")
        acquired = True
        yield
    finally:
        if acquired and not kernel32.ReleaseMutex(handle):
            raise ctypes.WinError(ctypes.get_last_error())
        if not kernel32.CloseHandle(handle):
            raise ctypes.WinError(ctypes.get_last_error())


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _b64url(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def test_service_self_test_is_canonical_and_has_no_activation_authority(tmp_path):
    completed = subprocess.run(
        [sys.executable, "-I", "-S", str(SERVICE), "--self-test"],
        cwd=tmp_path,
        env={"SystemRoot": os.environ["SystemRoot"], "WINDIR": os.environ["WINDIR"]},
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    receipt = json.loads(completed.stdout)
    assert receipt == {
        "activation_authority": False,
        "accepted_commands": ["interrogate", "shutdown", "stop"],
        "schema": "galaxy.singularity-service-self-test/v1",
        "service_state": "stopped",
    }


def test_request_client_roundtrips_one_exact_framed_pipe_request(
    tmp_path, fixed_pipe_lease
):
    service = importlib.import_module("bootstrap.galaxy_launcher.singularity_service")
    anchor = importlib.import_module("bootstrap.galaxy_launcher.anchor")
    ready = threading.Event()
    observed = []
    failures = []
    identities = []
    powershell = Path(shutil.which("powershell.exe") or "")
    assert powershell.is_file()
    expected_client = service.ExpectedPipeClient(
        process_image_path=powershell.resolve(),
        process_image_sha256=hashlib.sha256(powershell.read_bytes()).hexdigest(),
        request_client_path=CLIENT.resolve(),
        request_client_sha256=hashlib.sha256(CLIENT.read_bytes()).hexdigest(),
    )
    current_sid = subprocess.run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value",
        ],
        text=True,
        capture_output=True,
        timeout=10,
        check=True,
    ).stdout.strip()
    pipe_sddl = service.build_pipe_sddl(current_sid, "S-1-5-80-1-1-1-1-1")
    response = _canonical(
        {
            "accepted": True,
            "authority_ceiling": "maintenance_only",
            "operation": "append-path-manifest",
            "production_active": False,
            "request_id": "request_" + "f" * 64,
            "result": {"next_sequence": 1},
            "schema": "galaxy.singularity-admin-response/v1",
        }
    )

    def handler(raw):
        parsed = anchor.parse_admin_request(raw)
        observed.append(parsed)
        return response

    def server():
        try:
            service.serve_pipe_once(
                handler,
                ready_event=ready,
                identity_validator=lambda handle: identities.append(
                    service.validate_pipe_client(handle, expected_client)
                ),
                security_sddl=pipe_sddl,
            )
        except BaseException as exc:  # surfaced in the parent test thread
            failures.append(exc)

    thread = threading.Thread(target=server, daemon=True)
    thread.start()
    assert ready.wait(5)
    arguments = _canonical(
        {
            "manifest_id": "manifest_" + "e" * 64,
            "scope": "source_" + "d" * 64,
            "sequence": 0,
        }
    )
    payload = _canonical(
        {
            "records": [{"path": "x.py", "role": "required-change"}],
            "sequence": 0,
        }
    )
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(CLIENT),
            "-RequestOnly",
            "-Operation",
            "append-path-manifest",
            "-ArgumentsBase64Url",
            _b64url(arguments),
            "-PayloadBase64Url",
            _b64url(payload),
            "-EnvelopeRequestId",
            "request_" + "f" * 64,
            "-RequireServerValidatedClientDigest",
            "-EmitCanonicalResponse",
        ],
        cwd=tmp_path,
        env={"SystemRoot": os.environ["SystemRoot"], "WINDIR": os.environ["WINDIR"]},
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    thread.join(5)

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.encode("utf-8").strip() == response
    assert not thread.is_alive()
    assert failures == []
    assert len(observed) == 1
    assert observed[0].arguments == json.loads(arguments)
    assert observed[0].payload == json.loads(payload)
    assert len(identities) == 1
    assert identities[0]["process_id"] > 0
    assert Path(identities[0]["process_image_path"]) == powershell.resolve()
    assert identities[0]["request_client_sha256"] == expected_client.request_client_sha256


def test_pipe_acl_is_closed_to_system_operator_and_restricted_service_only():
    service = importlib.import_module("bootstrap.galaxy_launcher.singularity_service")
    operator = "S-1-5-21-111-222-333-1001"
    restricted_service = "S-1-5-80-" + "-".join(["1"] * 5)
    sddl = service.build_pipe_sddl(operator, restricted_service)
    assert sddl == (
        "D:P(A;;GA;;;SY)"
        f"(A;;GRGW;;;{operator})"
        f"(A;;GA;;;{restricted_service})"
    )
    assert "WD" not in sddl and "AU" not in sddl and "AN" not in sddl


def test_request_client_canonicalizes_plan_style_flags_without_raw_json_argv(
    tmp_path, fixed_pipe_lease
):
    service = importlib.import_module("bootstrap.galaxy_launcher.singularity_service")
    anchor = importlib.import_module("bootstrap.galaxy_launcher.anchor")
    ready = threading.Event()
    observed = []
    failures = []

    def handler(raw):
        parsed = anchor.parse_admin_request(raw)
        observed.append(parsed)
        return _canonical(
            {
                "accepted": True,
                "authority_ceiling": "maintenance_only",
                "operation": parsed.operation,
                "production_active": False,
                "request_id": parsed.request_id,
                "result": {
                    "manifest_id": "manifest_" + "1" * 64,
                    "output": "manifest_" + "1" * 64,
                },
                "schema": "galaxy.singularity-admin-response/v1",
            }
        )

    def server():
        try:
            service.serve_pipe_once(handler, ready_event=ready)
        except BaseException as exc:
            failures.append(exc)

    thread = threading.Thread(target=server, daemon=True)
    thread.start()
    assert ready.wait(5)
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(CLIENT),
            "--request-only",
            "--require-server-validated-client-digest",
            "begin-path-manifest",
            "--scope",
            "source_" + "2" * 64,
            "--expected-total-count",
            "3",
            "--expected-required-count",
            "2",
            "--expected-test-count",
            "1",
        ],
        cwd=tmp_path,
        env={"SystemRoot": os.environ["SystemRoot"], "WINDIR": os.environ["WINDIR"]},
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    thread.join(5)

    assert completed.returncode == 0, completed.stderr
    assert failures == [] and not thread.is_alive()
    assert len(observed) == 1
    assert observed[0].operation == "begin-path-manifest"
    assert observed[0].arguments == {
        "expected_required_count": 2,
        "expected_test_count": 1,
        "expected_total_count": 3,
        "scope": "source_" + "2" * 64,
    }
    assert observed[0].payload == {}
    assert observed[0].request_id.startswith("request_")
    assert completed.stdout == "manifest_" + "1" * 64 + "\n"


def test_plan_style_client_drives_exact_durable_path_manifest_protocol(
    tmp_path, fixed_pipe_lease
):
    service = importlib.import_module("bootstrap.galaxy_launcher.singularity_service")
    anchor = importlib.import_module("bootstrap.galaxy_launcher.anchor")
    repository = tmp_path / "repo"
    repository.mkdir()
    processor = anchor.AdminCommandProcessor(
        tmp_path / "external", repository_root=repository
    )

    def invoke(*arguments):
        ready = threading.Event()
        failures = []

        def server():
            try:
                service.serve_pipe_once(processor.process, ready_event=ready)
            except BaseException as exc:
                failures.append(exc)

        thread = threading.Thread(target=server, daemon=True)
        thread.start()
        assert ready.wait(5)
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(CLIENT),
                "--request-only",
                "--require-server-validated-client-digest",
                *arguments,
            ],
            cwd=tmp_path,
            env={"SystemRoot": os.environ["SystemRoot"], "WINDIR": os.environ["WINDIR"]},
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
        thread.join(5)
        assert failures == [] and not thread.is_alive()
        assert completed.returncode == 0, completed.stderr
        return completed.stdout.strip()

    scope = "source_" + "3" * 64
    manifest_id = invoke(
        "begin-path-manifest",
        "--scope",
        scope,
        "--expected-total-count",
        "1",
        "--expected-required-count",
        "1",
        "--expected-test-count",
        "1",
    )
    assert manifest_id.startswith("manifest_")
    payload = _b64url(
        _canonical(
            {
                "records": [{"path": "tests/test_x.py", "role": "required-test"}],
                "sequence": 0,
            }
        )
    )
    assert (
        invoke(
            "append-path-manifest",
            "--scope",
            scope,
            "--manifest",
            manifest_id,
            "--sequence",
            "0",
            "--canonical-records-json-base64url",
            payload,
            "--require-strict-unpadded-base64url",
            "--require-decoded-canonical-json-max-bytes",
            "4096",
            "--require-decode-recanonicalize-byte-equality",
            "--require-exact-envelope-max-bytes",
            "8192",
        )
        == ""
    )
    receipt_id = invoke(
        "seal-path-manifest",
        "--scope",
        scope,
        "--manifest",
        manifest_id,
        "--canonical-order",
        "--sha256",
        "--require-total-count",
        "1",
        "--require-required-count",
        "1",
        "--require-test-count",
        "1",
        "--persist-and-reread",
    )
    assert receipt_id.startswith("pathmanifest_")
    receipts = list((tmp_path / "external" / "path-manifests" / "sealed").glob("*.json"))
    assert len(receipts) == 1
    assert json.loads(receipts[0].read_bytes())["test_paths"] == ["tests/test_x.py"]


def test_request_client_finds_closed_operation_after_authority_prefix(
    tmp_path, fixed_pipe_lease
):
    service = importlib.import_module("bootstrap.galaxy_launcher.singularity_service")
    anchor = importlib.import_module("bootstrap.galaxy_launcher.anchor")
    ready = threading.Event()
    observed = []
    failures = []

    def handler(raw):
        request = anchor.parse_admin_request(raw)
        observed.append(request)
        return _canonical(
            {
                "accepted": True,
                "authority_ceiling": "maintenance_only",
                "operation": request.operation,
                "production_active": False,
                "request_id": request.request_id,
                "result": {"output": ""},
                "schema": "galaxy.singularity-admin-response/v1",
            }
        )

    def server():
        try:
            service.serve_pipe_once(handler, ready_event=ready)
        except BaseException as exc:
            failures.append(exc)

    thread = threading.Thread(target=server, daemon=True)
    thread.start()
    assert ready.wait(5)
    purpose = "purpose_" + "a" * 64
    owner_fence = "ownerfence_" + "b" * 64
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(CLIENT),
            "--request-only",
            "--require-server-validated-client-digest",
            "--transition-purpose-receipt",
            purpose,
            "--transition-owner-fence-receipt",
            owner_fence,
            "--require-current-owner-fencing-generation",
            "begin-path-manifest",
            "--scope",
            "source_" + "c" * 64,
            "--expected-total-count",
            "1",
            "--expected-required-count",
            "0",
            "--expected-test-count",
            "0",
        ],
        cwd=tmp_path,
        env={"SystemRoot": os.environ["SystemRoot"], "WINDIR": os.environ["WINDIR"]},
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    thread.join(5)

    assert completed.returncode == 0, completed.stderr
    assert failures == [] and not thread.is_alive()
    assert len(observed) == 1
    assert observed[0].operation == "begin-path-manifest"
    assert observed[0].arguments["transition_purpose_receipt"] == purpose
    assert observed[0].arguments["transition_owner_fence_receipt"] == owner_fence
    assert observed[0].arguments["require_current_owner_fencing_generation"] is True


def test_request_client_refuses_response_authority_or_request_binding_drift(
    tmp_path, fixed_pipe_lease
):
    service = importlib.import_module("bootstrap.galaxy_launcher.singularity_service")
    ready = threading.Event()
    failures = []

    def handler(raw):
        del raw
        return _canonical(
            {
                "accepted": True,
                "authority_ceiling": "production",
                "operation": "begin-path-manifest",
                "production_active": True,
                "request_id": "request_" + "0" * 64,
                "result": {"output": "manifest_" + "1" * 64},
                "schema": "galaxy.singularity-admin-response/v1",
            }
        )

    def server():
        try:
            service.serve_pipe_once(handler, ready_event=ready)
        except BaseException as exc:
            failures.append(exc)

    thread = threading.Thread(target=server, daemon=True)
    thread.start()
    assert ready.wait(5)
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(CLIENT),
            "--request-only",
            "--require-server-validated-client-digest",
            "begin-path-manifest",
            "--scope",
            "source_" + "2" * 64,
            "--expected-total-count",
            "1",
            "--expected-required-count",
            "0",
            "--expected-test-count",
            "0",
        ],
        cwd=tmp_path,
        env={"SystemRoot": os.environ["SystemRoot"], "WINDIR": os.environ["WINDIR"]},
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    thread.join(5)

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "authority" in completed.stderr.casefold()
    assert failures == [] and not thread.is_alive()


def test_service_transport_rewrites_only_the_bound_anchor_operation(tmp_path):
    service = importlib.import_module("bootstrap.galaxy_launcher.singularity_service")
    powershell = Path(shutil.which("powershell.exe") or "").resolve()
    anchor_source = ROOT / "bootstrap" / "galaxy_launcher" / "singularity_anchor.ps1"
    client = service.ExpectedPipeClient(
        process_image_path=powershell,
        process_image_sha256=hashlib.sha256(powershell.read_bytes()).hexdigest(),
        request_client_path=CLIENT.resolve(),
        request_client_sha256=hashlib.sha256(CLIENT.read_bytes()).hexdigest(),
    )
    empty_working = tmp_path / "empty"
    empty_working.mkdir()
    boundary = service.AnchorLaunchBoundary(
        expected_client=client,
        anchor_path=anchor_source,
        anchor_sha256=hashlib.sha256(anchor_source.read_bytes()).hexdigest(),
        host_path=powershell,
        host_sha256=client.process_image_sha256,
        launch_arguments=(
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(anchor_source),
            "-ProtectedRecordPath",
            str(tmp_path / "anchor-record.json"),
            "-Operation",
            "diagnostic",
            "-ExpectedRecordSha256",
            "1" * 64,
        ),
        working_directory=empty_working,
        environment={"SystemRoot": os.environ["SystemRoot"], "WINDIR": os.environ["WINDIR"]},
        operator_sid="S-1-5-21-111-222-333-1001",
        service_sid="S-1-5-80-1-1-1-1-1",
    )
    raw = _canonical(
        {
            "arguments": {},
            "operation": "verify-self",
            "payload_base64url": _b64url(b"{}"),
            "request_id": "request_" + "1" * 64,
        }
    )
    expected = _canonical(
        {
            "accepted": True,
            "authority_ceiling": "maintenance_only",
            "operation": "verify-self",
            "production_active": False,
            "request_id": "request_" + "1" * 64,
            "result": {},
            "schema": "galaxy.singularity-admin-response/v1",
        }
    )
    observed = []

    def runner(command, **kwargs):
        observed.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout=expected + b"\n", stderr=b"")

    assert service.invoke_native_anchor(boundary, raw, runner=runner) == expected
    command, kwargs = observed[0]
    assert command[0] == str(powershell)
    operation_index = command.index("-Operation")
    assert command[operation_index + 1] == "maintenance"
    assert command[-2] == "-MaintenanceRequestBase64Url"
    assert base64.urlsafe_b64decode(command[-1] + "==") == raw
    assert kwargs["cwd"] == empty_working
    assert kwargs["env"] == boundary.environment
    assert kwargs["input"] == b""


def _installed_boundary_fixture(tmp_path):
    service = importlib.import_module("bootstrap.galaxy_launcher.singularity_service")
    external = tmp_path / "external"
    controller = external / "generations" / "00000001" / "controller"
    bootstrap = external / "generations" / "00000001" / "bootstrap"
    bin_root = external / "bin"
    tofu_root = external / "tofu"
    record_root = external / "repositories" / ("a" * 64)
    for directory in (controller, bootstrap, bin_root, tofu_root, record_root):
        directory.mkdir(parents=True, exist_ok=True)
    installed_service = controller / "singularity_service.py"
    installed_anchor = bootstrap / "singularity_anchor.ps1"
    installed_client = bin_root / "singularity-admin-client.ps1"
    shutil.copyfile(SERVICE, installed_service)
    shutil.copyfile(
        ROOT / "bootstrap" / "galaxy_launcher" / "singularity_anchor.ps1",
        installed_anchor,
    )
    shutil.copyfile(CLIENT, installed_client)
    powershell = Path(shutil.which("powershell.exe") or "").resolve()
    empty = record_root / "empty-cwd"
    empty.mkdir()
    anchor_record = record_root / "anchor-record.json"
    anchor_record.write_bytes(b"{}")
    launch_record = {
        "activation_state": "inactive",
        "anchor_path": str(installed_anchor),
        "anchor_sha256": hashlib.sha256(installed_anchor.read_bytes()).hexdigest(),
        "arguments": [
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(installed_anchor),
            "-ProtectedRecordPath",
            str(anchor_record),
            "-Operation",
            "diagnostic",
            "-ExpectedRecordSha256",
            hashlib.sha256(anchor_record.read_bytes()).hexdigest(),
            "-ExpectedHostPath",
            str(powershell),
            "-ExpectedHostSha256",
            hashlib.sha256(powershell.read_bytes()).hexdigest(),
        ],
        "control_pipe": r"\\.\pipe\9to5-singularity-v1",
        "environment": {
            "PATH": "",
            "PSModulePath": "",
            "SystemRoot": os.environ["SystemRoot"],
            "WINDIR": os.environ["WINDIR"],
        },
        "host_path": str(powershell),
        "host_sha256": hashlib.sha256(powershell.read_bytes()).hexdigest(),
        "host_signature": {
            "is_os_binary": True,
            "signature_type": "Catalog",
            "signer_subject": "CN=Microsoft Windows, test",
            "signer_thumbprint": "1" * 40,
            "status": "Valid",
        },
        "host_signature_sha256": "2" * 64,
        "schema": "galaxy.singularity-anchor-launch/v1",
        "service_name": "9to5Singularity",
        "stdio": {"stderr": "null", "stdin": "null", "stdout": "null"},
        "working_directory": str(empty),
    }
    launch_path = record_root / "anchor-launch-record.json"
    launch_path.write_bytes(_canonical(launch_record))

    def leaf(logical, path):
        return {
            "installed_path": str(path),
            "logical_path": logical,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size": path.stat().st_size,
        }

    source_leaves = [
        leaf("bootstrap/singularity_admin_client.ps1", installed_client),
        leaf("bootstrap/singularity_anchor.ps1", installed_anchor),
    ]
    artifact_leaves = [leaf("system/powershell.exe", powershell)]
    runtime_digest = "3" * 64
    receipt = {
        "schema": "galaxy.trust-on-first-install/v1",
        "status": "installed_inactive",
        "source_leaves": source_leaves,
        "artifact_leaves": artifact_leaves,
        "source_root": "4" * 64,
        "artifact_root": "5" * 64,
        "merkle_root": "6" * 64,
        "nonce": "7" * 64,
        "challenge": "TRUST",
        "approval_response_sha256": "8" * 64,
        "runtime_digest": runtime_digest,
        "image_digests": {},
        "activation_acceptance_sha256": "9" * 64,
        "activation_runtime_profiles_sha256": "a" * 64,
        "activation_adapter_sha256": "b" * 64,
        "activation_receipt_public_key": "c" * 64,
        "activation_receipt_public_key_digest": "d" * 64,
        "monotone_generation": 1,
        "dacl_sddl": "O:SYD:P",
        "operator_sid": "S-1-5-21-111-222-333-1001",
        "service_sid": "S-1-5-80-1-1-1-1-1",
        "service_name": "9to5Singularity",
        "repository_identity": "a" * 64,
        "anchor_record_path": str(anchor_record),
        "anchor_launch_record_path": str(launch_path),
        "anchor_launch_record_sha256": hashlib.sha256(launch_path.read_bytes()).hexdigest(),
        "host_signature_sha256": "2" * 64,
        "activation_state": "inactive",
    }
    receipt_path = tofu_root / "receipt-00000001.json"
    receipt_path.write_bytes(_canonical(receipt))
    runtime_lock = {
        "schema": "galaxy.activation.sealed-runtime/v1",
        "status": "installed_inactive",
        "generation": 1,
        "external_root": str(external),
        "files": {
            "interpreter": str(Path(sys.executable).resolve()),
            "service_host": str(installed_service),
        },
        "file_digests": {
            "interpreter": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
            "service_host": hashlib.sha256(installed_service.read_bytes()).hexdigest(),
        },
        "runtime_digest": runtime_digest,
        "image_digests": {},
        "image_archive_paths": {},
        "tofu_receipt_path": str(receipt_path),
        "security_profiles": {},
        "max_probe_concurrency": 1,
    }
    (controller / "runtime.lock.json").write_bytes(_canonical(runtime_lock))
    return service, installed_service, installed_client, powershell


def test_service_resolves_launch_boundary_only_from_exact_installed_closure(tmp_path):
    service, installed_service, installed_client, powershell = _installed_boundary_fixture(
        tmp_path
    )
    boundary = service.resolve_anchor_launch_boundary(
        service_path=installed_service,
        process_image_path=Path(sys.executable),
    )
    assert boundary.host_path == powershell
    assert boundary.anchor_path.name == "singularity_anchor.ps1"
    assert boundary.expected_client.request_client_path == installed_client
    assert boundary.operator_sid == "S-1-5-21-111-222-333-1001"
    assert boundary.service_sid == "S-1-5-80-1-1-1-1-1"
    assert boundary.working_directory.is_dir()

    installed_client.write_text("tampered", encoding="utf-8")
    with pytest.raises((OSError, ValueError)):
        service.resolve_anchor_launch_boundary(
            service_path=installed_service,
            process_image_path=Path(sys.executable),
        )
