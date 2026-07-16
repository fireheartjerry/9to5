"""Focused contracts for the sealed GALAXY runtime proposal builder."""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import subprocess

import pytest


def _mod():
    return importlib.import_module("tools.lock_galaxy_runtime")


def _finalizer():
    return importlib.import_module("bootstrap.galaxy_launcher.tofu_finalize")


def _harness():
    return importlib.import_module("bootstrap.galaxy_launcher.activation_harness")


def _leaf(mod, logical_path, path):
    return {
        "logical_path": logical_path,
        "staging_path": None,
        "installed_path": str(path),
        "size": path.stat().st_size,
        "sha256": mod._sha_file(path),
    }


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
    source_leaves = [_leaf(locker, "bootstrap/capsule.py", capsule)]
    artifact_leaves = [
        _leaf(locker, "controller/activation_adapter.py", adapter),
        _leaf(locker, "keys/activation-receipt-public.bin", public_key),
        _leaf(locker, "runtime/runtime.lock.json", lock_path),
    ]
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
