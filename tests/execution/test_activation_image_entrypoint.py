"""Executable contracts for the generic sealed activation-image entrypoint."""

from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path

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
    return importlib.import_module("bootstrap.galaxy_launcher.activation_image_entrypoint")


@pytest.mark.parametrize("role", sorted(ROLES))
def test_each_role_emits_an_inactive_empty_cwd_nonroot_canary(tmp_path, role):
    mod = _mod()
    empty_cwd = tmp_path / "empty"
    empty_cwd.mkdir()
    receipt = mod.build_image_canary(
        sealed_role=role,
        requested_role=role,
        cwd=empty_cwd,
        environment={"LC_CTYPE": "C.UTF-8"},
        uid=65532,
        gid=65532,
    )
    assert receipt == {
        "schema": "galaxy.activation-image-canary/v1",
        "status": "ready_inactive",
        "role": role,
        "uid": 65532,
        "gid": 65532,
        "cwd_empty": True,
        "ambient_environment": [],
        "manifest_binding_required": True,
    }


@pytest.mark.parametrize(
    ("change", "match"),
    [
        ({"uid": 0}, "nonroot"),
        ({"requested_role": "reviewer"}, "role"),
        ({"environment": {"OPENAI_API_KEY": "poison"}}, "environment"),
    ],
)
def test_canary_refuses_root_role_substitution_and_ambient_environment(tmp_path, change, match):
    mod = _mod()
    empty_cwd = tmp_path / "empty"
    empty_cwd.mkdir()
    args = {
        "sealed_role": "verifier",
        "requested_role": "verifier",
        "cwd": empty_cwd,
        "environment": {},
        "uid": 65532,
        "gid": 65532,
    }
    args.update(change)
    with pytest.raises(mod.ActivationImageRefused, match=match):
        mod.build_image_canary(**args)


def test_canary_refuses_nonempty_cwd(tmp_path):
    mod = _mod()
    nonempty_cwd = tmp_path / "nonempty"
    nonempty_cwd.mkdir()
    (nonempty_cwd / "poison").write_text("untrusted", encoding="utf-8")
    with pytest.raises(mod.ActivationImageRefused, match="working directory"):
        mod.build_image_canary(
            sealed_role="verifier",
            requested_role="verifier",
            cwd=nonempty_cwd,
            environment={},
            uid=65532,
            gid=65532,
        )


def _write_bound_runtime(root: Path, *, role: str = "verifier"):
    runtime = root / "runtime"
    runtime.mkdir()
    entrypoint = runtime / "entry.py"
    entrypoint.write_bytes(b"print('sealed')\n")
    leaf_digest = hashlib.sha256(entrypoint.read_bytes()).hexdigest()
    manifest = {
        "schema": "galaxy.activation-runtime/v1",
        "role": role,
        "entrypoint": "entry.py",
        "argv": ["--sealed"],
        "leaves": [{"path": "entry.py", "sha256": leaf_digest, "size": entrypoint.stat().st_size}],
    }
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    manifest_path = root / "activation.json"
    manifest_path.write_bytes(raw)
    return runtime, manifest_path, hashlib.sha256(raw).hexdigest()


def test_bound_runtime_requires_canonical_exact_manifest_and_every_leaf(tmp_path):
    mod = _mod()
    runtime, manifest, digest = _write_bound_runtime(tmp_path)
    bound = mod.verify_bound_runtime(
        manifest_path=manifest,
        runtime_root=runtime,
        expected_manifest_sha256=digest,
        sealed_role="verifier",
    )
    assert bound.entrypoint == (runtime / "entry.py").resolve()
    assert bound.argv == ("--sealed",)
    assert bound.manifest_sha256 == digest

    manifest.write_bytes(manifest.read_bytes() + b"\n")
    with pytest.raises(mod.ActivationImageRefused, match="manifest"):
        mod.verify_bound_runtime(
            manifest_path=manifest,
            runtime_root=runtime,
            expected_manifest_sha256=digest,
            sealed_role="verifier",
        )


def test_bound_runtime_rejects_role_symlink_unlisted_file_and_leaf_tamper(tmp_path):
    mod = _mod()
    runtime, manifest, digest = _write_bound_runtime(tmp_path)
    with pytest.raises(mod.ActivationImageRefused, match="role"):
        mod.verify_bound_runtime(
            manifest_path=manifest,
            runtime_root=runtime,
            expected_manifest_sha256=digest,
            sealed_role="reviewer",
        )

    (runtime / "unlisted").write_bytes(b"smuggled")
    with pytest.raises(mod.ActivationImageRefused, match="unlisted"):
        mod.verify_bound_runtime(
            manifest_path=manifest,
            runtime_root=runtime,
            expected_manifest_sha256=digest,
            sealed_role="verifier",
        )
    (runtime / "unlisted").unlink()

    (runtime / "entry.py").write_bytes(b"tampered")
    with pytest.raises(mod.ActivationImageRefused, match="leaf"):
        mod.verify_bound_runtime(
            manifest_path=manifest,
            runtime_root=runtime,
            expected_manifest_sha256=digest,
            sealed_role="verifier",
        )


def test_bound_runtime_appends_only_explicit_container_command_arguments(tmp_path, monkeypatch):
    mod = _mod()
    entrypoint = tmp_path / "probe.py"
    entrypoint.write_bytes(b"pass\n")
    monkeypatch.setattr(mod, "_unix_identity", lambda: (65532, 65532))
    monkeypatch.setattr(mod, "_validate_boot_boundary", lambda **_kwargs: None)
    monkeypatch.setattr(
        mod,
        "verify_bound_runtime",
        lambda **_kwargs: mod.BoundRuntime(
            entrypoint=entrypoint,
            argv=("--probe-worker",),
            manifest_sha256="1" * 64,
            verified_leaves=(entrypoint,),
        ),
    )
    observed = {}

    def capture(executable, argv, environment):
        observed.update(executable=executable, argv=argv, environment=environment)
        raise RuntimeError("exec captured")

    monkeypatch.setattr(mod.os, "execve", capture)
    with pytest.raises(RuntimeError, match="exec captured"):
        mod.main(
            [
                "run-bound",
                "--sealed-role",
                "verifier",
                "--manifest-sha256",
                "1" * 64,
                "probe-id",
                "2" * 64,
            ]
        )
    assert observed == {
        "executable": "/usr/local/bin/python3",
        "argv": [
            "/usr/local/bin/python3",
            "-I",
            "-S",
            str(entrypoint),
            "--probe-worker",
            "probe-id",
            "2" * 64,
        ],
        "environment": {},
    }
