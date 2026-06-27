"""Notification system enhancements — Part A.

Covers:
  - NotificationBus.surface_count property
  - notifications.entry.isValid() convenience helper
  - Entry JSON roundtrip
  - Audit trail integration (entries are JSON-serialisable)

Split from test_notification_enhancements.py (was 400 lines).
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config
import notifications.audit as audit
from notifications.bus import NotificationBus, NotificationSurface
from notifications.entry import VALID_KINDS, isValid, makeEntry, validate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _Cap:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def handle(self, event_type: str, payload: dict) -> None:
        self.calls.append((event_type, payload))


class _Fail:
    def handle(self, event_type: str, payload: dict) -> None:
        raise ValueError("intentional failure")


class _SlowFail:
    """Raises a non-standard exception type."""
    def handle(self, event_type: str, payload: dict) -> None:
        raise SystemExit(1)  # extreme — must still be caught


# ---------------------------------------------------------------------------
# 1. surface_count property
# ---------------------------------------------------------------------------

class TestSurfaceCount(unittest.TestCase):
    def test_empty_bus_count_is_zero(self):
        bus = NotificationBus()
        self.assertEqual(bus.surface_count, 0)

    def test_count_increments_per_registration(self):
        bus = NotificationBus()
        for i in range(5):
            bus.register(_Cap())
            self.assertEqual(bus.surface_count, i + 1)

    def test_same_surface_registered_twice_counts_twice(self):
        bus = NotificationBus()
        cap = _Cap()
        bus.register(cap)
        bus.register(cap)
        self.assertEqual(bus.surface_count, 2)

    def test_count_unchanged_after_emit(self):
        bus = NotificationBus()
        bus.register(_Cap())
        bus.emit("replan", {})
        self.assertEqual(bus.surface_count, 1)

    def test_count_unchanged_after_failing_emit(self):
        bus = NotificationBus()
        bus.register(_Fail())
        try:
            bus.emit("replan", {})
        except Exception:  # noqa: BLE001
            pass
        self.assertEqual(bus.surface_count, 1)


# ---------------------------------------------------------------------------
# 2. isValid() convenience helper
# ---------------------------------------------------------------------------

class TestIsValid(unittest.TestCase):
    def test_valid_entry_returns_true(self):
        entry = makeEntry("complete", "run finished")
        self.assertTrue(isValid(entry))

    def test_missing_key_returns_false(self):
        self.assertFalse(isValid({"kind": "replan", "detail": "x"}))

    def test_bad_at_returns_false(self):
        self.assertFalse(isValid({"at": "not-a-date", "kind": "replan", "detail": "x"}))

    def test_empty_kind_returns_false(self):
        self.assertFalse(isValid({
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "kind": "",
            "detail": "x",
        }))

    def test_non_dict_returns_false(self):
        self.assertFalse(isValid("not-a-dict"))  # type: ignore[arg-type]

    def test_all_valid_kinds_return_true(self):
        for kind in VALID_KINDS:
            with self.subTest(kind=kind):
                self.assertTrue(isValid(makeEntry(kind, "detail")))

    def test_isvalid_consistent_with_validate(self):
        entries = [
            makeEntry("replan", "x"),
            {"kind": "bad", "detail": "x"},
            {"at": "2026-01-01T00:00:00+00:00", "kind": "complete", "detail": "ok"},
        ]
        for entry in entries:
            with self.subTest(entry=entry):
                self.assertEqual(isValid(entry), validate(entry) == [])


# ---------------------------------------------------------------------------
# 3. Entry JSON roundtrip
# ---------------------------------------------------------------------------

class TestEntryJsonRoundtrip(unittest.TestCase):
    def test_entry_is_json_serialisable(self):
        entry = makeEntry("subtask_done", "st-001 completed", attempt=1)
        serialised = json.dumps(entry)
        self.assertIsInstance(serialised, str)

    def test_roundtrip_preserves_required_fields(self):
        entry = makeEntry("replan", "added 2 subtasks")
        restored = json.loads(json.dumps(entry))
        self.assertTrue(isValid(restored))
        self.assertEqual(restored["kind"], entry["kind"])
        self.assertEqual(restored["detail"], entry["detail"])
        self.assertEqual(restored["at"], entry["at"])

    def test_roundtrip_preserves_extra_fields(self):
        entry = makeEntry("adversary_triggered", "heartbeat", verdict="approved", attempt=3)
        restored = json.loads(json.dumps(entry))
        self.assertEqual(restored["verdict"], "approved")
        self.assertEqual(restored["attempt"], 3)

    def test_entry_at_is_utc(self):
        entry = makeEntry("complete", "done")
        parsed = datetime.fromisoformat(entry["at"])
        self.assertIsNotNone(parsed.tzinfo)
        self.assertEqual(parsed.utcoffset().total_seconds(), 0)


# ---------------------------------------------------------------------------
# 4. Audit integration
# ---------------------------------------------------------------------------

class TestAuditIntegration(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._path = Path(self._tmp) / "audit.jsonl"
        self._patch = mock.patch.object(config, "AUDIT_LOG_PATH", self._path)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_record_produces_json_line(self):
        audit.record(123, "abort", "task-1", "web button")
        lines = self._path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        row = json.loads(lines[0])
        self.assertEqual(row["action"], "abort")
        self.assertEqual(row["user_id"], "123")
        self.assertEqual(row["task_id"], "task-1")
        self.assertEqual(row["detail"], "web button")

    def test_record_entry_has_at_field(self):
        audit.record(1, "pause", "task-x")
        row = json.loads(self._path.read_text(encoding="utf-8").splitlines()[0])
        self.assertIn("at", row)
        datetime.fromisoformat(row["at"])  # must not raise

    def test_recent_returns_n_entries(self):
        for i in range(10):
            audit.record(i, f"action-{i}", "t")
        result = audit.recent(5)
        self.assertEqual(len(result), 5)

    def test_recent_empty_on_missing_file(self):
        missing = Path(self._tmp) / "no_such_file.jsonl"
        with mock.patch.object(config, "AUDIT_LOG_PATH", missing):
            self.assertEqual(audit.recent(), [])

    def test_record_does_not_raise_on_bad_path(self):
        bad = Path(self._tmp) / "nonexistent_dir" / "deep" / "audit.jsonl"
        with mock.patch.object(config, "AUDIT_LOG_PATH", bad):
            audit.record(1, "abort", "t")  # must not raise

    def test_multiple_records_accumulate(self):
        for action in ("abort", "pause", "resume"):
            audit.record(1, action, "t")
        result = audit.recent(10)
        self.assertEqual(len(result), 3)
        self.assertEqual([r["action"] for r in result], ["abort", "pause", "resume"])


if __name__ == "__main__":
    import unittest as _ut
    loader = _ut.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = _ut.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
