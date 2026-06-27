"""Acceptance shim for st-009 — delegates to test_workflows_registry."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.test_workflows_registry import (  # noqa: E402
    TestLoadRegistry,
    TestModuleLevelRegistry,
    TestShippedDefinitions,
    TestValidateAgent,
    TestValidatePhase,
    TestValidateWorkflowDefinition,
)

if __name__ == "__main__":
    unittest.main()
