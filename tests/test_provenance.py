# tests/test_provenance.py
"""The provenance tag + the assertIngestible chokepoint."""
import unittest

import provenance
from provenance import Provenance, Origin


class TestProvenanceValue(unittest.TestCase):
    def test_roundtrips_through_dict(self):
        p = Provenance(origin=Origin.EXECUTOR, authoring_task_id="t1")
        self.assertEqual(Provenance.fromDict(p.toDict()), p)

    def test_unknown_dict_degrades_to_executor_origin(self):
        # Missing/garbage provenance must default to the LEAST-trusted origin, never human.
        self.assertEqual(provenance.coerce(None).origin, Origin.EXECUTOR)
        self.assertEqual(provenance.coerce({"origin": "nonsense"}).origin, Origin.EXECUTOR)


if __name__ == "__main__":
    unittest.main()
