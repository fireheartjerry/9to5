"""Unit tests for learning/adversary_trust.py -- torn-line resilience (B23) + basic aggregation."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from learning import adversary_trust


class TestTrustLogResilience(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.log = self.dir / "adversary_trust.jsonl"
        self._p = mock.patch.object(config, "ADVERSARY_TRUST_LOG", self.log)
        self._p.start()

    def tearDown(self):
        self._p.stop()
        for p in sorted(self.dir.rglob("*"), reverse=True):
            if p.is_file():
                p.unlink()
            elif p.is_dir():
                p.rmdir()
        self.dir.rmdir()

    def _write(self, lines):
        self.log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_one_torn_line_does_not_sink_the_whole_log(self):
        good1 = json.dumps({"tier": "gpt", "verdict": "approved"})
        good2 = json.dumps({"tier": "ollama", "verdict": "challenged"})
        torn = '{"tier": "gpt", "verdict": "app'   # interrupted append -> invalid JSON
        self._write([good1, torn, good2])
        rows = adversary_trust._rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["tier"] for r in rows}, {"gpt", "ollama"})

    def test_summary_ignores_torn_line(self):
        self._write([json.dumps({"tier": "gpt", "verdict": "challenged"}),
                     '{ broken',
                     json.dumps({"tier": "gpt", "verdict": "approved"})])
        s = adversary_trust.summary()
        self.assertEqual(s["consults"], 2)
        self.assertEqual(s["gpt"], 2)
        self.assertEqual(s["challenges"], 1)

    def test_record_then_read_roundtrip(self):
        adversary_trust.record("spec", {"tier": "gpt", "verdict": "approved", "severity": "low"})
        adversary_trust.record("spec", {"tier": "ollama", "verdict": "challenged"})
        rows = adversary_trust._rows()
        self.assertEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main()
