"""RED contracts for revocation-raced execution authority watchdogs."""

from __future__ import annotations

import importlib
import threading
from datetime import datetime, timedelta, timezone

import pytest


def _watchdog():
    return importlib.import_module("platform_core.execution.authority_watchdog")


def _issue(mod, watchdog, *, deadline: str = "2099-01-01T00:00:00+00:00"):
    return watchdog.issueExecutionLaunchAuthority(
        transaction_id="tx_watchdog",
        resource_id="driver_resource",
        clone_root="C:/isolated/clone",
        clone_ownership_nonce="clone_nonce",
        runner_kind="local",
        capability_receipt_id="cap_watchdog",
        capability_process_grant_nonce="process_grant",
        trust_receipt_id="trust_watchdog",
        trust_grant_nonce="trust_grant",
        issuer_generation=4,
        canonical_base="1" * 40,
        journal_phase="ready",
        deadline=deadline,
    )


def test_revocation_wins_before_os_start_release() -> None:
    mod = _watchdog()
    starts: list[str] = []
    watchdog = mod.AuthorityWatchdog(
        controller_generation=5,
        watchdog_generation=9,
        revocation_generation=2,
    )
    authority = watchdog.issueExecutionLaunchAuthority(
        transaction_id="tx_watchdog",
        resource_id="driver_resource",
        clone_root="C:/isolated/clone",
        clone_ownership_nonce="clone_nonce",
        runner_kind="local",
        capability_receipt_id="cap_watchdog",
        capability_process_grant_nonce="process_grant",
        trust_receipt_id="trust_watchdog",
        trust_grant_nonce="trust_grant",
        issuer_generation=4,
        canonical_base="1" * 40,
        journal_phase="ready",
        deadline="2099-01-01T00:00:00+00:00",
    )
    watchdog.revoke(3)

    with pytest.raises(mod.ExecutionLaunchRefused):
        watchdog.releaseStart(authority, lambda: starts.append("started"))

    assert starts == []


def test_serialized_or_copied_authority_is_not_accepted() -> None:
    mod = _watchdog()
    watchdog = mod.AuthorityWatchdog(
        controller_generation=5,
        watchdog_generation=9,
        revocation_generation=2,
    )
    with pytest.raises(mod.ExecutionLaunchRefused):
        watchdog.validateExecutionLaunchAuthority(
            {
                "transaction_id": "tx_watchdog",
                "resource_id": "driver_resource",
                "deadline": "2099-01-01T00:00:00+00:00",
            }
        )


def test_dataclass_copy_cannot_reuse_process_local_launch_capability() -> None:
    from dataclasses import replace

    mod = _watchdog()
    watchdog = mod.AuthorityWatchdog(
        controller_generation=5,
        watchdog_generation=9,
        revocation_generation=2,
    )
    authority = watchdog.issueExecutionLaunchAuthority(
        transaction_id="tx_watchdog",
        resource_id="driver_resource",
        clone_root="C:/isolated/clone",
        clone_ownership_nonce="clone_nonce",
        runner_kind="local",
        capability_receipt_id="cap_watchdog",
        capability_process_grant_nonce="process_grant",
        trust_receipt_id="trust_watchdog",
        trust_grant_nonce="trust_grant",
        issuer_generation=4,
        canonical_base="1" * 40,
        journal_phase="ready",
        deadline="2099-01-01T00:00:00+00:00",
    )

    with pytest.raises(mod.ExecutionLaunchRefused):
        watchdog.validateExecutionLaunchAuthority(replace(authority))


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("transaction_id", "tx_retargeted"),
        ("resource_id", "other_resource"),
        ("clone_root", "C:/attacker/clone"),
        ("clone_ownership_nonce", "other_clone_nonce"),
        ("runner_kind", "docker"),
        ("capability_receipt_id", "other_capability"),
        ("capability_process_grant_nonce", "other_process_grant"),
        ("trust_receipt_id", "other_trust"),
        ("trust_grant_nonce", "other_trust_grant"),
        ("issuer_generation", 5),
        ("canonical_base", "2" * 40),
        ("journal_phase", "committed"),
        ("controller_generation", 6),
        ("watchdog_generation", 10),
        ("revocation_generation", 3),
        ("deadline", "2100-01-01T00:00:00+00:00"),
        ("_issuer_identity", -1),
        ("_seal", object()),
    ),
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_exact_launch_authority_rejects_every_in_place_field_mutation(
    field: str,
    replacement: object,
) -> None:
    """Frozen dataclasses must not become mutable exact-object capabilities."""

    mod = _watchdog()
    watchdog = mod.AuthorityWatchdog(
        controller_generation=5,
        watchdog_generation=9,
        revocation_generation=2,
    )
    authority = watchdog.issueExecutionLaunchAuthority(
        transaction_id="tx_watchdog",
        resource_id="driver_resource",
        clone_root="C:/isolated/clone",
        clone_ownership_nonce="clone_nonce",
        runner_kind="local",
        capability_receipt_id="cap_watchdog",
        capability_process_grant_nonce="process_grant",
        trust_receipt_id="trust_watchdog",
        trust_grant_nonce="trust_grant",
        issuer_generation=4,
        canonical_base="1" * 40,
        journal_phase="ready",
        deadline="2099-01-01T00:00:00+00:00",
    )
    assert watchdog.validateExecutionLaunchAuthority(authority) is authority

    object.__setattr__(authority, field, replacement)

    with pytest.raises(mod.ExecutionLaunchRefused):
        watchdog.validateExecutionLaunchAuthority(authority)


def test_guarded_entry_derives_workdir_only_after_exact_authority_validation() -> None:
    mod = _watchdog()
    watchdog = mod.AuthorityWatchdog(
        controller_generation=5,
        watchdog_generation=9,
        revocation_generation=2,
    )
    authority = watchdog.issueExecutionLaunchAuthority(
        transaction_id="tx_watchdog",
        resource_id="driver_resource",
        clone_root="C:/isolated/clone",
        clone_ownership_nonce="clone_nonce",
        runner_kind="local",
        capability_receipt_id="cap_watchdog",
        capability_process_grant_nonce="process_grant",
        trust_receipt_id="trust_watchdog",
        trust_grant_nonce="trust_grant",
        issuer_generation=4,
        canonical_base="1" * 40,
        journal_phase="ready",
        deadline="2099-01-01T00:00:00+00:00",
    )

    validated, work_dir = mod.validateLaunchAuthority(
        watchdog=watchdog,
        authority=authority,
        caller_work_dir=None,
    )
    assert validated is authority
    assert work_dir == authority.clone_root

    with pytest.raises(mod.ExecutionLaunchRefused):
        mod.validateLaunchAuthority(
            watchdog=watchdog,
            authority=authority,
            caller_work_dir="C:/canonical",
        )


def test_bootstrap_epoch_caps_execution_deadline_and_launch_liveness() -> None:
    mod = _watchdog()
    now = [datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)]
    watchdog = mod.AuthorityWatchdog(
        controller_generation=5,
        watchdog_generation=9,
        revocation_generation=2,
        clock=lambda: now[0],
        resource_probe=lambda _resource_id: True,
        canonical_probe=lambda: "1" * 40,
        trust_probe=lambda _authority: True,
        capability_probe=lambda _authority: True,
        journal_probe=lambda _authority: True,
        bootstrap_outer_scope_digest="1" * 64,
        bootstrap_capsule_scope_digest="2" * 64,
        bootstrap_child_pid=1234,
        bootstrap_expires_at="2026-07-19T12:05:00+00:00",
        bootstrap_activation_generation=3,
        bootstrap_boot_generation=4,
    )
    request = {
        "transaction_id": "tx_bootstrap_watchdog",
        "resource_id": "driver_resource",
        "clone_root": "C:/isolated/clone",
        "clone_ownership_nonce": "clone_nonce",
        "runner_kind": "local",
        "capability_receipt_id": "cap_watchdog",
        "capability_process_grant_nonce": "process_grant",
        "trust_receipt_id": "trust_watchdog",
        "trust_grant_nonce": "trust_grant",
        "issuer_generation": 4,
        "canonical_base": "1" * 40,
        "journal_phase": "ready",
    }

    with pytest.raises(mod.ExecutionLaunchRefused, match="bootstrap|expiry|deadline"):
        watchdog.issueExecutionLaunchAuthority(
            **request,
            deadline="2026-07-19T12:06:00+00:00",
        )
    with pytest.raises(mod.ExecutionLaunchRefused, match="installed|bootstrap"):
        watchdog.advanceWatchdog(10)

    authority = watchdog.issueExecutionLaunchAuthority(
        **request,
        deadline="2026-07-19T12:04:00+00:00",
    )
    now[0] = datetime(2026, 7, 19, 12, 5, tzinfo=timezone.utc)
    with pytest.raises(mod.ExecutionLaunchRefused, match="bootstrap|expired"):
        watchdog.validateExecutionLaunchAuthority(authority)
    starts: list[str] = []
    with pytest.raises(mod.ExecutionLaunchRefused, match="bootstrap|expired"):
        watchdog.releaseStart(authority, lambda: starts.append("started"))
    assert starts == []

    now[0] = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
    with pytest.raises(mod.ExecutionLaunchRefused, match="watchdog|live|expired"):
        watchdog.validateExecutionLaunchAuthority(authority)


def test_backward_clock_observation_terminally_retires_watchdog() -> None:
    mod = _watchdog()
    initial = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
    observed = [initial]
    watchdog = mod.AuthorityWatchdog(
        controller_generation=5,
        watchdog_generation=9,
        revocation_generation=2,
        clock=lambda: observed[0],
    )
    authority = _issue(
        mod,
        watchdog,
        deadline="2026-07-19T12:05:00+00:00",
    )
    observed[0] = initial + timedelta(minutes=2)
    assert watchdog.validateExecutionLaunchAuthority(authority) is authority

    observed[0] = initial + timedelta(minutes=1)
    with pytest.raises(mod.ExecutionLaunchRefused, match="clock|backward|live"):
        watchdog.validateExecutionLaunchAuthority(authority)

    observed[0] = initial + timedelta(minutes=3)
    with pytest.raises(mod.ExecutionLaunchRefused, match="watchdog|live"):
        watchdog.validateExecutionLaunchAuthority(authority)


def test_release_start_is_idempotent_and_starts_exactly_once() -> None:
    mod = _watchdog()
    watchdog = mod.AuthorityWatchdog(
        controller_generation=5,
        watchdog_generation=9,
        revocation_generation=2,
    )
    authority = _issue(mod, watchdog)
    starts: list[object] = []
    outcome = object()

    def starter() -> object:
        starts.append(outcome)
        return outcome

    first = watchdog.releaseStart(authority, starter)
    second = watchdog.releaseStart(
        authority,
        lambda: pytest.fail("replayed launch called starter"),
    )

    assert first is outcome
    assert second is outcome
    assert starts == [outcome]


def test_concurrent_release_start_has_one_effect_and_one_shared_outcome() -> None:
    mod = _watchdog()
    watchdog = mod.AuthorityWatchdog(
        controller_generation=5,
        watchdog_generation=9,
        revocation_generation=2,
    )
    authority = _issue(mod, watchdog)
    entered = threading.Event()
    release = threading.Event()
    outcome = object()
    starts: list[str] = []
    results: list[object] = []
    errors: list[BaseException] = []

    def starter() -> object:
        starts.append("started")
        entered.set()
        assert release.wait(timeout=5)
        return outcome

    def invoke() -> None:
        try:
            results.append(watchdog.releaseStart(authority, starter))
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [threading.Thread(target=invoke) for _ in range(2)]
    threads[0].start()
    assert entered.wait(timeout=5)
    threads[1].start()
    release.set()
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    assert starts == ["started"]
    assert len(results) == 2
    assert all(result is outcome for result in results)


def test_ambiguous_starter_failure_is_terminal_and_never_released_again() -> None:
    mod = _watchdog()
    watchdog = mod.AuthorityWatchdog(
        controller_generation=5,
        watchdog_generation=9,
        revocation_generation=2,
    )
    authority = _issue(mod, watchdog)
    starts: list[str] = []

    def fail_after_release() -> None:
        starts.append("attempted")
        raise RuntimeError("provider response was lost")

    with pytest.raises(RuntimeError, match="response was lost"):
        watchdog.releaseStart(authority, fail_after_release)
    with pytest.raises(mod.ExecutionLaunchRefused, match="indeterminate|terminal"):
        watchdog.releaseStart(authority, fail_after_release)

    assert starts == ["attempted"]


@pytest.mark.parametrize(
    "probe_name",
    ("resource", "canonical", "trust", "capability", "journal"),
)
def test_validation_probes_require_exact_truth_not_truthiness(probe_name: str) -> None:
    mod = _watchdog()
    observed: dict[str, object] = {
        "resource": True,
        "canonical": "1" * 40,
        "trust": True,
        "capability": True,
        "journal": True,
    }
    watchdog = mod.AuthorityWatchdog(
        controller_generation=5,
        watchdog_generation=9,
        revocation_generation=2,
        resource_probe=lambda _resource_id: observed["resource"],
        canonical_probe=lambda: observed["canonical"],
        trust_probe=lambda _authority: observed["trust"],
        capability_probe=lambda _authority: observed["capability"],
        journal_probe=lambda _authority: observed["journal"],
    )
    authority = _issue(mod, watchdog)
    observed[probe_name] = 1

    with pytest.raises(mod.ExecutionLaunchRefused, match="probe|resource|canonical|trust|capability|journal"):
        watchdog.validateExecutionLaunchAuthority(authority)


def test_probe_exception_is_normalized_to_typed_refusal() -> None:
    mod = _watchdog()
    fail = [False]

    def resource_probe(_resource_id: str) -> bool:
        if fail[0]:
            raise OSError("provider disappeared")
        return True

    watchdog = mod.AuthorityWatchdog(
        controller_generation=5,
        watchdog_generation=9,
        revocation_generation=2,
        resource_probe=resource_probe,
    )
    authority = _issue(mod, watchdog)
    fail[0] = True

    with pytest.raises(mod.ExecutionLaunchRefused, match="probe|resource"):
        watchdog.validateExecutionLaunchAuthority(authority)


def test_issue_resource_probe_requires_exact_true_and_normalizes_failure() -> None:
    mod = _watchdog()
    truthy = mod.AuthorityWatchdog(
        controller_generation=5,
        watchdog_generation=9,
        revocation_generation=2,
        resource_probe=lambda _resource_id: 1,
    )
    with pytest.raises(mod.ExecutionLaunchRefused, match="probe|resource|exact"):
        _issue(mod, truthy)

    def explode(_resource_id: str) -> bool:
        raise OSError("resource registry unavailable")

    failing = mod.AuthorityWatchdog(
        controller_generation=5,
        watchdog_generation=9,
        revocation_generation=2,
        resource_probe=explode,
    )
    with pytest.raises(mod.ExecutionLaunchRefused, match="probe|resource"):
        _issue(mod, failing)


def test_watchdog_clock_cannot_be_retargeted_to_extend_launch_lifetime() -> None:
    mod = _watchdog()
    initial = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
    observed = [initial]
    watchdog = mod.AuthorityWatchdog(
        controller_generation=5,
        watchdog_generation=9,
        revocation_generation=2,
        clock=lambda: observed[0],
    )
    authority = _issue(
        mod,
        watchdog,
        deadline="2026-07-19T12:00:01+00:00",
    )
    observed[0] = initial + timedelta(seconds=2)
    object.__setattr__(watchdog, "_clock", lambda: initial)

    with pytest.raises(mod.ExecutionLaunchRefused, match="watchdog|scope|changed"):
        watchdog.validateExecutionLaunchAuthority(authority)


def test_watchdog_admission_probe_cannot_be_retargeted() -> None:
    mod = _watchdog()
    resource_live = [True]

    def resource_probe(_resource_id: str) -> bool:
        return resource_live[0]

    watchdog = mod.AuthorityWatchdog(
        controller_generation=5,
        watchdog_generation=9,
        revocation_generation=2,
        resource_probe=resource_probe,
    )
    authority = _issue(mod, watchdog)
    resource_live[0] = False
    object.__setattr__(watchdog, "_resource_probe", lambda _resource_id: True)

    with pytest.raises(mod.ExecutionLaunchRefused, match="watchdog|scope|changed"):
        watchdog.validateExecutionLaunchAuthority(authority)


def test_installed_watchdog_scope_cannot_be_extended_in_place() -> None:
    mod = _watchdog()
    observed = [datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)]
    watchdog = mod.AuthorityWatchdog(
        controller_generation=5,
        watchdog_generation=9,
        revocation_generation=2,
        clock=lambda: observed[0],
        resource_probe=lambda _resource_id: True,
        canonical_probe=lambda: "1" * 40,
        trust_probe=lambda _authority: True,
        capability_probe=lambda _authority: True,
        journal_probe=lambda _authority: True,
        bootstrap_outer_scope_digest="1" * 64,
        bootstrap_capsule_scope_digest="2" * 64,
        bootstrap_child_pid=1234,
        bootstrap_expires_at="2026-07-19T12:00:01+00:00",
        bootstrap_activation_generation=3,
        bootstrap_boot_generation=4,
    )
    observed[0] += timedelta(seconds=2)
    object.__setattr__(
        watchdog,
        "_bootstrap_expires_at",
        "2026-07-19T12:05:00+00:00",
    )

    with pytest.raises(mod.ExecutionLaunchRefused, match="watchdog|scope|changed"):
        _issue(
            mod,
            watchdog,
            deadline="2026-07-19T12:04:00+00:00",
        )


def test_issue_rechecks_deadline_after_resource_probe_before_publication() -> None:
    mod = _watchdog()
    now = [datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)]

    def resource_probe(_resource_id: str) -> bool:
        now[0] += timedelta(seconds=2)
        return True

    watchdog = mod.AuthorityWatchdog(
        controller_generation=5,
        watchdog_generation=9,
        revocation_generation=2,
        clock=lambda: now[0],
        resource_probe=resource_probe,
    )

    with pytest.raises(mod.ExecutionLaunchRefused, match="expired|deadline"):
        _issue(
            mod,
            watchdog,
            deadline="2026-07-19T12:00:01+00:00",
        )
    assert watchdog._issued == {}


def test_validation_rechecks_deadline_after_slow_probes_before_release() -> None:
    mod = _watchdog()
    now = [datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)]

    def trust_probe(_authority: object) -> bool:
        now[0] += timedelta(seconds=2)
        return True

    watchdog = mod.AuthorityWatchdog(
        controller_generation=5,
        watchdog_generation=9,
        revocation_generation=2,
        clock=lambda: now[0],
        resource_probe=lambda _resource_id: True,
        canonical_probe=lambda: "1" * 40,
        trust_probe=trust_probe,
        capability_probe=lambda _authority: True,
        journal_probe=lambda _authority: True,
    )
    authority = _issue(
        mod,
        watchdog,
        deadline="2026-07-19T12:00:01+00:00",
    )
    starts: list[str] = []

    with pytest.raises(mod.ExecutionLaunchRefused, match="expired|deadline"):
        watchdog.releaseStart(authority, lambda: starts.append("started"))

    assert starts == []
