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


if __name__ == "__main__":
    result = unittest.main(verbosity=2, exit=False)
    sys.exit(0 if result.result.wasSuccessful() else 1)
