"""BUG-012: _resolveState() must not guess the wrong task via loadLatest() when no task is
pinned via env vars at all. In a concurrent/resumed session "the latest" task may not be the
one this hook's tool call actually belongs to, enforcing the wrong task's hard_boundaries."""
import os
from unittest import mock

from agents.hooks_selfmod import _resolveState


class _FakeState:
    pass


def test_no_env_vars_returns_none_without_calling_load_latest():
    with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("NINE_TO_FIVE_TASK_FILE", None)
        os.environ.pop("NINE_TO_FIVE_TASK_ID", None)
        with mock.patch("state.task.TaskState.loadLatest") as m:
            m.return_value = _FakeState()   # would be a WRONG-task guess if ever called
            state, explicit = _resolveState()
    m.assert_not_called()
    assert state is None
    assert explicit is False


def test_task_id_env_var_failure_still_falls_back_to_load_latest():
    # A real degraded case (env var WAS set but resolution failed) is not the same bug --
    # falling back here is a reasonable degrade, not a guess from nothing.
    with mock.patch.dict(os.environ, {"NINE_TO_FIVE_TASK_ID": "does-not-exist"}, clear=False):
        os.environ.pop("NINE_TO_FIVE_TASK_FILE", None)
        with mock.patch("state.task.TaskState.load", side_effect=RuntimeError("missing")), \
             mock.patch("state.task.TaskState.loadLatest") as m:
            fake = _FakeState()
            m.return_value = fake
            state, explicit = _resolveState()
    m.assert_called_once()
    assert state is fake
    assert explicit is False
