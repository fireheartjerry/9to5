"""Tests for the Pillow visuals layer: valid PNG/GIF bytes when enabled, graceful None when off.
Never raises. Toggles config.VISUALS_ENABLED around each case."""
import unittest

import config
from notifications import visuals
from notifications import discord_bot as discord


class _StubState:
    def __init__(self, statuses=("done", "in_progress", "pending", "failed", "done")):
        self.meta = {"goal_raw": "Build a frontier Discord lab with maximum power and many features",
                     "status": "executing", "control_mode": "gated", "started_at": None}
        self.subtasks = [{"subtask_id": f"st-{i:03d}", "title": f"t{i}", "status": s}
                         for i, s in enumerate(statuses, 1)]
        self.data = {"notifications": [{"kind": "replan"}], "adversary_reviews": [{}, {}]}


PNG = b"\x89PNG\r\n\x1a\n"


class VisualsEnabled(unittest.TestCase):
    def setUp(self):
        self._flag = config.VISUALS_ENABLED
        config.VISUALS_ENABLED = True

    def tearDown(self):
        config.VISUALS_ENABLED = self._flag

    def test_progress_card_is_png(self):
        out = visuals.progressCard(_StubState(), phase="executing", model="claude-opus-4-8", effort="high")
        self.assertIsInstance(out, bytes)
        self.assertTrue(out.startswith(PNG))
        self.assertGreater(len(out), 200)

    def test_timelapse_is_gif(self):
        f1 = visuals.progressCard(_StubState(("pending",)))
        f2 = visuals.progressCard(_StubState(("done",)))
        gif = visuals.timelapseGif([f1, f2], duration_ms=400)
        self.assertIsInstance(gif, bytes)
        self.assertTrue(gif[:6] in (b"GIF87a", b"GIF89a"))

    def test_empty_subtasks_does_not_crash(self):
        st = _StubState(())
        self.assertTrue(visuals.progressCard(st).startswith(PNG))


class VisualsDisabled(unittest.TestCase):
    def setUp(self):
        self._flag = config.VISUALS_ENABLED
        config.VISUALS_ENABLED = False

    def tearDown(self):
        config.VISUALS_ENABLED = self._flag

    def test_all_none_when_disabled(self):
        st = _StubState()
        self.assertFalse(visuals.available())
        self.assertIsNone(visuals.progressCard(st))
        self.assertIsNone(visuals.timelapseGif([b"x"]))


# ---- merged from test_replay.py ----
# T8 end-of-run replay GIF: real GIF bytes from the final subtask grid; graceful None.


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
