"""file-disjointness scheduling + atomic CAS claim (guild port)."""
from platform_core.orchestration import parallel_safety as ps


def _sub(sid, files, status="pending", deps=None):
    return {"subtask_id": sid, "files_touched": files, "status": status,
            "depends_on": deps or []}


class _State:
    def __init__(self, subs):
        self._subs = {s["subtask_id"]: s for s in subs}

    def getSubtask(self, sid):
        return self._subs.get(sid)

    def updateSubtask(self, sid, **f):
        self._subs[sid].update(f)


def test_files_touched_and_disjoint():
    a = _sub("a", ["x.py"])
    b = _sub("b", ["y.py"])
    c = _sub("c", ["x.py"])
    assert ps.filesTouched(a) == {"x.py"}
    assert ps.disjoint(a, b) is True
    assert ps.disjoint(a, c) is False


def test_empty_files_touched_serializes():
    a = _sub("a", [])           # unknown set -> conservatively conflicting
    b = _sub("b", ["y.py"])
    assert ps.disjoint(a, b) is False
    batch = ps.safeParallelSet(_State([a, b]), [a, b], limit=4)
    assert [s["subtask_id"] for s in batch] == ["a"]   # serialize: only the first


def test_safe_parallel_set_picks_disjoint():
    a, b, c = _sub("a", ["x.py"]), _sub("b", ["y.py"]), _sub("c", ["x.py"])
    batch = ps.safeParallelSet(_State([a, b, c]), [a, b, c], limit=4)
    ids = [s["subtask_id"] for s in batch]
    assert "a" in ids and "b" in ids and "c" not in ids   # c conflicts with a


def test_safe_parallel_set_honors_deps():
    a = _sub("a", ["x.py"])
    b = _sub("b", ["y.py"], deps=["a"])   # depends on a (not yet done) -> cannot co-run with a
    batch = ps.safeParallelSet(_State([a, b]), [a, b], limit=4)
    assert [s["subtask_id"] for s in batch] == ["a"]


def test_claim_cas_wins_once():
    a = _sub("a", ["x.py"])
    state = _State([a])
    assert ps.claim(state, "a") is True               # pending -> in_progress
    assert state.getSubtask("a")["status"] == "in_progress"
    assert ps.claim(state, "a") is False              # lost race: already claimed
