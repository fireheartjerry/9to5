"""Unit tests for the branding design system + embed builders."""
import unittest

import config
from notifications import branding, commands
from notifications import discord_bot as discord
from state.task import TaskState


class _Bus:
    def getPendingGate(self):
        return None


def _state():
    st = TaskState.create("build a thing", 1.0)
    st.addSubtask("first", "d")
    st.addSubtask("second", "d")
    return st


class TestBranding(unittest.TestCase):
    def test_brand_embed_defaults(self):
        e = branding.brandEmbed("Title")
        self.assertEqual(e["title"], "Title")
        self.assertEqual(e["color"], config.BRAND_COLOR)
        self.assertIn("author", e)
        self.assertIn("footer", e)

    def test_help_lists_all_registry_commands(self):
        e = branding.helpEmbed()
        blob = (e.get("description", "") + " " +
                " ".join(f["value"] for f in e["fields"]))
        for name in commands.COMMAND_REGISTRY:
            self.assertIn(f"/{name}", blob, name)

    def test_status_embed_within_limits(self):
        e = discord._clampEmbed(branding.statusEmbed(_state(), _Bus()))
        self.assertTrue(e["title"])
        for f in e["fields"]:
            self.assertLessEqual(len(f["value"]), config.DISCORD_MAX_FIELD_VALUE)

    def test_plan_pagination_math(self):
        st = TaskState.create("g", 1.0)
        for i in range(25):
            st.addSubtask(f"t{i}", "d")
        _, pages = branding.planEmbed(st, page=0, per=10)
        self.assertEqual(pages, 3)
        e2, _ = branding.planEmbed(st, page=99, per=10)   # clamps to last page
        self.assertIn("3/3", e2["title"])

    def test_runs_pagination(self):
        sums = [{"task_id": f"id{i:02d}aaaa", "status": "done", "done": 1, "total": 1,
                 "goal": "g"} for i in range(20)]
        _, pages = branding.runsEmbed(sums, 0, 8)
        self.assertEqual(pages, 3)

    def test_metrics_embed_handles_none(self):
        e = branding.metricsEmbed({"total_runs": 0, "by_status": {}, "terminal_runs": 0,
                                   "success_runs": 0, "success_rate": None,
                                   "avg_duration_seconds": None, "subtasks_total": 0,
                                   "subtasks_passed": 0})
        self.assertTrue(e["fields"])

    def test_diagnostics_embed(self):
        e = branding.diagnosticsEmbed([{"name": "x", "ok": True, "detail": "ok", "fix": ""},
                                       {"name": "y", "ok": False, "detail": "bad", "fix": "do z"}])
        self.assertIn("1/2", e["title"])

    def test_control_panel_row_ids(self):
        rows = branding.controlPanelRow()
        ids = [c["custom_id"] for row in rows for c in row["components"]]
        self.assertEqual(set(ids), set(branding.CONTROL_PANEL_IDS.values()))


if __name__ == "__main__":
    unittest.main()
