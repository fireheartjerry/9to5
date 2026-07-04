"""Unit tests for notifications/views_feedback.py -- FeedbackView button handling.

Covers:
  - FeedbackView initialization and persistence timeout
  - Button execution (approve/reject/skip/retry) calling slash._runControl
  - Error handling and ephemeral error messages
  - Feedback recording via implicit human_feedback.record()
  - Button icon application via _applyButtonIcons
"""

from __future__ import annotations

import asyncio
import unittest
from unittest import mock

import discord

from notifications.views_feedback import FeedbackView


def _run(coro):
    """Run an async coroutine with a fresh event loop (prevents flakes across test ordering)."""
    return asyncio.run(coro)


class TestFeedbackViewInitialization(unittest.TestCase):
    """FeedbackView initialization and metadata."""

    def test_initializes_with_timeout_none(self):
        """View must persist across restarts (timeout=None)."""
        view = FeedbackView()
        self.assertIsNone(view.timeout, "FeedbackView should have timeout=None for persistence")

    def test_has_four_buttons(self):
        """FeedbackView must have exactly 4 buttons: Approve, Reject, Skip, Retry."""
        view = FeedbackView()
        buttons = [c for c in view.children if isinstance(c, discord.ui.Button)]
        self.assertEqual(len(buttons), 4, f"Expected 4 buttons, got {len(buttons)}")

    def test_button_custom_ids(self):
        """Each button must have a unique custom_id for persistence."""
        view = FeedbackView()
        custom_ids = set()
        for c in view.children:
            if isinstance(c, discord.ui.Button):
                custom_ids.add(c.custom_id)
        expected = {"fb_approve", "fb_reject", "fb_skip", "fb_retry"}
        self.assertEqual(custom_ids, expected, f"Custom IDs mismatch: {custom_ids}")

    def test_button_labels(self):
        """Each button must have the correct label."""
        view = FeedbackView()
        labels_by_custom_id = {}
        for c in view.children:
            if isinstance(c, discord.ui.Button):
                labels_by_custom_id[c.custom_id] = c.label
        self.assertEqual(labels_by_custom_id.get("fb_approve"), "Approve")
        self.assertEqual(labels_by_custom_id.get("fb_reject"), "Reject")
        self.assertEqual(labels_by_custom_id.get("fb_skip"), "Skip")
        self.assertEqual(labels_by_custom_id.get("fb_retry"), "Retry")


class TestApproveButton(unittest.TestCase):
    """FeedbackView.approve button behavior."""

    def test_approve_calls_runControl(self):
        """Clicking Approve must call slash._runControl(interaction, 'approve')."""
        view = FeedbackView()
        interaction = mock.AsyncMock(spec=discord.Interaction)
        button = mock.Mock()

        # @discord.ui.button wraps the method; call the raw class-dict coroutine
        raw_approve = FeedbackView.__dict__["approve"]

        with mock.patch("notifications.views_feedback.slash._runControl") as mock_run:
            mock_run.return_value = None  # async, returns None
            _run(raw_approve(view, interaction, button))

        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        self.assertEqual(args[0], interaction)
        self.assertEqual(args[1], "approve")

    def test_approve_error_sends_ephemeral(self):
        """If approve fails, send an ephemeral error message."""
        view = FeedbackView()
        interaction = mock.AsyncMock(spec=discord.Interaction)
        # Make followup.send async so it can be awaited
        interaction.followup.send = mock.AsyncMock()
        button = mock.Mock()

        raw_approve = FeedbackView.__dict__["approve"]

        async def raise_error(*args, **kwargs):
            raise ValueError("Simulated error")

        with mock.patch("notifications.views_feedback.slash._runControl", side_effect=raise_error):
            _run(raw_approve(view, interaction, button))

        interaction.followup.send.assert_called_once()
        call_args = interaction.followup.send.call_args
        self.assertIn("Feedback failed to save", call_args[0][0])
        self.assertTrue(call_args[1].get("ephemeral"))


class TestRejectButton(unittest.TestCase):
    """FeedbackView.reject button behavior."""

    def test_reject_calls_runControl(self):
        """Clicking Reject must call slash._runControl(interaction, 'reject')."""
        view = FeedbackView()
        interaction = mock.AsyncMock(spec=discord.Interaction)
        button = mock.Mock()

        raw_reject = FeedbackView.__dict__["reject"]

        with mock.patch("notifications.views_feedback.slash._runControl") as mock_run:
            mock_run.return_value = None
            _run(raw_reject(view, interaction, button))

        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        self.assertEqual(args[0], interaction)
        self.assertEqual(args[1], "reject")

    def test_reject_error_sends_ephemeral(self):
        """If reject fails, send an ephemeral error message."""
        view = FeedbackView()
        interaction = mock.AsyncMock(spec=discord.Interaction)
        interaction.followup.send = mock.AsyncMock()
        button = mock.Mock()

        raw_reject = FeedbackView.__dict__["reject"]

        async def raise_error(*args, **kwargs):
            raise RuntimeError("DB write failed")

        with mock.patch("notifications.views_feedback.slash._runControl", side_effect=raise_error):
            _run(raw_reject(view, interaction, button))

        interaction.followup.send.assert_called_once()


class TestSkipButton(unittest.TestCase):
    """FeedbackView.skip button behavior."""

    def test_skip_calls_skipCurrent(self):
        """Clicking Skip must call views_control._skipCurrent(interaction, 'feedback')."""
        view = FeedbackView()
        interaction = mock.AsyncMock(spec=discord.Interaction)
        button = mock.Mock()

        raw_skip = FeedbackView.__dict__["skip"]

        with mock.patch("notifications.views_feedback._skipCurrent") as mock_skip:
            mock_skip.return_value = None
            _run(raw_skip(view, interaction, button))

        mock_skip.assert_called_once()
        args, kwargs = mock_skip.call_args
        self.assertEqual(args[0], interaction)
        self.assertEqual(args[1], "feedback")

    def test_skip_error_sends_ephemeral(self):
        """If skip fails, send an ephemeral error message."""
        view = FeedbackView()
        interaction = mock.AsyncMock(spec=discord.Interaction)
        interaction.followup.send = mock.AsyncMock()
        button = mock.Mock()

        raw_skip = FeedbackView.__dict__["skip"]

        async def raise_error(*args, **kwargs):
            raise Exception("Skip failed")

        with mock.patch("notifications.views_feedback._skipCurrent", side_effect=raise_error):
            _run(raw_skip(view, interaction, button))

        interaction.followup.send.assert_called_once()


class TestRetryButton(unittest.TestCase):
    """FeedbackView.retry button behavior."""

    def test_retry_calls_runControl(self):
        """Clicking Retry must call slash._runControl(interaction, 'retry')."""
        view = FeedbackView()
        interaction = mock.AsyncMock(spec=discord.Interaction)
        button = mock.Mock()

        raw_retry = FeedbackView.__dict__["retry"]

        with mock.patch("notifications.views_feedback.slash._runControl") as mock_run:
            mock_run.return_value = None
            _run(raw_retry(view, interaction, button))

        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        self.assertEqual(args[0], interaction)
        self.assertEqual(args[1], "retry")

    def test_retry_error_sends_ephemeral(self):
        """If retry fails, send an ephemeral error message."""
        view = FeedbackView()
        interaction = mock.AsyncMock(spec=discord.Interaction)
        interaction.followup.send = mock.AsyncMock()
        button = mock.Mock()

        raw_retry = FeedbackView.__dict__["retry"]

        async def raise_error(*args, **kwargs):
            raise Exception("Retry failed")

        with mock.patch("notifications.views_feedback.slash._runControl", side_effect=raise_error):
            _run(raw_retry(view, interaction, button))

        interaction.followup.send.assert_called_once()


class TestIntegrationWithRunControl(unittest.TestCase):
    """Integration tests showing button -> slash._runControl pipeline."""

    def test_all_buttons_route_to_runControl(self):
        """Approve/Reject/Retry route through slash._runControl; Skip routes through _skipCurrent."""
        view = FeedbackView()
        interaction = mock.AsyncMock(spec=discord.Interaction)
        button = mock.Mock()

        # Patch _runControl to capture all calls
        kinds_called = []
        skip_called = []

        async def capture_call(inter, kind, *args):
            kinds_called.append(kind)

        async def capture_skip(inter, source):
            skip_called.append(source)

        raw_approve = FeedbackView.__dict__["approve"]
        raw_reject = FeedbackView.__dict__["reject"]
        raw_skip = FeedbackView.__dict__["skip"]
        raw_retry = FeedbackView.__dict__["retry"]

        with (
            mock.patch("notifications.views_feedback.slash._runControl", side_effect=capture_call),
            mock.patch("notifications.views_feedback._skipCurrent", side_effect=capture_skip),
        ):
            _run(raw_approve(view, interaction, button))
            _run(raw_reject(view, interaction, button))
            _run(raw_skip(view, interaction, button))
            _run(raw_retry(view, interaction, button))

        self.assertEqual(kinds_called, ["approve", "reject", "retry"])
        self.assertEqual(skip_called, ["feedback"])

    def test_runControl_receives_interaction(self):
        """slash._runControl must receive the interaction object unchanged."""
        view = FeedbackView()
        interaction = mock.AsyncMock(spec=discord.Interaction)
        interaction.user.id = 12345
        button = mock.Mock()

        captured_interactions = []

        async def capture_call(inter, kind, *args):
            captured_interactions.append(inter)

        raw_approve = FeedbackView.__dict__["approve"]

        with mock.patch("notifications.views_feedback.slash._runControl", side_effect=capture_call):
            _run(raw_approve(view, interaction, button))

        self.assertEqual(len(captured_interactions), 1)
        self.assertIs(captured_interactions[0], interaction)


class TestButtonIconApplication(unittest.TestCase):
    """Button icons are applied via _applyButtonIcons."""

    def test_feedback_view_has_icons_applied(self):
        """_applyButtonIcons must be called during init (even if icons are unprovisioned)."""
        with mock.patch("notifications.views_feedback._applyButtonIcons") as mock_apply:
            view = FeedbackView()
            mock_apply.assert_called_once_with(view)
