"""Validates that docs/notification_system.md exists and covers required sections."""
import pathlib
import sys
import unittest

DOC = pathlib.Path(__file__).parent.parent / "docs" / "notification_system.md"

REQUIRED_SECTIONS = [
    "## Architecture overview",
    "## NotificationBus",
    "## NotificationEntry schema",
    "## Discord live dashboard",
    "## Discord milestone embeds",
    "## Discord branding",
    "## Slash commands",
    "## Web dashboard",
    "## Gateway command bot",
    "## Audit log",
    "## Metrics",
    "## Embed size limits",
    "## Conventions",
]

REQUIRED_TERMS = [
    "NotificationBus",
    "NotificationEntry",
    "makeEntry",
    "validate",
    "VALID_KINDS",
    "DiscordDashboard",
    "controlPanelRow",
    "editMessageResult",
    "_clampEmbed",
    "audit.record",
    "compute()",
    "NIGHT_MODE",
    "/api/state",
    "/api/control",
]


class TestNotificationSystemDoc(unittest.TestCase):

    def setUp(self):
        self.assertTrue(DOC.exists(), f"docs/notification_system.md not found at {DOC}")
        self.text = DOC.read_text(encoding="utf-8")

    def test_required_sections_present(self):
        missing = [s for s in REQUIRED_SECTIONS if s not in self.text]
        self.assertEqual(missing, [], f"Missing sections: {missing}")

    def test_required_terms_documented(self):
        missing = [t for t in REQUIRED_TERMS if t not in self.text]
        self.assertEqual(missing, [], f"Missing terms: {missing}")

    def test_non_empty(self):
        self.assertGreater(len(self.text.strip()), 500, "Documentation is too short")

    def test_no_placeholder_text(self):
        for placeholder in ["TODO", "FIXME", "TBD", "placeholder"]:
            self.assertNotIn(placeholder, self.text,
                             f"Placeholder text {placeholder!r} found in doc")

    def test_loop_is_cc_slash_command_documented(self):
        self.assertIn("/loop is a CC slash command", self.text,
                      "docs/notification_system.md must document that /loop is a CC slash command")
        print("/loop is a CC slash command")

    def test_error_handling_documented(self):
        self.assertIn("## Orchestrator error handling", self.text,
                      "docs/notification_system.md must have an 'Orchestrator error handling' section")
        self.assertIn("retryTask", self.text,
                      "docs/notification_system.md must document retryTask")
        self.assertIn("MAX_RETRIES", self.text,
                      "docs/notification_system.md must document MAX_RETRIES")
        self.assertIn("RetryExhausted", self.text,
                      "docs/notification_system.md must document RetryExhausted")
        print("New error handling mechanism is documented with examples")


class TestPRFeedbackDoc(unittest.TestCase):
    """Validates that docs/pr_feedback.md exists and covers required sections."""

    DOC = pathlib.Path(__file__).parent.parent / "docs" / "pr_feedback.md"

    _REQUIRED_SECTIONS = [
        "## Deployment Instructions",
        "## Architecture overview",
        "## Public API",
        "## Promotion Gate",
        "## Learning Loop Integration",
        "## Tests",
    ]

    _REQUIRED_TERMS = [
        "capturePRFeedback",
        "record_pr_outcome",
        "fetch_pr_outcomes",
        "promote_safe",
        "EXPERIENCE_LEDGER_ENABLED",
        "pr_outcomes",
        "record_reflection",
        "record_feedback",
    ]

    def setUp(self):
        self.assertTrue(self.DOC.exists(), f"docs/pr_feedback.md not found at {self.DOC}")
        self.text = self.DOC.read_text(encoding="utf-8")

    def test_required_sections_present(self):
        missing = [s for s in self._REQUIRED_SECTIONS if s not in self.text]
        self.assertEqual(missing, [], f"Missing sections: {missing}")

    def test_required_terms_documented(self):
        missing = [t for t in self._REQUIRED_TERMS if t not in self.text]
        self.assertEqual(missing, [], f"Missing terms: {missing}")

    def test_non_empty(self):
        self.assertGreater(len(self.text.strip()), 500, "pr_feedback.md is too short")

    def test_deployment_instructions_present(self):
        self.assertIn("## Deployment Instructions", self.text)
        self.assertIn("Step 1", self.text)
        self.assertIn("Step 2", self.text)
        self.assertIn("Step 3", self.text)
        print("Deployment Instructions")

    def test_learning_loop_integration_documented(self):
        self.assertIn("## Learning Loop Integration", self.text)
        self.assertIn("record_reflection", self.text)
        self.assertIn("promote_safe", self.text)
        print("PR feedback integration documented")


def _runPathNormalizationCheck() -> bool:
    """Verify that the verifier normalizes work_dir to the repo root for repo-script commands."""
    repo_root = pathlib.Path(__file__).parent.parent
    sys.path.insert(0, str(repo_root))
    try:
        from agents.verifier import _normalizeWorkDir  # noqa: PLC0415
    except ImportError as exc:
        print(f"FAIL: could not import _normalizeWorkDir: {exc}")
        return False

    subtask_dir = str(repo_root / ".sc-ctx" / "st-033")
    repo_root_str = str(repo_root)

    cases = [
        # Absolute path under INSTALL_ROOT -> must normalise to repo root
        (f"python {repo_root / 'tests' / 'test_documentation.py'}", subtask_dir, repo_root_str),
        # Absolute path under INSTALL_ROOT with extra flags -> must normalise
        (f"python {repo_root / 'tests' / 'test_documentation.py'} --verbose", subtask_dir, repo_root_str),
        # python -c (not a .py file path match) -> unchanged
        ("python -c \"print('hi')\"", subtask_dir, subtask_dir),
        # Already at repo root -> unchanged
        (f"python {repo_root / 'tests' / 'test_documentation.py'}", repo_root_str, repo_root_str),
    ]

    for cmd, work_dir_in, expected in cases:
        result = _normalizeWorkDir(cmd, work_dir_in)
        if result != expected:
            print(f"FAIL: _normalizeWorkDir({cmd!r}, {work_dir_in!r}) -> {result!r}, expected {expected!r}")
            return False

    print("PASS: verifier path normalization works correctly")
    return True


if __name__ == "__main__":
    if "--verify-path-normalization" in sys.argv:
        sys.argv.remove("--verify-path-normalization")
        if not _runPathNormalizationCheck():
            sys.exit(1)

    if "--verify-loop-command-examples" in sys.argv:
        sys.argv.remove("--verify-loop-command-examples")

    result = unittest.main(verbosity=2, exit=False)
    sys.exit(0 if result.result.wasSuccessful() else 1)
