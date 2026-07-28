"""resume_session_id persists to subtask['session']; resumable subtasks seed attempt 1."""
import threading
from types import SimpleNamespace
from unittest import mock

import config
from platform_core.execution import wiring
from platform_core.execution.environment import (
    EnvHandle,
    ExecutionContext,
    ResolvedExecutionPolicy,
)
from platform_core.orchestration.execute_mixin import OrchestratorExecuteMixin
from state.task import TaskState


def test_set_resume_session_persists(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    st = TaskState.create("g", 1.0)
    st.addSubtask("A", "")
    st.setResumeSession("st-001", "sess-42")
    assert st.getSubtask("st-001")["session"]["resume_session_id"] == "sess-42"
    # Idempotent + preserves other session keys.
    st.updateSubtask("st-001", session={**st.getSubtask("st-001")["session"], "effort": "high"})
    st.setResumeSession("st-001", "sess-99")
    sess = st.getSubtask("st-001")["session"]
    assert sess["resume_session_id"] == "sess-99" and sess["effort"] == "high"


def test_seed_resume_context_keeps_text_but_rejects_unbound_provider_session(monkeypatch):
    monkeypatch.setattr(config, "STEP_RESUME_ENABLED", True)
    resume_block = "## Resume\n[x] bounded textual diagnostic"
    sub = {
        "subtask_id": "st-001",
        "session": {
            "resumable": True,
            "resume_block": resume_block,
            "resume_session_id": "sess-7",
            # No exact transaction/clone/capability/provider/spec binding proof.
        },
    }
    fb, resume = OrchestratorExecuteMixin._seedResumeContext(sub)
    assert fb == resume_block
    assert resume is None


def test_seed_resume_context_off_when_flag_disabled(monkeypatch):
    monkeypatch.setattr(config, "STEP_RESUME_ENABLED", False)
    sub = {"subtask_id": "st-001", "session": {"resumable": True, "resume_block": "x",
                                               "resume_session_id": "s"}}
    fb, resume = OrchestratorExecuteMixin._seedResumeContext(sub)
    assert fb is None and resume is None


def test_new_retry_transaction_drops_provider_session_but_keeps_failure_feedback(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(config, "STEP_RESUME_ENABLED", False)
    monkeypatch.setattr(config, "MAX_SUBTASK_ATTEMPTS", 2)
    state = TaskState.create("retry session boundary", 1.0)
    state.addSubtask("retry", "")
    subtask = state.getSubtask("st-001")

    def context(ordinal: int) -> ExecutionContext:
        work_dir = tmp_path / f"attempt-{ordinal}"
        work_dir.mkdir()
        lease = SimpleNamespace(
            attempt_id=f"attempt-{ordinal}",
            transaction_id=f"transaction-{ordinal}",
        )
        environment = object()
        handle = EnvHandle(
            work_dir=str(work_dir),
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
            work_dir=str(work_dir),
            read_only=False,
        )

    contexts = [context(1), context(2)]
    incoming = []
    failure_diagnostics = "verification failed at exact revision"

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
        env_ctx,
    ):
        del state, subtask, architect_doc, bus, dashboard, sid, verify_spec
        incoming.append((attempt, resume_session, failure_feedback, env_ctx, exec_cwd))
        passed = attempt == 2
        return (
            {"attempt": attempt},
            {"ok": passed},
            {"passed": passed},
            f"attempt {attempt}",
            passed,
            None if passed else "provider-session-attempt-1",
            None if passed else failure_diagnostics,
        )

    host = OrchestratorExecuteMixin()
    host._state_lock = threading.RLock()
    bus = mock.Mock()
    bus.isAbort.return_value = False
    policy = ResolvedExecutionPolicy("worktree", "local", "clone", False)
    with (
        mock.patch.object(wiring, "resolveExecutionPolicy", return_value=policy),
        mock.patch.object(wiring, "provisionForAttempt", side_effect=contexts) as provision,
        mock.patch.object(wiring, "finalizeAttemptContextQuietly") as finalize,
        mock.patch.object(host, "_runOneAttempt", side_effect=run_one_attempt),
        mock.patch.object(host, "_translateDiscord", create=True),
        mock.patch.object(host, "_waitWhilePaused", create=True),
    ):
        host._runAttemptLoop(
            state,
            subtask,
            "architect",
            str(tmp_path / "canonical"),
            bus,
            mock.Mock(),
            "st-001",
            None,
        )

    assert provision.call_count == 2
    assert finalize.call_count == 2
    assert [item[3] for item in incoming] == contexts
    assert [item[4] for item in incoming] == [context.work_dir for context in contexts]
    assert [(item[0], item[1], item[2]) for item in incoming] == [
        (1, None, None),
        (2, None, failure_diagnostics),
    ]
