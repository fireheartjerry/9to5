"""Strict deterministic DIRC-v2 codec tests for canonical promotion."""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

from platform_core.runtime.git_index import GitIndex, GitIndexRefused
from platform_core.runtime.object_manifest import ManifestEntry, ManifestPolicy, ObjectManifest


def _manifest() -> ObjectManifest:
    return ObjectManifest(
        expected_revision="a" * 40,
        entries=(
            ManifestEntry(
                path="bin/run.py",
                mode=0o100755,
                blob_oid="b" * 40,
                blob_sha256="1" * 64,
                framed_object_sha256="2" * 64,
                size=7,
            ),
            ManifestEntry(
                path="README.md",
                mode=0o100644,
                blob_oid="c" * 40,
                blob_sha256="3" * 64,
                framed_object_sha256="4" * 64,
                size=5,
            ),
        ),
        attribute_rules=(),
        policy=ManifestPolicy(
            reserved_roots=(),
            max_files=10,
            max_total_bytes=100,
            max_file_bytes=50,
            max_depth=5,
            max_path_bytes=200,
        ),
    )


def _resign(raw: bytes) -> bytes:
    return raw[:-20] + hashlib.sha1(raw[:-20], usedforsecurity=False).digest()


def test_deterministic_index_build_parse_and_manifest_validation() -> None:
    manifest = _manifest()
    raw = GitIndex.build(manifest)
    assert raw == GitIndex.build(manifest)
    parsed = GitIndex.parse(raw, expected_manifest=manifest)
    assert parsed.version == 2
    assert [entry.path for entry in parsed.entries] == ["README.md", "bin/run.py"]
    assert parsed.extensions == ()
    assert parsed.index_digest == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("version", [1, 3, 4])
def test_non_v2_index_is_refused(version: int) -> None:
    raw = bytearray(GitIndex.build(_manifest()))
    raw[4:8] = version.to_bytes(4, "big")
    with pytest.raises(GitIndexRefused, match="DIRC v2"):
        GitIndex.parse(_resign(bytes(raw)))


def test_checksum_truncation_and_entry_oid_drift_are_refused() -> None:
    raw = GitIndex.build(_manifest())
    with pytest.raises(GitIndexRefused, match="checksum"):
        GitIndex.parse(raw[:-1] + bytes([raw[-1] ^ 1]))
    with pytest.raises(GitIndexRefused, match="truncated"):
        GitIndex.parse(raw[:30])

    changed = bytearray(raw)
    changed[12 + 40] ^= 1  # first entry OID begins after its ten stat words
    with pytest.raises(GitIndexRefused, match="manifest"):
        GitIndex.parse(_resign(bytes(changed)), expected_manifest=_manifest())


def test_assume_valid_stage_and_unknown_extension_are_refused() -> None:
    raw = bytearray(GitIndex.build(_manifest()))
    first_path_len = len("README.md".encode("utf-8"))
    flags_offset = 12 + 40 + 20
    flags = int.from_bytes(raw[flags_offset : flags_offset + 2], "big")

    assume = bytearray(raw)
    assume[flags_offset : flags_offset + 2] = (flags | 0x8000).to_bytes(2, "big")
    with pytest.raises(GitIndexRefused, match="assume-valid"):
        GitIndex.parse(_resign(bytes(assume)))

    staged = bytearray(raw)
    staged[flags_offset : flags_offset + 2] = (flags | 0x1000).to_bytes(2, "big")
    with pytest.raises(GitIndexRefused, match="unmerged"):
        GitIndex.parse(_resign(bytes(staged)))

    entry_size = 62 + first_path_len + 1
    entry_size += (-entry_size) % 8
    second_path_len = len("bin/run.py".encode("utf-8"))
    second_size = 62 + second_path_len + 1
    second_size += (-second_size) % 8
    extension_offset = 12 + entry_size + second_size
    unknown = raw[:extension_offset] + b"ABCD" + (1).to_bytes(4, "big") + b"x"
    unknown += hashlib.sha1(unknown, usedforsecurity=False).digest()
    with pytest.raises(GitIndexRefused, match="extension"):
        GitIndex.parse(bytes(unknown))


def test_zero_oid_intent_to_add_entry_is_refused() -> None:
    raw = bytearray(GitIndex.build(_manifest()))
    first_oid_offset = 12 + 40
    raw[first_oid_offset : first_oid_offset + 20] = b"\0" * 20
    with pytest.raises(GitIndexRefused, match="intent-to-add"):
        GitIndex.parse(_resign(bytes(raw)))


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    return result.stdout.strip()


def test_real_git_dirc_v2_with_cache_tree_is_strictly_accepted(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "-c", "init.defaultBranch=main", "init")
    _git(repo, "config", "user.name", "Index Test")
    _git(repo, "config", "user.email", "index@example.invalid")
    (repo / "pkg").mkdir()
    (repo / "README.md").write_text("read\n", encoding="utf-8")
    (repo / "pkg" / "mod.py").write_text("pass\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    _git(repo, "write-tree")
    raw = (repo / ".git" / "index").read_bytes()
    parsed = GitIndex.parse(raw)
    assert parsed.version == 2
    assert [entry.path for entry in parsed.entries] == ["README.md", "pkg/mod.py"]
    assert set(parsed.extensions).issubset({"TREE"})
    manifest = ObjectManifest(
        expected_revision=_git(repo, "rev-parse", "HEAD"),
        entries=tuple(
            ManifestEntry(
                path=entry.path,
                mode=entry.mode,
                blob_oid=entry.oid,
                blob_sha256=f"{index + 1:064x}",
                framed_object_sha256=f"{index + 101:064x}",
                size=entry.size,
            )
            for index, entry in enumerate(parsed.entries)
        ),
        attribute_rules=(),
        policy=ManifestPolicy(
            reserved_roots=(),
            max_files=10,
            max_total_bytes=100,
            max_file_bytes=50,
            max_depth=5,
            max_path_bytes=200,
        ),
    )
    tree_oids = {
        "": _git(repo, "rev-parse", "HEAD^{tree}"),
        "pkg": _git(repo, "rev-parse", "HEAD:pkg"),
    }
    assert GitIndex.parse(
        raw,
        expected_manifest=manifest,
        expected_tree_oids=tree_oids,
    ).tree_extension_digest
    with pytest.raises(GitIndexRefused, match="TREE.*object|tree.*OID"):
        GitIndex.parse(
            raw,
            expected_manifest=manifest,
            expected_tree_oids=tree_oids | {"pkg": "0" * 40},
        )

    tree_offset = raw.rfind(b"TREE", 0, len(raw) - 20)
    assert tree_offset > 0
    count_offset = tree_offset + 8 + 1
    corrupted = bytearray(raw)
    assert corrupted[count_offset : count_offset + 1] == b"2"
    corrupted[count_offset : count_offset + 1] = b"3"
    with pytest.raises(GitIndexRefused, match="TREE.*count|cache-tree.*count"):
        GitIndex.parse(_resign(bytes(corrupted)))
