"""Unit tests for notifications/views.py -- pure view-state logic (no live Discord)."""
import asyncio
import unittest
from unittest import mock

import discord

from notifications.views import ConfirmView, Paginator


def _run(coro):
    # asyncio.run gives each call a FRESH event loop and closes it cleanly. The old
    # get_event_loop().run_until_complete reused a shared loop -> once another test closed it,
    # these tests flaked non-deterministically under xdist ordering.
    return asyncio.run(coro)


class TestLaunchRejectsActiveRunFirst(unittest.TestCase):
    """A guided-setup Launch must reject a duplicate run BEFORE the ChatGPT pre-flight, so a second
    /work can't kill the active run's second-brain browser only to then be rejected."""
    def test_launch_bails_on_active_run_before_launch(self):
        from notifications.views import WorkSetupView
        from notifications import work_launcher
        v = WorkSetupView(1, "goal", 1.0, None)
        interaction = mock.AsyncMock()
        # @discord.ui.button makes the instance attr a Button; call the raw class-dict coroutine.
        raw_launch = WorkSetupView.__dict__["_launch"]
        with mock.patch.object(work_launcher, "activeRun", return_value=mock.Mock()) as ar, \
                mock.patch.object(work_launcher, "launchOrError") as launch:
            _run(raw_launch(v, interaction, mock.Mock()))
        ar.assert_called_once()
        launch.assert_not_called()   # bailed before launch (and before the browser pre-flight)


class TestSkipTargetsPending(unittest.TestCase):
    """The dashboard Skip button must queue a skip of a PENDING subtask (what the backend honors),
    not the in_progress one (which the orchestrator drops -> the button silently no-op'd)."""
    def test_skip_targets_next_pending(self):
        from notifications import views
        state = mock.Mock()
        state.task_id = "t1"
        state.subtasks = [
            {"subtask_id": "st-001", "status": "in_progress"},
            {"subtask_id": "st-002", "status": "pending"},
            {"subtask_id": "st-003", "status": "pending"},
        ]
        interaction = mock.AsyncMock()
        interaction.user.id = 1
        captured = {}
        with mock.patch.object(views, "_ownerOk", return_value=True), \
                mock.patch.object(views.commands, "resolveTargetTask", return_value=state), \
                mock.patch.object(views.commands, "applyCommand",
                                  side_effect=lambda bus, st, cmd: captured.setdefault("cmd", cmd) or "queued"), \
                mock.patch.object(views.audit, "record"), \
                mock.patch.object(views, "ControlBus"):
            _run(views._skipCurrent(interaction, "test"))
        self.assertEqual(captured["cmd"].arg, "st-002",
                         "Skip targeted a non-pending subtask (backend would drop it)")


class TestConfirmView(unittest.TestCase):
    def test_initial_value_is_false(self):
        v = ConfirmView(owner_id=42)
        self.assertFalse(v.value)

    def test_owner_id_stored(self):
        v = ConfirmView(owner_id=999)
        self.assertEqual(v.owner_id, 999)

    def test_timeout_thirty_seconds(self):
        v = ConfirmView(owner_id=1)
        self.assertEqual(v.timeout, 30)

    def test_interaction_check_wrong_user(self):
        v = ConfirmView(owner_id=1)
        interaction = mock.Mock()
        interaction.user.id = 2
        result = _run(v.interaction_check(interaction))
        self.assertFalse(result)

    def test_interaction_check_owner_passes(self):
        v = ConfirmView(owner_id=7)
        interaction = mock.Mock()
        interaction.user.id = 7
        result = _run(v.interaction_check(interaction))
        self.assertTrue(result)


class TestPaginator(unittest.TestCase):
    def _pages(self, n=3):
        return [discord.Embed(description=f"page {i}") for i in range(n)]

    def test_starts_at_page_zero(self):
        p = Paginator(owner_id=1, pages=self._pages(3))
        self.assertEqual(p.i, 0)

    def test_prev_disabled_at_start(self):
        p = Paginator(owner_id=1, pages=self._pages(3))
        self.assertTrue(p.prev.disabled)

    def test_next_enabled_at_start(self):
        p = Paginator(owner_id=1, pages=self._pages(3))
        self.assertFalse(p.next.disabled)

    def test_both_disabled_on_single_page(self):
        p = Paginator(owner_id=1, pages=self._pages(1))
        self.assertTrue(p.prev.disabled)
        self.assertTrue(p.next.disabled)

    def test_sync_last_page_disables_next(self):
        p = Paginator(owner_id=1, pages=self._pages(3))
        p.i = 2
        p._sync()
        self.assertTrue(p.next.disabled)
        self.assertFalse(p.prev.disabled)

    def test_sync_middle_page_both_enabled(self):
        p = Paginator(owner_id=1, pages=self._pages(5))
        p.i = 2
        p._sync()
        self.assertFalse(p.prev.disabled)
        self.assertFalse(p.next.disabled)

    def test_empty_pages_fallback_to_placeholder(self):
        p = Paginator(owner_id=1, pages=[])
        self.assertEqual(len(p.pages), 1)

    def test_interaction_check_wrong_user_sends_message(self):
        p = Paginator(owner_id=1, pages=self._pages(2))
        interaction = mock.AsyncMock()
        interaction.user.id = 2
        result = _run(p.interaction_check(interaction))
        self.assertFalse(result)
        interaction.response.send_message.assert_called_once()

    def test_interaction_check_owner_passes(self):
        p = Paginator(owner_id=5, pages=self._pages(2))
        interaction = mock.AsyncMock()
        interaction.user.id = 5
        result = _run(p.interaction_check(interaction))
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
