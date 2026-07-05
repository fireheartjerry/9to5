import os
import tempfile
import unittest

from agents.planning.elaborator import path_verify


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
