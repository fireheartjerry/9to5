"""task_io single-writer mechanics: iterStored shape validation (foreign JSON in the store
dir is skipped + counted, never misparsed as a run) and the reapDeadRun escape hatch
(refuses unless the run is provably dead). Dirs are isolated by conftest."""

import json
import logging
import os
import time

import pytest

import config
from platform_core.core import fsio
from state import task_io
from state.task import TaskState


def _controller_binding(tmp_path):
    from platform_core.runtime import controller_state

    capability = object()
    authority = controller_state.issueDiagnosticControllerStateAuthority(
        root=tmp_path / "controller-state",
        repository_id="repo_task_io_test",
        controller_generation=7,
        process_capability=capability,
        expires_at="2099-01-01T00:00:00+00:00",
    )
    store = controller_state.ControllerStateStore(
        root=tmp_path / "controller-state", authority=authority
    )
    return store, authority


def test_diagnostic_task_state_uses_only_explicit_controller_store(
    tmp_path, monkeypatch
):
    store, authority = _controller_binding(tmp_path)
    poison = tmp_path / "target-repository" / "state" / "tasks"
    monkeypatch.setattr(task_io, "_INSTALLED_BINDING", None, raising=False)
    monkeypatch.setattr(task_io, "_controllerPathsActive", lambda: False)
    monkeypatch.setattr(config, "STATE_DIR", poison)
    task_io.installTaskStateStore(store=store, authority=authority)

    st = TaskState.create("external state", 1.0)
    st.save()
    st.meta["status"] = "executing"
    st.save()

    assert not poison.exists()
    assert TaskState.load(st.task_id).meta["status"] == "executing"
    assert [data["task_id"] for _path, data in TaskState.iterStored()] == [
        st.task_id
    ]
    assert store.readJson(
        f"task-backups/{st.task_id}", authority=authority
    )["meta"]["status"] == "created"


def test_capsule_task_state_refuses_without_exact_store_binding(monkeypatch):
    from platform_core.app_config import paths

    monkeypatch.setattr(task_io, "_INSTALLED_BINDING", None, raising=False)
    monkeypatch.setattr(paths, "controllerPathsActive", lambda: True)

    with pytest.raises(task_io.TaskStateStoreUnavailable):
        TaskState.load("33333333-3333-4333-8333-333333333333")


# --------------------------------------------------------------------- iterStored
def test_iterstored_skips_foreign_shaped_files(caplog):
    st = TaskState.create("real goal", 1.0)
    st.save()
    # a terminal_nav.json-shaped file dropped into the store dir (the old IPC location)
    (config.STATE_DIR / "terminal_nav.json").write_text(
        json.dumps({"page_idx": 0, "mode": "summary", "frozen": False}), encoding="utf-8"
    )
    (config.STATE_DIR / "corrupt.json").write_text("{not json", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="9to5.task_io"):
        got = list(task_io.iterStored())
    assert [d["task_id"] for _, d in got] == [st.task_id]
    assert any("skipped 2" in r.message for r in caplog.records), (
        f"skip count not logged: {[r.message for r in caplog.records]}"
    )


def test_loadlatest_ignores_foreign_files():
    (config.STATE_DIR / "terminal_mirror.json").write_text(
        json.dumps({"body": "x", "page_count": 1, "lanes": []}), encoding="utf-8"
    )
    assert TaskState.loadLatest() is None
    st = TaskState.create("g", 1.0)
    st.save()
    assert TaskState.loadLatest().task_id == st.task_id


def test_save_has_no_state_epoch_stamp():
    st = TaskState.create("g", 1.0)
    st.save()
    on_disk = json.loads(st.path().read_text(encoding="utf-8"))
    assert "state_epoch" not in on_disk["meta"]


# --------------------------------------------------------------------- durable save + .bak
def test_save_writes_bak_of_prior_good_state_and_load_falls_back():
    st = TaskState.create("real goal", 1.0)
    st.save()  # 1st save: no prior content -> no .bak yet
    p = st.path()
    first_payload = p.read_text(encoding="utf-8")
    st.meta["status"] = "executing"
    st.save()  # 2nd save: backs up the 1st save's content to .bak
    bak = p.with_name(p.name + ".bak")
    assert bak.exists()
    assert bak.read_text(encoding="utf-8") == first_payload
    # corrupt the primary -> load() recovers the LAST-BACKED-UP-GOOD state (the 1st save,
    # i.e. status "created") from .bak rather than stranding the run entirely.
    p.write_text("{torn-mid-write", encoding="utf-8")
    recovered = task_io.load(st.task_id)
    assert recovered.meta["status"] == "created"
    assert task_io.loadSafe(st.task_id) is not None


def test_load_raises_when_primary_and_bak_both_unusable():
    st = TaskState.create("g", 1.0)
    st.save()
    p = st.path()
    p.write_text("{not json", encoding="utf-8")  # no .bak yet -> nothing to recover
    with pytest.raises(Exception):
        task_io.load(st.task_id)
    assert task_io.loadSafe(st.task_id) is None


# --------------------------------------------------------------------- fork-clone skip
def test_iterstored_skips_fork_branch_clones():
    st = TaskState.create("real goal", 1.0)
    st.save()
    fork_path = config.STATE_DIR / f"{st.task_id}__fork_a.json"
    fork_data = dict(st.data)
    fork_data["task_id"] = f"{st.task_id}__fork_a"
    fork_path.write_text(json.dumps(fork_data), encoding="utf-8")
    ids = [d["task_id"] for _, d in task_io.iterStored()]
    assert ids == [st.task_id]  # fork clone never yielded


def test_loadlatest_ignores_fork_branch_clone_even_with_later_mtime():
    st = TaskState.create("real goal", 1.0)
    st.meta["status"] = "executing"
    st.save()
    fork_path = config.STATE_DIR / f"{st.task_id}__fork_a.json"
    fork_data = dict(st.data)
    fork_data["task_id"] = f"{st.task_id}__fork_a"
    fork_data["meta"] = dict(st.meta)
    fork_path.write_text(json.dumps(fork_data), encoding="utf-8")
    latest = TaskState.loadLatest()
    assert latest is not None
    assert latest.task_id == st.task_id  # never the fork clone


# --------------------------------------------------------------------- deterministic tie-break + offset-aware order
def test_loadlatest_tie_break_is_deterministic_task_id_order():
    """Two tasks with an identical (status, started_at) key must not depend on glob order --
    the higher task_id (final tuple element) always wins."""
    started = "2026-06-22T08:00:00-04:00"
    ids = sorted(["11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"])
    for tid in ids:
        (config.STATE_DIR / f"{tid}.json").write_text(
            json.dumps(
                {
                    "task_id": tid,
                    "meta": {"status": "executing", "started_at": started},
                    "plan": {"subtasks": []},
                }
            ),
            encoding="utf-8",
        )
    latest = TaskState.loadLatest()
    assert latest.task_id == ids[-1]


def test_loadlatest_and_listrecent_order_by_absolute_time_across_utc_offsets():
    """'...T10:00:00-05:00' (15:00 UTC) is chronologically LATER than '...T09:00:00-04:00'
    (13:00 UTC) even though the raw strings sort the other way -- offset-aware parsing
    must win over lexicographic string comparison."""
    earlier_id = "33333333-3333-4333-8333-333333333333"
    later_id = "44444444-4444-4444-8444-444444444444"
    (config.STATE_DIR / f"{earlier_id}.json").write_text(
        json.dumps(
            {
                "task_id": earlier_id,
                "meta": {
                    "status": "executing",
                    "started_at": "2026-06-22T09:00:00-04:00",
                    "goal_raw": "earlier",
                },
                "plan": {"subtasks": []},
            }
        ),
        encoding="utf-8",
    )
    (config.STATE_DIR / f"{later_id}.json").write_text(
        json.dumps(
            {
                "task_id": later_id,
                "meta": {
                    "status": "executing",
                    "started_at": "2026-06-22T10:00:00-05:00",
                    "goal_raw": "later",
                },
                "plan": {"subtasks": []},
            }
        ),
        encoding="utf-8",
    )
    assert TaskState.loadLatest().task_id == later_id
    assert task_io.listRecent(2)[0]["task_id"] == later_id


# --------------------------------------------------------------------- reapDeadRun
def _deadTask() -> TaskState:
    st = TaskState.create("g", 1.0)
    st.meta["status"] = "executing"
    st.meta["run_pid"] = 999999999  # implausible -> provably dead
    st.save()
    return st


def test_reap_refuses_while_alive():
    st = _deadTask()
    st.meta["run_pid"] = os.getpid()  # live process
    st.save()
    assert task_io.reapDeadRun(st.task_id) is False
    assert TaskState.load(st.task_id).meta["status"] == "executing"


def test_reap_refuses_on_fresh_heartbeat():
    st = _deadTask()
    fsio.atomicWriteJson(
        config.HEARTBEAT_DIR / f"{st.task_id}.json", {"pid": 999999999, "seq": 1, "ts": time.time()}
    )
    assert task_io.reapDeadRun(st.task_id) is False


def test_reap_finalizes_provably_dead_run():
    st = _deadTask()
    assert task_io.reapDeadRun(st.task_id) is True
    reloaded = TaskState.load(st.task_id)
    assert reloaded.meta["status"] == "aborted"
    assert "dead" in (reloaded.meta.get("blocked_reason") or "")


def test_reap_noops_on_terminal_or_missing():
    st = _deadTask()
    st.meta["status"] = "done"
    st.save()
    assert task_io.reapDeadRun(st.task_id) is False
    assert task_io.reapDeadRun("no-such-task") is False


# ------------------------------------------------------------- single-writer grep gate
def test_no_task_json_writers_in_bot_process_modules():
    """Bot-process code must be bus-only: no setStatus / state.save() / subtask mutation
    call sites in the launcher, the '!' command spine, or the gateway bot package.
    (task_io.reapDeadRun is the one sanctioned escape hatch and lives in state/.)"""
    import re
    from pathlib import Path

    root = Path(task_io.__file__).resolve().parents[1] / "notifications"
    bot_files = [
        root / "work_launcher.py",
        root / "commands.py",
        *sorted((root / "bot").rglob("*.py")),
        *sorted(root.glob("views*.py")),
    ]
    banned = re.compile(r"\.setStatus\(|state\.save\(\)|\.updateSubtask\(|\.addSubtask\(")
    offenders = []
    for f in bot_files:
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if banned.search(line) and not line.lstrip().startswith("#"):
                offenders.append(f"{f.name}:{i}: {line.strip()}")
    assert offenders == [], "bot-process task-JSON writers found (bus-only rule):\n" + "\n".join(offenders)
