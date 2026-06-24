"""Factory-reset module — granular deletion of 9to5 state, vault, and logs."""
from __future__ import annotations

import os
import shutil
import sys
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import config

LOG = config.getLogger("wipe")

ROOT = config.INSTALL_ROOT

CATEGORIES: dict[str, dict] = {
    "tasks": {
        "paths": [ROOT / "state" / "tasks"],
        "label": "Task JSON files",
    },
    "control": {
        "paths": [ROOT / "state" / "control"],
        "label": "Control bus files",
    },
    "experience": {
        "paths": [
            ROOT / "state" / "experience.db",
            ROOT / "state" / "experience.db-shm",
            ROOT / "state" / "experience.db-wal",
            ROOT / "state" / "adversary_trust.jsonl",
            ROOT / "state" / "audit.jsonl",
        ],
        "label": "Experience DB + audit log",
    },
    "vault": {
        "paths": [ROOT / "vault"],
        "label": "Obsidian vault",
        "keep_dir": True,
    },
    "logs": {
        "paths": [ROOT / "logs"],
        "label": "Execution logs",
    },
    "learning": {
        "paths": [ROOT / "learning"],
        "label": "Learning directory",
    },
    "knowledge": {
        "paths": [ROOT / "knowledge"],
        "label": "Knowledge base",
    },
    "chatgpt_profile": {
        "paths": [ROOT / "state" / "chatgpt_profile"],
        "label": "ChatGPT browser profile",
    },
}

BACKUP_DIR = ROOT / "state" / "backups"


def backupState(keys: list[str]) -> Optional[Path]:
    """Tarball the paths about to be wiped. Returns path or None on failure."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_DIR / f"wipe-backup-{stamp}.tar.gz"
    try:
        with tarfile.open(dest, "w:gz") as tar:
            for key in keys:
                cat = CATEGORIES.get(key, {})
                for p in cat.get("paths", []):
                    if p.exists():
                        tar.add(p, arcname=str(p.relative_to(ROOT)))
        LOG.info("Backup saved → %s", dest)
        return dest
    except Exception:
        LOG.exception("Backup failed")
        return None


def deleteCategory(key: str) -> tuple[bool, str]:
    """Delete one category. Returns (ok, human-readable status line)."""
    cat = CATEGORIES.get(key)
    if cat is None:
        return False, f"Unknown category: {key}"
    errors: list[str] = []
    for p in cat["paths"]:
        if not p.exists():
            continue
        try:
            if p.is_dir() and cat.get("keep_dir"):
                for child in p.iterdir():
                    shutil.rmtree(child) if child.is_dir() else child.unlink()
            elif p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
        except Exception as exc:
            errors.append(f"{p.name}: {exc}")
    if errors:
        return False, f"{cat['label']}: {'; '.join(errors)}"
    return True, cat["label"]


def executeWipe(keys: list[str], backup: bool = False) -> dict[str, str]:
    """Run wipe on selected categories. Returns ordered {key: status_line} dict."""
    results: dict[str, str] = {}
    if backup:
        path = backupState(keys)
        results["_backup"] = f"✓ Backup: {path}" if path else "✗ Backup failed (proceeding anyway)"
    for key in keys:
        ok, msg = deleteCategory(key)
        results[key] = f"✓ {msg}" if ok else f"✗ {msg}"
    LOG.info("Wipe complete: %s", results)
    return results


def restartBot() -> None:
    """Replace current process with a fresh bot instance (no leftover in-memory state)."""
    LOG.info("Restarting bot via os.execv")
    os.execv(sys.executable, [sys.executable, "-m", "notifications.command_bot"])
