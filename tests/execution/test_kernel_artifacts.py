"""Externally signed, staging-only transactional-kernel artifact qualification."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from bootstrap.galaxy_launcher.activation_crypto import public_key_from_seed, sign

_SEED = bytes(range(32))


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def test_docker_server_identity_ignores_ambient_cli_configuration(tmp_path, monkeypatch):
    from platform_core.runtime import kernel_artifacts as mod

    ambient = tmp_path / "ambient-docker-config"
    ambient.mkdir()
    (ambient / "config.json").write_text('{"credsStore":"poison"}', encoding="utf-8")
    monkeypatch.setenv("DOCKER_CONFIG", str(ambient))
    observed: dict[str, object] = {}
    server = {"Arch": "amd64", "Os": "linux"}

    def fake_run(argv, **kwargs):
        environment = kwargs["env"]
        config_root = Path(environment["DOCKER_CONFIG"])
        observed["config_root"] = config_root
        observed["environment"] = dict(environment)
        assert config_root.is_dir()
        assert not any(config_root.iterdir())
        return SimpleNamespace(
            returncode=0,
            stdout=_canonical(server),
            stderr=b"",
        )

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    digest = mod._dockerServerIdentityDigest(tmp_path / "docker.exe", "desktop-linux")

    assert digest == hashlib.sha256(_canonical(server)).hexdigest()
    assert observed["config_root"] != ambient
    assert not Path(observed["config_root"]).exists()
    assert observed["environment"]["DOCKER_HOST"] == "npipe:////./pipe/dockerDesktopLinuxEngine"


def test_host_sha1dc_attestation_uses_the_sealed_standalone_closure(
    tmp_path, monkeypatch
):
    from platform_core.runtime import kernel_artifacts as mod

    executable = tmp_path / "controller" / "galaxy-sha1dc.exe"
    build_evidence = tmp_path / "build-evidence" / "sha1dc-build-evidence.json"
    expected = {
        "schema": "galaxy.sha1dc-standalone-evidence/v1",
        "executable_path": str(executable),
        "executable_sha256": "1" * 64,
        "executable_link_count": 1,
        "runtime_attestation_digest": "2" * 64,
        "build_evidence_path": str(build_evidence),
        "build_evidence_sha256": "3" * 64,
        "source_revision": "855827c583bc30645ba427885caa40c5b81764d2",
        "protocol": "galaxy.sha1dc-object-oracle/v1",
        "collision_detection": "SHA1_DC",
        "network_allowed": False,
    }
    calls: list[tuple[object, ...]] = []

    class Evidence:
        def toDict(self):
            return dict(expected)

    class Oracle:
        def revalidate(self):
            calls.append(("revalidate",))

    def qualify(**kwargs):
        calls.append(("qualify", kwargs))
        return Evidence(), Oracle()

    monkeypatch.setattr(mod, "qualifyStandaloneSha1dc", qualify)

    assert mod._attestHostSha1dc(expected) == expected
    assert calls[0][0] == "qualify"
    assert calls[0][1]["executable"] == str(executable)
    assert calls[0][1]["build_evidence"] == str(build_evidence)
    assert calls[1] == ("revalidate",)


def _resign(payload: dict[str, object], receipt_path: Path, pointer_path: Path) -> None:
    identity_payload = dict(payload)
    identity_payload.pop("qualification_id")
    payload["qualification_id"] = hashlib.sha256(_canonical(identity_payload)).hexdigest()
    signature = base64.urlsafe_b64encode(sign(_SEED, _canonical(payload))).decode().rstrip("=")
    receipt_path.write_bytes(
        _canonical({"signed_payload": payload, "signature_base64url": signature})
    )
    pointer = json.loads(pointer_path.read_bytes())
    pointer["qualification_sha256"] = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    pointer_path.write_bytes(_canonical(pointer))


def _write_qualification(tmp_path: Path, monkeypatch):
    from platform_core.runtime import kernel_artifacts as mod

    root = tmp_path / "installed"
    generation = root / "generations" / "00000007"
    controller = generation / "controller"
    images = generation / "images"
    qualifications = generation / "qualifications"
    build_evidence_root = generation / "build-evidence"
    for directory in (controller, images, qualifications, build_evidence_root):
        directory.mkdir(parents=True)
    runtime_lock = controller / "runtime.lock.json"
    runtime_lock.write_bytes(b"sealed-runtime-lock")
    docker = controller / "docker.exe"
    docker.write_bytes(b"sealed-docker")
    parser = controller / "object_parser_entrypoint.py"
    parser.write_bytes(b"print('sealed parser')\n")
    writer = controller / "git_object_writer.py"
    writer.write_bytes(
        (Path(__file__).parents[2] / "platform_core" / "runtime" / "git_object_writer.py").read_bytes()
    )
    sha1dc = controller / "galaxy-sha1dc.exe"
    sha1dc.write_bytes(b"sealed-standalone-sha1dc")
    sha1dc_runtime_source = controller / "sha1dc.py"
    sha1dc_runtime_source.write_bytes(
        (Path(__file__).parents[2] / "platform_core" / "runtime" / "sha1dc.py").read_bytes()
    )
    sha1dc_build_evidence = build_evidence_root / "sha1dc-build-evidence.json"
    sha1dc_build_evidence.write_bytes(b"sealed-sha1dc-build-evidence")
    archive = images / "object-parser.oci.tar"
    archive.write_bytes(b"sealed-object-parser-archive")
    public = generation / "keys" / "activation-receipt-public.bin"
    public.parent.mkdir()
    public.write_bytes(public_key_from_seed(_SEED))
    sha1dc_binding = {
        "schema": "galaxy.sha1dc-runtime-binding/v1",
        "executable_path": "/opt/galaxy/galaxy-sha1dc",
        "executable_sha256": "1" * 64,
        "executable_size": 4096,
        "source_lock_sha256": "2" * 64,
        "source_archive_sha256": "3" * 64,
        "source_passport_sha256": "4" * 64,
        "wrapper_sha256": "5" * 64,
        "builder_base_digest": "6" * 64,
        "runtime_base_digest": "7" * 64,
        "reproducibility_runs": 2,
        "self_test": "collision-detected",
        "normal_object_corpus_count": 4,
        "network_allowed": False,
    }
    sha1dc_binding_digest = hashlib.sha256(_canonical(sha1dc_binding)).hexdigest()
    host_sha1dc = {
        "schema": "galaxy.sha1dc-standalone-evidence/v1",
        "executable_path": str(sha1dc),
        "executable_sha256": hashlib.sha256(sha1dc.read_bytes()).hexdigest(),
        "executable_link_count": 1,
        "runtime_attestation_digest": "9" * 64,
        "build_evidence_path": str(sha1dc_build_evidence),
        "build_evidence_sha256": hashlib.sha256(
            sha1dc_build_evidence.read_bytes()
        ).hexdigest(),
        "source_revision": "855827c583bc30645ba427885caa40c5b81764d2",
        "protocol": "galaxy.sha1dc-object-oracle/v1",
        "collision_detection": "SHA1_DC",
        "network_allowed": False,
    }
    payload = {
        "schema": "galaxy.kernel-artifact-qualification/v1",
        "status": "qualified_staging_only",
        "authority_ceiling": "staging_only",
        "qualification_id": "",
        "generation": 7,
        "controller_source_revision": "b" * 40,
        "runtime_digest": "c" * 64,
        "runtime_lock_sha256": hashlib.sha256(runtime_lock.read_bytes()).hexdigest(),
        "issued_at": "2026-07-16T18:00:00Z",
        "expires_at": "2026-07-17T18:00:00Z",
        "revocation_generation": 3,
        "docker": {
            "executable_path": str(docker),
            "executable_sha256": hashlib.sha256(docker.read_bytes()).hexdigest(),
            "context": "desktop-linux",
            "server_identity_digest": "d" * 64,
        },
        "object_parser": {
            "repository": "galaxy-r3/object-parser",
            "manifest_digest": "e" * 64,
            "archive_path": str(archive),
            "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "config_digest": "f" * 64,
            "toolchain_digest": "0" * 64,
            "runtime_digest": "1" * 64,
            "security_profile_digest": "2" * 64,
            "sha1dc_binding_digest": sha1dc_binding_digest,
            "runtime_entrypoint_path": str(parser),
            "runtime_entrypoint_sha256": hashlib.sha256(parser.read_bytes()).hexdigest(),
        },
        "writer": {
            "source_path": str(writer),
            "source_sha256": hashlib.sha256(writer.read_bytes()).hexdigest(),
            "version_digest": hashlib.sha256(writer.read_bytes()).hexdigest(),
            "host_sha1dc": host_sha1dc,
        },
    }
    identity_payload = dict(payload)
    identity_payload.pop("qualification_id")
    payload["qualification_id"] = hashlib.sha256(_canonical(identity_payload)).hexdigest()
    signature = base64.urlsafe_b64encode(sign(_SEED, _canonical(payload))).decode().rstrip("=")
    receipt = {"signed_payload": payload, "signature_base64url": signature}
    receipt_path = qualifications / "kernel-artifacts.json"
    receipt_path.write_bytes(_canonical(receipt))
    pointer = {
        "schema": "galaxy.kernel-artifacts-pointer/v1",
        "status": "qualified_staging_only",
        "generation": 7,
        "revocation_generation": 3,
        "qualification_path": str(receipt_path),
        "qualification_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        "runtime_lock_sha256": hashlib.sha256(runtime_lock.read_bytes()).hexdigest(),
    }
    (root / "kernel-artifacts.current.json").write_bytes(_canonical(pointer))
    runtime = SimpleNamespace(
        external_root=root,
        generation=7,
        runtime_lock_path=runtime_lock,
        runtime_digest="c" * 64,
        docker_path=docker,
        docker_digest=hashlib.sha256(docker.read_bytes()).hexdigest(),
        receipt_public_key_path=public,
        git_object_writer_source_path=writer,
        git_object_writer_source_digest=hashlib.sha256(writer.read_bytes()).hexdigest(),
        object_parser_entrypoint_path=parser,
        object_parser_entrypoint_digest=hashlib.sha256(parser.read_bytes()).hexdigest(),
        sha1dc_build_evidence_path=sha1dc_build_evidence,
        sha1dc_build_evidence_digest=hashlib.sha256(
            sha1dc_build_evidence.read_bytes()
        ).hexdigest(),
        sha1dc_oracle_path=sha1dc,
        sha1dc_oracle_digest=hashlib.sha256(sha1dc.read_bytes()).hexdigest(),
        sha1dc_runtime_source_path=sha1dc_runtime_source,
        sha1dc_runtime_source_digest=hashlib.sha256(
            sha1dc_runtime_source.read_bytes()
        ).hexdigest(),
    )
    inspection = SimpleNamespace(
        manifest_digest="e" * 64,
        config_digest="f" * 64,
        closure_digests={
            "toolchain": "0" * 64,
            "runtime": "1" * 64,
            "security_profile": "2" * 64,
        },
        closure_documents={"runtime": {"sha1dc_oracle": sha1dc_binding}},
    )
    monkeypatch.setattr(mod, "_resolveInstalledRuntime", lambda: runtime)
    monkeypatch.setattr(mod, "_inspectObjectParserArchive", lambda path: inspection)
    monkeypatch.setattr(mod, "_dockerServerIdentityDigest", lambda path, context: "d" * 64)
    monkeypatch.setattr(mod, "_attestHostSha1dc", lambda value: host_sha1dc)
    monkeypatch.setattr(
        mod,
        "_now",
        lambda: datetime(2026, 7, 16, 20, 0, tzinfo=timezone.utc),
    )
    return mod, root, payload, receipt_path


def test_signed_installed_qualification_cross_resolves_every_artifact(tmp_path, monkeypatch):
    mod, _, payload, _ = _write_qualification(tmp_path, monkeypatch)

    verified = mod.loadInstalledKernelArtifacts()

    assert verified.qualification_id == payload["qualification_id"]
    assert verified.authority_ceiling == "staging_only"
    assert verified.object_parser_manifest_digest == payload["object_parser"]["manifest_digest"]
    assert verified.writer_version_digest == payload["writer"]["version_digest"]
    assert verified.isInstalledAuthority()


def test_missing_tampered_expired_or_revoked_qualification_fails_closed(tmp_path, monkeypatch):
    mod, root, payload, receipt_path = _write_qualification(tmp_path, monkeypatch)
    pointer_path = root / "kernel-artifacts.current.json"

    pointer_path.unlink()
    with pytest.raises(mod.KernelArtifactsUnavailable, match="pointer"):
        mod.loadInstalledKernelArtifacts()

    _, root, payload, receipt_path = _write_qualification(tmp_path / "again", monkeypatch)
    receipt = json.loads(receipt_path.read_bytes())
    receipt["signature_base64url"] = "A" * 86
    receipt_path.write_bytes(_canonical(receipt))
    pointer_path = root / "kernel-artifacts.current.json"
    pointer = json.loads(pointer_path.read_bytes())
    pointer["qualification_sha256"] = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    pointer_path.write_bytes(_canonical(pointer))
    with pytest.raises(mod.KernelArtifactsUnavailable, match="signature"):
        mod.loadInstalledKernelArtifacts()

    _, _, _, _ = _write_qualification(tmp_path / "expired", monkeypatch)
    monkeypatch.setattr(
        mod,
        "_now",
        lambda: datetime(2026, 7, 18, 0, 0, tzinfo=timezone.utc),
    )
    with pytest.raises(mod.KernelArtifactsUnavailable, match="expired"):
        mod.loadInstalledKernelArtifacts()

    _, root, _, _ = _write_qualification(tmp_path / "revoked", monkeypatch)
    pointer_path = root / "kernel-artifacts.current.json"
    pointer = json.loads(pointer_path.read_bytes())
    pointer["status"] = "revoked"
    pointer["revocation_generation"] = 4
    pointer_path.write_bytes(_canonical(pointer))
    with pytest.raises(mod.KernelArtifactsUnavailable, match="staging-only"):
        mod.loadInstalledKernelArtifacts()


def test_artifact_or_independent_oci_identity_drift_fails_closed(tmp_path, monkeypatch):
    mod, root, _, _ = _write_qualification(tmp_path, monkeypatch)
    archive = root / "generations" / "00000007" / "images" / "object-parser.oci.tar"
    archive.write_bytes(b"changed-object-parser-archive")

    with pytest.raises(mod.KernelArtifactsUnavailable, match="archive digest differs"):
        mod.loadInstalledKernelArtifacts()

    mod, _, _, _ = _write_qualification(tmp_path / "oci", monkeypatch)
    monkeypatch.setattr(
        mod,
        "_inspectObjectParserArchive",
        lambda path: SimpleNamespace(
            manifest_digest="9" * 64,
            config_digest="f" * 64,
            closure_digests={
                "toolchain": "0" * 64,
                "runtime": "1" * 64,
                "security_profile": "2" * 64,
            },
            closure_documents={"runtime": {"sha1dc_oracle": {}}},
        ),
    )
    with pytest.raises(mod.KernelArtifactsUnavailable, match="OCI closure differs"):
        mod.loadInstalledKernelArtifacts()


def test_signed_sha1dc_substitution_cannot_escape_the_sealed_runtime(
    tmp_path, monkeypatch
):
    mod, root, payload, receipt_path = _write_qualification(tmp_path, monkeypatch)
    pointer_path = root / "kernel-artifacts.current.json"
    replacement = (
        root
        / "generations"
        / "00000007"
        / "controller"
        / "replacement-sha1dc.exe"
    )
    replacement.write_bytes(b"signed-but-not-sealed")
    host = payload["writer"]["host_sha1dc"]
    host["executable_path"] = str(replacement)
    host["executable_sha256"] = hashlib.sha256(replacement.read_bytes()).hexdigest()
    _resign(payload, receipt_path, pointer_path)

    with pytest.raises(mod.KernelArtifactsUnavailable, match="sealed runtime"):
        mod.loadInstalledKernelArtifacts()


def test_repository_sha1dc_attestor_must_match_the_sealed_runtime_source(
    tmp_path, monkeypatch
):
    mod, _, _, _ = _write_qualification(tmp_path, monkeypatch)
    drifted = tmp_path / "drifted-sha1dc.py"
    drifted.write_bytes(b"different attestor implementation")
    monkeypatch.setattr(mod._sha1dc_module, "__file__", str(drifted))

    with pytest.raises(mod.KernelArtifactsUnavailable, match="attestor source"):
        mod.loadInstalledKernelArtifacts()


def test_signed_unknown_fields_and_live_host_sha1dc_drift_fail_closed(tmp_path, monkeypatch):
    mod, root, payload, receipt_path = _write_qualification(tmp_path, monkeypatch)
    pointer_path = root / "kernel-artifacts.current.json"
    payload["unexpected"] = "signed-but-not-allowed"
    _resign(payload, receipt_path, pointer_path)

    with pytest.raises(mod.KernelArtifactsUnavailable, match="fields are not closed"):
        mod.loadInstalledKernelArtifacts()

    mod, _, _, _ = _write_qualification(tmp_path / "sha1dc", monkeypatch)
    monkeypatch.setattr(
        mod,
        "_attestHostSha1dc",
        lambda value: {**value, "executable_sha256": "0" * 64},
    )
    with pytest.raises(mod.KernelArtifactsUnavailable, match="evidence differs"):
        mod.loadInstalledKernelArtifacts()


def test_authority_is_live_and_revalidation_observes_pointer_loss(tmp_path, monkeypatch):
    mod, root, _, _ = _write_qualification(tmp_path, monkeypatch)
    verified = mod.loadInstalledKernelArtifacts()

    root.joinpath("kernel-artifacts.current.json").unlink()

    with pytest.raises(mod.KernelArtifactsUnavailable, match="pointer"):
        verified.revalidate()


def test_installed_object_parser_factory_has_no_injected_runner_seam(tmp_path, monkeypatch):
    mod, _, _, _ = _write_qualification(tmp_path, monkeypatch)
    verified = mod.loadInstalledKernelArtifacts()
    from platform_core.execution import object_parser as parser_mod

    monkeypatch.setattr(parser_mod, "loadInstalledKernelArtifacts", lambda: verified)
    parser = parser_mod.ObjectParser.fromInstalledArtifacts(
        controller_root=tmp_path / "parser-state",
    )

    assert parser.hasInstalledArtifactAuthority()
    assert parser.image.manifest_digest == verified.object_parser_manifest_digest
    assert parser.runtime_entrypoint == verified.object_parser_entrypoint

    with pytest.raises(parser_mod.ObjectParserRefused, match="injected process runner"):
        parser_mod.ObjectParser(
            controller_root=tmp_path / "other-state",
            image=parser.image,
            runtime_entrypoint=verified.object_parser_entrypoint,
            process_runner=lambda invocation: None,
            docker_executable=str(verified.docker_executable),
            docker_context=verified.docker_context,
            artifact_qualification=verified,
        )


def test_installed_clone_kernel_factory_is_the_only_production_ready_path(
    tmp_path,
    monkeypatch,
):
    mod, _, _, _ = _write_qualification(tmp_path, monkeypatch)
    verified = mod.loadInstalledKernelArtifacts()
    from platform_core.execution.backends import clone as clone_mod
    from platform_core.runtime import candidate as candidate_mod
    from platform_core.runtime.attempt_journal import AttemptJournal

    monkeypatch.setattr(clone_mod, "loadInstalledKernelArtifacts", lambda: verified)
    process_capability = object()
    issuer = candidate_mod._buildDiagnosticLandingAuthorityIssuer(
        run_id="run-installed-test",
        controller_generation=verified.generation,
        watchdog_generation=1,
        process_capability=process_capability,
        child_pid=os.getpid(),
    )
    monkeypatch.setattr(
        candidate_mod.LandingAuthorityIssuer,
        "isInstalledAuthority",
        lambda self: self is issuer,
    )
    admission = issuer.issueRunAdmission(
        process_capability=process_capability,
        deadline=datetime.now(timezone.utc) + timedelta(minutes=1),
    )
    with pytest.raises(Exception, match="credential.*verifier|sealed broker"):
        clone_mod.buildInstalledTransactionalCloneKernel(
            parser_state_root=tmp_path / "parser-state-unsealed",
            snapshot_root=tmp_path / "snapshots-unsealed",
            verification_root=tmp_path / "verification-unsealed",
            expected_manifest_provider=lambda *_: None,
            quiescence_provider=lambda *_: None,
            commit_metadata_provider=lambda *_: None,
            coordinator_factory=lambda *_: None,
            landing_authority_issuer=issuer,
            run_admission=admission,
        )

    from platform_core.execution.credential_broker import CredentialBroker

    credential_capability = object()
    credential_broker = CredentialBroker(
        metadata_root=tmp_path / "credential-store",
        secret_provider=lambda _provider: pytest.fail(
            "snapshot composition must not derive a credential"
        ),
        process_capability=credential_capability,
    )
    credential_verifier = credential_broker.freshAbsenceVerifier(
        process_capability=credential_capability
    )
    kernel = clone_mod.buildInstalledTransactionalCloneKernel(
        parser_state_root=tmp_path / "parser-state",
        snapshot_root=tmp_path / "snapshots",
        verification_root=tmp_path / "verification",
        expected_manifest_provider=lambda *_: None,
        quiescence_provider=lambda *_: None,
        commit_metadata_provider=lambda *_: None,
        coordinator_factory=lambda *_: None,
        landing_authority_issuer=issuer,
        run_admission=admission,
        credential_absence_verifier=credential_verifier,
    )

    assert kernel.productionReady()
    assert kernel.parser.hasInstalledArtifactAuthority()

    environment = clone_mod.buildInstalledCloneEnvironment(
        clone_factory=lambda **_: None,
        attempt_journal=AttemptJournal(tmp_path / "attempt-journal"),
        controller_scope_id="controller-installed-test",
        process_security_profile_digest="a" * 64,
        parser_state_root=tmp_path / "parser-state-2",
        snapshot_root=tmp_path / "snapshots-2",
        verification_root=tmp_path / "verification-2",
        expected_manifest_provider=lambda *_: None,
        quiescence_provider=lambda *_: None,
        commit_metadata_provider=lambda *_: None,
        coordinator_factory=lambda *_: None,
        landing_authority_issuer=issuer,
        run_admission=admission,
        credential_absence_verifier=credential_verifier,
    )
    assert environment.healthCheck()
    assert environment.clone_factory is not None
    assert environment.kernel.productionReady()
    from platform_core.execution import router

    registry = router.buildInstalledExecutionBackendRegistry(
        clone_environment=environment,
        landing_authority_issuer=issuer,
        run_admission=admission,
    )
    assert registry.installed
    assert registry.resolve("clone") is environment


def test_installed_clone_prepare_refuses_revoked_run_admission(
    tmp_path,
    monkeypatch,
):
    """Snapshot preparation must reprove external run admission, not trust __init__."""

    mod, _, _, _ = _write_qualification(tmp_path, monkeypatch)
    verified = mod.loadInstalledKernelArtifacts()
    from platform_core.execution.backends import clone as clone_mod
    from platform_core.execution.credential_broker import CredentialBroker
    from platform_core.runtime import candidate as candidate_mod

    monkeypatch.setattr(clone_mod, "loadInstalledKernelArtifacts", lambda: verified)
    process_capability = object()
    issuer = candidate_mod._buildDiagnosticLandingAuthorityIssuer(
        run_id="run-revoked-admission",
        controller_generation=verified.generation,
        watchdog_generation=1,
        process_capability=process_capability,
        child_pid=os.getpid(),
    )
    monkeypatch.setattr(
        candidate_mod.LandingAuthorityIssuer,
        "isInstalledAuthority",
        lambda self: self is issuer,
    )
    admission = issuer.issueRunAdmission(
        process_capability=process_capability,
        deadline=datetime.now(timezone.utc) + timedelta(minutes=1),
    )
    credential_capability = object()
    credential_verifier = CredentialBroker(
        metadata_root=tmp_path / "credential-store",
        secret_provider=lambda _provider: pytest.fail(
            "snapshot composition must not derive a credential"
        ),
        process_capability=credential_capability,
    ).freshAbsenceVerifier(process_capability=credential_capability)
    kernel = clone_mod.buildInstalledTransactionalCloneKernel(
        parser_state_root=tmp_path / "parser-state",
        snapshot_root=tmp_path / "snapshots",
        verification_root=tmp_path / "verification",
        expected_manifest_provider=lambda *_: pytest.fail(
            "revoked run admission must refuse before manifest composition"
        ),
        quiescence_provider=lambda *_: pytest.fail(
            "revoked run admission must refuse before quiescence composition"
        ),
        commit_metadata_provider=lambda *_: None,
        coordinator_factory=lambda *_: pytest.fail(
            "revoked run admission must refuse before coordinator construction"
        ),
        landing_authority_issuer=issuer,
        run_admission=admission,
        credential_absence_verifier=credential_verifier,
    )
    assert kernel.productionReady()

    issuer.revokeRunAdmission(admission)

    assert not kernel.productionReady()
    with pytest.raises(Exception, match="run admission|not live"):
        kernel.prepare(
            SimpleNamespace(transaction_id="tx-revoked"),
            task_state=None,
            subtask=None,
        )
