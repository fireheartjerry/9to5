"""Staging acceptance tests -- Deploy Changes to Staging Environment.

Validates that the updated error handling, workflow registry, and monitoring
tools are consistently functional before promotion to production.

Run:
    python C:/9to5/tests/test_staging_changes.py
    python -m pytest tests/test_staging_changes.py
"""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# 1. Error handling
# ---------------------------------------------------------------------------

class TestErrorHandlingImports(unittest.TestCase):
    def test_error_handling_imports(self):
        import platform_core.runtime.error_handling as error_handling
        self.assertEqual(error_handling.MAX_RETRIES, 3)
        self.assertIsNotNone(error_handling.retryTask)

    def test_enhanced_error_handling_re_exports(self):
        import platform_core.runtime.enhanced_error_handling as eeh
        self.assertEqual(eeh.MAX_RETRIES, 3)
        self.assertIsNotNone(eeh.retryTask)


class TestRetryTaskBehavior(unittest.TestCase):
    def test_succeeds_on_first_try(self):
        from platform_core.runtime.error_handling import retryTask
        result = retryTask(lambda: 42, delay=0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"], 42)
        self.assertEqual(result["attempts"], 1)

    def test_retries_up_to_max_then_raises(self):
        from platform_core.runtime.error_handling import retryTask, RetryExhausted, MAX_RETRIES
        calls = [0]

        def _always_fail():
            calls[0] += 1
            raise RuntimeError("boom")

        with self.assertRaises(RetryExhausted):
            retryTask(_always_fail, delay=0)
        self.assertEqual(calls[0], MAX_RETRIES)

    def test_retries_and_recovers(self):
        from platform_core.runtime.error_handling import retryTask
        calls = [0]

        def _fail_twice():
            calls[0] += 1
            if calls[0] < 3:
                raise ValueError("transient")
            return "ok"

        result = retryTask(_fail_twice, delay=0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"], "ok")
        self.assertEqual(result["attempts"], 3)

    def test_on_alert_callback_called_on_exhaustion(self):
        from platform_core.runtime.error_handling import retryTask
        alerted = []
        retryTask(
            lambda: (_ for _ in ()).throw(RuntimeError("x")),
            delay=0,
            on_alert=lambda msg, attempts: alerted.append((msg, attempts)),
        )
        self.assertEqual(len(alerted), 1)
        self.assertIn("RuntimeError", alerted[0][0])

    def test_no_sleep_after_final_attempt(self):
        """retryTask must not sleep after the last attempt."""
        from platform_core.runtime.error_handling import retryTask
        sleep_calls = []
        with mock.patch("platform_core.runtime.error_handling.time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            try:
                retryTask(lambda: (_ for _ in ()).throw(RuntimeError("x")), delay=0.5)
            except Exception:
                pass
        # With MAX_RETRIES=3, sleeps fire between attempts 1→2 and 2→3 only (2 sleeps).
        from platform_core.runtime.error_handling import MAX_RETRIES
        self.assertEqual(len(sleep_calls), MAX_RETRIES - 1)


# ---------------------------------------------------------------------------
# 2. Workflow registry
# ---------------------------------------------------------------------------

class TestWorkflowRegistryImports(unittest.TestCase):
    def test_registry_module_imports(self):
        from src.workflow_registry import WorkflowRegistry, REGISTRY
        self.assertIsInstance(REGISTRY, WorkflowRegistry)

    def test_workflow_resolver_imports(self):
        from agents.workflow_resolver import resolveWorkflowDefinition
        self.assertIsNotNone(resolveWorkflowDefinition)


class TestWorkflowRegistryCRUD(unittest.TestCase):
    def setUp(self):
        from src.workflow_registry import WorkflowRegistry
        self._reg = WorkflowRegistry.__new__(WorkflowRegistry)
        import threading
        self._reg._lock = threading.Lock()
        self._reg._store = {}
        self._reg._builtin = frozenset()

    def _wf(self, name: str = "staging-test") -> dict:
        return {
            "name": name,
            "phases": [
                {
                    "title": "Phase 1",
                    "parallel": False,
                    "agents": [{"label": "a", "effort": "default", "prompt": "do X"}],
                }
            ],
        }

    def test_add_and_get_workflow(self):
        self._reg.addWorkflow("staging-test", self._wf())
        result = self._reg.getWorkflow("staging-test")
        self.assertEqual(result["name"], "staging-test")

    def test_list_workflows(self):
        self._reg.addWorkflow("wf-a", self._wf("wf-a"))
        self._reg.addWorkflow("wf-b", self._wf("wf-b"))
        names = self._reg.listWorkflows()
        self.assertIn("wf-a", names)
        self.assertIn("wf-b", names)

    def test_remove_workflow(self):
        from src.workflow_registry import WorkflowNotFoundError
        self._reg.addWorkflow("wf-rm", self._wf("wf-rm"))
        self._reg.removeWorkflow("wf-rm")
        with self.assertRaises(WorkflowNotFoundError):
            self._reg.getWorkflow("wf-rm")

    def test_get_missing_raises(self):
        from src.workflow_registry import WorkflowNotFoundError
        with self.assertRaises(WorkflowNotFoundError):
            self._reg.getWorkflow("does-not-exist")

    def test_invalid_definition_raises(self):
        from src.workflow_registry import WorkflowValidationError
        # Unknown key in the root dict triggers validation failure.
        with self.assertRaises(WorkflowValidationError):
            self._reg.addWorkflow("bad", {"unknown_key": True})

    def test_execute_workflow_returns_prompt(self):
        self._reg.addWorkflow("exec-test", self._wf("exec-test"))
        out = self._reg.executeWorkflow("exec-test", context="staging")
        self.assertTrue(out["ok"])
        self.assertIn("Phase 1", out["prompt"])
        self.assertIn("staging", out["prompt"])


class TestWorkflowResolver(unittest.TestCase):
    def test_none_spec_returns_none(self):
        from agents.workflow_resolver import resolveWorkflowDefinition
        self.assertIsNone(resolveWorkflowDefinition(None))

    def test_empty_spec_returns_none(self):
        from agents.workflow_resolver import resolveWorkflowDefinition
        self.assertIsNone(resolveWorkflowDefinition({}))

    def test_inline_definition_resolves(self):
        from agents.workflow_resolver import resolveWorkflowDefinition
        spec = {
            "workflow_definition": {
                "name": "inline-wf",
                "phases": [
                    {"title": "P1", "agents": [{"label": "x", "effort": "default", "prompt": "y"}]}
                ],
            }
        }
        result = resolveWorkflowDefinition(spec)
        self.assertIsNotNone(result)
        self.assertIn("phases", result)


# ---------------------------------------------------------------------------
# 3. Monitoring tools
# ---------------------------------------------------------------------------

class TestMonitoringImports(unittest.TestCase):
    def test_monitoring_package_imports(self):
        import monitoring
        for fn in ["record_execution", "record_critical_event", "get_success_rate",
                   "get_avg_delay", "get_alerts", "get_critical_events", "reset"]:
            self.assertTrue(callable(getattr(monitoring, fn)), fn)

    def test_alerter_imports(self):
        import monitoring.alerter as alerter
        for fn in ["checkAndNotify", "startAlertLoop", "stopAlertLoop",
                   "getNotifiedKeys", "resetState"]:
            self.assertTrue(callable(getattr(alerter, fn)), fn)


class TestMonitoringTrackerThresholds(unittest.TestCase):
    def setUp(self):
        import monitoring
        monitoring.reset()

    def tearDown(self):
        import monitoring
        monitoring.reset()

    def test_success_rate_threshold_is_90_percent(self):
        from monitoring.tracker import SUCCESS_RATE_MIN
        self.assertAlmostEqual(SUCCESS_RATE_MIN, 0.90)

    def test_max_delay_threshold_is_5_minutes(self):
        from monitoring.tracker import MAX_DELAY_SECONDS
        self.assertAlmostEqual(MAX_DELAY_SECONDS, 300.0)

    def test_max_retries_threshold_is_3(self):
        from monitoring.tracker import MAX_RETRIES
        self.assertEqual(MAX_RETRIES, 3)

    def test_critical_detection_window_is_2_minutes(self):
        # Contract is 2 minutes (120s) per docs/spec/monitoring_check.py; the prior
        # 60s constant was the bug (B45) — the window must match the documented value.
        from monitoring.tracker import CRITICAL_DETECTION_WINDOW_SECS
        self.assertAlmostEqual(CRITICAL_DETECTION_WINDOW_SECS, 120.0)

    def test_healthy_executions_produce_no_alerts(self):
        import monitoring
        for _ in range(10):
            monitoring.record_execution("healthy-wf", True, 10.0, retries=0)
        self.assertEqual(monitoring.get_alerts(), [])

    def test_low_success_rate_triggers_alert(self):
        import monitoring
        for _ in range(5):
            monitoring.record_execution("failing-wf", False, 1.0)
        alerts = monitoring.get_alerts()
        types = [a["type"] for a in alerts]
        self.assertIn("low_success_rate", types)

    def test_high_delay_triggers_alert(self):
        import monitoring
        monitoring.record_execution("slow-wf", True, 400.0)
        alerts = monitoring.get_alerts()
        types = [a["type"] for a in alerts]
        self.assertIn("high_avg_delay", types)

    def test_max_retries_triggers_alert(self):
        import monitoring
        monitoring.record_execution("retry-wf", True, 1.0, retries=3)
        alerts = monitoring.get_alerts()
        types = [a["type"] for a in alerts]
        self.assertIn("max_retries_exceeded", types)

    def test_critical_event_late_detection_triggers_alert(self):
        import monitoring
        from monitoring.tracker import CRITICAL_DETECTION_WINDOW_SECS
        old_ts = time.time() - (CRITICAL_DETECTION_WINDOW_SECS + 30.0)
        monitoring.record_critical_event("evt-staging", "disk_full", occurred_at=old_ts)
        alerts = monitoring.get_alerts()
        types = [a["type"] for a in alerts]
        self.assertIn("critical_event_late_detection", types)

    def test_in_window_critical_event_no_alert(self):
        import monitoring
        monitoring.record_critical_event("evt-fast", "cpu_spike", occurred_at=time.time())
        alerts = monitoring.get_alerts()
        late_alerts = [a for a in alerts if a["type"] == "critical_event_late_detection"]
        self.assertEqual(late_alerts, [])


# ---------------------------------------------------------------------------
# 4. Staging validator gate
# ---------------------------------------------------------------------------

class TestStagingValidatorGate(unittest.TestCase):
    def test_staging_validator_passes(self):
        import platform_core.ops.staging_validator as staging_validator
        result = staging_validator.main(quiet=True)
        self.assertEqual(result, 0, "staging_validator reported gate failures")


if __name__ == "__main__":
    unittest.main()
