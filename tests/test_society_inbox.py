"""makeEntry constructor + inboxFilter cursor logic (metagpt _observe rule)."""
from society.inbox import makeEntry, inboxFilter


def test_make_entry_defaults():
    e = makeEntry(kind="result", author="coder", to="coordinator",
                  subtask_id="st-1", value={"ok": True})
    assert e.kind == "result" and e.to == "coordinator"
    assert e.key == "result:st-1"            # derived slot when not given
    assert e.refs == [] and e.span_id is None


def test_make_entry_explicit_key_and_refs():
    e = makeEntry(kind="vote", author="reviewer", to="all",
                  value={}, key="vote:debate-3", refs=["bb-1", "bb-2"])
    assert e.key == "vote:debate-3" and e.refs == ["bb-1", "bb-2"]


def test_inbox_filter_role_and_cursor():
    rows = [
        {"entry_id": "a", "to": "all", "ts_ns": 10},
        {"entry_id": "b", "to": "coder", "ts_ns": 20},
        {"entry_id": "c", "to": "tester", "ts_ns": 30},
        {"entry_id": "d", "to": "coder", "ts_ns": 40},
    ]
    got = inboxFilter(rows, role="coder", since_ns=15)
    assert [r["entry_id"] for r in got] == ["b", "d"]  # 'all'@10 cut by cursor; tester excluded
