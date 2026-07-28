"""Provider-neutral event contracts and contained Claude driver adapter.

The adapter owns no filesystem or process primitive.  It receives an already
safe-booted transport and a closed broker operation set, then validates a
monotonic event stream.

RUN/TEST: python -m pytest tests/execution/test_provider_safe_boot.py
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Callable, Iterable, Mapping

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}$")
_OPERATIONS = frozenset(
    {"repo_read", "repo_list", "repo_search", "repo_apply_patch", "repo_exec"}
)
_EVENTS = frozenset({"started", "delta", "tool_request", "tool_result", "terminal", "failure"})


class DriverProtocolRefused(RuntimeError):
    """Provider driver request or event stream violates the closed protocol."""


def _time(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise DriverProtocolRefused("driver deadline is invalid") from exc
    if result.tzinfo is None:
        raise DriverProtocolRefused("driver deadline is not absolute")
    return result.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class DriverRequest:
    invocation_id: str
    transaction_id: str
    prompt: str
    model: str
    broker_operations: frozenset[str]
    deadline: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.invocation_id, "invocation_id"),
            (self.transaction_id, "transaction_id"),
            (self.model, "model"),
        ):
            if not isinstance(value, str) or not _ID.fullmatch(value):
                raise DriverProtocolRefused(f"{name} is invalid")
        if not isinstance(self.prompt, str) or not self.prompt or len(self.prompt.encode("utf-8")) > 2 * 1024 * 1024:
            raise DriverProtocolRefused("driver prompt is empty or oversized")
        if not self.broker_operations or not self.broker_operations <= _OPERATIONS:
            raise DriverProtocolRefused("driver broker operation set is invalid")
        if _time(self.deadline) <= datetime.now(timezone.utc):
            raise DriverProtocolRefused("driver request already expired")


@dataclass(frozen=True, slots=True)
class DriverEvent:
    invocation_id: str
    sequence: int
    kind: str
    payload: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _ID.fullmatch(self.invocation_id) or type(self.sequence) is not int or self.sequence < 1:
            raise DriverProtocolRefused("driver event identity or sequence is invalid")
        if self.kind not in _EVENTS or not isinstance(self.payload, Mapping):
            raise DriverProtocolRefused("driver event kind or payload is invalid")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


def validateDriverEventStream(
    request: DriverRequest,
    events: Iterable[DriverEvent],
) -> tuple[DriverEvent, ...]:
    if type(request) is not DriverRequest:
        raise DriverProtocolRefused("typed driver request is required")
    result = tuple(events)
    if not result:
        raise DriverProtocolRefused("driver event stream is empty")
    terminal = 0
    for expected, event in enumerate(result, 1):
        if type(event) is not DriverEvent or event.invocation_id != request.invocation_id:
            raise DriverProtocolRefused("driver event invocation differs")
        if event.sequence != expected:
            raise DriverProtocolRefused("driver event sequence is not contiguous")
        if event.kind in {"terminal", "failure"}:
            terminal += 1
            if expected != len(result):
                raise DriverProtocolRefused("driver terminal event is not last")
    if result[0].kind != "started" or terminal != 1:
        raise DriverProtocolRefused("driver stream lacks unique start/terminal events")
    return result


class ClaudeDriver:
    provider = "claude"

    def __init__(self, *, transport: Callable[[DriverRequest], Iterable[DriverEvent]]) -> None:
        self._transport = transport

    def invoke(self, request: DriverRequest) -> tuple[DriverEvent, ...]:
        if type(request) is not DriverRequest:
            raise DriverProtocolRefused("typed driver request is required")
        return validateDriverEventStream(request, self._transport(request))


__all__ = [
    "ClaudeDriver",
    "DriverEvent",
    "DriverProtocolRefused",
    "DriverRequest",
    "validateDriverEventStream",
]
