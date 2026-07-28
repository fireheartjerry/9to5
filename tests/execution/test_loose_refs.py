"""Create-only private refs and one canonical loose-ref CAS tests."""
from __future__ import annotations

import os
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

import platform_core.runtime.loose_refs as loose_refs_module
from platform_core.core.fsio import NativeDirectoryEntry, NativeFileIdentity
from platform_core.runtime.canonical_repo import attestCanonicalRepository
from platform_core.runtime.loose_refs import (
    CanonicalRefCas,
    LooseRefStore,
    RefCasRefused,
    RefCollision,
    RefPathRefused,
)


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


def _repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "-c", "init.defaultBranch=main", "init")
    _git(repo, "config", "user.name", "Ref Test")
    _git(repo, "config", "user.email", "ref@example.invalid")
    (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "tracked.txt").write_text("proposed\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "proposed")
    proposed = _git(repo, "rev-parse", "HEAD")
    _git(repo, "reset", "--hard", base)
    return repo, base, proposed


def _cas(
    store: LooseRefStore,
    *,
    expected_oid: str,
    proposed_oid: str,
    ownership_nonce: str,
    failpoint=None,
) -> CanonicalRefCas:
    prepared = store.prepareCanonicalLock(proposed_oid=proposed_oid)
    try:
        return store.compareAndSwapCanonical(
            expected_oid=expected_oid,
            proposed_oid=proposed_oid,
            ownership_nonce=ownership_nonce,
            prepared_lock=prepared,
            commit_guard=lambda: None,
            failpoint=failpoint,
        )
    finally:
        store.releaseCanonicalLock(prepared)


def test_ref_parent_traversal_refuses_a_volume_escape() -> None:
    root_identity = NativeFileIdentity(
        volume_id=7,
        file_id=1,
        link_count=1,
        size=0,
        attributes=0,
        mode=0o40700,
        write_time=0,
        change_time=0,
        is_directory=True,
        is_reparse=False,
    )

    class Directory:
        def __init__(self, name: str, identity: NativeFileIdentity) -> None:
            self.name = name
            self.identity = identity

        def listEntries(self):
            return (
                NativeDirectoryEntry(
                    "refs",
                    replace(root_identity, file_id=2),
                ),
            )

        def openDirectory(self, _name, *, expected=None):
            return Directory("refs", replace(root_identity, volume_id=8, file_id=2))

        def close(self):
            return None

    with pytest.raises(RefPathRefused, match="volume"):
        with loose_refs_module._openRefParent(
            Directory("root", root_identity),  # type: ignore[arg-type]
            "refs/heads/main",
            create=False,
        ):
            pass


def test_private_ref_create_is_exact_idempotent_and_never_moves(tmp_path: Path) -> None:
    repo, base, proposed = _repo(tmp_path)
    store = LooseRefStore(attestCanonicalRepository(repo))
    ref = "refs/9to5/staged/tx-001"
    created = store.createPrivateRef(ref, proposed)
    assert created.created is True
    assert store.createPrivateRef(ref, proposed).created is False
    with pytest.raises(RefCollision):
        store.createPrivateRef(ref, base)
    assert store.readRef(ref) == proposed


def test_canonical_cas_moves_only_ref_and_preserves_index_and_worktree(tmp_path: Path) -> None:
    repo, base, proposed = _repo(tmp_path)
    store = LooseRefStore(attestCanonicalRepository(repo))
    index_before = (repo / ".git" / "index").read_bytes()
    file_before = (repo / "tracked.txt").read_bytes()
    result = _cas(
        store,
        expected_oid=base,
        proposed_oid=proposed,
        ownership_nonce="a" * 64,
    )
    assert result is CanonicalRefCas.MOVED
    assert store.readRef("refs/heads/main") == proposed
    assert (repo / ".git" / "index").read_bytes() == index_before
    assert (repo / "tracked.txt").read_bytes() == file_before
    assert not (repo / ".git" / "refs" / "heads" / "main.lock").exists()


def test_stale_expected_and_unknown_existing_lock_refuse_without_cleanup(
    tmp_path: Path,
) -> None:
    repo, base, proposed = _repo(tmp_path)
    store = LooseRefStore(attestCanonicalRepository(repo))
    with pytest.raises(RefCasRefused, match="expected OID"):
        _cas(
            store,
            expected_oid="f" * 40,
            proposed_oid=proposed,
            ownership_nonce="a" * 64,
        )
    assert store.readRef("refs/heads/main") == base

    lock = repo / ".git" / "refs" / "heads" / "main.lock"
    lock.write_text("foreign-lock", encoding="ascii")
    with pytest.raises(RefCasRefused, match="lock"):
        _cas(
            store,
            expected_oid=base,
            proposed_oid=proposed,
            ownership_nonce="a" * 64,
        )
    assert lock.read_text(encoding="ascii") == "foreign-lock"
    assert store.readRef("refs/heads/main") == base


def test_same_oid_branch_switch_under_lock_is_refused(tmp_path: Path) -> None:
    repo, base, proposed = _repo(tmp_path)
    store = LooseRefStore(attestCanonicalRepository(repo))
    other_ref = repo / ".git" / "refs" / "heads" / "other"
    other_ref.write_bytes((base + "\n").encode("ascii"))

    def switch(stage: str) -> None:
        if stage == "after_lock_before_head_check":
            (repo / ".git" / "HEAD").write_bytes(b"ref: refs/heads/other\n")

    with pytest.raises(RefCasRefused, match="symbolic HEAD"):
        _cas(
            store,
            expected_oid=base,
            proposed_oid=proposed,
            ownership_nonce="a" * 64,
            failpoint=switch,
        )
    assert store.readRef("refs/heads/main") == base


def test_noncooperative_ref_move_before_rename_is_detected_not_overwritten(
    tmp_path: Path,
) -> None:
    repo, base, proposed = _repo(tmp_path)
    store = LooseRefStore(attestCanonicalRepository(repo))
    third = "f" * 40

    def direct_move(stage: str) -> None:
        if stage == "before_ref_rename":
            (repo / ".git" / "refs" / "heads" / "main").write_bytes(
                (third + "\n").encode("ascii")
            )

    with pytest.raises(RefCasRefused, match="changed under fence"):
        _cas(
            store,
            expected_oid=base,
            proposed_oid=proposed,
            ownership_nonce="a" * 64,
            failpoint=direct_move,
        )
    assert store.readRef("refs/heads/main") == third


@pytest.mark.skipif(os.name != "nt", reason="Windows retained-handle boundary")
def test_canonical_cas_refuses_a_rebound_git_common_before_rename(
    tmp_path: Path,
) -> None:
    repo, base, proposed = _repo(tmp_path)
    store = LooseRefStore(attestCanonicalRepository(repo))
    common = repo / ".git"
    heads = common / "refs" / "heads"
    held = common / "refs" / "heads-held"

    def rebind(stage: str) -> None:
        if stage != "before_ref_rename":
            return
        heads.rename(held)
        heads.mkdir()
        (heads / "main").write_bytes((base + "\n").encode("ascii"))
        (heads / "goldstone.txt").write_bytes(b"replacement\n")

    with pytest.raises(RefCasRefused, match="identity|drift"):
        _cas(
            store,
            expected_oid=base,
            proposed_oid=proposed,
            ownership_nonce="a" * 64,
            failpoint=rebind,
        )

    assert (heads / "main").read_text(encoding="ascii") == f"{base}\n"
    assert (heads / "goldstone.txt").read_bytes() == b"replacement\n"
    assert (held / "main").read_text(encoding="ascii") == f"{base}\n"
    # The parent identity was deliberately rebound.  Cleanup must not rediscover
    # or delete by pathname; the exact old-parent lease remains inert evidence.
    assert (held / "main.lock").read_text(encoding="ascii") == f"{proposed}\n"


def test_crash_after_atomic_rename_is_classified_from_ref_truth(tmp_path: Path) -> None:
    repo, base, proposed = _repo(tmp_path)
    store = LooseRefStore(attestCanonicalRepository(repo))

    def crash(stage: str) -> None:
        if stage == "after_ref_rename":
            raise RuntimeError("simulated process death")

    with pytest.raises(RuntimeError, match="simulated"):
        _cas(
            store,
            expected_oid=base,
            proposed_oid=proposed,
            ownership_nonce="a" * 64,
            failpoint=crash,
        )
    assert store.classifyCanonical(expected_oid=base, proposed_oid=proposed) is CanonicalRefCas.MOVED


@pytest.mark.parametrize(
    "ref",
    ["../escape", "refs/heads/../../escape", "refs//heads/x", "refs/heads/x.lock", "HEAD"],
)
def test_ref_namespace_cannot_escape_or_alias_lockfiles(tmp_path: Path, ref: str) -> None:
    repo, _, proposed = _repo(tmp_path)
    store = LooseRefStore(attestCanonicalRepository(repo))
    with pytest.raises(RefPathRefused):
        store.createPrivateRef(ref, proposed)
