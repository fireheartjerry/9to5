#!/usr/bin/env python3
"""
tests/skill_gap_analysis_enhancements/loader_test.py
Tests for Enhancement 1 (_loadOneTask) and Enhancement 2 (ThreadPoolExecutor parallel loading).
"""
import importlib.util
import io
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

_SRC = pathlib.Path("C:/9to5/workflows/skill-gap-analysis.py")
_spec = importlib.util.spec_from_file_location("_sga_wf_loader", _SRC)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

_loadOneTask = _mod._loadOneTask
loadTaskHistory = _mod.loadTaskHistory


class TestLoadOneTask(unittest.TestCase):
    """Enhancement 1: _loadOneTask is a new isolated per-file helper."""

    def test_valid_json_returns_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "task.json"
            data = {"meta": {"goal_raw": "do something"}, "plan": {}}
            p.write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual(_loadOneTask(p), data)

    def test_invalid_json_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "bad.json"
            p.write_text("{not valid", encoding="utf-8")
            with patch("sys.stderr", new_callable=io.StringIO):
                self.assertIsNone(_loadOneTask(p))

    def test_empty_file_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "empty.json"
            p.write_text("", encoding="utf-8")
            with patch("sys.stderr", new_callable=io.StringIO):
                self.assertIsNone(_loadOneTask(p))

    def test_missing_file_returns_none(self):
        p = pathlib.Path("/no/such/file/task.json")
        with patch("sys.stderr", new_callable=io.StringIO):
            self.assertIsNone(_loadOneTask(p))

    def test_warn_emitted_to_stderr_on_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "bad.json"
            p.write_text("NOTJSON", encoding="utf-8")
            buf = io.StringIO()
            with patch("sys.stderr", buf):
                _loadOneTask(p)
        self.assertIn("warn", buf.getvalue().lower())

    def test_preserves_nested_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "task.json"
            data = {
                "meta": {"goal_raw": "build", "goal_elaborated": "build X"},
                "plan": {"subtasks": [{"title": "step1"}]},
            }
            p.write_text(json.dumps(data), encoding="utf-8")
            result = _loadOneTask(p)
        self.assertEqual(result["plan"]["subtasks"][0]["title"], "step1")

    def test_list_root_json_returns_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "task.json"
            p.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
            result = _loadOneTask(p)
        self.assertEqual(result, [1, 2, 3])


class TestParallelLoadTaskHistory(unittest.TestCase):
    """Enhancement 2: ThreadPoolExecutor must not drop or duplicate tasks."""

    def test_no_drops_with_many_files(self):
        count = 20
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            for i in range(count):
                (tp / f"t{i:04d}.json").write_text(
                    json.dumps({"meta": {"goal_raw": f"goal-{i}"}}), encoding="utf-8"
                )
            with patch.object(_mod, "TASKS_DIR", tp):
                result = loadTaskHistory()
        self.assertEqual(len(result), count)

    def test_no_duplicates(self):
        count = 12
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            for i in range(count):
                (tp / f"t{i:04d}.json").write_text(
                    json.dumps({"meta": {"goal_raw": f"unique-{i}"}}), encoding="utf-8"
                )
            with patch.object(_mod, "TASKS_DIR", tp):
                result = loadTaskHistory()
        goals = [r["meta"]["goal_raw"] for r in result]
        self.assertEqual(len(goals), len(set(goals)))

    def test_invalid_files_skipped_valid_returned(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            for i in range(5):
                (tp / f"good{i}.json").write_text(
                    json.dumps({"meta": {"goal_raw": f"g{i}"}}), encoding="utf-8"
                )
            (tp / "bad.json").write_text("NOT JSON", encoding="utf-8")
            with patch.object(_mod, "TASKS_DIR", tp):
                with patch("sys.stderr", new_callable=io.StringIO):
                    result = loadTaskHistory()
        self.assertEqual(len(result), 5)

    def test_empty_dir_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(_mod, "TASKS_DIR", pathlib.Path(tmp)):
                self.assertEqual(loadTaskHistory(), [])

    def test_all_invalid_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            for i in range(3):
                (tp / f"bad{i}.json").write_text("BAD", encoding="utf-8")
            with patch.object(_mod, "TASKS_DIR", tp):
                with patch("sys.stderr", new_callable=io.StringIO):
                    result = loadTaskHistory()
        self.assertEqual(result, [])

    def test_non_json_files_not_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            (tp / "notes.txt").write_text("text file", encoding="utf-8")
            (tp / "real.json").write_text(json.dumps({"meta": {}}), encoding="utf-8")
            with patch.object(_mod, "TASKS_DIR", tp):
                result = loadTaskHistory()
        self.assertEqual(len(result), 1)

    def test_missing_tasks_dir_returns_empty_list(self):
        with patch.object(_mod, "TASKS_DIR", pathlib.Path("/no/such/tasks/dir")):
            self.assertEqual(loadTaskHistory(), [])


if __name__ == "__main__":
    unittest.main()
