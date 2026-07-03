"""Tests for the preflight doctor."""
import unittest
from unittest import mock

import platform_core.ops.doctor as doctor


class TestDoctor(unittest.TestCase):
    def tearDown(self):
        mock.patch.stopall()

    def test_claude_cli_detected(self):
        with mock.patch("shutil.which", return_value="/usr/bin/claude"):
            c = doctor.check_claude_cli()
        self.assertTrue(c["ok"])
        self.assertTrue(c["hard"])

    def test_claude_cli_missing_is_hard_blocker(self):
        with mock.patch("shutil.which", return_value=None):
            c = doctor.check_claude_cli()
        self.assertFalse(c["ok"])
        self.assertTrue(c["hard"])
        self.assertIn("authenticate", c["fix"])

    def test_ollama_unreachable_is_hard_blocker(self):
        with mock.patch("ollama.Client", side_effect=RuntimeError("refused")):
            c = doctor.check_ollama()
        self.assertFalse(c["ok"])
        self.assertTrue(c["hard"])

    def test_run_aggregates_and_flags_blockers(self):
        with mock.patch.object(doctor, "check_ollama",
                               return_value=doctor._check("Ollama", False, hard=True)), \
             mock.patch.object(doctor, "check_claude_cli",
                               return_value=doctor._check("Claude", True, hard=True)), \
             mock.patch.object(doctor, "check_embedder",
                               return_value=doctor._check("Emb", False, hard=False)), \
             mock.patch.object(doctor, "check_git",
                               return_value=doctor._check("Git", True, hard=False)), \
             mock.patch.object(doctor, "check_gh",
                               return_value=doctor._check("gh", False, hard=False)), \
             mock.patch.object(doctor, "check_gpu",
                               return_value=doctor._check("GPU", False, hard=False)):
            rep = doctor.run()
        self.assertFalse(rep["ready"])               # one hard blocker (Ollama)
        self.assertEqual(len(rep["blockers"]), 1)
        text = doctor.render(rep)
        self.assertIn("NOT ready", text)

    def test_render_ready(self):
        rep = {"checks": [doctor._check("Ollama", True, hard=True, detail="ok")],
               "ready": True, "blockers": []}
        self.assertIn("Ready", doctor.render(rep))
