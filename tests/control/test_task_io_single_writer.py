"""task_io single-writer mechanics: iterStored shape validation (foreign JSON in the store
dir is skipped + counted, never misparsed as a run) and the reapDeadRun escape hatch
(refuses unless the run is provably dead). Dirs are isolated by conftest."""
import json
import logging
import os
import time

import config
from platform_core.core import fsio
from state import task_io
from state.task import TaskState


# --------------------------------------------------------------------- iterStored
def test_iterstored_skips_foreign_shaped_files(caplog):
    st = TaskState.create("real goal", 1.0)
    st.save()
    # a terminal_nav.json-shaped file dropped into the store dir (the old IPC location)
    (config.STATE_DIR / "terminal_nav.json").write_text(
        json.dumps({"page_idx": 0, "mode": "summary", "frozen": False}), encoding="utf-8")
    (config.STATE_DIR / "corrupt.json").write_text("{not json", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="9to5.task_io"):
        got = list(task_io.iterStored())
    assert [d["task_id"] for _, d in got] == [st.task_id]
    assert any("skipped 2" in r.message for r in caplog.records), \
        f"skip count not logged: {[r.message for r in caplog.records]}"


def test_loadlatest_ignores_foreign_files():
    (config.STATE_DIR / "terminal_mirror.json").write_text(
        json.dumps({"body": "x", "page_count": 1, "lanes": []}), encoding="utf-8")
    assert TaskState.loadLatest() is None
    st = TaskState.create("g", 1.0)
    st.save()
    assert TaskState.loadLatest().task_id == st.task_id


def test_save_has_no_state_epoch_stamp():
    st = TaskState.create("g", 1.0)
    st.save()
    on_disk = json.loads(st.path().read_text(encoding="utf-8"))
    assert "state_epoch" not in on_disk["meta"]


# --------------------------------------------------------------------- reapDeadRun
def _deadTask() -> TaskState:
    st = TaskState.create("g", 1.0)
    st.meta["status"] = "executing"
    st.meta["run_pid"] = 999999999          # implausible -> provably dead
    st.save()
    return st


def test_reap_refuses_while_alive():
    st = _deadTask()
    st.meta["run_pid"] = os.getpid()        # live process
    st.save()
    assert task_io.reapDeadRun(st.task_id) is False
    assert TaskState.load(st.task_id).meta["status"] == "executing"


def test_reap_refuses_on_fresh_heartbeat():
    st = _deadTask()
    fsio.atomicWriteJson(config.HEARTBEAT_DIR / f"{st.task_id}.json",
                         {"pid": 999999999, "seq": 1, "ts": time.time()})
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
    bot_files = [root / "work_launcher.py", root / "commands.py",
                 *sorted((root / "bot").rglob("*.py")),
                 *sorted(root.glob("views*.py"))]
    banned = re.compile(r"\.setStatus\(|state\.save\(\)|\.updateSubtask\(|\.addSubtask\(")
    offenders = []
    for f in bot_files:
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if banned.search(line) and not line.lstrip().startswith("#"):
                offenders.append(f"{f.name}:{i}: {line.strip()}")
    assert offenders == [], "bot-process task-JSON writers found (bus-only rule):\n" + "\n".join(offenders)
