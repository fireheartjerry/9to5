"""Error handling utilities for the simulation layer.

Centralises the three recurring patterns in simulation.py:
  - safe JSON parsing (brain responses)
  - safe file writes (builderRunClaude artifacts)
  - safe chat-message extraction (SimBrain / BuilderBrain)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

LOG = logging.getLogger("sim_error_handling")


def safeParseJson(text: str, fallback: Any = None) -> Any:
    """Return parsed JSON or *fallback* on any parse / type error."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        LOG.warning("safeParseJson failed: %s", exc)
        return fallback


def safeWritePath(path, content: str, encoding: str = "utf-8") -> dict:
    """Write *content* to *path*, creating parent dirs as needed.

    Returns {"ok": True, "error": None} on success or
    {"ok": False, "error": "<message>"} on failure (never raises).
    """
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding=encoding)
        return {"ok": True, "error": None}
    except Exception as exc:  # noqa: BLE001
        LOG.warning("safeWritePath failed for %s: %s", path, exc)
        return {"ok": False, "error": str(exc)}


def safeChatExtract(messages, role: str = "user") -> str:
    """Return the last *role* message content, or "" on any error."""
    try:
        msgs = messages or []
        content = next(
            (m.get("content") for m in reversed(msgs)
             if isinstance(m, dict) and m.get("role") == role),
            None,
        )
        return content if isinstance(content, str) else ""
    except Exception as exc:  # noqa: BLE001
        LOG.warning("safeChatExtract failed: %s", exc)
        return ""
