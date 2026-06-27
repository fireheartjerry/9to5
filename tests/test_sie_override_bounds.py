import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config


class TestOverrideBounds(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self._orig_heartbeat = config.ADVERSARY_HEARTBEAT_EVERY
        mock.patch.object(config, "SIE_OVERRIDES_PATH", self.dir / "sie_overrides.json").start()

    def tearDown(self):
        mock.patch.stopall()
        config.ADVERSARY_HEARTBEAT_EVERY = self._orig_heartbeat
        for p in self.dir.glob("*"):
            p.unlink()
        self.dir.rmdir()

    def test_out_of_range_value_rejected(self):
        # ADVERSARY_HEARTBEAT_EVERY=9999 (review-disabling) must be refused.
        self.assertFalse(config.set_override("ADVERSARY_HEARTBEAT_EVERY", 9999))

    def test_in_range_value_accepted(self):
        self.assertTrue(config.set_override("ADVERSARY_HEARTBEAT_EVERY", 3))

    def test_unknown_knob_rejected(self):
        self.assertFalse(config.set_override("PROJECT_ROOT", "C:/evil"))


if __name__ == "__main__":
    unittest.main()
