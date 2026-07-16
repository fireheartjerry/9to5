"""RED behavioral contracts for TOFU closure and the global transition journal."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


def _anchor():
    return importlib.import_module("bootstrap.galaxy_launcher.anchor")


def _coordinator(tmp_path, *, epoch="epoch-1", owner="owner-1"):
    return _anchor().DurableTransitionCoordinator(tmp_path, epoch=epoch, owner_id=owner)


def _begin_transition(c, *, operation, input_digest):
    slot = c.reserve(operation=operation, input_digest=input_digest)
    purpose = c.issue_purpose(slot, plan_node="test-plan", expected_old="old")
    intent = c.persist_intent(slot, purpose_id=purpose.id)
    begun = c.begin(slot, purpose_id=purpose.id, intent_id=intent.id)
    return slot, purpose, begun


def _complete_transition(c, *, operation, input_digest):
    slot, purpose, begun = _begin_transition(
        c, operation=operation, input_digest=input_digest)
    c.record_cas(slot, owner_token=begun.owner_token, old="old", new="new")
    c.finish(slot, owner_token=begun.owner_token)
    observation = c.observe(slot)
    c.acknowledge(slot, observation_token=observation.token)
    archived = c.archive(slot)
    assert archived.purpose_id == purpose.id
    return archived


def _duplicate_persisted_record(root, needle, *, name):
    candidates = [path for path in Path(root).rglob("*.json")
                  if needle.encode() in path.read_bytes()]
    assert candidates, f"no persisted record contains {needle!r}"
    shutil.copyfile(candidates[0], candidates[0].with_name(name))


def _replace_persisted_text(root, old, new):
    candidates = [path for path in Path(root).rglob("*.json")
                  if old.encode() in path.read_bytes()]
    assert candidates, f"no persisted record contains {old!r}"
    raw = candidates[0].read_bytes()
    candidates[0].write_bytes(raw.replace(old.encode(), new.encode(), 1))


@pytest.mark.parametrize("phase", [
    "purpose", "intent", "begin", "cas", "finish", "observe", "acknowledge", "archive",
])
@pytest.mark.parametrize("edge", ["before_persist", "after_persist"])
def test_every_transition_failpoint_recovers_after_parent_death_or_response_loss(tmp_path, phase, edge):
    mod = _anchor()
    first = _coordinator(tmp_path)
    slot = first.reserve(operation="source_cutover", input_digest="batch-a")
    try:
        first.advance(slot, phase, failpoint=f"{edge}:{phase}")
    except mod.InjectedTransitionCrash:
        pass
    recovered = _coordinator(tmp_path, owner="recovery-owner").recover_all_generations()
    assert len(recovered) == 1
    state = recovered[0]
    assert state.operation == "source_cutover"
    assert state.input_digest == "batch-a"
    assert state.phase in mod.RECOVERABLE_PHASES
    # Repeating after an after-persist response loss is create-or-return/idempotent.
    resumed = _coordinator(tmp_path, owner="recovery-owner").resume(state.slot_id)
    assert resumed.purpose_id == state.purpose_id


def test_transition_happy_path_persists_purpose_through_archive_and_fresh_shell(tmp_path):
    c = _coordinator(tmp_path)
    slot = c.reserve(operation="controller_install", input_digest="batch-a")
    purpose = c.issue_purpose(slot, plan_node="task-1", expected_old="old")
    intent = c.persist_intent(slot, purpose_id=purpose.id)
    begun = c.begin(slot, purpose_id=purpose.id, intent_id=intent.id)
    c.record_cas(slot, owner_token=begun.owner_token, old="old", new="inactive-1")
    c.finish(slot, owner_token=begun.owner_token)
    observation = c.observe(slot)
    c.acknowledge(slot, observation_token=observation.token)
    archived = c.archive(slot)
    assert archived.status == "archived_achieved"
    code = (
        f"import sys;sys.path.insert(0,r'{__import__('pathlib').Path(__file__).resolve().parents[2]}');"
        "from bootstrap.galaxy_launcher.anchor import DurableTransitionCoordinator as C;"
        f"c=C(r'{tmp_path}',epoch='epoch-1',owner_id='fresh-shell');"
        "x=c.lookup_all_generations(operation='controller_install');"
        "print(x[0].status, x[0].purpose_id)"
    )
    cp = subprocess.run([sys.executable, "-I", "-S", "-c", code], cwd=tmp_path,
                        env={}, text=True, capture_output=True, timeout=10)
    assert cp.returncode == 0, f"stdout={cp.stdout}\nstderr={cp.stderr}"
    assert cp.stdout.strip() == f"archived_achieved {purpose.id}"


def test_all_generation_slot_takeover_fences_old_owner_and_rejects_live_hijack(tmp_path):
    mod = _anchor()
    old = _coordinator(tmp_path, owner="old-owner")
    slot = old.reserve(operation="cutover", input_digest="batch-a")
    purpose = old.issue_purpose(slot, plan_node="task-1", expected_old="old")
    intent = old.persist_intent(slot, purpose_id=purpose.id)
    begun = old.begin(slot, purpose_id=purpose.id, intent_id=intent.id)
    contender = _coordinator(tmp_path, owner="new-owner")
    with pytest.raises(mod.LiveOwnerConflict):
        contender.takeover(slot, owner_dead=False, resources_quiescent=False)
    taken = contender.takeover(slot, owner_dead=True, resources_quiescent=True,
                               expected_owner_generation=begun.owner_generation)
    assert taken.owner_generation == begun.owner_generation + 1
    for mutation in (old.record_cas, old.finish, old.acknowledge):
        with pytest.raises(mod.StaleTransitionOwner):
            mutation(slot, owner_token=begun.owner_token)


def test_purpose_is_bound_against_cross_purpose_epoch_and_terminal_replay(tmp_path):
    mod = _anchor()
    c = _coordinator(tmp_path)
    a = c.reserve(operation="source", input_digest="batch-a")
    pa = c.issue_purpose(a, plan_node="task-1", expected_old="old")
    intent = c.persist_intent(a, purpose_id=pa.id)
    begun = c.begin(a, purpose_id=pa.id, intent_id=intent.id)
    c.record_cas(a, owner_token=begun.owner_token, old="old", new="new")
    c.finish(a, owner_token=begun.owner_token)
    observation = c.observe(a)
    c.acknowledge(a, observation_token=observation.token)
    c.archive(a)
    b = c.reserve(operation="controller", input_digest="batch-b")
    c.issue_purpose(b, plan_node="task-1", expected_old="old")
    with pytest.raises(mod.PurposeMismatch):
        c.persist_intent(b, purpose_id=pa.id)
    other_epoch = _coordinator(tmp_path, epoch="epoch-2", owner="owner-2")
    with pytest.raises(mod.EpochMismatch):
        other_epoch.resume(a)
    with pytest.raises(mod.PurposeMismatch):
        c.observe(b, terminal_token=pa.id)


def test_tofu_receipt_requires_exact_source_and_artifact_closure_and_fresh_challenge(tmp_path):
    mod = _anchor()
    source = {"anchor.py": b"canonical\n", "capsule.py": b"capsule\n"}
    artifacts = {"runtime/python.exe": b"python", "oci/driver.tar": b"oci"}
    proposal = mod.build_tofu_proposal(source_leaves=source, artifact_leaves=artifacts,
                                       policy="strict-utf8-parent-bom-crlf-to-lf-v1")
    response = f"TRUST SINGULARITY BOOTSTRAP {proposal.merkle_root} NONCE {proposal.nonce}"
    receipt = mod.install_tofu(proposal, response=response, external_root=tmp_path)
    assert receipt.source_root == proposal.source_root
    assert receipt.artifact_root == proposal.artifact_root
    assert receipt.merkle_root == proposal.merkle_root
    for changed in (
        {**source, "anchor.py": b"changed\n"},
        source,
    ):
        bad_artifacts = artifacts if changed is not source else {**artifacts, "oci/driver.tar": b"changed"}
        drift = mod.build_tofu_proposal(source_leaves=changed, artifact_leaves=bad_artifacts,
                                        policy="strict-utf8-parent-bom-crlf-to-lf-v1")
        with pytest.raises(mod.TofuApprovalRefused):
            mod.install_tofu(drift, response=response, external_root=tmp_path / "other")
    with pytest.raises(mod.TofuApprovalRefused):
        mod.install_tofu(proposal, response=response, external_root=tmp_path / "replay")


def test_request_client_roundtrips_canonical_base64url_and_enforces_both_caps():
    mod = importlib.import_module("bootstrap.galaxy_launcher.capsule")
    payload = {"path": 'C:\\quoted\\"café\\x', "records": ["a\\b", "組合"]}
    encoded = mod.encode_path_manifest(payload)
    assert "=" not in encoded
    assert mod.decode_path_manifest(encoded) == payload
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False).encode("utf-8")
    assert mod.decode_path_manifest_bytes(encoded) == canonical
    forbidden = encoded.replace("-", "+") if "-" in encoded else "+" + encoded[1:]
    for invalid in (encoded + "=", forbidden, "***"):
        with pytest.raises(mod.RequestEnvelopeRefused):
            mod.decode_path_manifest(invalid)
    with pytest.raises(mod.RequestEnvelopeRefused):
        mod.encode_path_manifest({"x": "a" * 4097})
    with pytest.raises(mod.RequestEnvelopeRefused):
        mod.decode_path_manifest("A" * 8193)


def test_response_loss_and_parent_death_are_independently_recoverable(tmp_path):
    c = _coordinator(tmp_path)
    slot = c.reserve(operation="source", input_digest="batch")
    purpose = c.issue_purpose(slot, plan_node="task-1", expected_old="old",
                              lose_response_after_persist=True)
    assert purpose is None
    reread = c.resolve_purpose(slot)
    assert reread.input_digest == "batch"
    death_root = tmp_path / "independent-parent-death-store"
    root = __import__('pathlib').Path(__file__).resolve().parents[2]
    code = (
        f"import os,sys;sys.path.insert(0,r'{root}');"
        "from bootstrap.galaxy_launcher.anchor import DurableTransitionCoordinator as C;"
        f"c=C(r'{death_root}',epoch='epoch-1',owner_id='dying-parent');"
        "s=c.reserve(operation='parent-death',input_digest='death-batch');"
        "c.issue_purpose(s,plan_node='task-1',expected_old='old',after_persist_hook=lambda:os._exit(91))"
    )
    dead = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env={},
                          text=True, capture_output=True, timeout=10)
    assert dead.returncode == 91, f"stdout={dead.stdout}\nstderr={dead.stderr}"
    fresh = _coordinator(death_root, owner="fresh")
    recovered = fresh.lookup_all_generations(operation="parent-death")
    assert len(recovered) == 1 and recovered[0].input_digest == "death-batch"


@pytest.mark.parametrize("phase", ["advance_old_to_new", "reconcile", "release"])
@pytest.mark.parametrize("edge", ["before_persist", "after_persist"])
def test_advance_reconcile_release_failpoints_are_restart_safe(tmp_path, phase, edge):
    mod = _anchor()
    c = _coordinator(tmp_path)
    slot, _, _ = _begin_transition(c, operation="controller", input_digest="batch")
    with pytest.raises(mod.InjectedTransitionCrash):
        c.advance(slot, phase, failpoint=f"{edge}:{phase}")
    recovered = _coordinator(tmp_path, owner="recovery").recover_all_generations()[0]
    assert recovered.phase in mod.RECOVERABLE_PHASES


def test_liveness_unknown_refuses_takeover_and_global_mutex_spans_operations_and_generations(tmp_path):
    mod = _anchor()
    owner = _coordinator(tmp_path, epoch="e1", owner="owner")
    slot, _, _ = _begin_transition(owner, operation="cutover", input_digest="a")
    contender = _coordinator(tmp_path, epoch="e2", owner="contender")
    with pytest.raises(mod.LivenessUnknown):
        contender.takeover(slot, owner_dead=None, resources_quiescent=None)
    for operation in ("source", "controller", "cutover"):
        with pytest.raises(mod.GlobalTransitionMutexHeld):
            contender.reserve(operation=operation, input_digest=operation)


@pytest.mark.parametrize("mutation", [
    "manifest", "normalization", "proposal", "verification", "reconcile",
    "release", "observe", "archive",
])
def test_stale_owner_is_rejected_at_every_mutation_boundary(tmp_path, mutation):
    mod = _anchor()
    old = _coordinator(tmp_path, owner="old")
    slot, _, _ = _begin_transition(old, operation="source", input_digest="batch")
    token = old.owner_token(slot)
    _coordinator(tmp_path, owner="new").takeover(
        slot, owner_dead=True, resources_quiescent=True,
        expected_owner_generation=token.owner_generation)
    with pytest.raises(mod.StaleTransitionOwner):
        old.mutate(slot, mutation=mutation, owner_token=token)


def test_purpose_handoff_retry_reviewed_restart_and_archive_ambiguity(tmp_path):
    mod = _anchor()
    c = _coordinator(tmp_path)
    first = _complete_transition(c, operation="source", input_digest="a")
    same = c.issue_or_return_purpose(operation="source", input_digest="a")
    assert same.id == first.purpose_id
    next_purpose = c.issue_or_return_purpose(operation="controller", input_digest="b",
                                             predecessor_purpose=first.purpose_id)
    assert next_purpose.predecessor_id == first.purpose_id
    restarted = c.reviewed_wave_restart(first.purpose_id, new_epoch="epoch-2")
    assert restarted.epoch == "epoch-2" and restarted.id != first.purpose_id
    _duplicate_persisted_record(tmp_path, first.purpose_id,
                                name="ambiguous-archive.json")
    with pytest.raises(mod.AmbiguousArchivedPurpose):
        c.lookup_purpose(first.purpose_id)


def test_stale_observation_ack_loss_and_terminal_inactive_discord_truth(tmp_path):
    mod = _anchor()
    c = _coordinator(tmp_path)
    terminal = _complete_transition(c, operation="cutover", input_digest="a")
    observation = c.observe(terminal.slot_id)
    _complete_transition(c, operation="cutover", input_digest="a-next")
    with pytest.raises(mod.StaleObservation):
        c.acknowledge(terminal.slot_id, observation_token=observation.token)
    current = c.observe(terminal.slot_id)
    assert c.acknowledge(terminal.slot_id, observation_token=current.token,
                         lose_response_after_persist=True) is None
    recovered = _coordinator(tmp_path, owner="fresh").lookup_all_generations()[0]
    assert recovered.acknowledged
    assert not recovered.production_active and not recovered.discord_enabled


def test_task5_fresh_shell_settles_before_dirty_or_report_gate_and_batches_are_content_addressed(tmp_path):
    c = _coordinator(tmp_path)
    old = _complete_transition(c, operation="task5", input_digest="vanished-batch")
    result = c.task5_fresh_shell(
        observe_slots=lambda: "settled",
        inspect_dirty=lambda: (_ for _ in ()).throw(AssertionError("dirty gate called")),
        inspect_report=lambda: (_ for _ in ()).throw(AssertionError("report gate called")),
    )
    assert result.achieved_purpose_id == old.purpose_id
    same = c.task5_resolve_batch("vanished-batch")
    new = c.task5_resolve_batch("new-batch")
    assert same.purpose_id == old.purpose_id and new.purpose_id != old.purpose_id


@pytest.mark.parametrize("failpoint", [
    "after_invocation_persisted_before_purpose", "after_purpose_before_intent",
    "after_intent_before_begin",
])
def test_task5_entry_failpoints_recover_same_invocation_purpose_chain(tmp_path, failpoint):
    mod = _anchor()
    c = _coordinator(tmp_path)
    with pytest.raises(mod.InjectedTransitionCrash):
        c.task5_invoke(input_digest="batch-a", failpoint=failpoint)
    fresh = _coordinator(tmp_path, owner="fresh")
    recovered = fresh.task5_fresh_shell(input_digest="batch-a")
    assert recovered.input_digest == "batch-a"
    assert recovered.status in {"clear_retryable", "intent_persisted", "begun"}
    assert fresh.task5_fresh_shell(input_digest="batch-a").invocation_id == recovered.invocation_id


def test_final_evidence_and_tracked_report_recover_before_untracked_report_gate(tmp_path):
    c = _coordinator(tmp_path)
    terminal = _complete_transition(c, operation="final_evidence",
                                    input_digest="report-batch")
    result = c.task5_fresh_shell(
        inspect_sole_untracked_report=lambda: (_ for _ in ()).throw(
            AssertionError("untracked report gate called")))
    assert result.achieved_purpose_id == terminal.purpose_id


def test_invocation_only_and_clear_retryable_inputs_reuse_exact_input_but_new_batch_differs(tmp_path):
    c = _coordinator(tmp_path)
    invocation = c.task5_invoke(input_digest="same", stop_after="invocation")
    same = _coordinator(tmp_path, owner="fresh").task5_fresh_shell(input_digest="same")
    assert same.invocation_id == invocation.id
    retryable = c.task5_invoke(input_digest="retry", disposition="clear_retryable")
    assert c.task5_fresh_shell(input_digest="retry").invocation_id == retryable.id
    assert c.task5_fresh_shell(input_digest="new").invocation_id not in {invocation.id, retryable.id}


def test_normalization_receipt_binds_raw_snapshot_policy_and_canonical_records(tmp_path):
    mod = _anchor()
    c = _coordinator(tmp_path)
    raw = {"a.txt": b"a\r\n", "b.bin": b"\x00\xff"}
    receipt = c.normalize_task5_batch(raw_snapshot=raw,
        policy_digest="strict-utf8-parent-bom-crlf-to-lf-v1")
    assert receipt.raw_snapshot_digest == mod.digest_raw_snapshot(raw)
    assert receipt.policy_digest == "strict-utf8-parent-bom-crlf-to-lf-v1"
    assert receipt.canonical_records["a.txt"].bytes == b"a\n"
    assert receipt.canonical_records["b.bin"].bytes == b"\x00\xff"


def test_task5_orphan_ambiguity_and_adversarial_edit_refuse_without_sweeping(tmp_path):
    mod = _anchor()
    c = _coordinator(tmp_path)
    orphan_root = tmp_path / "task5" / "orphan-results"
    orphan_root.mkdir(parents=True)
    for name in ("a", "b"):
        (orphan_root / f"{name}.json").write_text(
            json.dumps({"schema": 1, "result_id": name, "invocation_id": None}),
            encoding="utf-8")
    with pytest.raises(mod.AmbiguousTask5Recovery):
        c.task5_fresh_shell()
    reservation = c.task5_reserve("batch-a")
    _replace_persisted_text(tmp_path, "batch-a", "batch-b")
    with pytest.raises(mod.Task5InputDrift):
        c.task5_begin(reservation)


@pytest.mark.parametrize("helper", [
    "cancel_source", "cancel_controller", "cancel_cutover",
    "cancel_correction", "cancel_final_evidence", "cancel_activation",
])
def test_all_six_cancellation_helpers_require_authoritative_no_begin(tmp_path, helper):
    mod = _anchor()
    c = _coordinator(tmp_path)
    untouched = c.task5_reserve(helper)
    assert getattr(c, helper)(untouched, authoritative_no_begin=True).cancelled
    begun = c.task5_reserve(helper + "-begun")
    c.task5_mark_begin(begun)
    with pytest.raises(mod.BegunReservationCannotCancel):
        getattr(c, helper)(begun, authoritative_no_begin=True)


def test_real_ps51_request_client_rejects_noncanonical_and_roundtrips_near_caps(tmp_path):
    import base64
    import shutil
    powershell = shutil.which("powershell.exe")
    assert powershell
    client = __import__("pathlib").Path(__file__).resolve().parents[2] / "bootstrap/galaxy_launcher/singularity_admin_client.ps1"
    combining_path = 'C:\\q\\"cafe\u0301\\x'
    base = {"path": combining_path, "records": [""]}
    overhead = len(json.dumps(base, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":")).encode())
    base["records"][0] = "x" * (4090 - overhead)
    payload = json.dumps(base, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode()
    assert 4050 <= len(payload) <= 4096
    payload_b64url = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    request = {
        "operation": "append-path-manifest",
        "payload_base64url": payload_b64url,
        "request_id": "r" * 500,
    }
    request_bytes = json.dumps(request, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":")).encode()
    encoded = base64.urlsafe_b64encode(request_bytes).decode().rstrip("=")
    assert "=" not in encoded
    assert 8000 <= len(encoded) <= 8192
    accepted = subprocess.run([powershell, "-NoLogo", "-NoProfile", "-NonInteractive",
        "-File", str(client), "-SelfTestRequestEnvelope", encoded],
        text=True, capture_output=True, timeout=30)
    assert accepted.returncode == 0, f"stdout={accepted.stdout}\nstderr={accepted.stderr}"
    roundtrip = json.loads(accepted.stdout)
    assert roundtrip["canonical_request_base64url"] == encoded
    assert base64.urlsafe_b64decode(roundtrip["payload_base64url"] + "==") == payload
    forbidden = encoded.replace("-", "+") if "-" in encoded else "+" + encoded[1:]
    attacks = [encoded + "=", forbidden, "AB",
               base64.b64encode(b"\xff").decode(),
               "A" * 8193]
    for attack in attacks:
        cp = subprocess.run([powershell, "-NoLogo", "-NoProfile", "-NonInteractive",
            "-File", str(client), "-SelfTestRequestEnvelope", attack], text=True,
            capture_output=True, timeout=30)
        assert cp.returncode != 0, f"attack unexpectedly accepted: {attack!r}\nstdout={cp.stdout}"
