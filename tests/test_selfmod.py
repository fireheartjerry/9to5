"""Tests for the safe self-modification gate (improve own core, never ship a broken build)."""
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
import selfmod


def _git(d, *a):
    return subprocess.run(["git", *a], cwd=d, capture_output=True, text=True)


def _forceRmtree(path) -> None:
    """Delete a temp dir robustly on Windows: git marks .git/objects/* read-only, so a plain
    unlink raises PermissionError (WinError 5). Clear the read-only bit and retry; tolerate a
    still-locked file (best-effort temp cleanup -- the OS reclaims %TEMP% regardless)."""
    def _onerror(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:  # noqa: BLE001 -- cleanup must never fail a passing test
            pass
    shutil.rmtree(path, onerror=_onerror)


class TestSelfMod(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        d = str(self.dir)
        _git(d, "init", "-q")
        _git(d, "config", "user.email", "t@t.t")
        _git(d, "config", "user.name", "t")
        (self.dir / "orchestrator.py").write_text("ORIGINAL\n", encoding="utf-8")
        (self.dir / "other.py").write_text("x\n", encoding="utf-8")
        _git(d, "add", "-A")
        _git(d, "commit", "-qm", "init")
        mock.patch.object(config, "CORE_PROTECTED_FILES",
                          ("orchestrator.py", "main.py", "config.py", "agents/hooks.py")).start()
        mock.patch.object(config, "SELFMOD_ALLOW_CORE", True).start()

    def tearDown(self):
        mock.patch.stopall()
        _forceRmtree(self.dir)

    def test_detects_core_change(self):
        (self.dir / "orchestrator.py").write_text("CHANGED\n", encoding="utf-8")
        (self.dir / "other.py").write_text("y\n", encoding="utf-8")
        self.assertEqual(selfmod.core_files_changed(str(self.dir)), ["orchestrator.py"])

    def test_gate_noop_without_core_change(self):
        out = selfmod.safety_gate(str(self.dir), is_self_referential=True,
                                  test_runner=lambda d: (True, ""))
        self.assertFalse(out["ran"])
        self.assertEqual(out["reason"], "no_core_changes")

    def test_gate_passes_keeps_changes(self):
        (self.dir / "orchestrator.py").write_text("IMPROVED\n", encoding="utf-8")
        out = selfmod.safety_gate(str(self.dir), is_self_referential=True,
                                  test_runner=lambda d: (True, "OK"))
        self.assertTrue(out["passed"])
        self.assertEqual((self.dir / "orchestrator.py").read_text(), "IMPROVED\n")  # kept

    def test_gate_fails_reverts_core(self):
        (self.dir / "orchestrator.py").write_text("BROKEN\n", encoding="utf-8")
        out = selfmod.safety_gate(str(self.dir), is_self_referential=True,
                                  test_runner=lambda d: (False, "FAILED (errors=3)"))
        self.assertFalse(out["passed"])
        self.assertTrue(out["reverted"])
        self.assertEqual((self.dir / "orchestrator.py").read_text(), "ORIGINAL\n")  # reverted!

    def test_gate_disabled_when_flag_off(self):
        with mock.patch.object(config, "SELFMOD_ALLOW_CORE", False):
            (self.dir / "orchestrator.py").write_text("X\n", encoding="utf-8")
            out = selfmod.safety_gate(str(self.dir), is_self_referential=True,
                                      test_runner=lambda d: (True, ""))
        self.assertFalse(out["ran"])
        self.assertEqual(out["reason"], "not_enabled")

    def test_non_core_change_does_not_trigger_gate(self):
        (self.dir / "other.py").write_text("changed\n", encoding="utf-8")
        out = selfmod.safety_gate(str(self.dir), is_self_referential=True,
                                  test_runner=lambda d: (False, "would fail"))
        self.assertFalse(out["ran"])           # non-core changes never gated/reverted
        self.assertEqual((self.dir / "other.py").read_text(), "changed\n")


if __name__ == "__main__":
    unittest.main()
