"""NotificationBus — fan-out event emitter for notification surfaces.

Each registered surface must expose a ``handle(event_type: str, payload: dict)``
method.  A surface that raises must never propagate into the caller (Gap 1
surface-isolation contract from st-006).
"""
from __future__ import annotations

import logging
import threading
from typing import Protocol, runtime_checkable

_log = logging.getLogger(__name__)


@runtime_checkable
class NotificationSurface(Protocol):
    def handle(self, event_type: str, payload: dict) -> None: ...


class NotificationBus:
    """Register surfaces once; emit events to all of them, swallowing per-surface errors."""

    def __init__(self) -> None:
        self._surfaces: list[NotificationSurface] = []
        self._lock = threading.Lock()

    def register(self, surface: NotificationSurface) -> None:
        with self._lock:
            self._surfaces.append(surface)

    @property
    def surface_count(self) -> int:
        """Number of registered surfaces."""
        with self._lock:
            return len(self._surfaces)

    def emit(self, event_type: str, payload: dict) -> None:
        with self._lock:
            snapshot = list(self._surfaces)
        for surface in snapshot:
            try:
                surface.handle(event_type, payload)
            except BaseException:  # noqa: BLE001 — surface errors must never reach callers
                _log.exception("surface %r raised on event %r — suppressed", surface, event_type)
