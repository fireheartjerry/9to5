"""makeSink fans each tool call to BOTH the journal and the trajectory recorder, fail-open."""
from platform_core.orchestration import step_sink


class _Rec:
    def __init__(self):
        self.children = []

    def openSpan(self, kind, parent_id, attrs):
        self.children.append((kind, parent_id, attrs))
        return f"span-{len(self.children)}"

    def closeSpan(self, step_id, usage=None, cost_usd=None):
        pass


def test_sink_writes_journal_and_trajectory(monkeypatch):
    journaled = []
    monkeypatch.setattr(step_sink.experience, "appendStep",
                        lambda *a, **k: journaled.append(a))
    rec = _Rec()
    sink = step_sink.makeSink("run-1", "st-001", attempt=1, plan_sig="sig-1",
                              session_getter=lambda: "sess-7",
                              recorder=rec, parent_span_id="root-span")
    sink(0, "Edit", "edit a.py", {"file_path": "a.py"})
    sink(1, "Bash", "run tests", {"command": "pytest"})
    assert len(journaled) == 2
    # appendStep positional args: run_id, subtask_id, attempt, step_idx, kind, tool, ...
    assert journaled[0][0] == "run-1" and journaled[0][3] == 0 and journaled[0][5] == "Edit"
    assert rec.children[0] == ("tool", "root-span", {"tool": "Edit", "file_path": "a.py"})


def test_sink_is_failopen(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(step_sink.experience, "appendStep", _boom)
    sink = step_sink.makeSink("run-1", "st-001", attempt=1, plan_sig="sig",
                              session_getter=lambda: "s", recorder=None, parent_span_id=None)
    sink(0, "Edit", "x", {})           # must not raise


def test_sink_none_recorder_still_journals(monkeypatch):
    journaled = []
    monkeypatch.setattr(step_sink.experience, "appendStep",
                        lambda *a, **k: journaled.append(a))
    sink = step_sink.makeSink("run-1", "st-001", attempt=1, plan_sig="sig",
                              session_getter=lambda: "s", recorder=None, parent_span_id=None)
    sink(0, "Read", "read c.py", {"file_path": "c.py"})
    assert len(journaled) == 1
