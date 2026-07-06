"""Tests for the run narrative arc (beats append + render + templates)."""
from notifications import run_arc


class _S:
    def __init__(self, meta=None):
        self.meta = meta if meta is not None else {}
        self.saved = 0

    def save(self):
        self.saved += 1


def test_append_and_render_order():
    s = _S({"arc": []})
    run_arc.append_beat(s, "Chapter 1 — first")
    run_arc.append_beat(s, "Chapter 2 — second")
    out = run_arc.render_arc(s)
    assert out.index("first") < out.index("second")
    assert len(s.meta["arc"]) == 2
    assert s.saved >= 1


def test_append_tolerates_missing_arc_key():
    s = _S({})  # no "arc"
    run_arc.append_beat(s, "Chapter 1 — beat")
    assert s.meta["arc"] and s.meta["arc"][0]["text"] == "Chapter 1 — beat"


def test_append_beat_is_idempotent_by_text():
    s = _S({"arc": []})
    run_arc.append_beat(s, "Chapter 1 - same")
    run_arc.append_beat(s, "Chapter 1 - same")

    assert len(s.meta["arc"]) == 1
    assert s.saved == 1


def test_templates():
    assert run_arc.beat_discovery(8, "harden") == "Chapter 1 — Discovery surfaced 8 findings. Theme: harden."
    assert run_arc.beat_architect(3) == "Chapter 2 — Architect chose 3 findings, shaped them into one narrative."
    assert run_arc.beat_first_verify() == "Chapter 3 — First subtask closed clean."
    assert run_arc.beat_replan("scope wider") == "Chapter 4 — Replanning. scope wider."
    assert run_arc.beat_complete("done", 3, 3, "12m 04s") == "Final — done. 3/3 subtasks. 12m 04s."


def test_render_empty():
    assert run_arc.render_arc(_S({"arc": []})) == "(no story yet)"


def test_never_raises_on_bad_state():
    class _Bad:
        meta = None
    run_arc.append_beat(_Bad(), "x")  # must not raise
    assert isinstance(run_arc.render_arc(_Bad()), str)
