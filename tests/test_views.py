"""Unit tests for notifications/views.py -- pure view-state logic (no live Discord)."""
import asyncio
import unittest
from unittest import mock

import discord

from notifications.views import ConfirmView, Paginator


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


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
