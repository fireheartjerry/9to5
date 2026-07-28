"""Every retry owns a fresh execution context and tears it down on every exit path."""
import threading
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import config
from platform_core.execution import wiring
from platform_core.execution.environment import EnvHandle, ExecutionContext
from platform_core.orchestration.execute_mixin import OrchestratorExecuteMixin


class _Host(OrchestratorExecuteMixin):
    def __init__(self):
        self._state_lock = threading.Lock()

    def _execCwd(self, state, sid, work_dir):
        return work_dir


class _FakeDashboard:
    def update(self, *a, **k):
        pass


class _FakeState:
    def __init__(self):
        self.task_id = "task-retry"
        self.meta = {}
        self.subtasks = [{"subtask_id": "st-001", "status": "in_progress", "title": "do x"}]

    def getSubtask(self, sid):
        return next((s for s in self.subtasks if s["subtask_id"] == sid), None)

    def updateSubtask(self, sid, **fields):
        self.getSubtask(sid).update(fields)

    def addNotification(self, *a, **k):
        pass


class TestFinalizeAlwaysRuns(unittest.TestCase):
    def setUp(self):
        self.host = _Host()
        self.state = _FakeState()
        self.subtask = self.state.subtasks[0]
        self.handle = EnvHandle(work_dir="/repo", backend="local", meta={}, capabilities=None)

    def _context(self):
        environment = object()
        return ExecutionContext(
            landing_environment=environment,
            landing_handle=self.handle,
            execution_environment=environment,
            execution_handle=self.handle,
            runtime_resources=(),
            verification_environment=None,
            verification_handle=None,
            work_dir=self.handle.work_dir,
            read_only=False,
        )

    def test_finalize_runs_when_attempts_raise(self):
        finalize = mock.patch("platform_core.execution.wiring.finalizeQuietly")
        provision = mock.patch(
            "platform_core.execution.wiring.provisionForAttempt",
            return_value=self._context(),
        )
        with finalize as fin, provision, \
             mock.patch.object(config, "MAX_SUBTASK_ATTEMPTS", 1), \
             mock.patch.object(config, "SOLUTION_FORK_ENABLED", False), \
             mock.patch.object(self.host, "_runOneAttempt",
                               side_effect=RuntimeError("boom (stands in for AbortRun)")):
            with self.assertRaises(RuntimeError):
                self.host._executeSubtask(self.state, self.subtask, "arch doc", "/repo",
                                          bus=mock.Mock(), dashboard=_FakeDashboard(), position=0)
        fin.assert_called_once()

    def test_finalize_runs_on_normal_completion(self):
        finalize = mock.patch("platform_core.execution.wiring.finalizeQuietly")
        provision = mock.patch(
            "platform_core.execution.wiring.provisionForAttempt",
            return_value=self._context(),
        )
        bus = mock.Mock()
        bus.isAbort.return_value = False
        with finalize as fin, provision, \
             mock.patch.object(config, "MAX_SUBTASK_ATTEMPTS", 1), \
             mock.patch.object(config, "SOLUTION_FORK_ENABLED", False), \
             mock.patch.object(
                 self.host,
                 "_runOneAttempt",
                 return_value=(
                     {"prompt": "x"}, {"ok": True}, {"passed": True},
                     "combined", True, None, None,
                 ),
             ), \
             mock.patch.object(self.host, "_translateDiscord", create=True), \
             mock.patch.object(self.host, "_waitWhilePaused", create=True), \
             mock.patch.object(self.host, "_finalizeAttemptOutcome", return_value="done"):
            result = self.host._executeSubtask(self.state, self.subtask, "arch doc", "/repo",
                                               bus=bus, dashboard=_FakeDashboard(), position=0)
        self.assertEqual(result, "done")
        fin.assert_called_once()

    def test_retry_provisions_and_finalizes_fresh_context_per_attempt(self):
        """A rejected attempt's context is closed before a fresh retry is provisioned."""

        with tempfile.TemporaryDirectory(prefix="galaxy-retry-red-") as temp_dir:
            root = Path(temp_dir)
            canonical = root / "canonical"
            canonical.mkdir()

            def make_context(ordinal: int) -> ExecutionContext:
                checkout = root / f"attempt-{ordinal}"
                checkout.mkdir()
                lease = SimpleNamespace(
                    attempt_id=f"attempt-retry-{ordinal}",
                    transaction_id=f"tx-retry-{ordinal}",
                )
                environment = object()
                handle = EnvHandle(
                    work_dir=str(checkout),
                    backend="clone",
                    meta={
                        "attempt_id": lease.attempt_id,
                        "transaction_id": lease.transaction_id,
                    },
                    capabilities=None,
                    runtime_token=lease,
                )
                return ExecutionContext(
                    landing_environment=environment,
                    landing_handle=handle,
                    execution_environment=environment,
                    execution_handle=handle,
                    runtime_resources=(),
                    verification_environment=None,
                    verification_handle=None,
                    work_dir=str(checkout),
                    read_only=False,
                )

            contexts = [make_context(1), make_context(2)]
            context_iterator = iter(contexts)
            events: list[tuple[str, str]] = []
            seen_contexts: list[object] = []
            seen_work_dirs: list[str] = []
            inherited_sentinel: list[bool] = []

            def transaction_id_for(env_ctx) -> str:
                if type(env_ctx) is ExecutionContext:
                    return env_ctx.landing_handle.meta["transaction_id"]
                if isinstance(env_ctx, tuple) and len(env_ctx) == 2:
                    return env_ctx[1].meta["transaction_id"]
                return "missing-context"

            def run_one_attempt(
                state,
                subtask,
                architect_doc,
                exec_cwd,
                bus,
                dashboard,
                sid,
                verify_spec,
                failure_feedback,
                resume_session,
                attempt,
                env_ctx=None,
            ):
                del state, subtask, architect_doc, bus, dashboard, sid, verify_spec
                del failure_feedback, resume_session
                transaction_id = transaction_id_for(env_ctx)
                events.append(("execute", transaction_id))
                seen_contexts.append(env_ctx)
                seen_work_dirs.append(exec_cwd)
                sentinel = Path(exec_cwd) / "attempt-1-only.txt"
                inherited_sentinel.append(sentinel.exists())
                if attempt == 1:
                    sentinel.write_text("rejected attempt", encoding="utf-8")
                passed = attempt == 2
                return (
                    {"attempt": attempt},
                    {"ok": passed},
                    {"passed": passed},
                    f"attempt {attempt}",
                    passed,
                    None,
                    None if passed else "attempt 1 verification failed",
                )

            def provision_for_attempt(*args, **kwargs) -> ExecutionContext:
                del args, kwargs
                context = next(context_iterator)
                transaction_id = context.landing_handle.meta["transaction_id"]
                events.append(("provision", transaction_id))
                return context

            def legacy_provision(*args, **kwargs):
                del args, kwargs
                context = contexts[0]
                transaction_id = context.landing_handle.meta["transaction_id"]
                events.append(("legacy-provision", transaction_id))
                return (
                    context.landing_environment,
                    context.landing_handle,
                    (context.execution_environment, context.execution_handle),
                    context.work_dir,
                )

            def finalize(env, handle, state, subtask, sid, log):
                del env, state, subtask, sid, log
                events.append(("finalize", handle.meta["transaction_id"]))

            bus = mock.Mock()
            bus.isAbort.return_value = False
            with (
                mock.patch.object(config, "MAX_SUBTASK_ATTEMPTS", 2),
                mock.patch.object(config, "SOLUTION_FORK_ENABLED", False),
                mock.patch.object(
                    wiring,
                    "provisionForAttempt",
                    side_effect=provision_for_attempt,
                    create=True,
                ) as per_attempt_provision,
                mock.patch.object(
                    wiring,
                    "provisionForSubtask",
                    side_effect=legacy_provision,
                ) as legacy_provision_mock,
                mock.patch.object(wiring, "finalizeQuietly", side_effect=finalize) as finalizer,
                mock.patch.object(self.host, "_runOneAttempt", side_effect=run_one_attempt),
                mock.patch.object(self.host, "_translateDiscord", create=True),
                mock.patch.object(self.host, "_waitWhilePaused", create=True),
                mock.patch.object(self.host, "_finalizeAttemptOutcome", return_value="done"),
            ):
                result = self.host._executeSubtask(
                    self.state,
                    self.subtask,
                    "arch doc",
                    str(canonical),
                    bus=bus,
                    dashboard=_FakeDashboard(),
                    position=0,
                )

            transaction_ids = [
                context.landing_handle.meta["transaction_id"] for context in contexts
            ]
            attempt_ids = [
                context.landing_handle.meta["attempt_id"] for context in contexts
            ]
            expected_events = [
                ("provision", transaction_ids[0]),
                ("execute", transaction_ids[0]),
                ("finalize", transaction_ids[0]),
                ("provision", transaction_ids[1]),
                ("execute", transaction_ids[1]),
                ("finalize", transaction_ids[1]),
            ]
            self.maxDiff = None
            self.assertEqual(
                {
                    "result": result,
                    "legacy_provision_calls": legacy_provision_mock.call_count,
                    "per_attempt_provision_calls": per_attempt_provision.call_count,
                    "finalization_calls": finalizer.call_count,
                    "events": events,
                    "exact_contexts_seen": [
                        seen is expected for seen, expected in zip(seen_contexts, contexts)
                    ],
                    "work_dirs": seen_work_dirs,
                    "inherited_sentinel": inherited_sentinel,
                    "attempt_ids_distinct": len(set(attempt_ids)) == 2,
                    "transaction_ids_distinct": len(set(transaction_ids)) == 2,
                    "lease_identities_distinct": (
                        contexts[0].landing_handle.runtime_token
                        is not contexts[1].landing_handle.runtime_token
                    ),
                },
                {
                    "result": "done",
                    "legacy_provision_calls": 0,
                    "per_attempt_provision_calls": 2,
                    "finalization_calls": 2,
                    "events": expected_events,
                    "exact_contexts_seen": [True, True],
                    "work_dirs": [context.work_dir for context in contexts],
                    "inherited_sentinel": [False, False],
                    "attempt_ids_distinct": True,
                    "transaction_ids_distinct": True,
                    "lease_identities_distinct": True,
                },
            )
            legacy_provision_mock.assert_not_called()

