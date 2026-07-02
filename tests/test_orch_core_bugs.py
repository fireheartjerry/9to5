"""P1 ORCHESTRATOR-CORE bug regressions (mega-upgrade).

Covers:
  B1 llm_io.responseText   -- a _tap_brain telemetry failure must NEVER blank a valid completion.
  B2 run_loop._prepareSelfReferential -- a failing git checkout must NOT markSelfReferential.
  B4 run_loop_mixin._applyReplan       -- a non-string title must not crash (coerced to 'untitled').
  B5 brain_io._fitUserToCtx            -- system > window must trim the user (not return it whole).
  B6 control_mixin._worthGptReview     -- per-sid, lock-guarded dedup; commit only after success.
  B3 run_loop_mixin._handleParallelBatch (if feasible) -- a still-running future's worktree exit is
     DEFERRED until after the pool shuts down.
"""
from __future__ import annotations

import threading
import time
from unittest import mock


import config
import llm_io
from platform_core.orchestration import brain_io, run_loop
from platform_core.runtime.control import AbortRun


# --------------------------------------------------------------------------- B1
def test_b1_tap_brain_failure_never_blanks_completion(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("telemetry down / lane_feed import error")

    monkeypatch.setattr(llm_io, "_tap_brain", boom)
    # Both the dict shape and the pydantic-style shape must still yield the content.
    assert llm_io.responseText({"message": {"content": "valid completion"}}) == "valid completion"

    class _Msg:
        content = "attr completion"

        def get(self, k, d=None):
            return getattr(self, k, d)

    class _Resp:
        message = _Msg()

        def get(self, k, d=None):
            return getattr(self, k, d)

    assert llm_io.responseText(_Resp()) == "attr completion"


# --------------------------------------------------------------------------- B2
class _Completed:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _fake_git(checkout_rc):
    def run(cmd, **_kw):
        if "--is-inside-work-tree" in cmd:
            return _Completed(0, "true\n")
        if "--verify" in cmd:
            return _Completed(1)             # branch does not exist -> checkout -B path
        if "checkout" in cmd:
            return _Completed(checkout_rc, stderr="fatal: cannot checkout")
        return _Completed(0)
    return run


def _selfref_state():
    st = mock.Mock()
    st.task_id = "abcd1234ef"
    st.markSelfReferential = mock.Mock()
    return st


def test_b2_failed_checkout_does_not_mark_selfref(monkeypatch):
    state, dashboard = _selfref_state(), mock.Mock()
    monkeypatch.setattr(run_loop.subprocess, "run", _fake_git(checkout_rc=1))
    with mock.patch("notifications.discord_bot.sendEmbed") as send, \
            mock.patch("notifications.discord_bot.noticeEmbed", return_value={"e": 1}), \
            mock.patch("notifications.discord_bot.selfRefEmbed", return_value={"e": 2}) as selfref:
        run_loop._prepareSelfReferential(state, "/repo", mock.Mock(), dashboard)
    state.markSelfReferential.assert_not_called()     # prep aborted: no core-file locks w/o branch
    selfref.assert_not_called()                       # the self-ref "you're isolated" embed is NOT sent
    send.assert_called_once()                         # an alert WAS sent
    dashboard.event.assert_not_called()


def test_b2_successful_checkout_marks_selfref(monkeypatch):
    state, dashboard = _selfref_state(), mock.Mock()
    monkeypatch.setattr(run_loop.subprocess, "run", _fake_git(checkout_rc=0))
    with mock.patch("notifications.discord_bot.sendEmbed"), \
            mock.patch("notifications.discord_bot.selfRefEmbed", return_value={"e": 2}):
        run_loop._prepareSelfReferential(state, "/repo", mock.Mock(), dashboard)
    assert state.markSelfReferential.call_count == 1
    dashboard.event.assert_called_once()


# --------------------------------------------------------------------------- B4
class _FakeState:
    def __init__(self):
        self.subtasks = []
        self.notifications = []
        self._n = 0

    def addSubtask(self, title, description="", layer=3, verify=None):
        self._n += 1
        st = {"subtask_id": f"s{self._n}", "title": title, "description": description,
              "status": "pending", "layer": layer, "verify": verify}
        self.subtasks.append(st)
        return st

    def getSubtask(self, sid):
        return next((s for s in self.subtasks if s["subtask_id"] == sid), None)

    def updateSubtask(self, sid, **kw):
        st = self.getSubtask(sid)
        if st:
            st.update(kw)

    def addNotification(self, *a, **k):
        self.notifications.append((a, k))

    def replanLogRel(self):
        return "replan.md"


def _orch():
    from orchestrator import Orchestrator
    return Orchestrator(brain=mock.Mock(), obs=mock.Mock())


def test_b4_non_string_titles_do_not_crash_and_rest_applies():
    orch = _orch()
    state = _FakeState()
    victim = state.addSubtask("to remove")            # a pending subtask we ask the replan to drop
    decision = {
        "reason": "malformed 7B replan",
        "add": [{"title": 5}, {"title": {"x": 1}}, {"title": "kept add"}],
        "remove": [victim["subtask_id"]],
    }
    orch._applyReplan(state, decision)                # must NOT raise on int/dict titles
    titles = [s["title"] for s in state.subtasks]
    assert "kept add" in titles                       # the well-formed add still landed
    assert "untitled" in titles                       # the non-string titles coerced to 'untitled'
    assert state.getSubtask(victim["subtask_id"])["status"] == "removed"   # the remove still applied


# --------------------------------------------------------------------------- B5
def test_b5_system_over_window_trims_user_not_returns_whole():
    system = "S" * 100_000                            # system alone dwarfs the window -> budget <= 0
    user = "U" * 5_000
    out = brain_io._fitUserToCtx(system, user, num_ctx=8192, headroom=2048)
    assert out != user                               # the FULL payload is NOT returned (old bug)
    assert len(out) == brain_io.BUDGET_FLOOR_CHARS   # bounded to the floor tail slice
    assert out == user[-brain_io.BUDGET_FLOOR_CHARS:]


def test_b5_short_user_under_floor_survives():
    out = brain_io._fitUserToCtx("S" * 100_000, "tiny", num_ctx=8192, headroom=2048)
    assert out == "tiny"


def test_b5_normal_over_budget_path_still_trims_with_marker():
    out = brain_io._fitUserToCtx("sys", "x" * (8192 * 4), num_ctx=8192, headroom=2048)
    assert "context trimmed to fit the model window" in out


# --------------------------------------------------------------------------- B6
def test_b6_per_sid_dedup_does_not_cross_contaminate():
    orch = _orch()
    out = "R" * 2000
    assert orch._worthGptReview(out, sid="a") is True     # first time for sid a
    assert orch._worthGptReview(out, sid="b") is True     # SAME output, different sid -> still worth
    assert orch._worthGptReview(out, sid="a") is False    # exact repeat for sid a -> deduped


def test_b6_failed_review_does_not_suppress_next_identical():
    orch = _orch()
    out = "R" * 2000
    # commit=False models "check worth but the review then FAILED (raised) -> hash NOT recorded".
    assert orch._worthGptReview(out, sid="a", commit=False) is True
    assert orch._worthGptReview(out, sid="a", commit=False) is True   # not suppressed by the failure
    orch._markGptReviewed(out, sid="a")                              # a review finally SUCCEEDS
    assert orch._worthGptReview(out, sid="a", commit=False) is False  # now (and only now) deduped


def test_b6_default_commit_path_dedups_same_sid():
    orch = _orch()
    out = "R" * 2000
    assert orch._worthGptReview(out) is True
    assert orch._worthGptReview(out) is False


# --------------------------------------------------------------------------- B3
def test_b3_running_future_worktree_exit_deferred_until_after_pool_join(monkeypatch):
    from platform_core.orchestration.run_loop_mixin import OrchestratorRunLoopMixin
    from platform_core.orchestration import parallel_safety
    from platform_core.runtime import worktree
    from memory import experience

    monkeypatch.setattr(config, "WORKTREE_ISOLATION_ENABLED", True, raising=False)
    monkeypatch.setattr(parallel_safety, "claim", lambda state, sid: True)
    monkeypatch.setattr(worktree, "enterWorktree", lambda state, sid: f"ctx::{sid}")
    monkeypatch.setattr(experience, "close_pool", lambda: None)

    run_finished = {"run": False}
    run_started = threading.Event()
    exit_calls = []   # (ctx, merge, run_finished_snapshot_at_call_time)

    def fake_exit(ctx, merge=False):
        exit_calls.append((ctx, merge, run_finished["run"]))

    monkeypatch.setattr(worktree, "exitWorktree", fake_exit)

    class _State:
        def getSubtask(self, sid):
            return {"status": "pending"}

        def updateSubtask(self, *a, **k):
            pass

        def addNotification(self, *a, **k):
            pass

    class _Harness(OrchestratorRunLoopMixin):
        def __init__(self):
            self._state_lock = threading.Lock()

        def _executeSubtask(self, state, st, *a, **k):
            if st["subtask_id"] == "abort":
                run_started.wait(2.0)        # ensure 'run' is genuinely mid-flight (uncancellable)
                raise AbortRun("boom")
            run_started.set()
            time.sleep(0.25)                 # still running while the abort tears the batch down
            run_finished["run"] = True

    harness = _Harness()
    batch = [{"subtask_id": "abort"}, {"subtask_id": "run"}]
    position, abort = harness._handleParallelBatch(
        _State(), batch, "doc", "/wd", mock.Mock(), mock.Mock(), position=0, parallelism=2)

    assert isinstance(abort, AbortRun)
    run_exits = [c for c in exit_calls if c[0] == "ctx::run"]
    assert run_exits, "the running future's worktree must still be exited exactly once"
    # The KEY invariant: when the running future's worktree was exited, the worker had ALREADY
    # finished -- i.e. the exit was DEFERRED past pool shutdown, not run mid-flight (B3).
    assert all(snapshot is True for (_c, _m, snapshot) in run_exits)
    assert all(merge is False for (_c, merge, _s) in run_exits)   # abort never adopts partial work
