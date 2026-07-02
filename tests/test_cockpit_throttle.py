"""P1 hardening: the cockpit hero-image upload is throttled to <=1 per COCKPIT_IMAGE_MIN_INTERVAL,
so the every-4s pause loop can't drive a multipart-upload rate-limit storm. Text-CV2 still flows."""
import unittest

import config
from notifications import dashboard as dm


class _State:
    meta = {"goal_raw": "Build the lab", "status": "executing", "control_mode": "watch",
            "started_at": None, "work_dir": "C:/9to5"}
    subtasks = [{"subtask_id": "st-001", "title": "a", "status": "in_progress"}]
    data = {"notifications": [], "adversary_reviews": []}


class CockpitImageThrottle(unittest.TestCase):
    def setUp(self):
        self._flags = (config.VISUALS_ENABLED, config.DASHBOARD_CV2, config.COCKPIT_IMAGE_MIN_INTERVAL)
        config.VISUALS_ENABLED = True
        config.DASHBOARD_CV2 = True
        config.COCKPIT_IMAGE_MIN_INTERVAL = 30

    def tearDown(self):
        config.VISUALS_ENABLED, config.DASHBOARD_CV2, config.COCKPIT_IMAGE_MIN_INTERVAL = self._flags

    def test_first_includes_image_then_throttled(self):
        d = dm.DiscordDashboard()
        _, files1 = d._cockpit(_State(), "executing")
        self.assertIsNotNone(files1)                      # first render uploads the image
        self.assertEqual(files1[0][0], "cockpit.png")

        _, files2 = d._cockpit(_State(), "executing")
        self.assertIsNone(files2)                         # rapid second tick: throttled (text-CV2 only)

    def test_refreshes_after_interval(self):
        d = dm.DiscordDashboard()
        d._cockpit(_State(), "executing")                 # primes _last_image_ts
        d._last_image_ts -= 31                            # simulate >interval elapsed
        _, files = d._cockpit(_State(), "executing")
        self.assertIsNotNone(files)                       # image refreshes after the interval

    def test_text_cockpit_always_built(self):
        d = dm.DiscordDashboard()
        comps, _ = d._cockpit(_State(), "executing")
        # the CV2 container is always present regardless of image throttling
        self.assertEqual(comps[0]["type"], 17)

    def test_disabled_never_uploads(self):
        config.VISUALS_ENABLED = False
        d = dm.DiscordDashboard()
        _, files = d._cockpit(_State(), "executing")
        self.assertIsNone(files)
