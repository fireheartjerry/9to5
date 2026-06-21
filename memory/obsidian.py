"""Obsidian memory layer: REST-first, disk-fallback note writer/reader.

The Local REST API is the preferred transport. It only accepts the 9to5
API key while the *9to5* vault is the one open in Obsidian (the port is
per-Obsidian-instance, not per-vault). Whenever REST is unavailable -- 401
because another vault is open, connection refused, or any non-2xx -- we
transparently fall back to writing the markdown straight onto disk under
``VAULT_DISK_ROOT``. Obsidian indexes those files the instant the vault opens,
so notes are never lost.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import requests
import urllib3

import config

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

LOG = config.getLogger("obsidian")


def writeClaudioMd(task_state, subtask: Optional[dict], additional_context: str = "",
                   work_dir: Optional[str] = None) -> Path:
    """Write a fresh per-subtask CLAUDE.md to the working directory.

    Claude Code auto-reads CLAUDE.md at session start, so this is how the
    Orchestrator hands full, just-in-time context to the Executor instead of
    stuffing it all into the prompt string. ``additional_context`` is the
    ``claude_md_inject`` field from the Ollama invocation spec.
    """
    work_dir_path = Path(work_dir) if work_dir else config.PROJECT_ROOT
    work_dir_path.mkdir(parents=True, exist_ok=True)
    meta = task_state.meta
    parts = [
        "# 9TO5 — live subtask context (auto-generated; read fully before acting)",
        "",
        f"**Task:** {task_state.task_id}  ·  **Status:** {meta.get('status')}",
        "",
        "## Goal (elaborated)",
        (meta.get("goal_elaborated") or meta.get("goal_raw") or "").strip(),
        "",
    ]
    if subtask:
        parts += [
            f"## Current subtask: {subtask.get('subtask_id')} — {subtask.get('title')}",
            (subtask.get("description") or "").strip(),
            "",
        ]
        verify = subtask.get("verify") or {}
        if verify.get("cmd"):
            parts += [
                "## Acceptance check (this subtask is DONE only when this passes)",
                f"`{verify['cmd']}`  (expect: {verify.get('expect', 'exit_zero')})",
                "",
            ]
    if additional_context:
        parts += ["## Orchestrator-injected context", additional_context.strip(), ""]
    parts += [
        "## Conventions",
        "- `ALL_CAPS` constants, `snake_case` variables, `camelCase` functions, `pathlib.Path` everywhere.",
        "",
        "## Never touch",
        "- `.env`, `venv/`, `.git/`, `state/`, other tasks' files — unless the subtask explicitly says so.",
        "",
    ]
    path = work_dir_path / "CLAUDE.md"
    path.write_text("\n".join(parts), encoding="utf-8")
    LOG.info("Wrote living CLAUDE.md (%d chars) to %s", path.stat().st_size, path)
    return path


class ObsidianClient:
    def __init__(self) -> None:
        self.base_url = config.OBSIDIAN_BASE_URL
        self.headers = {"Authorization": f"Bearer {config.OBSIDIAN_API_KEY}"}
        self.disk_root = config.VAULT_DISK_ROOT

    # ---- disk helpers ---------------------------------------------------
    def _diskPath(self, rel_path: str) -> Path:
        return self.disk_root / rel_path

    def _writeDisk(self, rel_path: str, content: str) -> Path:
        p = self._diskPath(rel_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    # ---- public API -----------------------------------------------------
    def writeNote(self, rel_path: str, content: str) -> dict:
        """Write ``content`` to ``rel_path`` via REST, falling back to disk."""
        url = f"{self.base_url}/vault/{rel_path}"
        try:
            r = requests.put(
                url,
                data=content.encode("utf-8"),
                headers={**self.headers, "Content-Type": "text/markdown"},
                verify=False,
                timeout=10,
            )
            if 200 <= r.status_code < 300:
                LOG.info("REST wrote %s (%s)", rel_path, r.status_code)
                return {"ok": True, "via": "rest", "rel_path": rel_path, "status": r.status_code}
            LOG.warning("REST PUT %s -> %s; falling back to disk", rel_path, r.status_code)
        except Exception as e:  # noqa: BLE001 -- any transport error => disk
            LOG.warning("REST PUT %s failed (%s); falling back to disk", rel_path, e)
        disk = self._writeDisk(rel_path, content)
        return {"ok": True, "via": "disk", "rel_path": rel_path, "disk_path": str(disk)}

    def readNote(self, rel_path: str) -> Optional[str]:
        url = f"{self.base_url}/vault/{rel_path}"
        try:
            r = requests.get(url, headers=self.headers, verify=False, timeout=10)
            if 200 <= r.status_code < 300:
                return r.text
        except Exception:  # noqa: BLE001
            pass
        p = self._diskPath(rel_path)
        if p.exists():
            return p.read_text(encoding="utf-8")
        return None

    def appendNote(self, rel_path: str, content: str) -> dict:
        existing = self.readNote(rel_path) or ""
        return self.writeNote(rel_path, existing + content)

    def health(self) -> dict:
        """Probe REST reachability and whether our key authenticates."""
        rest_ok = False
        authed = False
        try:
            r = requests.get(f"{self.base_url}/", verify=False, timeout=6)
            rest_ok = r.status_code == 200
        except Exception:  # noqa: BLE001
            return {"rest_ok": False, "authed": False}
        try:
            r2 = requests.get(f"{self.base_url}/vault/", headers=self.headers, verify=False, timeout=6)
            authed = 200 <= r2.status_code < 300
        except Exception:  # noqa: BLE001
            authed = False
        return {"rest_ok": rest_ok, "authed": authed}
