"""External project clone support for CLI and Nightclaw launches."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from notifications import work_launcher
from platform_core.cli.main_cli import _parseArgs
from platform_core.ops import external_project


class TestExternalProjectClone(unittest.TestCase):
    def test_parse_repo_url(self):
        args = _parseArgs(["--goal", "x", "--repo-url", "https://github.com/acme/repo.git"])
        self.assertEqual(args.repo_url, "https://github.com/acme/repo.git")

    def test_work_request_rejects_repo_url_with_work_dir(self):
        with tempfile.TemporaryDirectory() as d:
            errs = work_launcher.validate(
                work_launcher.WorkRequest(goal="x", work_dir=d, repo_url="https://x/repo.git"))
        self.assertTrue(any("mutually exclusive" in e for e in errs))

    def test_work_request_rejects_ref_without_repo_url(self):
        errs = work_launcher.validate(work_launcher.WorkRequest(goal="x", repo_ref="main"))
        self.assertTrue(any("repo_ref requires repo_url" in e for e in errs))

    def test_build_argv_passes_repo_url(self):
        argv = work_launcher.buildArgv(
            work_launcher.WorkRequest(goal="x", repo_url="https://github.com/acme/repo.git",
                                      repo_ref="main"))
        self.assertIn("--repo-url", argv)
        self.assertIn("https://github.com/acme/repo.git", argv)
        self.assertIn("--repo-ref", argv)
        self.assertIn("main", argv)

    def test_clone_repo_to_managed_workspace_from_local_bare_origin(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root / "source"
            origin = root / "origin.git"
            subprocess.run(["git", "init", str(source)], check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "bot@example.com"], cwd=source, check=True)
            subprocess.run(["git", "config", "user.name", "9TO5"], cwd=source, check=True)
            (source / "README.md").write_text("hello\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=source, check=True,
                           capture_output=True, text=True)
            subprocess.run(["git", "clone", "--bare", str(source), str(origin)], check=True,
                           capture_output=True, text=True)

            managed_root = root / "managed"
            with mock.patch.object(config, "PROJECT_ROOT", managed_root):
                clone = external_project.cloneRepo(str(origin))

            self.assertTrue((clone / "README.md").exists())
            self.assertTrue(str(clone).startswith(str(managed_root / "state" / "external-projects")))

    def test_clone_repo_checks_out_requested_branch(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root / "source"
            origin = root / "origin.git"
            subprocess.run(["git", "init", str(source)], check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "bot@example.com"], cwd=source, check=True)
            subprocess.run(["git", "config", "user.name", "9TO5"], cwd=source, check=True)
            (source / "README.md").write_text("main\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=source, check=True,
                           capture_output=True, text=True)
            subprocess.run(["git", "checkout", "-b", "feature"], cwd=source, check=True,
                           capture_output=True, text=True)
            (source / "README.md").write_text("feature\n", encoding="utf-8")
            subprocess.run(["git", "commit", "-am", "feature"], cwd=source, check=True,
                           capture_output=True, text=True)
            subprocess.run(["git", "clone", "--bare", str(source), str(origin)], check=True,
                           capture_output=True, text=True)

            managed_root = root / "managed"
            with mock.patch.object(config, "PROJECT_ROOT", managed_root):
                clone = external_project.cloneRepo(str(origin), "feature")

            branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=clone,
                                    check=True, capture_output=True, text=True).stdout.strip()
            self.assertEqual(branch, "feature")
            self.assertEqual((clone / "README.md").read_text(encoding="utf-8"), "feature\n")

    def test_failed_clone_cleans_managed_target(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            managed_root = root / "managed"
            with mock.patch.object(config, "PROJECT_ROOT", managed_root), \
                    mock.patch.object(external_project.uuid, "uuid4",
                                      return_value=mock.Mock(hex="deadbeefcafebabe")):
                with self.assertRaises(RuntimeError):
                    external_project.cloneRepo(str(root / "missing.git"))
            leftovers = list((managed_root / "state" / "external-projects").glob("*deadbeef*"))
            self.assertEqual(leftovers, [])

    def test_prepare_external_repo_mutates_request_to_work_dir(self):
        req = work_launcher.WorkRequest(goal="x", repo_url="https://github.com/acme/repo.git")
        with mock.patch("platform_core.ops.external_project.cloneRepo", return_value=Path("C:/tmp/repo")) as clone:
            work_launcher.prepareExternalRepo(req)
        clone.assert_called_once_with("https://github.com/acme/repo.git", None)
        self.assertEqual(req.work_dir, "C:\\tmp\\repo")
        self.assertIsNone(req.repo_url)

    def test_prepare_external_repo_passes_ref(self):
        req = work_launcher.WorkRequest(goal="x", repo_url="https://github.com/acme/repo.git",
                                       repo_ref="dev")
        with mock.patch("platform_core.ops.external_project.cloneRepo", return_value=Path("C:/tmp/repo")) as clone:
            work_launcher.prepareExternalRepo(req)
        clone.assert_called_once_with("https://github.com/acme/repo.git", "dev")
        self.assertIsNone(req.repo_ref)

    def test_clone_rejects_file_scheme(self):
        with self.assertRaises(ValueError):
            external_project.cloneRepo("file:///etc/passwd")

    def test_clone_rejects_git_scheme(self):
        with self.assertRaises(ValueError):
            external_project.cloneRepo("git://internal.example/repo.git")

    def test_clone_rejects_ssh_scheme(self):
        with self.assertRaises(ValueError):
            external_project.cloneRepo("ssh://git@internal.example/repo.git")

    def test_clone_rejects_remote_helper_syntax(self):
        # git's `ext::` transport runs an arbitrary helper PROGRAM -- this is a known
        # command-execution vector via a crafted "repo_url", not just SSRF.
        with self.assertRaises(ValueError):
            external_project.cloneRepo("ext::sh -c touch% /tmp/pwned")

    def test_clone_rejects_dash_prefixed_url(self):
        with self.assertRaises(ValueError):
            external_project.cloneRepo("--upload-pack=/bin/sh")

    def test_clone_rejects_dash_prefixed_ref(self):
        with self.assertRaises(ValueError):
            external_project.cloneRepo("https://github.com/acme/repo.git", "--upload-pack=/bin/sh")

    def test_clone_rejects_ref_with_shell_metacharacters(self):
        with self.assertRaises(ValueError):
            external_project.cloneRepo("https://github.com/acme/repo.git", "main; rm -rf /")

    def test_clone_accepts_https_url(self):
        # Doesn't actually reach the network -- a nonexistent host fails at git-clone time
        # (RuntimeError), which proves validation passed and execution proceeded past it.
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(config, "PROJECT_ROOT", Path(d)):
                with self.assertRaises(RuntimeError):
                    external_project.cloneRepo("https://127.0.0.1:1/definitely-not-a-repo.git")

    def test_launch_reply_shows_prepared_work_dir(self):
        req = work_launcher.WorkRequest(goal="x", repo_url="https://github.com/acme/repo.git")
        with tempfile.TemporaryDirectory() as d, \
                mock.patch("platform_core.ops.external_project.cloneRepo", return_value=Path(d)), \
                mock.patch.object(work_launcher, "activeRun", return_value=None), \
                mock.patch.object(work_launcher, "spawn", return_value=123), \
                mock.patch.object(work_launcher, "newestTaskSince", return_value="abcdef12"):
            out = work_launcher.launchOrError(req)
        self.assertIn("Working dir:", out)
        self.assertIn(str(Path(d).resolve()), out)


if __name__ == "__main__":
    unittest.main()
