"""WorkerAgent: CAS-claim on task JSON, injectable run_fn, posts result to board."""
import threading

from society.blackboard import Blackboard
from society.roles import ROLES
from society.worker import WorkerAgent
from state.task import TaskState


def _state_with_subtask():
    st = TaskState.create("goal", 1.0)
    st.addSubtask("Implement x", "do x")
    return st, st.subtasks[0]["subtask_id"]


def test_run_claims_executes_and_posts_result(tmp_path):
    state, sid = _state_with_subtask()
    bb = Blackboard(tmp_path / "b.jsonl")
    calls = {}

    def fake_run(spec, **kw):
        calls["spec"] = spec
        calls["work_dir"] = kw.get("work_dir")
        return {"ok": True, "returncode": 0, "stdout": "done", "cost_usd": 0.01}

    w = WorkerAgent(ROLES["coder"], state.getSubtask(sid), str(tmp_path),
                    bb, state, threading.Lock(), run_fn=fake_run)
    msg = w.run()

    assert msg["ok"] is True and msg["role"] == "coder"
    assert state.getSubtask(sid)["status"] == "done"
    assert state.getSubtask(sid)["claimed_by"] == "coder"
    # role narrows effort/model but does not bypass routing
    assert calls["spec"]["effort_level"] == ROLES["coder"].effort_level
    assert calls["work_dir"] == str(tmp_path)
    posted = bb.readAll()
    assert posted[-1]["kind"] == "result" and posted[-1]["author"] == "coder"


def test_lost_claim_yields_without_running(tmp_path):
    state, sid = _state_with_subtask()
    state.updateSubtask(sid, status="in_progress", claimed_by="other")  # already taken
    bb = Blackboard(tmp_path / "b.jsonl")
    ran = {"n": 0}

    def fake_run(spec, **kw):
        ran["n"] += 1
        return {"ok": True}

    w = WorkerAgent(ROLES["coder"], state.getSubtask(sid), str(tmp_path),
                    bb, state, threading.Lock(), run_fn=fake_run)
    msg = w.run()
    assert msg["ok"] is False and msg["kind"] == "claim"
    assert ran["n"] == 0  # never executed -- lost the race


def test_two_workers_one_winner(tmp_path):
    state, sid = _state_with_subtask()
    bb = Blackboard(tmp_path / "b.jsonl")
    lock = threading.Lock()
    wins = []

    def fake_run(spec, **kw):
        return {"ok": True, "returncode": 0}

    def attempt(role):
        w = WorkerAgent(ROLES[role], state.getSubtask(sid), str(tmp_path),
                        bb, state, lock, run_fn=fake_run)
        m = w.run()
        if m["ok"]:
            wins.append(role)

    t1 = threading.Thread(target=attempt, args=("coder",))
    t2 = threading.Thread(target=attempt, args=("tester",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert len(wins) == 1  # exactly one worker ever owns the subtask


def test_failing_verify_lands_failed(tmp_path):
    state, sid = _state_with_subtask()
    state.updateSubtask(sid, verify={"cmd": "python -c \"import sys; sys.exit(1)\"",
                                     "expect": "exit_zero"})
    bb = Blackboard(tmp_path / "b.jsonl")

    def fake_run(spec, **kw):
        return {"ok": True, "returncode": 0, "stdout": "done", "cost_usd": 0.0}

    w = WorkerAgent(ROLES["coder"], state.getSubtask(sid), str(tmp_path),
                    bb, state, threading.Lock(), run_fn=fake_run)
    msg = w.run()

    assert msg["ok"] is True  # executor itself succeeded
    assert state.getSubtask(sid)["status"] == "failed"  # but the verifier did not pass
