"""Minimal external recovery and monotone TaskState persistence helpers.

Recovery can inspect only an existing transaction selected by a process-local
authority.  It cannot create a task, transaction, model call, or promotion.

RUN/TEST: python -m pytest tests/execution/test_runtime_resource_recovery.py tests/execution/test_external_recovery.py tests/control/test_attempt_state_transaction.py
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import (
    TYPE_CHECKING,
    Callable,
    Iterable,
    Mapping,
    MutableMapping,
    MutableSequence,
    cast,
)

from platform_core.runtime.attempt_journal import (
    AttemptJournal,
    AttemptPersistenceAuthority,
    AttemptPersistenceAuthorityRefused,
    AttemptPhase,
    AttemptRecord,
)

if TYPE_CHECKING:
    from state.task_schema import TaskState

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}$")
_OUTCOMES = frozenset({"promoted", "failed", "rejected", "not_selected", "retry"})


class RecoveryRefused(RuntimeError):
    """Recovery authority, scope, or durable truth is incomplete."""


class PromotionPersistencePending(RecoveryRefused):
    """Promotion is durable and only TaskState/journal reconciliation is legal."""


def _time(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise RecoveryRefused("recovery authority expiry is invalid") from exc
    if result.tzinfo is None:
        raise RecoveryRefused("recovery authority expiry is not absolute")
    return result.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class RecoverableRuntimeResource:
    resource_id: str
    role: str
    dependency_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not _ID.fullmatch(self.resource_id) or not _ID.fullmatch(self.role):
            raise RecoveryRefused("runtime resource identity is invalid")
        if len(set(self.dependency_ids)) != len(self.dependency_ids):
            raise RecoveryRefused("runtime resource dependencies contain duplicates")
        if self.resource_id in self.dependency_ids:
            raise RecoveryRefused("runtime resource cannot depend on itself")


def runtimeResourceRecoveryOrder(
    resources: Iterable[RecoverableRuntimeResource],
) -> tuple[RecoverableRuntimeResource, ...]:
    """Return dependants-before-owners order or refuse an incomplete graph."""

    records = tuple(resources)
    by_id: dict[str, RecoverableRuntimeResource] = {}
    for record in records:
        if type(record) is not RecoverableRuntimeResource or record.resource_id in by_id:
            raise RecoveryRefused("runtime resource graph has duplicate or untyped records")
        by_id[record.resource_id] = record
    for record in records:
        if any(dependency not in by_id for dependency in record.dependency_ids):
            raise RecoveryRefused("runtime resource graph has a missing dependency")

    remaining = set(by_id)
    ordered: list[RecoverableRuntimeResource] = []
    while remaining:
        depended_on = {
            dependency
            for resource_id in remaining
            for dependency in by_id[resource_id].dependency_ids
            if dependency in remaining
        }
        leaves = sorted(remaining - depended_on)
        if not leaves:
            raise RecoveryRefused("runtime resource graph contains a cycle")
        for resource_id in leaves:
            ordered.append(by_id[resource_id])
            remaining.remove(resource_id)
    return tuple(ordered)


@dataclass(frozen=True, slots=True)
class ExternalRecoveryAuthority:
    transaction_id: str
    controller_generation: int
    expires_at: str
    _issuer_identity: int
    _seal: object


@dataclass(frozen=True, slots=True)
class ExternalRecoveryReceipt:
    transaction_id: str
    controller_generation: int
    observation: object
    activation_authority: bool = False


class ExternalRecoveryController:
    def __init__(
        self,
        *,
        journal_lookup: Callable[[str], object | None],
        path_inspector: Callable[[object], object],
        process_capability: object | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._journal_lookup = journal_lookup
        self._path_inspector = path_inspector
        self._process_capability = process_capability
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._identity = id(self)
        self._seal = object()

    def _issueDiagnosticAuthority(
        self,
        *,
        transaction_id: str,
        controller_generation: int,
        process_capability: object,
        expires_at: str,
    ) -> ExternalRecoveryAuthority:
        """Test seam; production authority is supplied by the installed capsule."""

        if self._process_capability is None or process_capability is not self._process_capability:
            raise RecoveryRefused("recovery process capability differs")
        if not _ID.fullmatch(transaction_id) or controller_generation < 1:
            raise RecoveryRefused("recovery scope is invalid")
        if _time(expires_at) <= self._clock().astimezone(timezone.utc):
            raise RecoveryRefused("recovery authority already expired")
        return ExternalRecoveryAuthority(
            transaction_id=transaction_id,
            controller_generation=controller_generation,
            expires_at=expires_at,
            _issuer_identity=self._identity,
            _seal=self._seal,
        )

    def _validate(self, authority: object, transaction_id: str) -> ExternalRecoveryAuthority:
        if type(authority) is not ExternalRecoveryAuthority:
            raise RecoveryRefused("exact process-local recovery authority is required")
        assert isinstance(authority, ExternalRecoveryAuthority)
        if authority._issuer_identity != self._identity or authority._seal is not self._seal:
            raise RecoveryRefused("recovery authority issuer differs")
        if authority.transaction_id != transaction_id:
            raise RecoveryRefused("recovery authority transaction differs")
        if _time(authority.expires_at) <= self._clock().astimezone(timezone.utc):
            raise RecoveryRefused("recovery authority expired")
        return authority

    def recover(self, transaction_id: str, *, authority: object) -> ExternalRecoveryReceipt:
        validated = self._validate(authority, transaction_id)
        record = self._journal_lookup(transaction_id)
        if record is None:
            raise RecoveryRefused("recovery cannot create or adopt an unknown transaction")
        observation = self._path_inspector(record)
        return ExternalRecoveryReceipt(
            transaction_id=transaction_id,
            controller_generation=validated.controller_generation,
            observation=observation,
        )


@dataclass(frozen=True, slots=True)
class AttemptPersistenceRequest:
    transaction_id: str
    subtask_id: str
    outcome: str
    receipt_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not _ID.fullmatch(self.transaction_id) or not _ID.fullmatch(self.subtask_id):
            raise RecoveryRefused("attempt persistence identity is invalid")
        if self.outcome not in _OUTCOMES:
            raise RecoveryRefused("attempt persistence outcome is invalid")
        if not self.receipt_ids or len(set(self.receipt_ids)) != len(self.receipt_ids):
            raise RecoveryRefused("attempt persistence receipts are empty or duplicate")
        if any(not _ID.fullmatch(value) for value in self.receipt_ids):
            raise RecoveryRefused("attempt persistence receipt identity is invalid")


@dataclass(frozen=True, slots=True)
class AttemptPersistenceResult:
    transaction_id: str
    status: str
    terminal: bool


class _AttemptJournalPersistenceAdapter:
    """One naming boundary for the durable AttemptJournal recovery axes."""

    __slots__ = ("_authority", "_journal")

    _authority: AttemptPersistenceAuthority
    _journal: AttemptJournal

    def __init__(self, journal: object, authority: object) -> None:
        if (
            type(journal) is not AttemptJournal
            or type(authority) is not AttemptPersistenceAuthority
        ):
            raise RecoveryRefused(
                "exact AttemptJournal and persistence authority are required"
            )
        self._journal = cast(AttemptJournal, journal)
        self._authority = cast(AttemptPersistenceAuthority, authority)

    @staticmethod
    def _receipt_chain(record: AttemptRecord) -> tuple[str, ...]:
        ordered = (
            record.staging_receipt_id,
            record.verification_receipt_id,
            record.review_receipt_id,
            record.selection_receipt_id,
            record.promotion_receipt_id,
            *record.reconciliation_receipt_ids,
            record.finalization_receipt_id,
            *record.cleanup_receipt_ids,
        )
        return tuple(receipt_id for receipt_id in ordered if receipt_id)

    def validate_request(
        self,
        *,
        state_data: Mapping[str, object],
        request: AttemptPersistenceRequest,
    ) -> AttemptRecord:
        try:
            record = self._journal.validate_persistence_authority(
                self._authority,
                transaction_id=request.transaction_id,
            )
        except AttemptPersistenceAuthorityRefused as exc:
            raise RecoveryRefused(
                "attempt persistence authority is invalid"
            ) from exc
        except Exception as exc:
            raise RecoveryRefused("attempt journal truth is unavailable") from exc
        if type(record) is not AttemptRecord:
            raise RecoveryRefused("attempt journal returned an untyped record")
        task_id = state_data.get("task_id")
        if not isinstance(task_id, str) or record.task_id != task_id:
            raise RecoveryRefused("attempt journal task differs from TaskState")
        if record.subtask_id != request.subtask_id:
            raise RecoveryRefused("attempt journal subtask differs from request")
        promoted = request.outcome == "promoted"
        if promoted and record.phase is not AttemptPhase.PROMOTED:
            raise RecoveryRefused("promoted persistence requires durable promoted truth")
        if not promoted and record.phase is AttemptPhase.PROMOTED:
            raise RecoveryRefused("non-promoted outcome conflicts with durable promotion")
        if promoted and not record.finalization_receipt_id:
            raise RecoveryRefused("promoted persistence requires finalization truth")
        if promoted and not record.cleanup_complete:
            raise RecoveryRefused("promoted persistence requires complete cleanup truth")
        if request.receipt_ids != self._receipt_chain(record):
            raise RecoveryRefused("attempt receipt chain differs from durable journal truth")
        return record

    def acknowledge_task_state(self, transaction_id: str) -> object:
        return self._journal.mark_task_state_acknowledged(
            transaction_id,
            authority=self._authority,
        )

    def mark_terminal_state_persisted(self, transaction_id: str) -> object:
        return self._journal.mark_terminal_state_persisted(
            transaction_id,
            authority=self._authority,
        )


def _find_subtask(data: MutableMapping[str, object], subtask_id: str) -> MutableMapping[str, object]:
    plan = data.get("plan")
    if not isinstance(plan, MutableMapping):
        raise RecoveryRefused("TaskState has no mutable plan")
    subtasks = plan.get("subtasks")
    if not isinstance(subtasks, list):
        raise RecoveryRefused("TaskState has no subtask list")
    matches = [
        item
        for item in subtasks
        if isinstance(item, dict) and item.get("subtask_id") == subtask_id
    ]
    if len(matches) != 1:
        raise RecoveryRefused("TaskState subtask is missing or ambiguous")
    return matches[0]


def _apply_in_place(target: object, source: object) -> None:
    if isinstance(target, MutableMapping) and isinstance(source, Mapping):
        for key in tuple(target):
            if key not in source:
                del target[key]
        for key, value in source.items():
            if key in target and isinstance(target[key], (dict, list)) and isinstance(value, type(target[key])):
                _apply_in_place(target[key], value)
            else:
                target[key] = copy.deepcopy(value)
        return
    if isinstance(target, MutableSequence) and isinstance(source, list):
        shared = min(len(target), len(source))
        for index in range(shared):
            if isinstance(target[index], (dict, list)) and isinstance(source[index], type(target[index])):
                _apply_in_place(target[index], source[index])
            else:
                target[index] = copy.deepcopy(source[index])
        if len(target) > len(source):
            del target[len(source) :]
        elif len(source) > len(target):
            target.extend(copy.deepcopy(source[len(target) :]))
        return
    raise RecoveryRefused("in-place state application requires like-shaped containers")


def _attach(candidate: dict, request: AttemptPersistenceRequest, *, status: str) -> None:
    subtask = _find_subtask(candidate, request.subtask_id)
    existing_status = subtask.get("status")
    existing_transaction = subtask.get("attempt_transaction_id")
    if existing_status in {"promotion_persistence_pending", "done"}:
        if existing_transaction != request.transaction_id:
            raise RecoveryRefused(
                "sealed subtask belongs to a different transaction"
            )
    if existing_status == "done" and status != "done":
        status = "done"
    receipts = subtask.setdefault("receipts", [])
    if not isinstance(receipts, list):
        raise RecoveryRefused("subtask receipts are malformed")
    transaction = {
        "transaction_id": request.transaction_id,
        "outcome": request.outcome,
        "receipt_ids": list(request.receipt_ids),
    }
    matches = [item for item in receipts if isinstance(item, dict) and item.get("transaction_id") == request.transaction_id]
    if matches and matches != [transaction]:
        raise RecoveryRefused("attempt receipt replay differs")
    if not matches:
        receipts.append(transaction)
    subtask["status"] = status
    subtask["attempt_transaction_id"] = request.transaction_id


def persistAttemptTransaction(
    *,
    state: "TaskState",
    request: AttemptPersistenceRequest,
    journal: AttemptJournal,
    authority: AttemptPersistenceAuthority,
    save_snapshot: Callable[[dict], None] | None = None,
) -> AttemptPersistenceResult:
    """Persist state-before-ack-before-terminal without leaking failed copies."""

    from state.task_schema import TaskState

    if (
        type(state) is not TaskState
        or type(request) is not AttemptPersistenceRequest
        or not isinstance(state.data, dict)
    ):
        raise RecoveryRefused("typed persistence request and TaskState data are required")
    journal_adapter = _AttemptJournalPersistenceAdapter(journal, authority)
    journal_adapter.validate_request(state_data=state.data, request=request)
    snapshot_writer: Callable[[dict], None]
    if save_snapshot is None:
        from state.task_io import saveDataSnapshot

        def snapshot_writer(snapshot: dict) -> None:
            saveDataSnapshot(state, snapshot)
    else:
        snapshot_writer = save_snapshot
    original = state.data
    first = copy.deepcopy(original)
    promoted = request.outcome == "promoted"
    first_status = "promotion_persistence_pending" if promoted else (
        "failed" if request.outcome == "failed" else "running"
    )
    _attach(first, request, status=first_status)
    try:
        snapshot_writer(first)
    except BaseException as exc:
        if promoted:
            raise PromotionPersistencePending(
                "initial promoted TaskState save is pending"
            ) from exc
        raise
    _apply_in_place(original, first)
    try:
        journal_adapter.acknowledge_task_state(request.transaction_id)
    except BaseException as exc:
        if promoted:
            raise PromotionPersistencePending("promotion acknowledgement is pending") from exc
        raise
    if not promoted:
        return AttemptPersistenceResult(
            transaction_id=request.transaction_id,
            status=first_status,
            terminal=first_status == "failed",
        )
    final = copy.deepcopy(first)
    _attach(final, request, status="done")
    try:
        snapshot_writer(final)
    except BaseException as exc:
        raise PromotionPersistencePending("final promoted TaskState save is pending") from exc
    _apply_in_place(original, final)
    try:
        journal_adapter.mark_terminal_state_persisted(request.transaction_id)
    except BaseException as exc:
        raise PromotionPersistencePending("terminal-state journal flag is pending") from exc
    return AttemptPersistenceResult(
        transaction_id=request.transaction_id,
        status="done",
        terminal=True,
    )


__all__ = [
    "AttemptPersistenceRequest",
    "AttemptPersistenceResult",
    "ExternalRecoveryAuthority",
    "ExternalRecoveryController",
    "ExternalRecoveryReceipt",
    "PromotionPersistencePending",
    "RecoverableRuntimeResource",
    "RecoveryRefused",
    "persistAttemptTransaction",
    "runtimeResourceRecoveryOrder",
]
