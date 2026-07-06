import unittest

from agents.planning.elaborator import schema


class TestValidateSpec(unittest.TestCase):
    def _good(self):
        return {
            "objective": "do x", "why": "because", "who": "core.py", "where": "agents/",
            "how": "edit", "deliverables": ["a"], "acceptance_criteria": ["b"],
            "constraints": ["c"], "assumptions": [],
        }

    def test_valid_spec_passes(self):
        ok, errors = schema.validateSpec(self._good())
        self.assertTrue(ok)
        self.assertEqual(errors, [])

    def test_missing_required_field_fails(self):
        bad = self._good()
        del bad["deliverables"]
        ok, errors = schema.validateSpec(bad)
        self.assertFalse(ok)
        self.assertTrue(any("deliverables" in e for e in errors))

    def test_empty_list_field_fails(self):
        bad = self._good()
        bad["deliverables"] = []
        ok, errors = schema.validateSpec(bad)
        self.assertFalse(ok)

    def test_wrong_type_fails(self):
        bad = self._good()
        bad["deliverables"] = "not a list"
        ok, errors = schema.validateSpec(bad)
        self.assertFalse(ok)


class TestValidateUniverse(unittest.TestCase):
    def test_baseline_hard_boundaries_reported_missing(self):
        ok, errors = schema.validateUniverse(
            {"description": "d", "allowed_paths": ["a"], "allowed_to_expand_to": [], "hard_boundaries": []})
        self.assertFalse(ok)
        self.assertTrue(any("hard_boundaries" in e for e in errors))
