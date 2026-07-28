"""Implementation-backed 1,000-seed crash campaign for attempt truth."""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import replace
from pathlib import Path

import pytest

from platform_core.core.fsio import (
    durableAtomicReplaceBytes,
    exclusiveCreateBytes,
    readNoFollowBytes,
)
from platform_core.execution.environment import FinalizationReceipt
from platform_core.runtime.attempt_journal import (
    AttemptJournal,
    AttemptPhase,
    AttemptRecord,
    IncompleteResourceSet,
    MissingResourceSet,
)
from platform_core.runtime.candidate import (
    ProcessResourceState,
    ResourceRole,
    RuntimeResourceLease,
)
from platform_core.runtime.receipts import (
    CleanupReceipt,
    PromotionReceipt,
    ReceiptStore,
)

EXPECTED = "a" * 40
PROPOSED = "b" * 40
PROPOSED_TREE = "c" * 40
STAGING_RECEIPT = "1" * 64
VERIFICATION_RECEIPT = "2" * 64
REVIEW_RECEIPT = "3" * 64
CREATED_AT = "2026-07-16T12:00:00+00:00"

FAILPOINTS = (
    "lease_registered",
    "resources_registered",
    "resources_quiesced",
    "snapshot_persisted",
    "candidate_checkpointed",
    "staged_prepared",
    "verified",
    "promotion_prepared",
    "index_fenced",
    "before_ref_rename",
    "after_ref_rename",
    "ref_moved",
    "materialized",
    "promotion_receipt",
    "promoted",
    "task_state_pending",
    "task_state_acknowledged",
    "cleanup_receipt",
    "cleanup_complete",
    "done_snapshot",
    "terminal_state_persisted",
)
CAMPAIGN_BATCHES = tuple(
    tuple(range(start, start + 100))
    for start in range(0, 1000, 100)
)


class SimulatedHardDeath(BaseException):
    pass


def _record(root: Path, seed: int) -> AttemptRecord:
    transaction_id = f"tx-crash-{seed:04d}"
    return AttemptRecord(
        transaction_id=transaction_id,
        task_id=f"task-{seed:04d}",
        subtask_id=f"subtask-{seed:04d}",
        attempt_id=f"attempt-{seed:04d}",
        repository_id="4" * 64,
        canonical_root=str(root / "canonical" / transaction_id),
        canonical_ref="refs/heads/main",
        base_revision=EXPECTED,
        candidate_kind="clone",
        clone_lease_id=f"clone-{seed:04d}",
        clone_path=str(root / "clones" / transaction_id),
        ownership_nonce="5" * 64,
        spec_digest="6" * 64,
        policy_digest="7" * 64,
        canonical_metadata_attestation_digest="8" * 64,
        object_format="sha1",
        oid_length=40,
        ref_backend="files",
        candidate_branch=f"refs/heads/9to5/candidates/{transaction_id}",
        checkpoint_message_digest="9" * 64,
        proposal_message_digest="a" * 64,
        commit_timestamp_seed=CREATED_AT,
        runner_kind="local",
        candidate_git_dir=str(root / "clones" / transaction_id / ".git"),
        canonical_git_common_dir=str(
            root / "canonical" / transaction_id / ".git"
        ),
        source_manifest_digest="b" * 64,
        source_object_closure_digest="c" * 64,
        source_snapshot_digest="d" * 64,
        source_parser_receipt_id="e" * 64,
        source_payload_root=str(root / "source-payloads" / transaction_id),
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
    )


def _process_resource(
    record: AttemptRecord,
    seed: int,
    *,
    role: ResourceRole,
    backend: str,
    depends_on: tuple[str, ...] = (),
) -> RuntimeResourceLease:
    return RuntimeResourceLease(
        resource_id=f"{role.value}-{seed:04d}",
        run_id="run-crash-campaign",
        transaction_id=record.transaction_id,
        controller_scope_id="controller-crash-campaign",
        role=role,
        backend=backend,
        ownership_nonce=record.ownership_nonce,
        state=ProcessResourceState.REGISTERED,
        cleanup_locator_digest="f" * 64,
        pid=0,
        process_group_id=0,
        container_id="",
        image_digest="2" * 64 if backend == "docker" else "",
        entrypoint_digest="3" * 64,
        mount_digest="4" * 64,
        environment_digest="5" * 64,
        security_profile_digest="1" * 64,
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
        depends_on=depends_on,
    )


def _runtime_closure(
    record: AttemptRecord,
    seed: int,
) -> tuple[RuntimeResourceLease, ...]:
    watchdog = _process_resource(
        record,
        seed,
        role=ResourceRole.AUTHORITY_WATCHDOG,
        backend="local",
    )
    watchdog_identity = f"{watchdog.role.value}:{watchdog.resource_id}"
    driver = _process_resource(
        record,
        seed,
        role=ResourceRole.MODEL_DRIVER,
        backend="local",
        depends_on=(watchdog_identity,),
    )
    driver_identity = f"{driver.role.value}:{driver.resource_id}"
    parser = _process_resource(
        record,
        seed,
        role=ResourceRole.CANDIDATE_PARSER,
        backend="docker",
        depends_on=(watchdog_identity, driver_identity),
    )
    parser_identity = f"{parser.role.value}:{parser.resource_id}"
    verifier = _process_resource(
        record,
        seed,
        role=ResourceRole.VERIFIER,
        backend="docker",
        depends_on=(watchdog_identity, parser_identity),
    )
    return tuple(
        sorted(
            (watchdog, driver, parser, verifier),
            key=lambda resource: f"{resource.role.value}:{resource.resource_id}",
        )
    )


def _with_runtime_manifest(
    record: AttemptRecord,
    resources: tuple[RuntimeResourceLease, ...],
) -> AttemptRecord:
    raw = json.dumps(
        {
            "resources": [
                {
                    "backend": resource.backend,
                    "depends_on": list(resource.depends_on),
                    "resource_identity": (
                        f"{resource.role.value}:{resource.resource_id}"
                    ),
                }
                for resource in resources
            ],
            "runner_kind": record.runner_kind,
            "schema": "galaxy.runtime-resource-manifest/v1",
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return replace(
        record,
        runtime_resource_manifest_json=raw,
        runtime_resource_manifest_digest=hashlib.sha256(
            raw.encode("utf-8")
        ).hexdigest(),
    )


def _promotion_receipt(record: AttemptRecord) -> PromotionReceipt:
    return PromotionReceipt(
        transaction_id=record.transaction_id,
        staging_receipt_id=STAGING_RECEIPT,
        verification_receipt_id=VERIFICATION_RECEIPT,
        review_receipt_id=REVIEW_RECEIPT,
        expected_revision=EXPECTED,
        observed_revision=EXPECTED,
        proposed_revision=PROPOSED,
        resulting_revision=PROPOSED,
        canonical_index_revision=PROPOSED_TREE,
        canonical_tree_revision=PROPOSED_TREE,
        custom_lock_owner_digest="3" * 64,
        index_fence_owner_digest="4" * 64,
        cas_result="moved",
        intent_ref=f"refs/9to5/promotion-intent/{record.transaction_id}",
        intent_oid=PROPOSED,
        materialization_result="exact",
        postcondition_digest="5" * 64,
    )


def _finalization_receipt(record: AttemptRecord) -> FinalizationReceipt:
    return FinalizationReceipt(
        backend="clone",
        accepted=True,
        requires_canonical_landing=True,
        collected=True,
        merged=True,
        expected_revision=EXPECTED,
        observed_revision=EXPECTED,
        resulting_revision=PROPOSED,
        verification_revision=PROPOSED,
        promotion_transaction_id=record.transaction_id,
        staging_receipt_id=STAGING_RECEIPT,
        verification_receipt_id=VERIFICATION_RECEIPT,
        review_receipt_id=REVIEW_RECEIPT,
        promotion_receipt_id=_promotion_receipt(record).receipt_id,
        materialized=True,
        journal_phase="promoted",
    )


def _cleanup_receipt(record: AttemptRecord) -> CleanupReceipt:
    finalization = _finalization_receipt(record)
    return CleanupReceipt(
        transaction_id=record.transaction_id,
        finalization_receipt_id=finalization.receipt_id,
        previous_cleanup_receipt_id="",
        removed_artifact_ids=(f"candidate:{record.transaction_id}",),
        retained_artifact_ids=(f"checkpoint:{record.transaction_id}",),
        failed_artifact_ids=(),
        warnings=(),
        complete=True,
        completed_at="2026-07-16T12:30:00+00:00",
    )


class _CampaignAttempt:
    def __init__(
        self,
        *,
        root: Path,
        journal: AttemptJournal,
        receipts: ReceiptStore,
        seed: int,
        crash_after: str,
    ) -> None:
        self.root = root
        self.journal = journal
        self.receipts = receipts
        self.seed = seed
        provisional = _record(root, seed)
        self.resources = _runtime_closure(provisional, seed)
        self.record = _with_runtime_manifest(provisional, self.resources)
        self.crash_after = crash_after
        self.truth_root = root / "truth" / self.record.transaction_id
        self.truth_root.mkdir(parents=True)
        self.ref_path = self.truth_root / "canonical.ref"
        self.cas_marker = self.truth_root / "canonical.cas"
        self.snapshot_path = self.truth_root / "snapshot.json"
        self.done_path = self.truth_root / "done.json"
        exclusiveCreateBytes(self.ref_path, (EXPECTED + "\n").encode("ascii"))

    def point(self, name: str) -> None:
        if name == self.crash_after:
            raise SimulatedHardDeath(name)

    def _bind_promotion_plan(self) -> None:
        transaction_id = self.record.transaction_id
        canonical_index = Path(self.record.canonical_git_common_dir) / "index"
        self.journal.bind_promotion_plan(
            transaction_id,
            intent_ref=f"refs/9to5/promotion-intent/{transaction_id}",
            proposed_index_digest="6" * 64,
            proposed_index_path=str(self.truth_root / "proposed.index"),
            canonical_index_path=str(canonical_index),
            index_fence_path=str(canonical_index.with_name("index.lock")),
            orig_head_fence_path=str(canonical_index.with_name("ORIG_HEAD.lock")),
            index_fence_nonce="7" * 64,
            index_fence_owner_digest="4" * 64,
            orig_head_fence_owner_digest="8" * 64,
            custom_lock_path=str(self.truth_root / "promotion.lock"),
            custom_lock_owner_digest="3" * 64,
            canonical_ref_lock_path=str(
                Path(self.record.canonical_git_common_dir)
                / "refs"
                / "heads"
                / "main.lock"
            ),
            canonical_ref_lock_owner_digest="9" * 64,
            materialization_manifest_digest="a" * 64,
            index_install_sibling=str(self.truth_root / "index.install"),
        )
        self.journal.bind_promotion_artifact_identities(
            transaction_id,
            custom_lock_identity_digest="b" * 64,
            index_fence_identity_digest="c" * 64,
            orig_head_fence_identity_digest="d" * 64,
            canonical_ref_lock_identity_digest="e" * 64,
        )

    def _finish_success_axes(self) -> None:
        transaction_id = self.record.transaction_id
        current = self.journal.load(transaction_id)
        if not current.task_state_acknowledged:
            self.journal.mark_task_state_acknowledged(transaction_id)
        finalization = _finalization_receipt(self.record)
        self.receipts.put(finalization)
        current = self.journal.load(transaction_id)
        if not current.finalization_receipt_id:
            self.journal.append_finalization_receipt(
                transaction_id,
                finalization.receipt_id,
            )
        cleanup = _cleanup_receipt(self.record)
        self.receipts.put(cleanup)
        current = self.journal.load(transaction_id)
        if not current.cleanup_receipt_id:
            self.journal.append_cleanup_receipt(
                transaction_id,
                cleanup.receipt_id,
                finalization_receipt_id=finalization.receipt_id,
                previous_cleanup_receipt_id="",
                complete=True,
            )
        try:
            exclusiveCreateBytes(self.done_path, b'{"status":"done"}\n')
        except FileExistsError:
            if readNoFollowBytes(self.done_path, max_bytes=64) != b'{"status":"done"}\n':
                raise AssertionError("done snapshot collision")
        current = self.journal.load(transaction_id)
        if not current.terminal_state_persisted:
            self.journal.mark_terminal_state_persisted(transaction_id)

    def run(self) -> None:
        transaction_id = self.record.transaction_id
        self.journal.create(self.record)
        self.point("lease_registered")
        resources = self.journal.register_resources(
            transaction_id,
            self.resources,
        )
        self.point("resources_registered")
        self.journal.transition(
            transaction_id,
            AttemptPhase.RUNNING,
            resource_lease_ids=tuple(
                f"{resource.role.value}:{resource.resource_id}"
                for resource in resources
            ),
        )
        for resource in resources:
            self.journal.transition_resource(
                transaction_id,
                resource.resource_id,
                ProcessResourceState.QUIESCED,
            )
        self.point("resources_quiesced")
        exclusiveCreateBytes(self.snapshot_path, b'{"snapshot":"exact"}\n')
        self.point("snapshot_persisted")
        self.journal.transition(
            transaction_id,
            AttemptPhase.CANDIDATE_CHECKPOINTED,
            checkpoint_revision=PROPOSED,
            checkpoint_ref=f"refs/9to5/checkpoints/{transaction_id}",
            candidate_snapshot_digest="1" * 64,
            parser_manifest_digest="2" * 64,
            blob_set_digest="3" * 64,
        )
        self.point("candidate_checkpointed")
        self.journal.transition(
            transaction_id,
            AttemptPhase.STAGED_PREPARED,
            staging_receipt_id=STAGING_RECEIPT,
            proposed_revision=PROPOSED,
            proposed_tree=PROPOSED_TREE,
            proposed_diff_digest="4" * 64,
            staged_ref=f"refs/9to5/staged/{transaction_id}",
            staging_manifest_bundle_digest="5" * 64,
            expected_manifest_digest=self.record.source_manifest_digest,
            proposed_manifest_digest="2" * 64,
        )
        self.point("staged_prepared")
        self.journal.transition(
            transaction_id,
            AttemptPhase.VERIFIED,
            verification_receipt_id=VERIFICATION_RECEIPT,
            verified_revision=PROPOSED,
        )
        self.point("verified")
        self.journal.transition(
            transaction_id,
            AttemptPhase.PROMOTION_PREPARED,
            review_receipt_id=REVIEW_RECEIPT,
        )
        self.point("promotion_prepared")
        self._bind_promotion_plan()
        self.journal.transition(transaction_id, AttemptPhase.INDEX_FENCED)
        self.point("index_fenced")
        self.point("before_ref_rename")
        exclusiveCreateBytes(
            self.cas_marker,
            (transaction_id + "\n").encode("ascii"),
        )
        durableAtomicReplaceBytes(self.ref_path, (PROPOSED + "\n").encode("ascii"))
        self.point("after_ref_rename")
        self.journal.transition(
            transaction_id,
            AttemptPhase.REF_MOVED,
            observed_revision=EXPECTED,
            resulting_revision=PROPOSED,
        )
        self.point("ref_moved")
        self.journal.transition(
            transaction_id,
            AttemptPhase.MATERIALIZED,
            canonical_index_digest="6" * 64,
            canonical_tree_digest="6" * 64,
        )
        self.point("materialized")
        promotion = _promotion_receipt(self.record)
        self.receipts.put(promotion)
        self.point("promotion_receipt")
        self.journal.transition(
            transaction_id,
            AttemptPhase.PROMOTED,
            promotion_receipt_id=promotion.receipt_id,
        )
        self.point("promoted")
        self.point("task_state_pending")
        self.journal.mark_task_state_acknowledged(transaction_id)
        self.point("task_state_acknowledged")
        finalization = _finalization_receipt(self.record)
        self.receipts.put(finalization)
        self.journal.append_finalization_receipt(
            transaction_id,
            finalization.receipt_id,
        )
        cleanup = _cleanup_receipt(self.record)
        self.receipts.put(cleanup)
        self.point("cleanup_receipt")
        self.journal.append_cleanup_receipt(
            transaction_id,
            cleanup.receipt_id,
            finalization_receipt_id=finalization.receipt_id,
            previous_cleanup_receipt_id="",
            complete=True,
        )
        self.point("cleanup_complete")
        exclusiveCreateBytes(self.done_path, b'{"status":"done"}\n')
        self.point("done_snapshot")
        self.journal.mark_terminal_state_persisted(transaction_id)
        self.point("terminal_state_persisted")

    def recover(self) -> None:
        transaction_id = self.record.transaction_id
        try:
            resources = self.journal.load_resources(transaction_id)
        except (MissingResourceSet, IncompleteResourceSet):
            resources = self.journal.register_resources(
                transaction_id,
                self.resources,
            )
        current = self.journal.load(transaction_id)
        if current.phase is AttemptPhase.LEASE_REGISTERED:
            current = self.journal.transition(
                transaction_id,
                AttemptPhase.RUNNING,
                resource_lease_ids=tuple(
                    f"{resource.role.value}:{resource.resource_id}"
                    for resource in resources
                ),
            )
        for resource in resources:
            if resource.state not in {
                ProcessResourceState.QUIESCED,
                ProcessResourceState.COLLECTED,
            }:
                self.journal.transition_resource(
                    transaction_id,
                    resource.resource_id,
                    ProcessResourceState.QUIESCED,
                )
        current = self.journal.load(transaction_id)
        observed = readNoFollowBytes(self.ref_path, max_bytes=64).decode("ascii").strip()
        if observed == PROPOSED:
            if current.phase is AttemptPhase.INDEX_FENCED:
                current = self.journal.transition(
                    transaction_id,
                    AttemptPhase.REF_MOVED,
                    observed_revision=EXPECTED,
                    resulting_revision=PROPOSED,
                )
            if current.phase is AttemptPhase.REF_MOVED:
                current = self.journal.transition(
                    transaction_id,
                    AttemptPhase.MATERIALIZED,
                    canonical_index_digest="6" * 64,
                    canonical_tree_digest="6" * 64,
                )
            if current.phase is AttemptPhase.MATERIALIZED:
                promotion = _promotion_receipt(self.record)
                self.receipts.put(promotion)
                current = self.journal.transition(
                    transaction_id,
                    AttemptPhase.PROMOTED,
                    promotion_receipt_id=promotion.receipt_id,
                )
            if current.phase is not AttemptPhase.PROMOTED:
                raise AssertionError("proposed canonical truth was not recoverable")
            self._finish_success_axes()
            return
        if observed != EXPECTED:
            raise AssertionError("canonical truth escaped the closed revision set")
        if current.phase in {
            AttemptPhase.VERIFIED,
            AttemptPhase.PROMOTION_PREPARED,
            AttemptPhase.INDEX_FENCED,
        }:
            self.journal.transition(
                transaction_id,
                AttemptPhase.NOT_PROMOTED,
                error="crash recovery proved the canonical ref did not move",
                reconciliation_outcome="not_promoted",
            )
        elif current.phase not in {
            AttemptPhase.REJECTED,
            AttemptPhase.NOT_PROMOTED,
        }:
            self.journal.transition(
                transaction_id,
                AttemptPhase.REJECTED,
                error="crash recovery rejected an incomplete attempt",
            )

    def assert_invariants(self) -> None:
        current = self.journal.load(self.record.transaction_id)
        resources = self.journal.load_resources(self.record.transaction_id)
        expected_resource_ids = tuple(
            f"{resource.role.value}:{resource.resource_id}"
            for resource in self.resources
        )
        observed_resource_ids = tuple(
            f"{resource.role.value}:{resource.resource_id}"
            for resource in resources
        )
        if observed_resource_ids != expected_resource_ids:
            raise AssertionError("runtime resource closure differs")
        if any(
            resource.state is not ProcessResourceState.QUIESCED
            for resource in resources
        ):
            raise AssertionError("runtime resource closure is not quiesced")
        observed = readNoFollowBytes(self.ref_path, max_bytes=64).decode("ascii").strip()
        promoted = current.phase is AttemptPhase.PROMOTED
        if promoted:
            promotion = _promotion_receipt(self.record)
            if observed != PROPOSED or current.promotion_receipt_id != promotion.receipt_id:
                raise AssertionError("durable promotion truth differs")
            if self.receipts.read(
                promotion.receipt_id,
                expected_type=PromotionReceipt,
            ) != promotion:
                raise AssertionError("promotion receipt replay differs")
            if not (
                current.task_state_acknowledged
                and current.cleanup_complete
                and current.terminal_state_persisted
            ):
                raise AssertionError("promoted attempt lacks final durable axes")
            if readNoFollowBytes(self.done_path, max_bytes=64) != b'{"status":"done"}\n':
                raise AssertionError("done snapshot differs")
            if readNoFollowBytes(self.cas_marker, max_bytes=256) != (
                self.record.transaction_id + "\n"
            ).encode("ascii"):
                raise AssertionError("canonical CAS marker differs")
        else:
            if observed != EXPECTED or current.promotion_receipt_id:
                raise AssertionError("non-promoted attempt fabricated landing truth")
            if self.done_path.exists() or self.cas_marker.exists():
                raise AssertionError("pre-CAS crash fabricated terminal or CAS truth")


@pytest.mark.parametrize(
    "seeds",
    CAMPAIGN_BATCHES,
    ids=lambda seeds: f"seeds-{seeds[0]:04d}-{seeds[-1]:04d}",
)
def test_one_thousand_seeded_crashes_never_fabricate_or_lose_promotion(
    tmp_path: Path,
    seeds: tuple[int, ...],
) -> None:
    journal = AttemptJournal(tmp_path / "journal", diagnostic=True)
    receipts = ReceiptStore(tmp_path / "receipts")
    for seed in seeds:
        rng = random.Random(seed)
        crash_after = FAILPOINTS[rng.randrange(len(FAILPOINTS))]
        campaign = _CampaignAttempt(
            root=tmp_path,
            journal=journal,
            receipts=receipts,
            seed=seed,
            crash_after=crash_after,
        )
        try:
            campaign.run()
        except SimulatedHardDeath:
            pass
        campaign.recover()
        campaign.assert_invariants()


def test_one_thousand_seed_registry_covers_every_crash_boundary() -> None:
    covered = {
        FAILPOINTS[random.Random(seed).randrange(len(FAILPOINTS))]
        for seeds in CAMPAIGN_BATCHES
        for seed in seeds
    }
    assert covered == set(FAILPOINTS)
