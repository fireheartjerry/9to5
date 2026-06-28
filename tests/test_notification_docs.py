"""Audit: verify docs/notification_system.md and docs/notification_bus_error_handling.md
cover all canonical terms derived from the notification source modules.

Checks:
  notification_system.md:
  - All VALID_KINDS from entry.py appear in the doc
  - All REQUIRED_KEYS appear in the doc
  - All module file names appear in the doc
  - Key API symbols (classes, functions) appear in the doc
  - All embed builders listed in discord_bot section
  - All slash commands
  - All ! text commands
  - Web routes and control actions
  - Metrics return-shape keys
  - Audit schema keys
  - Embed size-limit values
  - editMessageResult return values
  - Validation error message fragments
  - Key config env-var names

  notification_bus_error_handling.md:
  - Core suppression mechanism, specific exception types
  - Isolation contract language, logging, surface_count helper
  - Anti-patterns, ControlBus guidance
"""
import pathlib
import re
import sys
import unittest

# Resolve project root regardless of CWD
_ROOT = pathlib.Path(__file__).parent.parent
_DOC = _ROOT / "docs" / "notification_system.md"
_BUS_DOC = _ROOT / "docs" / "notification_bus_error_handling.md"


def _doc() -> str:
    return _DOC.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# notification_system.md coverage
# ---------------------------------------------------------------------------

class TestNotificationDocsCoverage(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        assert _DOC.exists(), f"doc not found: {_DOC}"
        cls.text = _doc()

    def _check_all(self, label: str, terms: list[str]) -> None:
        missing = [t for t in terms if t not in self.text]
        self.assertFalse(
            missing,
            f"[{label}] missing from {_DOC.name}: {missing}",
        )

    # --- entry.py -------------------------------------------------------

    def test_valid_kinds_all_documented(self):
        sys.path.insert(0, str(_ROOT))
        from notifications.entry import VALID_KINDS
        self._check_all("VALID_KINDS", sorted(VALID_KINDS))

    def test_required_keys_documented(self):
        self._check_all("REQUIRED_KEYS", ["`at`", "`kind`", "`detail`"])

    def test_entry_api_symbols(self):
        self._check_all("entry API", ["makeEntry", "validate", "VALID_KINDS", "isValid"])

    def test_validation_error_fragments(self):
        self._check_all("validate() errors", [
            "missing required key",
            "not valid ISO-8601",
            "'kind' must be a non-empty string",
            "'detail' must be a str",
        ])

    # --- bus.py ---------------------------------------------------------

    def test_bus_symbols(self):
        self._check_all("bus API", [
            "NotificationBus",
            "NotificationSurface",
            "register",
            "emit",
            "@runtime_checkable",
        ])

    def test_isolation_contract_documented(self):
        self._check_all("isolation contract", ["suppressed", "WARNING"])

    def test_anti_patterns_documented(self):
        self._check_all("anti-patterns", [
            "module-level singleton",
            "recursive",   # "recursive emission is not guarded" may span a line break
        ])

    # --- module file names ---------------------------------------------

    def test_module_files_documented(self):
        self._check_all("module files", [
            "notifications/bus.py",
            "notifications/entry.py",
            "notifications/dashboard.py",
            "notifications/discord_bot.py",
            "notifications/webdash.py",
            "notifications/command_bot.py",
            "notifications/branding.py",
            "notifications/slash.py",
            "notifications/audit.py",
            "notifications/metrics.py",
        ])

    # --- dashboard.py --------------------------------------------------

    def test_dashboard_fields_documented(self):
        self._check_all("dashboard fields", [
            "Elapsed",
            "ETA",
            "Replans",
            "Adversary",
            "Effort",
            "Working dir",
            "Last verify",
            "Recent events",
        ])

    def test_dashboard_lifecycle_documented(self):
        self._check_all("dashboard lifecycle", ["dash.start", "dash.update", "dash.unpin"])

    def test_resilience_restart_values(self):
        self._check_all("editMessageResult", ['"ok"', '"not_found"', '"transient"'])

    def test_control_panel_buttons(self):
        self._check_all("control panel", ["Pause", "Resume", "Approve", "Reject", "Skip", "Abort"])

    # --- discord_bot.py embed builders --------------------------------

    def test_embed_builders_documented(self):
        self._check_all("embed builders", [
            "planningStartEmbed",
            "architectDoneEmbed",
            "adversaryTriggeredEmbed",
            "subtaskFailedEmbed",
            "completeEmbed",
            "abortedEmbed",
            "blockedEmbed",
            "blockedComponents",
            "gateNeededEmbed",
            "noticeEmbed",
            "selfRefEmbed",
        ])

    def test_night_mode_documented(self):
        self._check_all("night mode", ["NIGHT_MODE", "milestone"])

    def test_rate_limit_documented(self):
        self._check_all("rate limit", ["_RATE_LIMITED_UNTIL", "429", "_DISABLED"])

    def test_embed_size_limits_documented(self):
        self._check_all("embed size limits", ["4 096", "1 024", "6 000", "256", "25"])

    # --- branding.py --------------------------------------------------

    def test_branding_builders_documented(self):
        self._check_all("branding builders", [
            "brandEmbed",
            "statusEmbed",
            "planEmbed",
            "runsEmbed",
            "helpEmbed",
            "diagnosticsEmbed",
            "metricsEmbed",
            "pingEmbed",
            "auditEmbed",
            "controlPanelRow",
        ])

    # --- slash.py commands --------------------------------------------

    def test_slash_commands_documented(self):
        self._check_all("slash commands", [
            "/status", "/plan", "/log", "/help", "/runs", "/run",
            "/ping", "/diagnostics", "/metrics", "/audit",
            "/work", "/resume", "/abort", "/pause",
            "/approve", "/reject", "/skip", "/add", "/retry",
        ])

    def test_slash_mutating_audited(self):
        self._check_all("slash audit", ["audit.record"])

    # --- command_bot.py ! commands ------------------------------------

    def test_bang_commands_documented(self):
        self._check_all("! commands", [
            "!status", "!plan", "!log", "!abort", "!pause", "!resume",
            "!approve", "!reject", "!skip", "!add", "!retry", "!help",
        ])

    def test_command_bot_auth_documented(self):
        self._check_all("command bot auth", ["DISCORD_HUMAN_USER_ID"])

    # --- webdash.py ---------------------------------------------------

    def test_web_routes_documented(self):
        self._check_all("web routes", ["/api/state", "/api/control"])

    def test_web_control_actions_documented(self):
        self._check_all("web control actions", [
            '"abort"', '"pause"', '"resume"', '"approve"', '"reject"', '"skip"',
        ])

    def test_snapshot_ttl_documented(self):
        self._check_all("snapshot TTL", ["1 second", "TTL"])

    def test_web_port_documented(self):
        self._check_all("web port", ["8787", "WEB_DASHBOARD_PORT"])

    # --- audit.py -----------------------------------------------------

    def test_audit_api_documented(self):
        self._check_all("audit API", ["record", "recent"])

    def test_audit_schema_keys_documented(self):
        self._check_all("audit schema", [
            '"at"', '"user_id"', '"action"', '"task_id"', '"detail"',
        ])

    def test_audit_config_documented(self):
        self._check_all("audit config", ["AUDIT_LOG_PATH", "AUDIT_MAX_BYTES"])

    # --- metrics.py ---------------------------------------------------

    def test_metrics_return_keys_documented(self):
        self._check_all("metrics keys", [
            "total_runs", "by_status", "terminal_runs", "success_runs",
            "success_rate", "avg_duration_seconds", "subtasks_total", "subtasks_passed",
        ])

    def test_metrics_api_documented(self):
        self._check_all("metrics API", ["compute()"])

    # --- conventions --------------------------------------------------

    def test_conventions_documented(self):
        self._check_all("conventions", [
            "ALL_CAPS", "snake_case", "camelCase", "pathlib.Path",
            "best-effort",
        ])

    def test_secrets_policy_documented(self):
        self._check_all("secrets", ["DISCORD_BOT_TOKEN", "DISCORD_CHANNEL_ID", ".env"])

    # --- architecture overview ----------------------------------------

    def test_architecture_overview_present(self):
        self._check_all("architecture overview", [
            "NotificationBus.emit",
            "DiscordDashboard.handle",
            "WebdashSurface.handle",
        ])


# ---------------------------------------------------------------------------
# notification_bus_error_handling.md coverage
# ---------------------------------------------------------------------------

REQUIRED_BUS_TERMS = [
    # Core suppression mechanism
    "BaseException",
    "suppressed",
    # Specific exception types that must be documented
    "KeyboardInterrupt",
    "SystemExit",
    # Isolation contract language
    "surface",
    "emit",
    # Logging
    "WARNING",
    "notifications.bus",
    # surface_count helper
    "surface_count",
    # Anti-patterns
    "Anti-pattern",
    # ControlBus guidance
    "ControlBus",
]


class TestNotificationBusDocs(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        assert _BUS_DOC.exists(), f"doc not found: {_BUS_DOC}"
        cls.text = _BUS_DOC.read_text(encoding="utf-8")

    def _check_all(self, label: str, terms: list) -> None:
        missing = [t for t in terms if t not in self.text]
        self.assertFalse(missing, f"[{label}] missing from {_BUS_DOC.name}: {missing}")

    def test_doc_exists(self):
        self.assertTrue(_BUS_DOC.exists(), f"documentation file not found: {_BUS_DOC}")

    def test_required_terms_present(self):
        self._check_all("required error-handling terms", REQUIRED_BUS_TERMS)

    def test_keyboard_interrupt_documented(self):
        self.assertIn(
            "KeyboardInterrupt",
            self.text,
            "doc must explain KeyboardInterrupt suppression inside surfaces",
        )

    def test_system_exit_documented(self):
        self.assertIn(
            "SystemExit",
            self.text,
            "doc must explain SystemExit suppression inside surfaces",
        )

    def test_base_exception_documented(self):
        self.assertIn(
            "BaseException",
            self.text,
            "doc must document that BaseException (not Exception) is caught",
        )

    def test_what_is_not_suppressed(self):
        self.assertIn(
            "NOT suppressed",
            self.text,
            "doc must explain what errors are NOT suppressed by emit()",
        )

    def test_logging_table_present(self):
        self._check_all("logging behaviour", ["WARNING", "notifications.bus", "exception()"])

    def test_surface_count_documented(self):
        self.assertIn("surface_count", self.text, "doc must document the surface_count helper")

    def test_anti_patterns_present(self):
        self._check_all("anti-patterns section", [
            "Anti-pattern",
            "recursive",
            "singleton",
        ])

    def test_controlbus_guidance_present(self):
        self.assertIn(
            "ControlBus",
            self.text,
            "doc must direct surface authors to use ControlBus for shutdown signals",
        )

    def test_quick_reference_present(self):
        self._check_all("quick reference", ["NotificationBus", "register", "emit"])

    def test_h2_headers_present(self):
        """Doc must use H2 section headers for key topics."""
        required_headers = [
            "## The isolation contract",
            "## KeyboardInterrupt and SystemExit inside a surface",
            "## What is NOT suppressed",
            "## Logging behaviour",
            "## Guidance for surface authors",
            "## Anti-patterns",
            "## ControlBus for shutdown signals",
            "## Quick reference",
        ]
        missing = [h for h in required_headers if h not in self.text]
        self.assertFalse(missing, f"missing H2 headers in {_BUS_DOC.name}: {missing}")

    def test_code_blocks_present(self):
        """Doc must contain fenced code blocks for examples."""
        blocks = re.findall(r"^```", self.text, re.MULTILINE)
        self.assertGreaterEqual(
            len(blocks), 4,
            "doc must have at least 4 fenced code block delimiters (opening+closing pairs = 2+ examples)",
        )

    def test_deadlock_mechanism_documented(self):
        """Doc must explicitly name the deadlock risk of recursive emit() calls."""
        self.assertIn(
            "deadlock",
            self.text.lower(),
            "doc must document the deadlock mechanism caused by recursive bus.emit() inside handle()",
        )


if __name__ == "__main__":
    unittest.main()
