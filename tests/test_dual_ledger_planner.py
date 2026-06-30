"""Dual-ledger planner free functions, all driven by a mocked ollama_chat callable."""
from platform_core.orchestration import dual_ledger_planner as dlp


class _Chat:
    def __init__(self, replies):
        self.replies = list(replies)

    def __call__(self, system, user, *, want_json=False):
        return {"message": {"content": self.replies.pop(0)}}


def test_author_task_ledger_two_calls():
    chat = _Chat([
        '{"given_facts": ["g"], "lookup_facts": [], "derive_facts": [], "guess_facts": []}',
        '{"plan": ["step one", "[independent] step two"]}',
    ])
    led = dlp.authorTaskLedger(chat, "build X", "arch doc")
    assert led is not None
    assert led.given_facts == ["g"]
    assert led.plan == ["step one", "[independent] step two"]


def test_author_task_ledger_none_on_bad_json():
    chat = _Chat(["not json", "not json", "not json", "not json", "not json", "not json"])
    assert dlp.authorTaskLedger(chat, "build X", "arch") is None


import tempfile
from pathlib import Path
from unittest import mock

import config
from platform_core.orchestration import task_ledger as tl
from state.task import TaskState


def test_derive_dag_sequential_and_independent():
    led = tl.TaskLedger(plan=["build module", "[independent] write docs", "wire it up"])
    subs = dlp.deriveSubtaskDag(led, "goal")
    assert len(subs) == 3
    assert subs[0]["depends_on"] == []            # first bullet, no dep
    assert subs[1]["depends_on"] == []            # [independent] breaks the chain
    assert subs[2]["depends_on"] == [1]           # sequential: depends on the prior index
    assert subs[1]["title"] == "write docs"       # marker stripped


def test_materialize_resolves_index_deps_to_ids():
    with mock.patch.object(config, "STATE_DIR", Path(tempfile.mkdtemp())):
        st = TaskState.create("g", 1.0)
        led = tl.TaskLedger(plan=["a", "b"])  # b depends on a (index 0)
        subs = dlp.deriveSubtaskDag(led, "g")
        created = dlp.materializeDag(st, subs)
        assert created[1]["depends_on"] == [created[0]["subtask_id"]]
        assert st.getSubtask(created[1]["subtask_id"])["depends_on"] == [created[0]["subtask_id"]]


def test_progress_ledger_step_validates_four_keys():
    chat = _Chat(['{"is_request_satisfied": {"reason": "no", "answer": false}, '
                  '"is_in_loop": {"reason": "no", "answer": false}, '
                  '"is_progress_being_made": {"reason": "yes", "answer": true}, '
                  '"instruction": {"reason": "next", "answer": "do step 2"}}'])
    out = dlp.progressLedgerStep(chat, "goal", "recent output")
    assert out["instruction"]["answer"] == "do step 2"


def test_update_stall_count_increments_on_loop():
    prog = {"is_in_loop": {"answer": True}, "is_progress_being_made": {"answer": True}}
    assert dlp.updateStallCount(prog, 0) == 1


def test_update_stall_count_increments_on_no_progress():
    prog = {"is_in_loop": {"answer": False}, "is_progress_being_made": {"answer": False}}
    assert dlp.updateStallCount(prog, 1) == 2


def test_update_stall_count_decrements_on_progress_floor_zero():
    prog = {"is_in_loop": {"answer": False}, "is_progress_being_made": {"answer": True}}
    assert dlp.updateStallCount(prog, 0) == 0   # never below zero
    assert dlp.updateStallCount(prog, 2) == 1


def test_root_cause_replan_bumps_revision_and_rewrites():
    led = tl.TaskLedger(given_facts=["old"], plan=["old step"], revision=1)
    chat = _Chat([
        '{"root_cause": "wrong assumption", "given_facts": ["new"], "lookup_facts": [], '
        '"derive_facts": [], "guess_facts": []}',
        '{"plan": ["new step a", "new step b"]}',
    ])
    new_led = dlp.rootCauseReplan(chat, "goal", led, "subtask failed twice")
    assert new_led is not None
    assert new_led.revision == 2            # bumped
    assert new_led.given_facts == ["new"]
    assert new_led.plan == ["new step a", "new step b"]


def test_root_cause_replan_none_on_bad_json_keeps_caller_fallback():
    led = tl.TaskLedger(plan=["x"], revision=0)
    chat = _Chat(["junk"] * 6)
    assert dlp.rootCauseReplan(chat, "goal", led, "fail") is None
