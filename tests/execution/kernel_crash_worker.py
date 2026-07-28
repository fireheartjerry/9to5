"""Fresh-process hard-death worker for the transactional promotion tests."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from platform_core.core.galaxy_evidence import canonical_digest
from platform_core.execution.object_parser import (
    CandidateSnapshot,
    ParsedCandidateSnapshot,
    SnapshotEntry,
)
from platform_core.runtime import candidate as candidate_mod
from platform_core.runtime.attempt_journal import AttemptJournal
from platform_core.runtime.candidate import (
    RunnerKind,
    StagedRevisionLease,
    StagingCoordinator,
    StagingRequest,
)
from platform_core.runtime.canonical_repo import CanonicalRepositoryAttestation
from platform_core.runtime.git_object_writer import (
    CommitMetadata,
    GitObjectWriter,
    ObjectRecord,
)
from platform_core.runtime.loose_refs import LooseRefStore
from platform_core.runtime.object_manifest import ManifestPolicy, ObjectManifest
from platform_core.runtime.receipts import PromotionAuthorization, ReceiptStore
from platform_core.runtime.sha1dc import qualifyGitSha1dc


def _load(path: Path) -> dict:
    def reject_duplicates(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate JSON key: {key}")
            value[key] = item
        return value

    raw = path.read_bytes()
    value = json.loads(
        raw.decode("utf-8", errors="strict"),
        object_pairs_hook=reject_duplicates,
    )
    if not isinstance(value, dict):
        raise ValueError("crash case must be an object")
    return value


def _request(value: dict) -> StagingRequest:
    snapshot_value = value["snapshot"]
    policy = ManifestPolicy.fromDict(snapshot_value["policy"])
    snapshot = CandidateSnapshot(
        transaction_id=snapshot_value["transaction_id"],
        blob_root=Path(snapshot_value["blob_root"]),
        entries=tuple(
            SnapshotEntry(**entry) for entry in snapshot_value["entries"]
        ),
        policy=policy,
    )
    parsed_value = value["parsed"]
    parsed = ParsedCandidateSnapshot(
        transaction_id=parsed_value["transaction_id"],
        manifest=ObjectManifest.fromDict(parsed_value["manifest"]),
        snapshot_digest=parsed_value["snapshot_digest"],
        blob_set_digest=parsed_value["blob_set_digest"],
        diff_digest=parsed_value["diff_digest"],
        parser_version_digest=parsed_value["parser_version_digest"],
        receipt_id=parsed_value["receipt_id"],
        raw_result=base64.b64decode(
            parsed_value["raw_result_base64"],
            validate=True,
        ),
        container_network_allowed=parsed_value["container_network_allowed"],
    )
    return StagingRequest(
        transaction_id=value["transaction_id"],
        task_id=value["task_id"],
        subtask_id=value["subtask_id"],
        attempt_id=value["attempt_id"],
        runner_kind=RunnerKind(value["runner_kind"]),
        snapshot=snapshot,
        parsed=parsed,
        expected_manifest=ObjectManifest.fromDict(value["expected_manifest"]),
        commit_metadata=CommitMetadata(**value["commit_metadata"]),
        cleanup_token=object(),
    )


def _verify_loose(raw: bytes, record: ObjectRecord, oracle) -> str:
    try:
        frame = zlib.decompress(raw)
        header, payload = frame.split(b"\0", 1)
        object_type_raw, size_raw = header.split(b" ", 1)
        object_type = object_type_raw.decode("ascii", errors="strict")
        size = int(size_raw.decode("ascii", errors="strict"))
    except (ValueError, UnicodeError, zlib.error) as exc:
        raise ValueError("loose object framing differs") from exc
    if (
        size != len(payload)
        or object_type != record.object_type
        or record.size != len(payload)
        or hashlib.sha256(payload).hexdigest() != record.payload_sha256
        or hashlib.sha256(frame).hexdigest() != record.framed_object_sha256
        or oracle.hashObject(object_type, payload) != record.oid
    ):
        raise ValueError("loose object evidence differs")
    return canonical_digest(
        {
            "oid": record.oid,
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "frame_sha256": record.framed_object_sha256,
        }
    )


def _coordinator(case: dict, mode: str):
    attestation = CanonicalRepositoryAttestation(**case["attestation"])
    evidence, oracle = qualifyGitSha1dc(
        executable=case["git_executable"],
        sterile_root=Path(case["object_root"]).parent / f"sha1dc-{mode}",
    )
    writer = GitObjectWriter(
        object_root=case["object_root"],
        blob_root=case["blob_root"],
        sha1dc_oracle=oracle,
        sha1dc_evidence=evidence,
        writer_version_digest=case["writer_version_digest"],
        forbidden_roots=(attestation.canonical_root,),
        canonical_object_verifier=lambda raw, record: _verify_loose(
            raw,
            record,
            oracle,
        ),
    )
    capability = object()
    issuer = candidate_mod._buildDiagnosticLandingAuthorityIssuer(
        run_id="fresh-process-crash-run",
        controller_generation=7,
        watchdog_generation=11,
        process_capability=capability,
        canonical_repository_id=attestation.repository_id,
        repository_attestation_digest=attestation.attestation_digest,
        expected_base_sha=attestation.head_oid,
        recovery_quiescence_probe=lambda _transaction_id: True,
    )
    admission = issuer.issueRunAdmission(
        process_capability=capability,
        deadline=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    coordinator = StagingCoordinator(
        attestation=attestation,
        journal=AttemptJournal(case["journal_root"]),
        receipt_store=ReceiptStore(
            case["receipt_root"],
            forbidden_roots=(attestation.canonical_root,),
        ),
        ref_store=LooseRefStore(attestation),
        writer=writer,
        parser_image_digest=case["parser_image_digest"],
        parser_security_profile_digest=case["parser_security_profile_digest"],
        landing_authority_issuer=issuer,
        run_admission=admission,
    )
    return coordinator, issuer, admission


def _crash(case: dict, crash_point: str) -> int:
    coordinator, issuer, admission = _coordinator(case, "crash")
    request = _request(case["request"])
    lease_value = dict(case["lease"])
    lease_value["runner_kind"] = RunnerKind(lease_value["runner_kind"])
    lease = StagedRevisionLease(**lease_value, cleanup_token=object())
    authorization = PromotionAuthorization(**case["authorization"])
    coordinator._live_requests[request.transaction_id] = request
    authority = issuer.issueLandingAuthority(
        admission=admission,
        authorization=authorization,
    )

    def terminate(name: str) -> None:
        if name == crash_point:
            os._exit(97)

    coordinator.promoteStagedRevision(
        lease,
        authorization,
        authority,
        failpoint=terminate,
    )
    return 3


def _recover(case: dict) -> int:
    coordinator, issuer, admission = _coordinator(case, "recover")
    transaction_id = case["request"]["transaction_id"]
    recovery = issuer.issueRecoveryAuthority(
        admission=admission,
        repository_id=coordinator.attestation.repository_id,
        transaction_id=transaction_id,
    )
    coordinator.reconcileAttempt(recovery, transaction_id)
    record = coordinator.journal.load(transaction_id)
    sys.stdout.write(
        json.dumps(
            {"phase": record.phase.value, "sequence": record.sequence},
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


def main(argv: list[str]) -> int:
    if len(argv) not in {3, 4}:
        return 2
    mode = argv[1]
    case = _load(Path(argv[2]))
    if mode == "crash" and len(argv) == 4:
        return _crash(case, argv[3])
    if mode == "recover" and len(argv) == 3:
        return _recover(case)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
