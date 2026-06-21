"""9to5 /health -- environment readiness checks.

Each check yields (name, ok, detail, fix). Run via `python main.py --health`
or `python health.py`. Exits 0 only if every check passes.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import requests
import urllib3

import config

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

GREEN = "\033[92m"
RED = "\033[91m"
YEL = "\033[93m"
RST = "\033[0m"


def _ollama() -> tuple[bool, str, str]:
    try:
        r = requests.get(f"{config.OLLAMA_HOST}/api/tags", timeout=5)
        models = [m.get("name") for m in (r.json().get("models") or [])]
        if config.OLLAMA_MODEL not in models:
            return False, f"server up but {config.OLLAMA_MODEL} not pulled (have {models})", \
                f"run: ollama pull {config.OLLAMA_MODEL}"
        # GPU: check loaded models for VRAM usage
        gpu = "GPU unknown (model not currently loaded)"
        try:
            ps = requests.get(f"{config.OLLAMA_HOST}/api/ps", timeout=5).json().get("models") or []
            for m in ps:
                if m.get("name") == config.OLLAMA_MODEL or m.get("model") == config.OLLAMA_MODEL:
                    vram = m.get("size_vram", 0)
                    gpu = f"on GPU ({vram // (1024*1024)} MB VRAM)" if vram else "loaded on CPU only"
        except Exception:  # noqa: BLE001
            pass
        return True, f"{config.OLLAMA_MODEL} present; {gpu}", ""
    except Exception as e:  # noqa: BLE001
        return False, f"server not reachable at {config.OLLAMA_HOST} ({e})", \
            "start Ollama (ollama serve) and ensure it listens on 11434"


def _claudeCli() -> tuple[bool, str, str]:
    exe = shutil.which("claude")
    if not exe:
        return False, "claude not on PATH", "install Claude Code CLI and ensure `claude` is on PATH"
    try:
        launcher = ["cmd", "/c", exe] if exe.lower().endswith((".cmd", ".bat")) else [exe]
        proc = subprocess.run(launcher + ["--print", "--dangerously-skip-permissions"],
                              input="Reply with exactly: OK", capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=40)
        if proc.returncode == 0 and (proc.stdout or "").strip():
            return True, f"authenticated; replied {proc.stdout.strip()[:20]!r}", ""
        return False, f"ran but no output (rc={proc.returncode}): {(proc.stderr or '')[:120]}", \
            "run `claude` once interactively to authenticate"
    except subprocess.TimeoutExpired:
        return False, "timed out (40s)", "check Claude Code auth / network"
    except Exception as e:  # noqa: BLE001
        return False, str(e), "run `claude` interactively to authenticate"


def _gh() -> tuple[bool, str, str]:
    if not shutil.which("gh"):
        return False, "gh not on PATH", "install GitHub CLI (https://cli.github.com)"
    try:
        proc = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True, timeout=15)
        ok = proc.returncode == 0
        msg = (proc.stderr or proc.stdout or "").strip().splitlines()
        return ok, (msg[-1] if msg else "ok"), ("" if ok else "run: gh auth login")
    except Exception as e:  # noqa: BLE001
        return False, str(e), "run: gh auth login"


def _obsidian() -> tuple[bool, str, str]:
    try:
        r = requests.get(config.OBSIDIAN_BASE_URL + "/", verify=False, timeout=5)
        return r.status_code == 200, f"reachable ({r.status_code}) at {config.OBSIDIAN_BASE_URL}", \
            ("" if r.status_code == 200 else "open Obsidian + enable Local REST API")
    except Exception as e:  # noqa: BLE001
        return False, f"not reachable ({e})", "start Obsidian with the Local REST API plugin"


def _discord() -> tuple[bool, str, str]:
    if not config.DISCORD_BOT_TOKEN:
        return False, "DISCORD_BOT_TOKEN missing", "set DISCORD_BOT_TOKEN in .env"
    try:
        r = requests.get("https://discord.com/api/v10/users/@me",
                         headers={"Authorization": f"Bot {config.DISCORD_BOT_TOKEN}"}, timeout=10)
        if r.status_code == 200:
            return True, f"bot online as {r.json().get('username')}", ""
        return False, f"token rejected ({r.status_code})", "check DISCORD_BOT_TOKEN in .env"
    except Exception as e:  # noqa: BLE001
        return False, str(e), "check network / DISCORD_BOT_TOKEN"


def _envKeys() -> tuple[bool, str, str]:
    required = ["DISCORD_BOT_TOKEN", "DISCORD_CHANNEL_ID", "DISCORD_HUMAN_USER_ID",
               "OBSIDIAN_API_KEY", "OBSIDIAN_PORT", "OBSIDIAN_VAULT_PATH", "PROJECT_ROOT", "LOG_PATH"]
    import os
    missing = [k for k in required if not os.getenv(k)]
    return (not missing), ("all present" if not missing else f"missing {missing}"), \
        ("" if not missing else f"add {missing} to .env")


def _git() -> tuple[bool, str, str]:
    try:
        proc = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                              cwd=config.PROJECT_ROOT, capture_output=True, text=True)
        ok = proc.returncode == 0 and "true" in (proc.stdout or "").lower()
        return ok, ("initialized" if ok else "not a git repo"), \
            ("" if ok else f"run: git -C {config.PROJECT_ROOT} init")
    except Exception as e:  # noqa: BLE001
        return False, str(e), "install git"


def _hooks() -> tuple[bool, str, str]:
    p = config.CLAUDE_SETTINGS_PATH
    if not p.exists():
        return False, "no .claude/settings.json", "create .claude/settings.json with hooks"
    try:
        import json
        data = json.loads(p.read_text(encoding="utf-8"))
        hooks = data.get("hooks") or {}
        return bool(hooks), f"hooks configured: {sorted(hooks.keys())}", \
            ("" if hooks else "add a hooks block to settings.json")
    except Exception as e:  # noqa: BLE001
        return False, str(e), "fix .claude/settings.json JSON"


def _vault() -> tuple[bool, str, str]:
    root = config.VAULT_DISK_ROOT
    tasks = root / config.TASKS_DIR_REL
    ok = root.exists()
    return ok, (f"exists at {root}" if ok else f"missing {root}"), \
        ("" if ok else "run any task once (ensureDirs creates it) or mkdir it")


CHECKS = [
    ("Ollama + qwen2.5:7b (GPU)", _ollama),
    ("Claude Code CLI auth", _claudeCli),
    ("GitHub CLI auth", _gh),
    ("Obsidian REST", _obsidian),
    ("Discord bot", _discord),
    (".env keys", _envKeys),
    ("git initialized", _git),
    ("hooks configured", _hooks),
    ("vault structure", _vault),
]


def runHealthChecks() -> bool:
    config.ensureDirs()
    print(f"\n  9to5 /health  —  {len(CHECKS)} checks\n  " + "=" * 52)
    all_ok = True
    for name, fn in CHECKS:
        try:
            ok, detail, fix = fn()
        except Exception as e:  # noqa: BLE001
            ok, detail, fix = False, f"check errored: {e}", "see traceback"
        all_ok = all_ok and ok
        tag = f"{GREEN}PASS{RST}" if ok else f"{RED}FAIL{RST}"
        print(f"  [{tag}] {name:30s} {detail}")
        if not ok and fix:
            print(f"         {YEL}fix:{RST} {fix}")
    print("  " + "=" * 52)
    print(f"  {'ALL SYSTEMS GO' if all_ok else 'NOT READY — see fixes above'}\n")
    return all_ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if runHealthChecks() else 1)
