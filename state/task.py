"""Lean task-state model + JSON persistence.

The JSON holds only IDs, statuses, timestamps and references to Obsidian notes.
All long-form content (architecture, subtask logs, reviews, handoffs) lives in
the vault as ``.md`` files; the JSON merely points at them.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import config

# Serializes concurrent save() calls within this process so the temp-file
# write + os.replace swap never interleave. os.replace itself is atomic at the
# filesystem level, guarding cross-process readers against torn JSON.
_SAVE_LOCK = threading.Lock()


def nowIso() -> str:
    """Local-timezone ISO-8601 timestamp (second precision)."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


class TaskState:
    """Wraps the lean state dict and persists it to ``state/tasks/<id>.json``."""

    def __init__(self, data: dict[str, Any]):
        self.data = data

    # ---- construction ---------------------------------------------------
    @classmethod
    def create(cls, goal_raw: str, time_horizon_hours: float) -> "TaskState":
        task_id = str(uuid.uuid4())
        started = datetime.now().astimezone()
        deadline = started + timedelta(hours=float(time_horizon_hours))
        date_str = started.strftime("%Y-%m-%d")
        vault_task_rel = f"{config.TASKS_DIR_REL}/{task_id}_{date_str}"
        data: dict[str, Any] = {
            "task_id": task_id,
            "meta": {
                "goal_raw": goal_raw,
                "goal_elaborated": None,
                "time_horizon_hours": float(time_horizon_hours),
                "started_at": started.isoformat(timespec="seconds"),
                "deadline_at": deadline.isoformat(timespec="seconds"),
                "status": "created",
                "blocked_reason": None,
                "control_mode": config.CONTROL_MODE_DEFAULT,
                "is_self_referential": False,
                "self_ref_branch": None,
                "subtask_seq": 0,
                "universe": None,
            },
            "plan": {"architect_design_doc": None, "subtasks": []},
            "adversary_reviews": [],
            "notifications": [],
            "context_handoffs": [],
            "obsidian": {
                "vault_root": str(config.VAULT_DISK_ROOT),
                "vault_task_dir": vault_task_rel,
                "index_note": f"{vault_task_rel}/index.md",
            },
        }
        return cls(data)

    # ---- convenient accessors ------------------------------------------
    @property
    def task_id(self) -> str:
        return self.data["task_id"]

    @property
    def meta(self) -> dict[str, Any]:
        return self.data["meta"]

    @property
    def subtasks(self) -> list[dict[str, Any]]:
        return self.data["plan"]["subtasks"]

    # ---- persistence ----------------------------------------------------
    def path(self) -> Path:
        return config.STATE_DIR / f"{self.task_id}.json"

    def save(self) -> Path:
        p = self.path()
        with _SAVE_LOCK:
            # serialize INSIDE the lock: another thread appending to a list/dict in self.data
            # while json.dumps walks it raises "changed size during iteration".
            payload = json.dumps(self.data, indent=2, ensure_ascii=False)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, p)
        return p

    @classmethod
    def load(cls, task_id: str) -> "TaskState":
        p = config.STATE_DIR / f"{task_id}.json"
        return cls(json.loads(p.read_text(encoding="utf-8")))

    _TERMINAL = ("done", "complete", "aborted", "partial", "blocked", "failed")

    @classmethod
    def loadLatest(cls) -> Optional["TaskState"]:
        # Prefer the most-recently-STARTED *active* (non-terminal) task; an unrelated save() that
        # bumps an old task's file mtime must not cause the wrong task to be resumed/inspected.
        best = None
        best_key = None
        for f in config.STATE_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            meta = data.get("meta", {})
            key = (0 if meta.get("status") in cls._TERMINAL else 1, meta.get("started_at", ""))
            if best_key is None or key > best_key:
                best_key, best = key, data
        return cls(best) if best is not None else None

    @classmethod
    def listRecent(cls, n: int = 10) -> list[dict[str, Any]]:
        """Lightweight summaries of recent tasks, newest first. Reads the JSON store directly."""
        out: list[dict[str, Any]] = []
        for f in config.STATE_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            meta = data.get("meta", {})
            subs = (data.get("plan", {}) or {}).get("subtasks", []) or []
            done = sum(1 for s in subs if s.get("status") == "done")
            total = sum(1 for s in subs if s.get("status") != "removed")
            out.append({
                "task_id": data.get("task_id", f.stem),
                "status": meta.get("status", "unknown"),
                "goal": meta.get("goal_raw", ""),
                "done": done,
                "total": total,
                "started_at": meta.get("started_at", ""),
            })
        out.sort(key=lambda d: d["started_at"], reverse=True)
        return out[:n]

    # ---- vault-relative note paths -------------------------------------
    def vaultTaskDir(self) -> str:
        return self.data["obsidian"]["vault_task_dir"]

    def indexNoteRel(self) -> str:
        return self.data["obsidian"]["index_note"]

    def architectNoteRel(self) -> str:
        return f"{self.vaultTaskDir()}/architect.md"

    def subtaskNoteRel(self, subtask_id: str) -> str:
        return f"{self.vaultTaskDir()}/subtasks/{subtask_id}.md"

    def subtaskReviewNoteRel(self, subtask_id: str) -> str:
        return f"{self.vaultTaskDir()}/subtasks/{subtask_id}-rv.md"

    def handoffNoteRel(self, ho_id: str) -> str:
        return f"{self.vaultTaskDir()}/handoffs/{ho_id}.md"

    def replanLogRel(self) -> str:
        return f"{self.vaultTaskDir()}/replan-log.md"

    # ---- mutation -------------------------------------------------------
    def setStatus(self, status: str, blocked_reason: Optional[str] = None) -> None:
        self.meta["status"] = status
        if blocked_reason is not None:
            self.meta["blocked_reason"] = blocked_reason
        self.save()

    def setElaboratedGoal(self, text: str) -> None:
        self.meta["goal_elaborated"] = text
        self.save()

    def setArchitectDoc(self, rel_path: str) -> None:
        self.data["plan"]["architect_design_doc"] = rel_path
        self.save()

    def setControlMode(self, mode: str) -> None:
        self.meta["control_mode"] = mode
        self.save()

    def markSelfReferential(self, branch: Optional[str] = None) -> None:
        self.meta["is_self_referential"] = True
        if branch:
            self.meta["self_ref_branch"] = branch
        self.save()

    def setUniverse(self, universe: dict) -> None:
        self.meta["universe"] = universe
        self.save()

    def recordVerify(self, subtask_id: str, result: dict) -> Optional[dict[str, Any]]:
        return self.updateSubtask(subtask_id, verify_result=result)

    def _nextSubtaskSeq(self) -> int:
        """Allocate a never-reused subtask number from a persisted counter.

        Legacy tasks created before ``meta["subtask_seq"]`` existed fall back to
        the max numeric id already present in the subtask list, so we never
        re-issue an id that a removed-but-still-referenced subtask once held.
        """
        seq = self.meta.get("subtask_seq")
        if seq is None:
            seq = 0
            for st in self.subtasks:
                sid = st.get("subtask_id", "")
                try:
                    seq = max(seq, int(str(sid).split("-")[-1]))
                except (ValueError, IndexError):
                    continue
        seq += 1
        self.meta["subtask_seq"] = seq
        return seq

    def addSubtask(self, title: str, description: str, assigned_to: str = "executor",
                   layer: int = 3, depends_on: Optional[list[str]] = None,
                   verify: Optional[dict] = None) -> dict[str, Any]:
        seq = self._nextSubtaskSeq()
        st: dict[str, Any] = {
            "subtask_id": f"st-{seq:03d}",
            "title": title,
            "description": description,
            "assigned_to": assigned_to,
            "layer": layer,
            "status": "pending",
            "depends_on": depends_on or [],
            "started_at": None,
            "completed_at": None,
            "output_ref": None,
            "github_pr": None,
            "verify": verify,
            "verify_result": None,
            "session": {},
        }
        self.subtasks.append(st)
        self.save()
        return st

    def getSubtask(self, subtask_id: str) -> Optional[dict[str, Any]]:
        for st in self.subtasks:
            if st["subtask_id"] == subtask_id:
                return st
        return None

    def updateSubtask(self, subtask_id: str, **fields: Any) -> Optional[dict[str, Any]]:
        st = self.getSubtask(subtask_id)
        if st is None:
            return None
        st.update(fields)
        self.save()
        return st

    def addAdversaryReview(self, subtask_id: str, trigger_reason: str, verdict: str,
                           note_ref: Optional[str] = None) -> dict[str, Any]:
        rec = {"subtask_id": subtask_id, "trigger_reason": trigger_reason,
               "verdict": verdict, "note_ref": note_ref, "at": nowIso()}
        self.data["adversary_reviews"].append(rec)
        self.save()
        return rec

    def addNotification(self, kind: str, detail: str) -> dict[str, Any]:
        rec = {"kind": kind, "detail": detail, "at": nowIso()}
        self.data["notifications"].append(rec)
        self.save()
        return rec

    def addHandoff(self, ho_id: str, summary: str, note_ref: str) -> dict[str, Any]:
        rec = {"handoff_id": ho_id, "summary": summary, "note_ref": note_ref, "at": nowIso()}
        self.data["context_handoffs"].append(rec)
        self.save()
        return rec

    # ---- progress helpers ----------------------------------------------
    def progress(self) -> tuple[int, int]:
        done = sum(1 for s in self.subtasks if s["status"] == "done")
        countable = sum(1 for s in self.subtasks if s["status"] != "removed")
        return done, countable

    def nextActionable(self) -> Optional[dict[str, Any]]:
        """First subtask whose deps are done; falls back to first not-finished."""
        finished = {"done", "failed", "removed"}
        for s in self.subtasks:
            if s["status"] != "pending":
                continue
            deps = s.get("depends_on") or []
            if all((self.getSubtask(d) or {}).get("status") == "done" for d in deps):
                return s
        for s in self.subtasks:
            if s["status"] not in finished:
                return s
        return None
