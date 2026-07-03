"""handleRunAbort must never propagate a persistence failure: a failing state save cannot
turn an operator ABORT into a 'crash' that recovery would auto-resume, and the operator
still gets notified (embed + dashboard attempted independently of persistence)."""
from unittest import mock

from platform_core.orchestration import run_phase_outcome as rpo
from state.task import TaskState, nowIso


class _Orch:
    def __init__(self):
        self.writeIndex = mock.Mock()


def _state():
    st = TaskState.create("g", 1.0)
    st.meta["started_at"] = nowIso()
    return st


def test_abort_with_raising_persistence_still_notifies_and_returns_aborted():
    st = _state()
    orch = _Orch()
    dashboard = mock.Mock()
    with mock.patch.object(TaskState, "setStatus", side_effect=OSError("disk full")), \
            mock.patch.object(rpo.discord, "sendEmbed") as embed:
        out = rpo.handleRunAbort(orch, st, RuntimeError("operator abort"), None, dashboard)
    assert out["status"] == "aborted"
    embed.assert_called_once()                      # notification still attempted
    dashboard.update.assert_called_once()


def test_abort_with_raising_embed_still_returns_aborted():
    st = _state()
    orch = _Orch()
    dashboard = mock.Mock()
    with mock.patch.object(rpo.discord, "sendEmbed", side_effect=OSError("discord down")):
        out = rpo.handleRunAbort(orch, st, KeyboardInterrupt(), None, dashboard)
    assert out["status"] == "aborted"
    assert out["reason"] == "ctrl-c"
    assert st.meta["status"] == "aborted"           # persistence path ran independently


def test_clean_abort_persists_and_notifies():
    st = _state()
    orch = _Orch()
    dashboard = mock.Mock()
    with mock.patch.object(rpo.discord, "sendEmbed") as embed:
        out = rpo.handleRunAbort(orch, st, RuntimeError("stop"), "http://x", dashboard)
    assert out["status"] == "aborted" and out["web_dashboard"] == "http://x"
    assert st.meta["status"] == "aborted"
    assert st.meta["blocked_reason"] == "stop"
    orch.writeIndex.assert_called_once()
    embed.assert_called_once()
