"""ControlBus -- file-backed, cross-process run control.

Three processes share one JSON file per task (``state/control/<task_id>.json``):
the orchestrator run, the Discord gateway command bot, and the web dashboard.
Each command (abort / pause / approve / reject / skip / add / retry) is written
to the bus; the orchestrator drains it between steps. File-backed = no sockets,
survives process restarts, trivially inspectable.

Writes are atomic (temp file + ``os.replace``) so concurrent readers never see a
half-written file.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

import config


class AbortRun(Exception):
    """Raised inside the orchestrator when an abort has been requested."""


# Approval gates the orchestrator may wait on (gated mode).
GATES = ("plan", "pre_pr")


def _blank() -> dict[str, Any]:
    return {
        "abort": False,
        "pause": False,
        "decisions": {g: None for g in GATES},
        "plan_ops": [],          # queued: {"op": "skip"|"add"|"retry", ...}
        "seen_discord_id": None,  # last Discord message id processed by the poller
        "pending_gate": None,     # gate the run is currently waiting on (gated mode)
    }


class ControlBus:
    def __init__(self, task_id: str):
        self.task_id = task_id
        self.path: Path = config.CONTROL_DIR / f"{task_id}.json"
        if not self.path.exists():
            self._write(_blank())

    # ---- low-level atomic IO -------------------------------------------
    def load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 -- missing/corrupt => fresh
            data = _blank()
        # forward-compatible defaults
        base = _blank()
        base.update(data)
        base["decisions"] = {**_blank()["decisions"], **(data.get("decisions") or {})}
        return base

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def _mutate(self, fn) -> dict[str, Any]:
        data = self.load()
        fn(data)
        self._write(data)
        return data

    # ---- abort / pause --------------------------------------------------
    def requestAbort(self) -> None:
        self._mutate(lambda d: d.__setitem__("abort", True))

    def isAbort(self) -> bool:
        return bool(self.load()["abort"])

    def requestPause(self) -> None:
        self._mutate(lambda d: d.__setitem__("pause", True))

    def clearPause(self) -> None:
        self._mutate(lambda d: d.__setitem__("pause", False))

    def isPaused(self) -> bool:
        return bool(self.load()["pause"])

    # ---- approval decisions (gated mode) -------------------------------
    def decide(self, gate: str, verdict: str) -> None:
        def _f(d: dict[str, Any]) -> None:
            d.setdefault("decisions", {})[gate] = verdict
        self._mutate(_f)

    def getDecision(self, gate: str) -> Optional[str]:
        return (self.load().get("decisions") or {}).get(gate)

    def clearDecision(self, gate: str) -> None:
        def _f(d: dict[str, Any]) -> None:
            d.setdefault("decisions", {})[gate] = None
        self._mutate(_f)

    def setPendingGate(self, gate: Optional[str]) -> None:
        self._mutate(lambda d: d.__setitem__("pending_gate", gate))

    def getPendingGate(self) -> Optional[str]:
        return self.load().get("pending_gate")

    # ---- queued plan operations ----------------------------------------
    def pushOp(self, op: dict[str, Any]) -> None:
        self._mutate(lambda d: d["plan_ops"].append(op))

    def drainOps(self) -> list[dict[str, Any]]:
        data = self.load()
        ops = list(data.get("plan_ops") or [])
        if ops:
            data["plan_ops"] = []
            self._write(data)
        return ops

    # ---- Discord poll cursor -------------------------------------------
    def setSeen(self, message_id: Optional[str]) -> None:
        self._mutate(lambda d: d.__setitem__("seen_discord_id", message_id))

    def getSeen(self) -> Optional[str]:
        return self.load().get("seen_discord_id")

    # ---- lifecycle ------------------------------------------------------
    def clear(self) -> None:
        self._write(_blank())
