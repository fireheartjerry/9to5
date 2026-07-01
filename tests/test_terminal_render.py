from notifications.terminal_render import render

META = {"label": "authcache", "idle_s": 0.5, "line_count": 3, "elapsed_s": 41}


def test_render_contains_header_and_tail():
    body = render("st-002", ["a", "b", "c"], META, page=1, page_count=4,
                  mode="summary", frozen=False)
    assert "1/4" in body
    assert "authcache" in body
    assert "c" in body            # newest line present
    assert body.count("```") == 2  # exactly one fenced block


def test_render_caps_total_length():
    huge = [f"line-{i} " + "x" * 500 for i in range(400)]
    body = render("brain", huge, META, page=1, page_count=1, mode="raw", frozen=False)
    assert len(body) <= 1900
    assert "line-399" in body      # tail kept, head dropped


def test_render_truncates_long_lines():
    body = render("brain", ["z" * 999], META, page=1, page_count=1,
                  mode="raw", frozen=False)
    assert len(body) <= 1900
    assert "z" in body


def test_render_marks_frozen_and_empty():
    frozen = render("brain", [], META, page=1, page_count=1, mode="summary", frozen=True)
    assert "FROZEN" in frozen.upper()
    empty = render("brain", [], META, page=1, page_count=1, mode="summary", frozen=False)
    assert "```" in empty            # still a valid block, no crash


def test_render_never_raises_on_bad_input():
    # None lines / weird meta must degrade to an offline frame, not raise.
    body = render("x", None, {}, page=1, page_count=1, mode="summary", frozen=False)
    assert isinstance(body, str) and body


def test_control_rows_have_stable_ids():
    from notifications.terminal_render import TERM_CUSTOM_IDS, terminalControlRows
    assert TERM_CUSTOM_IDS == {
        "prev": "term_prev", "freeze": "term_freeze", "raw": "term_raw",
        "next": "term_next", "snap": "term_snap",
    }
    rows = terminalControlRows()
    # Discord action rows: {"type":1,"components":[{"type":2,...,"custom_id":...}]}
    cids = {c["custom_id"] for row in rows for c in row["components"]}
    assert set(TERM_CUSTOM_IDS.values()) <= cids
    assert all(row["type"] == 1 for row in rows)
    assert all(len(row["components"]) <= 5 for row in rows)  # Discord max 5/row
