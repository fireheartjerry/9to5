"""Tests for the cross-session user-preference store + NL prefer/brief-set parsers."""
import json

from memory import user_prefs


def test_load_returns_defaults_when_absent(tmp_path):
    prefs = user_prefs.load(path=tmp_path / "p.json")
    assert prefs["brief_default_depth"] == "standard"
    assert prefs["brief_include_cost"] is True
    assert prefs["instinct_enabled"] is True


def test_set_pref_persists(tmp_path):
    p = tmp_path / "p.json"
    user_prefs.set_pref("brief_include_cost", False, path=p)
    assert user_prefs.load(path=p)["brief_include_cost"] is False
    assert json.loads(p.read_text())["brief_include_cost"] is False


def test_reset_restores_defaults(tmp_path):
    p = tmp_path / "p.json"
    user_prefs.set_pref("brief_tone", "minimal", path=p)
    user_prefs.reset(path=p)
    assert user_prefs.load(path=p)["brief_tone"] == "colleague"


def test_unknown_key_rejected(tmp_path):
    p = tmp_path / "p.json"
    assert user_prefs.set_pref("not_a_key", 1, path=p) is None
    assert "not_a_key" not in user_prefs.load(path=p)


def test_parse_prefer_brief_without_cost():
    assert user_prefs.parsePreferIntent("brief without cost") == ("brief_include_cost", False)


def test_parse_prefer_no_tool_call_narration():
    assert user_prefs.parsePreferIntent("no tool-call narration") == (
        "narration_include_tool_calls", False)


def test_parse_prefer_deep_and_one_line():
    assert user_prefs.parsePreferIntent("deep") == ("default_detail_level", "deep")
    assert user_prefs.parsePreferIntent("one-line") == ("default_detail_level", "one-line")


def test_parse_brief_set_tool_calls_off():
    assert user_prefs.parseBriefSet("set tool-calls off") == ("brief_include_tool_calls", False)


def test_parse_prefer_unknown_returns_none():
    assert user_prefs.parsePreferIntent("make me a sandwich") is None


def test_apply_prefer_persists_and_reports(tmp_path):
    p = tmp_path / "p.json"
    msg = user_prefs.applyPrefer("brief without cost", path=p)
    assert "cost" in msg.lower()
    assert user_prefs.load(path=p)["brief_include_cost"] is False


def test_format_prefs_is_readable(tmp_path):
    out = user_prefs.formatPrefs(user_prefs.load(path=tmp_path / "p.json"))
    assert "brief_default_depth" in out
