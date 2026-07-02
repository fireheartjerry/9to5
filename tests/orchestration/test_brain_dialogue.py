"""Brain-dialogue pure core: context builder + graceful answer (chat injected)."""
from notifications import brain_dialogue as bd


class _State:
    task_id = "t1"
    meta = {"goal_raw": "wire the pool", "goal_elaborated": "wire the connection pool",
            "status": "executing"}
    subtasks = [
        {"subtask_id": "st-004", "title": "pool fix", "status": "done", "depends_on": []},
        {"subtask_id": "st-005", "title": "verify pool", "status": "pending",
         "depends_on": ["st-004"], "description": "verify against the pool"},
    ]
    data = {"notifications": [{"at": "t", "kind": "subtask_done", "detail": "st-004"}],
            "adversary_reviews": []}


def test_why_context_has_plan_and_question():
    ctx = bd.build_context(_State(), "why", "st-004 before st-005?")
    assert "st-004" in ctx and "st-005" in ctx
    assert "st-004 before st-005?" in ctx


def test_explain_context_targets_subtask():
    ctx = bd.build_context(_State(), "explain", "st-005")
    assert "verify against the pool" in ctx


def test_answer_uses_injected_chat():
    out = bd.answer("why", "st-004 before st-005?", _State(),
                    chat=lambda s, u: "st-005 depends on st-004's pool fix.")
    assert "depends" in out


def test_answer_offline_degrades():
    def boom(s, u):
        raise RuntimeError("down")
    out = bd.answer("ask", "what now?", _State(), chat=boom)
    assert "offline" in out.lower() or "unavailable" in out.lower()


def test_explain_unknown_sid_message():
    out = bd.answer("explain", "st-999", _State(), chat=lambda s, u: "x")
    assert "st-999" in out


def test_plan_rationale_lists_all_subtasks():
    ctx = bd.build_context(_State(), "plan-rationale", "")
    assert "st-004" in ctx and "st-005" in ctx
