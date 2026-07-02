"""Tests for the Pillow visuals layer: valid PNG/GIF bytes when enabled, graceful None when off.
Never raises. Toggles config.VISUALS_ENABLED around each case."""
import unittest

import config
from notifications import visuals


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

    def test_burndown_is_png(self):
        out = visuals.burndownChart(_StubState())
        self.assertIsInstance(out, bytes)
        self.assertTrue(out.startswith(PNG))

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
        self.assertIsNone(visuals.burndownChart(st))
        self.assertIsNone(visuals.timelapseGif([b"x"]))
