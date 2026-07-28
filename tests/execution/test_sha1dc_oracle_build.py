"""Offline, reproducible SHA1DC object-oracle source and build tests."""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.build_sha1dc_oracle import (
    Sha1dcBuildRefused,
    buildSha1dcOracle,
    readSha1dcSourceLock,
)

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "bootstrap/galaxy_launcher/sha1dc_source.lock.json"
PASSPORT = ROOT / "bootstrap/galaxy_launcher/sha1dc_source_passport.json"


def test_sha1dc_docker_runner_uses_pinned_binary_and_empty_config(tmp_path, monkeypatch):
    mod = importlib.import_module("tools.build_sha1dc_oracle")
    docker = tmp_path / "docker.exe"
    buildx = tmp_path / "docker-buildx.exe"
    docker.write_bytes(b"docker")
    buildx.write_bytes(b"buildx")
    ambient = tmp_path / "ambient-docker-config"
    ambient.mkdir()
    monkeypatch.setenv("DOCKER_CONFIG", str(ambient))
    monkeypatch.setattr(
        mod,
        "resolvePinnedDockerTools",
        lambda: SimpleNamespace(executable=docker, buildx_plugin=buildx),
    )
    observed: dict[str, object] = {}

    def fake_run(command, **kwargs):
        environment = dict(kwargs["env"])
        config_root = Path(environment["DOCKER_CONFIG"])
        observed["command"] = list(command)
        observed["environment"] = environment
        assert config_root.is_dir()
        assert not any(config_root.iterdir())
        return subprocess.CompletedProcess(command, 0, stdout=b"ok", stderr=b"")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    completed = mod._run(["docker", "version"])

    assert completed.stdout == b"ok"
    assert Path(observed["command"][0]) == docker
    assert observed["environment"]["DOCKER_CONFIG"] != str(ambient)
    assert "PATH" not in observed["environment"]
    assert not Path(observed["environment"]["DOCKER_CONFIG"]).exists()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _cached_archive() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    assert local is not None
    return (
        Path(local)
        / "9to5"
        / "galaxy-dev-tools"
        / "sources"
        / "sha1collisiondetection-855827c583bc30645ba427885caa40c5b81764d2.tar.gz"
    )


def test_source_lock_and_passport_are_canonical_and_complete() -> None:
    source = readSha1dcSourceLock(LOCK)
    passport_raw = PASSPORT.read_bytes()
    passport = json.loads(passport_raw)

    assert LOCK.read_bytes() == _canonical(json.loads(LOCK.read_bytes())) + b"\n"
    assert passport_raw == _canonical(passport) + b"\n"
    assert source.revision == "855827c583bc30645ba427885caa40c5b81764d2"
    assert source.archive_sha256 == (
        "9bdeac6f97cc09b05343810c5da6f541c052a6f8b15e79959802ae96105b29da"
    )
    assert source.license_sha256 == passport["license_file"]["sha256"]
    assert passport["authority"] == "qualification_only"
    assert passport["closed_input_contract"]["repository_access"] is False
    assert passport["rollback"].endswith("ordinary SHA-1.")


def test_source_passport_semantically_binds_lock_owner_symbols_and_expiry() -> None:
    mod = importlib.import_module("tools.build_sha1dc_oracle")
    source = readSha1dcSourceLock(LOCK)

    passport = mod.readSha1dcSourcePassport(
        PASSPORT,
        source=source,
        at_time=datetime(2026, 7, 16, tzinfo=UTC),
    )

    assert passport.revision == source.revision
    assert passport.tree_oid == source.tree_oid
    assert passport.owner == "GALAXY Singularity kernel owner"
    assert passport.expiry == datetime(2027, 7, 16, tzinfo=UTC)
    assert passport.copied_symbols == (
        "SHA1DCInit",
        "SHA1DCSetSafeHash",
        "SHA1DCSetUseDetectColl",
        "SHA1DCUpdate",
        "SHA1DCFinal",
        "sha1_compression_states",
        "ubc_check",
    )


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("revision", "0" * 40, "source lock"),
        ("copied_symbols", ["SHA1DCInit"], "symbol inventory"),
        ("kill_switch_owner", "", "owner"),
        ("expiry", "2026-07-16T12:00:00Z", "expired"),
    ],
)
def test_source_passport_semantic_weakening_is_refused(
    tmp_path: Path,
    field: str,
    replacement: object,
    message: str,
) -> None:
    mod = importlib.import_module("tools.build_sha1dc_oracle")
    source = readSha1dcSourceLock(LOCK)
    value = json.loads(PASSPORT.read_bytes())
    value[field] = replacement
    candidate = tmp_path / "passport.json"
    candidate.write_bytes(_canonical(value) + b"\n")

    with pytest.raises(Sha1dcBuildRefused, match=message):
        mod.readSha1dcSourcePassport(
            candidate,
            source=source,
            at_time=datetime(2026, 7, 17, tzinfo=UTC),
        )


def test_source_archive_corruption_is_refused_before_extraction(tmp_path: Path) -> None:
    archive = tmp_path / "source.tar.gz"
    archive.write_bytes(b"not-the-reviewed-source")

    with pytest.raises(Sha1dcBuildRefused, match="archive digest"):
        buildSha1dcOracle(
            source_lock_path=LOCK,
            source_archive=archive,
            output_root=tmp_path / "output",
        )


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker CLI unavailable")
def test_oracle_build_is_reproducible_and_collision_detecting(tmp_path: Path) -> None:
    archive = _cached_archive()
    if not archive.is_file():
        pytest.skip("reviewed SHA1DC source archive is not preseeded")

    evidence = buildSha1dcOracle(
        source_lock_path=LOCK,
        source_archive=archive,
        output_root=tmp_path / "output",
    )

    executable = Path(evidence.executable_path)
    assert executable.is_file()
    assert hashlib.sha256(executable.read_bytes()).hexdigest() == evidence.executable_sha256
    assert evidence.reproducibility_runs == 2
    assert evidence.self_test == "collision-detected"
    assert evidence.normal_object_corpus_count >= 4
    assert evidence.network_allowed is False
    assert (tmp_path / "output" / "sha1dc-build-evidence.json").is_file()
