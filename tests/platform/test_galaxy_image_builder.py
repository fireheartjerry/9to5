"""Contracts for deterministic, networkless GALAXY activation-image builds."""

from __future__ import annotations

import hashlib
import importlib
import json
import os

import pytest


def _mod():
    return importlib.import_module("tools.build_galaxy_launcher")


def _minimal_layout(root):
    blobs = root / "blobs" / "sha256"
    blobs.mkdir(parents=True)
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
            "Labels": {"org.galaxy.image.authority": "inactive", "org.galaxy.image.roles": "verifier"},
        },
        "rootfs": {"type": "layers", "diff_ids": [base_diff_id, "sha256:" + "2" * 64]},
    }
    config = json.dumps(config_obj, sort_keys=True, separators=(",", ":")).encode()
    layer = b"layer"
    config_digest = hashlib.sha256(config).hexdigest()
    layer_digest = hashlib.sha256(layer).hexdigest()
    (blobs / config_digest).write_bytes(config)
    (blobs / layer_digest).write_bytes(layer)
    manifest_obj = {
        "schemaVersion": 2,
        "config": {"digest": f"sha256:{config_digest}", "size": len(config)},
        "layers": [{"digest": f"sha256:{layer_digest}", "size": len(layer)}],
    }
    manifest = json.dumps(manifest_obj, sort_keys=True, separators=(",", ":")).encode()
    manifest_digest = hashlib.sha256(manifest).hexdigest()
    (blobs / manifest_digest).write_bytes(manifest)
    (root / "oci-layout").write_text('{"imageLayoutVersion":"1.0.0"}', encoding="utf-8")
    (root / "index.json").write_text(
        json.dumps(
            {
                "schemaVersion": 2,
                "manifests": [{"digest": f"sha256:{manifest_digest}", "size": len(manifest)}],
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    return config_digest, layer_digest, base_diff_id


def test_sealer_adds_six_distinct_referenced_closure_blobs_and_is_idempotent(tmp_path):
    mod = _mod()
    layout = tmp_path / "oci"
    config_digest, layer_digest, base_diff_id = _minimal_layout(layout)
    spec = mod.ImageSpec("verifier", ("verifier",), "test.Dockerfile", mod.SLIM_BASE)
    audit = mod.DockerfileAudit(
        path=tmp_path / "test.Dockerfile",
        sha256="b" * 64,
        base_digest=mod.SLIM_BASE.digest,
        supported_roles=("verifier",),
    )
    base = {
        "name": mod.SLIM_BASE.name,
        "reference": mod.SLIM_BASE.reference,
        "manifest_digest": mod.SLIM_BASE.digest,
        "image_id": f"sha256:{mod.SLIM_BASE.digest}",
        "architecture": "amd64",
        "os": "linux",
        "rootfs_diff_ids": [base_diff_id],
        "inventory": {
            "tools": {"dpkg": "test", "gcc": None, "git": None},
            "runtime": {"python": "3.12.13"},
            "packages": [
                {
                    "name": "python",
                    "version": "3.12.13",
                    "architecture": "amd64",
                    "license_evidence": {
                        "path": "/usr/share/doc/python/copyright",
                        "sha256": "c" * 64,
                        "size": 1,
                    },
                }
            ],
        },
    }
    boundary = {"default_route_absent": True, "routes": []}
    documents = mod._closure_documents(
        spec=spec,
        audit=audit,
        base=base,
        boundary=boundary,
        config_digest=config_digest,
        layer_digests=(layer_digest,),
    )
    first = mod.seal_oci_layout(layout, documents)
    second = mod.seal_oci_layout(layout, documents)
    assert first == second
    assert first.config_digest == config_digest
    assert first.layer_digests == (layer_digest,)
    assert len(set(first.closure_digests.values())) == 6
    for digest in first.closure_digests.values():
        assert (layout / "blobs" / "sha256" / digest).is_file()


def test_deterministic_archive_has_stable_bytes_and_refuses_links(tmp_path):
    mod = _mod()
    layout = tmp_path / "oci"
    _minimal_layout(layout)
    first = tmp_path / "one.tar"
    second = tmp_path / "two.tar"
    mod.write_deterministic_oci_archive(layout, first)
    mod.write_deterministic_oci_archive(layout, second)
    assert first.read_bytes() == second.read_bytes()
    os.link(layout / "index.json", layout / "hardlink")
    with pytest.raises(mod.ImageBuildRefused, match="hard-linked"):
        mod.write_deterministic_oci_archive(layout, tmp_path / "refused.tar")


def test_dockerfile_audit_requires_exact_pinned_base_and_closed_build(tmp_path):
    mod = _mod()
    digest = "a" * 64
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(
        "\n".join(
            [
                f"FROM python@sha256:{digest}",
                "COPY bootstrap/galaxy_launcher/activation_image_entrypoint.py /opt/galaxy/activation_image_entrypoint.py",
                "USER 65532:65532",
                'ENTRYPOINT ["/usr/bin/env","-i","/usr/local/bin/python3","-I","-S","/opt/galaxy/activation_image_entrypoint.py"]',
            ]
        ),
        encoding="utf-8",
    )
    audited = mod.audit_dockerfile(dockerfile, expected_base_digest=digest)
    assert audited.base_digest == digest
    for poison in (
        "FROM python:3.12",
        f"FROM python@sha256:{digest}\nRUN apt-get update",
        f"FROM python@sha256:{digest}\nADD https://example.invalid/x /x",
    ):
        dockerfile.write_text(poison, encoding="utf-8")
        with pytest.raises(mod.ImageBuildRefused):
            mod.audit_dockerfile(dockerfile, expected_base_digest=digest)


def test_lock_loader_requires_exact_nine_roles_and_canonical_schema(tmp_path):
    mod = _mod()
    lock = tmp_path / "activation_images.lock.json"
    lock.write_text('{"schema":"wrong","images":[]}', encoding="utf-8")
    with pytest.raises(mod.ImageBuildRefused):
        mod.load_activation_image_lock(lock, archive_root=tmp_path)
