"""TaskLedger round-trips through state.meta and carries the autogen-derived prompt constants."""
import tempfile
from pathlib import Path
from unittest import mock

import config
from platform_core.orchestration import task_ledger as tl
from state.task import TaskState


def test_ledger_roundtrip_through_meta():
    with mock.patch.object(config, "STATE_DIR", Path(tempfile.mkdtemp())):
        st = TaskState.create("g", 1.0)
        led = tl.TaskLedger(given_facts=["gf"], lookup_facts=["lf"], derive_facts=["df"],
                            guess_facts=["gg"], plan=["step 1", "step 2"], revision=0)
        tl.saveToState(st, led)
        loaded = tl.loadFromState(st)
        assert loaded.plan == ["step 1", "step 2"]
        assert loaded.given_facts == ["gf"]
        assert loaded.revision == 0


def test_load_absent_returns_none():
    with mock.patch.object(config, "STATE_DIR", Path(tempfile.mkdtemp())):
        st = TaskState.create("g", 1.0)
        assert tl.loadFromState(st) is None


def test_prompt_constants_present():
    assert "facts" in tl.TASK_LEDGER_FACTS_PROMPT.lower()
    assert "plan" in tl.TASK_LEDGER_PLAN_PROMPT.lower()
    assert tl.PROGRESS_LEDGER_PROMPT and tl.FACTS_UPDATE_PROMPT and tl.PLAN_UPDATE_PROMPT
