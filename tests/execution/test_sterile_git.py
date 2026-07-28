"""Narrow host-Git runner tests over controller-generated shadow stores only."""
from __future__ import annotations

import hashlib
import shutil
import zlib
from pathlib import Path

import pytest

from platform_core.runtime.sha1dc import qualifyGitSha1dc
from platform_core.runtime.sterile_git import (
    SterileGit,
    SterileGitRefused,
    initializeSterileGitDirectory,
)


def _runner(tmp_path: Path, *, max_output_bytes: int = 1024 * 1024):
    git = shutil.which("git")
    assert git is not None
    evidence, oracle = qualifyGitSha1dc(
        executable=git,
        sterile_root=tmp_path / "sha1dc",
    )
    controller = tmp_path / "controller"
    git_dir = controller / "shadow.git"
    initializeSterileGitDirectory(git_dir)
    runner = SterileGit(
        git_dir=git_dir,
        controller_root=controller,
        sha1dc_oracle=oracle,
        sha1dc_evidence=evidence,
        max_output_bytes=max_output_bytes,
    )
    return runner, git_dir


def _install_blob(git_dir: Path, payload: bytes) -> str:
    framed = b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload
    oid = hashlib.sha1(framed, usedforsecurity=False).hexdigest()
    path = git_dir / "objects" / oid[:2] / oid[2:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(zlib.compress(framed, level=9))
    return oid


def test_sterile_git_reads_only_allowlisted_generated_objects(tmp_path: Path) -> None:
    runner, git_dir = _runner(tmp_path)
    oid = _install_blob(git_dir, b"safe\n")
    result = runner.run(("cat-file", "-p", oid))
    assert result.returncode == 0
    assert result.stdout == b"safe\n"
    assert result.stderr == b""
    assert result.argv[-3:] == ("cat-file", "-p", oid)
    assert result.network_allowed is False


def test_sterile_git_ignores_poisoned_ambient_config_and_rejects_local_poison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ambient = tmp_path / "ambient"
    ambient.mkdir()
    goldstone = tmp_path / "goldstone"
    global_config = ambient / ".gitconfig"
    global_config.write_text(
        f"[include]\n\tpath = {goldstone.as_posix()}\n[alias]\n\tpwn = !echo touched\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(ambient))
    monkeypatch.setenv("USERPROFILE", str(ambient))
    runner, git_dir = _runner(tmp_path)
    oid = _install_blob(git_dir, b"safe")
    assert runner.run(("cat-file", "-t", oid)).stdout == b"blob\n"
    assert not goldstone.exists()

    (git_dir / "config").write_text(
        "[core]\n\tbare = true\n[include]\n\tpath = ../goldstone\n",
        encoding="utf-8",
    )
    with pytest.raises(SterileGitRefused, match="local configuration"):
        runner.run(("cat-file", "-t", oid))


@pytest.mark.parametrize(
    "argv",
    [
        ("config", "--list"),
        ("cat-file", "--batch"),
        ("cat-file", "-p", "HEAD"),
        ("upload-pack", "."),
        ("-c", "core.hooksPath=.", "cat-file", "-t", "a" * 40),
    ],
)
def test_sterile_git_rejects_commands_flags_and_revision_syntax(
    tmp_path: Path, argv: tuple[str, ...]
) -> None:
    runner, _ = _runner(tmp_path)
    with pytest.raises(SterileGitRefused, match="allowlist"):
        runner.run(argv)


def test_sterile_git_enforces_combined_output_quota(tmp_path: Path) -> None:
    runner, git_dir = _runner(tmp_path, max_output_bytes=16)
    oid = _install_blob(git_dir, b"x" * 128)
    with pytest.raises(SterileGitRefused, match="output quota"):
        runner.run(("cat-file", "-p", oid))


def test_sterile_git_directory_must_be_owned_and_outside_forbidden_root(
    tmp_path: Path,
) -> None:
    git = shutil.which("git")
    assert git is not None
    evidence, oracle = qualifyGitSha1dc(
        executable=git,
        sterile_root=tmp_path / "sha1dc",
    )
    controller = tmp_path / "controller"
    outside = tmp_path / "outside.git"
    initializeSterileGitDirectory(outside)
    with pytest.raises(SterileGitRefused, match="controller root"):
        SterileGit(
            git_dir=outside,
            controller_root=controller,
            sha1dc_oracle=oracle,
            sha1dc_evidence=evidence,
        )

    forbidden = controller / "canonical"
    git_dir = forbidden / ".git"
    initializeSterileGitDirectory(git_dir)
    with pytest.raises(SterileGitRefused, match="forbidden"):
        SterileGit(
            git_dir=git_dir,
            controller_root=controller,
            sha1dc_oracle=oracle,
            sha1dc_evidence=evidence,
            forbidden_roots=(forbidden,),
        )
