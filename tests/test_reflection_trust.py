"""Task 4.3 — reflection.trust() must reject stub/degraded adversary anchors."""
import unittest
from learning import reflection

# A minimal summary dict -- trust() checks isinstance(dict) as first guard.
_SUMMARY = {"approach": "did the thing", "confidence": 0.9}


class TestTrust(unittest.TestCase):
    def test_stub_adversary_is_not_trusted(self):
        # verify passed, adversary "approved" but it was a STUB -> not trusted.
        self.assertFalse(reflection.trust(_SUMMARY, verify_passed=True,
                                          adversary_verdict="approved",
                                          adversary_stub=True))

    def test_real_approval_is_trusted(self):
        # verify passed + real (non-stub) approval -> trusted.
        self.assertTrue(reflection.trust(_SUMMARY, verify_passed=True,
                                         adversary_verdict="approved",
                                         adversary_stub=False))

    def test_failed_verify_never_trusted(self):
        # failed verify, even with real approval -> not trusted.
        self.assertFalse(reflection.trust(_SUMMARY, verify_passed=False,
                                          adversary_verdict="approved",
                                          adversary_stub=False))
