import os
import tempfile
import unittest

from agents.planning.elaborator import grounding, path_verify


class TestPathVerify(unittest.TestCase):
    def test_real_path_stays_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "agents"))
            open(os.path.join(tmp, "agents", "core.py"), "w").close()
            result = path_verify.splitVerified(["agents/core.py"], tmp)
        self.assertEqual(result["allowed_paths"], ["agents/core.py"])
        self.assertEqual(result["unverified_paths"], [])

    def test_fake_path_moves_to_unverified(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = path_verify.splitVerified(["does/not/exist.py"], tmp)
        self.assertEqual(result["allowed_paths"], [])
        self.assertEqual(result["unverified_paths"], ["does/not/exist.py"])

    def test_glob_path_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "agents"))
            open(os.path.join(tmp, "agents", "a.py"), "w").close()
            result = path_verify.splitVerified(["agents/*.py"], tmp)
        self.assertEqual(result["allowed_paths"], ["agents/*.py"])


class TestVagueGoal(unittest.TestCase):
    def test_detects_vague_goal(self):
        self.assertTrue(grounding.isVagueGoal("improve everything"))
        self.assertTrue(grounding.isVagueGoal("fix bugs"))
        self.assertTrue(grounding.isVagueGoal("clean up the code"))

    def test_precise_goal_not_vague(self):
        self.assertFalse(grounding.isVagueGoal("add a --json flag to agents/planning/elaborator/core.py"))
        self.assertFalse(grounding.isVagueGoal("rename extractUniverse to extract_universe in core.py"))

    def test_bundle_names_real_modules_from_repo_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, ".repo-map.json"), "w", encoding="utf-8") as fh:
                fh.write('{"modules": [{"path": "agents/planning/elaborator/core.py"}]}')
            bundle = grounding.vagueGoalBundle(tmp)
        self.assertIn("agents/planning/elaborator/core.py", bundle)
