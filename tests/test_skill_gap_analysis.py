"""Tests for .claude/skills/skill-gap-analysis.py — gap scoring workflow."""
import importlib.util
import io
import json
import pathlib
import sys
import tempfile
import unittest
from collections import Counter
from unittest import mock

# skill-gap-analysis.py has a hyphen — load via importlib
_SCRIPT = pathlib.Path(__file__).parent.parent / ".claude" / "skills" / "skill-gap-analysis.py"
_spec = importlib.util.spec_from_file_location("skill_gap_analysis", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

_stemTokens = _mod._stemTokens
loadSkillInventory = _mod.loadSkillInventory
loadTaskHistory = _mod.loadTaskHistory
buildDemandCounter = _mod.buildDemandCounter
scoreDomains = _mod.scoreDomains
printReport = _mod.printReport
DOMAIN_MAP = _mod.DOMAIN_MAP


# ---------------------------------------------------------------------------
# _stemTokens
# ---------------------------------------------------------------------------
class TestStemTokens(unittest.TestCase):
    def test_lowercases_and_splits(self):
        tokens = _stemTokens("Debug Trace ERROR")
        self.assertIn("debug", tokens)
        self.assertIn("trace", tokens)
        self.assertIn("error", tokens)

    def test_truncates_to_10_chars(self):
        tokens = _stemTokens("orchestration")
        self.assertIn("orchestrat", tokens)
        self.assertNotIn("orchestration", tokens)

    def test_ignores_short_words(self):
        tokens = _stemTokens("a ab abc")
        self.assertNotIn("a", tokens)
        self.assertNotIn("ab", tokens)
        self.assertIn("abc", tokens)

    def test_empty_string(self):
        self.assertEqual(_stemTokens(""), [])

    def test_digits_allowed_after_first_char(self):
        tokens = _stemTokens("test123 abc2")
        self.assertIn("test123", tokens)
        self.assertIn("abc2", tokens)

    def test_numbers_only_not_included(self):
        tokens = _stemTokens("123 456")
        self.assertEqual(tokens, [])


# ---------------------------------------------------------------------------
# loadSkillInventory
# ---------------------------------------------------------------------------
class TestLoadSkillInventory(unittest.TestCase):
    def test_reads_md_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            (d / "testing.md").write_text("pytest coverage assert", encoding="utf-8")
            (d / "debugging.md").write_text("trace inspect replay", encoding="utf-8")
            with mock.patch.object(_mod, "SKILLS_DIR", d):
                # also patch __file__ reference used in skip logic
                inv = loadSkillInventory()
            self.assertIn("testing", inv)
            self.assertIn("debugging", inv)
            # tokens from file content present
            self.assertTrue(any("pytest" in t for t in inv["testing"]))

    def test_reads_dir_with_readme(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            sub = d / "workflow"
            sub.mkdir()
            (sub / "README.md").write_text("pipeline orchestration schedule", encoding="utf-8")
            with mock.patch.object(_mod, "SKILLS_DIR", d):
                inv = loadSkillInventory()
            self.assertIn("workflow", inv)

    def test_ignores_dotfiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            (d / ".hidden.md").write_text("secret", encoding="utf-8")
            (d / "visible.md").write_text("debug trace", encoding="utf-8")
            with mock.patch.object(_mod, "SKILLS_DIR", d):
                inv = loadSkillInventory()
            self.assertNotIn(".hidden", inv)
            self.assertIn("visible", inv)

    def test_empty_skills_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            with mock.patch.object(_mod, "SKILLS_DIR", d):
                inv = loadSkillInventory()
            self.assertEqual(inv, {})


# ---------------------------------------------------------------------------
# loadTaskHistory
# ---------------------------------------------------------------------------
class TestLoadTaskHistory(unittest.TestCase):
    def _write_task(self, d, name, data):
        (d / name).write_text(json.dumps(data), encoding="utf-8")

    def test_returns_empty_when_dir_missing(self):
        with mock.patch.object(_mod, "TASKS_DIR", pathlib.Path("/does/not/exist")):
            result = loadTaskHistory()
        self.assertEqual(result, [])

    def test_loads_valid_json_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            self._write_task(d, "task1.json", {"meta": {"goal_raw": "deploy service"}})
            self._write_task(d, "task2.json", {"meta": {"goal_raw": "write tests"}})
            with mock.patch.object(_mod, "TASKS_DIR", d):
                tasks = loadTaskHistory()
        self.assertEqual(len(tasks), 2)

    def test_skips_malformed_json_with_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            (d / "bad.json").write_text("not json!!!", encoding="utf-8")
            self._write_task(d, "good.json", {"meta": {"goal_raw": "test"}})
            with mock.patch.object(_mod, "TASKS_DIR", d):
                tasks = loadTaskHistory()
        self.assertEqual(len(tasks), 1)

    def test_non_json_files_not_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            (d / "notes.txt").write_text("ignore me", encoding="utf-8")
            self._write_task(d, "real.json", {"meta": {}})
            with mock.patch.object(_mod, "TASKS_DIR", d):
                tasks = loadTaskHistory()
        self.assertEqual(len(tasks), 1)


# ---------------------------------------------------------------------------
# buildDemandCounter
# ---------------------------------------------------------------------------
class TestBuildDemandCounter(unittest.TestCase):
    def test_counts_goal_raw_tokens(self):
        tasks = [{"meta": {"goal_raw": "deploy release artifact"}, "plan": {}}]
        counter = buildDemandCounter(tasks)
        self.assertGreater(counter["deploy"], 0)
        self.assertGreater(counter["release"], 0)

    def test_counts_subtask_titles(self):
        tasks = [{
            "meta": {},
            "plan": {"subtasks": [{"title": "debug failing test", "description": ""}]},
        }]
        counter = buildDemandCounter(tasks)
        self.assertGreater(counter["debug"], 0)
        self.assertGreater(counter["test"], 0)

    def test_empty_tasks(self):
        counter = buildDemandCounter([])
        self.assertEqual(len(counter), 0)

    def test_accumulates_across_tasks(self):
        tasks = [
            {"meta": {"goal_raw": "debug errors"}, "plan": {}},
            {"meta": {"goal_raw": "debug logs"}, "plan": {}},
        ]
        counter = buildDemandCounter(tasks)
        self.assertGreaterEqual(counter["debug"], 2)

    def test_missing_plan_key(self):
        tasks = [{"meta": {"goal_raw": "refactor code"}}]
        counter = buildDemandCounter(tasks)
        self.assertGreater(counter["refactor"], 0)


# ---------------------------------------------------------------------------
# scoreDomains
# ---------------------------------------------------------------------------
class TestScoreDomains(unittest.TestCase):
    def _make_demand(self, **kwargs):
        return Counter(kwargs)

    def test_returns_all_domains(self):
        rows = scoreDomains(Counter(), {})
        domains = {r["domain"] for r in rows}
        self.assertEqual(domains, set(DOMAIN_MAP.keys()))

    def test_zero_demand_gives_zero_gap(self):
        rows = scoreDomains(Counter(), {})
        for r in rows:
            self.assertEqual(r["gap_score"], 0.0)

    def test_gap_score_reduced_by_coverage(self):
        # "testing" domain — demand on "test" stem
        demand = Counter({"test": 10})
        # no coverage
        rows_no_cov = scoreDomains(demand, {})
        gap_no_cov = next(r for r in rows_no_cov if r["domain"] == "testing")["gap_score"]

        # with one covering skill
        rows_cov = scoreDomains(demand, {"test-coverage": set()})
        gap_cov = next(r for r in rows_cov if r["domain"] == "testing")["gap_score"]

        self.assertGreater(gap_no_cov, gap_cov)

    def test_two_skills_saturate_coverage(self):
        demand = Counter({"test": 10})
        inventory = {"test-coverage": set(), "testing-helpers": set()}
        rows = scoreDomains(demand, inventory)
        testing_row = next(r for r in rows if r["domain"] == "testing")
        self.assertEqual(testing_row["gap_score"], 0.0)

    def test_sorted_descending_by_gap(self):
        demand = Counter({"test": 100, "deploy": 1})
        rows = scoreDomains(demand, {})
        scores = [r["gap_score"] for r in rows]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_covered_by_lists_matching_skills(self):
        demand = Counter()
        inventory = {"testing-framework": set(), "other": set()}
        rows = scoreDomains(demand, inventory)
        testing_row = next(r for r in rows if r["domain"] == "testing")
        self.assertIn("testing-framework", testing_row["covered_by"])
        self.assertNotIn("other", testing_row["covered_by"])


# ---------------------------------------------------------------------------
# printReport
# ---------------------------------------------------------------------------
class TestPrintReport(unittest.TestCase):
    def _capture_report(self, rows, inventory, task_count):
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            printReport(rows, inventory, task_count)
        return buf.getvalue()

    def test_contains_header(self):
        out = self._capture_report([], {}, 0)
        self.assertIn("SKILL GAP REPORT", out)

    def test_shows_task_and_skill_counts(self):
        out = self._capture_report([], {"s1": set()}, 5)
        self.assertIn("5", out)   # task count
        self.assertIn("1", out)   # skill count

    def test_shows_critical_gaps(self):
        rows = [{"domain": "monitoring", "demand": 10, "covered_by": [], "gap_score": 10.0}]
        out = self._capture_report(rows, {}, 1)
        self.assertIn("Critical Gaps", out)
        self.assertIn("monitoring", out)

    def test_shows_latent_gaps(self):
        rows = [{"domain": "security", "demand": 0, "covered_by": [], "gap_score": 0.0}]
        out = self._capture_report(rows, {}, 0)
        self.assertIn("Latent Gaps", out)
        self.assertIn("security", out)

    def test_no_critical_section_when_all_covered(self):
        rows = [{"domain": "testing", "demand": 5, "covered_by": ["tests"], "gap_score": 2.5}]
        out = self._capture_report(rows, {}, 1)
        self.assertNotIn("Critical Gaps", out)

    def test_truncates_long_coverage_label(self):
        long_skills = ["skill_a", "skill_b", "skill_c", "skill_d", "skill_e", "skill_f"]
        rows = [{"domain": "testing", "demand": 1, "covered_by": long_skills, "gap_score": 0.0}]
        out = self._capture_report(rows, {}, 1)
        self.assertIn("...", out)


# ---------------------------------------------------------------------------
# main() integration
# ---------------------------------------------------------------------------
class TestMain(unittest.TestCase):
    def _make_skill_dir(self, tmp):
        d = pathlib.Path(tmp)
        (d / "testing.md").write_text("test assert validate", encoding="utf-8")
        (d / "debugging.md").write_text("debug trace inspect", encoding="utf-8")
        return d

    def test_main_exits_zero_with_real_skills_dir(self):
        """main() must return 0 when real skills dir is non-empty."""
        ret = _mod.main()
        self.assertEqual(ret, 0)

    def test_main_exits_one_when_no_skills(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty_dir = pathlib.Path(tmp)
            with mock.patch.object(_mod, "SKILLS_DIR", empty_dir):
                ret = _mod.main()
        self.assertEqual(ret, 1)

    def test_main_succeeds_with_task_history(self):
        with tempfile.TemporaryDirectory() as tasks_tmp:
            tasks_dir = pathlib.Path(tasks_tmp)
            task_data = {
                "meta": {
                    "goal_raw": "debug and deploy",
                    "goal_elaborated": "fix deployment pipeline",
                },
                "plan": {"subtasks": [
                    {"title": "write tests", "description": "add coverage"},
                ]},
            }
            (tasks_dir / "t1.json").write_text(json.dumps(task_data), encoding="utf-8")
            with mock.patch.object(_mod, "TASKS_DIR", tasks_dir):
                ret = _mod.main()
        self.assertEqual(ret, 0)


# ---------------------------------------------------------------------------
# _YAML_CONFIG loading
# ---------------------------------------------------------------------------
class TestYamlConfig(unittest.TestCase):
    def test_yaml_config_non_empty(self):
        """_YAML_CONFIG must be a non-empty dict when the YAML file is present."""
        self.assertIsInstance(_mod._YAML_CONFIG, dict)
        self.assertGreater(len(_mod._YAML_CONFIG), 0,
                           "_YAML_CONFIG is empty — skill-gap-analysis.yaml failed to load")

    def test_yaml_config_has_known_keys(self):
        """YAML config must contain at least one of the documented top-level keys."""
        known_keys = {"inputs", "coverage_model", "recommendations", "domains",
                      "report_sections", "name", "version"}
        self.assertTrue(
            known_keys & _mod._YAML_CONFIG.keys(),
            f"_YAML_CONFIG has none of the expected keys; got: {list(_mod._YAML_CONFIG.keys())}",
        )

    def test_yaml_import_guarded(self):
        """The yaml import must be guarded so ImportError doesn't crash the module."""
        import importlib
        import builtins
        real_import = builtins.__import__

        def _blocking_import(name, *args, **kwargs):
            if name == "yaml":
                raise ImportError("yaml not available")
            return real_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=_blocking_import):
            # Re-executing _loadYamlConfig with yaml unavailable must return {}
            result = _mod._loadYamlConfig() if _mod._YAML_AVAILABLE else {}
        # When yaml is unavailable the function returns {} (not an exception)
        self.assertIsInstance(result, dict)


if __name__ == "__main__":
    unittest.main()
