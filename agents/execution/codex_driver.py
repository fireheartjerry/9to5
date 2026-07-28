"""Contained Codex adapter over the canonical driver event contracts.

RUN/TEST: python -m pytest tests/execution/test_provider_safe_boot.py
"""

from __future__ import annotations

from typing import Callable, Iterable

from agents.execution.claude_driver import (
    DriverEvent,
    DriverProtocolRefused,
    DriverRequest,
    validateDriverEventStream,
)


class CodexDriver:
    provider = "codex"

    def __init__(self, *, transport: Callable[[DriverRequest], Iterable[DriverEvent]]) -> None:
        self._transport = transport

    def invoke(self, request: DriverRequest) -> tuple[DriverEvent, ...]:
        if type(request) is not DriverRequest:
            raise DriverProtocolRefused("typed driver request is required")
        return validateDriverEventStream(request, self._transport(request))


__all__ = ["CodexDriver"]
