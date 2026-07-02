"""parseJsonText gains a third ladder rung: json_repair salvages truncated/malformed 7B JSON
AFTER strict parse + balanced-object extraction fail. Garbage still returns None."""
from platform_core.orchestration import brain_io


def test_truncated_object_salvaged():
    # missing closing brace + trailing comma: strict json.loads and balanced-walk both fail
    out = brain_io.parseJsonText('{"subtasks": [{"title": "a"},], "n": 3')
    assert isinstance(out, dict)
    assert out["n"] == 3


def test_clean_json_passthrough():
    assert brain_io.parseJsonText('{"x": 1}') == {"x": 1}


def test_pure_prose_returns_none():
    assert brain_io.parseJsonText("no json here at all") is None
