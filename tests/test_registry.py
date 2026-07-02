"""Acceptance shim for st-009 — asserts the workflows-registry test suite shipped.

The exhaustive unit tests live in ``test_workflows_registry_validators.py`` and
``test_workflows_registry_load.py``. This shim previously ``from``-imported their ``Test*`` classes,
which made pytest collect all ~50 of them a SECOND time (once here, once in their own file). We now
import the module(s) under test and assert the expected test classes exist -- keeping the st-009
acceptance guarantee without double-collection.
"""
import importlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# The registry test suite lives in these modules (older layout: the single test_workflows_registry).
_SUITE_MODULES = (
    "tests.test_workflows_registry",
    "tests.test_workflows_registry_validators",
    "tests.test_workflows_registry_load",
)
_EXPECTED_CLASSES = (
    "TestLoadRegistry",
    "TestModuleLevelRegistry",
    "TestShippedDefinitions",
    "TestValidateAgent",
    "TestValidatePhase",
    "TestValidateWorkflowDefinition",
)


class TestSt009RegistrySuitePresent(unittest.TestCase):
    def test_registry_test_classes_exist(self):
        found: set[str] = set()
        for modname in _SUITE_MODULES:
            try:
                mod = importlib.import_module(modname)
            except ModuleNotFoundError:
                continue
            found |= {name for name in _EXPECTED_CLASSES if hasattr(mod, name)}
        missing = set(_EXPECTED_CLASSES) - found
        self.assertFalse(missing, f"st-009 registry test classes missing: {sorted(missing)}")


if __name__ == "__main__":
    unittest.main()
