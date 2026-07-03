"""Tests for PR gate and staging behavior in platform_core.orchestration.github.

Also covers the CLAUDE.md-restore idiom that createPullRequest's staging step relies on:
a non-self-ref PR must NOT commit 9to5's living CLAUDE.md over the user's tracked one.
After `git add -A` stages 9to5's modified CLAUDE.md, only `git checkout HEAD -- CLAUDE.md`
restores the user's committed version (both index + working tree); the bare
`git checkout -- CLAUDE.md` restores from the index, which already holds 9to5's version --
a no-op that leaks into the commit."""
from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from platform_core.orchestration import github


def _cp(returncode: int = 0, stdout: str = "", stderr: str = ""):
    return mock.Mock(returncode=returncode, stdout=stdout, stderr=stderr)


def _state():
    state = mock.MagicMock()
    state.task_id = "abcdef12-0000"
    state.meta = {"goal_raw": "ship focused change", "is_self_referential": True}
    return state


class TestPrePrSuiteGate(unittest.TestCase):
    def test_self_ref_gate_runs_repo_map_before_checks_and_fast_lane(self):
        passed = _cp(stdout="ok")
        with mock.patch("platform_core.orchestration.github.subprocess.run", return_value=passed) as run:
            ok, _ = github._prePrSuiteGate(_state(), "C:\\9to5")
        self.assertTrue(ok)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[0][1:], ["tools\\repo_map.py"])
        self.assertEqual(commands[1][1:], ["tools\\repo_map.py", "--check"])
        self.assertEqual(commands[2][1:], ["validate_workflows.py"])
        self.assertEqual(commands[3][1:4], ["-m", "pytest", "-m"])
        self.assertIn("not slow", commands[3])

    def test_self_ref_gate_blocks_on_first_failure(self):
        failed = _cp(returncode=1, stdout="repo map stale")
        with mock.patch("platform_core.orchestration.github.subprocess.run", return_value=failed) as run:
            ok, detail = github._prePrSuiteGate(_state(), "C:\\9to5")
        self.assertFalse(ok)
        self.assertIn("repo map stale", detail)
        self.assertEqual(run.call_count, 1)


class TestCreatePullRequestStaging(unittest.TestCase):
    def test_staging_excludes_scratch_and_python_cache_files(self):
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):  # noqa: ANN001
            calls.append(cmd)
            if cmd[:2] == ["git", "rev-parse"]:
                return _cp(stdout="true\n")
            if cmd[:3] == ["git", "remote", "get-url"]:
                return _cp(stdout="https://github.com/acme/repo.git\n")
            if cmd[:2] == ["git", "ls-files"]:
                return _cp(returncode=1)
            if cmd[:2] == ["git", "commit"]:
                return _cp(stdout="committed")
            if cmd[:2] == ["git", "push"]:
                return _cp()
            if cmd[:3] == ["gh", "pr", "create"]:
                return _cp(stdout="https://github.com/acme/repo/pull/1\n")
            return _cp()

        with mock.patch("platform_core.orchestration.github.subprocess.run", side_effect=fake_run):
            result = github.createPullRequest(_state(), "C:\\9to5")

        self.assertTrue(result["ok"])
        add_cmd = next(cmd for cmd in calls if cmd[:3] == ["git", "add", "-A"])
        self.assertIn(":(exclude).sc-ctx", add_cmd)
        self.assertIn(":(exclude)**/__pycache__/**", add_cmd)
        self.assertIn(":(exclude)**/*.pyc", add_cmd)

    def test_missing_origin_reports_specific_reason(self):
        def fake_run(cmd, **kwargs):  # noqa: ANN001
            if cmd[:2] == ["git", "rev-parse"]:
                return _cp(stdout="true\n")
            if cmd[:3] == ["git", "remote", "get-url"]:
                return _cp(returncode=2, stderr="No such remote")
            return _cp()

        with mock.patch("platform_core.orchestration.github.subprocess.run", side_effect=fake_run):
            result = github.createPullRequest(_state(), "C:\\repo")

        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "no origin remote configured")

    def test_missing_gh_reports_specific_reason_before_checkout(self):
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):  # noqa: ANN001
            calls.append(cmd)
            if cmd[:2] == ["git", "rev-parse"]:
                return _cp(stdout="true\n")
            if cmd[:3] == ["git", "remote", "get-url"]:
                return _cp(stdout="https://github.com/acme/repo.git\n")
            return _cp()

        with mock.patch("platform_core.orchestration.github.subprocess.run", side_effect=fake_run), \
                mock.patch("platform_core.orchestration.github.shutil.which", return_value=None):
            result = github.createPullRequest(_state(), "C:\\repo")

        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "GitHub CLI not found on PATH")
        self.assertFalse(any(cmd[:3] == ["git", "checkout", "-B"] for cmd in calls))

    def test_commit_failure_reports_specific_reason(self):
        def fake_run(cmd, **kwargs):  # noqa: ANN001
            if cmd[:2] == ["git", "rev-parse"]:
                return _cp(stdout="true\n")
            if cmd[:3] == ["git", "remote", "get-url"]:
                return _cp(stdout="https://github.com/acme/repo.git\n")
            if cmd[:2] == ["git", "ls-files"]:
                return _cp(returncode=1)
            if cmd[:2] == ["git", "commit"]:
                return _cp(returncode=128, stderr="author identity unknown")
            return _cp()

        with mock.patch("platform_core.orchestration.github.subprocess.run", side_effect=fake_run), \
                mock.patch("platform_core.orchestration.github.shutil.which", return_value="gh"):
            result = github.createPullRequest(_state(), "C:\\repo")

        self.assertTrue(result["skipped"])
        self.assertIn("git commit failed", result["reason"])
        self.assertIn("author identity", result["reason"])

    def test_external_local_repo_pushes_branch_and_creates_pr(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            origin = root / "origin.git"
            work = root / "work"
            subprocess.run(["git", "init", "--bare", str(origin)], check=True,
                           capture_output=True, text=True)
            subprocess.run(["git", "init", str(work)], check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "bot@example.com"], cwd=work, check=True)
            subprocess.run(["git", "config", "user.name", "9TO5"], cwd=work, check=True)
            subprocess.run(["git", "remote", "add", "origin", str(origin)], cwd=work, check=True)
            (work / "app.py").write_text("print('hello')\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=work, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=work, check=True,
                           capture_output=True, text=True)
            subprocess.run(["git", "push", "-u", "origin", "HEAD:main"], cwd=work, check=True,
                           capture_output=True, text=True)

            (work / "feature.py").write_text("VALUE = 42\n", encoding="utf-8")
            state = _state()
            state.meta["is_self_referential"] = False

            real_run = subprocess.run

            def fake_run(cmd, **kwargs):  # noqa: ANN001
                if cmd[:3] == ["gh", "pr", "create"]:
                    return _cp(stdout="https://github.com/acme/repo/pull/1\n")
                return real_run(cmd, **kwargs)

            with mock.patch("platform_core.orchestration.github.subprocess.run", side_effect=fake_run), \
                    mock.patch("platform_core.orchestration.github.shutil.which", return_value="gh"):
                result = github.createPullRequest(state, str(work))

            self.assertTrue(result["ok"])
            self.assertEqual(result["url"], "https://github.com/acme/repo/pull/1")
            head = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=work,
                                  check=True, capture_output=True, text=True).stdout.strip()
            self.assertEqual(head, "9to5/abcdef12")


# ---------------------------------------------------------------------------
# CLAUDE.md restore idiom (raw git behavior demonstration, no mocking): proves the
# fix github.createPullRequest relies on (git checkout HEAD -- CLAUDE.md) and locks
# the bug it replaced (bare git checkout -- CLAUDE.md, which leaks 9to5's version).
# ---------------------------------------------------------------------------

def _git(d, *a):
    return subprocess.run(["git", *a], cwd=d, capture_output=True, text=True)


def _forceRmtree(path):
    def _onerror(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:  # noqa: BLE001
            pass
    import shutil
    shutil.rmtree(path, onerror=_onerror)


class TestClaudeMdRestore(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        d = str(self.dir)
        _git(d, "init", "-q")
        _git(d, "config", "user.email", "t@t.t")
        _git(d, "config", "user.name", "t")
        (self.dir / "CLAUDE.md").write_text("USER OWN CLAUDE\n", encoding="utf-8")
        _git(d, "add", "-A")
        _git(d, "commit", "-qm", "user")

    def tearDown(self):
        _forceRmtree(self.dir)

    def test_checkout_head_restores_user_version_after_add(self):
        d = str(self.dir)
        # 9to5 overwrites CLAUDE.md, then the PR path stages everything
        (self.dir / "CLAUDE.md").write_text("9TO5 LIVING CLAUDE (leak)\n", encoding="utf-8")
        _git(d, "add", "-A")
        # the FIX: restore from HEAD (both index + working tree)
        _git(d, "checkout", "HEAD", "--", "CLAUDE.md")
        # working tree restored
        self.assertEqual((self.dir / "CLAUDE.md").read_text(encoding="utf-8"), "USER OWN CLAUDE\n")
        # and the STAGED blob is the user's version (so a commit won't leak 9to5's)
        staged = _git(d, "show", ":CLAUDE.md").stdout
        self.assertIn("USER OWN CLAUDE", staged)
        self.assertNotIn("leak", staged)

    def test_bare_checkout_would_leak_demonstrates_bug(self):
        d = str(self.dir)
        (self.dir / "CLAUDE.md").write_text("9TO5 LIVING CLAUDE (leak)\n", encoding="utf-8")
        _git(d, "add", "-A")
        _git(d, "checkout", "--", "CLAUDE.md")   # the OLD (buggy) restore: from the index
        # the staged blob is STILL 9to5's -- proving the old idiom leaked it
        self.assertIn("leak", _git(d, "show", ":CLAUDE.md").stdout)
