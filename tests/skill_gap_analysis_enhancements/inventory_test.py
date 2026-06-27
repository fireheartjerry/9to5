#!/usr/bin/env python3
"""
tests/skill_gap_analysis_enhancements/inventory_test.py
Tests for Enhancement 3 (SKILLS_DIR.exists() guard) and Enhancement 4 (.py file exclusion).
"""
import importlib.util
import pathlib
import tempfile
import unittest
from unittest.mock import patch

_SRC = pathlib.Path("C:/9to5/workflows/skill-gap-analysis.py")
_spec = importlib.util.spec_from_file_location("_sga_wf_inventory", _SRC)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

loadSkillInventory = _mod.loadSkillInventory


class TestSkillsDirExistsGuard(unittest.TestCase):
    """Enhancement 3: early return when SKILLS_DIR does not exist."""

    def test_nonexistent_dir_returns_empty_dict(self):
        with patch.object(_mod, "SKILLS_DIR", pathlib.Path("/totally/nonexistent/xyz")):
            result = loadSkillInventory()
        self.assertEqual(result, {})

    def test_nonexistent_dir_does_not_raise(self):
        with patch.object(_mod, "SKILLS_DIR", pathlib.Path("/no/such/path/abc")):
            try:
                loadSkillInventory()
            except Exception as exc:
                self.fail(f"loadSkillInventory raised unexpectedly: {exc}")

    def test_existing_empty_dir_returns_empty_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(_mod, "SKILLS_DIR", pathlib.Path(tmp)):
                result = loadSkillInventory()
        self.assertEqual(result, {})

    def test_existing_dir_with_skills_returns_nonempty(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp)
            (p / "myskill.md").write_text("some content", encoding="utf-8")
            with patch.object(_mod, "SKILLS_DIR", p):
                result = loadSkillInventory()
        self.assertIn("myskill", result)


class TestPyFileExclusion(unittest.TestCase):
    """Enhancement 4: .py files are excluded from skill inventory (was previously only self-exclusion)."""

    def test_py_files_not_added(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp)
            (p / "runner.py").write_text("import sys", encoding="utf-8")
            (p / "helper.py").write_text("# helper", encoding="utf-8")
            with patch.object(_mod, "SKILLS_DIR", p):
                inv = loadSkillInventory()
        self.assertNotIn("runner", inv)
        self.assertNotIn("helper", inv)

    def test_md_files_still_included(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp)
            (p / "runner.py").write_text("# python", encoding="utf-8")
            (p / "debugging.md").write_text("trace inspect", encoding="utf-8")
            with patch.object(_mod, "SKILLS_DIR", p):
                inv = loadSkillInventory()
        self.assertIn("debugging", inv)
        self.assertNotIn("runner", inv)

    def test_dotfiles_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp)
            (p / ".hidden").write_text("secret", encoding="utf-8")
            (p / "visible.md").write_text("debug trace", encoding="utf-8")
            with patch.object(_mod, "SKILLS_DIR", p):
                inv = loadSkillInventory()
        self.assertIn("visible", inv)
        self.assertNotIn(".hidden", inv)

    def test_subdir_skills_included(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp)
            sub = p / "workflow-patterns"
            sub.mkdir()
            (sub / "skill.md").write_text("pipeline orchestration", encoding="utf-8")
            with patch.object(_mod, "SKILLS_DIR", p):
                inv = loadSkillInventory()
        self.assertIn("workflow-patterns", inv)

    def test_multiple_py_files_all_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp)
            for name in ["a", "b", "c", "score", "main"]:
                (p / f"{name}.py").write_text("pass", encoding="utf-8")
            (p / "myskill.md").write_text("some skill text", encoding="utf-8")
            with patch.object(_mod, "SKILLS_DIR", p):
                inv = loadSkillInventory()
        for name in ["a", "b", "c", "score", "main"]:
            self.assertNotIn(name, inv)
        self.assertIn("myskill", inv)

    def test_txt_files_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp)
            (p / "notes.txt").write_text("some notes", encoding="utf-8")
            (p / "skill.md").write_text("actual skill", encoding="utf-8")
            with patch.object(_mod, "SKILLS_DIR", p):
                inv = loadSkillInventory()
        self.assertNotIn("notes", inv)
        self.assertIn("skill", inv)


if __name__ == "__main__":
    unittest.main()
