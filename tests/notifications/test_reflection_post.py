"""Tests for the self-reflection post (generate + save + obsidian + discord)."""
import config
from notifications import reflection_post


class _Stub:
    def __init__(self, task_id, meta=None):
        self.task_id = task_id
        self.meta = meta or {"codename": "IRON_PHOENIX", "goal_raw": "do the thing"}
        self.data = {"obsidian": {"vault_task_dir": f"tasks/{task_id}"}}
        self.saved = 0

    def vaultTaskDir(self):
        return self.data["obsidian"]["vault_task_dir"]

    def save(self):
        self.saved += 1


def _chat_str(system, user, **kw):
    return "I came in thinking this was a rate-limit problem. It wasn't."


def _chat_resp(system, user, **kw):
    return {"message": {"content": "A paragraph from the model."}}


def test_writes_reflection_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    state = _Stub("task-abc")
    text = reflection_post.write_reflection(state, chat=_chat_str)
    assert text and "rate-limit" in text
    f = tmp_path / "task-abc" / "reflection.md"
    assert f.exists()
    assert "rate-limit" in f.read_text(encoding="utf-8")


def test_extracts_text_from_resp_dict(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    text = reflection_post.write_reflection(_Stub("task-def"), chat=_chat_resp)
    assert text == "A paragraph from the model."


def test_writes_obsidian_note(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    written = []

    class _Obs:
        def writeNote(self, rel, body):
            written.append((rel, body))
            return {"rel_path": rel}

    reflection_post.write_reflection(_Stub("task-ghi"), chat=_chat_str, obs=_Obs())
    assert written and "reflection" in written[0][0]


def test_bad_chat_never_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)

    def _boom(system, user, **kw):
        raise RuntimeError("model down")

    assert reflection_post.write_reflection(_Stub("task-x"), chat=_boom) is None
    # empty/None chat output -> None, no file written, no raise
    assert reflection_post.write_reflection(_Stub("task-y"), chat=lambda s, u, **k: None) is None


def test_post_reflection_never_raises():
    # DISCORD blanked by conftest -> no network; must simply not raise.
    reflection_post.post_reflection(_Stub("task-z"), "some text",
                                    comparative={"pace": "1.2x faster"})


def test_post_reflection_is_idempotent(monkeypatch):
    state = _Stub("task-once")
    sent = []

    class _Discord:
        @staticmethod
        def noticeEmbed(body, title=""):
            return {"body": body, "title": title}

        @staticmethod
        def sendEmbed(embed):
            sent.append(embed)

    monkeypatch.setattr("notifications.discord_bot", _Discord)

    reflection_post.post_reflection(state, "same text")
    reflection_post.post_reflection(state, "same text")

    assert len(sent) == 1
    assert state.saved == 1
