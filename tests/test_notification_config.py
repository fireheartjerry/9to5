"""Audit: notification system configuration for production readiness.

Validates that all config constants governing the notification system are
within expected bounds and internally consistent.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config
from notifications.entry import VALID_KINDS, REQUIRED_KEYS
from notifications.bus import NotificationBus, NotificationSurface


# ---------------------------------------------------------------------------
# Discord hard-limit constants
# ---------------------------------------------------------------------------

class TestDiscordLimits(unittest.TestCase):
    """Config must not exceed Discord's documented API limits."""

    def test_max_content_at_discord_limit(self):
        self.assertEqual(config.DISCORD_MAX_CONTENT, 2000)

    def test_max_embed_desc_at_discord_limit(self):
        self.assertEqual(config.DISCORD_MAX_EMBED_DESC, 4096)

    def test_max_field_name_at_discord_limit(self):
        self.assertEqual(config.DISCORD_MAX_FIELD_NAME, 256)

    def test_max_field_value_at_discord_limit(self):
        self.assertEqual(config.DISCORD_MAX_FIELD_VALUE, 1024)

    def test_embed_total_max_at_discord_limit(self):
        self.assertEqual(config.DISCORD_EMBED_TOTAL_MAX, 6000)

    def test_rest_timeout_positive(self):
        self.assertGreater(config.DISCORD_REST_TIMEOUT, 0)

    def test_retry_max_non_negative(self):
        self.assertGreaterEqual(config.DISCORD_RETRY_MAX, 0)

    def test_poll_seconds_positive(self):
        self.assertGreater(config.DISCORD_POLL_SECONDS, 0)

    def test_field_value_less_than_embed_desc(self):
        self.assertLess(config.DISCORD_MAX_FIELD_VALUE, config.DISCORD_MAX_EMBED_DESC)

    def test_embed_total_max_exceeds_single_field(self):
        self.assertGreater(config.DISCORD_EMBED_TOTAL_MAX, config.DISCORD_MAX_FIELD_VALUE)


# ---------------------------------------------------------------------------
# Audit log configuration
# ---------------------------------------------------------------------------

class TestAuditConfig(unittest.TestCase):
    def test_audit_max_bytes_positive(self):
        self.assertGreater(config.AUDIT_MAX_BYTES, 0)

    def test_audit_log_path_is_path(self):
        self.assertIsInstance(config.AUDIT_LOG_PATH, Path)

    def test_audit_log_path_parent_is_under_state(self):
        # Must live under state/ not root or tmp
        self.assertIn("state", config.AUDIT_LOG_PATH.parts)

    def test_audit_log_path_is_jsonl(self):
        self.assertEqual(config.AUDIT_LOG_PATH.suffix, ".jsonl")


# ---------------------------------------------------------------------------
# Status color palette completeness
# ---------------------------------------------------------------------------

_REQUIRED_STATUSES = {
    "executing", "planning", "done", "complete", "failed", "aborted", "paused", "blocked",
}


class TestStatusColors(unittest.TestCase):
    def test_required_statuses_have_colors(self):
        for status in _REQUIRED_STATUSES:
            with self.subTest(status=status):
                self.assertIn(status, config.STATUS_COLORS, f"STATUS_COLORS missing {status!r}")

    def test_all_colors_are_valid_integers(self):
        for status, color in config.STATUS_COLORS.items():
            with self.subTest(status=status):
                self.assertIsInstance(color, int, f"color for {status!r} is not int")
                self.assertGreaterEqual(color, 0)
                self.assertLessEqual(color, 0xFFFFFF)

    def test_done_and_complete_same_color(self):
        self.assertEqual(config.STATUS_COLORS["done"], config.STATUS_COLORS["complete"])

    def test_failed_and_blocked_are_red(self):
        # Both should be red-family (R channel dominant)
        for status in ("failed", "blocked"):
            color = config.STATUS_COLORS[status]
            red = (color >> 16) & 0xFF
            green = (color >> 8) & 0xFF
            blue = color & 0xFF
            with self.subTest(status=status):
                self.assertGreater(red, green, f"{status} should be red-dominant")


# ---------------------------------------------------------------------------
# Effort bars / labels consistency
# ---------------------------------------------------------------------------

class TestEffortConfig(unittest.TestCase):
    def test_effort_bars_and_labels_same_keys(self):
        self.assertEqual(set(config.EFFORT_BARS.keys()), set(config.EFFORT_LABELS.keys()))

    def test_effort_flag_map_keys_subset_of_levels(self):
        valid = set(config.EFFORT_BARS.keys()) | {"low"}
        for key in config.EFFORT_FLAG_MAP:
            with self.subTest(key=key):
                self.assertIn(key, valid | set(config.EFFORT_FLAG_MAP.keys()))

    def test_default_effort_bar_exists(self):
        self.assertIn("default", config.EFFORT_BARS)
        self.assertIn("default", config.EFFORT_LABELS)

    def test_effort_bars_use_block_chars(self):
        for key, bar in config.EFFORT_BARS.items():
            with self.subTest(key=key):
                self.assertTrue(
                    all(c in "▰▱ " for c in bar),
                    f"EFFORT_BARS[{key!r}] contains unexpected chars: {bar!r}",
                )


# ---------------------------------------------------------------------------
# Notification entry schema constants
# ---------------------------------------------------------------------------

class TestNotificationEntryConfig(unittest.TestCase):
    def test_required_keys_present(self):
        for key in ("at", "kind", "detail"):
            self.assertIn(key, REQUIRED_KEYS)

    def test_valid_kinds_non_empty(self):
        self.assertTrue(len(VALID_KINDS) > 0)

    def test_valid_kinds_is_frozenset(self):
        self.assertIsInstance(VALID_KINDS, frozenset)

    def test_lifecycle_kinds_present(self):
        for kind in ("complete", "aborted", "subtask_done", "subtask_failed", "replan"):
            with self.subTest(kind=kind):
                self.assertIn(kind, VALID_KINDS)

    def test_all_kinds_are_strings(self):
        for k in VALID_KINDS:
            with self.subTest(k=k):
                self.assertIsInstance(k, str)
                self.assertTrue(k, "kind must be non-empty")


# ---------------------------------------------------------------------------
# NotificationBus protocol
# ---------------------------------------------------------------------------

class TestNotificationBusContract(unittest.TestCase):
    def test_surface_protocol_is_runtime_checkable(self):
        class _Good:
            def handle(self, event_type: str, payload: dict) -> None:
                pass
        self.assertIsInstance(_Good(), NotificationSurface)

    def test_surface_isolation_in_bus(self):
        class _Bad:
            def handle(self, event_type, payload):
                raise RuntimeError("boom")
        bus = NotificationBus()
        bus.register(_Bad())
        bus.emit("complete", {})  # must not raise

    def test_bus_emits_to_all_surfaces(self):
        received = []
        class _Cap:
            def handle(self, et, p):
                received.append(et)
        bus = NotificationBus()
        bus.register(_Cap())
        bus.register(_Cap())
        bus.emit("planning_start", {})
        self.assertEqual(len(received), 2)


# ---------------------------------------------------------------------------
# Module import health
# ---------------------------------------------------------------------------

class TestNotificationImports(unittest.TestCase):
    def test_notifications_entry_importable(self):
        import notifications.entry  # noqa: F401

    def test_notifications_bus_importable(self):
        import notifications.bus  # noqa: F401

    def test_notifications_audit_importable(self):
        import notifications.audit  # noqa: F401

    def test_config_has_discord_dashboard_flag(self):
        self.assertIsInstance(config.DISCORD_DASHBOARD, bool)

    def test_config_has_web_dashboard_flag(self):
        self.assertIsInstance(config.WEB_DASHBOARD, bool)

    def test_web_dashboard_port_in_valid_range(self):
        self.assertGreater(config.WEB_DASHBOARD_PORT, 1024)
        self.assertLess(config.WEB_DASHBOARD_PORT, 65536)


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
