"""The historical worktree preference is a truthful private-clone facade."""
from __future__ import annotations

from pathlib import Path

import pytest

from platform_core.execution.backends.worktree import WorktreeEnvironment
from platform_core.execution.environment import (
    Capability,
    EnvHandle,
    EnvironmentUnavailable,
    FinalizationReceipt,
    PreparedFinalization,
)


class _CloneDelegate:
    def __init__(self, checkout: Path) -> None:
        self.checkout = checkout
        self.torn_down = False

    def healthCheck(self) -> bool:
        return True

    def provision(self, **kwargs) -> EnvHandle:
        del kwargs
        self.checkout.mkdir(parents=True)
        return EnvHandle(
            work_dir=str(self.checkout),
            backend="clone",
            meta={"transaction_id": "tx-001", "linked_worktree": False},
            capabilities=Capability.FILE_RW | Capability.EXEC | Capability.SNAPSHOT,
            requires_canonical_landing=True,
            runtime_token=object(),
        )

    def wrapLauncher(self, run_cmd, handle):
        return run_cmd, handle.work_dir

    def collectChanges(self, handle, **kwargs):
        del handle, kwargs
        return {"backend": "clone", "merged": False, "canonical_mutation": False}

    def prepareChanges(self, handle, **kwargs):
        del kwargs
        return PreparedFinalization(
            backend="clone",
            work_dir=handle.work_dir,
            accepted=True,
            proposed_revision="a" * 40,
            summary={"transaction_id": "tx-001"},
            runtime_token=handle.runtime_token,
        )

    def preparedChangesIntact(self, prepared):
        return prepared.accepted

    def completeChanges(self, prepared, **kwargs):
        del kwargs
        return FinalizationReceipt(
            backend="clone",
            accepted=prepared.accepted,
            requires_canonical_landing=True,
            error="authorization required for staged promotion",
        )

    def checkpointRecovery(self, handle, **kwargs):
        del handle, kwargs
        return {"available": True}

    def teardown(self, handle):
        del handle
        self.torn_down = True


class _State:
    task_id = "task-001"


def test_unconfigured_worktree_preference_is_typed_unavailable(tmp_path: Path) -> None:
    env = WorktreeEnvironment()
    assert env.healthCheck() is False
    with pytest.raises(EnvironmentUnavailable):
        env.provision(
            task_state=_State(),
            subtask={"subtask_id": "subtask-001"},
            base_dir=str(tmp_path),
            policy=None,
        )


def test_worktree_preference_delegates_without_linked_checkout(tmp_path: Path) -> None:
    delegate = _CloneDelegate(tmp_path / "external" / "candidate")
    env = WorktreeEnvironment(delegate)  # type: ignore[arg-type]
    handle = env.provision(
        task_state=_State(),
        subtask={"subtask_id": "subtask-001"},
        base_dir=str(tmp_path / "canonical"),
        policy=None,
    )

    assert handle.backend == "worktree"
    assert handle.meta["requested_backend"] == "worktree"
    assert handle.meta["effective_backend"] == "private-clone"
    assert handle.meta["linked_worktree"] is False
    assert Capability.SNAPSHOT in handle.capabilities
    summary = env.collectChanges(
        handle,
        task_state=_State(),
        subtask={"subtask_id": "subtask-001"},
    )
    assert summary["canonical_mutation"] is False
    assert summary["merged"] is False

    prepared = env.prepareChanges(
        handle,
        task_state=_State(),
        subtask={"subtask_id": "subtask-001"},
    )
    assert prepared.backend == "worktree"
    assert prepared.summary["linked_worktree"] is False
    env.teardown(handle)
    assert delegate.torn_down
