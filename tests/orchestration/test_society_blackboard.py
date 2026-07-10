"""Append-only JSONL blackboard: ordering, attribution, malformed tolerance."""
from platform_core.orchestration.society.blackboard import Blackboard, BlackboardEntry


def _entry(key, kind, author, to, value):
    return BlackboardEntry(key=key, kind=kind, author=author, to=to,
                           subtask_id=None, value=value, refs=[], span_id=None)


def test_append_then_read_all_in_order(tmp_path):
    bb = Blackboard(tmp_path / "t.jsonl")
    id1 = bb.append(_entry("facts", "facts", "coordinator", "all", {"n": 1}))
    id2 = bb.append(_entry("result:st-1", "result", "coder", "coordinator", {"n": 2}))
    rows = bb.readAll()
    assert [r["entry_id"] for r in rows] == [id1, id2]
    assert rows[0]["author"] == "coordinator" and rows[1]["author"] == "coder"
    assert rows[0]["ts_ns"] <= rows[1]["ts_ns"]


def test_malformed_line_is_skipped(tmp_path):
    p = tmp_path / "t.jsonl"
    bb = Blackboard(p)
    bb.append(_entry("facts", "facts", "coordinator", "all", {"n": 1}))
    with open(p, "a", encoding="utf-8") as fh:
        fh.write("{ this is not json\n")
    bb.append(_entry("result:st-1", "result", "coder", "coordinator", {"n": 2}))
    rows = bb.readAll()
    assert len(rows) == 2  # the garbage line is tolerated, not fatal


def test_on_append_hook_fires(tmp_path):
    seen = []
    bb = Blackboard(tmp_path / "t.jsonl", on_append=seen.append)
    bb.append(_entry("facts", "facts", "coordinator", "all", {"n": 1}))
    assert seen and seen[0]["kind"] == "facts"


def test_for_task_uses_blackboard_dir(tmp_path):
    bb = Blackboard.forTask("abc-123", base_dir=tmp_path)
    bb.append(_entry("facts", "facts", "coordinator", "all", {}))
    assert (tmp_path / "abc-123.jsonl").exists()


import threading as _threading

from platform_core.orchestration.society.blackboard import Blackboard as _BB, BlackboardEntry as _BE


def test_concurrent_append_no_lost_or_torn_lines(tmp_path):
    bb = _BB(tmp_path / "c.jsonl")
    n_threads, per = 8, 25

    def worker(wid):
        for i in range(per):
            bb.append(_BE(key=f"k{wid}", kind="result", author=f"w{wid}",
                          to="coordinator", value={"wid": wid, "i": i}))

    threads = [_threading.Thread(target=worker, args=(w,)) for w in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    rows = bb.readAll()
    assert len(rows) == n_threads * per          # zero lost lines
    ids = {r["entry_id"] for r in rows}
    assert len(ids) == n_threads * per           # zero torn/duplicate ids
    # every line parsed cleanly (no interleaved/torn writes)
    seen = {(r["value"]["wid"], r["value"]["i"]) for r in rows}
    assert len(seen) == n_threads * per
