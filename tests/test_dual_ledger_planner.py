"""Dual-ledger planner free functions, all driven by a mocked ollama_chat callable."""
from platform_core.orchestration import dual_ledger_planner as dlp


class _Chat:
    def __init__(self, replies):
        self.replies = list(replies)

    def __call__(self, system, user, *, want_json=False):
        return {"message": {"content": self.replies.pop(0)}}


def test_author_task_ledger_two_calls():
    chat = _Chat([
        '{"given_facts": ["g"], "lookup_facts": [], "derive_facts": [], "guess_facts": []}',
        '{"plan": ["step one", "[independent] step two"]}',
    ])
    led = dlp.authorTaskLedger(chat, "build X", "arch doc")
    assert led is not None
    assert led.given_facts == ["g"]
    assert led.plan == ["step one", "[independent] step two"]


def test_author_task_ledger_none_on_bad_json():
    chat = _Chat(["not json", "not json", "not json", "not json", "not json", "not json"])
    assert dlp.authorTaskLedger(chat, "build X", "arch") is None
