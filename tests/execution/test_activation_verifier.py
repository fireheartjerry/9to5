"""Fail-closed tests for the credentialless live-probe worker."""

from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path

import pytest


def _module():
    return importlib.import_module("bootstrap.galaxy_launcher.activation_verifier")


def _reviewer():
    return importlib.import_module("bootstrap.galaxy_launcher.activation_reviewer")


@pytest.mark.parametrize(
    "raw",
    (
        b'{"schema":1,"schema":1}',
        b'{"value":1.25}',
        b'{"value":NaN}',
        b'{"value":Infinity}',
        b" {}",
    ),
)
def test_probe_specification_rejects_noncanonical_or_ambiguous_json(tmp_path, raw):
    mod = _module()
    path = tmp_path / "probe.json"
    path.write_bytes(raw)
    with pytest.raises(mod.ProbeRefused):
        mod._load_canonical(path)


def test_probe_arguments_are_bound_before_any_broker_effect(tmp_path, monkeypatch):
    mod = _module()
    path = tmp_path / "probe.json"
    value = {"probe_id": "p", "probe_digest": "1" * 64}
    path.write_bytes(mod._canonical_json(value))

    def must_not_run(_path):
        raise AssertionError("broker effect happened before argument binding")

    monkeypatch.setattr(mod, "run_probe", must_not_run)
    assert (
        mod.main(
            [
                "--probe-worker",
                "wrong",
                "1" * 64,
                "--spec",
                str(path),
            ]
        )
        == 78
    )


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _closed_anchor_launch_record(source_path, source_sha256):
    protected_record = source_path.with_name("anchor-record.json")
    json_assembly = r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\System.Web.Extensions.dll"
    host_signature = {
        "is_os_binary": True,
        "signature_type": "Catalog",
        "signer_subject": "CN=Microsoft Windows, O=Microsoft Corporation",
        "signer_thumbprint": "8" * 40,
        "status": "Valid",
    }
    host_signature_sha256 = hashlib.sha256(_canonical(host_signature)).hexdigest()
    return {
        "activation_state": "inactive",
        "anchor_path": str(source_path),
        "anchor_sha256": source_sha256,
        "arguments": [
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(source_path),
            "-ProtectedRecordPath",
            str(protected_record),
            "-Operation",
            "diagnostic",
            "-ExpectedRecordSha256",
            "6" * 64,
            "-ExpectedHostPath",
            r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
            "-ExpectedHostSha256",
            "2" * 64,
            "-ExpectedHostSignatureSha256",
            host_signature_sha256,
            "-ExpectedAnchorSha256",
            source_sha256,
            "-JsonAssemblyPath",
            json_assembly,
            "-ExpectedJsonAssemblySha256",
            "7" * 64,
        ],
        "control_pipe": r"\\.\pipe\9to5-singularity-v1",
        "environment": {
            "PATH": "",
            "PSModulePath": "",
            "SystemRoot": r"C:\Windows",
            "WINDIR": r"C:\Windows",
        },
        "host_path": r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        "host_sha256": "2" * 64,
        "host_signature": host_signature,
        "host_signature_sha256": host_signature_sha256,
        "schema": "galaxy.singularity-anchor-launch/v1",
        "service_name": "9to5Singularity",
        "stdio": {"stderr": "null", "stdin": "null", "stdout": "null"},
        "working_directory": r"C:\ProgramData\9to5\singularity\empty",
    }


def _review_request(
    source_sha256, launch_sha256, installed_anchor_path, *, slot=1, prior=None
):
    return {
        "contamination_controls": [
            "fresh-session",
            "no-writer-rationale",
            "no-writer-transcript",
            "read-only-inputs",
        ],
        "independence_context_sha256": "3" * 64,
        "installed_anchor_path": str(installed_anchor_path),
        "launch_record_sha256": launch_sha256,
        "prior_reviewer_ids": [] if prior is None else prior,
        "review_id": f"review-{slot}",
        "review_slot": slot,
        "reviewer_id": f"independent-reviewer-{slot}",
        "schema": "galaxy.activation-review-request/v1",
        "source_sha256": source_sha256,
    }


def test_anchor_reviewer_is_digest_bound_independent_and_advisory_only(tmp_path):
    mod = _reviewer()
    source = tmp_path / "bootstrap" / "singularity_anchor.ps1"
    source.parent.mkdir()
    source.write_bytes(b"[System.Console]::Out.WriteLine('inactive')\n")
    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    launch = tmp_path / "launch.json"
    launch.write_bytes(_canonical(_closed_anchor_launch_record(source, source_sha256)))
    launch_sha256 = hashlib.sha256(launch.read_bytes()).hexdigest()
    request = tmp_path / "request.json"
    request.write_bytes(
        _canonical(_review_request(source_sha256, launch_sha256, source))
    )

    report = mod.review_anchor(
        source_path=source, launch_record_path=launch, request_path=request
    )

    assert report["decision"] == "advisory_pass"
    assert report["authority"] is False
    assert report["findings"] == []
    assert report["bindings"] == {
        "independence_context_sha256": "3" * 64,
        "installed_anchor_path": str(source),
        "launch_record_sha256": launch_sha256,
        "source_sha256": source_sha256,
    }


def test_anchor_reviewer_refuses_noncanonical_drift_and_contaminated_second_pass(tmp_path):
    mod = _reviewer()
    source = tmp_path / "bootstrap" / "singularity_anchor.ps1"
    source.parent.mkdir()
    source.write_bytes(b"Invoke-Expression $payload\n")
    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    launch = tmp_path / "launch.json"
    launch.write_bytes(_canonical(_closed_anchor_launch_record(source, source_sha256)))
    launch_sha256 = hashlib.sha256(launch.read_bytes()).hexdigest()
    request = tmp_path / "request.json"

    bad_second_pass = _review_request(
        source_sha256,
        launch_sha256,
        source,
        slot=2,
        prior=["independent-reviewer-2"],
    )
    request.write_bytes(_canonical(bad_second_pass))
    with pytest.raises(mod.ActivationReviewRefused):
        mod.review_anchor(
            source_path=source, launch_record_path=launch, request_path=request
        )

    request.write_bytes(
        _canonical(_review_request(source_sha256, launch_sha256, source)) + b"\n"
    )
    with pytest.raises(mod.ActivationReviewRefused):
        mod.review_anchor(
            source_path=source, launch_record_path=launch, request_path=request
        )

    request.write_bytes(
        _canonical(_review_request(source_sha256, launch_sha256, source))
    )
    report = mod.review_anchor(
        source_path=source, launch_record_path=launch, request_path=request
    )
    assert report["decision"] == "advisory_refuse"
    assert report["finding_counts"]["P0"] == 1
    assert report["authority"] is False


def test_anchor_reviewer_binds_staged_bytes_to_the_future_installed_path(tmp_path):
    mod = _reviewer()
    staged_source = tmp_path / "staging" / "singularity_anchor.ps1"
    staged_source.parent.mkdir()
    staged_source.write_bytes(b"[System.Console]::Out.WriteLine('inactive')\n")
    source_sha256 = hashlib.sha256(staged_source.read_bytes()).hexdigest()
    installed_source = Path(
        r"C:\ProgramData\9to5\singularity\generations\00000001"
        r"\bootstrap\singularity_anchor.ps1"
    )
    launch = tmp_path / "launch.json"
    launch.write_bytes(
        _canonical(_closed_anchor_launch_record(installed_source, source_sha256))
    )
    launch_sha256 = hashlib.sha256(launch.read_bytes()).hexdigest()
    request_value = _review_request(
        source_sha256, launch_sha256, installed_source
    )
    request = tmp_path / "request.json"
    request.write_bytes(_canonical(request_value))

    report = mod.review_anchor(
        source_path=staged_source,
        launch_record_path=launch,
        request_path=request,
    )

    assert report["decision"] == "advisory_pass"
    assert report["bindings"]["installed_anchor_path"] == str(installed_source)


def _git_oid(object_type, payload):
    frame = f"{object_type} {len(payload)}".encode("ascii") + b"\0" + payload
    return hashlib.sha1(frame, usedforsecurity=False).hexdigest()


def _source_proposal_fixture(tmp_path):
    parent_payload = b"old\n"
    payload = b"new\n"
    parent_blob_oid = _git_oid("blob", parent_payload)
    blob_oid = _git_oid("blob", payload)
    tree_payload = b"100644 a.txt\0" + bytes.fromhex(blob_oid)
    tree_oid = _git_oid("tree", tree_payload)
    message = "feat: exact proposal"
    commit_payload = (
        f"tree {tree_oid}\n"
        f"parent {'a' * 40}\n"
        "author GALAXY Singularity <singularity@localhost> 0 +0000\n"
        "committer GALAXY Singularity <singularity@localhost> 0 +0000\n"
        f"\n{message}\n"
    ).encode()
    commit_oid = _git_oid("commit", commit_payload)
    raw_objects = {
        blob_oid: ("blob", payload),
        tree_oid: ("tree", tree_payload),
        commit_oid: ("commit", commit_payload),
    }
    object_root = tmp_path / "objects"
    public_objects = []
    for oid, (object_type, object_payload) in raw_objects.items():
        frame = (
            f"{object_type} {len(object_payload)}".encode("ascii")
            + b"\0"
            + object_payload
        )
        path = object_root / oid[:2] / f"{oid[2:]}.frame"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(frame)
        public_objects.append(
            {
                "frame_sha256": hashlib.sha256(frame).hexdigest(),
                "object_type": object_type,
                "oid": oid,
                "payload_size": len(object_payload),
            }
        )
    public_objects.sort(key=lambda item: item["oid"])
    parent_entries = [
        {
            "blob_oid": parent_blob_oid,
            "blob_sha256": hashlib.sha256(parent_payload).hexdigest(),
            "mode": 0o100644,
            "path": "a.txt",
            "size": len(parent_payload),
        }
    ]
    current_entries = [
        {
            "blob_oid": blob_oid,
            "blob_sha256": hashlib.sha256(payload).hexdigest(),
            "mode": 0o100644,
            "path": "a.txt",
            "size": len(payload),
        }
    ]
    changes = [
        {
            "after_mode": 0o100644,
            "after_sha256": hashlib.sha256(payload).hexdigest(),
            "before_mode": 0o100644,
            "before_sha256": hashlib.sha256(parent_payload).hexdigest(),
            "change": "modified",
            "path": "a.txt",
        }
    ]
    parser_receipt = "parserreceipt_" + "b" * 64
    parent_manifest = {
        "contained_parser_receipt_id": parser_receipt,
        "entries": parent_entries,
        "parent_oid": "a" * 40,
        "schema": "galaxy.admin-parent-manifest/v1",
    }
    body = {
        "allowed_paths": ["a.txt"],
        "canonical_ref_written": False,
        "changes": changes,
        "commit_oid": commit_oid,
        "commit_payload_hex": commit_payload.hex(),
        "contained_parser_receipt_id": parser_receipt,
        "current_entries": current_entries,
        "diff_sha256": hashlib.sha256(_canonical(changes)).hexdigest(),
        "discord_enabled": False,
        "fresh_exact_approval_present": False,
        "message": message,
        "normalization_receipt_id": "normalization_" + "1" * 64,
        "normalized_state_sha256": "2" * 64,
        "object_closure_sha256": hashlib.sha256(
            _canonical(public_objects)
        ).hexdigest(),
        "objects": public_objects,
        "owner_fence_id": "ownerfence_" + "3" * 64,
        "parent_entries": parent_entries,
        "parent_manifest_sha256": hashlib.sha256(
            _canonical(parent_manifest)
        ).hexdigest(),
        "parent_oid": "a" * 40,
        "path_manifest_receipt_id": "pathmanifest_" + "4" * 64,
        "production_active": False,
        "purpose_id": "purpose_" + "5" * 64,
        "required_paths": ["a.txt"],
        "schema": "galaxy.source-commit-proposal/v1",
        "transaction_id": "source_" + "6" * 64,
        "tree_manifest_sha256": hashlib.sha256(
            _canonical(current_entries)
        ).hexdigest(),
        "tree_oid": tree_oid,
    }
    proposal_id = "proposal_" + hashlib.sha256(_canonical(body)).hexdigest()
    proposal = {**body, "proposal_id": proposal_id}
    proposal["record_sha256"] = hashlib.sha256(_canonical(proposal)).hexdigest()
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_bytes(_canonical(proposal))
    request = {
        "contamination_controls": [
            "fresh-session",
            "no-writer-rationale",
            "no-writer-transcript",
            "read-only-inputs",
        ],
        "pass_index": 1,
        "proposal_id": proposal_id,
        "proposal_record_sha256": proposal["record_sha256"],
        "reviewer_image_digest": "sha256:" + "7" * 64,
        "reviewer_qualification_receipt_id": "reviewerqualification_" + "8" * 64,
        "reviewer_runtime_sha256": "9" * 64,
        "reviewer_session_id": "reviewsession_" + "a" * 64,
        "schema": "galaxy.source-proposal-review-request/v1",
    }
    request_path = tmp_path / "source-review-request.json"
    request_path.write_bytes(_canonical(request))
    return proposal_path, object_root, request_path


def test_source_proposal_reviewer_rebuilds_object_tree_and_diff_without_authority(
    tmp_path,
):
    mod = _reviewer()
    proposal, object_root, request = _source_proposal_fixture(tmp_path)

    report = mod.review_source_proposal(
        proposal_path=proposal,
        object_root=object_root,
        request_path=request,
        hash_object=_git_oid,
    )

    assert report["decision"] == "accept"
    assert report["findings"] == []
    assert report["independent"] is True
    assert report["network_enabled"] is False
    assert report["canonical_write_observed"] is False
    assert report["source_execution_observed"] is False

    object_path = next(object_root.rglob("*.frame"))
    object_path.write_bytes(object_path.read_bytes() + b"tamper")
    with pytest.raises(mod.ActivationReviewRefused):
        mod.review_source_proposal(
            proposal_path=proposal,
            object_root=object_root,
            request_path=request,
            hash_object=_git_oid,
        )
