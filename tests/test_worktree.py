"""git-worktree backend: enter/exit on a temp repo, fail-open to shared tree, safe gc."""
import shutil
import subprocess

import pytest

from platform_core.runtime import worktree


def _git(args, cwd):
    subprocess.run(["git"] + args, cwd=cwd, check=True,
                   capture_output=True, text=True)


def _has_git():
    return shutil.which("git") is not None


class _State:
    def __init__(self, task_id, root):
        self.task_id = task_id
        self.meta = {"work_dir": str(root)}


@pytest.mark.skipif(not _has_git(), reason="git not available")
def test_enter_exit_merge(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-b", "main"], repo)
    _git(["config", "user.email", "t@t"], repo)
    _git(["config", "user.name", "t"], repo)
    (repo / "f.txt").write_text("hi", encoding="utf-8")
    _git(["add", "."], repo)
    _git(["commit", "-m", "init"], repo)
    monkeypatch.setattr(worktree.config, "PROJECT_ROOT", repo)
    monkeypatch.setattr(worktree.config, "STATE_DIR", tmp_path / "state")
    st = _State("abcdef12-task", repo)

    path = worktree.enterWorktree(st, "st-001")
    assert worktree.isIsolated(path) is True
    # Leave the edit UNCOMMITTED (as a real executor does): exitWorktree must commit it before
    # merging, otherwise the zero-commit branch merges nothing and `remove --force` deletes it.
    (Path(path) / "new.txt").write_text("x", encoding="utf-8")
    worktree.exitWorktree(path, merge=True)
    assert (repo / "new.txt").exists()       # committed in-worktree, then merged back into main


@pytest.mark.skipif(not _has_git(), reason="git not available")
def test_merge_conflict_aborts_not_left_mid_merge(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-b", "main"], repo)
    _git(["config", "user.email", "t@t"], repo)
    _git(["config", "user.name", "t"], repo)
    (repo / "f.txt").write_text("base\n", encoding="utf-8")
    _git(["add", "."], repo)
    _git(["commit", "-m", "init"], repo)
    monkeypatch.setattr(worktree.config, "PROJECT_ROOT", repo)
    monkeypatch.setattr(worktree.config, "STATE_DIR", tmp_path / "state")
    st = _State("abcdef12-task", repo)

    path = worktree.enterWorktree(st, "st-001")
    # Worktree edits f.txt one way (uncommitted); main edits the SAME line another way + commits.
    (Path(path) / "f.txt").write_text("worktree version\n", encoding="utf-8")
    (repo / "f.txt").write_text("main version\n", encoding="utf-8")
    _git(["add", "."], repo)
    _git(["commit", "-m", "main diverges"], repo)

    worktree.exitWorktree(path, merge=True)   # merge conflicts -> must abort, never strand MERGING

    import subprocess as _sp
    r = _sp.run(["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"],
                cwd=str(repo), capture_output=True, text=True)
    assert r.returncode != 0 and not r.stdout.strip()   # repo is NOT left mid-merge


def test_enter_failopen_returns_shared(tmp_path, monkeypatch):
    # Point PROJECT_ROOT at a non-git dir -> git errors -> fall back to the shared work_dir.
    monkeypatch.setattr(worktree.config, "PROJECT_ROOT", tmp_path / "nope")
    monkeypatch.setattr(worktree.config, "STATE_DIR", tmp_path / "state")
    st = _State("t", tmp_path / "shared")
    (tmp_path / "shared").mkdir()
    path = worktree.enterWorktree(st, "st-001")
    assert path == str(tmp_path / "shared")  # degrades to today's shared-tree behavior
    assert worktree.isIsolated(path) is False


def test_gc_refuses_paths_outside_sc_worktrees(tmp_path, monkeypatch):
    monkeypatch.setattr(worktree.config, "STATE_DIR", tmp_path / "state")
    outside = tmp_path / "important"
    outside.mkdir()
    worktree.removeWorktree(str(outside))    # must refuse: not under state/.sc-worktrees/
    assert outside.exists()


from pathlib import Path  # noqa: E402  (kept after tests for readability)
