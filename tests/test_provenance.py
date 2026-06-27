# tests/test_provenance.py
"""The provenance tag + the assertIngestible chokepoint."""
import unittest

import platform_core.core.provenance as provenance
from platform_core.core.provenance import Provenance, Origin, Verdict


class TestProvenanceValue(unittest.TestCase):
    def test_roundtrips_through_dict(self):
        p = Provenance(origin=Origin.EXECUTOR, authoring_task_id="t1")
        self.assertEqual(Provenance.fromDict(p.toDict()), p)

    def test_unknown_dict_degrades_to_executor_origin(self):
        # Missing/garbage provenance must default to the LEAST-trusted origin, never human.
        self.assertEqual(provenance.coerce(None).origin, Origin.EXECUTOR)
        self.assertEqual(provenance.coerce({"origin": "nonsense"}).origin, Origin.EXECUTOR)


class TestAssertIngestible(unittest.TestCase):
    def test_obey_path_refuses_executor_origin(self):
        d = provenance.assertIngestible("knowledge/recommendations.md", "obey",
                                        Provenance(origin=Origin.EXECUTOR))
        self.assertEqual(d.verdict, Verdict.QUARANTINE)

    def test_obey_path_allows_human(self):
        d = provenance.assertIngestible("~/.claude/CLAUDE.md", "obey",
                                        Provenance(origin=Origin.HUMAN))
        self.assertEqual(d.verdict, Verdict.ALLOW)

    def test_believe_path_maps_unattested_to_neutral(self):
        # A stub/unattested verdict must NOT count as positive evidence.
        d = provenance.assertIngestible("gold_examples", "believe",
                                        Provenance(origin=Origin.EXECUTOR, attested_by=None))
        self.assertEqual(d.verdict, Verdict.NEUTRAL)

    def test_believe_path_allows_real_attestation(self):
        d = provenance.assertIngestible("gold_examples", "believe",
                                        Provenance(origin=Origin.EXECUTOR, attested_by="adversary:real"))
        self.assertEqual(d.verdict, Verdict.ALLOW)


if __name__ == "__main__":
    unittest.main()
