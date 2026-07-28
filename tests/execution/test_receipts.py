"""Transactional-kernel immutable receipt and authorization contracts."""
from __future__ import annotations

import os
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from platform_core.execution.environment import FinalizationReceipt
from platform_core.runtime.attempt_journal import AttemptJournal, AttemptPhase, AttemptRecord
from platform_core.runtime.candidate import (
    ProcessResourceState,
    ResourceRole,
    RuntimeResourceLease,
)
from platform_core.runtime.receipts import (
    CleanupReceipt,
    PromotionAuthorization,
    PromotionReceipt,
    ReceiptCollision,
    ReceiptCorruption,
    ReceiptPathViolation,
    ReceiptStore,
    ReviewDecision,
    ReviewReceipt,
    RevisionVerificationReceipt,
    SelectionReceipt,
    StagingReceipt,
    validatePromotionAuthorization,
)

SHA_A = "a" * 40
SHA_B = "b" * 40
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64


def _staging() -> StagingReceipt:
    return StagingReceipt(
        transaction_id="tx-001",
        source_snapshot_digest=DIGEST_A,
        parser_receipt_id=DIGEST_B,
        parser_manifest_digest=DIGEST_C,
        blob_set_digest="d" * 64,
        parser_image_digest="e" * 64,
        parser_runtime_digest="f" * 64,
        parser_security_profile_digest="1" * 64,
        object_writer_version_digest="2" * 64,
        expected_parent=SHA_A,
        proposed_commit=SHA_B,
        proposed_tree="c" * 40,
        proposed_diff_digest="3" * 64,
        proposed_commit_content_digest="4" * 64,
        proposed_tree_content_digest="5" * 64,
        object_closure_digest="6" * 64,
        proposed_index_digest="7" * 64,
        staged_ref="refs/9to5/staged/tx-001",
        policy_manifest_digest="8" * 64,
        commit_metadata_digest="9" * 64,
        commit_timestamp="2026-07-16T12:00:00+00:00",
    )


def _verification(staging: StagingReceipt) -> RevisionVerificationReceipt:
    return RevisionVerificationReceipt(
        transaction_id=staging.transaction_id,
        staging_receipt_id=staging.receipt_id,
        passed=True,
        proposed_revision=staging.proposed_commit,
        verified_revision=staging.proposed_commit,
        verification_clone_revision=staging.proposed_commit,
        execution_origin_tier="hostile-docker",
        verification_clone_id="verify-clone-001",
        container_resource_id="container-001",
        verifier_image_digest=DIGEST_A,
        verifier_sbom_digest=DIGEST_B,
        watchdog_generation=3,
        verification_command_authority_receipt_id=DIGEST_C,
        command_evidence_digest="d" * 64,
        evidence_id="evidence-001",
        tracked_tree_before_digest="e" * 64,
        tracked_tree_after_digest="e" * 64,
    )


def _review(staging: StagingReceipt) -> ReviewReceipt:
    return ReviewReceipt(
        transaction_id=staging.transaction_id,
        staging_receipt_id=staging.receipt_id,
        proposed_revision=staging.proposed_commit,
        target_evidence_digest=DIGEST_A,
        reviewer_id="reviewer-001",
        reviewer_provider="codex",
        clean_room_context_digest=DIGEST_B,
        findings_digest=DIGEST_C,
        contamination_controls_digest="d" * 64,
        decision=ReviewDecision.PERMIT,
        policy_id="kernel-review-v1",
        policy_version="1",
        policy_inputs_digest="e" * 64,
        independent=True,
    )


def test_receipt_is_frozen_content_addressed_and_round_trips(tmp_path: Path) -> None:
    receipt = _staging()
    first_id = receipt.receipt_id
    assert len(first_id) == 64
    with pytest.raises(FrozenInstanceError):
        receipt.error = "rewritten"  # type: ignore[misc]

    store = ReceiptStore(tmp_path / "controller" / "receipts")
    stored = store.put(receipt)
    assert stored.receipt_id == first_id
    assert store.put(receipt) == stored  # exact replay is idempotent
    assert store.read(first_id, expected_type=StagingReceipt) == receipt


def test_receipt_store_quarantines_but_never_replaces_corrupt_node(tmp_path: Path) -> None:
    store = ReceiptStore(tmp_path / "receipts")
    receipt = _staging()
    stored = store.put(receipt)
    stored.path.write_bytes(b'{"forged":true}')

    with pytest.raises(ReceiptCorruption):
        store.read(receipt.receipt_id, expected_type=StagingReceipt)

    assert stored.path.read_bytes() == b'{"forged":true}'
    quarantined = list((store.root / "quarantine").glob("*.corrupt"))
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes() == b'{"forged":true}'


def test_put_refuses_digest_path_collision_without_overwrite(tmp_path: Path) -> None:
    store = ReceiptStore(tmp_path / "receipts")
    receipt = _staging()
    path = store.path_for(receipt.receipt_id)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not-the-canonical-node")

    with pytest.raises(ReceiptCollision):
        store.put(receipt)
    assert path.read_bytes() == b"not-the-canonical-node"


def test_receipt_store_rejects_forbidden_or_reparse_roots(tmp_path: Path) -> None:
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    with pytest.raises(ReceiptPathViolation):
        ReceiptStore(canonical / "state", forbidden_roots=(canonical,))
    with pytest.raises(ReceiptPathViolation):
        ReceiptStore(tmp_path, forbidden_roots=(canonical,))

    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "linked"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable for this account")
    with pytest.raises(ReceiptPathViolation):
        ReceiptStore(link)


def test_receipt_store_refuses_multilink_control_node(tmp_path: Path) -> None:
    store = ReceiptStore(tmp_path / "receipts")
    receipt = _staging()
    stored = store.put(receipt)
    second_name = tmp_path / "second-name.json"
    try:
        os.link(stored.path, second_name)
    except OSError:
        pytest.skip("hardlinks are unavailable for this account")
    with pytest.raises(ReceiptPathViolation, match="multiple links"):
        store.read(receipt.receipt_id, expected_type=StagingReceipt)


def test_passing_verification_requires_exact_revision_and_integrity() -> None:
    staging = _staging()
    values = _verification(staging).__dict__ | {"verified_revision": SHA_A}
    with pytest.raises(ValueError, match="same proposed revision"):
        RevisionVerificationReceipt(**values)

    values = _verification(staging).__dict__ | {
        "tracked_tree_after_digest": DIGEST_C,
    }
    with pytest.raises(ValueError, match="tracked tree integrity"):
        RevisionVerificationReceipt(**values)


def test_promotion_authorization_is_exact_typed_linkage_not_a_boolean() -> None:
    staging = _staging()
    verification = _verification(staging)
    review = _review(staging)
    authorization = PromotionAuthorization(
        transaction_id=staging.transaction_id,
        task_id="task-001",
        subtask_id="subtask-001",
        staging_receipt_id=staging.receipt_id,
        verification_receipt_id=verification.receipt_id,
        review_receipt_id=review.receipt_id,
        proposed_revision=staging.proposed_commit,
        proposed_tree=staging.proposed_tree,
        proposed_diff_digest=staging.proposed_diff_digest,
        spec_digest=DIGEST_A,
        policy_digest=staging.policy_manifest_digest,
    )
    assert authorization.selection_receipt_id == ""

    with pytest.raises(TypeError):
        PromotionAuthorization.from_value(True)


def test_successful_promotion_requires_complete_immutable_chain() -> None:
    staging = _staging()
    verification = _verification(staging)
    review = _review(staging)
    base = dict(
        transaction_id=staging.transaction_id,
        staging_receipt_id=staging.receipt_id,
        verification_receipt_id=verification.receipt_id,
        review_receipt_id=review.receipt_id,
        expected_revision=staging.expected_parent,
        observed_revision=staging.expected_parent,
        proposed_revision=staging.proposed_commit,
        resulting_revision=staging.proposed_commit,
        canonical_index_revision=staging.proposed_tree,
        canonical_tree_revision=staging.proposed_tree,
        custom_lock_owner_digest=DIGEST_A,
        index_fence_owner_digest=DIGEST_B,
        cas_result="moved",
        intent_ref="refs/9to5/promotion-intent/tx-001",
        intent_oid=staging.proposed_commit,
        materialization_result="exact",
        postcondition_digest=DIGEST_C,
    )
    receipt = PromotionReceipt(**base)
    assert receipt.succeeded is True

    with pytest.raises(ValueError, match="resulting revision"):
        PromotionReceipt(**(base | {"resulting_revision": SHA_A}))
    with pytest.raises(ValueError, match="review receipt"):
        PromotionReceipt(**(base | {"review_receipt_id": ""}))


def _journal_at_promotion_prepared(
    tmp_path: Path,
    staging: StagingReceipt,
    verification: RevisionVerificationReceipt,
    review: ReviewReceipt,
    *,
    tournament_batch_id: str = "",
    selection_receipt_id: str = "",
) -> AttemptJournal:
    journal = AttemptJournal(tmp_path / "controller" / "journal")
    record = AttemptRecord(
        transaction_id=staging.transaction_id,
        task_id="task-001",
        subtask_id="subtask-001",
        attempt_id="attempt-001",
        repository_id=DIGEST_A,
        canonical_root=str(tmp_path / "canonical"),
        canonical_ref="refs/heads/main",
        base_revision=staging.expected_parent,
        candidate_kind="clone",
        clone_lease_id="clone-001",
        clone_path=str(tmp_path / "controller" / "checkouts" / staging.transaction_id),
        ownership_nonce=DIGEST_B,
        spec_digest=DIGEST_A,
        policy_digest=staging.policy_manifest_digest,
        canonical_metadata_attestation_digest="f" * 64,
        object_format="sha1",
        oid_length=40,
        ref_backend="files",
        candidate_branch=f"refs/heads/9to5/candidates/{staging.transaction_id}",
        checkpoint_message_digest="1" * 64,
        proposal_message_digest="2" * 64,
        commit_timestamp_seed="2026-07-16T12:00:00+00:00",
        runner_kind="local",
        candidate_git_dir=str(
            tmp_path
            / "controller"
            / "checkouts"
            / staging.transaction_id
            / ".git"
        ),
        canonical_git_common_dir=str(tmp_path / "canonical" / ".git"),
        source_manifest_digest=staging.parser_manifest_digest,
        source_object_closure_digest=staging.object_closure_digest,
        source_snapshot_digest=staging.source_snapshot_digest,
        source_parser_receipt_id=staging.parser_receipt_id,
        source_payload_root=str(tmp_path / "controller" / "source-payloads"),
        tournament_batch_id=tournament_batch_id,
        selection_receipt_id=selection_receipt_id,
        created_at="2026-07-16T12:00:00+00:00",
        updated_at="2026-07-16T12:00:00+00:00",
    )
    journal.create(record)
    runtime_resource = RuntimeResourceLease(
        resource_id="driver-001",
        run_id="run-001",
        transaction_id=record.transaction_id,
        controller_scope_id="controller-001",
        role=ResourceRole.MODEL_DRIVER,
        backend="local",
        ownership_nonce=record.ownership_nonce,
        state=ProcessResourceState.REGISTERED,
        cleanup_locator_digest="3" * 64,
        pid=0,
        process_group_id=0,
        container_id="",
        image_digest="",
        entrypoint_digest="4" * 64,
        mount_digest="5" * 64,
        environment_digest="6" * 64,
        security_profile_digest="7" * 64,
        created_at=record.created_at,
        updated_at=record.created_at,
    )
    journal.register_resources(record.transaction_id, (runtime_resource,))
    journal.transition(
        record.transaction_id,
        AttemptPhase.RUNNING,
        resource_lease_ids=("model_driver:driver-001",),
    )
    journal.transition(
        record.transaction_id,
        AttemptPhase.CANDIDATE_CHECKPOINTED,
        checkpoint_revision=staging.proposed_commit,
        checkpoint_ref=f"refs/9to5/checkpoints/{record.transaction_id}",
        candidate_snapshot_digest=staging.source_snapshot_digest,
        parser_manifest_digest=staging.parser_manifest_digest,
        blob_set_digest=staging.blob_set_digest,
    )
    journal.transition(
        record.transaction_id,
        AttemptPhase.STAGED_PREPARED,
        staging_receipt_id=staging.receipt_id,
        proposed_revision=staging.proposed_commit,
        proposed_tree=staging.proposed_tree,
        proposed_diff_digest=staging.proposed_diff_digest,
        staged_ref=staging.staged_ref,
        staging_manifest_bundle_digest="8" * 64,
        expected_manifest_digest=record.source_manifest_digest,
        proposed_manifest_digest=staging.parser_manifest_digest,
    )
    journal.transition(
        record.transaction_id,
        AttemptPhase.VERIFIED,
        verification_receipt_id=verification.receipt_id,
        verified_revision=verification.verified_revision,
    )
    journal.transition(
        record.transaction_id,
        AttemptPhase.PROMOTION_PREPARED,
        review_receipt_id=review.receipt_id,
    )
    return journal


def _authorization(
    staging: StagingReceipt,
    verification: RevisionVerificationReceipt,
    review: ReviewReceipt,
    *,
    selection_receipt_id: str = "",
) -> PromotionAuthorization:
    return PromotionAuthorization(
        transaction_id=staging.transaction_id,
        task_id="task-001",
        subtask_id="subtask-001",
        staging_receipt_id=staging.receipt_id,
        verification_receipt_id=verification.receipt_id,
        review_receipt_id=review.receipt_id,
        selection_receipt_id=selection_receipt_id,
        proposed_revision=staging.proposed_commit,
        proposed_tree=staging.proposed_tree,
        proposed_diff_digest=staging.proposed_diff_digest,
        spec_digest=DIGEST_A,
        policy_digest=staging.policy_manifest_digest,
    )


def test_authorization_validator_rereads_exact_journal_bound_chain(tmp_path: Path) -> None:
    store = ReceiptStore(tmp_path / "controller" / "receipts")
    staging = _staging()
    verification = _verification(staging)
    review = _review(staging)
    for receipt in (staging, verification, review):
        store.put(receipt)
    journal = _journal_at_promotion_prepared(tmp_path, staging, verification, review)

    evidence = validatePromotionAuthorization(
        _authorization(staging, verification, review),
        store=store,
        journal=journal,
    )
    assert evidence.staging == staging
    assert evidence.verification == verification
    assert evidence.review == review
    assert evidence.selection is None


def test_authorization_validator_refuses_cross_transaction_review(tmp_path: Path) -> None:
    store = ReceiptStore(tmp_path / "controller" / "receipts")
    staging = _staging()
    verification = _verification(staging)
    foreign_review = ReviewReceipt(
        **(_review(staging).__dict__ | {"transaction_id": "tx-foreign"})
    )
    for receipt in (staging, verification, foreign_review):
        store.put(receipt)
    journal = _journal_at_promotion_prepared(
        tmp_path, staging, verification, foreign_review
    )

    with pytest.raises(ValueError, match="review transaction"):
        validatePromotionAuthorization(
            _authorization(staging, verification, foreign_review),
            store=store,
            journal=journal,
        )


def test_selection_requires_unique_candidate_subsets_and_dispositions() -> None:
    staging = _staging()
    verification = _verification(staging)
    review = _review(staging)
    base = dict(
        batch_id="batch-001",
        candidate_transaction_ids=(staging.transaction_id, "tx-002"),
        candidate_verification_receipt_ids=(verification.receipt_id, "1" * 64),
        candidate_review_receipt_ids=(review.receipt_id, "2" * 64),
        eligible_transaction_ids=(staging.transaction_id,),
        judge_evidence_digest="3" * 64,
        policy_digest="4" * 64,
        selected_transaction_id=staging.transaction_id,
        loser_transaction_ids=("tx-002",),
    )

    with pytest.raises(ValueError, match="eligible.*unique|eligible.*subset"):
        SelectionReceipt(
            **(
                base
                | {
                    "eligible_transaction_ids": (
                        staging.transaction_id,
                        staging.transaction_id,
                    )
                }
            )
        )
    with pytest.raises(ValueError, match="loser.*unique|disposition"):
        SelectionReceipt(
            **(
                base
                | {
                    "loser_transaction_ids": ("tx-002", "tx-002"),
                }
            )
        )
    with pytest.raises(ValueError, match="eligible.*subset"):
        SelectionReceipt(
            **(base | {"eligible_transaction_ids": ("tx-foreign",)})
        )


def test_tournament_authorization_rereads_every_candidate_chain(
    tmp_path: Path,
) -> None:
    staging = _staging()
    verification = _verification(staging)
    review = _review(staging)
    selection = SelectionReceipt(
        batch_id="batch-001",
        candidate_transaction_ids=(staging.transaction_id, "tx-002"),
        candidate_verification_receipt_ids=(verification.receipt_id, "1" * 64),
        candidate_review_receipt_ids=(review.receipt_id, "2" * 64),
        eligible_transaction_ids=(staging.transaction_id,),
        judge_evidence_digest="3" * 64,
        policy_digest="4" * 64,
        selected_transaction_id=staging.transaction_id,
        loser_transaction_ids=("tx-002",),
    )
    store = ReceiptStore(tmp_path / "controller" / "receipts")
    for receipt in (staging, verification, review, selection):
        store.put(receipt)
    journal = _journal_at_promotion_prepared(
        tmp_path,
        staging,
        verification,
        review,
        tournament_batch_id=selection.batch_id,
        selection_receipt_id=selection.receipt_id,
    )

    with pytest.raises((ReceiptCorruption, ValueError), match="receipt|candidate"):
        validatePromotionAuthorization(
            _authorization(
                staging,
                verification,
                review,
                selection_receipt_id=selection.receipt_id,
            ),
            store=store,
            journal=journal,
        )


def test_tournament_requirement_comes_from_journal_not_caller(tmp_path: Path) -> None:
    staging = _staging()
    verification = _verification(staging)
    review = _review(staging)
    selection = SelectionReceipt(
        batch_id="batch-001",
        candidate_transaction_ids=(staging.transaction_id, "tx-002"),
        candidate_verification_receipt_ids=(verification.receipt_id, "1" * 64),
        candidate_review_receipt_ids=(review.receipt_id, "2" * 64),
        eligible_transaction_ids=(staging.transaction_id, "tx-002"),
        judge_evidence_digest="3" * 64,
        policy_digest="4" * 64,
        selected_transaction_id=staging.transaction_id,
        loser_transaction_ids=("tx-002",),
    )
    store = ReceiptStore(tmp_path / "controller" / "receipts")
    for receipt in (staging, verification, review, selection):
        store.put(receipt)
    journal = _journal_at_promotion_prepared(
        tmp_path,
        staging,
        verification,
        review,
        tournament_batch_id=selection.batch_id,
        selection_receipt_id=selection.receipt_id,
    )
    with pytest.raises(ValueError, match="selection receipt"):
        validatePromotionAuthorization(
            _authorization(staging, verification, review),
            store=store,
            journal=journal,
        )


def test_finalization_receipt_is_content_addressed_and_summary_is_frozen(
    tmp_path: Path,
) -> None:
    source_summary = {"artifacts": ["candidate", "verification"]}
    receipt = FinalizationReceipt(
        backend="clone",
        accepted=True,
        requires_canonical_landing=True,
        collected=True,
        merged=True,
        expected_revision="a" * 40,
        observed_revision="a" * 40,
        resulting_revision="b" * 40,
        verification_revision="b" * 40,
        promotion_transaction_id="tx-finalization-001",
        staging_receipt_id="1" * 64,
        verification_receipt_id="2" * 64,
        review_receipt_id="3" * 64,
        promotion_receipt_id="4" * 64,
        materialized=True,
        journal_phase="promoted",
        summary=source_summary,
    )
    receipt_id = receipt.receipt_id
    source_summary["artifacts"].append("drift")
    assert receipt.receipt_id == receipt_id
    assert receipt.toDict()["summary"] == {
        "artifacts": ["candidate", "verification"]
    }
    store = ReceiptStore(tmp_path / "receipts")
    assert store.put(receipt).receipt_id == receipt_id
    assert store.read(receipt_id, expected_type=FinalizationReceipt) == receipt


def test_cleanup_receipts_form_an_immutable_retry_chain(tmp_path: Path) -> None:
    store = ReceiptStore(tmp_path / "receipts")
    first = CleanupReceipt(
        transaction_id="tx-cleanup-001",
        finalization_receipt_id="1" * 64,
        previous_cleanup_receipt_id="",
        removed_artifact_ids=("candidate:tx-cleanup-001",),
        retained_artifact_ids=("checkpoint:tx-cleanup-001",),
        failed_artifact_ids=("verification:tx-cleanup-001",),
        warnings=("verification: cleanup adapter unavailable",),
        complete=False,
        completed_at="2026-07-16T12:00:00+00:00",
    )
    first_id = store.put(first).receipt_id
    second = CleanupReceipt(
        transaction_id=first.transaction_id,
        finalization_receipt_id=first.finalization_receipt_id,
        previous_cleanup_receipt_id=first_id,
        removed_artifact_ids=(
            "candidate:tx-cleanup-001",
            "verification:tx-cleanup-001",
        ),
        retained_artifact_ids=first.retained_artifact_ids,
        failed_artifact_ids=(),
        warnings=(),
        complete=True,
        completed_at="2026-07-16T12:01:00+00:00",
    )
    second_id = store.put(second).receipt_id
    assert store.read(second_id, expected_type=CleanupReceipt) == second
    assert second.previous_cleanup_receipt_id == first_id

    with pytest.raises(ValueError, match="cannot be complete"):
        CleanupReceipt(
            transaction_id=first.transaction_id,
            finalization_receipt_id=first.finalization_receipt_id,
            previous_cleanup_receipt_id=first_id,
            removed_artifact_ids=first.removed_artifact_ids,
            retained_artifact_ids=first.retained_artifact_ids,
            failed_artifact_ids=first.failed_artifact_ids,
            warnings=first.warnings,
            complete=True,
            completed_at="2026-07-16T12:01:00+00:00",
        )

    with pytest.raises(ValueError, match="one terminal disposition"):
        CleanupReceipt(
            transaction_id=first.transaction_id,
            finalization_receipt_id=first.finalization_receipt_id,
            previous_cleanup_receipt_id=first_id,
            removed_artifact_ids=("candidate:tx-cleanup-001",),
            retained_artifact_ids=("candidate:tx-cleanup-001",),
            failed_artifact_ids=(),
            warnings=(),
            complete=True,
            completed_at="2026-07-16T12:01:00+00:00",
        )


def test_cleanup_receipt_discovery_uses_retained_native_enumeration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ReceiptStore(tmp_path / "receipts")
    receipt = CleanupReceipt(
        transaction_id="tx-cleanup-native",
        finalization_receipt_id="1" * 64,
        previous_cleanup_receipt_id="",
        removed_artifact_ids=("candidate:tx-cleanup-native",),
        retained_artifact_ids=(),
        failed_artifact_ids=(),
        warnings=(),
        complete=True,
        completed_at="2026-07-16T12:00:00+00:00",
    )
    store.put(receipt)

    def forbid_path_enumeration(_self):
        raise AssertionError("receipt discovery used Path.iterdir")

    monkeypatch.setattr(Path, "iterdir", forbid_path_enumeration)
    assert store.find_cleanup_receipts(
        transaction_id=receipt.transaction_id,
        finalization_receipt_id=receipt.finalization_receipt_id,
        previous_cleanup_receipt_id=receipt.previous_cleanup_receipt_id,
    ) == (receipt,)
