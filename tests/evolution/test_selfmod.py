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
        mock.patch.object(
            config, "CORE_PROTECTED_FILES", ("orchestrator.py", "main.py", "config.py", "agents/hooks.py")
        ).start()
        mock.patch.object(config, "SELFMOD_ALLOW_CORE", True).start()

    def tearDown(self):
        mock.patch.stopall()
        _forceRmtree(self.dir)

    def test_detects_core_change(self):
        (self.dir / "orchestrator.py").write_text("CHANGED\n", encoding="utf-8")
        (self.dir / "other.py").write_text("y\n", encoding="utf-8")
        self.assertEqual(selfmod.core_files_changed(str(self.dir)), ["orchestrator.py"])

    def test_gate_noop_without_core_change(self):
        out = selfmod.safety_gate(str(self.dir), is_self_referential=True, test_runner=lambda d: (True, ""))
        self.assertFalse(out["ran"])
        self.assertEqual(out["reason"], "no_core_changes")

    def test_gate_passes_keeps_changes(self):
        (self.dir / "orchestrator.py").write_text("IMPROVED\n", encoding="utf-8")
        out = selfmod.safety_gate(
            str(self.dir), is_self_referential=True, test_runner=lambda d: (True, "passed", "OK")
        )
        self.assertTrue(out["passed"])
        self.assertEqual((self.dir / "orchestrator.py").read_text(), "IMPROVED\n")  # kept

    def test_gate_fails_reverts_core(self):
        # Suite fails WITH the change but PASSES on the clean baseline => the change broke it => revert.
        (self.dir / "orchestrator.py").write_text("BROKEN\n", encoding="utf-8")
        runner = mock.Mock(
            side_effect=[(False, "failed", "FAILED (errors=3)"), (True, "passed", "baseline OK")]
        )
        out = selfmod.safety_gate(str(self.dir), is_self_referential=True, test_runner=runner)
        self.assertFalse(out["passed"])
        self.assertTrue(out["reverted"])
        self.assertEqual((self.dir / "orchestrator.py").read_text(), "ORIGINAL\n")  # reverted!

    def test_gate_keeps_change_when_baseline_also_fails(self):
        # Suite fails WITH the change AND genuinely FAILS (not times out) on the clean baseline =>
        # failure is pre-existing/flaky, NOT caused by the change => KEEP the improvement (don't
        # throw away good work). This is the ONLY case where "keep despite double failure" applies:
        # both runs must be genuine FAILED results, never a timeout on either side.
        (self.dir / "orchestrator.py").write_text("IMPROVED\n", encoding="utf-8")
        runner = mock.Mock(
            side_effect=[(False, "failed", "flaky fail"), (False, "failed", "baseline also red")]
        )
        out = selfmod.safety_gate(str(self.dir), is_self_referential=True, test_runner=runner)
        self.assertFalse(out["passed"])
        self.assertFalse(out["reverted"])
        self.assertTrue(out.get("kept_despite_failure"))
        self.assertEqual((self.dir / "orchestrator.py").read_text(), "IMPROVED\n")  # kept!

    def test_gate_first_run_timeout_always_reverts(self):
        # A first-run TIMEOUT must revert unconditionally -- a hang in core code is not something
        # we can reason causality about against a baseline, so the baseline runner must never even
        # be called, and the "keep despite double failure" path must never be entered.
        (self.dir / "orchestrator.py").write_text("HANGS FOREVER\n", encoding="utf-8")
        runner = mock.Mock(side_effect=[(False, "timeout", "test runner TIMEOUT after 1800s")])
        out = selfmod.safety_gate(str(self.dir), is_self_referential=True, test_runner=runner)
        self.assertFalse(out["passed"])
        self.assertTrue(out["reverted"])
        self.assertFalse(out.get("kept_despite_failure"))
        self.assertEqual(runner.call_count, 1)  # baseline never run
        self.assertEqual((self.dir / "orchestrator.py").read_text(), "ORIGINAL\n")  # reverted!

    def test_gate_baseline_timeout_reverts_not_kept(self):
        # First run genuinely FAILS, but the baseline run TIMES OUT (its own hang/env hiccup) --
        # two failures of different character must never collapse into "pre-existing, keep it."
        # Fail closed: revert.
        (self.dir / "orchestrator.py").write_text("IMPROVED\n", encoding="utf-8")
        runner = mock.Mock(
            side_effect=[
                (False, "failed", "assertion failure"),
                (False, "timeout", "baseline TIMEOUT after 1800s"),
            ]
        )
        out = selfmod.safety_gate(str(self.dir), is_self_referential=True, test_runner=runner)
        self.assertFalse(out["passed"])
        self.assertTrue(out["reverted"])
        self.assertFalse(out.get("kept_despite_failure"))
        self.assertEqual((self.dir / "orchestrator.py").read_text(), "ORIGINAL\n")  # reverted!

    def test_gate_disabled_when_flag_off(self):
        with mock.patch.object(config, "SELFMOD_ALLOW_CORE", False):
            (self.dir / "orchestrator.py").write_text("X\n", encoding="utf-8")
            out = selfmod.safety_gate(
                str(self.dir), is_self_referential=True, test_runner=lambda d: (True, "")
            )
        self.assertFalse(out["ran"])
        self.assertEqual(out["reason"], "not_enabled")

    def test_non_core_change_does_not_trigger_gate(self):
        (self.dir / "other.py").write_text("changed\n", encoding="utf-8")
        out = selfmod.safety_gate(
            str(self.dir), is_self_referential=True, test_runner=lambda d: (False, "would fail")
        )
        self.assertFalse(out["ran"])  # non-core changes never gated/reverted
        self.assertEqual((self.dir / "other.py").read_text(), "changed\n")
