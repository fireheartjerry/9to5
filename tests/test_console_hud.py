"""Tests for the ANSI mission-console HUD (T8): valid ```ansi block, live fields, never raises."""
import unittest

from notifications import console_hud


class _StubState:
    def __init__(self, statuses=("done", "done", "in_progress", "pending")):
        self.meta = {"goal_raw": "Build the lab", "status": "executing",
                     "control_mode": "watch", "started_at": None}
        self.subtasks = [{"subtask_id": f"st-{i:03d}", "title": f"t{i}", "status": s,
                          "verify_result": ({"passed": True} if s == "done" else None)}
                         for i, s in enumerate(statuses, 1)]
        self.data = {"notifications": [], "adversary_reviews": []}


class Hud(unittest.TestCase):
    def test_ansi_block_shape(self):
        out = console_hud.render(_StubState(), "executing")
        self.assertTrue(out.startswith("```ansi\n"))
        self.assertTrue(out.endswith("\n```"))
        self.assertIn("\x1b[", out)                       # contains SGR escape codes
        self.assertIn("MISSION CONSOLE", out)

    def test_live_fields(self):
        out = console_hud.render(_StubState(), "executing")
        self.assertIn("EXECUTING", out)                   # phase upper
        self.assertIn("st-003", out)                      # current subtask
        self.assertIn("50%", out)                         # 2/4 done
        self.assertIn("2/4", out)
        self.assertTrue("█" in out and "░" in out)        # progress bar glyphs

    def test_empty_subtasks(self):
        st = _StubState(())
        out = console_hud.render(st, "starting")
        self.assertIn("```ansi", out)
        self.assertIn("0/1", out)                          # total clamps to >=1

    def test_never_raises_on_broken_state(self):
        class Broken:
            meta = {}
            @property
            def subtasks(self):
                raise RuntimeError("boom")
            data = {}
        out = console_hud.render(Broken(), "executing")
        self.assertIn("console offline", out)


if __name__ == "__main__":
    unittest.main()
