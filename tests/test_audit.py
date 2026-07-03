"""Unit tests for the file-backed audit log."""
import pathlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Allow `python tests/test_audit.py` from any working directory.
_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config
from notifications import audit


class TestAudit(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.path = self.dir / "audit.jsonl"

    def tearDown(self):
        for p in self.dir.glob("*"):
            p.unlink()
        self.dir.rmdir()

    def test_record_and_recent(self):
        with mock.patch.object(config, "AUDIT_LOG_PATH", self.path):
            audit.record(777, "abort", "task-1")
            audit.record(777, "pause", "task-1", "button")
            entries = audit.recent(10)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[-1]["action"], "pause")
        self.assertEqual(entries[-1]["detail"], "button")
        self.assertEqual(entries[0]["user_id"], "777")

    def test_recent_empty_when_no_file(self):
        with mock.patch.object(config, "AUDIT_LOG_PATH", self.dir / "nope.jsonl"):
            self.assertEqual(audit.recent(), [])

    def test_rotation(self):
        with mock.patch.object(config, "AUDIT_LOG_PATH", self.path), \
                mock.patch.object(config, "AUDIT_MAX_BYTES", 50):
            for i in range(30):
                audit.record(1, f"act{i}", "t")
            self.assertTrue((self.dir / "audit.jsonl.1").exists())
            self.assertTrue(audit.recent(5))   # still works after rotation

    def test_concurrent_rotations_are_serialized(self):
        # Fresh bug hunt: the rotate-check + replace + append sequence was unlocked, so two
        # near-simultaneous callers could both observe size > AUDIT_MAX_BYTES and race
        # path.replace() to the same ".1" destination -- the loser's replace (or append to a
        # path the winner just moved) raises, silently dropping that audit entry (swallowed by
        # record()'s outer except). Directly verify mutual exclusion over the critical section
        # (rotate-check -> replace -> append) rather than relying on real filesystem timing.
        import threading
        import time
        real_replace = Path.replace
        events: list = []

        def slow_replace(self_path, target):
            events.append(("start", threading.get_ident()))
            time.sleep(0.02)   # widen the race window so an unlocked version reliably overlaps
            result = real_replace(self_path, target)
            events.append(("end", threading.get_ident()))
            return result

        with mock.patch.object(config, "AUDIT_LOG_PATH", self.path), \
                mock.patch.object(config, "AUDIT_MAX_BYTES", 1), \
                mock.patch.object(Path, "replace", slow_replace):
            self.path.write_text('{"seed": true}\n', encoding="utf-8")

            def worker(tid):
                audit.record(tid, f"act-{tid}")

            threads = [threading.Thread(target=worker, args=(t,)) for t in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        # No two threads' rotate-critical-sections may overlap: depth must never exceed 1.
        depth = 0
        for kind, _tid in events:
            depth += 1 if kind == "start" else -1
            self.assertLessEqual(depth, 1, "concurrent audit rotations were not serialized")
        self.assertGreaterEqual(len(events), 2, "test setup did not exercise rotation at all")


if __name__ == "__main__":
    unittest.main()
