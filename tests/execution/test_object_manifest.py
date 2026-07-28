"""Canonical inert object-manifest policy and filesystem representability tests."""
from __future__ import annotations

import unicodedata

import pytest

from platform_core.runtime.object_manifest import (
    AttributeRule,
    ManifestEntry,
    ManifestPolicy,
    ObjectManifest,
    ObjectManifestRefused,
)


def _entry(path: str, *, marker: str = "a", mode: int = 0o100644) -> ManifestEntry:
    return ManifestEntry(
        path=path,
        mode=mode,
        blob_oid=marker * 40,
        blob_sha256=marker * 64,
        framed_object_sha256=("b" if marker == "a" else marker) * 64,
        size=4,
    )


def _manifest(*entries: ManifestEntry) -> ObjectManifest:
    return ObjectManifest(
        expected_revision="a" * 40,
        entries=entries,
        attribute_rules=(
            AttributeRule(pattern="*.json", attributes=("text", "eol=lf")),
        ),
        policy=ManifestPolicy(
            reserved_roots=("state/tasks", "state/control", ".galaxy/controller"),
            max_files=20,
            max_total_bytes=1024,
            max_file_bytes=512,
            max_depth=8,
            max_path_bytes=240,
        ),
    )


def test_manifest_is_sorted_content_addressed_and_json_safe() -> None:
    manifest = _manifest(_entry("z.txt"), _entry("a/data.json", marker="c"))
    assert [entry.path for entry in manifest.entries] == ["a/data.json", "z.txt"]
    assert len(manifest.manifest_digest) == 64
    assert len(manifest.object_closure_digest) == 64
    assert manifest.toDict()["attribute_rules"][0]["attributes"] == ["text", "eol=lf"]


@pytest.mark.parametrize(
    "path",
    [
        "/absolute.py",
        "../escape.py",
        "dir//double.py",
        "dir/./dot.py",
        "dir/trailing. ",
        "CON.txt",
        "aux/file.txt",
        "file.txt:stream",
        "bad<name>.py",
        'bad"name.py',
        "bad|name.py",
        "bad?name.py",
        "bad*name.py",
        "bad\x01name.py",
        "back\\slash.py",
        ".git/config",
        "COM1 .txt",
        "LONGNA~10.TXT",
        unicodedata.normalize("NFD", "caf\u00e9.txt"),
    ],
)
def test_unsafe_or_unrepresentable_paths_are_rejected(path: str) -> None:
    with pytest.raises((ValueError, ObjectManifestRefused)):
        _entry(path)


@pytest.mark.parametrize("path", ["state/tasks/run.json", "STATE/CONTROL/key", ".GALAXY/controller/x"])
def test_reserved_runtime_paths_are_case_insensitively_rejected(path: str) -> None:
    with pytest.raises(ObjectManifestRefused, match="reserved runtime"):
        _manifest(_entry(path))


def test_case_and_unicode_aliases_are_rejected() -> None:
    with pytest.raises(ObjectManifestRefused, match="filesystem alias"):
        _manifest(_entry("Readme.md"), _entry("README.md", marker="c"))

    composed = "caf\u00e9.txt"
    decomposed = unicodedata.normalize("NFD", composed)
    with pytest.raises((ValueError, ObjectManifestRefused), match="alias|NFC"):
        _manifest(_entry(composed), _entry(decomposed, marker="c"))


@pytest.mark.parametrize("mode", [0o120000, 0o160000, 0o040000, 0o100600])
def test_only_regular_non_symlink_non_submodule_modes_are_accepted(mode: int) -> None:
    with pytest.raises(ValueError, match="mode"):
        _entry("unsafe", mode=mode)


def test_parent_file_collision_and_quotas_are_rejected() -> None:
    with pytest.raises(ObjectManifestRefused, match="ancestor"):
        _manifest(_entry("pkg"), _entry("pkg/mod.py", marker="c"))
    with pytest.raises(ObjectManifestRefused, match="aggregate byte quota"):
        ObjectManifest(
            expected_revision="a" * 40,
            entries=(
                ManifestEntry(
                    path="large-a.bin",
                    mode=0o100644,
                    blob_oid="a" * 40,
                    blob_sha256="a" * 64,
                    framed_object_sha256="b" * 64,
                    size=300,
                ),
                ManifestEntry(
                    path="large-b.bin",
                    mode=0o100644,
                    blob_oid="c" * 40,
                    blob_sha256="c" * 64,
                    framed_object_sha256="d" * 64,
                    size=300,
                ),
            ),
            attribute_rules=(),
            policy=ManifestPolicy(
                reserved_roots=(),
                max_files=2,
                max_total_bytes=500,
                max_file_bytes=500,
                max_depth=4,
                max_path_bytes=240,
            ),
        )

    with pytest.raises(ValueError, match="portable path ceiling"):
        ManifestPolicy(
            reserved_roots=(),
            max_files=2,
            max_total_bytes=500,
            max_file_bytes=500,
            max_depth=4,
            max_path_bytes=241,
        )


@pytest.mark.parametrize(
    "attributes",
    [
        ("text",),
        ("text", "eol=crlf"),
        ("filter=lfs",),
        ("diff=python",),
        ("working-tree-encoding=UTF-16",),
        ("-text",),
    ],
)
def test_only_exact_precanonicalized_lf_attribute_rule_is_supported(
    attributes: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError, match="text eol=lf"):
        AttributeRule(pattern="*.txt", attributes=attributes)


@pytest.mark.parametrize(
    "pattern",
    ("[attr]owned", "!negative.txt", "dir\\file.txt", "file?.txt", "../escape"),
)
def test_attribute_pattern_grammar_is_closed(pattern: str) -> None:
    with pytest.raises(ValueError, match="safe subset"):
        AttributeRule(pattern=pattern, attributes=("text", "eol=lf"))
