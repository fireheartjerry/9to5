"""Contract test for the ExecutionEnvironment ABC (no real backend)."""
import dataclasses
import importlib
import json

from platform_core.execution.environment import (
    Capability, EnvHandle, ExecutionEnvironment,
)


class FakeEnvironment(ExecutionEnvironment):
    NAME = "fake"
    CAPABILITIES = Capability.FILE_RW | Capability.EXEC

    def __init__(self):
        self.calls = []

    def provision(self, *, task_state, subtask, base_dir, policy):
        self.calls.append("provision")
        return EnvHandle(work_dir=base_dir + "/wt", backend=self.NAME,
                         meta={"id": "x1"}, capabilities=self.CAPABILITIES)

    def wrapLauncher(self, run_cmd, handle):
        self.calls.append("wrap")
        return ["prefix", *run_cmd], handle.work_dir

    def collectChanges(self, handle, *, task_state, subtask):
        self.calls.append("collect")
        return {"merged": True}

    def teardown(self, handle):
        self.calls.append("teardown")


def test_capability_flag_is_combinable():
    caps = Capability.FILE_RW | Capability.NETWORK
    assert Capability.FILE_RW in caps
    assert Capability.SNAPSHOT not in caps


def test_envhandle_fields():
    h = EnvHandle(work_dir="/w", backend="fake", meta={}, capabilities=Capability(0))
    assert h.work_dir == "/w" and h.backend == "fake" and h.meta == {}


def test_lifecycle_ordering_and_workdir_honored():
    env = FakeEnvironment()
    handle = env.provision(task_state=None, subtask={"subtask_id": "s1"},
                           base_dir="/base", policy=None)
    assert handle.work_dir == "/base/wt"
    cmd, work = env.wrapLauncher(["claude", "--print"], handle)
    assert cmd == ["prefix", "claude", "--print"] and work == "/base/wt"
    summary = env.collectChanges(handle, task_state=None, subtask={"subtask_id": "s1"})
    assert summary == {"merged": True}
    env.teardown(handle)
    assert env.calls == ["provision", "wrap", "collect", "teardown"]


def test_default_healthcheck_true():
    assert FakeEnvironment().healthCheck() is True


def test_typed_finalization_contracts_are_frozen_and_json_safe():
    mod = importlib.import_module("platform_core.execution.environment")
    prepared_fields = {
        "backend", "work_dir", "accepted", "requires_revision_verification",
        "proposed_revision", "verification_dir", "verification_backend", "staged_ref",
        "candidate_snapshot_digest", "canonical_tree_manifest_digest",
        "staging_receipt_id", "error", "summary", "runtime_token",
    }
    final_fields = {
        "backend", "accepted", "requires_canonical_landing", "collected", "merged",
        "removed", "expected_revision", "observed_revision", "resulting_revision",
        "checkpoint_revision", "checkpoint_ref", "verification_revision",
        "promotion_transaction_id", "execution_receipt_id", "staging_receipt_id",
        "verification_receipt_id", "review_receipt_id", "selection_receipt_id",
        "promotion_receipt_id", "materialized", "journal_phase", "error",
        "cleanup_error", "summary",
    }
    assert mod.PreparedFinalization.__dataclass_params__.frozen
    assert mod.FinalizationReceipt.__dataclass_params__.frozen
    assert prepared_fields == {f.name for f in dataclasses.fields(mod.PreparedFinalization)}
    assert final_fields == {f.name for f in dataclasses.fields(mod.FinalizationReceipt)}
    prepared = mod.PreparedFinalization(
        backend="remote", work_dir="/candidate", accepted=True,
        requires_revision_verification=True, proposed_revision="a" * 40,
        verification_dir="/verify", verification_backend="docker",
        staged_ref="refs/galaxy/candidate", candidate_snapshot_digest="snap",
        canonical_tree_manifest_digest="tree", staging_receipt_id="stage",
        error="", summary={"staged": True}, runtime_token=object(),
    )
    encoded = prepared.toDict()
    assert "runtime_token" not in encoded
    json.dumps(encoded)


def test_removed_alone_cannot_make_accepted_landing_succeed():
    mod = importlib.import_module("platform_core.execution.environment")
    receipt = mod.FinalizationReceipt(
        backend="remote", accepted=True, requires_canonical_landing=True,
        collected=False, merged=False, removed=True, expected_revision="a" * 40,
        observed_revision="", resulting_revision="", checkpoint_revision="",
        checkpoint_ref="", verification_revision="", promotion_transaction_id="",
        execution_receipt_id="", staging_receipt_id="", verification_receipt_id="",
        review_receipt_id="", selection_receipt_id="", promotion_receipt_id="",
        materialized=False, journal_phase="prepared", error="", cleanup_error="",
        summary={},
    )
    assert receipt.succeeded is False


def test_execution_context_frozenly_separates_environment_runtime_and_verification_resources():
    mod = importlib.import_module("platform_core.execution.environment")
    names = {f.name for f in dataclasses.fields(mod.ExecutionContext)}
    assert names == {
        "landing_environment", "landing_handle", "execution_environment", "execution_handle",
        "runtime_resources", "verification_environment", "verification_handle",
        "work_dir", "read_only",
    }
    assert mod.ExecutionContext.__dataclass_params__.frozen
    assert mod.ExecutionContext.__dataclass_fields__["work_dir"].metadata["frozen_scope"] is True
    assert mod.ExecutionContext.__dataclass_fields__["read_only"].metadata["frozen_scope"] is True
    assert "landing_authority" not in names


def test_handle_and_all_finalization_dicts_are_json_safe_without_runtime_capabilities():
    mod = importlib.import_module("platform_core.execution.environment")
    handle = mod.EnvHandle(work_dir="/w", backend="remote", meta={"id": "x"},
                           capabilities=mod.Capability.EXEC,
                           requires_canonical_landing=True, runtime_token=object())
    encoded_handle = handle.toDict()
    assert "runtime_token" not in encoded_handle
    assert "capabilities" not in encoded_handle or isinstance(encoded_handle["capabilities"], list)
    json.dumps(encoded_handle)
    prepared = mod.PreparedFinalization(runtime_token=object(), summary={"ok": True})
    final = mod.FinalizationReceipt(summary={"ok": True})
    for value in (prepared.toDict(), final.toDict()):
        assert "runtime_token" not in value
        json.dumps(value)


def test_environment_defaults_fail_closed_for_staged_landing():
    mod = importlib.import_module("platform_core.execution.environment")
    for name in ("prepareChanges", "preparedChangesIntact", "completeChanges",
                 "checkpointRecovery"):
        assert name in mod.ExecutionEnvironment.__dict__
