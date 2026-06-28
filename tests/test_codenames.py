"""Tests for the run codename generator and TaskState codename wiring."""
import re

from platform_core.ops import codenames

_RE = re.compile(r"[A-Z]+_[A-Z]+")


def test_generate_shape():
    name = codenames.generate()
    assert _RE.fullmatch(name), name


def test_generate_varies():
    seen = {codenames.generate() for _ in range(300)}
    assert len(seen) > 20


def test_word_list_sizes():
    assert len(codenames.ADJECTIVES) >= 200
    assert len(codenames.NOUNS) >= 200


def test_word_lists_are_unique_upper_single_token():
    for word in (*codenames.ADJECTIVES, *codenames.NOUNS):
        assert word.isupper() and word.isalpha(), word
    assert len(set(codenames.ADJECTIVES)) == len(codenames.ADJECTIVES)
    assert len(set(codenames.NOUNS)) == len(codenames.NOUNS)


def test_taskstate_has_codename(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    from state.task import TaskState
    s = TaskState.create("do a thing", 1.0)
    assert _RE.fullmatch(s.meta["codename"])
    assert s.meta["arc"] == []
    assert s.meta["tunnel_url"] is None
    assert s.meta["health_score"] == 100
