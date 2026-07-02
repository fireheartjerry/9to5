"""Deployment review acceptance test for feat/frontier-discord-ui branch changes.

Run normally (unittest discovery) or with:
  python tests/test_deployment.py --verify-deployment-review
"""
import importlib
import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestDeploymentChanges(unittest.TestCase):
    """Verify all deliverables from the feat/frontier-discord-ui branch are in place."""

    # ------------------------------------------------------------------
    # agents/verifier.py — _normalizeWorkDir added
    # ------------------------------------------------------------------

    def test_normalize_work_dir_importable(self):
        mod = importlib.import_module("agents.verifier")
        self.assertTrue(
            callable(getattr(mod, "_normalizeWorkDir", None)),
            "_normalizeWorkDir must exist in agents.verifier",
        )

    def test_normalize_work_dir_absolute_repo_script(self):
        from agents.verifier import _normalizeWorkDir
        subtask_dir = str(REPO_ROOT / ".sc-ctx" / "st-033")
        cmd = f"python {REPO_ROOT / 'tests' / 'test_documentation.py'}"
        result = _normalizeWorkDir(cmd, subtask_dir)
        self.assertEqual(result, str(REPO_ROOT),
                         "_normalizeWorkDir must return repo root for absolute repo-path scripts")

    def test_normalize_work_dir_non_repo_script_unchanged(self):
        from agents.verifier import _normalizeWorkDir
        subtask_dir = str(REPO_ROOT / ".sc-ctx" / "st-033")
        result = _normalizeWorkDir("python -c \"print('hi')\"", subtask_dir)
        self.assertEqual(result, subtask_dir, "Non-.py commands must be left unchanged")

    # ------------------------------------------------------------------
    # .github/workflows/tests.yml — validate_workflows step present
    # ------------------------------------------------------------------

    def test_ci_workflow_has_validate_step(self):
        ci_file = REPO_ROOT / ".github" / "workflows" / "tests.yml"
        self.assertTrue(ci_file.exists(), "tests.yml must exist")
        text = ci_file.read_text(encoding="utf-8")
        self.assertIn("validate_workflows.py", text,
                      "CI workflow must include the validate_workflows.py step")

    # ------------------------------------------------------------------
    # validate_workflows.py — exists and is runnable
    # ------------------------------------------------------------------

    def test_validate_workflows_script_exists(self):
        script = REPO_ROOT / "validate_workflows.py"
        self.assertTrue(script.exists(), "validate_workflows.py must exist at repo root")

    # ------------------------------------------------------------------
    # docs/notification_system.md — /loop command documented
    # ------------------------------------------------------------------

    def test_notification_doc_loop_command(self):
        doc = REPO_ROOT / "docs" / "notification_system.md"
        self.assertTrue(doc.exists(), "docs/notification_system.md must exist")
        text = doc.read_text(encoding="utf-8")
        self.assertIn("/loop is a CC slash command", text)

    # ------------------------------------------------------------------
    # tests/test_dashboard.py — DASHBOARD_CV2 patch present
    # ------------------------------------------------------------------

    def test_dashboard_test_patches_cv2_flag(self):
        test_file = REPO_ROOT / "tests" / "test_dashboard.py"
        self.assertTrue(test_file.exists())
        text = test_file.read_text(encoding="utf-8")
        self.assertIn("DASHBOARD_CV2", text,
                      "test_dashboard.py must patch DASHBOARD_CV2 to isolate cv2 path")


def _runDeploymentReview() -> bool:
    """Run a focused suite and report pass/fail."""
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestDeploymentChanges)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()
