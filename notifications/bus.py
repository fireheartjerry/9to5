"""NotificationBus — fan-out event emitter for notification surfaces.

Each registered surface must expose a ``handle(event_type: str, payload: dict)``
method.  A surface that raises must never propagate into the caller (Gap 1
surface-isolation contract from st-006).
"""
from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

_log = logging.getLogger(__name__)


@runtime_checkable
class NotificationSurface(Protocol):
    def handle(self, event_type: str, payload: dict) -> None: ...


class NotificationBus:
    """Register surfaces once; emit events to all of them, swallowing per-surface errors."""

    def __init__(self) -> None:
        self._surfaces: list[NotificationSurface] = []

    def register(self, surface: NotificationSurface) -> None:
        self._surfaces.append(surface)

    def emit(self, event_type: str, payload: dict) -> None:
        for surface in self._surfaces:
            try:
                surface.handle(event_type, payload)
            except Exception:  # noqa: BLE001
                _log.exception("surface %r raised on event %r — suppressed", surface, event_type)
