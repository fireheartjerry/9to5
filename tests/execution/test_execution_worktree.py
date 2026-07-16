"""WorktreeEnvironment lifecycle against a real temp git repo (offline, cross-platform).

ADAPTATION (Epic 1 brownfield): WorktreeEnvironment is a thin adapter over the landed
``platform_core/runtime/worktree.py`` (enterWorktree/exitWorktree/removeWorktree/isIsolated),
which key off ``config.PROJECT_ROOT`` / ``config.STATE_DIR``. The ``repo`` fixture redirects both
at those globals to the temp git repo so the REAL worktree module exercises the temp tree (never
the live 9TO5 repo). All provision/collect/teardown assertions are unchanged from the plan.
"""
import os
import shutil
import subprocess

import pytest

import config
from platform_core.execution.backends.worktree import WorktreeEnvironment
from platform_core.execution.environment import Capability

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                   check=True, timeout=20)


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    _git(["init", "-b", "main"], base)
    _git(["config", "user.email", "t@t.io"], base)
    _git(["config", "user.name", "t"], base)
    (base / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(["add", "-A"], base)
    _git(["commit", "-m", "seed"], base)
    # Redirect the landed worktree module's globals at the sandbox repo (offline + non-destructive).
    monkeypatch.setattr(config, "PROJECT_ROOT", str(base))
    monkeypatch.setattr(config, "STATE_DIR", str(base))
    return str(base)


class _TS:
    task_id = "abcd1234ef"
    meta = {"work_dir": None}


def test_healthcheck_true_when_git_present():
    assert WorktreeEnvironment().healthCheck() is True


def test_provision_creates_isolated_worktree_with_snapshot_cap(repo):
    env = WorktreeEnvironment()
    h = env.provision(task_state=_TS(), subtask={"subtask_id": "st-001"},
                      base_dir=repo, policy=None)
    assert os.path.isdir(h.work_dir)
    assert os.path.abspath(h.work_dir) != os.path.abspath(repo)   # isolated tree
    assert h.backend == "worktree"
    assert Capability.SNAPSHOT in h.capabilities
    assert h.meta["branch"].startswith("wt/")
    env.teardown(h)


def test_wraplauncher_is_identity_on_worktree_dir(repo):
    env = WorktreeEnvironment()
    h = env.provision(task_state=_TS(), subtask={"subtask_id": "st-002"},
                      base_dir=repo, policy=None)
    cmd = ["claude", "--print"]
    out_cmd, out_work = env.wrapLauncher(cmd, h)
    assert out_cmd == cmd                 # the process runs natively, just in another dir
    assert out_work == h.work_dir
    env.teardown(h)


def test_collect_merges_back_then_teardown_removes(repo):
    env = WorktreeEnvironment()
    h = env.provision(task_state=_TS(), subtask={"subtask_id": "st-003"},
                      base_dir=repo, policy=None)
    # the "executor" writes a new file inside the isolated worktree
    new_file = os.path.join(h.work_dir, "made_in_worktree.txt")
    with open(new_file, "w", encoding="utf-8") as fh:
        fh.write("hello from the worktree\n")
    summary = env.collectChanges(h, task_state=_TS(), subtask={"subtask_id": "st-003"})
    assert summary["merged"] is True
    # the edit is now in the base tree on the main branch
    assert os.path.isfile(os.path.join(repo, "made_in_worktree.txt"))
    env.teardown(h)
    assert not os.path.isdir(h.work_dir)   # worktree pruned


def test_collect_with_no_changes_is_clean(repo):
    env = WorktreeEnvironment()
    h = env.provision(task_state=_TS(), subtask={"subtask_id": "st-004"},
                      base_dir=repo, policy=None)
    summary = env.collectChanges(h, task_state=_TS(), subtask={"subtask_id": "st-004"})
    assert summary["backend"] == "worktree"
    assert summary.get("merged") in (True, False)   # nothing to merge is not a failure
    env.teardown(h)


def test_worktree_handle_requires_staged_canonical_landing(repo):
    env = WorktreeEnvironment()
    h = env.provision(task_state=_TS(), subtask={"subtask_id": "st-landing"},
                      base_dir=repo, policy=None)
    try:
        assert h.requires_canonical_landing is True
    finally:
        env.teardown(h)
