"""Lightweight dict-shape validation: required keys present + per-field validators, no pydantic."""
from platform_core.orchestration import brain_json


def test_missing_required_key_reported():
    errors = brain_json._validateShape({"a": 1}, ["a", "b"], {})
    assert any("b:" in e and "missing" in e for e in errors)


def test_non_object_root_reported():
    errors = brain_json._validateShape([1, 2], ["a"], {})
    assert errors and "<root>" in errors[0]


def test_validator_failure_reports_repr():
    errors = brain_json._validateShape(
        {"n": "oops"}, ["n"], {"n": lambda v: isinstance(v, int)})
    assert any("n:" in e and "'oops'" in e for e in errors)


def test_clean_object_no_errors():
    assert brain_json._validateShape({"n": 3}, ["n"], {"n": lambda v: isinstance(v, int)}) == []


def test_retry_prompt_carries_exact_errors():
    prompt = brain_json._makeRetryPrompt(["b: required key missing [got <absent>]"])
    assert "b: required key missing" in prompt
    assert "ONLY" in prompt  # instructs the brain to return only corrected JSON


class _FakeChat:
    """A stand-in for self._ollamaChat: returns a queued list of fake resp dicts in order."""
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, system, user, *, want_json=False, act="unspecified"):
        self.calls.append(user)
        body = self.replies.pop(0)
        return {"message": {"content": body}}


def test_recovers_within_retry_budget():
    chat = _FakeChat(['{"a": "wrong"}', '{"a": 1, "b": 2}'])
    out = brain_json.chatJsonValidated(
        chat, "sys", "do it", required_keys=["a", "b"],
        validators={"a": lambda v: isinstance(v, int)}, max_retries=2)
    assert out == {"a": 1, "b": 2}
    # the 2nd call's user prompt must carry the exact field error from the 1st
    assert "a: failed validation" in chat.calls[1]


def test_exhausts_and_returns_none():
    chat = _FakeChat(['not json', 'still not', 'nope'])
    out = brain_json.chatJsonValidated(
        chat, "sys", "do it", required_keys=["a"], max_retries=2)
    assert out is None
    assert len(chat.calls) == 3  # initial + 2 retries, bounded by max_retries
