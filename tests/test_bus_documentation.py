"""Validates that the NotificationBus error-handling docs cover KeyboardInterrupt and SystemExit."""
import pathlib
import sys
import unittest

DOC = pathlib.Path(__file__).parent.parent / "docs" / "notification_system.md"

REQUIRED_TERMS = [
    "KeyboardInterrupt",
    "SystemExit",
    "BaseException",
]


class TestBusDocumentation(unittest.TestCase):

    def setUp(self):
        self.assertTrue(DOC.exists(), f"docs/notification_system.md not found at {DOC}")
        self.text = DOC.read_text(encoding="utf-8")

    def test_error_handling_terms_present(self):
        missing = [t for t in REQUIRED_TERMS if t not in self.text]
        self.assertEqual(missing, [], f"Missing error-handling terms: {missing}")

    def test_error_handling_section_present(self):
        self.assertIn(
            "KeyboardInterrupt",
            self.text,
            "NotificationBus error-handling section must document KeyboardInterrupt",
        )
        self.assertIn(
            "SystemExit",
            self.text,
            "NotificationBus error-handling section must document SystemExit",
        )


if __name__ == "__main__":
    result = unittest.main(verbosity=2, exit=False)
    if result.result.wasSuccessful():
        print("Error handling updated for KeyboardInterrupt and SystemExit")
    sys.exit(0 if result.result.wasSuccessful() else 1)
