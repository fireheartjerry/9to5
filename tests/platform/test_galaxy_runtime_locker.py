"""Focused contracts for the sealed GALAXY runtime proposal builder."""

from __future__ import annotations

import base64
import hashlib
import importlib
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _mod():
    return importlib.import_module("tools.lock_galaxy_runtime")


def _finalizer():
    return importlib.import_module("bootstrap.galaxy_launcher.tofu_finalize")


def _harness():
    return importlib.import_module("bootstrap.galaxy_launcher.activation_harness")


def test_reviewed_build_source_inventory_is_dependency_closed() -> None:
    mod = _mod()
    inventory = set(getattr(mod, "_REVIEWED_BUILD_SOURCE_PATHS", ()))
    required = {
        "bootstrap/galaxy_launcher/activation_image_entrypoint.py",
        "bootstrap/galaxy_launcher/activation_images.lock.json",
        "bootstrap/galaxy_launcher/runtime_manifest.py",
        "bootstrap/galaxy_launcher/sha1dc_source.lock.json",
        "bootstrap/galaxy_launcher/sha1dc_source_passport.json",
        "containers/galaxy/object_parser.Dockerfile",
        "containers/galaxy/sha1dc_object_oracle.c",
        "tools/build_galaxy_launcher.py",
        "tools/build_sha1dc_oracle.py",
        "tools/lock_galaxy_runtime.py",
    }

    assert required <= inventory
    assert all((ROOT / path).is_file() for path in inventory)
    logical_paths = {
        f"reviewed-build-source/{path}": {"logical_path": path}
        for path in inventory
    }
    mod._requireReviewedBuildSourceClosure(logical_paths)
    logical_paths.pop("reviewed-build-source/tools/build_sha1dc_oracle.py")
    with pytest.raises(mod.RuntimeLockRefused, match="reviewed build source"):
        mod._requireReviewedBuildSourceClosure(logical_paths)


def test_installed_runtime_closes_transactional_kernel_executables_and_sources() -> None:
    mod = _mod()
    harness = _harness()
    controller_sources = dict(
        getattr(mod, "_TRANSACTIONAL_KERNEL_CONTROLLER_SOURCES", ())
    )

    assert harness._RUNTIME_FILE_KEYS >= {
        "git_object_writer_source",
        "object_parser_entrypoint",
        "sha1dc_build_evidence",
        "sha1dc_oracle",
        "sha1dc_runtime_source",
    }
    assert controller_sources == {
        "git_object_writer_source": "platform_core/runtime/git_object_writer.py",
        "object_parser_entrypoint": "containers/galaxy/object_parser_entrypoint.py",
        "sha1dc_runtime_source": "platform_core/runtime/sha1dc.py",
    }
    logical_paths = {
        "controller/git_object_writer.py": {"logical_path": "writer"},
        "controller/object_parser_entrypoint.py": {"logical_path": "entrypoint"},
        "controller/sha1dc.py": {"logical_path": "sha1dc"},
    }
    mod._requireTransactionalKernelRuntimeSources(logical_paths)
    with pytest.raises(mod.RuntimeLockRefused, match="transactional kernel runtime source"):
        mod._requireTransactionalKernelRuntimeSources(
            {"controller/object_parser_entrypoint.py": {"logical_path": "entrypoint"}}
        )


def test_sha1dc_windows_host_admission_rejects_linux_elf(tmp_path) -> None:
    mod = _mod()
    executable = tmp_path / "galaxy-sha1dc"
    executable.write_bytes(b"\x7fELF" + b"\0" * 256)

    with pytest.raises(mod.RuntimeLockRefused, match="Windows PE"):
        mod._assert_windows_pe(executable)


@pytest.mark.skipif(
    os.name != "nt"
    or not Path(
        r"C:\Users\fireh\AppData\Local\9to5\galaxy-dev-tools\sources\sha1collisiondetection-855827c583bc30645ba427885caa40c5b81764d2.tar.gz"
    ).is_file(),
    reason="the exact cached SHA1DC source and Windows toolchain are required",
)
def test_windows_sha1dc_oracle_is_double_built_and_runtime_verified(tmp_path) -> None:
    mod = _mod()
    archive = Path(
        r"C:\Users\fireh\AppData\Local\9to5\galaxy-dev-tools\sources\sha1collisiondetection-855827c583bc30645ba427885caa40c5b81764d2.tar.gz"
    )
    output = tmp_path / "galaxy-sha1dc.exe"
    evidence_path = tmp_path / "sha1dc-build-evidence.json"

    evidence = mod._compile_windows_sha1dc(
        source_archive=archive,
        output=output,
        evidence_path=evidence_path,
    )

    assert output.read_bytes().startswith(b"MZ")
    assert evidence_path.read_bytes() == mod._canonical(evidence)
    assert evidence["schema"] == "galaxy.sha1dc-windows-build-evidence/v1"
    assert evidence["authority"] == "inactive"
    assert evidence["network_allowed"] is False
    assert evidence["reproducibility_runs"] == 2
    assert evidence["normal_object_corpus_count"] == 4
    assert evidence["first_output_sha256"] == evidence["second_output_sha256"]
    assert evidence["output_sha256"] == mod._sha_file(output)
    assert mod._probeSha1dc(output, ("--version",)) == (
        0,
        mod._SHA1DC_VERSION,
        b"",
    )
    runtime_sha1dc = importlib.import_module("platform_core.runtime.sha1dc")
    qualified, oracle = runtime_sha1dc.qualifyStandaloneSha1dc(
        executable=output,
        build_evidence=evidence_path,
        sterile_root=tmp_path / "sterile",
    )
    assert qualified.source_revision == mod._SHA1DC_UPSTREAM_REVISION
    assert oracle.hashObject("blob", b"hello\n") == hashlib.sha1(
        b"blob 6\0hello\n",
        usedforsecurity=False,
    ).hexdigest()


def test_transactional_kernel_runtime_artifact_closure_is_closed() -> None:
    mod = _mod()
    leaves = {
        "controller/galaxy-sha1dc.exe": {"sha256": "1" * 64},
        "build-evidence/sha1dc-build-evidence.json": {"sha256": "2" * 64},
    }

    assert mod._requireTransactionalKernelRuntimeArtifacts(leaves) == {
        "sha1dc_build_evidence": leaves[
            "build-evidence/sha1dc-build-evidence.json"
        ],
        "sha1dc_oracle": leaves["controller/galaxy-sha1dc.exe"],
    }
    leaves.pop("controller/galaxy-sha1dc.exe")
    with pytest.raises(mod.RuntimeLockRefused, match="kernel runtime artifact"):
        mod._requireTransactionalKernelRuntimeArtifacts(leaves)


def test_proposal_builder_requires_semantically_verified_exact_nine_role_images(
    tmp_path,
):
    mod = _mod()
    roles = {
        "credentialed_driver",
        "command_sandbox",
        "source_fetcher",
        "source_parser",
        "candidate_parser",
        "object_parser",
        "verifier",
        "reviewer",
        "state_store",
    }
    records = tuple(SimpleNamespace(role=role) for role in sorted(roles))
    calls: list[tuple[object, ...]] = []
    loader = lambda lock_path, *, archive_root: (  # noqa: E731
        calls.append(("load", lock_path, archive_root)) or records
    )
    verifier = lambda values, **kwargs: (  # noqa: E731
        calls.append(("verify", values, kwargs))
        or SimpleNamespace(roles=frozenset(roles), every_byte_verified=True)
    )

    observed = mod._verifiedActivationImageRecords(
        tmp_path / "lock.json",
        tmp_path,
        loader=loader,
        verifier=verifier,
    )

    assert observed == records
    assert calls[1][2] == {
        "network_allowed": False,
        "allow_engine_build": False,
        "allow_pull": False,
    }

    incomplete = lambda values, **kwargs: SimpleNamespace(  # noqa: E731
        roles=frozenset(roles - {"object_parser"}),
        every_byte_verified=True,
    )
    with pytest.raises(mod.RuntimeLockRefused, match="nine-role"):
        mod._verifiedActivationImageRecords(
            tmp_path / "lock.json",
            tmp_path,
            loader=loader,
            verifier=incomplete,
        )


def _leaf(mod, logical_path, path):
    return {
        "logical_path": logical_path,
        "staging_path": None,
        "installed_path": str(path),
        "size": path.stat().st_size,
        "sha256": mod._sha_file(path),
    }


def _partial_recovery_fixture(tmp_path: Path) -> tuple[Path, Path, list[dict[str, object]]]:
    root = tmp_path / "installed"
    controller = root / "generations/00000001/controller"
    bootstrap = root / "generations/00000001/bootstrap"
    controller.mkdir(parents=True)
    bootstrap.mkdir(parents=True)
    service_host = controller / "singularity_service.py"
    bootstrap_script = bootstrap / "tofu_bootstrap.ps1"
    service_host.write_bytes(b"# inert service host\n")
    bootstrap_script.write_bytes(b"# proposal-bound bootstrap\n")
    leaves: list[dict[str, object]] = []
    for logical_path, installed in (
        ("bootstrap/tofu_bootstrap.ps1", bootstrap_script),
        ("controller/singularity_service.py", service_host),
    ):
        leaves.append(
            {
                "logical_path": logical_path,
                "staging_path": str(tmp_path / "payload" / logical_path),
                "installed_path": str(installed),
                "size": installed.stat().st_size,
                "sha256": hashlib.sha256(installed.read_bytes()).hexdigest(),
            }
        )
    proposal = {
        "schema": "galaxy.trust-on-first-install-proposal/v1",
        "status": "ready_for_exact_approval",
        "generation": 1,
        "external_root": str(root),
        "service_name": "9to5Singularity",
        "service_host_path": str(service_host),
        "tofu_receipt_path": str(root / "tofu/receipt-00000001.json"),
        "source_leaves": leaves[:1],
        "artifact_leaves": leaves[1:],
    }
    proposal_path = tmp_path / "tofu-proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
    return proposal_path, root, leaves


def _audit_partial_install(proposal_path: Path) -> subprocess.CompletedProcess[str]:
    script = (
        Path(__file__).resolve().parents[2]
        / "tools/recover_galaxy_partial_tofu.ps1"
    )
    powershell = (
        Path(os.environ["SystemRoot"])
        / "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    return subprocess.run(
        [
            str(powershell),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-AuditIncompleteFirstInstall",
            "-ProposalPath",
            str(proposal_path),
        ],
        cwd=proposal_path.parent,
        env={"SystemRoot": os.environ["SystemRoot"], "WINDIR": os.environ["SystemRoot"]},
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )


def _invoke_recovery_functions(
    body: str, *, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    """Load only function definitions from the recovery script, then run a pure probe."""
    script = Path(__file__).resolve().parents[2] / "tools/recover_galaxy_partial_tofu.ps1"
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    source = f"""
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:RECOVERY_SCRIPT, [ref]$tokens, [ref]$errors)
if ($errors.Count -ne 0) {{ throw 'recovery script parse failed' }}
$definitions = $ast.FindAll({{
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
}}, $true)
foreach ($definition in $definitions) {{
    . ([scriptblock]::Create($definition.Extent.Text))
}}
{body}
"""
    encoded = base64.b64encode(source.encode("utf-16le")).decode("ascii")
    child_env = {
        "SystemRoot": os.environ["SystemRoot"],
        "WINDIR": os.environ["SystemRoot"],
        "RECOVERY_SCRIPT": str(script),
        **env,
    }
    return subprocess.run(
        [
            str(powershell),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encoded,
        ],
        cwd=script.parent,
        env=child_env,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )


@pytest.mark.skipif(os.name != "nt", reason="the production boundary is Windows-only")
def test_powershell_wrapper_is_reproducibly_built_and_survives_empty_environment(tmp_path):
    mod = _mod()
    source = Path(__file__).resolve().parents[2] / "bootstrap/galaxy_launcher/powershell_env_launcher.c"
    output = tmp_path / "powershell_env_launcher.exe"
    evidence_path = tmp_path / "powershell_env_launcher.build.json"

    evidence = mod._compile_powershell_launcher(
        source=source,
        output=output,
        evidence_path=evidence_path,
    )

    assert evidence_path.read_bytes() == mod._canonical(evidence)
    assert evidence["schema"] == "galaxy.native-wrapper-build/v1"
    assert evidence["reproducible"] is True
    assert evidence["first_output_sha256"] == evidence["second_output_sha256"]
    assert evidence["output_sha256"] == mod._sha_file(output)
    assert evidence["source_sha256"] == mod._sha_file(source)
    assert evidence["compiler"]["sha256"] == mod.PINNED_GCC_SHA256
    assert evidence["compiler"]["version"] == mod.PINNED_GCC_VERSION

    completed = subprocess.run(
        [
            str(output),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "[System.Console]::Out.Write('closed-environment')",
        ],
        cwd=tmp_path,
        env={},
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "closed-environment"
    assert completed.stderr == ""
    assert json.loads(evidence_path.read_text(encoding="utf-8")) == evidence

    poisoned = subprocess.run(
        [
            str(output),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "[System.Console]::Out.Write([Environment]::GetEnvironmentVariable('GALAXY_POISON'))",
        ],
        cwd=tmp_path,
        env={"GALAXY_POISON": "must-not-survive"},
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert poisoned.returncode == 0, poisoned.stderr
    assert poisoned.stdout == ""

    refused = subprocess.run(
        [
            str(output),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "exit 42",
        ],
        cwd=tmp_path,
        env={},
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert refused.returncode == 42, (
        "native wrapper must preserve the exact PowerShell failure status; "
        f"stderr={refused.stderr!r}"
    )

    bootstrap = (
        Path(__file__).resolve().parents[2]
        / "bootstrap/galaxy_launcher/tofu_bootstrap.ps1"
    )
    missing_service = subprocess.run(
        [
            str(output),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(bootstrap),
            "-SelfTestMissingServiceQuery",
        ],
        cwd=tmp_path,
        env={},
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert missing_service.returncode == 0, missing_service.stderr
    assert missing_service.stdout.strip() == "missing-service-query:1060"


@pytest.mark.skipif(os.name != "nt", reason="the TOFU recovery boundary is Windows-only")
def test_partial_tofu_recovery_audit_accepts_only_the_exact_declared_inactive_tree(tmp_path):
    proposal_path, root, leaves = _partial_recovery_fixture(tmp_path)

    completed = _audit_partial_install(proposal_path)

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    inventory = "".join(
        f"{leaf['logical_path']}\0{Path(str(leaf['installed_path'])).resolve()}\0"
        f"{leaf['size']}\0{leaf['sha256']}\n"
        for leaf in sorted(leaves, key=lambda item: str(item["logical_path"]))
    ).encode("utf-8")
    assert result == {
        "schema": "galaxy.partial-tofu-recovery-audit/v1",
        "status": "verified_incomplete_first_install",
        "external_root": str(root.resolve()),
        "installed_leaf_count": 2,
        "installed_inventory_sha256": hashlib.sha256(inventory).hexdigest(),
        "service_absent": True,
        "authority_records_absent": True,
        "activation_authority": False,
    }


@pytest.mark.skipif(os.name != "nt", reason="the TOFU recovery boundary is Windows-only")
@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("extra_file", "undeclared file"),
        ("leaf_drift", "digest or size drift"),
        ("authority_record", "authority record exists"),
    ],
)
def test_partial_tofu_recovery_audit_refuses_ambiguous_or_authoritative_roots(
    tmp_path, mutation, message
):
    proposal_path, root, leaves = _partial_recovery_fixture(tmp_path)
    if mutation == "extra_file":
        (root / "unexpected.txt").write_text("ambiguous", encoding="utf-8")
    elif mutation == "leaf_drift":
        Path(str(leaves[0]["installed_path"])).write_bytes(b"changed\n")
    else:
        (root / "activation-runtime.json").write_text("{}", encoding="utf-8")

    completed = _audit_partial_install(proposal_path)

    assert completed.returncode == 2
    assert message in completed.stderr
    assert root.is_dir()


@pytest.mark.skipif(os.name != "nt", reason="the TOFU recovery boundary is Windows-only")
@pytest.mark.parametrize("logical_path", ["bootstrap/bad\nname", "bootstrap/bad\x00name"])
def test_partial_tofu_recovery_audit_refuses_inventory_delimiter_injection(
    tmp_path, logical_path
):
    proposal_path, root, _leaves = _partial_recovery_fixture(tmp_path)
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    proposal["source_leaves"][0]["logical_path"] = logical_path
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")

    completed = _audit_partial_install(proposal_path)

    assert completed.returncode == 2
    assert "proposal leaf schema is malformed" in completed.stderr
    assert root.is_dir()


@pytest.mark.skipif(os.name != "nt", reason="the TOFU recovery boundary is Windows-only")
def test_partial_tofu_recovery_audit_refuses_duplicate_logical_paths(tmp_path):
    proposal_path, root, leaves = _partial_recovery_fixture(tmp_path)
    duplicate = root / "generations/00000001/controller/duplicate.py"
    duplicate.write_bytes(b"# another declared leaf\n")
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    proposal["artifact_leaves"].append(
        {
            "logical_path": leaves[0]["logical_path"],
            "staging_path": str(tmp_path / "payload/duplicate.py"),
            "installed_path": str(duplicate),
            "size": duplicate.stat().st_size,
            "sha256": hashlib.sha256(duplicate.read_bytes()).hexdigest(),
        }
    )
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")

    completed = _audit_partial_install(proposal_path)

    assert completed.returncode == 2
    assert "duplicate logical proposal path" in completed.stderr
    assert root.is_dir()


@pytest.mark.skipif(os.name != "nt", reason="the TOFU recovery boundary is Windows-only")
def test_partial_tofu_recovery_refuses_journal_equal_to_external_root(tmp_path):
    root = tmp_path / "installed"
    root.mkdir()
    proposal = tmp_path / "proposal.json"
    response = tmp_path / "response.txt"
    proposal.write_text("{}", encoding="utf-8")
    response.write_text("approval", encoding="ascii")

    completed = _invoke_recovery_functions(
        """
try {
    Assert-RecoveryEvidencePaths -ProposalFile $env:TEST_PROPOSAL `
        -ResponseFile $env:TEST_RESPONSE -JournalDirectory $env:TEST_ROOT `
        -Root $env:TEST_ROOT
    [Console]::Out.WriteLine('unexpected-success')
    exit 0
}
catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 2
}
""",
        env={
            "TEST_PROPOSAL": str(proposal),
            "TEST_RESPONSE": str(response),
            "TEST_ROOT": str(root),
        },
    )

    assert completed.returncode == 2
    assert "recovery journal must be an existing directory outside the external root" in completed.stderr


@pytest.mark.skipif(os.name != "nt", reason="the TOFU recovery boundary is Windows-only")
def test_partial_tofu_recovery_preflights_conflicting_receipt_before_deletion(tmp_path):
    receipt = tmp_path / "receipt.json"
    receipt.write_bytes(b"conflicting")
    completed = _invoke_recovery_functions(
        """
try {
    $expected = [System.Text.Encoding]::ASCII.GetBytes('expected')
    Assert-RecoveryReceiptPrecondition -Path $env:TEST_RECEIPT `
        -ExpectedBytes $expected -RootExists $true
    [Console]::Out.WriteLine('unexpected-success')
    exit 0
}
catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 2
}
""",
        env={"TEST_RECEIPT": str(receipt)},
    )

    assert completed.returncode == 2
    assert "recovery receipt replay bytes differ" in completed.stderr


@pytest.mark.skipif(os.name != "nt", reason="the TOFU recovery boundary is Windows-only")
def test_partial_tofu_recovery_allows_vacant_receipt_path_before_deletion(tmp_path):
    receipt = tmp_path / "receipt.json"
    completed = _invoke_recovery_functions(
        """
$expected = [System.Text.Encoding]::ASCII.GetBytes('expected')
Assert-RecoveryReceiptPrecondition -Path $env:TEST_RECEIPT `
    -ExpectedBytes $expected -RootExists $true
[Console]::Out.WriteLine('vacant')
""",
        env={"TEST_RECEIPT": str(receipt)},
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "vacant"


@pytest.mark.skipif(os.name != "nt", reason="the TOFU recovery boundary is Windows-only")
def test_partial_tofu_recovery_canonical_drive_root_remains_absolute():
    drive_root = str(Path(os.environ["SystemRoot"]).anchor)
    completed = _invoke_recovery_functions(
        "[Console]::Out.WriteLine((ConvertTo-CanonicalDrivePath $env:TEST_DRIVE_ROOT))",
        env={"TEST_DRIVE_ROOT": drive_root},
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == drive_root


def test_python_runtime_copy_excludes_mutable_bytecode_caches(tmp_path):
    mod = _mod()
    source = tmp_path / "source"
    (source / "Lib/__pycache__").mkdir(parents=True)
    (source / "python.exe").write_bytes(b"interpreter")
    (source / "Lib/module.py").write_bytes(b"VALUE = 1\n")
    (source / "Lib/module.pyc").write_bytes(b"mutable")
    (source / "Lib/__pycache__/module.cpython-312.pyc").write_bytes(b"mutable")
    staging = tmp_path / "staging"
    installed = tmp_path / "installed"

    leaves = mod._copy_python_tree(source, staging, installed)

    assert {leaf["logical_path"] for leaf in leaves} == {
        "python/Lib/module.py",
        "python/python.exe",
    }
    assert not list(staging.rglob("*.pyc"))


def test_reviewed_source_manifest_and_platform_lock_close_every_declared_byte(tmp_path):
    mod = _mod()
    source_a = tmp_path / "singularity_anchor.ps1"
    source_b = tmp_path / "activation_reviewer.py"
    source_a.write_bytes(b"anchor\n")
    source_b.write_bytes(b"reviewer\n")
    python_root = tmp_path / "python"
    (python_root / "Lib").mkdir(parents=True)
    (python_root / "python.exe").write_bytes(b"python")
    (python_root / "python312.dll").write_bytes(b"dll")
    (python_root / "Lib/os.py").write_bytes(b"stdlib\n")
    (python_root / "Lib/stale.pyc").write_bytes(b"mutable")
    powershell = tmp_path / "powershell.exe"
    json_assembly = tmp_path / "System.Web.Extensions.dll"
    image_lock = tmp_path / "activation_images.lock.json"
    powershell.write_bytes(b"host")
    json_assembly.write_bytes(b"parser")
    image_lock.write_bytes(b'{"schema":"galaxy.activation-images/v1"}')
    manifest_path = tmp_path / "manifest.json"
    lock_path = tmp_path / "runtime.lock.json"

    manifest, lock = mod.write_reviewed_source_lock(
        manifest_path=manifest_path,
        lock_path=lock_path,
        python_root=python_root,
        powershell=powershell,
        json_assembly=json_assembly,
        image_lock=image_lock,
        source_paths={
            "bootstrap/galaxy_launcher/activation_reviewer.py": source_b,
            "bootstrap/galaxy_launcher/singularity_anchor.ps1": source_a,
        },
    )

    assert manifest_path.read_bytes() == mod._canonical(manifest)
    assert lock_path.read_bytes() == mod._canonical(lock)
    assert manifest["authority"] == "inactive"
    assert [leaf["path"] for leaf in manifest["source_leaves"]] == [
        "bootstrap/galaxy_launcher/activation_reviewer.py",
        "bootstrap/galaxy_launcher/singularity_anchor.ps1",
    ]
    assert {leaf["path"] for leaf in lock["python_leaves"]} == {
        "Lib/os.py",
        "python.exe",
        "python312.dll",
    }
    assert lock["source_manifest_sha256"] == mod._sha_file(manifest_path)
    assert mod.verify_reviewed_source_lock(
        manifest_path=manifest_path,
        lock_path=lock_path,
        source_paths={
            "bootstrap/galaxy_launcher/activation_reviewer.py": source_b,
            "bootstrap/galaxy_launcher/singularity_anchor.ps1": source_a,
        },
    ) == lock

    source_a.write_bytes(b"drift\n")
    with pytest.raises(mod.RuntimeLockRefused, match="source leaf drift"):
        mod.verify_reviewed_source_lock(
            manifest_path=manifest_path,
            lock_path=lock_path,
            source_paths={
                "bootstrap/galaxy_launcher/activation_reviewer.py": source_b,
                "bootstrap/galaxy_launcher/singularity_anchor.ps1": source_a,
            },
        )


@pytest.mark.skipif(os.name != "nt", reason="the pinned host is Windows PowerShell")
def test_powershell_signature_record_is_valid_os_owned_and_digest_bound():
    mod = _mod()
    powershell = (
        Path(os.environ["SystemRoot"])
        / "System32/WindowsPowerShell/v1.0/powershell.exe"
    )

    record = mod._powershell_signature_record(powershell)

    assert record["status"] == "Valid"
    assert record["is_os_binary"] is True
    assert record["signature_type"] in {"Catalog", "Authenticode"}
    assert record["signer_subject"].startswith("CN=Microsoft Windows")
    assert len(record["signer_thumbprint"]) == 40
    assert record == mod._powershell_signature_record(powershell)


@pytest.mark.skipif(os.name != "nt", reason="the TOFU bootstrap is Windows-only")
def test_ps51_tofu_singleton_leaf_selection_is_array_safe_under_strict_mode():
    script = (
        Path(__file__).resolve().parents[2]
        / "bootstrap/galaxy_launcher/tofu_bootstrap.ps1"
    )
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    completed = subprocess.run(
        [
            str(powershell),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-SelfTestSingletonLeafSelection",
        ],
        cwd=script.parent,
        env={"SystemRoot": os.environ["SystemRoot"], "WINDIR": os.environ["SystemRoot"]},
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "bootstrap/tofu_finalize.py"


def test_finalizer_creates_only_canonical_inactive_receipt_pointer_and_checkout_anchor(tmp_path):
    locker = _mod()
    finalizer = _finalizer()
    root = tmp_path / "installed"
    controller = root / "generations/00000001/controller"
    bootstrap = root / "generations/00000001/bootstrap"
    keys = root / "generations/00000001/keys"
    for directory in (controller, bootstrap, keys):
        directory.mkdir(parents=True, exist_ok=True)
    capsule = bootstrap / "capsule.py"
    capsule.write_bytes(b"ACTIVATION_STATE = 'inactive'\n")
    anchor_source = bootstrap / "singularity_anchor.ps1"
    developer_client = bootstrap / "developer_redirect.ps1"
    request_client = root / "bin/singularity-admin-client.ps1"
    source_manifest = bootstrap / "manifest.json"
    source_runtime_lock = bootstrap / "runtime.lock.json"
    anchor_source.write_bytes(b"# inert native anchor\n")
    developer_client.write_bytes(b"# request-only redirect\n")
    request_client.parent.mkdir(parents=True)
    request_client.write_bytes(b"# installed request client\n")
    source_manifest.write_bytes(b'{"authority":"inactive"}')
    source_runtime_lock.write_bytes(b'{"authority":"inactive"}')
    host = root / "system/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
    json_assembly = root / "system/Windows/Microsoft.NET/Framework64/v4.0.30319/System.Web.Extensions.dll"
    host.parent.mkdir(parents=True)
    json_assembly.parent.mkdir(parents=True)
    host.write_bytes(b"host")
    json_assembly.write_bytes(b"json-parser")
    public_key = keys / "activation-receipt-public.bin"
    public_key.write_bytes(bytes(range(32)))
    adapter = controller / "activation_adapter.py"
    adapter.write_bytes(b"# inert adapter\n")
    receipt_path = root / "tofu/receipt-00000001.json"
    lock_path = controller / "runtime.lock.json"
    runtime_digest = "a" * 64
    image_digests = {"verifier": "b" * 64}
    lock = {
        "schema": "galaxy.activation.sealed-runtime/v1",
        "status": "installed_inactive",
        "generation": 1,
        "external_root": str(root),
        "files": {
            "adapter": str(adapter),
            "receipt_public_key": str(public_key),
        },
        "file_digests": {
            "adapter": locker._sha_file(adapter),
            "receipt_public_key": locker._sha_file(public_key),
        },
        "runtime_digest": runtime_digest,
        "image_digests": image_digests,
        "tofu_receipt_path": str(receipt_path),
    }
    lock_path.write_bytes(locker._canonical(lock))
    source_leaves = [
        _leaf(locker, "bootstrap/capsule.py", capsule),
        _leaf(locker, "bootstrap/developer_redirect.ps1", developer_client),
        _leaf(locker, "bootstrap/manifest.json", source_manifest),
        _leaf(locker, "bootstrap/runtime.lock.json", source_runtime_lock),
        _leaf(locker, "bootstrap/singularity_admin_client.ps1", request_client),
        _leaf(locker, "bootstrap/singularity_anchor.ps1", anchor_source),
    ]
    source_leaves.sort(key=lambda leaf: leaf["logical_path"])
    artifact_leaves = [
        _leaf(locker, "controller/activation_adapter.py", adapter),
        _leaf(locker, "keys/activation-receipt-public.bin", public_key),
        _leaf(locker, "runtime/runtime.lock.json", lock_path),
        _leaf(locker, "system/System.Web.Extensions.dll", json_assembly),
        _leaf(locker, "system/powershell.exe", host),
    ]
    artifact_leaves.sort(key=lambda leaf: leaf["logical_path"])
    source_root = locker._leaf_root("source", source_leaves)
    artifact_root = locker._leaf_root("artifact", artifact_leaves)
    merkle_root = __import__("hashlib").sha256(
        b"galaxy-tofu-v1\0"
        + bytes.fromhex(source_root)
        + bytes.fromhex(artifact_root)
    ).hexdigest()
    nonce = "c" * 64
    challenge = f"TRUST SINGULARITY BOOTSTRAP {merkle_root} NONCE {nonce}"
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    repository_identity = __import__("hashlib").sha256(
        os.path.normcase(str(checkout.resolve())).encode("utf-8")
    ).hexdigest()
    record_root = root / "repositories" / repository_identity
    anchor_record_path = record_root / "anchor-record.json"
    launch_record_path = record_root / "anchor-launch-record.json"
    runtime_manifest_record = {
        "activation_state": "inactive",
        "closed": True,
        "generation": 1,
        "runtime_digest": runtime_digest,
        "runtime_lock_path": str(lock_path),
        "runtime_lock_sha256": locker._sha_file(lock_path),
        "schema": 1,
    }
    anchor_record = {
        "activation_state": "inactive",
        "capsule_path": str(record_root / "capsule.py"),
        "capsule_sha256": locker._sha_file(capsule),
        "generation": 1,
        "generation_path": str(record_root / "generation.txt"),
        "runtime_manifest_path": str(record_root / "runtime-manifest.json"),
        "runtime_manifest_sha256": hashlib.sha256(
            locker._canonical(runtime_manifest_record)
        ).hexdigest(),
        "schema": 1,
    }
    anchor_record_sha256 = hashlib.sha256(locker._canonical(anchor_record)).hexdigest()
    host_signature = {
        "is_os_binary": True,
        "signature_type": "Catalog",
        "signer_subject": "CN=Microsoft Windows, O=Microsoft Corporation",
        "signer_thumbprint": "8" * 40,
        "status": "Valid",
    }
    host_signature_sha256 = hashlib.sha256(
        locker._canonical(host_signature)
    ).hexdigest()
    anchor_arguments = [
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-File",
        str(anchor_source),
        "-ProtectedRecordPath",
        str(anchor_record_path),
        "-Operation",
        "diagnostic",
        "-ExpectedRecordSha256",
        anchor_record_sha256,
        "-ExpectedHostPath",
        str(host),
        "-ExpectedHostSha256",
        locker._sha_file(host),
        "-ExpectedHostSignatureSha256",
        host_signature_sha256,
        "-ExpectedAnchorSha256",
        locker._sha_file(anchor_source),
        "-JsonAssemblyPath",
        str(json_assembly),
        "-ExpectedJsonAssemblySha256",
        locker._sha_file(json_assembly),
    ]
    anchor_launch_record = {
        "activation_state": "inactive",
        "anchor_path": str(anchor_source),
        "anchor_sha256": locker._sha_file(anchor_source),
        "arguments": anchor_arguments,
        "control_pipe": r"\\.\pipe\9to5-singularity-v1",
        "environment": {
            "PATH": "",
            "PSModulePath": "",
            "SystemRoot": str(host.parents[3]),
            "WINDIR": str(host.parents[3]),
        },
        "host_path": str(host),
        "host_sha256": locker._sha_file(host),
        "host_signature": host_signature,
        "host_signature_sha256": host_signature_sha256,
        "schema": "galaxy.singularity-anchor-launch/v1",
        "service_name": "9to5Singularity",
        "stdio": {"stderr": "null", "stdin": "null", "stdout": "null"},
        "working_directory": str(record_root / "empty-cwd"),
    }
    proposal = {
        "schema": "galaxy.trust-on-first-install-proposal/v1",
        "status": "ready_for_exact_approval",
        "generation": 1,
        "staging_root": str(tmp_path),
        "payload_root": str(tmp_path),
        "external_root": str(root),
        "runtime_lock_staging_path": str(lock_path),
        "runtime_lock_installed_path": str(lock_path),
        "tofu_receipt_path": str(receipt_path),
        "source_leaves": source_leaves,
        "artifact_leaves": artifact_leaves,
        "source_root": source_root,
        "artifact_root": artifact_root,
        "merkle_root": merkle_root,
        "nonce": nonce,
        "challenge": challenge,
        "runtime_digest": runtime_digest,
        "image_digests": image_digests,
        "activation_acceptance_sha256": _harness().PINNED_ACCEPTANCE_LEDGER_DIGEST,
        "activation_runtime_profiles_sha256": _harness().PINNED_RUNTIME_PROFILE_LEDGER_DIGEST,
        "activation_adapter_sha256": locker._sha_file(adapter),
        "activation_receipt_public_key": public_key.read_bytes().hex(),
        "activation_receipt_public_key_digest": __import__("hashlib").sha256(
            public_key.read_bytes()
        ).hexdigest(),
        "operator_sid": "S-1-5-21-1-2-3-1001",
        "service_sid": "S-1-5-80-1-2-3-4-5",
        "service_name": "9to5Singularity",
        "checkout_path": str(checkout.resolve()),
        "repository_identity": repository_identity,
        "service_host_path": str(adapter),
        "anchor_source_path": str(anchor_source),
        "anchor_source_sha256": locker._sha_file(anchor_source),
        "developer_client_source_path": str(developer_client),
        "developer_client_source_sha256": locker._sha_file(developer_client),
        "request_client_path": str(request_client),
        "request_client_sha256": locker._sha_file(request_client),
        "host_path": str(host),
        "host_sha256": locker._sha_file(host),
        "host_signature": host_signature,
        "host_signature_sha256": host_signature_sha256,
        "json_assembly_path": str(json_assembly),
        "json_assembly_sha256": locker._sha_file(json_assembly),
        "anchor_record_path": str(anchor_record_path),
        "anchor_record_sha256": anchor_record_sha256,
        "anchor_launch_record_path": str(launch_record_path),
        "anchor_launch_record_sha256": hashlib.sha256(
            locker._canonical(anchor_launch_record)
        ).hexdigest(),
        "anchor_launch_record": anchor_launch_record,
        "anchor_task_name": "9to5SingularityAnchor",
        "source_manifest_sha256": locker._sha_file(source_manifest),
        "source_runtime_lock_sha256": locker._sha_file(source_runtime_lock),
        "interpreter_path": str(adapter),
        "interpreter_staging_path": str(adapter),
        "proposal_verifier_staging_path": str(adapter),
        "powershell_wrapper_build": {
            "schema": "galaxy.native-wrapper-build/v1",
            "reproducible": True,
        },
    }
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_bytes(locker._canonical(proposal))
    response_path = tmp_path / "response.txt"
    response_path.write_bytes(challenge.encode("ascii"))

    result = finalizer.finalize_inactive_install(
        proposal_path=proposal_path,
        response_path=response_path,
        dacl_sddl="O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FA;;;S-1-5-80-1-2-3-4-5)(A;;0x1200a9;;;S-1-5-21-1-2-3-1001)",
    )

    assert result["status"] == "installed_inactive"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt_path.read_bytes() == locker._canonical(receipt)
    assert receipt["approval_response_sha256"] == __import__("hashlib").sha256(
        challenge.encode("ascii")
    ).hexdigest()
    assert receipt["monotone_generation"] == 1
    assert receipt["status"] == "installed_inactive"
    pointer_path = root / "activation-runtime.json"
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    assert pointer_path.read_bytes() == locker._canonical(pointer)
    assert pointer["status"] == "installed_inactive"
    anchor_path = root / "repositories" / repository_identity / "anchor-record.json"
    anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
    assert anchor_path.read_bytes() == locker._canonical(anchor)
    assert anchor["activation_state"] == "inactive"
    assert Path(anchor["capsule_path"]).read_bytes() == capsule.read_bytes()
    launch_path = anchor_path.with_name("anchor-launch-record.json")
    launch = json.loads(launch_path.read_text(encoding="utf-8"))
    assert launch_path.read_bytes() == locker._canonical(launch)
    assert launch["activation_state"] == "inactive"
    assert launch["anchor_path"] == str(anchor_source)
    assert launch["arguments"][:5] == [
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-File",
        str(anchor_source),
    ]
    assert _harness()._verify_tofu_receipt(
        receipt,
        root=root.resolve(),
        generation=1,
        runtime_digest=runtime_digest,
        image_digests=image_digests,
        adapter_digest=locker._sha_file(adapter),
        public_key=public_key.read_bytes(),
        required_paths={lock_path.resolve(), adapter.resolve(), public_key.resolve()},
    ) == merkle_root


def test_finalizer_rejects_nonexact_response_before_writing_authority_records(tmp_path):
    finalizer = _finalizer()
    proposal = {
        "schema": "galaxy.trust-on-first-install-proposal/v1",
        "status": "ready_for_exact_approval",
        "challenge": "TRUST SINGULARITY BOOTSTRAP " + "a" * 64 + " NONCE " + "b" * 64,
        "external_root": str(tmp_path / "installed"),
    }
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
    response_path = tmp_path / "response.txt"
    response_path.write_bytes((proposal["challenge"] + "\n").encode("ascii"))
    with pytest.raises(finalizer.TofuFinalizationRefused, match="exact challenge"):
        finalizer.finalize_inactive_install(
            proposal_path=proposal_path,
            response_path=response_path,
            dacl_sddl="D:P",
        )
    assert not (tmp_path / "installed/activation-runtime.json").exists()
