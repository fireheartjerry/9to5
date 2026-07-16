"""RED executable contracts for offline digest-closed activation images."""

from __future__ import annotations

import hashlib
import importlib
import io
import json
import os
import subprocess
import tarfile

import pytest


ROLES = {
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


def _mod():
    return importlib.import_module("bootstrap.galaxy_launcher.runtime_manifest")


def _record(mod, *, role, archive, archive_sha256, **digests):
    fallback = archive_sha256
    return mod.ActivationImageRecord(
        role=role,
        physical_image=digests.get("physical_image", role),
        archive=archive,
        archive_sha256=archive_sha256,
        manifest_digest=digests.get("manifest_digest", fallback),
        config_digest=digests.get("config_digest", fallback),
        layer_digests=digests.get("layer_digests", (fallback,)),
        base_digest=digests.get("base_digest", fallback),
        toolchain_digest=digests.get("toolchain_digest", fallback),
        package_manifest_digest=digests.get("package_manifest_digest", fallback),
        sbom_digest=digests.get("sbom_digest", fallback),
        runtime_digest=digests.get("runtime_digest", fallback),
        security_profile_digest=digests.get("security_profile_digest", fallback),
        base_image_digest=digests.get("base_image_digest", "a" * 64),
        dockerfile_sha256=digests.get("dockerfile_sha256", "b" * 64),
    )


def test_offline_image_closure_opens_hashes_and_validates_every_declared_leaf(tmp_path):
    mod = _mod()
    records = []
    for role in ROLES:
        layout, digests = _real_oci_layout(tmp_path, role)
        path = _archive_layout(layout, tmp_path / f"{role}.oci.tar")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        records.append(
            _record(
                mod,
                role=role,
                archive=path,
                archive_sha256=digest,
                manifest_digest=digests["manifest"],
                config_digest=digests["config"],
                layer_digests=(digests["layer"],),
                base_digest=digests["base"],
                toolchain_digest=digests["toolchain"],
                package_manifest_digest=digests["package_manifest"],
                sbom_digest=digests["sbom"],
                runtime_digest=digests["runtime"],
                security_profile_digest=digests["security_profile"],
            )
        )
    report = mod.verify_activation_images(records, network_allowed=False)
    assert report.roles == ROLES and report.every_byte_verified


def test_missing_mismatch_symlink_and_engine_fallback_are_typed_hard_stops(tmp_path):
    mod = _mod()
    missing = _record(mod, role="verifier", archive=tmp_path / "missing.oci", archive_sha256="0" * 64)
    for record in (missing, dataclass_replace(missing, archive_sha256="f" * 64)):
        with pytest.raises(mod.OfflineActivationArtifactsUnavailable):
            mod.verify_activation_images(
                [record], network_allowed=False, allow_engine_build=False, allow_pull=False
            )
    assert not hasattr(mod, "optimistic_mock_image")


def dataclass_replace(value, **changes):
    import dataclasses

    return dataclasses.replace(value, **changes)


def _real_oci_layout(tmp_path, name="oci"):
    layout = tmp_path / name
    blobs = layout / "blobs" / "sha256"
    blobs.mkdir(parents=True)
    role = name if name in ROLES else "verifier"
    base_diff_id = "sha256:" + "1" * 64
    config_obj = {
        "architecture": "amd64",
        "os": "linux",
        "config": {
            "User": "65532:65532",
            "WorkingDir": "/empty",
            "Entrypoint": [
                "/usr/bin/env",
                "-i",
                "/usr/local/bin/python3",
                "-I",
                "-S",
                "/opt/galaxy/activation_image_entrypoint.py",
            ],
            "Cmd": ["image-canary"],
            "Labels": {
                "org.galaxy.image.authority": "inactive",
                "org.galaxy.image.roles": role,
            },
        },
        "rootfs": {
            "type": "layers",
            "diff_ids": [base_diff_id, "sha256:" + "2" * 64],
        },
    }
    config = json.dumps(config_obj, sort_keys=True, separators=(",", ":")).encode()
    layer = b"layer-bytes"
    config_d = hashlib.sha256(config).hexdigest()
    layer_d = hashlib.sha256(layer).hexdigest()
    (blobs / config_d).write_bytes(config)
    (blobs / layer_d).write_bytes(layer)
    base_image_digest = "a" * 64
    dockerfile_sha256 = "b" * 64
    license_digest = "c" * 64
    documents = {
        "base": {
            "schema": "galaxy.activation-base/v1",
            "kind": "base",
            "name": "test-base",
            "reference": f"python@sha256:{base_image_digest}",
            "manifest_digest": base_image_digest,
            "image_id": f"sha256:{base_image_digest}",
            "architecture": "amd64",
            "os": "linux",
            "rootfs_diff_ids": [base_diff_id],
        },
        "toolchain": {
            "schema": "galaxy.activation-toolchain/v1",
            "kind": "toolchain",
            "base_manifest_digest": base_image_digest,
            "runtime_tools": {"dpkg": "test", "gcc": None, "git": None},
            "python_runtime": {"python": "3.12.13"},
            "offline_builder": {"default_route_absent": True, "routes": []},
            "dockerfile_sha256": dockerfile_sha256,
            "build_flags": [
                "--network=none",
                "--pull=false",
                "--provenance=false",
                "--sbom=false",
                "--platform=linux/amd64",
                "SOURCE_DATE_EPOCH=0",
            ],
        },
        "package_manifest": {
            "schema": "galaxy.activation-package-manifest/v1",
            "kind": "package_manifest",
            "base_manifest_digest": base_image_digest,
            "package_count": 1,
            "all_license_evidence_present": True,
            "packages": [
                {
                    "name": "python",
                    "version": "3.12.13",
                    "architecture": "amd64",
                    "license_evidence": {
                        "path": "/usr/share/doc/python/copyright",
                        "sha256": license_digest,
                        "size": 1,
                    },
                }
            ],
        },
        "sbom": {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "version": 1,
            "serialNumber": "urn:uuid:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "kind": "sbom",
            "metadata": {"component": {"type": "container", "name": role}},
            "components": [{"type": "library", "name": "python", "version": "3.12.13", "properties": []}],
        },
        "runtime": {
            "schema": "galaxy.activation-image-runtime/v1",
            "kind": "runtime",
            "physical_image": role,
            "supported_roles": [role],
            "config_digest": config_d,
            "layer_digests": [layer_d],
            "entrypoint_path": "/opt/galaxy/activation_image_entrypoint.py",
            "entrypoint_sha256": "d" * 64,
            "interpreter": "/usr/local/bin/python3",
            "interpreter_flags": ["-I", "-S"],
            "base_runtime": {"python": "3.12.13"},
        },
        "security_profile": {
            "schema": "galaxy.activation-security-profile/v1",
            "kind": "security_profile",
            "physical_image": role,
            "supported_roles": [role],
            "config_digest": config_d,
            "authority": "inactive",
            "build_network": "none",
            "canary_network": "none",
            "maximum_runtime_network_by_role": {role: "none"},
            "identity": {"uid": 65532, "gid": 65532, "root_forbidden": True},
            "process": {"cap_drop": ["ALL"], "no_new_privileges": True, "restart": "no", "pids_limit": 64},
            "filesystem": {
                "rootfs": "read_only",
                "cwd": "/empty",
                "cwd_must_be_empty": True,
                "runtime_projection": "/galaxy-runtime:ro",
                "control_projection": "/galaxy-control:ro",
            },
            "resources": {"memory_bytes": 134217728, "nano_cpus": 500000000},
            "environment": {"entrypoint_clears_ambient": True, "inherited_keys": []},
            "manifest_binding": "exact_sha256_required",
        },
    }
    closure = {}
    for closure_name, document in documents.items():
        raw = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(raw).hexdigest()
        (blobs / digest).write_bytes(raw)
        closure[closure_name] = digest
    manifest_obj = {
        "schemaVersion": 2,
        "config": {"digest": f"sha256:{config_d}", "size": len(config)},
        "layers": [{"digest": f"sha256:{layer_d}", "size": len(layer)}],
        "annotations": {f"org.galaxy.{name}.digest": f"sha256:{digest}" for name, digest in closure.items()},
    }
    manifest = json.dumps(manifest_obj, separators=(",", ":")).encode()
    manifest_d = hashlib.sha256(manifest).hexdigest()
    (blobs / manifest_d).write_bytes(manifest)
    (layout / "oci-layout").write_text('{"imageLayoutVersion":"1.0.0"}', encoding="utf-8")
    (layout / "index.json").write_text(
        json.dumps(
            {"schemaVersion": 2, "manifests": [{"digest": f"sha256:{manifest_d}", "size": len(manifest)}]}
        ),
        encoding="utf-8",
    )
    return layout, {
        "manifest": manifest_d,
        "config": config_d,
        "layer": layer_d,
        "base_image": base_image_digest,
        "dockerfile": dockerfile_sha256,
        **closure,
    }


def _archive_layout(layout, archive):
    with tarfile.open(archive, "w", format=tarfile.PAX_FORMAT) as bundle:
        for path in sorted(layout.rglob("*"), key=lambda item: item.as_posix()):
            bundle.add(path, arcname=path.relative_to(layout).as_posix(), recursive=False)
    return archive


def test_real_minimal_oci_layout_hashes_distinct_referenced_blobs(tmp_path):
    mod = _mod()
    layout, expected = _real_oci_layout(tmp_path)
    parsed = mod.inspect_oci_layout(layout)
    assert parsed.manifest_digest == expected["manifest"]
    assert parsed.config_digest == expected["config"]
    assert parsed.layer_digests == (expected["layer"],)
    assert parsed.closure_digests == {
        k: expected[k]
        for k in ("base", "toolchain", "package_manifest", "sbom", "runtime", "security_profile")
    }
    assert len(set(expected.values())) == len(expected)


def _replace_closure_document(layout, expected, name, document):
    blobs = layout / "blobs" / "sha256"
    raw = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(raw).hexdigest()
    (blobs / digest).write_bytes(raw)
    manifest_path = blobs / expected["manifest"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["annotations"][f"org.galaxy.{name}.digest"] = f"sha256:{digest}"
    new_manifest = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    new_manifest_digest = hashlib.sha256(new_manifest).hexdigest()
    (blobs / new_manifest_digest).write_bytes(new_manifest)
    manifest_path.unlink()
    (blobs / expected[name]).unlink()
    index_path = layout / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["manifests"][0]["digest"] = f"sha256:{new_manifest_digest}"
    index["manifests"][0]["size"] = len(new_manifest)
    index_path.write_text(json.dumps(index, sort_keys=True, separators=(",", ":")), encoding="utf-8")


def test_semantically_incomplete_but_self_consistent_closure_is_rejected(tmp_path):
    mod = _mod()
    layout, expected = _real_oci_layout(tmp_path)
    _replace_closure_document(layout, expected, "base", {"kind": "base"})
    with pytest.raises(mod.OfflineActivationArtifactsUnavailable, match="base"):
        mod.inspect_oci_layout(layout)


@pytest.mark.parametrize(
    "leaf",
    [
        "manifest",
        "config",
        "layer",
        "base",
        "toolchain",
        "package_manifest",
        "sbom",
        "runtime",
        "security_profile",
    ],
)
def test_each_oci_referenced_leaf_mismatch_is_independently_rejected(tmp_path, leaf):
    mod = _mod()
    layout, expected = _real_oci_layout(tmp_path)
    blob = layout / "blobs" / "sha256" / expected[leaf]
    blob.write_bytes(blob.read_bytes() + b"tamper")
    with pytest.raises(mod.OfflineActivationArtifactsUnavailable, match=leaf):
        mod.inspect_oci_layout(layout)


def test_archive_verifier_compares_every_internal_digest_to_the_record(tmp_path):
    mod = _mod()
    records = []
    for role in ROLES:
        layout, digests = _real_oci_layout(tmp_path, role)
        archive = _archive_layout(layout, tmp_path / f"{role}.tar")
        archive_digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        records.append(
            _record(
                mod,
                role=role,
                archive=archive,
                archive_sha256=archive_digest,
                manifest_digest=digests["manifest"],
                config_digest=digests["config"],
                layer_digests=(digests["layer"],),
                base_digest=digests["base"],
                toolchain_digest=digests["toolchain"],
                package_manifest_digest=digests["package_manifest"],
                sbom_digest=digests["sbom"],
                runtime_digest=digests["runtime"],
                security_profile_digest=digests["security_profile"],
            )
        )

    records[0] = dataclass_replace(records[0], config_digest="f" * 64)
    with pytest.raises(mod.OfflineActivationArtifactsUnavailable, match="config"):
        mod.verify_activation_images(records)


def test_archive_verifier_rejects_incomplete_or_substituted_nine_role_set(tmp_path):
    mod = _mod()
    archive = tmp_path / "not-reached.tar"
    archive.write_bytes(b"x")
    digest = hashlib.sha256(b"x").hexdigest()
    record = _record(mod, role="verifier", archive=archive, archive_sha256=digest)
    with pytest.raises(mod.OfflineActivationArtifactsUnavailable, match="nine-role"):
        mod.verify_activation_images([record])
    substituted = [dataclass_replace(record, role=role) for role in sorted(ROLES)]
    substituted[-1] = dataclass_replace(substituted[-1], role="unexpected_role")
    with pytest.raises(mod.OfflineActivationArtifactsUnavailable, match="nine-role"):
        mod.verify_activation_images(substituted)


@pytest.mark.parametrize("member", ["../escape", "/absolute", "C:/drive", "link"])
def test_archive_verifier_refuses_unsafe_tar_members_without_extracting(tmp_path, member):
    mod = _mod()
    archive = tmp_path / "unsafe.tar"
    with tarfile.open(archive, "w") as bundle:
        info = tarfile.TarInfo(member)
        if member == "link":
            info.type = tarfile.SYMTYPE
            info.linkname = "../outside"
            bundle.addfile(info)
        else:
            raw = b"escape"
            info.size = len(raw)
            bundle.addfile(info, io.BytesIO(raw))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    records = [_record(mod, role=role, archive=archive, archive_sha256=digest) for role in sorted(ROLES)]
    with pytest.raises(mod.OfflineActivationArtifactsUnavailable, match="archive"):
        mod.verify_activation_images(records)
    assert not (tmp_path / "escape").exists()


def test_archive_mismatch_symlink_never_calls_builder_or_puller(tmp_path):
    mod = _mod()
    calls = []
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    real = real_dir / "archive.oci"
    real.write_bytes(b"oci")
    link = tmp_path / "junction"
    cp = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(real_dir)],
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert cp.returncode == 0, f"junction creation failed\nstdout={cp.stdout}\nstderr={cp.stderr}"
    try:
        for path, digest in ((real, "0" * 64), (link / real.name, hashlib.sha256(b"oci").hexdigest())):
            with pytest.raises(mod.OfflineActivationArtifactsUnavailable):
                mod.verify_activation_images(
                    [_record(mod, role="verifier", archive=path, archive_sha256=digest)],
                    builder=lambda: calls.append("build"),
                    puller=lambda: calls.append("pull"),
                )
    finally:
        if link.exists():
            os.rmdir(link)
    assert calls == []
