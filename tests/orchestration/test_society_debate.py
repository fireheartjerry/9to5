# tests/orchestration/test_society_debate.py
"""Structured debate: deterministic speaker selection, convergence, round-cap, oscillation."""
from society.blackboard import Blackboard, makeEntry
from society.debate import selectNextSpeaker, runDebate


def test_select_next_speaker_picks_unanswered():
    roster = ["coder", "reviewer"]
    thread = [
        {"entry_id": "p1", "author": "coder", "kind": "proposal", "refs": []},
        {"entry_id": "c1", "author": "reviewer", "kind": "proposal", "refs": ["p1"]},
    ]
    # coder's p1 has been answered (c1 refs it); reviewer's c1 is unanswered -> coder speaks next
    assert selectNextSpeaker(thread, roster) == "coder"


def test_converges_on_consensus(tmp_path):
    bb = Blackboard(tmp_path / "d.jsonl")

    def arbiter(**kw):  # scripted: immediately resolved in favor of coder
        return {"verdict": "approved", "tier": "stub",
                "value": {"is_resolved": True, "next_speaker": "coder",
                          "winner": "coder"}}

    v = runDebate(bb, subtask_id="st-1", roster=["coder", "reviewer"],
                  arbiter_fn=arbiter, max_rounds=3)
    assert v["resolved"] is True and v["winner"] == "coder"
    assert v["stopped_reason"] == "consensus" and v["rounds"] >= 1


def test_stops_on_round_cap(tmp_path):
    bb = Blackboard(tmp_path / "d.jsonl")

    def arbiter(**kw):  # never resolves, always alternates
        return {"verdict": "challenged", "tier": "stub",
                "value": {"is_resolved": False, "next_speaker": "reviewer",
                          "proposal": "x"}}

    v = runDebate(bb, subtask_id="st-1", roster=["coder", "reviewer"],
                  arbiter_fn=arbiter, max_rounds=2)
    assert v["resolved"] is False and v["stopped_reason"] == "round_cap"
    assert v["rounds"] == 2


def test_stops_on_oscillation(tmp_path):
    bb = Blackboard(tmp_path / "d.jsonl")
    seq = iter(["A", "B", "A", "B", "A", "B"])

    def arbiter(**kw):  # proposals cycle A->B->A -> oscillation guard fires
        return {"verdict": "challenged", "tier": "stub",
                "value": {"is_resolved": False, "next_speaker": "coder",
                          "proposal": next(seq)}}

    v = runDebate(bb, subtask_id="st-1", roster=["coder", "reviewer"],
                  arbiter_fn=arbiter, max_rounds=10)
    assert v["resolved"] is False and v["stopped_reason"] == "oscillation"
    assert v["rounds"] < 10


def test_debate_thread_is_scoped_to_contested_subtask(tmp_path):
    bb = Blackboard(tmp_path / "d.jsonl")
    bb.append(makeEntry(kind="proposal", author="coder", to="all",
                        subtask_id="st-old", value={"proposal": "stale old debate"}))

    seen_contents = []

    def arbiter(**kw):
        seen_contents.append(kw["content"])
        return {"verdict": "challenged", "tier": "stub",
                "value": {"is_resolved": False, "next_speaker": "reviewer",
                          "proposal": "fresh new debate"}}

    v = runDebate(bb, subtask_id="st-new", roster=["coder", "reviewer"],
                  arbiter_fn=arbiter, max_rounds=1)
    assert v["stopped_reason"] == "round_cap"
    assert seen_contents == ["[]"]
    rows = bb.readAll()
    assert rows[-1]["subtask_id"] == "st-new"
