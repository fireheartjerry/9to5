"""Final acceptance test: full notification system.

Aggregates all notification sub-suite tests and adds a final end-to-end
integration smoke-test to confirm the complete pipeline is healthy.

Run directly: python tests/test_full_notification_system.py
Acceptance:   exit code 0 iff all tests pass.
"""
from __future__ import annotations

import json
import logging
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ---------------------------------------------------------------------------
# Import all notification sub-suites so they are discovered by this runner
# ---------------------------------------------------------------------------

import tests.test_notification_bus            # noqa: F401 — registers test classes
import tests.test_notification_enhancements   # noqa: F401
import tests.test_notification_integration    # noqa: F401
import tests.test_notification_config         # noqa: F401
import tests.test_notification_docs           # noqa: F401


# ---------------------------------------------------------------------------
# Imports for the extra smoke tests defined here
# ---------------------------------------------------------------------------

import config
import notifications.audit as audit
from notifications.bus import NotificationBus, NotificationSurface
from notifications.entry import VALID_KINDS, makeEntry, validate, isValid


# ---------------------------------------------------------------------------
# Helper surfaces
# ---------------------------------------------------------------------------

class _Cap:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def handle(self, event_type: str, payload: dict) -> None:
        self.calls.append((event_type, payload))


class _Bomb:
    def handle(self, event_type: str, payload: dict) -> None:
        raise RuntimeError("intentional bomb")


# ---------------------------------------------------------------------------
# Full end-to-end smoke tests
# ---------------------------------------------------------------------------

class TestFullPipelineSmoke(unittest.TestCase):
    """End-to-end smoke tests covering the entire notification pipeline."""

    def test_full_lifecycle_via_bus(self):
        """All canonical lifecycle events transit through the bus correctly."""
        bus = NotificationBus()
        cap = _Cap()
        bus.register(cap)

        lifecycle = [
            "planning_start",
            "architect_done",
            "subtask_done",
            "adversary_triggered",
            "replan",
            "subtask_failed",
            "complete",
        ]
        for kind in lifecycle:
            entry = makeEntry(kind, f"smoke: {kind}")
            self.assertTrue(isValid(entry), f"makeEntry({kind!r}) produced invalid entry")
            bus.emit(entry["kind"], entry)

        self.assertEqual(len(cap.calls), len(lifecycle))
        received = [c[0] for c in cap.calls]
        self.assertEqual(received, lifecycle)

    def test_isolation_and_fan_out_together(self):
        """Failing surface between two good surfaces: both good ones receive all events."""
        bus = NotificationBus()
        a = _Cap()
        b = _Cap()
        bus.register(a)
        bus.register(_Bomb())
        bus.register(b)

        for kind in ("planning_start", "complete"):
            bus.emit(kind, makeEntry(kind, "test"))

        self.assertEqual([c[0] for c in a.calls], ["planning_start", "complete"])
        self.assertEqual([c[0] for c in b.calls], ["planning_start", "complete"])

    def test_concurrent_emit_no_drops_or_exceptions(self):
        """100 concurrent emits across 5 threads reach the single surface."""
        bus = NotificationBus()
        cap = _Cap()
        bus.register(cap)
        errors: list[Exception] = []

        def _worker(idx: int) -> None:
            try:
                for i in range(20):
                    bus.emit("subtask_done", makeEntry("subtask_done", f"t{idx}-{i}"))
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=_worker, args=(k,)) for k in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        self.assertEqual(len(cap.calls), 100)

    def test_entry_json_roundtrip_all_required_kinds(self):
        """Every VALID_KIND produces a JSON-serialisable, schema-valid entry."""
        for kind in VALID_KINDS:
            with self.subTest(kind=kind):
                entry = makeEntry(kind, f"roundtrip {kind}", extra_key="val")
                serialised = json.dumps(entry)
                restored = json.loads(serialised)
                self.assertEqual(validate(restored), [])
                self.assertEqual(restored["kind"], kind)
                self.assertEqual(restored["extra_key"], "val")

    def test_surface_count_tracks_registrations(self):
        bus = NotificationBus()
        self.assertEqual(bus.surface_count, 0)
        for i in range(1, 6):
            bus.register(_Cap())
            self.assertEqual(bus.surface_count, i)

    def test_system_exit_in_surface_never_propagates(self):
        class _SysExitSurface:
            def handle(self, et: str, p: dict) -> None:
                raise SystemExit(42)

        bus = NotificationBus()
        bus.register(_SysExitSurface())
        cap = _Cap()
        bus.register(cap)
        try:
            bus.emit("complete", {})
        except SystemExit:
            self.fail("SystemExit propagated out of bus.emit")
        self.assertEqual(len(cap.calls), 1)

    def test_isvalid_gate_pattern(self):
        """Only valid entries are emitted (guard pattern used in production)."""
        bus = NotificationBus()
        cap = _Cap()
        bus.register(cap)

        good = makeEntry("replan", "valid")
        bad_missing_at = {"kind": "replan", "detail": "x"}
        bad_empty_kind = makeEntry("complete", "ok")
        bad_empty_kind["kind"] = ""

        for entry in (good, bad_missing_at, bad_empty_kind):
            if isValid(entry):
                bus.emit(entry["kind"], entry)

        self.assertEqual(len(cap.calls), 1)
        self.assertEqual(cap.calls[0][0], "replan")

    def test_audit_record_and_recent_roundtrip(self):
        """audit.record() + audit.recent() produce consistent results."""
        tmp = tempfile.mkdtemp()
        path = Path(tmp) / "audit.jsonl"
        with mock.patch.object(config, "AUDIT_LOG_PATH", path):
            audit.record(99, "abort", "task-smoke", "final test")
            audit.record(99, "resume", "task-smoke")
            rows = audit.recent(10)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["action"], "abort")
        self.assertEqual(rows[0]["task_id"], "task-smoke")
        self.assertEqual(rows[0]["detail"], "final test")
        self.assertEqual(rows[1]["action"], "resume")
        # Every row must have a parseable 'at' timestamp
        for row in rows:
            datetime.fromisoformat(row["at"])  # must not raise

    def test_docs_exist_and_cover_key_terms(self):
        """notification_system.md exists and mentions the core API symbols."""
        doc = _ROOT / "docs" / "notification_system.md"
        self.assertTrue(doc.exists(), "docs/notification_system.md not found")
        text = doc.read_text(encoding="utf-8")
        for term in ("NotificationBus", "makeEntry", "isValid", "VALID_KINDS",
                     "NotificationSurface", "suppress"):
            self.assertIn(term, text, f"doc missing {term!r}")

    def test_module_import_health(self):
        """All notification modules are importable without side effects."""
        for mod in (
            "notifications.bus",
            "notifications.entry",
            "notifications.audit",
            "notifications.dashboard",
            "notifications.webdash",
        ):
            with self.subTest(module=mod):
                __import__(mod)

    def test_config_notification_constants_present(self):
        """Key notification config constants exist and are sensible."""
        self.assertIsInstance(config.DISCORD_DASHBOARD, bool)
        self.assertIsInstance(config.WEB_DASHBOARD, bool)
        self.assertGreater(config.WEB_DASHBOARD_PORT, 1024)
        self.assertGreater(config.DISCORD_REST_TIMEOUT, 0)
        self.assertIsInstance(config.AUDIT_LOG_PATH, Path)
        self.assertEqual(config.DISCORD_MAX_CONTENT, 2000)
        self.assertEqual(config.DISCORD_EMBED_TOTAL_MAX, 6000)

    def test_notification_surface_protocol_runtime_checkable(self):
        """NotificationSurface is @runtime_checkable."""
        self.assertIsInstance(_Cap(), NotificationSurface)
        self.assertIsInstance(_Bomb(), NotificationSurface)

        class _NoHandle:
            pass

        self.assertNotIsInstance(_NoHandle(), NotificationSurface)


# ---------------------------------------------------------------------------
# Entry point: run all tests and exit with appropriate code
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Discover sub-suite modules registered above + the smoke tests in this file
    loader = unittest.TestLoader()
    suite = loader.discover(str(_ROOT / "tests"), pattern="test_notification*.py")
    # Also explicitly add this module's smoke tests in case discovery misses them
    suite.addTests(loader.loadTestsFromModule(sys.modules[__name__]))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
