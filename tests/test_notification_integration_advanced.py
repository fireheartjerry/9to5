"""Advanced notification integration tests.

Covers dashboard lifecycle, webdash snapshots, embed builders, and surface
protocol edge cases.

Split from test_notification_integration.py (was 572 lines).  Bus/entry
pipeline and basic integration tests live in
test_notification_integration_basic.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import tempfile
import threading
import unittest
from unittest import mock

import config
import notifications.discord_bot as d
from control import ControlBus
from notifications import dashboard as dash
from notifications import webdash
from state.task import TaskState


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_state(goal: str = "integration test goal", horizon: float = 1.0) -> TaskState:
    st = TaskState.create(goal, horizon)
    st.meta["status"] = "executing"
    return st


def _add_subtasks(state: TaskState, n: int = 3) -> None:
    for i in range(n):
        state.addSubtask(f"st-{i + 1:03d}", f"subtask {i + 1}", "executor")


# ---------------------------------------------------------------------------
# 3. Dashboard + TaskState lifecycle (mocked Discord)
# ---------------------------------------------------------------------------

class TestDashboardTaskStateLifecycle(unittest.TestCase):
    """DiscordDashboard start/update/unpin integrated with TaskState (REST mocked)."""

    def _mock_discord(self):
        patches = [
            mock.patch.object(config, "DISCORD_DASHBOARD", True),
            mock.patch("notifications.discord_bot.editMessage", return_value=True),
            mock.patch("notifications.discord_bot.editMessageResult", return_value="ok"),
            mock.patch("notifications.discord_bot.createMessage", return_value="msg-1"),
            mock.patch("notifications.discord_bot.pinMessage", return_value=True),
            mock.patch("notifications.discord_bot.unpinMessage", return_value=True),
        ]
        return patches

    def test_start_creates_message_and_records_id(self):
        db = dash.DiscordDashboard()
        state = _make_state()
        _add_subtasks(state)
        patches = self._mock_discord()
        for p in patches:
            p.start()
        try:
            db.start(state, "planning")
            self.assertEqual(db.message_id, "msg-1")
        finally:
            for p in patches:
                p.stop()

    def test_update_reflects_effort_and_model(self):
        db = dash.DiscordDashboard()
        db.message_id = "existing-msg"
        state = _make_state()
        _add_subtasks(state)
        patches = self._mock_discord()
        for p in patches:
            p.start()
        try:
            db.update(state, "executing", effort="high", model="claude-opus-4-8", note="step 1 done")
            self.assertEqual(db.effort, "high")
            self.assertEqual(db.model, "claude-opus-4-8")
            snap = db._eventsSnapshot()
            self.assertTrue(any("step 1 done" in e for e in snap))
        finally:
            for p in patches:
                p.stop()

    def test_event_ring_survives_multiple_updates(self):
        db = dash.DiscordDashboard()
        db.message_id = "existing-msg"
        state = _make_state()
        patches = self._mock_discord()
        for p in patches:
            p.start()
        try:
            for i in range(12):
                db.update(state, "executing", note=f"event {i}")
            self.assertEqual(len(db._eventsSnapshot()), 10)
        finally:
            for p in patches:
                p.stop()

    def test_unpin_called_at_run_end(self):
        db = dash.DiscordDashboard()
        db.message_id = "msg-1"
        patches = self._mock_discord()
        m_unpin = None
        for p in patches:
            m = p.start()
            if "unpinMessage" in str(p):
                m_unpin = m
        try:
            db.unpin()
            if m_unpin is not None:
                m_unpin.assert_called_once()
        finally:
            for p in patches:
                p.stop()

    def test_start_noop_when_dashboard_disabled(self):
        db = dash.DiscordDashboard()
        state = _make_state()
        with mock.patch.object(config, "DISCORD_DASHBOARD", False):
            db.start(state, "starting")
        self.assertIsNone(db.message_id)

    def test_thread_safe_concurrent_updates(self):
        db = dash.DiscordDashboard()
        db.message_id = "existing-msg"
        state = _make_state()
        errors: list[Exception] = []
        patches = self._mock_discord()
        for p in patches:
            p.start()
        try:
            def _worker(n: int):
                try:
                    for i in range(5):
                        db.update(state, "executing", note=f"t{n}-{i}")
                except Exception as e:  # noqa: BLE001
                    errors.append(e)

            threads = [threading.Thread(target=_worker, args=(k,)) for k in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(errors, [])
        finally:
            for p in patches:
                p.stop()


# ---------------------------------------------------------------------------
# 4. Webdash _snapshot with populated TaskState
# ---------------------------------------------------------------------------

class TestWebdashSnapshotIntegration(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._patch_state_dir = mock.patch.object(
            config, "STATE_DIR", Path(self._tmp) / "state"
        )
        self._patch_control_dir = mock.patch.object(
            config, "CONTROL_DIR", Path(self._tmp) / "control"
        )
        self._patch_state_dir.start()
        self._patch_control_dir.start()
        (Path(self._tmp) / "state").mkdir(parents=True, exist_ok=True)
        (Path(self._tmp) / "control").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self._patch_state_dir.stop()
        self._patch_control_dir.stop()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_snapshot_unknown_task_returns_empty(self):
        snap = webdash._snapshot("nonexistent-task-id")
        self.assertTrue(snap.get("empty"))

    def test_snapshot_with_real_state_returns_expected_shape(self):
        state = _make_state("webdash test goal")
        _add_subtasks(state, 3)
        state.addNotification("planning_start", "plan authored")
        state.save()

        snap = webdash._snapshot(state.task_id)
        self.assertFalse(snap.get("empty"))
        self.assertIn("meta", snap)
        self.assertIn("subtasks", snap)
        self.assertIn("progress", snap)
        self.assertIn("control", snap)
        self.assertIn("events", snap)
        self.assertEqual(snap["progress"]["total"], 3)

    def test_snapshot_reflects_notifications(self):
        state = _make_state("notif test")
        state.addNotification("replan", "first replan")
        state.addNotification("subtask_done", "st-001 done")
        state.save()

        snap = webdash._snapshot(state.task_id)
        kinds = [e["kind"] for e in snap.get("events", [])]
        self.assertIn("replan", kinds)
        self.assertIn("subtask_done", kinds)

    def test_snapshot_control_reflects_abort(self):
        state = _make_state("control test")
        state.save()
        bus = ControlBus(state.task_id)
        bus.requestAbort()

        snap = webdash._snapshot(state.task_id)
        self.assertTrue(snap["control"]["abort"])

    def test_snapshot_control_reflects_pause(self):
        state = _make_state("pause test")
        state.save()
        ControlBus(state.task_id).requestPause()

        snap = webdash._snapshot(state.task_id)
        self.assertTrue(snap["control"]["pause"])


# ---------------------------------------------------------------------------
# 6. Embed builders produce Discord-safe payloads
# ---------------------------------------------------------------------------

class TestEmbedBuilderIntegration(unittest.TestCase):
    """Embed builders combined with _clampEmbed stay within Discord limits."""

    def _within_limits(self, embed: dict) -> bool:
        clamped = d._clampEmbed(embed)
        if d._embedLen(clamped) > config.DISCORD_EMBED_TOTAL_MAX:
            return False
        for f in clamped.get("fields", []):
            if len(str(f.get("value", ""))) > config.DISCORD_MAX_FIELD_VALUE:
                return False
        return True

    def test_planning_start_embed_within_limits(self):
        tasks = [{"title": f"t{i}: " + "x" * 100} for i in range(20)]
        embed = d.planningStartEmbed("x" * 2000, tasks)
        self.assertTrue(self._within_limits(embed))

    def test_adversary_triggered_embed_within_limits(self):
        embed = d.adversaryTriggeredEmbed("st-001 " + "x" * 200, "r" * 200, verdict="challenged")
        self.assertTrue(self._within_limits(embed))

    def test_blocked_embed_within_limits(self):
        embed = d.blockedEmbed("reason " + "r" * 2000, question="q" * 2000)
        self.assertTrue(self._within_limits(embed))

    def test_aborted_embed_within_limits(self):
        embed = d.abortedEmbed("abort reason " + "x" * 1000, "99h 59m")
        self.assertTrue(self._within_limits(embed))

    def test_subtask_failed_embed_within_limits(self):
        vr = {
            "cmd": "pytest " + "x" * 500,
            "returncode": 1,
            "stdout": "out " * 500,
            "stderr": "err " * 500,
            "passed": False,
        }
        embed = d.subtaskFailedEmbed("st-010", "title " + "x" * 100, vr, 3)
        self.assertTrue(self._within_limits(embed))

    def test_complete_embed_within_limits(self):
        state = _make_state("complete embed goal")
        _add_subtasks(state, 5)
        for i, st in enumerate(state.subtasks):
            state.subtasks[i]["status"] = "done"
        embed = d.completeEmbed(state, "https://github.com/example/repo/pull/42", "1h 30m")
        self.assertTrue(self._within_limits(embed))

    def test_clamp_does_not_drop_any_fields(self):
        state = _make_state("field preservation test")
        _add_subtasks(state, 3)
        for i in range(3):
            state.subtasks[i]["status"] = "done"
        raw = d.completeEmbed(state, "https://github.com/x/y/pull/1", "2h 0m")
        clamped = d._clampEmbed(raw)
        self.assertEqual(len(raw.get("fields", [])), len(clamped.get("fields", [])))


if __name__ == "__main__":
    unittest.main()
