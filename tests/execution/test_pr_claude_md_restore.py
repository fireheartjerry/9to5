"""A non-self-ref PR must NOT commit 9to5's living CLAUDE.md over the user's tracked one. After
`git add -A` stages 9to5's modified CLAUDE.md, only `git checkout HEAD -- CLAUDE.md` restores the
user's committed version (both index + working tree); the bare `git checkout -- CLAUDE.md` restores
from the index, which already holds 9to5's version -- a no-op that leaks into the commit."""
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


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
