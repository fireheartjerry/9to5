"""Orchestrator wiring for the multi-requirement fix.

Two structural root causes besides the weak verify itself:
  * ``_singleDeliverable`` treated 'N features in ONE file' as a single deliverable and force-
    collapsed the plan to 1 subtask -- actively preventing decomposition.
  * Nothing actually synthesized a compound verify, so the capability went unused.

These tests lock the wiring. They import ``orchestrator`` (pulls ollama/discord) and skip cleanly
where those aren't installed; run them in the project venv.
"""
from __future__ import annotations

import unittest

try:
    import orchestrator
    _IMPORT_ERR = None
except Exception as e:  # noqa: BLE001 -- heavy optional deps (ollama/discord)
    orchestrator = None
    _IMPORT_ERR = e

GOAL = ("improve notifications/webdash.py with (1) auto-refresh meta tag, "
        "(2) elapsed-time line, (3) per-subtask green/red color coding.")


@unittest.skipUnless(orchestrator is not None, f"orchestrator deps unavailable: {_IMPORT_ERR}")
class TestSingleDeliverableGate(unittest.TestCase):
    def setUp(self):
        # bypass __init__ (needs config/clients); the methods under test only use their argument
        self.orc = orchestrator.Orchestrator.__new__(orchestrator.Orchestrator)

    def test_enumerated_multi_requirement_is_not_single_deliverable(self):
        self.assertFalse(self.orc._singleDeliverable(GOAL),
                         "3 features in one file must NOT be collapsed to a single subtask")

    def test_plain_single_file_goal_is_single_deliverable(self):
        self.assertTrue(self.orc._singleDeliverable("improve webdash.py readability"))


@unittest.skipUnless(orchestrator is not None, f"orchestrator deps unavailable: {_IMPORT_ERR}")
class TestStrengthenPlanVerifies(unittest.TestCase):
    def setUp(self):
        self.orc = orchestrator.Orchestrator.__new__(orchestrator.Orchestrator)

    def test_collapsed_multi_req_subtask_gets_diff_grounded_target(self):
        # R10: the token-scan compound verify is gone; a covering subtask instead DECLARES
        # the resolved target file so the receipt pipeline fails it if the file never changed.
        subs = [{"title": "improve webdash", "description": GOAL, "layer": 3,
                 "verify": {"cmd": "python -c \"import os\"", "expect": "exit_zero"}}]
        out = self.orc._strengthenPlanVerifies(GOAL, subs)
        v = out[0]["verify"]
        targets = v.get("targets") or []
        self.assertTrue(targets, "covering subtask must declare a diff-grounded target")
        self.assertTrue(any("webdash.py" in t for t in targets),
                        "target must point at the resolved goal file")
        self.assertEqual(v["cmd"], 'python -c "import os"',
                         "the brain-authored verify cmd is preserved (targets are additive)")

    def test_single_deliverable_goal_left_untouched(self):
        original = {"cmd": "python C:/x.py", "expect": "exit_zero"}
        subs = [{"title": "x", "description": "tidy up webdash.py", "verify": dict(original)}]
        out = self.orc._strengthenPlanVerifies("tidy up webdash.py", subs)
        self.assertEqual(out[0]["verify"], original, "non-enumerated goal must keep the brain verify")
