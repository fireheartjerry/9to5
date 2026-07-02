"""Aggregated runner for all notification-related test suites.

Loads every notification test module (flat tests/test_notification_*.py and
the tests/notification/ subdirectory) into a single suite and exits 0 only
when every test passes.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_TESTS_DIR = Path(__file__).resolve().parent

# Flat test modules (tests/test_notification_*.py)
_FLAT_MODULES = [
    "test_notification_bus",
    "test_notification_entry",
    "test_notification_system",
]

# Subdirectory modules (tests/notification/*.py)
_SUBDIR_MODULES = [
    "notification.test_bus",
    "notification.test_entry",
    "notification.test_system",
]


def buildSuite() -> unittest.TestSuite:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    sys.path.insert(0, str(_TESTS_DIR))

    for mod_name in _FLAT_MODULES:
        mod = __import__(mod_name)
        suite.addTests(loader.loadTestsFromModule(mod))

    for mod_name in _SUBDIR_MODULES:
        mod = __import__(mod_name, fromlist=[""])
        suite.addTests(loader.loadTestsFromModule(mod))

    return suite
