"""RED contracts for typed prepare/complete lifecycle helpers."""

from __future__ import annotations

from types import SimpleNamespace

from platform_core.execution import wiring
from platform_core.execution.environment import PreparedFinalization
from platform_core.runtime.receipts import FinalizationReceipt


class _Environment:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def prepareChanges(self, handle, *, task_state, subtask):
        self.calls.append("prepare")
        return PreparedFinalization(
            backend="clone",
            accepted=True,
            proposed_revision="1" * 40,
            staging_receipt_id="a" * 64,
            summary={"transaction_id": "tx_finalization"},
        )

    def completeChanges(
        self,
        prepared,
        *,
        promote,
        authorization=None,
        landing_authority=None,
    ):
        self.calls.append(f"complete:{promote}")
        return FinalizationReceipt(
            backend="clone",
            accepted=True,
            requires_canonical_landing=True,
            promotion_transaction_id=prepared.summary["transaction_id"],
            staging_receipt_id=prepared.staging_receipt_id,
            journal_phase="finalized",
        )


def test_quiet_helpers_preserve_typed_prepare_and_completion_results() -> None:
    env = _Environment()
    state = SimpleNamespace(task_id="task-1")
    subtask = {"id": "st-1"}
    logs: list[str] = []
    prepared = wiring.prepareQuietly(
        env,
        object(),
        state,
        subtask,
        "st-1",
        logs.append,
    )
    final = wiring.completeQuietly(
        env,
        prepared,
        promote=True,
        authorization=object(),
        landing_authority=object(),
        log=logs.append,
    )

    assert prepared.summary["transaction_id"] == "tx_finalization"
    assert final.promotion_transaction_id == "tx_finalization"
    assert env.calls == ["prepare", "complete:True"]
