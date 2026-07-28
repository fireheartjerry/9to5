"""RED behavioral tests for protected-record and host isolation at the anchor."""
from __future__ import annotations

import base64
import hashlib
import importlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
NATIVE_ANCHOR = ROOT / "bootstrap" / "galaxy_launcher" / "singularity_anchor.ps1"
PYTHON_ANCHOR = ROOT / "bootstrap" / "galaxy_launcher" / "anchor.py"


def _mod():
    return importlib.import_module("bootstrap.galaxy_launcher.anchor")


def _canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _b64url(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _admin_request(operation, *, arguments, payload, request_digit):
    return _canonical(
        {
            "arguments": arguments,
            "operation": operation,
            "payload_base64url": _b64url(_canonical(payload)),
            "request_id": "request_" + request_digit * 64,
        }
    )


def test_admin_durable_publications_sync_parent_directory_entries(tmp_path, monkeypatch):
    mod = _mod()
    calls = []

    def sync(path):
        calls.append(Path(path).resolve())

    monkeypatch.setattr(mod, "_sync_admin_directory", sync)
    root = tmp_path / "durable"
    root.mkdir()
    mod._atomic_json(root / "atomic.json", {"schema": "atomic/v1"})
    mod._exclusive_sealed_json(root / "sealed.json", {"schema": "sealed/v1"})
    mod._exclusive_admin_bytes(root / "payload.bin", b"payload", label="payload")

    assert calls == [root.resolve(), root.resolve(), root.resolve()]


def test_admin_processor_serializes_requests_across_processes(tmp_path):
    mod = _mod()
    assert hasattr(mod, "_RepositoryAdminLock")
    repository = tmp_path / "repo"
    repository.mkdir()
    admin = tmp_path / "external" / "admin" / ("a" * 64)
    admin.mkdir(parents=True)
    request_path = tmp_path / "request.json"
    request_path.write_bytes(
        _admin_request(
            "resolve-current-top-level-transition",
            arguments={
                "print_none_or_bound_purpose_receipt": True,
                "read_only": True,
                "repo": str(repository.resolve()),
                "repository_global_all_generations": True,
                "require_unique_live_slot": True,
            },
            payload={},
            request_digit="f",
        )
    )
    ready = tmp_path / "lock-ready"
    release = tmp_path / "lock-release"
    response = tmp_path / "response.json"
    locker_code = (
        "import time\n"
        "from pathlib import Path\n"
        "from bootstrap.galaxy_launcher.anchor import _RepositoryAdminLock\n"
        f"lock=_RepositoryAdminLock(Path({str(admin)!r})/'.repository-admin.lock')\n"
        "with lock.hold(timeout=5):\n"
        f" Path({str(ready)!r}).write_text('ready', encoding='ascii')\n"
        f" while not Path({str(release)!r}).exists(): time.sleep(0.01)\n"
    )
    worker_code = (
        "from pathlib import Path\n"
        "from bootstrap.galaxy_launcher.anchor import AdminCommandProcessor\n"
        f"processor=AdminCommandProcessor(Path({str(admin)!r}), repository_root=Path({str(repository)!r}))\n"
        f"Path({str(response)!r}).write_bytes(processor.process(Path({str(request_path)!r}).read_bytes()))\n"
    )
    locker = subprocess.Popen(
        [sys.executable, "-c", locker_code],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    worker = None
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and locker.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists(), locker.communicate(timeout=1)[1]
        worker = subprocess.Popen(
            [sys.executable, "-c", worker_code],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        time.sleep(0.25)
        assert worker.poll() is None
        assert not response.exists()
        release.write_text("release", encoding="ascii")
        worker_stdout, worker_stderr = worker.communicate(timeout=10)
        locker_stdout, locker_stderr = locker.communicate(timeout=10)
        assert worker.returncode == 0, (worker_stdout, worker_stderr)
        assert locker.returncode == 0, (locker_stdout, locker_stderr)
    finally:
        release.touch(exist_ok=True)
        for process in (worker, locker):
            if process is not None and process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
    parsed = json.loads(response.read_bytes())
    assert parsed["accepted"] is True
    assert parsed["result"]["purpose_id"] == "none"


def test_contained_admin_runtime_batches_sha1dc_and_isolates_reviewer(tmp_path):
    mod = _mod()
    external = (tmp_path / "installed").resolve()
    repository = external / "registered-repository"
    admin = external / "admin" / ("a" * 64)
    object_root = admin / "source-commits" / "proposal-objects"
    for directory in (repository, object_root):
        directory.mkdir(parents=True)
    runtime = SimpleNamespace(
        external_root=external,
        generation=7,
        tofu_merkle_root="b" * 64,
        runtime_digest="c" * 64,
        object_parser_entrypoint_digest="d" * 64,
        reviewer_digest="e" * 64,
        image_digests={"object_parser": "f" * 64, "reviewer": "1" * 64},
    )
    calls: list[dict[str, object]] = []

    def role_runner(
        actual_runtime,
        *,
        role,
        runtime_argv,
        input_mounts,
        writable_mounts,
        invocation_root,
    ):
        assert actual_runtime is runtime
        calls.append(
            {
                "role": role,
                "argv": tuple(runtime_argv),
                "inputs": tuple(input_mounts),
                "writable": tuple(writable_mounts),
                "root": invocation_root,
            }
        )
        mounts = {target: Path(source) for source, target in input_mounts}
        if role == "object_parser":
            request_path = mounts["/galaxy-input"] / "request.json"
            request = json.loads(request_path.read_bytes())
            payload_root = mounts["/galaxy-objects"]
            records = []
            for item in request["records"]:
                digest = item["payload_sha256"]
                payload = (payload_root / digest[:2] / digest).read_bytes()
                frame = (
                    f"{item['object_type']} {len(payload)}".encode("ascii")
                    + b"\0"
                    + payload
                )
                records.append(
                    {
                        **item,
                        "oid": hashlib.sha1(
                            frame, usedforsecurity=False
                        ).hexdigest(),
                        "frame_sha256": hashlib.sha256(frame).hexdigest(),
                    }
                )
            result = {
                "schema": "galaxy.object-hash-batch-result/v1",
                "batch_id": request["batch_id"],
                "request_sha256": hashlib.sha256(
                    request_path.read_bytes()
                ).hexdigest(),
                "records": records,
                "parser_version_digest": runtime.object_parser_entrypoint_digest,
                "network_allowed": False,
            }
            return SimpleNamespace(
                role=role,
                image_digest=runtime.image_digests[role],
                runtime_digest=runtime.runtime_digest,
                entrypoint_digest=runtime.object_parser_entrypoint_digest,
                security_profile_digest="2" * 64,
                stdout=_canonical(result) + b"\n",
                stderr=b"",
            )
        request_path = mounts["/galaxy-input"] / "request.json"
        request = json.loads(request_path.read_bytes())
        proposal = json.loads((mounts["/galaxy-input"] / "proposal.json").read_bytes())
        observation = {
            "canonical_write_observed": False,
            "decision": "accept",
            "findings": [],
            "independent": True,
            "network_enabled": False,
            "pass_index": request["pass_index"],
            "proposal_id": proposal["proposal_id"],
            "proposal_record_sha256": proposal["record_sha256"],
            "reviewer_image_digest": request["reviewer_image_digest"],
            "reviewer_qualification_receipt_id": request[
                "reviewer_qualification_receipt_id"
            ],
            "reviewer_runtime_sha256": request["reviewer_runtime_sha256"],
            "reviewer_session_id": request["reviewer_session_id"],
            "schema": "galaxy.independent-source-review/v1",
            "source_execution_observed": False,
        }
        return SimpleNamespace(
            role=role,
            image_digest=runtime.image_digests[role],
            runtime_digest=runtime.runtime_digest,
            entrypoint_digest=runtime.reviewer_digest,
            security_profile_digest="3" * 64,
            stdout=_canonical(observation) + b"\n",
            stderr=b"",
        )

    adapter = mod.AdminContainedRuntime(
        external_root=external,
        admin_root=admin,
        repository_root=repository,
        repository_identity="a" * 64,
        trust_receipt_id="tofu_" + "4" * 64,
        runtime=runtime,
        role_runner=role_runner,
    )
    objects = (("blob", b"alpha\n"), ("tree", b""))
    first = adapter.hash_objects(objects)
    second = adapter.hash_objects(objects)
    assert first == second
    assert first == tuple(
        hashlib.sha1(
            f"{kind} {len(payload)}".encode("ascii") + b"\0" + payload,
            usedforsecurity=False,
        ).hexdigest()
        for kind, payload in objects
    )
    proposal = {
        "proposal_id": "proposal_" + "5" * 64,
        "record_sha256": "6" * 64,
    }
    review_one = adapter.review_proposal(proposal, 1)
    replay = adapter.review_proposal(proposal, 1)
    review_two = adapter.review_proposal(proposal, 2)
    assert replay == review_one
    assert review_one["reviewer_session_id"] != review_two["reviewer_session_id"]
    reviewer_calls = [call for call in calls if call["role"] == "reviewer"]
    assert len(reviewer_calls) == 3
    for call in reviewer_calls:
        assert call["writable"] == ()
        assert {target for _source, target in call["inputs"]} == {
            "/galaxy-input",
            "/galaxy-objects",
        }
        assert "--source-proposal" in call["argv"]
        assert "/opt/galaxy/galaxy-sha1dc" in call["argv"]
    qualification = list((admin / "contained-runtime" / "qualifications").glob("*.json"))
    assert len(qualification) == 1
    assert json.loads(qualification[0].read_bytes())["authority"] is False


def test_source_proposal_hashes_blobs_and_tree_levels_in_batches(tmp_path):
    mod = _mod()
    repository = tmp_path / "repo"
    repository.mkdir()
    calls: list[tuple[tuple[str, bytes], ...]] = []

    def batch_hasher(objects):
        batch = tuple(objects)
        calls.append(batch)
        return tuple(
            hashlib.sha1(
                f"{kind} {len(payload)}".encode("ascii") + b"\0" + payload,
                usedforsecurity=False,
            ).hexdigest()
            for kind, payload in batch
        )

    store = mod.AdminSourceCommitStore(
        tmp_path / "external" / "source-commits",
        repository_root=repository,
        transitions=SimpleNamespace(repository_root=repository.resolve()),
        path_manifests=SimpleNamespace(repository_root=repository.resolve()),
        object_hasher=lambda *_args: pytest.fail("single-object hasher used"),
        object_batch_hasher=batch_hasher,
    )
    current = [
        {
            "blob_sha256": hashlib.sha256(payload).hexdigest(),
            "mode": 0o100644,
            "path": path,
            "payload": payload,
            "size": len(payload),
        }
        for path, payload in (
            ("a.txt", b"a\n"),
            ("pkg/b.txt", b"b\n"),
            ("pkg/deep/c.txt", b"c\n"),
        )
    ]

    tree_oid, commit_oid, commit_payload, objects = store._build_git_objects(
        current,
        parent_oid="a" * 40,
        message="feat: batch exact source",
    )

    assert len(calls) == 10  # every batch is independently repeated
    assert calls[::2] == calls[1::2]
    logical_calls = calls[::2]
    assert [kind for kind, _payload in logical_calls[0]] == ["blob", "blob", "blob"]
    assert all(kind == "tree" for batch in logical_calls[1:4] for kind, _ in batch)
    assert logical_calls[-1] == (("commit", commit_payload),)
    assert tree_oid in objects and commit_oid in objects
    assert commit_oid == batch_hasher((("commit", commit_payload),))[0]


@pytest.mark.parametrize("packed", [False, True])
@pytest.mark.parametrize("linked", [False, True])
def test_contained_admin_runtime_snapshots_parent_objects_without_git_mount(
    tmp_path, packed, linked
):
    mod = _mod()
    external = (tmp_path / "installed").resolve()
    primary = external / ("primary" if linked else "repo")
    primary.mkdir(parents=True)
    subprocess.run(
        ["git", "-c", "init.defaultBranch=main", "init"],
        cwd=primary,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Parent"], cwd=primary, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "parent@example.invalid"],
        cwd=primary,
        check=True,
    )
    (primary / "foo").mkdir()
    (primary / "foo" / "inside.txt").write_bytes(b"tree\n")
    (primary / "foo.bar").write_bytes(b"file-before-tree\n")
    (primary / "README.md").write_bytes(b"read\n")
    (primary / "empty.txt").write_bytes(b"")
    subprocess.run(["git", "add", "."], cwd=primary, check=True)
    subprocess.run(
        ["git", "commit", "-m", "parent"],
        cwd=primary,
        check=True,
        capture_output=True,
    )
    parent_oid = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=primary,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if packed:
        subprocess.run(
            ["git", "repack", "-ad"],
            cwd=primary,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "prune-packed"],
            cwd=primary,
            check=True,
            capture_output=True,
        )
    repository = primary
    if linked:
        repository = external / "repo"
        subprocess.run(
            [
                "git",
                "worktree",
                "add",
                "-b",
                "source-update-test",
                str(repository),
                parent_oid,
            ],
            cwd=primary,
            check=True,
            capture_output=True,
        )
    admin = external / "admin" / ("a" * 64)
    (admin / "source-commits" / "proposal-objects").mkdir(parents=True)
    runtime = SimpleNamespace(
        external_root=external,
        generation=9,
        tofu_merkle_root="b" * 64,
        runtime_digest="c" * 64,
        object_parser_entrypoint_digest=hashlib.sha256(
            (ROOT / "containers/galaxy/object_parser_entrypoint.py").read_bytes()
        ).hexdigest(),
        reviewer_digest="e" * 64,
        image_digests={"object_parser": "f" * 64, "reviewer": "1" * 64},
    )
    observed_mounts: list[tuple[tuple[Path, str], ...]] = []
    observed_operations: list[str] = []

    def role_runner(
        actual_runtime,
        *,
        role,
        runtime_argv,
        input_mounts,
        writable_mounts,
        invocation_root,
    ):
        assert actual_runtime is runtime
        assert role == "object_parser"
        observed_mounts.append(tuple(input_mounts))
        observed_operations.append(str(runtime_argv[0]))
        inputs = {target: Path(source) for source, target in input_mounts}
        outputs = {target: Path(source) for source, target in writable_mounts}
        assert runtime_argv[0] in {
            "source-object-locate",
            "source-object-frontier",
        }
        git_executable = shutil.which("git")
        assert git_executable is not None
        translations = {
            "/opt/galaxy/galaxy-sha1dc": git_executable,
            "/galaxy-input/request.json": str(
                inputs["/galaxy-input"] / "request.json"
            ),
            "/galaxy-catalog": str(inputs.get("/galaxy-catalog", "")),
            "/galaxy-raw": str(inputs.get("/galaxy-raw", "")),
            "/galaxy-output": str(outputs.get("/galaxy-output", "")),
        }
        local_argv = [translations.get(str(value), str(value)) for value in runtime_argv]
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                "-S",
                str(ROOT / "containers/galaxy/object_parser_entrypoint.py"),
                *local_argv,
            ],
            cwd=inputs["/galaxy-input"],
            env={},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr.decode(errors="replace")
        return SimpleNamespace(
            role=role,
            image_digest=runtime.image_digests[role],
            runtime_digest=runtime.runtime_digest,
            entrypoint_digest=runtime.object_parser_entrypoint_digest,
            security_profile_digest="2" * 64,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    adapter = mod.AdminContainedRuntime(
        external_root=external,
        admin_root=admin,
        repository_root=repository,
        repository_identity="a" * 64,
        trust_receipt_id="tofu_" + "4" * 64,
        runtime=runtime,
        role_runner=role_runner,
    )

    manifest = adapter.load_parent_manifest(repository)
    replay = adapter.load_parent_manifest(repository)

    assert replay == manifest
    assert manifest["schema"] == "galaxy.admin-parent-manifest/v1"
    assert manifest["parent_oid"] == parent_oid
    assert manifest["contained_parser_receipt_id"].startswith("parserreceipt_")
    assert "source-object-locate" in observed_operations
    assert "source-object-frontier" in observed_operations
    assert [(entry["path"], entry["blob_sha256"]) for entry in manifest["entries"]] == [
        ("README.md", hashlib.sha256(b"read\n").hexdigest()),
        ("empty.txt", hashlib.sha256(b"").hexdigest()),
        ("foo.bar", hashlib.sha256(b"file-before-tree\n").hexdigest()),
        ("foo/inside.txt", hashlib.sha256(b"tree\n").hexdigest()),
    ]
    for mounts in observed_mounts:
        for source, _target in mounts:
            assert Path(source).is_relative_to(admin / "contained-runtime")
            assert not Path(source).is_relative_to(repository / ".git")
    if not packed and not linked:
        unknown = primary / ".git" / "objects" / "info" / "authority-like"
        unknown.write_bytes(b"not a derived accelerator\n")
        with pytest.raises(mod.AdminProtocolRefused, match="object info"):
            adapter.load_parent_manifest(repository)


@dataclass
class AnchorArtifacts:
    record: object
    original_record: object
    record_path: Path
    capsule: Path
    manifest: Path
    generation: Path


def _fixture(mod, root, *, generation=1, activation_state="inactive"):
    root.mkdir()
    capsule_dir = root / "capsule"
    capsule_dir.mkdir()
    capsule = capsule_dir / "controller.pyz"
    capsule.write_bytes(b"sealed controller capsule")
    manifest = root / "runtime-manifest.json"
    manifest.write_text('{"schema":1,"closed":true}', encoding="utf-8")
    generation_path = root / "generation"
    generation_path.write_text(str(generation), encoding="ascii")
    record_path = root / "anchor-record.json"
    mapping = {
        "schema": 1,
        "capsule_path": str(capsule),
        "capsule_sha256": hashlib.sha256(capsule.read_bytes()).hexdigest(),
        "runtime_manifest_path": str(manifest),
        "runtime_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "generation_path": str(generation_path),
        "generation": generation,
        "activation_state": activation_state,
    }
    record_path.write_text(json.dumps(mapping, sort_keys=True, separators=(",", ":")),
                           encoding="utf-8")
    record = mod.ProtectedAnchorRecord.load(record_path, no_follow=True)
    return AnchorArtifacts(record, record, record_path, capsule, manifest, generation_path)


def _create_junction(link, target):
    cp = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
                        text=True, capture_output=True, timeout=10)
    assert cp.returncode == 0, f"junction creation failed\nstdout={cp.stdout}\nstderr={cp.stderr}"


def _attack(fixture, attack, tmp_path):
    if attack == "capsule":
        fixture.capsule.write_bytes(b"replaced")
    elif attack == "manifest":
        fixture.manifest.write_bytes(b"replaced")
    elif attack == "generation":
        fixture.generation.write_text("999", encoding="ascii")
    else:
        original_dir = fixture.capsule.parent
        displaced = tmp_path / "displaced-capsule"
        original_dir.rename(displaced)
        outside = tmp_path / "outside-capsule"
        outside.mkdir()
        (outside / fixture.capsule.name).write_bytes(b"sealed controller capsule")
        _create_junction(original_dir, outside)
        return original_dir
    return None


def test_anchor_verifies_digest_generation_and_inactive_state_before_start(tmp_path):
    mod = _mod()
    fixture = _fixture(mod, tmp_path / "anchor", generation=3)
    starts = []
    with pytest.raises(mod.TransactionalKernelInactive):
        mod.SingularityAnchor(fixture.record).launch("fresh", starter=lambda **kw: starts.append(kw))
    assert starts == []


@pytest.mark.parametrize("attack", ["capsule", "manifest", "generation", "junction"])
def test_simultaneous_replacement_generation_and_reparse_attacks_never_start(attack, tmp_path):
    mod = _mod()
    fixture = _fixture(mod, tmp_path / "anchor", generation=5, activation_state="active")
    junction = _attack(fixture, attack, tmp_path)
    starts = []
    try:
        with pytest.raises(mod.AnchorIntegrityRefused):
            mod.SingularityAnchor(fixture.record).launch(
                "resume", starter=lambda **kw: starts.append(kw))
        assert starts == []
    finally:
        if junction is not None and junction.exists():
            os.rmdir(junction)


def test_poisoned_cwd_env_profiles_and_import_paths_are_not_inherited(tmp_path):
    mod = _mod()
    fixture = _fixture(mod, tmp_path / "anchor", activation_state="active")
    captured = []
    mod.SingularityAnchor(fixture.record).launch(
        "diagnostic", inherited_env={"PYTHONPATH": "poison", "PATH": "poison",
                                     "PROMPT": "poison", "HOME": str(tmp_path)},
        inherited_cwd=tmp_path, starter=lambda **kw: captured.append(kw))
    launch = captured[0]
    assert launch["cwd"] != tmp_path and list(launch["cwd"].iterdir()) == []
    assert "PYTHONPATH" not in launch["env"] and launch["env"].get("PATH") != "poison"
    assert launch["flags"] == ["-I", "-S"]
    assert launch["stdin"] == launch["stdout"] == launch["stderr"] == "DEVNULL"


def test_combined_capsule_sidecar_generation_attack_and_preanchor_readiness_refuse(tmp_path):
    mod = _mod()
    fixture = _fixture(mod, tmp_path / "anchor", generation=7, activation_state="active")
    fixture.capsule.write_bytes(b"replaced")
    fixture.manifest.write_bytes(b"replaced")
    fixture.generation.write_text("8", encoding="ascii")
    starts = []
    with pytest.raises(mod.AnchorIntegrityRefused):
        mod.SingularityAnchor(fixture.record).launch("fresh", starter=lambda **kw: starts.append(kw))
    assert starts == []
    legacy = mod.PreAnchorLegacyReadiness(processes=[123], listeners=["discord"])
    with pytest.raises(mod.PreAnchorGenerationRefused):
        mod.SingularityAnchor(fixture.original_record).accept_readiness(legacy)


def _native_anchor_command(record_path, operation="fresh"):
    powershell = shutil.which("powershell.exe")
    assert powershell and NATIVE_ANCHOR.is_file()
    framework = "Framework64" if sys.maxsize > 2**32 else "Framework"
    assembly = (
        Path(os.environ["WINDIR"])
        / "Microsoft.NET"
        / framework
        / "v4.0.30319"
        / "System.Web.Extensions.dll"
    )
    assert assembly.is_file()

    def digest(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    locker = importlib.import_module("tools.lock_galaxy_runtime")
    signature = locker._powershell_signature_record(Path(powershell))
    signature_digest = hashlib.sha256(locker._canonical(signature)).hexdigest()
    return [
        powershell,
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-File",
        str(NATIVE_ANCHOR),
        "-ProtectedRecordPath",
        str(record_path),
        "-Operation",
        operation,
        "-ExpectedRecordSha256",
        digest(record_path),
        "-ExpectedHostPath",
        powershell,
        "-ExpectedHostSha256",
        digest(powershell),
        "-ExpectedHostSignatureSha256",
        signature_digest,
        "-ExpectedAnchorSha256",
        digest(NATIVE_ANCHOR),
        "-JsonAssemblyPath",
        str(assembly),
        "-ExpectedJsonAssemblySha256",
        digest(assembly),
    ]


def test_native_anchor_contract_is_pre_python_closed_and_authority_free(tmp_path):
    powershell = shutil.which("powershell.exe")
    assert powershell and NATIVE_ANCHOR.is_file()
    source = NATIVE_ANCHOR.read_text(encoding="utf-8")
    for forbidden in (
        "Invoke-Expression",
        "Import-Module",
        "Get-Command",
        "New-Object",
        "ConvertFrom-Json",
        "Start-Process",
        "System.Management.Automation.SignatureHelper",
    ):
        assert forbidden.casefold() not in source.casefold()
    assert "Microsoft.PowerShell.Security\\Get-AuthenticodeSignature" in source
    assert source.index("Close-AmbientEnvironment $windowsRoot") < source.index(
        "$hostSignature = Get-PinnedHostSignatureRecord $actualHost"
    )
    result = subprocess.run(
        [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(NATIVE_ANCHOR),
            "-SelfTestContract",
        ],
        cwd=tmp_path,
        env={"SystemRoot": os.environ["SystemRoot"], "WINDIR": os.environ["WINDIR"]},
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert json.loads(result.stdout) == {
        "activation_authority": False,
        "ambient_command_resolution": False,
        "inherited_environment": False,
        "inherited_stdio": False,
        "pre_python": True,
        "schema": "galaxy.singularity-anchor-self-test/v1",
        "supported_operations": ["diagnostic", "fresh", "maintenance", "resume"],
    }


def test_native_anchor_verifies_inactive_record_and_never_launches_capsule(tmp_path):
    mod = _mod()
    fixture = _fixture(mod, tmp_path / "native-anchor", activation_state="inactive")
    goldstone = tmp_path / "capsule-started"
    fixture.capsule.write_text(
        f"from pathlib import Path; Path({str(goldstone)!r}).write_text('bad')",
        encoding="utf-8",
    )
    mapping = json.loads(fixture.record_path.read_text(encoding="utf-8"))
    mapping["capsule_sha256"] = hashlib.sha256(fixture.capsule.read_bytes()).hexdigest()
    fixture.manifest.write_text(
        json.dumps(
            {
                "activation_state": "inactive",
                "closed": True,
                "generation": 1,
                "runtime_digest": "4" * 64,
                "runtime_lock_path": str(tmp_path / "never-opened-runtime.lock.json"),
                "runtime_lock_sha256": "5" * 64,
                "schema": 1,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    mapping["runtime_manifest_sha256"] = hashlib.sha256(
        fixture.manifest.read_bytes()
    ).hexdigest()
    fixture.record_path.write_text(
        json.dumps(mapping, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    result = subprocess.run(
        _native_anchor_command(fixture.record_path),
        cwd=tmp_path,
        env={
            "PATH": "poison",
            "PSModulePath": "poison",
            "PYTHONPATH": "poison",
            "SystemRoot": os.environ["SystemRoot"],
            "WINDIR": os.environ["WINDIR"],
        },
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 78
    assert "TransactionalKernelInactive" in result.stderr
    assert not goldstone.exists()


def test_native_anchor_refuses_host_signature_record_substitution(tmp_path):
    mod = _mod()
    fixture = _fixture(mod, tmp_path / "native-signature", activation_state="inactive")
    command = _native_anchor_command(fixture.record_path, operation="diagnostic")
    digest_index = command.index("-ExpectedHostSignatureSha256") + 1
    command[digest_index] = "0" * 64

    result = subprocess.run(
        command,
        cwd=tmp_path,
        env={"SystemRoot": os.environ["SystemRoot"], "WINDIR": os.environ["WINDIR"]},
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert result.returncode == 79
    assert "host signature" in result.stderr.casefold()


def test_admin_request_envelope_is_canonical_bounded_and_has_no_run_authority():
    mod = _mod()
    payload = _canonical(
        {
            "records": [{"path": "platform_core/runtime/candidate.py", "role": "required-change"}],
            "sequence": 0,
        }
    )
    request = {
        "arguments": {
            "manifest_id": "manifest_" + "9" * 64,
            "scope": "source_" + "8" * 64,
            "sequence": 0,
        },
        "operation": "append-path-manifest",
        "payload_base64url": _b64url(payload),
        "request_id": "request_" + "1" * 64,
    }
    raw = _canonical(request)

    parsed = mod.parse_admin_request(raw)

    assert parsed.operation == "append-path-manifest"
    assert parsed.request_id == request["request_id"]
    assert parsed.arguments == request["arguments"]
    assert parsed.payload == json.loads(payload)
    assert parsed.canonical_bytes == raw
    for forbidden in ("run", "activate", "launch", "issue-graph-warrant"):
        poisoned = dict(request, operation=forbidden)
        with pytest.raises(mod.AdminProtocolRefused):
            mod.parse_admin_request(_canonical(poisoned))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw + b"\n",
        lambda raw: raw.replace(b'"operation":', b'"operation" :', 1),
        lambda raw: raw.replace(b'"request_id":', b'"request_id":"x","request_id":', 1),
    ],
)
def test_admin_request_rejects_noncanonical_or_duplicate_json(mutate):
    mod = _mod()
    payload = _b64url(_canonical({"records": [], "sequence": 0}))
    raw = _canonical(
        {
            "arguments": {
                "manifest_id": "manifest_" + "7" * 64,
                "scope": "source_" + "6" * 64,
                "sequence": 0,
            },
            "operation": "append-path-manifest",
            "payload_base64url": payload,
            "request_id": "request_" + "2" * 64,
        }
    )
    with pytest.raises(mod.AdminProtocolRefused):
        mod.parse_admin_request(mutate(raw))


def test_external_path_manifest_is_ordered_create_only_and_replay_idempotent(tmp_path):
    mod = _mod()
    repository = tmp_path / "repo"
    repository.mkdir()
    store = mod.ExternalPathManifestStore(tmp_path / "protected", repository_root=repository)
    manifest_id = store.begin(
        scope="source_" + "3" * 64,
        expected_total_count=3,
        expected_required_count=2,
        expected_test_count=1,
    )
    first = _b64url(
        _canonical(
            {
                "records": [
                    {"path": "platform_core/runtime/candidate.py", "role": "required-change"},
                    {"path": "tests/execution/test_candidate.py", "role": "required-test"},
                ],
                "sequence": 0,
            }
        )
    )
    second = _b64url(
        _canonical(
            {
                "records": [
                    {"path": "platform_core/runtime/receipts.py", "role": "allowed-only"}
                ],
                "sequence": 1,
            }
        )
    )

    assert store.append(
        scope="source_" + "3" * 64,
        manifest_id=manifest_id,
        sequence=0,
        canonical_records_base64url=first,
    )["replayed"] is False
    assert store.append(
        scope="source_" + "3" * 64,
        manifest_id=manifest_id,
        sequence=0,
        canonical_records_base64url=first,
    )["replayed"] is True
    with pytest.raises(mod.AdminProtocolRefused):
        store.append(
            scope="source_" + "3" * 64,
            manifest_id=manifest_id,
            sequence=2,
            canonical_records_base64url=second,
        )
    store.append(
        scope="source_" + "3" * 64,
        manifest_id=manifest_id,
        sequence=1,
        canonical_records_base64url=second,
    )

    receipt = store.seal(
        scope="source_" + "3" * 64,
        manifest_id=manifest_id,
        require_total_count=3,
        require_required_count=2,
        require_test_count=1,
    )

    assert receipt["schema"] == "galaxy.path-manifest-receipt/v1"
    assert receipt["manifest_id"] == manifest_id
    assert receipt["allowed_paths"] == [
        "platform_core/runtime/candidate.py",
        "platform_core/runtime/receipts.py",
        "tests/execution/test_candidate.py",
    ]
    assert receipt["required_paths"] == [
        "platform_core/runtime/candidate.py",
        "tests/execution/test_candidate.py",
    ]
    assert receipt["test_paths"] == ["tests/execution/test_candidate.py"]
    assert store.seal(
        scope="source_" + "3" * 64,
        manifest_id=manifest_id,
        require_total_count=3,
        require_required_count=2,
        require_test_count=1,
    ) == receipt


def test_external_path_manifest_rejects_role_confusion_duplicates_and_traversal(tmp_path):
    mod = _mod()
    repository = tmp_path / "repo"
    repository.mkdir()
    bad_records = (
        [
            {"path": "x.py", "role": "required-change"},
            {"path": "x.py", "role": "test-only"},
        ],
        [{"path": "../outside.py", "role": "allowed-only"}],
        [{"path": "x.py", "role": "required-and-test"}],
    )
    for index, records in enumerate(bad_records):
        store = mod.ExternalPathManifestStore(
            tmp_path / f"protected-{index}", repository_root=repository
        )
        manifest_id = store.begin(
            scope="source_" + str(index + 4) * 64,
            expected_total_count=len(records),
            expected_required_count=0,
            expected_test_count=0,
        )
        payload = _b64url(_canonical({"records": records, "sequence": 0}))
        with pytest.raises(mod.AdminProtocolRefused):
            store.append(
                scope="source_" + str(index + 4) * 64,
                manifest_id=manifest_id,
                sequence=0,
                canonical_records_base64url=payload,
            )


def test_admin_processor_durably_replays_path_manifest_commands(tmp_path):
    mod = _mod()
    repository = tmp_path / "repo"
    repository.mkdir()
    processor = mod.AdminCommandProcessor(tmp_path / "external", repository_root=repository)
    scope = "source_" + "a" * 64
    begin = _admin_request(
        "begin-path-manifest",
        arguments={
            "expected_required_count": 1,
            "expected_test_count": 1,
            "expected_total_count": 1,
            "scope": scope,
        },
        payload={},
        request_digit="a",
    )

    first = processor.process(begin)
    assert processor.process(begin) == first
    begin_response = json.loads(first)
    assert begin_response["accepted"] is True
    assert begin_response["authority_ceiling"] == "maintenance_only"
    manifest_id = begin_response["result"]["manifest_id"]
    assert begin_response["result"]["output"] == manifest_id

    append = _admin_request(
        "append-path-manifest",
        arguments={
            "manifest": manifest_id,
            "require_decode_recanonicalize_byte_equality": True,
            "require_decoded_canonical_json_max_bytes": 4096,
            "require_exact_envelope_max_bytes": 8192,
            "require_strict_unpadded_base64url": True,
            "scope": scope,
            "sequence": 0,
        },
        payload={
            "records": [{"path": "tests/execution/test_candidate.py", "role": "required-test"}],
            "sequence": 0,
        },
        request_digit="b",
    )
    append_response = processor.process(append)
    assert processor.process(append) == append_response

    seal = _admin_request(
        "seal-path-manifest",
        arguments={
            "canonical_order": True,
            "manifest": manifest_id,
            "persist_and_reread": True,
            "require_required_count": 1,
            "require_test_count": 1,
            "require_total_count": 1,
            "sha256": True,
            "scope": scope,
        },
        payload={},
        request_digit="c",
    )
    receipt = json.loads(processor.process(seal))["result"]
    assert receipt["allowed_paths"] == ["tests/execution/test_candidate.py"]
    assert receipt["required_paths"] == ["tests/execution/test_candidate.py"]
    assert receipt["test_paths"] == ["tests/execution/test_candidate.py"]
    assert receipt["receipt_id"].startswith("pathmanifest_")
    assert receipt["output"] == receipt["receipt_id"]
    assert processor.production_active is False


def test_admin_processor_aborts_open_path_manifest_and_replays_cleanup(tmp_path):
    mod = _mod()
    repository = tmp_path / "repo"
    repository.mkdir()
    external = tmp_path / "external"
    processor = mod.AdminCommandProcessor(external, repository_root=repository)
    scope = "source_" + "4" * 64
    begin = _admin_request(
        "begin-path-manifest",
        arguments={
            "expected_required_count": 0,
            "expected_test_count": 0,
            "expected_total_count": 1,
            "scope": scope,
        },
        payload={},
        request_digit="4",
    )
    manifest_id = json.loads(processor.process(begin))["result"]["manifest_id"]
    abort = _admin_request(
        "abort-path-manifest",
        arguments={
            "manifest": manifest_id,
            "persist_cleanup_receipt": True,
            "require_no_unsealed_resource": True,
            "scope": scope,
        },
        payload={},
        request_digit="5",
    )

    first = processor.process(abort)
    restarted = mod.AdminCommandProcessor(external, repository_root=repository)
    assert restarted.process(abort) == first
    result = json.loads(first)["result"]
    assert result["cleanup_receipt_id"].startswith("pathcleanup_")
    assert result["output"] == ""
    sessions = list((external / "path-manifests" / "sessions").glob("*.json"))
    assert len(sessions) == 1
    session = json.loads(sessions[0].read_bytes())
    assert session["status"] == "aborted"
    assert session["chunks"] == [] and session["records"] == []


def test_admin_processor_rejects_path_manifest_guard_downgrade(tmp_path):
    mod = _mod()
    repository = tmp_path / "repo"
    repository.mkdir()
    processor = mod.AdminCommandProcessor(tmp_path / "external", repository_root=repository)
    scope = "source_" + "6" * 64
    begin = _admin_request(
        "begin-path-manifest",
        arguments={
            "expected_required_count": 0,
            "expected_test_count": 0,
            "expected_total_count": 1,
            "scope": scope,
        },
        payload={},
        request_digit="6",
    )
    manifest_id = json.loads(processor.process(begin))["result"]["manifest_id"]
    downgraded = _admin_request(
        "append-path-manifest",
        arguments={
            "manifest": manifest_id,
            "require_decode_recanonicalize_byte_equality": False,
            "require_decoded_canonical_json_max_bytes": 4096,
            "require_exact_envelope_max_bytes": 8192,
            "require_strict_unpadded_base64url": True,
            "scope": scope,
            "sequence": 0,
        },
        payload={
            "records": [{"path": "x.py", "role": "allowed-only"}],
            "sequence": 0,
        },
        request_digit="7",
    )
    with pytest.raises(mod.AdminProtocolRefused):
        processor.process(downgraded)


def test_admin_processor_exposes_only_reread_tofu_token_and_self_attestation(
    tmp_path, monkeypatch
):
    mod = _mod()
    repository = tmp_path / "repo"
    repository.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    runtime_lock = external / "runtime.lock.json"
    runtime_lock.write_bytes(_canonical({"status": "installed_inactive"}))
    tofu_receipt = external / "tofu-receipt.json"
    tofu_receipt.write_bytes(_canonical({"status": "installed_inactive"}))
    context = mod.AdminTrustContext(
        external_root=external.resolve(),
        runtime_lock_path=runtime_lock.resolve(),
        runtime_lock_sha256=hashlib.sha256(runtime_lock.read_bytes()).hexdigest(),
        tofu_receipt_path=tofu_receipt.resolve(),
        tofu_receipt_sha256=hashlib.sha256(tofu_receipt.read_bytes()).hexdigest(),
        repository_identity="a" * 64,
    )
    observed = []

    def verify_context(actual, *, require_acl):
        assert actual == context
        observed.append(require_acl)
        return {
            "generation": 1,
            "merkle_root": "b" * 64,
            "runtime_digest": "c" * 64,
        }

    monkeypatch.setattr(mod, "_verify_admin_trust_context", verify_context)
    processor = mod.AdminCommandProcessor(
        external / "admin", repository_root=repository, trust_context=context
    )
    current = _admin_request(
        "current-tofu-receipt",
        arguments={"persisted_and_reread": True, "require_protected_generation": True},
        payload={},
        request_digit="8",
    )
    current_result = json.loads(processor.process(current))["result"]
    token = "tofu_" + context.tofu_receipt_sha256
    assert current_result == {
        "generation": 1,
        "merkle_root": "b" * 64,
        "output": token,
        "receipt_id": token,
        "runtime_digest": "c" * 64,
    }

    verify = _admin_request(
        "verify-tofu-receipt",
        arguments={
            "receipt": token,
            "require_full_leaf_manifest": True,
            "require_inactive_service_readiness": True,
            "require_protected_generation": True,
            "require_sealed_runtime_and_images": True,
        },
        payload={},
        request_digit="9",
    )
    verify_result = json.loads(processor.process(verify))["result"]
    assert verify_result["output"] == ""
    assert verify_result["receipt_id"] == token

    finalization_result = {
        "activation_authority": False,
        "anchor_launch_record_path": str(external / "anchor-launch-record.json"),
        "anchor_launch_record_sha256": "d" * 64,
        "anchor_record_path": str(external / "anchor-record.json"),
        "generation": 1,
        "merkle_root": "b" * 64,
        "receipt_path": str(tofu_receipt.resolve()),
        "runtime_pointer_path": str(external / "activation-runtime.json"),
        "schema": "galaxy.tofu-finalization-result/v1",
        "status": "installed_inactive",
    }
    mod._verify_tofu_receipt_argument(
        _canonical(finalization_result).decode("utf-8"),
        context,
        {"generation": 1, "merkle_root": "b" * 64},
    )

    verify_self = _admin_request(
        "verify-self",
        arguments={
            "require_closed_launch_record": True,
            "require_fresh_service_host": True,
            "require_inactive_generation": True,
            "require_os_pinned_digest": True,
            "require_protected_acl": True,
        },
        payload={},
        request_digit="a",
    )
    self_result = json.loads(processor.process(verify_self))["result"]
    assert self_result["output"] == ""
    assert self_result["production_active"] is False
    assert observed == [True, True, True]

    wrong = json.loads(verify)
    wrong["arguments"]["receipt"] = "tofu_" + "0" * 64
    wrong["request_id"] = "request_" + "0" * 64
    with pytest.raises(mod.AdminProtocolRefused):
        processor.process(_canonical(wrong))


def test_admin_acl_reader_uses_native_security_descriptor_without_shell(tmp_path):
    mod = _mod()
    sddl = mod._live_security_descriptor_sddl(tmp_path)
    assert sddl.startswith("O:")
    assert "G:" in sddl and "D:" in sddl


def test_admin_trust_context_rehashes_full_inactive_closure_and_refuses_drift(
    tmp_path, monkeypatch
):
    mod = _mod()
    external = (tmp_path / "external").resolve()
    controller = external / "generations" / "00000001" / "controller"
    repository_identity = "1" * 64
    record_root = external / "repositories" / repository_identity
    controller.mkdir(parents=True)
    record_root.mkdir(parents=True)
    runtime_files = {}
    runtime_digests = {}
    source_records = []
    for index, name in enumerate(sorted(mod._RUNTIME_FILE_KEYS)):
        path = controller / f"runtime-{index:02d}-{name}.bin"
        raw = bytes([index + 1]) * (32 if name == "receipt_public_key" else 7)
        path.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        runtime_files[name] = str(path)
        runtime_digests[name] = digest
        source_records.append(
            {
                "installed_path": str(path),
                "logical_path": f"runtime/{name}.bin",
                "sha256": digest,
                "size": len(raw),
            }
        )
    maintenance_sources = {}
    for logical, raw in {
        "bootstrap/anchor.py": b"anchor capsule source",
        "bootstrap/singularity_admin_client.ps1": b"request client source",
        "bootstrap/singularity_anchor.ps1": b"native anchor source",
    }.items():
        path = controller / logical.rsplit("/", 1)[-1]
        path.write_bytes(raw)
        maintenance_sources[logical] = path
        source_records.append(
            {
                "installed_path": str(path),
                "logical_path": logical,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size": len(raw),
            }
        )
    source_records.sort(key=lambda item: item["logical_path"])
    image = controller / "image.tar"
    image.write_bytes(b"offline image archive")
    receipt_path = external / "tofu" / "receipt-00000001.json"
    receipt_path.parent.mkdir()
    runtime_lock = controller / "runtime.lock.json"
    runtime_lock.write_bytes(
        _canonical(
            {
                "external_root": str(external),
                "file_digests": runtime_digests,
                "files": runtime_files,
                "generation": 1,
                "image_archive_paths": {"reviewer": str(image)},
                "image_digests": {"reviewer": "2" * 64},
                "max_probe_concurrency": 1,
                "runtime_digest": "3" * 64,
                "schema": "galaxy.activation.sealed-runtime/v1",
                "security_profiles": {},
                "status": "installed_inactive",
                "tofu_receipt_path": str(receipt_path),
            }
        )
    )
    artifact_records = []
    for logical, path in {
        "runtime/runtime.lock.json": runtime_lock,
        "images/reviewer.tar": image,
    }.items():
        raw = path.read_bytes()
        artifact_records.append(
            {
                "installed_path": str(path),
                "logical_path": logical,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size": len(raw),
            }
        )
    artifact_records.sort(key=lambda item: item["logical_path"])

    def leaf_root(domain, records):
        hashes = [
            hashlib.sha256(
                _canonical(
                    {
                        "logical_path": item["logical_path"],
                        "sha256": item["sha256"],
                        "size": item["size"],
                    }
                )
            ).digest()
            for item in records
        ]
        return hashlib.sha256(
            domain.encode("ascii") + b"\0" + b"".join(sorted(hashes))
        ).hexdigest()

    source_root = leaf_root("source", source_records)
    artifact_root = leaf_root("artifact", artifact_records)
    merkle_root = hashlib.sha256(
        b"galaxy-tofu-v1\0"
        + bytes.fromhex(source_root)
        + bytes.fromhex(artifact_root)
    ).hexdigest()
    nonce = "4" * 64
    challenge = f"TRUST SINGULARITY BOOTSTRAP {merkle_root} NONCE {nonce}"
    anchor_record = record_root / "anchor-record.json"
    anchor_record.write_bytes(_canonical({"activation_state": "inactive"}))
    empty_cwd = record_root / "empty-cwd"
    empty_cwd.mkdir()
    host_signature = {"publisher": "Microsoft Windows", "status": "valid"}
    launch_record = {
        "activation_state": "inactive",
        "anchor_path": str(maintenance_sources["bootstrap/singularity_anchor.ps1"]),
        "anchor_sha256": hashlib.sha256(
            maintenance_sources["bootstrap/singularity_anchor.ps1"].read_bytes()
        ).hexdigest(),
        "arguments": ["-NoLogo", "-NoProfile", "-NonInteractive"],
        "control_pipe": r"\\.\pipe\9to5-singularity-v1",
        "environment": {"PATH": "", "PSModulePath": "", "SystemRoot": "C:\\Windows", "WINDIR": "C:\\Windows"},
        "host_path": runtime_files["powershell"],
        "host_sha256": runtime_digests["powershell"],
        "host_signature": host_signature,
        "host_signature_sha256": hashlib.sha256(_canonical(host_signature)).hexdigest(),
        "schema": "galaxy.singularity-anchor-launch/v1",
        "service_name": "9to5Singularity",
        "stdio": {"stderr": "null", "stdin": "null", "stdout": "null"},
        "working_directory": str(empty_cwd),
    }
    launch_path = record_root / "anchor-launch-record.json"
    launch_path.write_bytes(_canonical(launch_record))
    operator_sid = "S-1-5-21-111-222-333-1001"
    service_sid = "S-1-5-80-1-1-1-1-1"
    dacl_sddl = (
        "O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
        f"(D;OICI;SDDTDC;;;{operator_sid})(A;OICI;FRFX;;;{operator_sid})"
        f"(A;OICI;FRFX;;;{service_sid})"
    )
    public_key = Path(runtime_files["receipt_public_key"]).read_bytes()
    receipt = {
        "activation_acceptance_sha256": runtime_digests["acceptance"],
        "activation_adapter_sha256": runtime_digests["adapter"],
        "activation_receipt_public_key": public_key.hex(),
        "activation_receipt_public_key_digest": hashlib.sha256(public_key).hexdigest(),
        "activation_runtime_profiles_sha256": runtime_digests["runtime_profiles"],
        "activation_state": "inactive",
        "anchor_launch_record_path": str(launch_path),
        "anchor_launch_record_sha256": hashlib.sha256(launch_path.read_bytes()).hexdigest(),
        "anchor_record_path": str(anchor_record),
        "approval_response_sha256": hashlib.sha256(challenge.encode("ascii")).hexdigest(),
        "artifact_leaves": artifact_records,
        "artifact_root": artifact_root,
        "challenge": challenge,
        "dacl_sddl": dacl_sddl,
        "host_signature_sha256": launch_record["host_signature_sha256"],
        "image_digests": {"reviewer": "2" * 64},
        "merkle_root": merkle_root,
        "monotone_generation": 1,
        "nonce": nonce,
        "operator_sid": operator_sid,
        "repository_identity": repository_identity,
        "runtime_digest": "3" * 64,
        "schema": "galaxy.trust-on-first-install/v1",
        "service_name": "9to5Singularity",
        "service_sid": service_sid,
        "source_leaves": source_records,
        "source_root": source_root,
        "status": "installed_inactive",
    }
    receipt_path.write_bytes(_canonical(receipt))
    context = mod.AdminTrustContext(
        external_root=external,
        runtime_lock_path=runtime_lock,
        runtime_lock_sha256=hashlib.sha256(runtime_lock.read_bytes()).hexdigest(),
        tofu_receipt_path=receipt_path,
        tofu_receipt_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        repository_identity=repository_identity,
    )
    monkeypatch.setattr(mod, "_live_security_descriptor_sddl", lambda path: dacl_sddl)

    assert mod._verify_admin_trust_context(context, require_acl=True) == {
        "generation": 1,
        "merkle_root": merkle_root,
        "runtime_digest": "3" * 64,
    }
    Path(runtime_files["adapter"]).write_bytes(b"tampered")
    with pytest.raises(mod.AdminProtocolRefused):
        mod._verify_admin_trust_context(context, require_acl=True)


def test_admin_transition_store_recovers_purpose_intent_fence_and_source_begin(tmp_path):
    mod = _mod()
    repository = tmp_path / "repo"
    repository.mkdir()
    root = tmp_path / "transitions"
    epoch = "tofu_" + "a" * 64
    store = mod.AdminTransitionStore(
        root,
        repository_root=repository,
        epoch=epoch,
        snapshotter=lambda path: "b" * 64,
        reviewed_dag={"task2-source-v1": None},
    )
    purpose_spec = {
        "canonicalization_policy": "strict-utf8-parent-bom-preserving-crlf-to-lf-or-exact",
        "contract": "source-update-maintenance-v1",
        "operation": "source-update",
        "plan_node": "task2-source-v1",
        "requested_fences": "cli-run-closed+discord-disabled+maintenance-index-ref",
    }

    purpose = store.acquire_purpose(purpose_spec)
    assert purpose.startswith("purpose_")
    assert store.acquire_purpose(purpose_spec) == purpose
    assert store.resolve_purpose(purpose_spec) == purpose
    assert store.current_purpose() == "none"

    intent_spec = {
        "contract": "source-update-maintenance-v1",
        "operation": "source-update",
        "requested_fences": "cli-run-closed+discord-disabled+maintenance-index-ref",
    }
    request_id = store.acquire_intent(purpose, intent_spec)
    assert request_id.startswith("request_")
    assert store.acquire_intent(purpose, intent_spec) == request_id
    assert store.resolve_intent(purpose, intent_spec) == request_id
    assert store.current_purpose() == purpose
    owner_fence = store.resolve_owner_fence(request_id, purpose)
    assert owner_fence.startswith("ownerfence_")

    transaction = store.begin_source_update(
        request_id=request_id,
        purpose_id=purpose,
        owner_fence_id=owner_fence,
    )
    assert transaction.startswith("source_")
    assert store.resolve_source_begin(request_id, purpose) == transaction
    assert store.production_active is False
    assert store.discord_enabled is False

    restarted = mod.AdminTransitionStore(
        root,
        repository_root=repository,
        epoch=epoch,
        snapshotter=lambda path: "b" * 64,
        reviewed_dag={"task2-source-v1": None},
    )
    assert restarted.resolve_purpose(purpose_spec) == purpose
    assert restarted.resolve_intent(purpose, intent_spec) == request_id
    assert restarted.resolve_owner_fence(request_id, purpose) == owner_fence
    assert restarted.resolve_source_begin(request_id, purpose) == transaction

    source_receipt = "sourcereceipt_" + "c" * 64
    restarted.record_source_cas(
        transaction_id=transaction,
        purpose_id=purpose,
        owner_fence_id=owner_fence,
        commit_oid="d" * 40,
        source_receipt_id=source_receipt,
    )
    restarted.record_source_attestation(
        transaction_id=transaction,
        purpose_id=purpose,
        owner_fence_id=owner_fence,
        source_receipt_id=source_receipt,
    )
    assert (
        restarted.finish_source_update(
            transaction_id=transaction,
            purpose_id=purpose,
            owner_fence_id=owner_fence,
        )
        == "committed_exact_new_developer_ingress_open"
    )
    terminal = restarted.observe_terminal(purpose)
    assert terminal.startswith("terminal_source_achieved_")
    restarted.acknowledge_terminal(purpose, terminal)
    assert restarted.current_purpose() == "none"
    assert restarted.resolve_purpose_outcome(purpose) == "archived_achieved"

    different = dict(purpose_spec, plan_node="task-other")
    with pytest.raises(mod.AdminProtocolRefused):
        restarted.acquire_purpose(different)


def test_admin_source_abort_restores_pre_normalization_bytes_and_archives_retryable(
    tmp_path, monkeypatch
):
    mod = _mod()
    repository = (tmp_path / "repo").resolve()
    repository.mkdir()
    source_path = repository / "module.py"
    original = b"first line\r\nsecond line\r\n"
    source_path.write_bytes(original)

    def snapshot(root):
        records = []
        for path in sorted(root.rglob("*")):
            if path.is_file():
                records.append(
                    {
                        "path": path.relative_to(root).as_posix(),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    }
                )
        return hashlib.sha256(_canonical(records)).hexdigest()

    external = tmp_path / "external"
    transitions = mod.AdminTransitionStore(
        external / "transitions",
        repository_root=repository,
        epoch="tofu_" + "a" * 64,
        snapshotter=snapshot,
        reviewed_dag={"task2-source-v1": None},
    )
    purpose = transitions.acquire_purpose(
        {
            "canonicalization_policy": "strict-utf8-parent-bom-preserving-crlf-to-lf-or-exact",
            "contract": "source-update-maintenance-v1",
            "operation": "source-update",
            "plan_node": "task2-source-v1",
            "requested_fences": "cli-run-closed+discord-disabled+maintenance-index-ref",
        }
    )
    request_id = transitions.acquire_intent(
        purpose,
        {
            "contract": "source-update-maintenance-v1",
            "operation": "source-update",
            "requested_fences": "cli-run-closed+discord-disabled+maintenance-index-ref",
        },
    )
    owner_fence = transitions.resolve_owner_fence(request_id, purpose)
    transaction = transitions.begin_source_update(
        request_id=request_id,
        purpose_id=purpose,
        owner_fence_id=owner_fence,
    )
    manifests = mod.ExternalPathManifestStore(
        external / "path-manifests", repository_root=repository
    )
    manifest_id = manifests.begin(
        scope=transaction,
        expected_total_count=1,
        expected_required_count=1,
        expected_test_count=0,
        idempotency_key="request_" + "b" * 64,
    )
    payload = {
        "records": [{"path": "module.py", "role": "required-change"}],
        "sequence": 0,
    }
    manifests.append(
        scope=transaction,
        manifest_id=manifest_id,
        sequence=0,
        canonical_records_base64url=_b64url(_canonical(payload)),
    )
    sealed = manifests.seal(
        scope=transaction,
        manifest_id=manifest_id,
        require_total_count=1,
        require_required_count=1,
        require_test_count=0,
    )
    path_receipt = "pathmanifest_" + sealed["record_sha256"]
    source = mod.AdminSourceCommitStore(
        external / "source-commits",
        repository_root=repository,
        transitions=transitions,
        path_manifests=manifests,
    )
    source.normalize_developer_source(
        transaction_id=transaction,
        purpose_id=purpose,
        owner_fence_id=owner_fence,
        path_manifest_receipt_id=path_receipt,
    )
    assert source_path.read_bytes() == b"first line\nsecond line\n"
    purpose_spec = {
        "canonicalization_policy": "strict-utf8-parent-bom-preserving-crlf-to-lf-or-exact",
        "contract": "source-update-maintenance-v1",
        "operation": "source-update",
        "plan_node": "task2-source-v1",
        "requested_fences": "cli-run-closed+discord-disabled+maintenance-index-ref",
    }
    assert transitions.resolve_purpose(purpose_spec) == purpose
    assert transitions.acquire_purpose(purpose_spec) == purpose

    processor = mod.AdminCommandProcessor(
        external / "admin",
        repository_root=repository,
        transition_store=transitions,
        source_commit_store=source,
    )
    authority = {
        "require_current_owner_fencing_generation": True,
        "transition_owner_fence_receipt": owner_fence,
        "transition_purpose_receipt": purpose,
    }
    abort = _admin_request(
        "abort-source-update",
        arguments={
            **authority,
            "abort_all_child_resources": True,
            "before_cas_only": True,
            "keep_discord_listener_disabled": True,
            "keep_production_run_inactive": True,
            "persist_and_reread_recovery_receipt": True,
            "print_disposition": True,
            "reconcile_journaled_normalization": True,
            "restore_developer_ingress_only_if_old_ref_index_tree_exact": True,
            "transaction": transaction,
        },
        payload={},
        request_digit="c",
    )
    replace_source = source._replace_source

    def lose_response_after_restore(*args, **kwargs):
        replace_source(*args, **kwargs)
        raise mod.InjectedAdminResponseLoss("injected abort process loss")

    monkeypatch.setattr(source, "_replace_source", lose_response_after_restore)
    with pytest.raises(mod.InjectedAdminResponseLoss):
        processor.process(abort)
    assert source_path.read_bytes() == original
    monkeypatch.setattr(source, "_replace_source", replace_source)
    response = json.loads(processor.process(abort))["result"]
    assert response["output"] == "safe_old_developer_ingress_open"
    assert response["recovery_receipt_id"].startswith("recovery_")
    assert source_path.read_bytes() == original
    assert json.loads(processor.process(abort))["result"] == response

    terminal = transitions.observe_terminal(purpose)
    assert terminal.startswith("terminal_source_retryable_old_")
    transitions.acknowledge_terminal(purpose, terminal)
    assert transitions.current_purpose() == "none"
    assert transitions.resolve_purpose_outcome(purpose) == "archived_retryable"
    assert transitions.resolve_source_disposition(transaction) == (
        "safe_old_developer_ingress_open"
    )
    next_request = transitions.acquire_intent(
        purpose,
        {
            "contract": "source-update-maintenance-v1",
            "operation": "source-update",
            "requested_fences": "cli-run-closed+discord-disabled+maintenance-index-ref",
        },
    )
    assert next_request != request_id
    next_owner_fence = transitions.resolve_owner_fence(next_request, purpose)
    assert next_owner_fence != owner_fence
    next_transaction = transitions.begin_source_update(
        request_id=next_request,
        purpose_id=purpose,
        owner_fence_id=next_owner_fence,
    )
    assert next_transaction != transaction


def test_admin_source_normalization_is_manifest_bound_binary_exact_and_replayable(
    tmp_path, monkeypatch
):
    mod = _mod()
    repository = (tmp_path / "repo").resolve()
    repository.mkdir()
    text_path = repository / "text.py"
    binary_path = repository / "asset.bin"
    rogue_path = repository / "rogue.txt"
    second_path = repository / "second.py"
    text_path.write_bytes(b"\xef\xbb\xbfline one\r\nline two\r\n")
    second_path.write_bytes(b"another\r\nfile\r\n")
    binary = b"\xff\x00binary\r\n"
    binary_path.write_bytes(binary)
    rogue_path.write_bytes(b"parent exact\n")

    def snapshot(root):
        records = []
        for path in sorted(root.rglob("*")):
            if path.is_file():
                records.append(
                    {
                        "path": path.relative_to(root).as_posix(),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    }
                )
        return hashlib.sha256(_canonical(records)).hexdigest()

    external = tmp_path / "external"
    transitions = mod.AdminTransitionStore(
        external / "transitions",
        repository_root=repository,
        epoch="tofu_" + "a" * 64,
        snapshotter=snapshot,
        reviewed_dag={"task2-source-v1": None},
    )
    purpose = transitions.acquire_purpose(
        {
            "canonicalization_policy": "strict-utf8-parent-bom-preserving-crlf-to-lf-or-exact",
            "contract": "source-update-maintenance-v1",
            "operation": "source-update",
            "plan_node": "task2-source-v1",
            "requested_fences": "cli-run-closed+discord-disabled+maintenance-index-ref",
        }
    )
    request_id = transitions.acquire_intent(
        purpose,
        {
            "contract": "source-update-maintenance-v1",
            "operation": "source-update",
            "requested_fences": "cli-run-closed+discord-disabled+maintenance-index-ref",
        },
    )
    owner_fence = transitions.resolve_owner_fence(request_id, purpose)
    transaction = transitions.begin_source_update(
        request_id=request_id,
        purpose_id=purpose,
        owner_fence_id=owner_fence,
    )
    manifests = mod.ExternalPathManifestStore(
        external / "path-manifests", repository_root=repository
    )
    manifest_id = manifests.begin(
        scope=transaction,
        expected_total_count=3,
        expected_required_count=2,
        expected_test_count=0,
        idempotency_key="request_" + "f" * 64,
    )
    payload = {
        "records": [
            {"path": "asset.bin", "role": "allowed-only"},
            {"path": "second.py", "role": "required-change"},
            {"path": "text.py", "role": "required-change"},
        ],
        "sequence": 0,
    }
    manifests.append(
        scope=transaction,
        manifest_id=manifest_id,
        sequence=0,
        canonical_records_base64url=_b64url(_canonical(payload)),
    )
    sealed = manifests.seal(
        scope=transaction,
        manifest_id=manifest_id,
        require_total_count=3,
        require_required_count=2,
        require_test_count=0,
    )
    path_receipt = "pathmanifest_" + sealed["record_sha256"]

    def object_hasher(object_type, payload):
        frame = f"{object_type} {len(payload)}".encode("ascii") + b"\0" + payload
        return hashlib.sha1(frame, usedforsecurity=False).hexdigest()

    def parent_manifest(root):
        entries = []
        for path, payload in (
            ("asset.bin", binary),
            ("rogue.txt", b"parent exact\n"),
            ("second.py", b"old second\n"),
            ("text.py", b"old text\n"),
        ):
            entries.append(
                {
                    "blob_oid": object_hasher("blob", payload),
                    "blob_sha256": hashlib.sha256(payload).hexdigest(),
                    "mode": 0o100644,
                    "path": path,
                    "size": len(payload),
                }
            )
        return {
            "schema": "galaxy.admin-parent-manifest/v1",
            "parent_oid": "a" * 40,
            "entries": entries,
            "contained_parser_receipt_id": "parserreceipt_" + "b" * 64,
        }

    def proposal_reviewer(proposal, pass_index):
        return {
            "canonical_write_observed": False,
            "decision": "accept",
            "findings": [],
            "independent": True,
            "network_enabled": False,
            "pass_index": pass_index,
            "proposal_id": proposal["proposal_id"],
            "proposal_record_sha256": proposal["record_sha256"],
            "reviewer_image_digest": "sha256:" + "c" * 64,
            "reviewer_qualification_receipt_id": (
                "reviewerqualification_" + "d" * 64
            ),
            "reviewer_runtime_sha256": "e" * 64,
            "reviewer_session_id": f"reviewsession_{pass_index}" + "f" * 63,
            "schema": "galaxy.independent-source-review/v1",
            "source_execution_observed": False,
        }

    source = mod.AdminSourceCommitStore(
        external / "source-commits",
        repository_root=repository,
        transitions=transitions,
        path_manifests=manifests,
        object_hasher=object_hasher,
        parent_manifest_loader=parent_manifest,
        proposal_reviewer=proposal_reviewer,
    )

    replace_source = source._replace_source
    replacements = 0

    def crash_after_first_replace(*args, **kwargs):
        nonlocal replacements
        replace_source(*args, **kwargs)
        replacements += 1
        if replacements == 1:
            raise mod.InjectedAdminResponseLoss("injected normalization process loss")

    monkeypatch.setattr(source, "_replace_source", crash_after_first_replace)
    with pytest.raises(mod.InjectedAdminResponseLoss):
        source.normalize_developer_source(
            transaction_id=transaction,
            purpose_id=purpose,
            owner_fence_id=owner_fence,
            path_manifest_receipt_id=path_receipt,
        )
    source = mod.AdminSourceCommitStore(
        external / "source-commits",
        repository_root=repository,
        transitions=transitions,
        path_manifests=manifests,
        object_hasher=object_hasher,
        parent_manifest_loader=parent_manifest,
        proposal_reviewer=proposal_reviewer,
    )
    receipt = source.normalize_developer_source(
        transaction_id=transaction,
        purpose_id=purpose,
        owner_fence_id=owner_fence,
        path_manifest_receipt_id=path_receipt,
    )
    assert receipt.startswith("normalization_")
    assert text_path.read_bytes() == b"\xef\xbb\xbfline one\nline two\n"
    assert second_path.read_bytes() == b"another\nfile\n"
    assert binary_path.read_bytes() == binary
    assert (
        source.normalize_developer_source(
            transaction_id=transaction,
            purpose_id=purpose,
            owner_fence_id=owner_fence,
            path_manifest_receipt_id=path_receipt,
        )
        == receipt
    )
    processor = mod.AdminCommandProcessor(
        external / "admin",
        repository_root=repository,
        transition_store=transitions,
        source_commit_store=source,
    )
    normalize_request = _admin_request(
        "normalize-developer-source",
        arguments={
            "binary_exact": True,
            "chain_purpose_pre_normalization_batch_and_policy": True,
            "create_if_absent_or_verify_existing_loose_head": True,
            "disable_auto_ref_packing": True,
            "ensure_symbolic_loose_head_same_oid": True,
            "native_full_tree_exact_index_bytes": True,
            "no_ambient_git_config": True,
            "no_filters": True,
            "no_hooks": True,
            "path_manifest_receipt": path_receipt,
            "persist_before_response": True,
            "print_normalization_receipt": True,
            "repo": str(repository),
            "require_current_owner_fencing_generation": True,
            "require_exact_purpose_batch_membership": True,
            "require_no_unexpected_change": True,
            "strict_utf8_parent_bom_preserving_crlf_to_lf_only": True,
            "transaction": transaction,
            "transition_owner_fence_receipt": owner_fence,
            "transition_purpose_receipt": purpose,
        },
        payload={},
        request_digit="8",
    )
    assert json.loads(processor.process(normalize_request))["result"]["output"] == receipt
    unqualified = mod.AdminSourceCommitStore(
        external / "source-commits",
        repository_root=repository,
        transitions=transitions,
        path_manifests=manifests,
    )
    with pytest.raises(mod.AdminProtocolRefused, match="parser authority"):
        unqualified.prepare_source_commit(
            transaction_id=transaction,
            purpose_id=purpose,
            owner_fence_id=owner_fence,
            path_manifest_receipt_id=path_receipt,
            normalization_receipt_id=receipt,
            message="feat: normalize exact source",
        )
    snapshotter = transitions.snapshotter
    _, transaction_record = transitions._transaction(transaction)
    transitions.snapshotter = lambda _root: transaction_record[
        "normalized_state_sha256"
    ]
    rogue_path.write_bytes(b"unmanifested drift\n")
    with pytest.raises(mod.AdminProtocolRefused, match="outside the sealed allowlist"):
        source.prepare_source_commit(
            transaction_id=transaction,
            purpose_id=purpose,
            owner_fence_id=owner_fence,
            path_manifest_receipt_id=path_receipt,
            normalization_receipt_id=receipt,
            message="feat: normalize exact source",
        )
    rogue_path.write_bytes(b"parent exact\n")
    transitions.snapshotter = snapshotter
    publish_objects = source._publish_proposal_objects

    def crash_after_first_object(objects):
        first_oid = sorted(objects)[0]
        publish_objects({first_oid: objects[first_oid]})
        raise mod.InjectedAdminResponseLoss("injected proposal-object process loss")

    monkeypatch.setattr(source, "_publish_proposal_objects", crash_after_first_object)
    with pytest.raises(mod.InjectedAdminResponseLoss):
        source.prepare_source_commit(
            transaction_id=transaction,
            purpose_id=purpose,
            owner_fence_id=owner_fence,
            path_manifest_receipt_id=path_receipt,
            normalization_receipt_id=receipt,
            message="feat: normalize exact source",
        )
    source = mod.AdminSourceCommitStore(
        external / "source-commits",
        repository_root=repository,
        transitions=transitions,
        path_manifests=manifests,
        object_hasher=object_hasher,
        parent_manifest_loader=parent_manifest,
        proposal_reviewer=proposal_reviewer,
    )
    processor.source_commits = source
    proposal = source.prepare_source_commit(
        transaction_id=transaction,
        purpose_id=purpose,
        owner_fence_id=owner_fence,
        path_manifest_receipt_id=path_receipt,
        normalization_receipt_id=receipt,
        message="feat: normalize exact source",
    )
    assert proposal.startswith("proposal_")
    proposal_record = source.resolve_proposal(proposal)
    assert proposal_record["parent_oid"] == "a" * 40
    assert proposal_record["commit_oid"] == object_hasher(
        "commit", bytes.fromhex(proposal_record["commit_payload_hex"])
    )
    assert source.prepare_source_commit(
        transaction_id=transaction,
        purpose_id=purpose,
        owner_fence_id=owner_fence,
        path_manifest_receipt_id=path_receipt,
        normalization_receipt_id=receipt,
        message="feat: normalize exact source",
    ) == proposal
    prepare_request = _admin_request(
        "prepare-source-commit",
        arguments={
            "fixed_commit_metadata": True,
            "message": "feat: normalize exact source",
            "native_no_follow_snapshot": True,
            "normalization_receipt": receipt,
            "parent_plus_allowlist_complete_tree": True,
            "path_manifest_receipt": path_receipt,
            "repo": str(repository),
            "require_current_owner_fencing_generation": True,
            "require_pre_normalization_purpose_chain": True,
            "transaction": transaction,
            "transition_owner_fence_receipt": owner_fence,
            "transition_purpose_receipt": purpose,
        },
        payload={},
        request_digit="9",
    )
    assert json.loads(processor.process(prepare_request))["result"]["output"] == proposal
    review_receipt = source.review_source_proposal(proposal, required_passes=1)
    assert review_receipt.startswith("review_")
    assert source.review_source_proposal(proposal, required_passes=1) == review_receipt
    verification_receipt = source.verify_source_proposal(
        proposal_id=proposal,
        normalization_receipt_id=receipt,
    )
    assert verification_receipt.startswith("verification_")
    review_request = _admin_request(
        "review-source-proposal",
        arguments={
            "no_canonical_write": True,
            "persist_and_reread_review_receipt": True,
            "sealed_independent_reviewer": True,
            "transaction": proposal,
            "transition_owner_fence_receipt": owner_fence,
            "transition_purpose_receipt": purpose,
            "require_current_owner_fencing_generation": True,
        },
        payload={},
        request_digit="a",
    )
    assert (
        json.loads(processor.process(review_request))["result"]["output"]
        == review_receipt
    )
    verify_request = _admin_request(
        "verify-source-proposal",
        arguments={
            "normalization_receipt": receipt,
            "require_current_owner_fencing_generation": True,
            "require_every_required_path_changed": True,
            "require_exact_manifest": True,
            "require_no_canonical_ref_write": True,
            "require_no_unexpected_change": True,
            "require_pre_normalization_purpose_chain": True,
            "require_review_receipt": True,
            "transaction": proposal,
            "transition_owner_fence_receipt": owner_fence,
            "transition_purpose_receipt": purpose,
        },
        payload={},
        request_digit="b",
    )
    assert (
        json.loads(processor.process(verify_request))["result"]["output"]
        == verification_receipt
    )
    commit_request = _admin_request(
        "commit-source-proposal",
        arguments={
            "cas_loose_ref": True,
            "durable": True,
            "install_verified_index": True,
            "keep_production_run_inactive": True,
            "native_full_tree_materialize": True,
            "normalization_receipt": receipt,
            "require_current_owner_fencing_generation": True,
            "require_final_byte_clean": True,
            "require_fresh_exact_digest_approval": True,
            "require_pre_normalization_purpose_chain": True,
            "source_update": transaction,
            "transaction": proposal,
            "transition_owner_fence_receipt": owner_fence,
            "transition_purpose_receipt": purpose,
        },
        payload={},
        request_digit="c",
    )
    with pytest.raises(mod.FreshExactApprovalRequired):
        processor.process(commit_request)
    assert source.resolve_proposal(proposal)["canonical_ref_written"] is False
    reconcile_request = _admin_request(
        "reconcile-source-update",
        arguments={
            "classify_old_or_exact_new_ref_index_tree": True,
            "finish_only_journal_bound_materialization_attestation_and_ingress": True,
            "keep_discord_listener_disabled": True,
            "keep_production_run_inactive": True,
            "persist_and_reread_recovery_receipt": True,
            "print_disposition": True,
            "proposal": proposal,
            "require_current_owner_fencing_generation": True,
            "transaction": transaction,
            "transition_owner_fence_receipt": owner_fence,
            "transition_purpose_receipt": purpose,
        },
        payload={},
        request_digit="d",
    )
    reconciled = json.loads(processor.process(reconcile_request))["result"]
    assert reconciled["output"] == "safe_old_developer_ingress_open"
    assert reconciled["recovery_receipt_id"].startswith("recovery_")
    assert text_path.read_bytes() == b"\xef\xbb\xbfline one\r\nline two\r\n"
    assert second_path.read_bytes() == b"another\r\nfile\r\n"
    binary_path.write_bytes(b"drift")
    with pytest.raises(mod.AdminProtocolRefused):
        source.normalize_developer_source(
            transaction_id=transaction,
            purpose_id=purpose,
            owner_fence_id=owner_fence,
            path_manifest_receipt_id=path_receipt,
        )


def test_admin_processor_runs_exact_task2_purpose_intent_and_begin_protocol(tmp_path):
    mod = _mod()
    repository = (tmp_path / "repo").resolve()
    repository.mkdir()
    external = tmp_path / "external"
    transition_store = mod.AdminTransitionStore(
        external / "transitions",
        repository_root=repository,
        epoch="tofu_" + "a" * 64,
        snapshotter=lambda path: "b" * 64,
        reviewed_dag={"task2-source-v1": None},
    )
    processor = mod.AdminCommandProcessor(
        external / "admin",
        repository_root=repository,
        transition_store=transition_store,
    )
    repo = str(repository)
    purpose_common = {
        "bind_active_reviewed_wave_epoch": True,
        "bind_canonicalization_policy": "strict-utf8-parent-bom-preserving-crlf-to-lf-or-exact",
        "bind_exact_old_state": True,
        "capture_native_no_follow_pre_normalization_batch": True,
        "contract": "source-update-maintenance-v1",
        "operation": "source-update",
        "reject_unrelated_or_multiple_predecessor_archives": True,
        "repo": repo,
        "reviewed_plan_node": "task2-source-v1",
        "requested_fences": "cli-run-closed+discord-disabled+maintenance-index-ref",
        "require_satisfied_reviewed_predecessor_ledger": True,
        "require_wave_epoch_bound_to_current_tofu_receipt": True,
    }
    acquire = _admin_request(
        "acquire-transition-purpose",
        arguments={
            **purpose_common,
            "create_or_return_exact": True,
            "persist_before_response": True,
            "print_purpose_receipt": True,
        },
        payload={},
        request_digit="b",
    )
    purpose = json.loads(processor.process(acquire))["result"]["output"]
    assert purpose.startswith("purpose_")
    resolve = _admin_request(
        "resolve-transition-purpose",
        arguments={
            **purpose_common,
            "print_purpose_receipt_or_none": True,
            "read_only": True,
            "require_unique_exact": True,
        },
        payload={},
        request_digit="c",
    )
    assert json.loads(processor.process(resolve))["result"]["output"] == purpose
    current = _admin_request(
        "resolve-current-top-level-transition",
        arguments={
            "print_none_or_bound_purpose_receipt": True,
            "read_only": True,
            "repo": repo,
            "repository_global_all_generations": True,
            "require_unique_live_slot": True,
        },
        payload={},
        request_digit="d",
    )
    assert json.loads(processor.process(current))["result"]["output"] == "none"

    intent_common = {
        "bind_exact_old_state": True,
        "contract": "source-update-maintenance-v1",
        "exclusive_top_level_mutation_per_registered_repo_all_generations": True,
        "operation": "source-update",
        "repo": repo,
        "requested_fences": "cli-run-closed+discord-disabled+maintenance-index-ref",
        "require_exact_purpose_binding": True,
        "transition_purpose_receipt": purpose,
    }
    acquire_intent = _admin_request(
        "acquire-begin-intent",
        arguments={
            **intent_common,
            "create_or_return_unique_slot": True,
            "persist_before_response": True,
            "print_request_id": True,
            "require_reviewed_purpose_dag": True,
        },
        payload={},
        request_digit="e",
    )
    request_id = json.loads(processor.process(acquire_intent))["result"]["output"]
    assert request_id.startswith("request_")
    resolve_intent = _admin_request(
        "resolve-begin-intent",
        arguments={
            **intent_common,
            "print_request_id_or_none": True,
            "read_only": True,
            "require_persisted_intent": True,
            "require_unique_slot": True,
        },
        payload={},
        request_digit="f",
    )
    assert json.loads(processor.process(resolve_intent))["result"]["output"] == request_id
    fence_request = _admin_request(
        "resolve-begin-intent-owner-fence",
        arguments={
            "print_owner_fence_receipt": True,
            "read_only": True,
            "repo": repo,
            "request_id": request_id,
            "require_current_owner_lease_and_fencing_generation": True,
            "transition_purpose_receipt": purpose,
        },
        payload={},
        request_digit="1",
    )
    owner_fence = json.loads(processor.process(fence_request))["result"]["output"]
    assert owner_fence.startswith("ownerfence_")

    authority = {
        "require_current_owner_fencing_generation": True,
        "transition_owner_fence_receipt": owner_fence,
        "transition_purpose_receipt": purpose,
    }
    begin = _admin_request(
        "begin-source-update",
        arguments={
            **authority,
            "close_cli_run_ingress": True,
            "hold_maintenance_index_and_ref_fences": True,
            "idempotent_create": True,
            "keep_discord_listener_disabled": True,
            "persist_begin_receipt_before_response": True,
            "repo": repo,
            "request_id": request_id,
            "require_exact_purpose_binding": True,
        },
        payload={},
        request_digit="2",
    )
    transaction = json.loads(processor.process(begin))["result"]["output"]
    assert transaction.startswith("source_")
    resolve_begin = _admin_request(
        "resolve-source-update-begin",
        arguments={
            **authority,
            "classify_started_exact_requested_fences_held_or_not_started": True,
            "print_transaction_or_not_started": True,
            "read_only": True,
            "repo": repo,
            "request_id": request_id,
            "require_exact_old_state_if_started": True,
            "require_exact_purpose_binding": True,
            "require_exact_request_binding": True,
            "require_latest_monotone_journal_if_started": True,
            "require_live_requested_fences_held_if_started": True,
            "require_persisted_begin_receipt_if_started": True,
        },
        payload={},
        request_digit="3",
    )
    assert json.loads(processor.process(resolve_begin))["result"]["output"] == transaction

    lock_path = external / "dummy-runtime-lock.json"
    receipt_path = external / "dummy-tofu-receipt.json"
    lock_path.write_bytes(_canonical({"status": "installed_inactive"}))
    receipt_path.write_bytes(_canonical({"status": "installed_inactive"}))
    trust_context = mod.AdminTrustContext(
        external_root=external.resolve(),
        runtime_lock_path=lock_path.resolve(),
        runtime_lock_sha256=hashlib.sha256(lock_path.read_bytes()).hexdigest(),
        tofu_receipt_path=receipt_path.resolve(),
        tofu_receipt_sha256="a" * 64,
        repository_identity="5" * 64,
    )
    secured = mod.AdminCommandProcessor(
        external / "secured-admin",
        repository_root=repository,
        trust_context=trust_context,
        transition_store=transition_store,
    )
    begin_manifest = _admin_request(
        "begin-path-manifest",
        arguments={
            **authority,
            "expected_required_count": 0,
            "expected_test_count": 0,
            "expected_total_count": 1,
            "scope": transaction,
        },
        payload={},
        request_digit="5",
    )
    assert json.loads(secured.process(begin_manifest))["result"]["manifest_id"].startswith(
        "manifest_"
    )
    orphan_manifest = json.loads(begin_manifest)
    for key in authority:
        del orphan_manifest["arguments"][key]
    orphan_manifest["request_id"] = "request_" + "6" * 64
    with pytest.raises(mod.AdminProtocolRefused):
        secured.process(_canonical(orphan_manifest))

    downgraded = json.loads(resolve_begin)
    downgraded["arguments"]["require_live_requested_fences_held_if_started"] = False
    downgraded["request_id"] = "request_" + "4" * 64
    with pytest.raises(mod.AdminProtocolRefused):
        processor.process(_canonical(downgraded))


def test_admin_processor_finishes_observes_acknowledges_and_releases_task2(tmp_path):
    mod = _mod()
    repository = (tmp_path / "repo").resolve()
    repository.mkdir()
    external = tmp_path / "external"
    store = mod.AdminTransitionStore(
        external / "transitions",
        repository_root=repository,
        epoch="tofu_" + "a" * 64,
        snapshotter=lambda path: "b" * 64,
        reviewed_dag={"task2-source-v1": None},
    )
    purpose = store.acquire_purpose(
        {
            "canonicalization_policy": "strict-utf8-parent-bom-preserving-crlf-to-lf-or-exact",
            "contract": "source-update-maintenance-v1",
            "operation": "source-update",
            "plan_node": "task2-source-v1",
            "requested_fences": "cli-run-closed+discord-disabled+maintenance-index-ref",
        }
    )
    request_id = store.acquire_intent(
        purpose,
        {
            "contract": "source-update-maintenance-v1",
            "operation": "source-update",
            "requested_fences": "cli-run-closed+discord-disabled+maintenance-index-ref",
        },
    )
    owner_fence = store.resolve_owner_fence(request_id, purpose)
    transaction = store.begin_source_update(
        request_id=request_id,
        purpose_id=purpose,
        owner_fence_id=owner_fence,
    )
    source_receipt = "sourcereceipt_" + "c" * 64
    store.record_source_cas(
        transaction_id=transaction,
        purpose_id=purpose,
        owner_fence_id=owner_fence,
        commit_oid="d" * 40,
        source_receipt_id=source_receipt,
    )
    store.record_source_attestation(
        transaction_id=transaction,
        purpose_id=purpose,
        owner_fence_id=owner_fence,
        source_receipt_id=source_receipt,
    )
    processor = mod.AdminCommandProcessor(
        external / "admin",
        repository_root=repository,
        transition_store=store,
    )
    authority = {
        "require_current_owner_fencing_generation": True,
        "transition_owner_fence_receipt": owner_fence,
        "transition_purpose_receipt": purpose,
    }
    disposition_guards = {
        **authority,
        "classify_safe_old_or_committed_exact_new_with_ingress_or_recovery_pending": True,
        "print_disposition": True,
        "read_only": True,
        "require_discord_listener_disabled": True,
        "require_persisted_receipt": True,
        "require_production_run_inactive": True,
        "transaction": transaction,
    }
    before = _admin_request(
        "resolve-source-update-disposition",
        arguments=disposition_guards,
        payload={},
        request_digit="0",
    )
    assert json.loads(processor.process(before))["result"]["output"] == (
        "committed_exact_new_developer_ingress_held_closed"
    )

    finish = _admin_request(
        "finish-source-update",
        arguments={
            **authority,
            "keep_discord_listener_disabled": True,
            "keep_production_run_inactive": True,
            "persist_and_reread_finish_receipt": True,
            "print_disposition": True,
            "release_developer_only_ingress": True,
            "transaction": transaction,
        },
        payload={},
        request_digit="1",
    )
    assert json.loads(processor.process(finish))["result"]["output"] == (
        "committed_exact_new_developer_ingress_open"
    )
    after = _admin_request(
        "resolve-source-update-disposition",
        arguments=disposition_guards,
        payload={},
        request_digit="2",
    )
    assert json.loads(processor.process(after))["result"]["output"] == (
        "committed_exact_new_developer_ingress_open"
    )

    observe = _admin_request(
        "observe-top-level-transition",
        arguments={
            "bound_purpose_receipt": purpose,
            "closed_terminal_map": "singularity-top-level-terminal-v1",
            "include_owner_lease_and_fencing_generation": True,
            "print_owner_state_recovery_pending_or_terminal_observation": True,
            "read_only": True,
            "repo": str(repository),
            "repository_global_all_generations": True,
            "require_latest_journal_live_state_and_ingress": True,
        },
        payload={},
        request_digit="3",
    )
    terminal = json.loads(processor.process(observe))["result"]["output"]
    assert terminal.startswith("terminal_source_achieved_")

    acknowledge = _admin_request(
        "acknowledge-terminal-disposition",
        arguments={
            "atomic_under_slot_lock": True,
            "bound_purpose_receipt": purpose,
            "closed_terminal_map": "singularity-top-level-terminal-v1",
            "idempotent": True,
            "persist_before_response": True,
            "reject_cross_operation_purpose_epoch_or_owner_token_replay": True,
            "repo": str(repository),
            "repository_global_all_generations": True,
            "require_current_owner_fencing_generation_bound_to_observation": True,
            "revalidate_observation_still_current_before_ack": True,
            "terminal_observation_token": terminal,
        },
        payload={},
        request_digit="4",
    )
    with pytest.raises(mod.InjectedAdminResponseLoss):
        processor.process(acknowledge, failpoint="after_response_persist")
    restarted = mod.AdminCommandProcessor(
        external / "admin",
        repository_root=repository,
        transition_store=store,
    )
    assert json.loads(restarted.process(acknowledge))["result"]["output"] == ""

    outcome = _admin_request(
        "resolve-transition-purpose-outcome",
        arguments={
            "print_archived_outcome": True,
            "purpose_receipt": purpose,
            "read_only": True,
            "repo": str(repository),
            "require_observation_acknowledgement_chain": True,
            "require_unique_exact_archive": True,
        },
        payload={},
        request_digit="5",
    )
    assert json.loads(restarted.process(outcome))["result"]["output"] == "archived_achieved"
    current = _admin_request(
        "resolve-current-top-level-transition",
        arguments={
            "print_none_or_bound_purpose_receipt": True,
            "read_only": True,
            "repo": str(repository),
            "repository_global_all_generations": True,
            "require_unique_live_slot": True,
        },
        payload={},
        request_digit="6",
    )
    assert json.loads(restarted.process(current))["result"]["output"] == "none"
    relationship = _admin_request(
        "classify-purpose-successor",
        arguments={
            "completed_purpose_receipt": purpose,
            "desired_purpose_receipt": purpose,
            "print_same_allowed_predecessor_or_unrelated": True,
            "read_only": True,
            "reject_multiple_matching_archives": True,
            "repo": str(repository),
            "require_closed_reviewed_purpose_dag": True,
            "require_explicit_wave_restart_edge": True,
        },
        payload={},
        request_digit="7",
    )
    assert json.loads(restarted.process(relationship))["result"]["output"] == "same"


def test_admin_repository_snapshot_supports_linked_worktree_and_rejects_multilink(
    tmp_path,
):
    mod = _mod()
    repository = tmp_path / "repo"
    repository.mkdir()
    common = tmp_path / "common.git"
    gitdir = common / "worktrees" / "repo"
    gitdir.mkdir(parents=True)
    (common / "refs" / "heads").mkdir(parents=True)
    (common / "refs" / "heads" / "feature").write_text("a" * 40 + "\n", encoding="ascii")
    marker = repository / ".git"
    marker.write_bytes(f"gitdir: {gitdir.as_posix()}\n".encode("utf-8"))
    (gitdir / "commondir").write_bytes(b"../..\n")
    (gitdir / "gitdir").write_text(str(marker.resolve()) + "\n", encoding="utf-8")
    (gitdir / "HEAD").write_text("ref: refs/heads/feature\n", encoding="ascii")
    source = repository / "source.py"
    source.write_bytes(b"before\n")

    first = mod._admin_repository_snapshot_digest(repository)
    assert first == mod._admin_repository_snapshot_digest(repository)
    source.write_bytes(b"after\n")
    assert mod._admin_repository_snapshot_digest(repository) != first
    os.link(source, repository / "alias.py")
    with pytest.raises(mod.AdminProtocolRefused):
        mod._admin_repository_snapshot_digest(repository)


def test_admin_processor_persists_outcome_before_response_and_rejects_id_collision(tmp_path):
    mod = _mod()
    repository = tmp_path / "repo"
    repository.mkdir()
    external = tmp_path / "external"
    processor = mod.AdminCommandProcessor(external, repository_root=repository)
    request = _admin_request(
        "begin-path-manifest",
        arguments={
            "expected_required_count": 0,
            "expected_test_count": 0,
            "expected_total_count": 1,
            "scope": "source_" + "d" * 64,
        },
        payload={},
        request_digit="d",
    )

    with pytest.raises(mod.InjectedAdminResponseLoss):
        processor.process(request, failpoint="after_response_persist")

    restarted = mod.AdminCommandProcessor(external, repository_root=repository)
    recovered = restarted.process(request)
    assert json.loads(recovered)["accepted"] is True
    assert len(list((external / "path-manifests" / "sessions").glob("*.json"))) == 1

    collision = json.loads(request)
    collision["arguments"]["expected_total_count"] = 2
    with pytest.raises(mod.AdminProtocolRefused):
        restarted.process(_canonical(collision))


def test_admin_processor_has_no_generic_activation_or_unimplemented_effect_fallback(tmp_path):
    mod = _mod()
    repository = tmp_path / "repo"
    repository.mkdir()
    processor = mod.AdminCommandProcessor(tmp_path / "external", repository_root=repository)
    unavailable = _admin_request(
        "install-inactive",
        arguments={},
        payload={},
        request_digit="e",
    )
    with pytest.raises(mod.AdminOperationUnavailable):
        processor.process(unavailable)
    assert processor.production_active is False
    assert list(repository.iterdir()) == []


def test_sealed_admin_entrypoint_resolves_only_the_protected_repository_binding(tmp_path):
    external = tmp_path / "external"
    controller = external / "generations" / "00000001" / "controller"
    record_root = external / "repositories" / ("9" * 64)
    controller.mkdir(parents=True)
    record_root.mkdir(parents=True)
    repository = tmp_path / "repo"
    repository.mkdir()
    repository_identity = hashlib.sha256(
        os.path.normcase(str(repository.resolve())).encode("utf-8")
    ).hexdigest()
    actual_record_root = external / "repositories" / repository_identity
    record_root.rename(actual_record_root)
    (actual_record_root / "checkout-binding.txt").write_text(
        str(repository.resolve()), encoding="utf-8"
    )
    receipt = external / "tofu" / "receipt-00000001.json"
    receipt.parent.mkdir()
    receipt.write_bytes(
        _canonical(
            {
                "activation_state": "inactive",
                "anchor_record_path": str(actual_record_root / "anchor-record.json"),
                "repository_identity": repository_identity,
                "schema": "galaxy.trust-on-first-install/v1",
                "status": "installed_inactive",
            }
        )
    )
    runtime_lock = controller / "runtime.lock.json"
    runtime_lock.write_bytes(
        _canonical(
            {
                "external_root": str(external.resolve()),
                "generation": 1,
                "schema": "galaxy.activation.sealed-runtime/v1",
                "status": "installed_inactive",
                "tofu_receipt_path": str(receipt),
            }
        )
    )
    request = _admin_request(
        "resolve-current-top-level-transition",
        arguments={
            "print_none_or_bound_purpose_receipt": True,
            "read_only": True,
            "repo": str(repository.resolve()),
            "repository_global_all_generations": True,
            "require_unique_live_slot": True,
        },
        payload={},
        request_digit="8",
    )
    encoded = _b64url(request)

    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(PYTHON_ANCHOR),
            "--admin-request-base64url",
            encoded,
            "--runtime-lock-path",
            str(runtime_lock),
            "--runtime-lock-sha256",
            hashlib.sha256(runtime_lock.read_bytes()).hexdigest(),
        ],
        cwd=tmp_path,
        env={},
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    response = json.loads(completed.stdout)
    assert response["accepted"] is True
    assert response["production_active"] is False
    assert response["result"]["output"] == "none"
    assert (external / "admin" / repository_identity / "admin-requests").is_dir()


def test_sealed_admin_entrypoint_refuses_noninactive_runtime_before_repository_access(tmp_path):
    runtime_lock = tmp_path / "runtime.lock.json"
    runtime_lock.write_bytes(
        _canonical(
            {
                "external_root": str((tmp_path / "external").resolve()),
                "generation": 1,
                "schema": "galaxy.activation.sealed-runtime/v1",
                "status": "active",
                "tofu_receipt_path": str(tmp_path / "poisoned-receipt.json"),
            }
        )
    )
    request = _admin_request(
        "begin-path-manifest",
        arguments={
            "expected_required_count": 0,
            "expected_test_count": 0,
            "expected_total_count": 1,
            "scope": "source_" + "7" * 64,
        },
        payload={},
        request_digit="7",
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(PYTHON_ANCHOR),
            "--admin-request-base64url",
            _b64url(request),
            "--runtime-lock-path",
            str(runtime_lock),
            "--runtime-lock-sha256",
            hashlib.sha256(runtime_lock.read_bytes()).hexdigest(),
        ],
        cwd=tmp_path,
        env={},
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert completed.returncode == 78
    assert "inactive" in completed.stderr.casefold()
    assert not (tmp_path / "poisoned-receipt.json").exists()


def test_native_anchor_allows_only_sealed_maintenance_while_generation_is_inactive(tmp_path):
    external = tmp_path / "external"
    repository = tmp_path / "repo"
    repository.mkdir()
    repository_identity = hashlib.sha256(
        os.path.normcase(str(repository.resolve())).encode("utf-8")
    ).hexdigest()
    record_root = external / "repositories" / repository_identity
    controller = external / "generations" / "00000001" / "controller"
    bootstrap = external / "generations" / "00000001" / "bootstrap"
    tofu = external / "tofu"
    for directory in (record_root, controller, bootstrap, tofu):
        directory.mkdir(parents=True, exist_ok=True)
    (record_root / "checkout-binding.txt").write_text(
        str(repository.resolve()), encoding="utf-8"
    )
    sealed_admin = bootstrap / "anchor.py"
    shutil.copyfile(PYTHON_ANCHOR, sealed_admin)
    receipt = tofu / "receipt-00000001.json"
    receipt.write_bytes(
        _canonical(
            {
                "activation_state": "inactive",
                "anchor_record_path": str(record_root / "anchor-record.json"),
                "repository_identity": repository_identity,
                "schema": "galaxy.trust-on-first-install/v1",
                "source_leaves": [
                    {
                        "installed_path": str(sealed_admin),
                        "logical_path": "bootstrap/anchor.py",
                        "sha256": hashlib.sha256(sealed_admin.read_bytes()).hexdigest(),
                        "size": sealed_admin.stat().st_size,
                    }
                ],
                "status": "installed_inactive",
            }
        )
    )
    runtime_lock = controller / "runtime.lock.json"
    runtime_lock.write_bytes(
        _canonical(
            {
                "external_root": str(external.resolve()),
                "file_digests": {
                    "interpreter": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()
                },
                "files": {"interpreter": str(Path(sys.executable).resolve())},
                "generation": 1,
                "image_archive_paths": {},
                "image_digests": {},
                "max_probe_concurrency": 1,
                "runtime_digest": "4" * 64,
                "schema": "galaxy.activation.sealed-runtime/v1",
                "security_profiles": {},
                "status": "installed_inactive",
                "tofu_receipt_path": str(receipt),
            }
        )
    )
    capsule = record_root / "capsule.py"
    capsule.write_text("raise SystemExit(99)\n", encoding="utf-8")
    generation = record_root / "generation.txt"
    generation.write_text("1", encoding="ascii")
    runtime_manifest = record_root / "runtime-manifest.json"
    runtime_manifest.write_bytes(
        _canonical(
            {
                "activation_state": "inactive",
                "closed": True,
                "generation": 1,
                "runtime_digest": "4" * 64,
                "runtime_lock_path": str(runtime_lock),
                "runtime_lock_sha256": hashlib.sha256(runtime_lock.read_bytes()).hexdigest(),
                "schema": 1,
            }
        )
    )
    anchor_record = record_root / "anchor-record.json"
    anchor_record.write_bytes(
        _canonical(
            {
                "activation_state": "inactive",
                "capsule_path": str(capsule),
                "capsule_sha256": hashlib.sha256(capsule.read_bytes()).hexdigest(),
                "generation": 1,
                "generation_path": str(generation),
                "runtime_manifest_path": str(runtime_manifest),
                "runtime_manifest_sha256": hashlib.sha256(
                    runtime_manifest.read_bytes()
                ).hexdigest(),
                "schema": 1,
            }
        )
    )
    request = _admin_request(
        "resolve-current-top-level-transition",
        arguments={
            "print_none_or_bound_purpose_receipt": True,
            "read_only": True,
            "repo": str(repository.resolve()),
            "repository_global_all_generations": True,
            "require_unique_live_slot": True,
        },
        payload={},
        request_digit="6",
    )
    command = _native_anchor_command(anchor_record, operation="maintenance")
    command.extend(["-MaintenanceRequestBase64Url", _b64url(request)])

    completed = subprocess.run(
        command,
        cwd=tmp_path,
        env={"SystemRoot": os.environ["SystemRoot"], "WINDIR": os.environ["WINDIR"]},
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    response = json.loads(completed.stdout)
    assert response["accepted"] is True
    assert response["authority_ceiling"] == "maintenance_only"
    assert response["production_active"] is False
