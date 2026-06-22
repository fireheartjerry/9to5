"""9TO5 -- central configuration.

Loads environment from ``C:\\supercritical\\.env`` and exposes typed, ALL_CAPS
constants plus a few helper functions (camelCase). Nothing here hardcodes a
secret or path; every value originates from the ``.env`` file.

Mental model reminder:
  * Orchestrator brain  = Ollama ``qwen2.5:7b`` (local, zero API cost).
  * Executor hands      = Claude Code CLI subprocess.
Python is pure plumbing between them.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Force UTF-8 stdio so emoji/arrows in prints, logs, and dashboards never crash
# under Windows' cp1252 default (e.g. when stdout is redirected to a file).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001 -- not a real TextIOWrapper; ignore
        pass

# --- locate + load .env (lives next to this file) ------------------------
_THIS_DIR = Path(__file__).resolve().parent
_ENV_FILE = _THIS_DIR / ".env"
load_dotenv(dotenv_path=_ENV_FILE)


def _envPath(key: str, default: str | None = None) -> Path | None:
    raw = os.getenv(key, default)
    return Path(raw) if raw else None


def _envBool(key: str, default: bool = False) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# --- core paths ----------------------------------------------------------
PROJECT_ROOT: Path = _envPath("PROJECT_ROOT", str(_THIS_DIR)) or _THIS_DIR
LOG_PATH: Path = _envPath("LOG_PATH", str(PROJECT_ROOT / "logs")) or (PROJECT_ROOT / "logs")

# --- Discord -------------------------------------------------------------
DISCORD_BOT_TOKEN: str = os.getenv("DISCORD_BOT_TOKEN", "")
_RAW_CHANNEL = os.getenv("DISCORD_CHANNEL_ID", "0") or "0"
DISCORD_CHANNEL_ID: int = int(_RAW_CHANNEL) if _RAW_CHANNEL.isdigit() else 0
# Human to @-ping for severe events only (blocked / critical decision / deadlock abort).
DISCORD_HUMAN_USER_ID: str = os.getenv("DISCORD_HUMAN_USER_ID", "")

# --- Obsidian Local REST API ---------------------------------------------
OBSIDIAN_API_KEY: str = os.getenv("OBSIDIAN_API_KEY", "")
OBSIDIAN_PORT: int = int(os.getenv("OBSIDIAN_PORT", "27124"))
OBSIDIAN_HTTPS: bool = _envBool("OBSIDIAN_HTTPS", True)
OBSIDIAN_VAULT_PATH: Path = _envPath("OBSIDIAN_VAULT_PATH", str(PROJECT_ROOT / "vault")) or (PROJECT_ROOT / "vault")

_SCHEME = "https" if OBSIDIAN_HTTPS else "http"
OBSIDIAN_BASE_URL: str = f"{_SCHEME}://127.0.0.1:{OBSIDIAN_PORT}"

# Physical folder of the Obsidian vault that actually contains ``.obsidian/``
# (one level below OBSIDIAN_VAULT_PATH). Notes are written here on disk; this is
# also the REST vault-root when the ``9to5`` vault is open in Obsidian.
VAULT_DISK_ROOT: Path = OBSIDIAN_VAULT_PATH / "9to5"

# Vault-relative folders (used for both REST paths and on-disk paths).
TASKS_DIR_REL: str = "tasks"
SESSIONS_DIR_REL: str = "sessions"

# --- Ollama (Orchestrator brain) -----------------------------------------
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")  # code-specialized brain (fits 8GB VRAM)
OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_TIMEOUT_SECONDS: int = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180"))  # prevent indefinite hangs

# --- Claude Code CLI (Executor hands) ------------------------------------
# A `claude --print` call is a FULL agent session (explore repo -> reason -> write -> self-verify),
# not a single completion. Measured: trivial call ~9s, a contained edit ~97s, an exploration-heavy
# task ~500s true runtime. 300s clipped the heavy tail. 600s covers it with margin. NOTE: the real
# bug was never this number -- it was that subprocess timeout on Windows left node grandchildren
# orphaned (work continued + drain blocked ~200s); executor._killProcessTree now kills the tree.
CLAUDE_CLI_TIMEOUT_SECONDS: int = int(os.getenv("CLAUDE_CLI_TIMEOUT_SECONDS", "600"))

# --- Local task-state JSON store -----------------------------------------
STATE_DIR: Path = PROJECT_ROOT / "state" / "tasks"
CONTROL_DIR: Path = PROJECT_ROOT / "state" / "control"

# --- Adversary trigger configuration -------------------------------------
ADVERSARY_TRIGGER_PHRASES: tuple[str, ...] = (
    "i'm not sure",
    "i am not sure",
    "unclear",
    "multiple approaches",
    "could go either way",
    "not certain",
    "ambiguous",
)
ADVERSARY_HEARTBEAT_EVERY: int = 3   # every 3rd subtask -> heartbeat review
MAX_SUBTASK_ATTEMPTS: int = 3        # max executor attempts per subtask (verify-retry)
MAX_SUBTASKS: int = 8                # hard cap on plan size (anti-runaway / anti-livelock)

# --- Verification gate ---------------------------------------------------
VERIFY_DEFAULT_EXPECT: str = "exit_zero"
VERIFY_TIMEOUT_SECONDS: int = 120

# --- Run control + live dashboards ---------------------------------------
CONTROL_MODE_DEFAULT: str = "watch"   # "watch" (autonomous + abort) | "gated" (approval gates)
DISCORD_POLL_SECONDS: int = 4         # poll the channel for control commands between steps
DISCORD_DASHBOARD: bool = True        # one self-updating embed per run
WEB_DASHBOARD: bool = True
WEB_DASHBOARD_PORT: int = 8787
DEFAULT_PARALLELISM: int = 1          # >1 runs independent ready subtasks concurrently

# --- Claude Code primitives (CLAUDE.md / skills / subagents / hooks / settings) ---
CLAUDE_DIR: Path = PROJECT_ROOT / ".claude"
CLAUDE_SETTINGS_PATH: Path = CLAUDE_DIR / "settings.json"
# Absolute venv python so Claude Code hooks run with our deps regardless of cwd.
VENV_PYTHON: Path = PROJECT_ROOT / "venv" / "Scripts" / "python.exe"
# Automatic model fallback chain (handed to `claude --fallback-model`).
PRIMARY_MODEL: str = "claude-opus-4-8"
FALLBACK_MODEL: str = "claude-sonnet-4-6"
# Skills + subagents the Orchestrator (Ollama) is allowed to reference in a spec.
AVAILABLE_SKILLS: tuple[str, ...] = ("/architect-review", "/write-obsidian-note", "/create-pr")
AVAILABLE_SUBAGENTS: tuple[str, ...] = ("architect", "security-reviewer")
AVAILABLE_PRE_HOOKS: tuple[str, ...] = ("block_destructive", "log_all")
AVAILABLE_POST_HOOKS: tuple[str, ...] = ("write_obsidian", "discord_notify", "log_all")

# --- Self-referential safety (9to5 modifying itself) ----------------------
# When a task targets 9to5 itself: run on a dedicated git branch, inject the
# architecture, and guard the core files that run the very loop executing it.
CORE_PROTECTED_FILES: tuple[str, ...] = ("orchestrator.py", "main.py", "agents/hooks.py", "config.py")
SELF_REF_BRANCH_PREFIX: str = "sc/"
# Files/dirs a run must NEVER touch unless the goal's universe explicitly allows.
UNIVERSE_DEFAULT_HARD_BOUNDARIES: tuple[str, ...] = (".env", ".git", "venv", "state/tasks")

SELF_IMPROVEMENT_PHILOSOPHY: str = (
    "When 9to5 runs on itself, it operates with one principle: improve indiscriminately. No numerical "
    "targets. No fixed feature list. No \"add 5 features\" goals. Instead: hunt bugs, strengthen error "
    "handling, refactor weak areas, improve code quality, add missing tests, tighten the orchestration "
    "loop, improve Obsidian write reliability, make Discord embeds richer, improve Ollama prompt quality "
    "-- whatever is most impactful at each moment based on what the codebase actually needs. Keep going "
    "instrumentally until the time horizon ends. The measure of success is not a checklist completed but "
    "a codebase that is meaningfully better than when the run started."
)
ARCHITECTURE_BRIEF: str = (
    "## 9to5 architecture (you are operating ON 9to5 itself)\n"
    "9to5 is an autonomous orchestrator: the BRAIN is local Ollama qwen2.5:7b (it authors JSON "
    "invocation specs); the HANDS are the Claude Code CLI (you). Python is pure plumbing.\n"
    "Key files: `orchestrator.py` (brain loop: plan->spec->execute->verify->retry->replan), "
    "`main.py` (entry/CLI/resume/health/terminal-control), `config.py` (env+constants), "
    "`agents/` (elaborator, architect, executor, adversary[stub], replanner, verifier, hooks), "
    "`control.py` (ControlBus: abort/pause/gates), `memory/obsidian.py` (notes, REST+disk fallback), "
    "`state/task.py` (lean task JSON), `notifications/` (discord_bot, dashboard, webdash, command_bot), "
    "`health.py` (/health checks).\n"
    "Invocation-spec keys: claude_md_inject, skills_to_invoke, effort_level, subagent, prompt, "
    "pre_tool_hooks, post_tool_hooks. Conventions: ALL_CAPS constants, snake_case vars, camelCase "
    "functions, pathlib.Path everywhere. Install root is C:\\supercritical (never move it).\n"
    "SELF-MODIFICATION RULES: you are on a dedicated git branch. Do NOT edit the CORE files "
    "(orchestrator.py, main.py, agents/hooks.py, config.py) -- they run the very loop executing you, "
    "and editing them mid-run can corrupt the orchestrator. Make changes to OTHER files, add new "
    "modules, or describe core-file changes in your output for human review."
)

# --- Effort levels --------------------------------------------------------
# Ollama emits one of these per subtask; mapped to the CLI's --effort value.
EFFORT_LEVELS: tuple[str, ...] = ("default", "high", "xhigh", "ultracode")
EFFORT_FLAG_MAP: dict[str, str] = {
    "low": "low", "default": "medium", "medium": "medium",
    "high": "high", "xhigh": "xhigh", "ultracode": "max",
}
EFFORT_BARS: dict[str, str] = {
    "low": "▰▱▱▱▱", "default": "▰▰▱▱▱", "medium": "▰▰▱▱▱",
    "high": "▰▰▰▱▱", "xhigh": "▰▰▰▰▱", "ultracode": "▰▰▰▰▰",
}

# --- Discord status palette (embed sidebar color by phase/status) ----------
STATUS_COLORS: dict[str, int] = {
    "created": 0x95A5A6, "starting": 0x95A5A6,
    "architecting": 0x3498DB,           # blue  = architect phase
    "planning": 0x3498DB,
    "executing": 0x2ECC71, "running": 0x2ECC71,   # green = running
    "verifying": 0x2ECC71,
    "adversary": 0xE67E22,              # orange = adversary reviewing
    "replanning": 0x9B59B6,             # purple = replanning
    "paused": 0xF1C40F,                 # yellow = paused/awaiting
    "blocked": 0xE74C3C,                # red   = blocked
    "failed": 0xE74C3C,
    "aborted": 0x992D22,
    "done": 0x2ECC71, "complete": 0x2ECC71, "partial": 0xE67E22,
}

# --- directories that must exist -----------------------------------------
_REQUIRED_DIRS = (
    LOG_PATH,
    STATE_DIR,
    CONTROL_DIR,
    CLAUDE_DIR,
    VAULT_DISK_ROOT,
    VAULT_DISK_ROOT / TASKS_DIR_REL,
    VAULT_DISK_ROOT / SESSIONS_DIR_REL,
)


def ensureDirs() -> None:
    """Create every directory 9TO5 needs (idempotent)."""
    for d in _REQUIRED_DIRS:
        Path(d).mkdir(parents=True, exist_ok=True)


def validateEnv() -> list[str]:
    """Return the names of required-but-missing environment values."""
    missing: list[str] = []
    if not OBSIDIAN_API_KEY:
        missing.append("OBSIDIAN_API_KEY")
    if not DISCORD_BOT_TOKEN:
        missing.append("DISCORD_BOT_TOKEN")
    if not DISCORD_CHANNEL_ID:
        missing.append("DISCORD_CHANNEL_ID")
    return missing


_LOGGER_CONFIGURED = False


def _configureLogging() -> None:
    global _LOGGER_CONFIGURED
    if _LOGGER_CONFIGURED:
        return
    LOG_PATH.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    base = logging.getLogger("9to5")
    base.setLevel(logging.INFO)
    fh = logging.FileHandler(LOG_PATH / "9to5.log", encoding="utf-8")
    fh.setFormatter(fmt)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    base.addHandler(fh)
    base.addHandler(ch)
    base.propagate = False
    _LOGGER_CONFIGURED = True


def getLogger(name: str = "9to5") -> logging.Logger:
    """Return a child of the configured ``9to5`` logger."""
    _configureLogging()
    full = name if name.startswith("9to5") else f"9to5.{name}"
    return logging.getLogger(full)
