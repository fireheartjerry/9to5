"""Acceptance shim for st-009 — delegates to test_workflows_registry."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from tests.test_workflows_registry import (  # noqa: E402
        TestLoadRegistry,
        TestModuleLevelRegistry,
        TestShippedDefinitions,
        TestValidateAgent,
        TestValidatePhase,
        TestValidateWorkflowDefinition,
    )
except ModuleNotFoundError:
    # test_workflows_registry was split into _validators and _load
    from tests.test_workflows_registry_validators import (  # noqa: E402
        TestValidateAgent, TestValidatePhase, TestValidateWorkflowDefinition,
        TestLoadRegistry,
    )
    from tests.test_workflows_registry_load import (  # noqa: E402
        TestModuleLevelRegistry, TestShippedDefinitions,
    )

if __name__ == "__main__":
    unittest.main()
