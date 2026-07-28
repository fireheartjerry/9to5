"""Typed, fail-closed launch plans for model and analysis processes.

The plan is inert data.  It neither discovers host configuration nor starts a
process; the guarded launch boundary consumes it only after capability and
watchdog validation.

Exports:
  LaunchPlanRefused -- A launch plan is incomplete or widens the closed surface.
  BackendLaunchPlan -- Immutable provider/backend launch facts.
  AnalysisLaunchPlan -- Immutable read-only analysis policy.
  buildLaunchEnvironment(plan) -- Build a closed environment from plan bytes only.
  validateAnalysisLaunchPlan(plan) -- Enforce the no-write/no-delegation profile.
  resolveAnalysisRunner(...) -- Resolve analysis containment without hidden fallback.

RUN/TEST: python -m pytest tests/execution/test_executor_env.py tests/review/test_analysis_isolation.py
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}$")

_ENVIRONMENT_NAMES = frozenset(
    {
        "CLAUDE_CONFIG_DIR",
        "CODEX_HOME",
        "HOME",
        "LANG",
        "LC_ALL",
        "NO_COLOR",
        "PATH",
        "SYSTEMROOT",
        "TEMP",
        "TERM",
        "TMP",
        "TMPDIR",
        "USERPROFILE",
        "WINDIR",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
    }
)
_FORBIDDEN_ENVIRONMENT_PREFIXES = (
    "ANTHROPIC_",
    "AWS_",
    "AZURE_",
    "CODEX_API_",
    "GIT_",
    "GOOGLE_",
    "HTTP_",
    "HTTPS_",
    "NO_PROXY",
    "OLLAMA_",
    "OPENAI_",
    "PYTHON",
    "SSL_",
    "VIRTUAL_ENV",
)
_BROKER_OPERATIONS = frozenset(
    {"repo_read", "repo_list", "repo_search", "repo_apply_patch", "repo_exec"}
)
_READ_ONLY_ANALYSIS_OPERATIONS = frozenset({"repo_read", "repo_list", "repo_search"})


class LaunchPlanRefused(ValueError):
    """The requested launch plan cannot prove its closed capability surface."""


def _identifier(value: str, name: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise LaunchPlanRefused(f"invalid {name}")
    return value


def _digest(value: str, name: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise LaunchPlanRefused(f"invalid {name}")
    return value


def _deadline(value: str) -> str:
    if not isinstance(value, str) or "T" not in value or not value.endswith(("Z", "+00:00")):
        raise LaunchPlanRefused("deadline must be an absolute UTC timestamp")
    return value


def _strings(values: tuple[str, ...] | frozenset[str], name: str) -> None:
    if not values or any(not isinstance(value, str) or not value for value in values):
        raise LaunchPlanRefused(f"{name} must contain non-empty strings")


@dataclass(frozen=True, slots=True)
class BackendLaunchPlan:
    """Immutable facts consumed by a guarded provider launch."""

    transaction_id: str
    driver_argv: tuple[str, ...]
    driver_environment: Mapping[str, str]
    driver_cwd: str
    projection_root: str
    session_root: str
    broker_operations: frozenset[str]
    resource_ids: tuple[str, ...]
    mounts: tuple[object, ...]
    egress_profile_digest: str
    resource_profile_digest: str
    security_profile_digest: str
    capability_receipt_id: str
    deadline: str

    def __post_init__(self) -> None:
        _identifier(self.transaction_id, "transaction_id")
        _strings(self.driver_argv, "driver_argv")
        _strings(self.resource_ids, "resource_ids")
        _identifier(self.capability_receipt_id, "capability_receipt_id")
        _digest(self.egress_profile_digest, "egress_profile_digest")
        _digest(self.resource_profile_digest, "resource_profile_digest")
        _digest(self.security_profile_digest, "security_profile_digest")
        _deadline(self.deadline)
        for name, value in (
            ("driver_cwd", self.driver_cwd),
            ("projection_root", self.projection_root),
            ("session_root", self.session_root),
        ):
            if not isinstance(value, str) or not value:
                raise LaunchPlanRefused(f"{name} is required")
        if not self.broker_operations or not self.broker_operations <= _BROKER_OPERATIONS:
            raise LaunchPlanRefused("broker operation surface is empty or unknown")
        if len(set(self.resource_ids)) != len(self.resource_ids):
            raise LaunchPlanRefused("resource_ids contain duplicates")
        if not isinstance(self.driver_environment, Mapping):
            raise LaunchPlanRefused("driver_environment must be a mapping")
        frozen = MappingProxyType(dict(self.driver_environment))
        object.__setattr__(self, "driver_environment", frozen)


def _environment_name_allowed(name: str) -> bool:
    upper = name.upper()
    if upper in _ENVIRONMENT_NAMES:
        return True
    return not upper.startswith(_FORBIDDEN_ENVIRONMENT_PREFIXES) and upper in _ENVIRONMENT_NAMES


def buildLaunchEnvironment(plan: BackendLaunchPlan) -> dict[str, str]:
    """Return a new closed environment without reading :data:`os.environ`."""

    if type(plan) is not BackendLaunchPlan:
        raise LaunchPlanRefused("launch environment requires an exact BackendLaunchPlan")
    result: dict[str, str] = {}
    for raw_name, raw_value in sorted(plan.driver_environment.items()):
        if not isinstance(raw_name, str) or not raw_name or not _environment_name_allowed(raw_name):
            raise LaunchPlanRefused(f"environment name is not allowlisted: {raw_name!r}")
        if not isinstance(raw_value, str) or "\x00" in raw_value or "\r" in raw_value or "\n" in raw_value:
            raise LaunchPlanRefused(f"environment value is invalid: {raw_name}")
        result[raw_name] = raw_value
    return result


@dataclass(frozen=True, slots=True)
class AnalysisLaunchPlan:
    """Contained analysis authority facts; never mutation or promotion authority."""

    transaction_id: str
    trust_tier: str
    allowed_operations: frozenset[str]
    snapshot_digest: str
    spec_digest: str
    capability_receipt_id: str
    deadline: str

    def __post_init__(self) -> None:
        _identifier(self.transaction_id, "transaction_id")
        _digest(self.snapshot_digest, "snapshot_digest")
        _digest(self.spec_digest, "spec_digest")
        _identifier(self.capability_receipt_id, "capability_receipt_id")
        _deadline(self.deadline)
        if self.trust_tier not in {"trusted_local", "unknown", "hostile"}:
            raise LaunchPlanRefused("analysis trust tier is unknown")
        if not self.allowed_operations:
            raise LaunchPlanRefused("analysis operation surface is empty")


def validateAnalysisLaunchPlan(plan: AnalysisLaunchPlan) -> AnalysisLaunchPlan:
    """Validate the exact read/list/search-only analysis surface."""

    if type(plan) is not AnalysisLaunchPlan:
        raise LaunchPlanRefused("analysis requires an exact AnalysisLaunchPlan")
    if not plan.allowed_operations <= _READ_ONLY_ANALYSIS_OPERATIONS:
        raise LaunchPlanRefused("analysis plan includes write, shell, delegation, or plugin authority")
    return plan


def resolveAnalysisRunner(
    *,
    trust_tier: str,
    docker_capability_receipt: object,
    trusted_local_capability_receipt: object,
) -> str:
    """Resolve one analysis runner without hostile-to-Local fallback."""

    if trust_tier in {"unknown", "hostile"}:
        if docker_capability_receipt is None:
            raise LaunchPlanRefused("contained Docker analysis capability is unavailable")
        return "docker"
    if trust_tier == "trusted_local":
        if trusted_local_capability_receipt is None:
            raise LaunchPlanRefused("trusted Local analysis capability is unavailable")
        return "local"
    raise LaunchPlanRefused("analysis trust tier is unknown")


__all__ = [
    "AnalysisLaunchPlan",
    "BackendLaunchPlan",
    "LaunchPlanRefused",
    "buildLaunchEnvironment",
    "resolveAnalysisRunner",
    "validateAnalysisLaunchPlan",
]
