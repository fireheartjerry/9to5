"""Acceptance entry point: notification entry schema production readiness.

Delegates to test_notification_entry which contains the full test suite.
"""
import sys
import unittest
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

import test_notification_entry  # noqa: E402
