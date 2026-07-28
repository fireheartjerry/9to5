"""Pinned collision-detecting SHA-1 oracle tests."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

import platform_core.runtime.sha1dc as sha1dc_module
from platform_core.runtime.sha1dc import (
    Sha1dcRefused,
    _sterile_env,
    qualifyGitSha1dc,
    qualifyStandaloneSha1dc,
)

# First complete 320-byte collision prefix from the two SHAttered fixtures at
# cr-marcstevens/sha1collisiondetection@855827c583bc30645ba427885caa40c5b81764d2.
# The compact prefixes retain the raw SHA-1 collision without vendoring two PDFs.
_SHATTERED_PREFIXES = (
    bytes.fromhex(
        "255044462d312e330a25e2e3cfd30a0a0a312030206f626a0a3c3c2f5769647468"
        "2032203020522f4865696768742033203020522f547970652034203020522f537562"
        "747970652035203020522f46696c7465722036203020522f436f6c6f725370616365"
        "2037203020522f4c656e6774682038203020522f42697473506572436f6d706f6e65"
        "6e7420383e3e0a73747265616d0affd8fffe00245348412d312069732064656164"
        "2121212121852fec092339759c39b1a1c63c4c97e1fffe017346dc9166b67e118f0"
        "29ab621b2560ff9ca67cca8c7f85ba84c79030c2b3de218f86db3a90901d5df45c1"
        "4f26fedfb3dc38e96ac22fe7bd728f0e45bce046d23c570feb141398bb552ef5a0a8"
        "2be331fea48037b8b5d71f0e332edf93ac3500eb4ddc0decc1a864790c782c762156"
        "60dd309791d06bd0af3f98cda4bc4629b1"
    ),
    bytes.fromhex(
        "255044462d312e330a25e2e3cfd30a0a0a312030206f626a0a3c3c2f5769647468"
        "2032203020522f4865696768742033203020522f547970652034203020522f537562"
        "747970652035203020522f46696c7465722036203020522f436f6c6f725370616365"
        "2037203020522f4c656e6774682038203020522f42697473506572436f6d706f6e65"
        "6e7420383e3e0a73747265616d0affd8fffe00245348412d312069732064656164"
        "2121212121852fec092339759c39b1a1c63c4c97e1fffe017f46dc93a6b67e013b0"
        "29aaa1db2560b45ca67d688c7f84b8c4c791fe02b3df614f86db1690901c56b45c1"
        "530afedfb76038e972722fe7ad728f0e4904e046c230570fe9d41398abe12ef5bc942"
        "be33542a4802d98b5d70f2a332ec37fac3514e74ddc0f2cc1a874cd0c78305a21566"
        "461309789606bd0bf3f98cda8044629a1"
    ),
)


def _standalone_build_evidence(executable: Path) -> dict[str, object]:
    return {
        "builder_base_digest": sha1dc_module._STANDALONE_BUILDER_BASE,
        "executable_path": str(executable.resolve()),
        "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "executable_size": executable.stat().st_size,
        "network_allowed": False,
        "normal_object_corpus_count": 4,
        "reproducibility_runs": 2,
        "runtime_base_digest": sha1dc_module._STANDALONE_RUNTIME_BASE,
        "schema": "galaxy.sha1dc-build-evidence/v1",
        "self_test": "collision-detected",
        "source_archive_sha256": "1" * 64,
        "source_lock_sha256": "2" * 64,
        "source_passport_sha256": "3" * 64,
        "wrapper_sha256": "4" * 64,
    }


def test_standalone_sha1dc_uses_only_the_closed_runtime_protocol(
    tmp_path: Path, monkeypatch
) -> None:
    executable = tmp_path / "galaxy-sha1dc.exe"
    executable.write_bytes(b"sealed-standalone-sha1dc")
    evidence_path = tmp_path / "sha1dc-build-evidence.json"
    build_evidence = _standalone_build_evidence(executable)
    evidence_path.write_bytes(
        json.dumps(
            build_evidence,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    calls: list[tuple[tuple[str, ...], bytes | None]] = []

    def run_closed(_executable, args, *, sterile_root, input_bytes, timeout):
        del sterile_root, timeout
        calls.append((tuple(args), input_bytes))
        if args == ["--version"]:
            return SimpleNamespace(
                returncode=0,
                stdout=sha1dc_module._STANDALONE_VERSION,
                stderr=b"",
            )
        if args == ["--self-test"]:
            return SimpleNamespace(
                returncode=0,
                stdout=sha1dc_module._STANDALONE_SELF_TEST,
                stderr=b"",
            )
        assert args == ["hash-object", "blob", "6"]
        framed = b"blob 6\0hello\n"
        return SimpleNamespace(
            returncode=0,
            stdout=hashlib.sha1(framed, usedforsecurity=False).hexdigest().encode()
            + b"\n",
            stderr=b"",
        )

    monkeypatch.setattr(sha1dc_module, "_run_standalone", run_closed)
    evidence, oracle = qualifyStandaloneSha1dc(
        executable=executable,
        build_evidence=evidence_path,
        sterile_root=tmp_path / "sterile",
    )

    assert evidence.toDict() == {
        "schema": "galaxy.sha1dc-standalone-evidence/v1",
        "executable_path": str(executable.resolve()),
        "executable_sha256": build_evidence["executable_sha256"],
        "executable_link_count": 1,
        "runtime_attestation_digest": hashlib.sha256(
            sha1dc_module._STANDALONE_VERSION
            + sha1dc_module._STANDALONE_SELF_TEST
        ).hexdigest(),
        "build_evidence_path": str(evidence_path.resolve()),
        "build_evidence_sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
        "source_revision": sha1dc_module._STANDALONE_SOURCE_REVISION,
        "protocol": "galaxy.sha1dc-object-oracle/v1",
        "collision_detection": "SHA1_DC",
        "network_allowed": False,
    }
    assert oracle.hashObject("blob", b"hello\n") == hashlib.sha1(
        b"blob 6\0hello\n", usedforsecurity=False
    ).hexdigest()
    assert calls == [
        (("--version",), None),
        (("--self-test",), None),
        (("--version",), None),
        (("--self-test",), None),
        (("hash-object", "blob", "6"), b"hello\n"),
    ]

    build_evidence["network_allowed"] = True
    evidence_path.write_bytes(
        json.dumps(build_evidence, separators=(",", ":"), sort_keys=True).encode()
    )
    with pytest.raises(Sha1dcRefused, match="build evidence"):
        oracle.revalidate()


def test_git_sha1dc_oracle_is_binary_and_build_digest_pinned(tmp_path: Path) -> None:
    git = shutil.which("git")
    assert git is not None
    evidence, oracle = qualifyGitSha1dc(
        executable=git,
        sterile_root=tmp_path / "sterile",
    )
    assert evidence.collision_detection == "SHA1_DC"
    assert len(evidence.executable_sha256) == 64
    assert len(evidence.build_options_digest) == 64
    assert evidence.network_allowed is False
    assert "sterile_root" not in evidence.toDict()

    payload = b"hello\n"
    expected = hashlib.sha1(
        b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload,
        usedforsecurity=False,
    ).hexdigest()
    assert oracle.hashObject("blob", payload) == expected
    assert oracle.revalidate() == evidence


def test_git_sha1dc_oracle_disables_lazy_fetch(tmp_path: Path) -> None:
    executable = tmp_path / "git"
    environment = _sterile_env(tmp_path / "sterile", executable)

    assert environment["GIT_NO_LAZY_FETCH"] == "1"


def test_shattered_collision_is_strongly_distinguished_before_object_identity(
    tmp_path: Path,
) -> None:
    left, right = _SHATTERED_PREFIXES
    assert left != right
    assert len(left) == len(right) == 320
    assert hashlib.sha1(left, usedforsecurity=False).hexdigest() == (
        "f92d74e3874587aaf443d1db961d4e26dde13e9c"
    )
    assert hashlib.sha1(right, usedforsecurity=False).hexdigest() == (
        "f92d74e3874587aaf443d1db961d4e26dde13e9c"
    )
    assert hashlib.sha256(left).hexdigest() == (
        "cac8644dba1a9aef70cc268f3794036a2be5b5107109ad742247858fd1a36990"
    )
    assert hashlib.sha256(right).hexdigest() == (
        "842a2c7d2f85b25998d5e43fcced0ba3ca570ee0d36bedb23a815d79e614f646"
    )
    git = shutil.which("git")
    assert git is not None
    _, oracle = qualifyGitSha1dc(
        executable=git,
        sterile_root=tmp_path / "sterile",
    )

    assert oracle.hashObject("blob", left) != oracle.hashObject("blob", right)


def test_oracle_refuses_binary_or_evidence_drift(tmp_path: Path) -> None:
    git = shutil.which("git")
    assert git is not None
    evidence, oracle = qualifyGitSha1dc(
        executable=git,
        sterile_root=tmp_path / "sterile",
    )
    with pytest.raises(Sha1dcRefused, match="binary digest"):
        oracle.withExpectedEvidence(
            evidence.__class__(
                **(evidence.__dict__ | {"executable_sha256": "f" * 64})
            )
        ).hashObject("blob", b"x")


@pytest.mark.parametrize("object_type", ["", "tag", "blob\ncommit", "../tree"])
def test_oracle_accepts_only_kernel_generated_object_types(
    tmp_path: Path, object_type: str
) -> None:
    git = shutil.which("git")
    assert git is not None
    _, oracle = qualifyGitSha1dc(
        executable=git,
        sterile_root=tmp_path / "sterile",
    )
    with pytest.raises(ValueError, match="object type"):
        oracle.hashObject(object_type, b"payload")
