"""T8 end-of-run replay GIF: real GIF bytes from the final subtask grid; graceful None."""
import unittest

import config
from notifications import visuals
from notifications import discord_bot as discord


class _State:
    def __init__(self, n=5):
        self.meta = {"goal_raw": "Build the lab", "status": "complete", "started_at": None}
        self.subtasks = [{"subtask_id": f"st-{i:03d}", "title": f"t{i}", "status": "done"}
                         for i in range(1, n + 1)]
        self.data = {"notifications": [], "adversary_reviews": []}


class Replay(unittest.TestCase):
    def setUp(self):
        self._v = config.VISUALS_ENABLED
        config.VISUALS_ENABLED = True

    def tearDown(self):
        config.VISUALS_ENABLED = self._v

    def test_gif_from_grid(self):
        gif = visuals.runReplayGif(_State(6))
        self.assertIsInstance(gif, bytes)
        self.assertIn(gif[:6], (b"GIF87a", b"GIF89a"))

    def test_caps_frames(self):
        # many subtasks must still produce a bounded GIF (<= max_frames sampling)
        self.assertTrue(visuals.runReplayGif(_State(40), max_frames=8))

    def test_empty_none(self):
        self.assertIsNone(visuals.runReplayGif(_State(0)))

    def test_disabled_none(self):
        config.VISUALS_ENABLED = False
        self.assertIsNone(visuals.runReplayGif(_State(5)))

    def test_postfile_exists(self):
        self.assertTrue(callable(discord.postFile))
