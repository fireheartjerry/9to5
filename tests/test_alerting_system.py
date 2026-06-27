"""Acceptance entry point alias for the active alerting system.

This module exists so the original acceptance command continues to work:
  python C:/9to5/tests/test_alerting_system.py

All tests live in the two canonical modules below. Run either entry point:
  python C:/9to5/tests/test_active_alerting.py   (primary / preferred)
  python C:/9to5/tests/test_alerting_system.py   (alias — identical coverage)

Delegates to:
  * tests.test_active_alerting  — alerter unit + loop lifecycle tests
  * tests.test_event_alerting   — proactive real-time detection + integration
"""
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import tests.test_active_alerting as _active
import tests.test_event_alerting as _event

if __name__ == "__main__":
    _loader = unittest.TestLoader()
    _suite = unittest.TestSuite()
    _suite.addTests(_loader.loadTestsFromModule(_active))
    _suite.addTests(_loader.loadTestsFromModule(_event))
    _result = unittest.TextTestRunner(verbosity=2).run(_suite)
    sys.exit(0 if _result.wasSuccessful() else 1)
