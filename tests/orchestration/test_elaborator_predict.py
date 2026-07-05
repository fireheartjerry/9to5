import unittest
from agents.planning.elaborator import predict


class TestPredict(unittest.TestCase):
    def test_parses_valid_prediction(self):
        def chat(system, user, *, act, want_json=False):
            return {"message": {"content": '{"likely_files":["a.py"],"likely_failure":"none","predicted_success":0.8}'}}
        out = predict.predictOutcome("spec", None, chat=chat)
        self.assertEqual(out["predicted_success"], 0.8)
        self.assertIn("a.py", out["likely_files"])

    def test_clamps_out_of_range(self):
        def chat(system, user, *, act, want_json=False):
            return {"message": {"content": '{"predicted_success": 5}'}}
        out = predict.predictOutcome("spec", None, chat=chat)
        self.assertEqual(out["predicted_success"], 1.0)

    def test_malformed_is_neutral(self):
        def chat(system, user, *, act, want_json=False):
            return {"message": {"content": "not json at all"}}
        out = predict.predictOutcome("spec", None, chat=chat)
        self.assertEqual(out["predicted_success"], 0.5)

    def test_none_response_neutral(self):
        def chat(system, user, *, act, want_json=False):
            return None
        out = predict.predictOutcome("spec", None, chat=chat)
        self.assertEqual(out["predicted_success"], 0.5)

    def test_single_call(self):
        calls = {"n": 0}
        def chat(system, user, *, act, want_json=False):
            calls["n"] += 1
            return {"message": {"content": "{}"}}
        predict.predictOutcome("spec", None, chat=chat)
        self.assertEqual(calls["n"], 1)
