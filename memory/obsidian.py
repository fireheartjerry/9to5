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

import atexit
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import requests
import urllib3

import config

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

LOG = config.getLogger("obsidian")

_APPEND_LOCK = threading.Lock()  # serialize appendNote read-modify-write

# Background pool for REST syncs to Obsidian -- the disk write is the source of truth and
# happens synchronously; the (slow, 10s-timeout) REST PUT runs off the hot path so a slow
# or unavailable vault never blocks the run loop. Flushed at process exit.
_REST_POOL: Optional[ThreadPoolExecutor] = None
_REST_LOCK = threading.Lock()


def _restPool() -> ThreadPoolExecutor:
    global _REST_POOL
    with _REST_LOCK:
        if _REST_POOL is None:
            _REST_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="obsidian-rest")
            atexit.register(lambda: _REST_POOL and _REST_POOL.shutdown(wait=True))
    return _REST_POOL


def _restPut(base_url: str, headers: dict, rel_path: str, content: str) -> None:
    """Best-effort REST sync to Obsidian (runs in the background pool)."""
    try:
        r = requests.put(f"{base_url}/vault/{rel_path}", data=content.encode("utf-8"),
                         headers={**headers, "Content-Type": "text/markdown"},
                         verify=False, timeout=10)
        if not (200 <= r.status_code < 300):
            LOG.debug("REST PUT %s -> %s (disk copy already written)", rel_path, r.status_code)
    except Exception as e:  # noqa: BLE001 -- disk already has it; REST is a bonus
        LOG.debug("REST PUT %s failed (%s); disk copy already written", rel_path, e)


def flushRest(timeout: Optional[float] = None) -> None:
    """Wait for queued REST syncs to drain (used on shutdown / before resume reads)."""
    global _REST_POOL
    with _REST_LOCK:
        pool, _REST_POOL = _REST_POOL, None
    if pool is not None:
        pool.shutdown(wait=True)


def writeClaudioMd(task_state, subtask: Optional[dict], additional_context: str = "",
                   work_dir: Optional[str] = None, executor_playbook: str = "") -> Path:
    """Write a fresh per-subtask CLAUDE.md to the working directory.

    Claude Code auto-reads CLAUDE.md at session start, so this is how the
    Orchestrator hands full, just-in-time context to the Executor instead of
    stuffing it all into the prompt string. ``additional_context`` is the
    ``claude_md_inject`` field from the Ollama invocation spec; ``executor_playbook``
    is the deterministic role-scoped briefing (from ``agents/playbook.py``) -- it is
    injected on EVERY attempt so the executor's expertise is never forgotten.
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
    if meta.get("is_self_referential"):
        parts += [config.ARCHITECTURE_BRIEF, ""]
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
    if executor_playbook:
        parts += [executor_playbook.strip(), ""]
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
    content = "\n".join(parts)
    _atomicWriteText(path, content)
    LOG.info("Wrote living CLAUDE.md (%d chars) to %s", len(content.encode("utf-8")), path)
    return path


def _atomicWriteText(path: Path, content: str) -> None:
    """Write text as a COMPLETE-file swap (unique temp + os.replace) so a concurrent reader never
    sees a half-written file. Parallel non-self-referential subtasks share one ``work_dir/CLAUDE.md``
    and the executor launches ``claude`` (which auto-reads it) right after writing -- a plain
    truncate-then-write would let one worker read another's torn CLAUDE.md. Bounded retry mirrors
    control.py's: on Windows ``os.replace`` raises PermissionError while a reader momentarily holds
    the destination. FALLS BACK to a direct write if the swap can't complete, so this is never worse
    than the previous plain write."""
    tmp = path.parent / f"{path.name}.{os.getpid()}-{threading.get_ident()}-{os.urandom(4).hex()}.tmp"
    try:
        tmp.write_text(content, encoding="utf-8")
        delay = 0.02
        for attempt in range(6):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == 5:
                    break
                time.sleep(min(delay, 0.3))
                delay *= 2
        path.write_text(content, encoding="utf-8")   # swap kept failing: fall back (no regression)
        tmp.unlink(missing_ok=True)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        path.write_text(content, encoding="utf-8")   # last resort: behave exactly like the old code


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
        """Persist ``content`` to ``rel_path``: disk first (fast + durable + readable, the
        source of truth), then sync to Obsidian via REST in the BACKGROUND so the slow
        10s-timeout PUT never blocks the run. Set ``OBSIDIAN_ASYNC=false`` for the old
        synchronous REST-first behavior."""
        if not getattr(config, "OBSIDIAN_ASYNC", True):
            return self._writeNoteSync(rel_path, content)
        try:
            disk = self._writeDisk(rel_path, content)
            result = {"ok": True, "via": "disk", "rel_path": rel_path, "disk_path": str(disk)}
        except Exception as e:  # noqa: BLE001 -- never raise into the run (documented contract)
            LOG.error("writeNote disk write failed for %s: %s", rel_path, e)
            result = {"ok": False, "via": "none", "rel_path": rel_path, "error": str(e)}
        try:
            _restPool().submit(_restPut, self.base_url, dict(self.headers), rel_path, content)
        except Exception:  # noqa: BLE001 -- background sync is a bonus, never load-bearing
            pass
        return result

    def _writeNoteSync(self, rel_path: str, content: str) -> dict:
        """Legacy synchronous REST-first write (disk fallback)."""
        try:
            r = requests.put(
                f"{self.base_url}/vault/{rel_path}", data=content.encode("utf-8"),
                headers={**self.headers, "Content-Type": "text/markdown"}, verify=False, timeout=10)
            if 200 <= r.status_code < 300:
                return {"ok": True, "via": "rest", "rel_path": rel_path, "status": r.status_code}
        except Exception as e:  # noqa: BLE001 -- any transport error => disk
            LOG.warning("REST PUT %s failed (%s); falling back to disk", rel_path, e)
        try:
            disk = self._writeDisk(rel_path, content)
            return {"ok": True, "via": "disk", "rel_path": rel_path, "disk_path": str(disk)}
        except Exception as e:  # noqa: BLE001
            LOG.error("writeNote disk fallback failed for %s: %s", rel_path, e)
            return {"ok": False, "via": "none", "rel_path": rel_path, "error": str(e)}

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
        # O(1) disk append (the common path -- REST 401s when another vault is open, and Obsidian
        # indexes the on-disk change anyway). Avoids the read+overwrite O(n^2) cost and lost-update race.
        with _APPEND_LOCK:
            p = self._diskPath(rel_path)
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                with p.open("a", encoding="utf-8") as fh:
                    fh.write(content)
                return {"ok": True, "via": "disk-append", "rel_path": rel_path, "disk_path": str(p)}
            except Exception as e:  # noqa: BLE001
                LOG.warning("appendNote disk-append failed (%s); read+rewrite fallback", e)
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
