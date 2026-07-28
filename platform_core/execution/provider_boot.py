"""Exact capability admission for credentialed provider safe boot.

RUN/TEST: python -m pytest tests/execution/test_provider_safe_boot.py
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, TypeVar

from platform_core.execution.authority_watchdog import (
    AuthorityWatchdog,
    ExecutionLaunchAuthority,
    ExecutionLaunchRefused,
)

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}$")
_T = TypeVar("_T")


class ProviderBootUnavailable(RuntimeError):
    """The exact provider containment canary does not authorize this launch."""


def _digest(value: str, name: str) -> None:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise ProviderBootUnavailable(f"{name} is invalid")


def _identifier(value: str, name: str) -> None:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ProviderBootUnavailable(f"{name} is invalid")


def _time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ProviderBootUnavailable("capability expiry is invalid") from exc
    if parsed.tzinfo is None:
        raise ProviderBootUnavailable("capability expiry is not absolute")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class ProviderBootPlan:
    provider: str
    transaction_id: str
    launch_plan_digest: str
    image_digest: str
    broker_policy_digest: str
    credential_policy_digest: str
    deadline: str

    def __post_init__(self) -> None:
        if self.provider not in {"claude", "codex"}:
            raise ProviderBootUnavailable("provider is unavailable")
        _identifier(self.transaction_id, "transaction_id")
        for value, name in (
            (self.launch_plan_digest, "launch_plan_digest"),
            (self.image_digest, "image_digest"),
            (self.broker_policy_digest, "broker_policy_digest"),
            (self.credential_policy_digest, "credential_policy_digest"),
        ):
            _digest(value, name)
        _time(self.deadline)


@dataclass(frozen=True, slots=True)
class CapabilityEnforcementReceipt:
    receipt_id: str
    provider: str
    launch_plan_digest: str
    image_digest: str
    broker_policy_digest: str
    credential_policy_digest: str
    host_fact_digest: str
    revocation_generation: int
    expires_at: str

    def __post_init__(self) -> None:
        _identifier(self.receipt_id, "receipt_id")
        if self.provider not in {"claude", "codex"}:
            raise ProviderBootUnavailable("receipt provider is unavailable")
        for value, name in (
            (self.launch_plan_digest, "launch_plan_digest"),
            (self.image_digest, "image_digest"),
            (self.broker_policy_digest, "broker_policy_digest"),
            (self.credential_policy_digest, "credential_policy_digest"),
            (self.host_fact_digest, "host_fact_digest"),
        ):
            _digest(value, name)
        if type(self.revocation_generation) is not int or self.revocation_generation < 0:
            raise ProviderBootUnavailable("revocation_generation is invalid")
        _time(self.expires_at)


def validateCapabilityEnforcement(
    plan: ProviderBootPlan,
    receipt: CapabilityEnforcementReceipt,
    *,
    current_revocation_generation: int,
    current_host_fact_digest: str | None = None,
    now: datetime | None = None,
) -> CapabilityEnforcementReceipt:
    """Exact-match a launch against fresh, provider-specific canary evidence."""

    if type(plan) is not ProviderBootPlan or type(receipt) is not CapabilityEnforcementReceipt:
        raise ProviderBootUnavailable("typed provider plan and capability receipt are required")
    if receipt.provider != plan.provider:
        raise ProviderBootUnavailable("provider differs from canary evidence")
    for expected, observed, name in (
        (receipt.launch_plan_digest, plan.launch_plan_digest, "launch plan"),
        (receipt.image_digest, plan.image_digest, "image"),
        (receipt.broker_policy_digest, plan.broker_policy_digest, "broker policy"),
        (
            receipt.credential_policy_digest,
            plan.credential_policy_digest,
            "credential policy",
        ),
    ):
        if expected != observed:
            raise ProviderBootUnavailable(f"{name} differs from canary evidence")
    if receipt.revocation_generation != current_revocation_generation:
        raise ProviderBootUnavailable("capability receipt was revoked")
    if current_host_fact_digest is not None:
        _digest(current_host_fact_digest, "current_host_fact_digest")
        if receipt.host_fact_digest != current_host_fact_digest:
            raise ProviderBootUnavailable("host enforcement facts changed")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ProviderBootUnavailable("capability clock must be timezone-aware")
    current = current.astimezone(timezone.utc)
    if _time(receipt.expires_at) <= current or _time(plan.deadline) <= current:
        raise ProviderBootUnavailable("provider capability or launch plan expired")
    if _time(plan.deadline) > _time(receipt.expires_at):
        raise ProviderBootUnavailable("launch deadline exceeds capability expiry")
    return receipt


class ProviderSafeBoot:
    """Guard a provider launcher with exact, fresh containment evidence."""

    def __init__(
        self,
        *,
        launcher: Callable[[ProviderBootPlan], _T],
        watchdog: AuthorityWatchdog,
        current_revocation_generation: int = 0,
        current_host_fact_digest: str | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if type(watchdog) is not AuthorityWatchdog:
            raise ProviderBootUnavailable("exact authority watchdog is required")
        self._launcher = launcher
        self._watchdog = watchdog
        self._revocation_generation = current_revocation_generation
        self._host_fact_digest = current_host_fact_digest
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def launch(
        self,
        plan: ProviderBootPlan,
        *,
        capability_receipt: CapabilityEnforcementReceipt | None,
        launch_authority: object,
    ) -> _T:
        if capability_receipt is None:
            raise ProviderBootUnavailable("provider canary evidence is unavailable")
        validated_receipt = validateCapabilityEnforcement(
            plan,
            capability_receipt,
            current_revocation_generation=self._revocation_generation,
            current_host_fact_digest=self._host_fact_digest,
            now=self._clock(),
        )
        try:
            validated_launch = self._watchdog.validateExecutionLaunchAuthority(
                launch_authority
            )
            assert isinstance(validated_launch, ExecutionLaunchAuthority)
            if validated_launch.transaction_id != plan.transaction_id:
                raise ProviderBootUnavailable("launch transaction differs")
            if validated_launch.capability_receipt_id != validated_receipt.receipt_id:
                raise ProviderBootUnavailable("launch capability receipt differs")
            if _time(validated_launch.deadline) > _time(plan.deadline):
                raise ProviderBootUnavailable("watchdog deadline exceeds provider plan")
            return self._watchdog.releaseStart(
                validated_launch,
                lambda: self._launcher(plan),
            )
        except ExecutionLaunchRefused as exc:
            raise ProviderBootUnavailable("watchdog launch authority is unavailable") from exc


__all__ = [
    "CapabilityEnforcementReceipt",
    "ProviderBootPlan",
    "ProviderBootUnavailable",
    "ProviderSafeBoot",
    "validateCapabilityEnforcement",
]
