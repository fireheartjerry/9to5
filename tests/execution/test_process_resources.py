"""Kernel-owned process creation is journaled before executable release."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from platform_core.execution import process_resources as process_resources_module
from platform_core.execution.process_resources import (
    ProcessLaunchRefused,
    RegisteredProcessLauncher,
    RegisteredProcessManager,
    buildInstalledRegisteredProcessManager,
    planRegisteredProcessResource,
)
from platform_core.runtime.attempt_journal import (
    AttemptJournal,
    AttemptPhase,
    AttemptRecord,
    IncompleteResourceSet,
    JournalCorruption,
    MissingResourceSet,
)
from platform_core.runtime.candidate import (
    CloneLease,
    LandingAuthorityIssuer,
    ProcessResourceState,
    ResourceRole,
    RunnerKind,
    RuntimeResourceLease,
    _buildDiagnosticLandingAuthorityIssuer,
    processStartToken,
)


def _record(tmp_path: Path) -> AttemptRecord:
    now = datetime.now(timezone.utc).isoformat()
    return AttemptRecord(
        transaction_id="tx-process-001",
        task_id="task-001",
        subtask_id="subtask-001",
        attempt_id="attempt-001",
        repository_id="a" * 64,
        canonical_root=str(tmp_path / "canonical"),
        canonical_ref="refs/heads/main",
        base_revision="a" * 40,
        candidate_kind="clone",
        clone_lease_id="clone-001",
        clone_path=str(tmp_path / "clone"),
        ownership_nonce="b" * 64,
        spec_digest="c" * 64,
        policy_digest="d" * 64,
        canonical_metadata_attestation_digest="e" * 64,
        object_format="sha1",
        oid_length=40,
        ref_backend="files",
        candidate_branch="refs/heads/9to5/candidates/tx-process-001",
        checkpoint_message_digest="f" * 64,
        proposal_message_digest="1" * 64,
        commit_timestamp_seed=now,
        runner_kind="local",
        candidate_git_dir=str(tmp_path / "clone" / ".git"),
        canonical_git_common_dir=str(tmp_path / "canonical" / ".git"),
        source_manifest_digest="2" * 64,
        source_object_closure_digest="3" * 64,
        source_snapshot_digest="4" * 64,
        source_parser_receipt_id="5" * 64,
        source_payload_root=str(tmp_path / "payload"),
        created_at=now,
        updated_at=now,
    )


def _environment() -> dict[str, str]:
    if os.name == "nt":
        return {
            "SystemRoot": os.environ["SystemRoot"],
            "WINDIR": os.environ.get("WINDIR", os.environ["SystemRoot"]),
        }
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}


def _local_closure_for_driver(
    driver: RuntimeResourceLease,
) -> tuple[RuntimeResourceLease, ...]:
    watchdog = replace(
        driver,
        resource_id="watchdog-001",
        role=ResourceRole.AUTHORITY_WATCHDOG,
        depends_on=(),
    )
    driver = replace(
        driver,
        depends_on=("authority_watchdog:watchdog-001",),
    )
    parser = replace(
        driver,
        resource_id="parser-001",
        role=ResourceRole.CANDIDATE_PARSER,
        backend="docker",
        image_digest="7" * 64,
        depends_on=(
            "authority_watchdog:watchdog-001",
            f"model_driver:{driver.resource_id}",
        ),
    )
    verifier = replace(
        driver,
        resource_id="verifier-001",
        role=ResourceRole.VERIFIER,
        backend="docker",
        image_digest="8" * 64,
        depends_on=(
            "authority_watchdog:watchdog-001",
            "candidate_parser:parser-001",
        ),
    )
    return watchdog, driver, parser, verifier


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
                for resource in sorted(
                    resources,
                    key=lambda item: f"{item.role.value}:{item.resource_id}",
                )
            ],
            "runner_kind": record.runner_kind,
            "schema": "galaxy.runtime-resource-manifest/v1",
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return replace(
        record,
        runtime_resource_manifest_json=raw,
        runtime_resource_manifest_digest=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    )


def _planned_driver(
    record: AttemptRecord,
    *,
    argv: list[str],
    cwd: Path,
    environment: dict[str, str],
    security: str,
    resource_id: str = "model-driver-managed",
) -> RuntimeResourceLease:
    return planRegisteredProcessResource(
        run_id="run-001",
        transaction_id=record.transaction_id,
        controller_scope_id="controller-001",
        resource_id=resource_id,
        role=ResourceRole.MODEL_DRIVER,
        backend="local",
        ownership_nonce=record.ownership_nonce,
        argv=argv,
        cwd=cwd,
        environment=environment,
        creationflags=0,
        security_profile_digest=security,
        registered_at=record.created_at,
    )


def _admit_local_closure(
    journal: AttemptJournal,
    record: AttemptRecord,
    driver: RuntimeResourceLease,
    *,
    enter_running: bool = True,
) -> tuple[AttemptRecord, tuple[RuntimeResourceLease, ...], RuntimeResourceLease]:
    closure = _local_closure_for_driver(driver)
    admitted = journal.create(_with_runtime_manifest(record, closure))
    registered = journal.register_resources(admitted.transaction_id, closure)
    identities = tuple(
        f"{resource.role.value}:{resource.resource_id}" for resource in registered
    )
    if enter_running:
        admitted = journal.transition(
            admitted.transaction_id,
            AttemptPhase.RUNNING,
            resource_lease_ids=identities,
        )
    durable_driver = next(
        resource
        for resource in registered
        if resource.role is ResourceRole.MODEL_DRIVER
    )
    return admitted, registered, durable_driver


def _lease(tmp_path: Path) -> CloneLease:
    canonical_git = tmp_path / "canonical" / ".git"
    canonical_git.mkdir(parents=True)
    checkout = tmp_path / "clone"
    git_dir = checkout / ".git"
    (git_dir / "objects" / "info").mkdir(parents=True)
    candidate_ref = (
        git_dir / "refs" / "heads" / "9to5" / "candidates" / "tx-process-001"
    )
    candidate_ref.parent.mkdir(parents=True)
    (git_dir / "config").write_text(
        "[core]\n\trepositoryformatversion = 0\n\tbare = false\n",
        encoding="utf-8",
    )
    (git_dir / "HEAD").write_bytes(
        b"ref: refs/heads/9to5/candidates/tx-process-001\n"
    )
    candidate_ref.write_bytes(("a" * 40 + "\n").encode("ascii"))
    (git_dir / "shallow").write_bytes(("a" * 40 + "\n").encode("ascii"))
    return CloneLease(
        transaction_id="tx-process-001",
        task_id="task-001",
        subtask_id="subtask-001",
        attempt_id="attempt-001",
        checkout_path=str(checkout),
        expected_base_revision="a" * 40,
        runner_kind=RunnerKind.LOCAL,
        candidate_branch="refs/heads/9to5/candidates/tx-process-001",
        repository_id="a" * 64,
        ownership_nonce="b" * 64,
        git_dir=str(git_dir),
        git_common_dir=str(git_dir),
        canonical_git_common_dir=str(canonical_git),
        closure_manifest_digest="3" * 64,
        shallow_root_revision="a" * 40,
        hardlink_count_verified=True,
        alternates_absent=True,
        remote_absent=True,
        linked_worktree_pointer_absent=True,
        registered_at=datetime.now(timezone.utc).isoformat(),
        runtime_token=object(),
    )


def _manager(
    journal: AttemptJournal,
    monkeypatch: pytest.MonkeyPatch,
    *,
    security: str,
) -> RegisteredProcessManager:
    capability = object()
    issuer = _buildDiagnosticLandingAuthorityIssuer(
        run_id="run-001",
        controller_generation=1,
        watchdog_generation=1,
        process_capability=capability,
        child_pid=os.getpid(),
    )
    monkeypatch.setattr(
        LandingAuthorityIssuer,
        "isInstalledAuthority",
        lambda self: self is issuer,
    )
    admission = issuer.issueRunAdmission(
        process_capability=capability,
        deadline=datetime.now(timezone.utc) + timedelta(minutes=1),
    )
    return buildInstalledRegisteredProcessManager(
        journal=journal,
        controller_scope_id="controller-001",
        security_profile_digest=security,
        landing_authority_issuer=issuer,
        run_admission=admission,
    )


def test_registered_process_plan_requires_exact_durable_timestamp(
    tmp_path: Path,
) -> None:
    record = _record(tmp_path)
    arguments: dict[str, object] = {
        "run_id": "run-001",
        "transaction_id": record.transaction_id,
        "controller_scope_id": "controller-001",
        "resource_id": "driver-001",
        "role": ResourceRole.MODEL_DRIVER,
        "backend": "local",
        "ownership_nonce": record.ownership_nonce,
        "argv": (sys.executable, "-I", "-c", "print('never launched')"),
        "cwd": tmp_path,
        "environment": _environment(),
        "creationflags": 0,
        "security_profile_digest": "6" * 64,
    }

    with pytest.raises(TypeError, match="registered_at"):
        planRegisteredProcessResource(**arguments)
    with pytest.raises(TypeError, match="registered_at"):
        planRegisteredProcessResource(**arguments, registered_at=object())
    for invalid in (
        "",
        "2026-07-20T10:00:00",
        "2026-07-20T10:00:00Z",
        "2026-07-20 10:00:00+00:00",
    ):
        with pytest.raises(ValueError, match="registered_at"):
            planRegisteredProcessResource(**arguments, registered_at=invalid)

    registered_at = "2026-07-20T10:00:00.123456+05:30"
    resource = planRegisteredProcessResource(
        **arguments,
        registered_at=registered_at,
    )

    assert resource.created_at == registered_at
    assert resource.updated_at == registered_at


def test_registered_process_is_created_blocked_then_journaled_and_collected(
    tmp_path: Path,
) -> None:
    journal = AttemptJournal(tmp_path / "journal")
    provisional = _record(tmp_path)
    argv = [
        sys.executable,
        "-I",
        "-c",
        "import sys; data=sys.stdin.read(); print('child:'+data, end='')",
    ]
    environment = _environment()
    security = "6" * 64
    resource = planRegisteredProcessResource(
        run_id="run-001",
        transaction_id=provisional.transaction_id,
        controller_scope_id="controller-001",
        resource_id="driver-001",
        role=ResourceRole.MODEL_DRIVER,
        backend="local",
        ownership_nonce=provisional.ownership_nonce,
        argv=argv,
        cwd=tmp_path,
        environment=environment,
        creationflags=0,
        security_profile_digest=security,
        registered_at=provisional.created_at,
    )
    record, _registered, resource = _admit_local_closure(
        journal,
        provisional,
        resource,
    )
    launcher = RegisteredProcessLauncher(
        journal=journal,
        resource=resource,
        security_profile_digest=security,
    )

    process = launcher(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="strict",
        cwd=str(tmp_path),
        creationflags=0,
        env=environment,
        start_new_session=(os.name != "nt"),
    )
    out, err = process.communicate(input="ready", timeout=20)

    assert process.returncode == 0
    assert out == "child:ready"
    assert err == ""
    observed = next(
        item
        for item in journal.load_resources(record.transaction_id)
        if item.role is ResourceRole.MODEL_DRIVER
    )
    assert observed.state is ProcessResourceState.COLLECTED
    assert observed.pid == process.pid
    assert observed.process_start_token
    assert observed.process_group_id > 0


def test_release_never_occurs_when_created_identity_cannot_be_persisted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    journal = AttemptJournal(tmp_path / "journal")
    provisional = _record(tmp_path)
    argv = [sys.executable, "-I", "-c", "print('must-not-run')"]
    environment = _environment()
    security = "6" * 64
    resource = planRegisteredProcessResource(
        run_id="run-001",
        transaction_id=provisional.transaction_id,
        controller_scope_id="controller-001",
        resource_id="driver-001",
        role=ResourceRole.MODEL_DRIVER,
        backend="local",
        ownership_nonce=provisional.ownership_nonce,
        argv=argv,
        cwd=tmp_path,
        environment=environment,
        creationflags=0,
        security_profile_digest=security,
        registered_at=provisional.created_at,
    )
    record, _registered, resource = _admit_local_closure(
        journal,
        provisional,
        resource,
    )
    real_transition = journal.transition_resource

    def refuse_created(transaction_id, resource_id, state, **changes):
        if state is ProcessResourceState.CREATED:
            raise OSError("injected journal loss")
        return real_transition(transaction_id, resource_id, state, **changes)

    monkeypatch.setattr(journal, "transition_resource", refuse_created)
    launcher = RegisteredProcessLauncher(
        journal=journal,
        resource=resource,
        security_profile_digest=security,
    )

    try:
        launcher(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="strict",
            cwd=str(tmp_path),
            creationflags=0,
            env=environment,
            start_new_session=(os.name != "nt"),
        )
    except OSError as exc:
        assert "journal loss" in str(exc)
    else:
        raise AssertionError("unpersisted process identity was released")

    observed = next(
        item
        for item in journal.load_resources(record.transaction_id)
        if item.role is ResourceRole.MODEL_DRIVER
    )
    assert observed.state is ProcessResourceState.REGISTERED


def test_manager_consumes_preregistered_driver_from_full_admission_closure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = AttemptJournal(tmp_path / "journal")
    provisional = _record(tmp_path)
    security = "6" * 64
    argv = [sys.executable, "-I", "-c", "print('managed', end='')"]
    environment = _environment()
    driver = _planned_driver(
        provisional,
        argv=argv,
        cwd=tmp_path,
        environment=environment,
        security=security,
    )
    closure = _local_closure_for_driver(driver)
    record = journal.create(_with_runtime_manifest(provisional, closure))
    registered = journal.register_resources(record.transaction_id, closure)
    lease = _lease(tmp_path)
    manager = _manager(journal, monkeypatch, security=security)
    register_calls: list[object] = []

    def forbidden_register(*args, **kwargs):
        register_calls.append((args, kwargs))
        raise AssertionError("manager must not create or close a resource manifest")

    monkeypatch.setattr(journal, "register_resources", forbidden_register)
    launcher = manager.launcherFor(
        lease,
        argv=argv,
        cwd=tmp_path,
        environment=environment,
        creationflags=0,
        security_profile_digest=security,
    )

    durable_driver = next(
        resource
        for resource in registered
        if resource.role is ResourceRole.MODEL_DRIVER
    )
    assert launcher.resource == durable_driver
    assert register_calls == []
    assert journal.load(record.transaction_id).resource_lease_ids == tuple(
        f"{resource.role.value}:{resource.resource_id}" for resource in registered
    )


def test_manager_refuses_manifestless_singleton_without_registering_or_launching(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = AttemptJournal(tmp_path / "journal")
    journal.create(_record(tmp_path))
    lease = _lease(tmp_path)
    security = "6" * 64
    manager = _manager(journal, monkeypatch, security=security)
    calls: list[str] = []
    monkeypatch.setattr(
        journal,
        "register_resources",
        lambda *_args, **_kwargs: calls.append("register"),
    )
    monkeypatch.setattr(
        process_resources_module.subprocess,
        "Popen",
        lambda *_args, **_kwargs: calls.append("popen"),
    )

    with pytest.raises(ProcessLaunchRefused, match="manifest|closure"):
        manager.launcherFor(
            lease,
            argv=[sys.executable, "-I", "-c", "print('must-not-run')"],
            cwd=tmp_path,
            environment=_environment(),
            creationflags=0,
            security_profile_digest=security,
        )

    assert calls == []


def test_live_run_manager_launches_exact_preregistered_clone_driver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = AttemptJournal(tmp_path / "journal")
    provisional = _record(tmp_path)
    security = "6" * 64
    argv = [sys.executable, "-I", "-c", "print('managed', end='')"]
    environment = _environment()
    closure = _local_closure_for_driver(
        _planned_driver(
            provisional,
            argv=argv,
            cwd=tmp_path,
            environment=environment,
            security=security,
        )
    )
    record = journal.create(_with_runtime_manifest(provisional, closure))
    journal.register_resources(record.transaction_id, closure)
    lease = _lease(tmp_path)
    manager = _manager(journal, monkeypatch, security=security)
    launcher = manager.launcherFor(
        lease,
        argv=argv,
        cwd=tmp_path,
        environment=environment,
        creationflags=0,
        security_profile_digest=security,
    )

    process = launcher(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="strict",
        cwd=str(tmp_path),
        creationflags=0,
        env=environment,
        start_new_session=(os.name != "nt"),
    )
    out, err = process.communicate(timeout=20)

    assert out == "managed"
    assert err == ""
    assert journal.load(lease.transaction_id).phase is AttemptPhase.RUNNING
    resource = next(
        item
        for item in journal.load_resources(lease.transaction_id)
        if item.role is ResourceRole.MODEL_DRIVER
    )
    assert resource.state is ProcessResourceState.COLLECTED
    assert resource.role is ResourceRole.MODEL_DRIVER

    with __import__("pytest").raises(
        ProcessLaunchRefused, match="installed run-admission composition"
    ):
        RegisteredProcessManager(
            journal=journal,
            controller_scope_id="controller-001",
            security_profile_digest=security,
            landing_authority_issuer=manager.landing_authority_issuer,
            run_admission=manager.run_admission,
        )


@pytest.mark.parametrize("adversarial", ["substituted", "extra"])
def test_manager_refuses_nonexact_durable_registration_before_running(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    adversarial: str,
) -> None:
    journal = AttemptJournal(tmp_path / "journal")
    provisional = _record(tmp_path)
    security = "6" * 64
    argv = [sys.executable, "-I", "-c", "print('must-not-run')"]
    environment = _environment()
    closure = _local_closure_for_driver(
        _planned_driver(
            provisional,
            argv=argv,
            cwd=tmp_path,
            environment=environment,
            security=security,
        )
    )
    record = journal.create(_with_runtime_manifest(provisional, closure))
    registered = journal.register_resources(record.transaction_id, closure)
    lease = _lease(tmp_path)
    manager = _manager(journal, monkeypatch, security=security)
    if adversarial == "substituted":
        observed = tuple(
            replace(resource, security_profile_digest="7" * 64)
            if resource.role is ResourceRole.MODEL_DRIVER
            else resource
            for resource in registered
        )
    else:
        observed = registered + (
            replace(
                registered[-1],
                resource_id="broker-extra",
                role=ResourceRole.BROKER,
            ),
        )

    monkeypatch.setattr(journal, "load_resources", lambda _transaction_id: observed)

    with pytest.raises(ProcessLaunchRefused, match="pre-registered|resource set"):
        manager.launcherFor(
            lease,
            argv=argv,
            cwd=tmp_path,
            environment=environment,
            creationflags=0,
            security_profile_digest=security,
        )

    assert journal.load(record.transaction_id).phase is AttemptPhase.LEASE_REGISTERED


@pytest.mark.parametrize(
    "cut",
    ["missing", "incomplete", "running_committed"],
)
def test_manager_restart_resumes_exact_durable_registration_cut(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cut: str,
) -> None:
    journal = AttemptJournal(tmp_path / "journal")
    provisional = _record(tmp_path)
    security = "6" * 64
    argv = [sys.executable, "-I", "-c", "print('never launched')"]
    environment = _environment()
    closure = _local_closure_for_driver(
        _planned_driver(
            provisional,
            argv=argv,
            cwd=tmp_path,
            environment=environment,
            security=security,
        )
    )
    record = journal.create(_with_runtime_manifest(provisional, closure))
    registered = journal.register_resources(record.transaction_id, closure)
    lease = _lease(tmp_path)
    manager = _manager(journal, monkeypatch, security=security)

    if cut in {"missing", "incomplete"}:
        failure: Exception = (
            MissingResourceSet("missing")
            if cut == "missing"
            else IncompleteResourceSet("incomplete")
        )
        with monkeypatch.context() as patch:
            patch.setattr(
                journal,
                "load_resources",
                lambda _transaction_id: (_ for _ in ()).throw(failure),
            )
            with pytest.raises(ProcessLaunchRefused, match=cut):
                manager.launcherFor(
                    lease,
                    argv=argv,
                    cwd=tmp_path,
                    environment=environment,
                    creationflags=0,
                    security_profile_digest=security,
                )
        assert journal.load(record.transaction_id).phase is AttemptPhase.LEASE_REGISTERED
    else:
        manager.launcherFor(
            lease,
            argv=argv,
            cwd=tmp_path,
            environment=environment,
            creationflags=0,
            security_profile_digest=security,
        )
        assert journal.load(record.transaction_id).phase is AttemptPhase.RUNNING

    restarted = _manager(journal, monkeypatch, security=security)
    with monkeypatch.context() as patch:
        patch.setattr(
            journal,
            "register_resources",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("restart cannot register resources")
            ),
        )
        launcher = restarted.launcherFor(
            lease,
            argv=argv,
            cwd=tmp_path,
            environment=environment,
            creationflags=0,
            security_profile_digest=security,
        )

    durable_driver = next(
        resource
        for resource in registered
        if resource.role is ResourceRole.MODEL_DRIVER
    )
    assert launcher.resource == durable_driver
    assert launcher.resource.state is ProcessResourceState.REGISTERED
    assert launcher.resource.created_at == record.created_at
    assert journal.load(record.transaction_id).phase is AttemptPhase.RUNNING


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (MissingResourceSet("missing"), "missing"),
        (IncompleteResourceSet("intent only"), "incomplete"),
        (JournalCorruption("bad completion"), "corrupt"),
    ],
)
def test_launcher_revalidates_closed_resource_set_before_any_popen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    message: str,
) -> None:
    journal = AttemptJournal(tmp_path / "journal")
    provisional = _record(tmp_path)
    argv = [sys.executable, "-I", "-c", "print('must-not-run')"]
    environment = _environment()
    security = "6" * 64
    resource = planRegisteredProcessResource(
        run_id="run-001",
        transaction_id=provisional.transaction_id,
        controller_scope_id="controller-001",
        resource_id="driver-001",
        role=ResourceRole.MODEL_DRIVER,
        backend="local",
        ownership_nonce=provisional.ownership_nonce,
        argv=argv,
        cwd=tmp_path,
        environment=environment,
        creationflags=0,
        security_profile_digest=security,
        registered_at=provisional.created_at,
    )
    record, _registered, resource = _admit_local_closure(
        journal,
        provisional,
        resource,
    )
    launcher = RegisteredProcessLauncher(
        journal=journal,
        resource=resource,
        security_profile_digest=security,
    )
    popen_calls: list[tuple[object, ...]] = []

    def forbidden_popen(*args, **kwargs):
        popen_calls.append((args, kwargs))
        raise AssertionError("Popen must not run")

    monkeypatch.setattr(journal, "load_resources", lambda _transaction_id: (_ for _ in ()).throw(failure))
    monkeypatch.setattr(process_resources_module.subprocess, "Popen", forbidden_popen)

    with pytest.raises(ProcessLaunchRefused, match=message):
        launcher(
            argv,
            cwd=str(tmp_path),
            creationflags=0,
            env=environment,
            start_new_session=(os.name != "nt"),
        )
    assert popen_calls == []


def test_creator_hard_death_cannot_leave_an_unregistered_child(
    tmp_path: Path,
) -> None:
    journal = AttemptJournal(tmp_path / "journal")
    provisional = _record(tmp_path)
    marker = tmp_path / "target-ran.txt"
    identity_path = tmp_path / "blocked-child-identity.json"
    argv = [
        sys.executable,
        "-I",
        "-c",
        (
            "from pathlib import Path; "
            f"Path({str(marker)!r}).write_text('escaped', encoding='utf-8')"
        ),
    ]
    environment = _environment()
    security = "6" * 64
    resource = planRegisteredProcessResource(
        run_id="run-001",
        transaction_id=provisional.transaction_id,
        controller_scope_id="controller-001",
        resource_id="driver-hard-death",
        role=ResourceRole.MODEL_DRIVER,
        backend="local",
        ownership_nonce=provisional.ownership_nonce,
        argv=argv,
        cwd=tmp_path,
        environment=environment,
        creationflags=0,
        security_profile_digest=security,
        registered_at=provisional.created_at,
    )
    record, _registered, resource = _admit_local_closure(
        journal,
        provisional,
        resource,
    )
    case = {
        "argv": argv,
        "creationflags": 0,
        "cwd": str(tmp_path),
        "environment": environment,
        "identity_path": str(identity_path),
        "journal_root": str(journal.root),
        "security_profile_digest": security,
        "transaction_id": record.transaction_id,
    }
    case_path = tmp_path / "case.json"
    case_path.write_text(
        json.dumps(case, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    worker = Path(__file__).with_name("process_resource_crash_worker.py")

    result = subprocess.run(
        [sys.executable, "-I", str(worker), str(case_path)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 88, result.stderr
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and processStartToken(identity["pid"]) is not None:
        time.sleep(0.02)
    assert processStartToken(identity["pid"]) is None
    assert not marker.exists()
    observed = next(
        item
        for item in journal.load_resources(record.transaction_id)
        if item.role is ResourceRole.MODEL_DRIVER
    )
    assert observed.state is ProcessResourceState.REGISTERED
