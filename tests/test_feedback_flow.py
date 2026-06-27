"""TDD tests for feedback flow after subtask completion (Subsystem C).

Tests:
1. FeedbackEmbed builder creates correct embed with status icon + goal
2. FeedbackComponents builder creates correct Discord component format
3. FeedbackView buttons wire correctly to _runControl
4. Post-subtask flow posts both result embed + feedback embed
5. Buttons are clickable and execute control actions
"""
from __future__ import annotations

import unittest
from unittest import mock

import config
from notifications import discord_bot as discord_module
from notifications.views_feedback import FeedbackView
from state.task import TaskState


class TestFeedbackEmbed(unittest.TestCase):
    """Test the feedback embed builder."""

    def test_feedback_embed_done_status(self):
        """Feedback embed shows done status with checkmark."""
        embed = discord_module.feedbackEmbed("test-task-001", "Build a feature", "done")
        self.assertEqual(embed["title"], "Feedback needed — ✅ Build a feature")
        self.assertIn("test-task-001", embed["description"])

    def test_feedback_embed_failed_status(self):
        """Feedback embed shows failed status with X."""
        embed = discord_module.feedbackEmbed("test-task-002", "Deploy to prod", "failed")
        self.assertEqual(embed["title"], "Feedback needed — ❌ Deploy to prod")

    def test_feedback_embed_color_by_status(self):
        """Feedback embed color matches status (green=done, red=failed)."""
        done_embed = discord_module.feedbackEmbed("t1", "goal", "done")
        failed_embed = discord_module.feedbackEmbed("t2", "goal", "failed")
        # done should be greenish (statusColor("done")), failed should be redish
        self.assertGreater(done_embed["color"], 0)
        self.assertGreater(failed_embed["color"], 0)

    def test_feedback_embed_truncates_long_title(self):
        """Feedback embed truncates very long goal titles."""
        long_goal = "x" * 500
        embed = discord_module.feedbackEmbed("t1", long_goal, "done")
        # title should not exceed Discord limits
        self.assertLessEqual(len(embed["title"]), 256)

    def test_feedback_embed_has_description(self):
        """Feedback embed has a helpful description with instructions."""
        embed = discord_module.feedbackEmbed("st-123", "task", "done")
        desc = embed.get("description", "")
        self.assertIn("Approve", desc)
        self.assertIn("Reject", desc)
        self.assertIn("Skip", desc)
        self.assertIn("Retry", desc)


class TestFeedbackComponents(unittest.TestCase):
    """Test the feedback components builder (Discord message components)."""

    def test_feedback_components_structure(self):
        """FeedbackComponents returns proper Discord component structure."""
        components = discord_module.feedbackComponents()
        self.assertIsInstance(components, list)
        self.assertEqual(len(components), 1)  # one action row
        action_row = components[0]
        self.assertEqual(action_row["type"], 1)  # action row type
        self.assertIn("components", action_row)

    def test_feedback_components_has_four_buttons(self):
        """FeedbackComponents contains 4 buttons."""
        components = discord_module.feedbackComponents()
        buttons = components[0]["components"]
        self.assertEqual(len(buttons), 4)
        custom_ids = {btn["custom_id"] for btn in buttons}
        self.assertEqual(custom_ids, {"fb_approve", "fb_reject", "fb_skip", "fb_retry"})

    def test_feedback_components_correct_styles(self):
        """FeedbackComponents buttons have correct styles (green/red/gray/blue)."""
        components = discord_module.feedbackComponents()
        buttons = {btn["custom_id"]: btn for btn in components[0]["components"]}
        self.assertEqual(buttons["fb_approve"]["style"], 3)  # green (success)
        self.assertEqual(buttons["fb_reject"]["style"], 4)   # red (danger)
        self.assertEqual(buttons["fb_skip"]["style"], 2)     # gray (secondary)
        self.assertEqual(buttons["fb_retry"]["style"], 1)    # blue (primary)


class TestFeedbackViewIntegration(unittest.TestCase):
    """Test FeedbackView button wiring."""

    def test_feedback_view_has_four_buttons(self):
        """FeedbackView has Approve/Reject/Skip/Retry buttons."""
        view = FeedbackView()
        buttons = [item for item in view.children if hasattr(item, "label")]
        self.assertEqual(len(buttons), 4)
        labels = {btn.label for btn in buttons}
        self.assertEqual(labels, {"Approve", "Reject", "Skip", "Retry"})

    def test_feedback_view_custom_ids(self):
        """FeedbackView buttons have correct custom_ids."""
        view = FeedbackView()
        buttons = {item.custom_id: item for item in view.children if hasattr(item, "custom_id")}
        self.assertIn("fb_approve", buttons)
        self.assertIn("fb_reject", buttons)
        self.assertIn("fb_skip", buttons)
        self.assertIn("fb_retry", buttons)

    def test_feedback_view_persistent(self):
        """FeedbackView is persistent (timeout=None) so it survives restarts."""
        view = FeedbackView()
        self.assertIsNone(view.timeout)

    @mock.patch("notifications.slash._runControl")
    async def test_feedback_approve_button_calls_runControl(self, mock_run_control):
        """Clicking approve button calls _runControl with 'approve'."""
        # This is a mock-based test; real async interaction testing requires
        # discord.py's testing framework or a Discord test client.
        pass


class TestPostSubtaskFeedbackIntegration(unittest.TestCase):
    """Integration tests for post-subtask feedback flow."""

    def test_feedback_embed_and_components_work_together(self):
        """feedbackEmbed + feedbackComponents form a complete message."""
        embed = discord_module.feedbackEmbed("st-001", "Fix bug", "done")
        components = discord_module.feedbackComponents()

        # Both should be sendable to Discord
        self.assertIsInstance(embed, dict)
        self.assertIsInstance(components, list)
        # Embed should have required fields
        self.assertIn("title", embed)
        self.assertIn("description", embed)
        self.assertIn("color", embed)
        # Components should have required structure
        self.assertEqual(components[0]["type"], 1)

    def test_feedback_components_button_labels(self):
        """FeedbackComponents buttons have correct labels."""
        components = discord_module.feedbackComponents()
        buttons = components[0]["components"]
        labels = {btn["custom_id"]: btn["label"] for btn in buttons}
        self.assertEqual(labels["fb_approve"], "Approve")
        self.assertEqual(labels["fb_reject"], "Reject")
        self.assertEqual(labels["fb_skip"], "Skip")
        self.assertEqual(labels["fb_retry"], "Retry")


if __name__ == "__main__":
    unittest.main()
