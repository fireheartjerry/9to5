"""RED contracts for copy-on-write TaskState promotion acknowledgement."""

from __future__ import annotations

import copy
import importlib
import inspect
from dataclasses import replace

import pytest

from state import task_io
from state.task import TaskState
from tests.execution.test_attempt_journal import (
    _persistence_authority,
    _record,
    _real_persistence_transaction,
    _run_installed_journal_case,
    _through_promoted,
)


def _recovery():
    return importlib.import_module("platform_core.runtime.recovery")


@pytest.mark.parametrize(
    "invalid_scope",
    ["stale_generation", "wrong_root", "wrong_transaction"],
)
def test_attempt_persistence_authority_refuses_before_snapshot_or_axis_mutation(
    tmp_path,
    invalid_scope: str,
) -> None:
    mod = _recovery()
    state, _subtask, journal, promoted, request = _real_persistence_transaction(
        tmp_path
    )
    active_generation = [7]
    authority = _persistence_authority(
        journal,
        promoted,
        controller_generation=active_generation,
    )
    target_journal = journal
    target_request = request
    if invalid_scope == "stale_generation":
        active_generation[0] = 8
    elif invalid_scope == "wrong_root":
        target_journal = type(journal)(tmp_path / "other-controller" / "journals")
    else:
        target_request = replace(request, transaction_id="tx-wrong-authority")
    snapshots: list[dict] = []

    with pytest.raises(mod.RecoveryRefused, match="persistence authority"):
        mod.persistAttemptTransaction(
            state=state,
            request=target_request,
            journal=target_journal,
            authority=authority,
            save_snapshot=lambda snapshot: snapshots.append(copy.deepcopy(snapshot)),
        )

    assert snapshots == []
    durable = journal.load(promoted.transaction_id)
    assert durable.task_state_acknowledged is False
    assert durable.terminal_state_persisted is False


def test_attempt_persistence_revalidates_generation_under_acknowledgement_lock(
    tmp_path,
) -> None:
    mod = _recovery()
    state, _subtask, journal, promoted, request = _real_persistence_transaction(
        tmp_path
    )
    active_generation = [7]
    authority = _persistence_authority(
        journal,
        promoted,
        controller_generation=active_generation,
    )
    snapshots: list[dict] = []

    def advance_generation_after_pending_save(snapshot: dict) -> None:
        snapshots.append(copy.deepcopy(snapshot))
        active_generation[0] = 8

    with pytest.raises(mod.PromotionPersistencePending, match="acknowledgement"):
        mod.persistAttemptTransaction(
            state=state,
            request=request,
            journal=journal,
            authority=authority,
            save_snapshot=advance_generation_after_pending_save,
        )

    assert [
        snapshot["plan"]["subtasks"][0]["status"] for snapshot in snapshots
    ] == ["promotion_persistence_pending"]
    durable = journal.load(promoted.transaction_id)
    assert durable.task_state_acknowledged is False
    assert durable.terminal_state_persisted is False


def test_installed_journal_requires_authority_for_acknowledgement(
    tmp_path,
) -> None:
    result = _run_installed_journal_case(
        tmp_path,
        """
from contextlib import contextmanager
from datetime import datetime, timezone

runtime = state.installControllerRuntimeState(bootstrap_authorities=bundle)
journal_root = Path(scope.controller_state_root) / 'attempt-journal'
journal_root.mkdir(parents=True)
journal = journal_mod.AttemptJournal(
    journal_root,
    diagnostic=False,
    bootstrap_authorities=bundle,
)
record = installed_record(runtime)
terminal = journal.transition(
    journal.create(record).transaction_id,
    journal_mod.AttemptPhase.REJECTED,
    error='terminal test outcome',
)
observations = []
original_load = journal._load_chain
original_append = journal._append_event
original_file_lock = journal_mod.fileLock

@contextmanager
def observed_file_lock(*_args, **_kwargs):
    observations.append('file-lock')
    yield

journal_mod.fileLock = observed_file_lock
journal._load_chain = lambda _transaction_id: observations.append('replay')
journal._append_event = lambda _record: observations.append('append')
try:
    journal.mark_task_state_acknowledged(terminal.transaction_id)
except journal_mod.AttemptPersistenceAuthorityRefused as exc:
    assert 'diagnostic-only' in str(exc)
else:
    raise AssertionError('installed raw acknowledgement was accepted')
assert observations == []
durable = original_load(terminal.transaction_id).record
assert durable.task_state_acknowledged is False
assert durable.terminal_state_persisted is False
journal_mod.fileLock = original_file_lock
journal._load_chain = original_load
journal._append_event = original_append
process_capability = state._controllerAuthorityScope(
    runtime.authority
).process_capability
issuer = journal_mod.AttemptPersistenceAuthorityIssuer(
    journal_root=journal_root,
    controller_state_authority=runtime.authority,
    process_capability=process_capability,
    bootstrap_authorities=bundle,
)
authority = issuer.issueAuthority(
    transaction_id=terminal.transaction_id,
    task_id=terminal.task_id,
    subtask_id=terminal.subtask_id,
    process_capability=process_capability,
    deadline=datetime(2098, 1, 1, tzinfo=timezone.utc),
)
acknowledged = journal.mark_task_state_acknowledged(
    terminal.transaction_id,
    authority=authority,
)
assert acknowledged.task_state_acknowledged is True
assert journal.load(terminal.transaction_id).task_state_acknowledged is True
""",
    )

    assert result.returncode == 0, result.stderr


def test_diagnostic_path_only_journal_is_unavailable_after_controller_activation(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal_module = importlib.import_module(
        "platform_core.runtime.attempt_journal"
    )
    paths_module = importlib.import_module("platform_core.app_config.paths")
    monkeypatch.setattr(paths_module, "controllerPathsActive", lambda: True)

    with pytest.raises(
        journal_module.AttemptPersistenceAuthorityRefused,
        match="diagnostic journal is unavailable",
    ):
        journal_module.AttemptJournal(
            tmp_path / "journal",
            diagnostic=True,
        )


def test_preexisting_diagnostic_journal_loses_raw_mutation_on_activation(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal_module = importlib.import_module(
        "platform_core.runtime.attempt_journal"
    )
    paths_module = importlib.import_module("platform_core.app_config.paths")
    journal = journal_module.AttemptJournal(
        tmp_path / "journal",
        diagnostic=True,
    )
    promoted = _through_promoted(journal, _record(tmp_path))
    appended: list[object] = []
    original_append = journal._append_event

    def observe_append(record):
        appended.append(record)
        return original_append(record)

    monkeypatch.setattr(journal, "_append_event", observe_append)
    monkeypatch.setattr(paths_module, "controllerPathsActive", lambda: True)

    with pytest.raises(
        journal_module.AttemptPersistenceAuthorityRefused,
        match="diagnostic journal is unavailable",
    ):
        journal.mark_task_state_acknowledged(promoted.transaction_id)

    assert appended == []


def test_terminal_axis_revalidates_generation_under_its_journal_lock(
    tmp_path,
) -> None:
    journal_module = importlib.import_module(
        "platform_core.runtime.attempt_journal"
    )
    _state, _subtask, journal, promoted, _request = (
        _real_persistence_transaction(tmp_path)
    )
    active_generation = [7]
    authority = _persistence_authority(
        journal,
        promoted,
        controller_generation=active_generation,
    )
    acknowledged = journal.mark_task_state_acknowledged(
        promoted.transaction_id,
        authority=authority,
    )
    assert acknowledged.task_state_acknowledged is True
    active_generation[0] = 8

    with pytest.raises(
        journal_module.AttemptPersistenceAuthorityRefused,
        match="generation is stale",
    ):
        journal.mark_terminal_state_persisted(
            promoted.transaction_id,
            authority=authority,
        )

    durable = journal.load(promoted.transaction_id)
    assert durable.task_state_acknowledged is True
    assert durable.terminal_state_persisted is False


def test_save_data_snapshot_persists_detached_copy_without_mutating_live() -> None:
    state = TaskState.create("detached snapshot", 1.0)
    subtask = state.addSubtask("persist", "copy on write")
    live_before = copy.deepcopy(state.data)
    candidate = copy.deepcopy(state.data)
    candidate["plan"]["subtasks"][0]["status"] = "promotion_persistence_pending"

    receipt = task_io.saveDataSnapshot(state, candidate)

    assert state.data == live_before
    assert type(receipt) is task_io.TaskStateSnapshotReceipt
    assert receipt.task_id == state.task_id
    assert receipt.byte_length > 0
    assert len(receipt.snapshot_sha256) == 64
    assert task_io.validateTaskStateSnapshotReceipt(
        receipt,
        state=state,
        snapshot=candidate,
    ) is receipt
    durable = TaskState.load(state.task_id)
    durable_subtask = durable.getSubtask(subtask["subtask_id"])
    assert durable_subtask is not None
    assert durable_subtask["status"] == "promotion_persistence_pending"


def test_persist_attempt_transaction_has_no_public_snapshot_writer_override() -> None:
    parameters = inspect.signature(_recovery().persistAttemptTransaction).parameters
    assert "save_snapshot" not in parameters


def test_noop_snapshot_writer_cannot_acknowledge_task_state(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _recovery()
    state, _subtask, journal, promoted, request = _real_persistence_transaction(
        tmp_path
    )
    before = copy.deepcopy(state.data)
    monkeypatch.setattr(task_io, "saveDataSnapshot", lambda *_args, **_kwargs: None)

    with pytest.raises(mod.PromotionPersistencePending, match="durable.*proof"):
        mod.persistAttemptTransaction(
            state=state,
            request=request,
            journal=journal,
            authority=_persistence_authority(journal, promoted),
        )

    assert state.data == before
    durable = journal.load(promoted.transaction_id)
    assert durable.task_state_acknowledged is False
    assert durable.terminal_state_persisted is False


def test_failed_first_snapshot_save_leaves_live_graph_byte_for_byte_unchanged(
    tmp_path,
) -> None:
    mod = _recovery()
    state, _subtask, journal, promoted, request = _real_persistence_transaction(
        tmp_path
    )
    before = copy.deepcopy(state.data)

    with pytest.raises(mod.PromotionPersistencePending, match="initial promoted"):
        mod.persistAttemptTransaction(
            state=state,
            request=request,
            journal=journal,
            authority=_persistence_authority(journal, promoted),
            save_snapshot=lambda snapshot: (_ for _ in ()).throw(OSError("disk")),
        )

    assert state.data == before
    durable = journal.load(promoted.transaction_id)
    assert durable.task_state_acknowledged is False
    assert durable.terminal_state_persisted is False


def test_promoted_transaction_persists_pending_then_ack_then_done(tmp_path) -> None:
    mod = _recovery()
    state, _subtask, journal, promoted, request = _real_persistence_transaction(
        tmp_path
    )
    snapshots: list[dict] = []

    result = mod.persistAttemptTransaction(
        state=state,
        request=request,
        journal=journal,
        authority=_persistence_authority(journal, promoted),
        save_snapshot=lambda snapshot: snapshots.append(copy.deepcopy(snapshot)),
    )

    assert [item["plan"]["subtasks"][0]["status"] for item in snapshots] == [
        "promotion_persistence_pending",
        "done",
    ]
    durable = journal.load(promoted.transaction_id)
    assert durable.task_state_acknowledged is True
    assert durable.terminal_state_persisted is True
    assert state.data["plan"]["subtasks"][0]["status"] == "done"
    assert result.terminal is True


def test_promoted_transaction_uses_detached_task_store_by_default(tmp_path) -> None:
    mod = _recovery()
    state, subtask, journal, promoted, request = _real_persistence_transaction(
        tmp_path
    )

    result = mod.persistAttemptTransaction(
        state=state,
        request=request,
        journal=journal,
        authority=_persistence_authority(journal, promoted),
    )

    durable_state = TaskState.load(state.task_id)
    durable_subtask = durable_state.getSubtask(subtask["subtask_id"])
    assert durable_subtask is not None
    durable_attempt = journal.load(promoted.transaction_id)
    assert durable_subtask["status"] == "done"
    assert durable_attempt.task_state_acknowledged is True
    assert durable_attempt.terminal_state_persisted is True
    assert result.status == "done"
