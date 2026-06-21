"""Lean task-state model + JSON persistence.

The JSON holds only IDs, statuses, timestamps and references to Obsidian notes.
All long-form content (architecture, subtask logs, reviews, handoffs) lives in
the vault as ``.md`` files; the JSON merely points at them.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import config


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
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        return p

    @classmethod
    def load(cls, task_id: str) -> "TaskState":
        p = config.STATE_DIR / f"{task_id}.json"
        return cls(json.loads(p.read_text(encoding="utf-8")))

    @classmethod
    def loadLatest(cls) -> Optional["TaskState"]:
        files = sorted(config.STATE_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime)
        if not files:
            return None
        return cls(json.loads(files[-1].read_text(encoding="utf-8")))

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

    def recordVerify(self, subtask_id: str, result: dict) -> Optional[dict[str, Any]]:
        return self.updateSubtask(subtask_id, verify_result=result)

    def addSubtask(self, title: str, description: str, assigned_to: str = "executor",
                   layer: int = 3, depends_on: Optional[list[str]] = None,
                   verify: Optional[dict] = None) -> dict[str, Any]:
        idx = len(self.subtasks) + 1
        st: dict[str, Any] = {
            "subtask_id": f"st-{idx:03d}",
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
