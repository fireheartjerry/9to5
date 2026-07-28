"""Contracts for deterministic, networkless GALAXY activation-image builds."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest


def _mod():
    return importlib.import_module("tools.build_galaxy_launcher")


def _builder_boundary():
    return {
        "schema": "galaxy.offline-docker-boundary/v1",
        "context": "default",
        "daemon_endpoint": "npipe:////./pipe/dockerDesktopLinuxEngine",
        "docker_cli": {
            "path": r"C:\Program Files\Docker\Docker\resources\bin\docker.exe",
            "sha256": "8f6dea04cf35515b6d6de5bfc3f5ba54c827fc4532996922eccc29d362585620",
            "size": 43267504,
        },
        "buildx_plugin": {
            "path": r"C:\Program Files\Docker\Docker\resources\cli-plugins\docker-buildx.exe",
            "sha256": "b0074bdac78c8b7f9179863c2d6e4cdfbbade54829ad4d569cc81e7409426fed",
            "size": 67032496,
        },
        "wsl_host": {
            "path": r"C:\Windows\System32\wsl.exe",
            "sha256": "e27cbfcbd61c44796e2cfdd031663245bda8d6e4a43c1451b1fc505333908126",
            "size": 278528,
        },
        "docker_server": {"Version": "29.5.2"},
        "buildx": "github.com/docker/buildx v0.34.0-desktop.1 exact",
        "ambient_environment": [],
        "routes": [],
        "default_route_absent": True,
    }


def test_host_runner_pins_tools_and_closes_docker_configuration(tmp_path, monkeypatch):
    mod = _mod()
    docker = tmp_path / "docker.exe"
    buildx = tmp_path / "docker-buildx.exe"
    wsl = tmp_path / "wsl.exe"
    for path in (docker, buildx, wsl):
        path.write_bytes(path.name.encode("ascii"))
    ambient = tmp_path / "ambient-docker-config"
    ambient.mkdir()
    (ambient / "config.json").write_text('{"credsStore":"poison"}', encoding="utf-8")
    monkeypatch.setenv("DOCKER_CONFIG", str(ambient))
    monkeypatch.setenv("HTTPS_PROXY", "http://poison.invalid")
    monkeypatch.setattr(
        mod,
        "resolvePinnedDockerTools",
        lambda: SimpleNamespace(executable=docker, buildx_plugin=buildx),
    )
    monkeypatch.setattr(mod, "_resolvePinnedWsl", lambda: wsl)
    observed: list[tuple[list[str], dict[str, str]]] = []

    def fake_run(command, **kwargs):
        environment = dict(kwargs["env"])
        observed.append((list(command), environment))
        if Path(command[0]) == docker:
            config_root = Path(environment["DOCKER_CONFIG"])
            assert config_root.is_dir()
            assert not any(config_root.iterdir())
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    mod._run(["docker", "buildx", "version"])
    mod._run(["wsl.exe", "--status"])

    buildx_command, docker_environment = observed[0]
    wsl_command, wsl_environment = observed[1]
    assert Path(buildx_command[0]) == buildx
    assert Path(wsl_command[0]) == wsl
    assert docker_environment["DOCKER_CONFIG"] != str(ambient)
    assert "HTTPS_PROXY" not in docker_environment
    assert "PATH" not in docker_environment
    assert set(wsl_environment) <= {"SystemRoot", "WINDIR"}
    assert not Path(docker_environment["DOCKER_CONFIG"]).exists()


def test_network_boundary_binds_exact_host_tool_evidence(tmp_path, monkeypatch):
    mod = _mod()
    docker = tmp_path / "docker.exe"
    buildx = tmp_path / "docker-buildx.exe"
    wsl = tmp_path / "wsl.exe"
    docker.write_bytes(b"docker")
    buildx.write_bytes(b"buildx")
    wsl.write_bytes(b"wsl")
    monkeypatch.setattr(
        mod,
        "resolvePinnedDockerTools",
        lambda: SimpleNamespace(executable=docker, buildx_plugin=buildx),
    )
    monkeypatch.setattr(mod, "_resolvePinnedWsl", lambda: wsl)

    def fake_run(command, **_kwargs):
        if command[:3] == ["wsl.exe", "-d", "docker-desktop"]:
            output = "172.26.176.0/20 dev eth0 scope link\n"
        elif command == ["docker", "context", "show"]:
            output = "default\n"
        elif command[:2] == ["docker", "version"]:
            output = '{"Version":"29.5.2"}\n'
        elif command[:3] == ["docker", "buildx", "version"]:
            output = "github.com/docker/buildx v0.34.0-desktop.1 exact\n"
        else:
            raise AssertionError(command)
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    monkeypatch.setattr(mod, "_run", fake_run)

    boundary = mod.require_docker_desktop_network_closed()

    assert boundary["context"] == "default"
    assert boundary["daemon_endpoint"] == "npipe:////./pipe/dockerDesktopLinuxEngine"
    assert boundary["ambient_environment"] == []
    assert boundary["docker_cli"] == {
        "path": str(docker.resolve()),
        "sha256": hashlib.sha256(b"docker").hexdigest(),
        "size": len(b"docker"),
    }
    assert boundary["buildx_plugin"]["sha256"] == hashlib.sha256(b"buildx").hexdigest()
    assert boundary["wsl_host"]["sha256"] == hashlib.sha256(b"wsl").hexdigest()


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
    boundary = _builder_boundary()
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


def test_dockerfile_audit_admits_sha1dc_only_as_an_exact_declared_copy(tmp_path):
    mod = _mod()
    digest = "a" * 64
    entrypoint_copy = (
        "bootstrap/galaxy_launcher/activation_image_entrypoint.py "
        "/opt/galaxy/activation_image_entrypoint.py"
    )
    oracle_copy = (
        "--chmod=0555 containers/galaxy/generated/galaxy-sha1dc "
        "/opt/galaxy/galaxy-sha1dc"
    )
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(
        "\n".join(
            [
                f"FROM python@sha256:{digest}",
                f"COPY {entrypoint_copy}",
                f"COPY {oracle_copy}",
                "USER 65532:65532",
                'ENTRYPOINT ["/usr/bin/env","-i","/usr/local/bin/python3","-I","-S","/opt/galaxy/activation_image_entrypoint.py"]',
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(mod.ImageBuildRefused, match="COPY closure"):
        mod.audit_dockerfile(dockerfile, expected_base_digest=digest)
    audited = mod.audit_dockerfile(
        dockerfile,
        expected_base_digest=digest,
        expected_copy_closure=(entrypoint_copy, oracle_copy),
    )
    assert audited.base_digest == digest

    for substituted in (
        oracle_copy.replace("0555", "0755"),
        oracle_copy.replace("generated/galaxy-sha1dc", "sha1dc_object_oracle.c"),
        oracle_copy.replace("/opt/galaxy/galaxy-sha1dc", "/usr/local/bin/git"),
    ):
        dockerfile.write_text(
            dockerfile.read_text(encoding="utf-8").replace(oracle_copy, substituted),
            encoding="utf-8",
        )
        with pytest.raises(mod.ImageBuildRefused, match="COPY closure"):
            mod.audit_dockerfile(
                dockerfile,
                expected_base_digest=digest,
                expected_copy_closure=(entrypoint_copy, oracle_copy),
            )
        dockerfile.write_text(
            dockerfile.read_text(encoding="utf-8").replace(substituted, oracle_copy),
            encoding="utf-8",
        )


def test_object_parser_context_contains_only_reviewed_sources_and_exact_oracle(tmp_path):
    mod = _mod()
    executable = tmp_path / "galaxy-sha1dc"
    executable.write_bytes(b"exact-oracle")
    root = mod._REPOSITORY_ROOT
    evidence = mod.Sha1dcBuildEvidence(
        executable_path=str(executable),
        executable_sha256=hashlib.sha256(b"exact-oracle").hexdigest(),
        executable_size=len(b"exact-oracle"),
        source_lock_sha256=hashlib.sha256(
            (root / "bootstrap/galaxy_launcher/sha1dc_source.lock.json").read_bytes()
        ).hexdigest(),
        source_archive_sha256="2" * 64,
        source_passport_sha256=hashlib.sha256(
            (root / "bootstrap/galaxy_launcher/sha1dc_source_passport.json").read_bytes()
        ).hexdigest(),
        wrapper_sha256=hashlib.sha256(
            (root / "containers/galaxy/sha1dc_object_oracle.c").read_bytes()
        ).hexdigest(),
        builder_base_digest=mod.FULL_BASE.digest,
        runtime_base_digest=mod.SLIM_BASE.digest,
        reproducibility_runs=2,
        self_test="collision-detected",
        normal_object_corpus_count=4,
        network_allowed=False,
    )
    spec = next(item for item in mod.IMAGE_SPECS if item.name == "object-parser")
    context = tmp_path / "context"

    mod._materialize_build_context(spec, context, sha1dc_evidence=evidence)

    files = {
        path.relative_to(context).as_posix(): path.read_bytes()
        for path in context.rglob("*")
        if path.is_file()
    }
    assert set(files) == {
        "bootstrap/galaxy_launcher/activation_image_entrypoint.py",
        "containers/galaxy/object_parser.Dockerfile",
        "containers/galaxy/generated/galaxy-sha1dc",
    }
    assert files["containers/galaxy/generated/galaxy-sha1dc"] == b"exact-oracle"
    audit = mod.audit_dockerfile(
        root / spec.dockerfile,
        expected_base_digest=spec.base.digest,
        expected_roles=spec.roles,
        expected_copy_closure=mod._expected_copy_closure(spec),
    )
    mod._validate_build_context(
        spec,
        context,
        audit=audit,
        sha1dc_evidence=evidence,
    )
    (context / "containers/galaxy/generated/galaxy-sha1dc").write_bytes(b"context-tamper")
    with pytest.raises(mod.ImageBuildRefused, match="build context leaf"):
        mod._validate_build_context(
            spec,
            context,
            audit=audit,
            sha1dc_evidence=evidence,
        )

    executable.write_bytes(b"substituted")
    with pytest.raises(mod.ImageBuildRefused, match="SHA1DC executable"):
        mod._materialize_build_context(
            spec,
            tmp_path / "tampered-context",
            sha1dc_evidence=evidence,
        )


def test_reviewer_context_requires_the_same_exact_sha1dc_oracle(tmp_path):
    mod = _mod()
    executable = tmp_path / "galaxy-sha1dc"
    executable.write_bytes(b"exact-review-oracle")
    root = mod._REPOSITORY_ROOT
    evidence = mod.Sha1dcBuildEvidence(
        executable_path=str(executable),
        executable_sha256=hashlib.sha256(b"exact-review-oracle").hexdigest(),
        executable_size=len(b"exact-review-oracle"),
        source_lock_sha256=hashlib.sha256(
            (root / "bootstrap/galaxy_launcher/sha1dc_source.lock.json").read_bytes()
        ).hexdigest(),
        source_archive_sha256="2" * 64,
        source_passport_sha256=hashlib.sha256(
            (root / "bootstrap/galaxy_launcher/sha1dc_source_passport.json").read_bytes()
        ).hexdigest(),
        wrapper_sha256=hashlib.sha256(
            (root / "containers/galaxy/sha1dc_object_oracle.c").read_bytes()
        ).hexdigest(),
        builder_base_digest=mod.FULL_BASE.digest,
        runtime_base_digest=mod.SLIM_BASE.digest,
        reproducibility_runs=2,
        self_test="collision-detected",
        normal_object_corpus_count=4,
        network_allowed=False,
    )
    spec = next(item for item in mod.IMAGE_SPECS if item.name == "reviewer")

    assert mod._expected_copy_closure(spec) == (
        mod._ENTRYPOINT_COPY,
        mod._SHA1DC_COPY,
    )
    context = mod._materialize_build_context(
        spec,
        tmp_path / "reviewer-context",
        sha1dc_evidence=evidence,
    )
    assert (
        context / "containers/galaxy/generated/galaxy-sha1dc"
    ).read_bytes() == b"exact-review-oracle"
    audit = mod.audit_dockerfile(
        root / spec.dockerfile,
        expected_base_digest=spec.base.digest,
        expected_roles=spec.roles,
        expected_copy_closure=mod._expected_copy_closure(spec),
    )
    mod._validate_build_context(
        spec,
        context,
        audit=audit,
        sha1dc_evidence=evidence,
    )
    base = {
        "name": mod.SLIM_BASE.name,
        "reference": mod.SLIM_BASE.reference,
        "manifest_digest": mod.SLIM_BASE.digest,
        "image_id": f"sha256:{mod.SLIM_BASE.digest}",
        "architecture": "amd64",
        "os": "linux",
        "rootfs_diff_ids": ["sha256:" + "6" * 64],
        "inventory": {
            "tools": {"dpkg": "test", "gcc": None, "git": None},
            "runtime": {"python": "3.12.13"},
            "packages": [],
        },
    }
    closure_args = {
        "spec": spec,
        "audit": audit,
        "base": base,
        "boundary": {"default_route_absent": True, "routes": []},
        "config_digest": "8" * 64,
        "layer_digests": ("9" * 64,),
    }
    with pytest.raises(mod.ImageBuildRefused, match="reviewer SHA1DC evidence"):
        mod._closure_documents(**closure_args)
    documents = {
        name: json.loads(raw)
        for name, raw in mod._closure_documents(
            **closure_args,
            sha1dc_evidence=evidence,
        ).items()
    }
    assert documents["runtime"]["sha1dc_oracle"] == documents["toolchain"][
        "sha1dc_oracle"
    ]
    assert (
        documents["runtime"]["sha1dc_oracle"]["executable_sha256"]
        == evidence.executable_sha256
    )


def test_build_layout_sends_only_the_external_exact_context_to_buildkit(tmp_path, monkeypatch):
    mod = _mod()
    spec = next(item for item in mod.IMAGE_SPECS if item.name == "driver")
    context = tmp_path / "context"
    context.mkdir()
    destination = tmp_path / "layout"
    calls = []

    def fake_run(command, *, timeout=1800, cwd=None, check=True):
        calls.append((command, cwd, timeout, check))
        destination.mkdir()
        return None

    monkeypatch.setattr(mod, "_run", fake_run)
    mod._build_layout(spec, destination, context_root=context)

    assert len(calls) == 1
    command, cwd, _, _ = calls[0]
    assert cwd == context.resolve(strict=True)
    assert cwd != mod._REPOSITORY_ROOT
    assert command[-1] == "."
    assert command[command.index("--file") + 1] == spec.dockerfile


def test_lock_publication_occurs_only_after_independent_verification(tmp_path, monkeypatch):
    mod = _mod()
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    lock_output = tmp_path / "activation_images.lock.json"
    lock_output.write_bytes(b"prior-reviewed-lock")
    proposal = {"schema": "proposal", "value": 1}

    def refuse(*args, **kwargs):
        raise mod.ImageBuildRefused("independent verification refused")

    monkeypatch.setattr(mod, "load_activation_image_lock", refuse)
    with pytest.raises(mod.ImageBuildRefused, match="independent verification"):
        mod._verify_and_publish_lock(
            proposal,
            artifact_root=artifact_root,
            lock_output=lock_output,
        )
    assert lock_output.read_bytes() == b"prior-reviewed-lock"

    calls = []
    monkeypatch.setattr(mod, "load_activation_image_lock", lambda *args, **kwargs: ("record",))
    monkeypatch.setattr(mod, "verify_activation_images", lambda records: calls.append(records))
    digest = mod._verify_and_publish_lock(
        proposal,
        artifact_root=artifact_root,
        lock_output=lock_output,
    )
    expected = json.dumps(proposal, sort_keys=True, separators=(",", ":")).encode()
    assert lock_output.read_bytes() == expected
    assert digest == hashlib.sha256(expected).hexdigest()
    assert calls == [("record",)]


def test_object_parser_closure_requires_and_cross_binds_sha1dc_evidence(tmp_path):
    mod = _mod()
    executable = tmp_path / "galaxy-sha1dc"
    executable.write_bytes(b"exact-oracle")
    root = mod._REPOSITORY_ROOT
    evidence = mod.Sha1dcBuildEvidence(
        executable_path=str(executable),
        executable_sha256=hashlib.sha256(b"exact-oracle").hexdigest(),
        executable_size=len(b"exact-oracle"),
        source_lock_sha256=hashlib.sha256(
            (root / "bootstrap/galaxy_launcher/sha1dc_source.lock.json").read_bytes()
        ).hexdigest(),
        source_archive_sha256="2" * 64,
        source_passport_sha256=hashlib.sha256(
            (root / "bootstrap/galaxy_launcher/sha1dc_source_passport.json").read_bytes()
        ).hexdigest(),
        wrapper_sha256=hashlib.sha256(
            (root / "containers/galaxy/sha1dc_object_oracle.c").read_bytes()
        ).hexdigest(),
        builder_base_digest=mod.FULL_BASE.digest,
        runtime_base_digest=mod.SLIM_BASE.digest,
        reproducibility_runs=2,
        self_test="collision-detected",
        normal_object_corpus_count=4,
        network_allowed=False,
    )
    spec = next(item for item in mod.IMAGE_SPECS if item.name == "object-parser")
    audit = mod.DockerfileAudit(
        path=tmp_path / "object_parser.Dockerfile",
        sha256="5" * 64,
        base_digest=mod.SLIM_BASE.digest,
        supported_roles=("object_parser",),
    )
    base = {
        "name": mod.SLIM_BASE.name,
        "reference": mod.SLIM_BASE.reference,
        "manifest_digest": mod.SLIM_BASE.digest,
        "image_id": f"sha256:{mod.SLIM_BASE.digest}",
        "architecture": "amd64",
        "os": "linux",
        "rootfs_diff_ids": ["sha256:" + "6" * 64],
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
                        "sha256": "7" * 64,
                        "size": 1,
                    },
                }
            ],
        },
    }
    kwargs = {
        "spec": spec,
        "audit": audit,
        "base": base,
        "boundary": {"default_route_absent": True, "routes": []},
        "config_digest": "8" * 64,
        "layer_digests": ("9" * 64,),
    }

    with pytest.raises(mod.ImageBuildRefused, match="SHA1DC evidence"):
        mod._closure_documents(**kwargs)
    documents = {
        name: json.loads(raw)
        for name, raw in mod._closure_documents(**kwargs, sha1dc_evidence=evidence).items()
    }
    oracle = documents["runtime"]["sha1dc_oracle"]
    assert oracle == documents["toolchain"]["sha1dc_oracle"]
    assert oracle["executable_path"] == "/opt/galaxy/galaxy-sha1dc"
    assert oracle["executable_sha256"] == evidence.executable_sha256
    assert oracle["source_passport_sha256"] == evidence.source_passport_sha256

    ordinary_spec = next(item for item in mod.IMAGE_SPECS if item.name == "driver")
    with pytest.raises(mod.ImageBuildRefused, match="only for object-parser"):
        mod._closure_documents(
            **{**kwargs, "spec": ordinary_spec},
            sha1dc_evidence=evidence,
        )


def test_offline_closure_requires_exact_retained_sha1dc_source_archive(tmp_path):
    mod = _mod()
    source_archive = tmp_path / "sha1dc-source.tar.gz"
    source_archive.write_bytes(b"exact-reviewed-source-archive")
    source = SimpleNamespace(
        archive_size=source_archive.stat().st_size,
        archive_sha256=hashlib.sha256(source_archive.read_bytes()).hexdigest(),
    )
    evidence = {
        "source_archive_path": source_archive.name,
        "source_archive_size": source.archive_size,
        "source_archive_sha256": source.archive_sha256,
    }

    assert mod._verify_offline_source_archive(
        tmp_path,
        evidence,
        source=source,
    ) == source_archive.resolve()

    source_archive.write_bytes(b"tampered-reviewed-source-archive")
    with pytest.raises(mod.ImageBuildRefused, match="source archive"):
        mod._verify_offline_source_archive(tmp_path, evidence, source=source)

    source_archive.unlink()
    with pytest.raises(mod.ImageBuildRefused, match="source archive"):
        mod._verify_offline_source_archive(tmp_path, evidence, source=source)


def test_exact_source_archive_copy_refuses_conflicts_and_binds_size_and_digest(tmp_path):
    mod = _mod()
    source = tmp_path / "download-cache.tar.gz"
    source.write_bytes(b"reviewed-upstream-source")
    destination = tmp_path / "closure" / "sha1dc-source.tar.gz"
    expected_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()

    copied = mod._copy_exact_source_archive(
        source,
        destination,
        expected_size=source.stat().st_size,
        expected_sha256=expected_sha256,
    )

    assert copied == destination.resolve()
    assert copied.read_bytes() == source.read_bytes()
    destination.write_bytes(b"conflict")
    with pytest.raises(mod.ImageBuildRefused, match="destination"):
        mod._copy_exact_source_archive(
            source,
            destination,
            expected_size=source.stat().st_size,
            expected_sha256=expected_sha256,
        )


def test_lock_loader_requires_exact_nine_roles_and_canonical_schema(tmp_path):
    mod = _mod()
    lock = tmp_path / "activation_images.lock.json"
    lock.write_text('{"schema":"wrong","images":[]}', encoding="utf-8")
    with pytest.raises(mod.ImageBuildRefused):
        mod.load_activation_image_lock(lock, archive_root=tmp_path)
