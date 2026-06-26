"""The replaceable-intelligence seams (protocols.py) are structural and fake-satisfiable."""
import unittest

import protocols


class _FakeExecutor:
    def runClaude(self, spec_or_prompt, *, work_dir=None, task_state=None,
                  subtask=None, cancel_check=None):
        return {"ok": True, "stdout": "", "surface": "terminal"}


class _FakeVerifier:
    def runVerification(self, verify, work_dir, **kwargs):
        return {"passed": True}


class _FakeReviewer:
    def review(self, subtask_title, trigger_reason, executor_output, *,
               goal="", review_type="subtask", **kwargs):
        return {"verdict": "approved"}


class TestStructuralSatisfaction(unittest.TestCase):
    def test_fake_executor_satisfies_protocol(self):
        # runtime_checkable + duck typing: a fake need not inherit to satisfy the seam.
        self.assertIsInstance(_FakeExecutor(), protocols.Executor)

    def test_fake_verifier_satisfies_protocol(self):
        self.assertIsInstance(_FakeVerifier(), protocols.Verifier)

    def test_fake_reviewer_satisfies_protocol(self):
        self.assertIsInstance(_FakeReviewer(), protocols.Reviewer)

    def test_a_plain_callable_satisfies_brain(self):
        def brain(system, user, *, want_json=False):
            return {"message": {"content": ""}}
        self.assertIsInstance(brain, protocols.Brain)

    def test_an_unrelated_object_does_not_satisfy_executor(self):
        self.assertNotIsInstance(object(), protocols.Executor)


if __name__ == "__main__":
    unittest.main()
