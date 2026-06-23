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

# Install root (the durable home of vault/logs/knowledge), independent of which
# git worktree the code happens to run from. Defaults to C:\supercritical.
SUPERCRITICAL_ROOT: Path = _envPath("SUPERCRITICAL_ROOT", r"C:\supercritical") or Path(r"C:\supercritical")

# --- Living Claude Code knowledge base -----------------------------------
# The maximalist self-analysis reference, refreshed each session and compressed
# into the "CLAUDE CODE CAPABILITIES" section injected into every Ollama prompt.
KNOWLEDGE_DIR: Path = _envPath("KNOWLEDGE_DIR", str(SUPERCRITICAL_ROOT / "knowledge")) or (SUPERCRITICAL_ROOT / "knowledge")
CLAUDE_KNOWLEDGE_PATH: Path = KNOWLEDGE_DIR / "claude_code.md"
# Expert, opinionated recommendations (how 9to5 should wield every Claude Code primitive).
# Folded into the unified reference as "Part E" and surfaced (executive slice) in the injection.
CLAUDE_RECOMMENDATIONS_PATH: Path = KNOWLEDGE_DIR / "recommendations.md"
# Roots scanned recursively for installed skills/agents/workflows/hooks/settings.
# Both the install root's .claude AND the running project's .claude are merged.
CLAUDE_SCAN_ROOTS: tuple[Path, ...] = (SUPERCRITICAL_ROOT / ".claude", PROJECT_ROOT / ".claude")
# Best-effort live-docs fetch (Python has internet; Ollama does not -- exploit it).
CLAUDE_DOC_FETCH: bool = _envBool("CLAUDE_DOC_FETCH", True)
CLAUDE_DOC_TIMEOUT_SECONDS: int = int(os.getenv("CLAUDE_DOC_TIMEOUT_SECONDS", "8"))
# Parallel doc fetch (the 27-page scrape goes from ~10s sequential to ~2s).
CLAUDE_DOC_FETCH_WORKERS: int = int(os.getenv("CLAUDE_DOC_FETCH_WORKERS", "10"))
# Freshness guard: if claude_code.md is younger than this, a (non-forced) refresh skips the
# web re-scrape and just recompresses the cached doc -- so frequent restarts stay instant.
CLAUDE_KNOWLEDGE_MAX_AGE_HOURS: float = float(os.getenv("CLAUDE_KNOWLEDGE_MAX_AGE_HOURS", "6"))
# Hard cap on the compressed injection so a 7B brain's context never overflows.
CLAUDE_CAPABILITIES_MAX_CHARS: int = int(os.getenv("CLAUDE_CAPABILITIES_MAX_CHARS", "9000"))

# --- Discord -------------------------------------------------------------
DISCORD_BOT_TOKEN: str = os.getenv("DISCORD_BOT_TOKEN", "")
_RAW_CHANNEL = os.getenv("DISCORD_CHANNEL_ID", "0") or "0"
DISCORD_CHANNEL_ID: int = int(_RAW_CHANNEL) if _RAW_CHANNEL.isdigit() else 0
# Human to @-ping for severe events only (blocked / critical decision / deadlock abort).
DISCORD_HUMAN_USER_ID: str = os.getenv("DISCORD_HUMAN_USER_ID", "")

# Guild for instant slash-command registration; 0 => global (can take ~1h to propagate).
_RAW_GUILD = os.getenv("DISCORD_GUILD_ID", "0") or "0"
DISCORD_GUILD_ID: int = int(_RAW_GUILD) if _RAW_GUILD.isdigit() else 0

# Discord hard limits (single source of truth for all truncation/clamping).
DISCORD_MAX_CONTENT: int = 2000
DISCORD_MAX_EMBED_DESC: int = 4096
DISCORD_MAX_FIELD_NAME: int = 256
DISCORD_MAX_FIELD_VALUE: int = 1024
DISCORD_EMBED_TOTAL_MAX: int = 6000
DISCORD_REST_TIMEOUT: int = 15      # seconds per Discord REST call
DISCORD_RETRY_MAX: int = 2          # 429 retries for milestone sends (NOT the control poll)

# --- Bot identity / branding ---
VERSION: str = "1.0.0"
BRAND_COLOR: int = 0x5865F2                      # 9TO5 brand (Discord blurple)
BRAND_ICON_URL: str = os.getenv("BRAND_ICON_URL", "")

# --- Bot UX behaviour ---
COOLDOWN_RATE: int = 3                            # max mutating-command uses ...
COOLDOWN_PER: float = 10.0                        # ... per this many seconds, per user
PRESENCE_INTERVAL: int = 30                       # seconds between bot presence refreshes

# --- Audit log (who issued which control command) ---
AUDIT_LOG_PATH: Path = PROJECT_ROOT / "state" / "audit.jsonl"
AUDIT_MAX_BYTES: int = 1_000_000                  # rotate audit.jsonl past ~1 MB

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
# Write notes to disk synchronously (durable + readable) and sync to Obsidian via REST in
# the background, so a slow/absent vault never blocks the run loop (~5-10s/run saved).
OBSIDIAN_ASYNC: bool = _envBool("OBSIDIAN_ASYNC", True)
# Reuse one SQLite connection per (thread, ledger path) instead of opening one per call.
EXPERIENCE_POOL: bool = _envBool("EXPERIENCE_POOL", True)

# --- Ollama (Orchestrator brain) -----------------------------------------
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")  # code-specialized brain (fits 8GB VRAM)
OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_TIMEOUT_SECONDS: int = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180"))  # prevent indefinite hangs
# Explicit context window: the injected CLAUDE CODE CAPABILITIES block (~2.2k tokens) sits in
# every system prompt; without this, ollama's small default num_ctx SILENTLY TRUNCATES the
# trailing JSON-schema instructions that format="json" calls depend on. Sized for injection +
# the largest user payload. Passed as options.num_ctx on every .chat() call.
OLLAMA_NUM_CTX: int = int(os.getenv("OLLAMA_NUM_CTX", "8192"))

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

# --- Self-Improvement Engine (SIE) ---------------------------------------
# Layer 0: the Experience Ledger -- a best-effort SQLite store of every run+subtask so
# the brain can learn from its own history. Sits beside the task store; writes never
# block a run. See docs/superpowers/specs/2026-06-22-self-improvement-engine-design.md.
EXPERIENCE_DB_PATH: Path = PROJECT_ROOT / "state" / "experience.db"
EXPERIENCE_LEDGER_ENABLED: bool = _envBool("EXPERIENCE_LEDGER_ENABLED", True)
# Layer 1 retrieval (wired in a later phase): local embedding model + injection budget.
EMBED_MODEL: str = os.getenv("EMBED_MODEL", "nomic-embed-text")
RETRIEVAL_K: int = int(os.getenv("RETRIEVAL_K", "5"))
RETRIEVAL_MAX_TOKENS: int = int(os.getenv("RETRIEVAL_MAX_TOKENS", "350"))
# Eval harness (the spine): golden suite + the single fitness scalar's weights.
EVAL_SUITE_DIR: Path = PROJECT_ROOT / "learning" / "eval_suite"
EVAL_FITNESS_WEIGHTS: dict[str, float] = {
    "first_pass_rate": 0.5,
    "attempts": 0.2,        # applied to (1 - norm_attempts)
    "cost": 0.15,           # applied to (1 - norm_cost)
    "plan_stability": 0.1,
    "challenge_rate": 0.05,  # applied to (1 - challenge_rate)
}
# Layer 2 consolidation: a lesson needs this many samples, and arms must separate by
# this win-rate gap, before it is emitted (keeps the digest high-signal, not noise).
LESSONS_MIN_SUPPORT: int = int(os.getenv("LESSONS_MIN_SUPPORT", "3"))
LESSONS_WIN_GAP: float = float(os.getenv("LESSONS_WIN_GAP", "0.2"))
# Layer 4 policy bandit reward weights (first-pass success minus cost/attempt penalties).
POLICY_REWARD_WEIGHTS: dict[str, float] = {
    "first_pass": 1.0, "attempts": 0.3, "cost": 0.2, "wallclock": 0.1,
}
# Layer 3 prompt promotion gate: a challenger needs this many field uses and this z-score
# (one-sided proportion test, 1.64 ~ 95%) on first-pass rate before it can become champion.
PROMPT_PROMOTE_MIN_USES: int = int(os.getenv("PROMPT_PROMOTE_MIN_USES", "20"))
PROMPT_PROMOTE_Z: float = float(os.getenv("PROMPT_PROMOTE_Z", "1.64"))
# Auto-maintenance: fire the throttled learning passes automatically after every run, so
# the user only ever starts/aborts/checks. (The test package disables this to stay fast;
# the runner itself is still exercised directly.)
SIE_AUTO_MAINTENANCE: bool = _envBool("SIE_AUTO_MAINTENANCE", True)
# Global kill switch: revert the brain to the frozen base model + freeze all promotions.
SIE_KILL_SWITCH: bool = _envBool("SIE_KILL_SWITCH", False)
# The frozen base model tag; champion adapters are served under BRAIN_MODEL_TAG:vN.
BRAIN_MODEL_TAG: str = os.getenv("BRAIN_MODEL_TAG", "9to5-brain")
# Layer 5 LoRA distillation: how many gold examples before a training cycle, and where
# adapters/datasets land. Training itself is a local, queued job (host GPU).
LORA_MIN_EXAMPLES: int = int(os.getenv("LORA_MIN_EXAMPLES", "50"))
LORA_OUTPUT_DIR: Path = _envPath("LORA_OUTPUT_DIR", str(PROJECT_ROOT / "state" / "adapters")) \
    or (PROJECT_ROOT / "state" / "adapters")
# DPO/ORPO preference training: KL anchor strength + minimum preference pairs to train.
DPO_KL_BETA: float = float(os.getenv("DPO_KL_BETA", "0.1"))
DPO_MIN_PAIRS: int = int(os.getenv("DPO_MIN_PAIRS", "30"))
# Next-wave knobs: confidence deferral threshold (escalate below this P(success)).
CONFIDENCE_DEFER_THRESHOLD: float = float(os.getenv("CONFIDENCE_DEFER_THRESHOLD", "0.4"))
# Subsystem I: ask the executor for a learning summary (teacher->student distillation).
SIE_REFLECTION_ENABLED: bool = _envBool("SIE_REFLECTION_ENABLED", True)
# Inject the learned authoring context (lessons/policy/guidance/surfaces/...) into specs.
SIE_AUTHORING_CONTEXT: bool = _envBool("SIE_AUTHORING_CONTEXT", True)
# Let 9to5 improve its OWN core loop files (orchestrator.py/main.py/config.py/hooks.py)
# during self-referential runs. Safe because: edits land on the isolated branch, the running
# process keeps its old bytecode, and a post-run test-suite gate reverts any breaking change
# before a PR. Default off (opt-in) -- the most powerful + most safety-sensitive capability.
SELFMOD_ALLOW_CORE: bool = _envBool("SELFMOD_ALLOW_CORE", False)
# Compute router for LoRA/DPO training: auto (GPU if present) | gpu (force) | cpu | off.
SIE_COMPUTE: str = os.getenv("SIE_COMPUTE", "auto")
# LoRA hyperparameters (used by the real local trainer on a GPU host).
LORA_RANK: int = int(os.getenv("LORA_RANK", "16"))
LORA_EPOCHS: int = int(os.getenv("LORA_EPOCHS", "2"))
# Autonomous self-play: practice self-generated goals during the work window (hands-off).
SELFPLAY_ENABLED: bool = _envBool("SELFPLAY_ENABLED", True)
SELFPLAY_MAX_PER_DAY: int = int(os.getenv("SELFPLAY_MAX_PER_DAY", "3"))
SELFPLAY_HOURS: float = float(os.getenv("SELFPLAY_HOURS", "1"))
SELFPLAY_START_HOUR: int = int(os.getenv("SELFPLAY_START_HOUR", "9"))
SELFPLAY_END_HOUR: int = int(os.getenv("SELFPLAY_END_HOUR", "17"))
# Auto-bootstrap the training stack + Ollama models (so the user only presses start).
SIE_BOOTSTRAP: bool = _envBool("SIE_BOOTSTRAP", True)
# Run supervision (the 9->5 promise): auto-resume a crashed run this many times before
# giving up, with exponential backoff capped here. Keeps a long run alive unattended.
RUN_MAX_RESTARTS: int = int(os.getenv("RUN_MAX_RESTARTS", "5"))
RUN_RESTART_MAX_BACKOFF: float = float(os.getenv("RUN_RESTART_MAX_BACKOFF", "60"))
RUN_STALL_SECONDS: float = float(os.getenv("RUN_STALL_SECONDS", "1800"))  # 30m no-progress

# Rich cross-surface automation: which non-terminal surfaces the executor can reach.
# MCP servers it should compose across (comma-separated env), plus browser/native layers.
MCP_SERVERS: tuple[str, ...] = tuple(
    s.strip() for s in os.getenv(
        "MCP_SERVERS", "github,gmail,google_calendar,google_drive,canva").split(",") if s.strip())
BROWSER_LAYER_ENABLED: bool = _envBool("BROWSER_LAYER_ENABLED", False)   # L1 (CDP)
NATIVE_LAYER_ENABLED: bool = _envBool("NATIVE_LAYER_ENABLED", False)     # L2 (UIA)
# Meta-optimization may auto-apply tuning to these knobs (persisted across restarts).
SIE_META_AUTOAPPLY: bool = _envBool("SIE_META_AUTOAPPLY", True)
SIE_TUNABLE_KNOBS: tuple[str, ...] = (
    "MAX_SUBTASK_ATTEMPTS", "RETRIEVAL_K", "ADVERSARY_HEARTBEAT_EVERY",
    "PROMPT_PROMOTE_MIN_USES", "CONFIDENCE_DEFER_THRESHOLD",
)
SIE_OVERRIDES_PATH: Path = PROJECT_ROOT / "state" / "sie_overrides.json"


def set_override(knob: str, value) -> bool:
    """Persist + live-apply a meta-optimizer knob change (whitelisted knobs only)."""
    if knob not in SIE_TUNABLE_KNOBS:
        return False
    import json as _json
    globals()[knob] = value
    try:
        data = {}
        if SIE_OVERRIDES_PATH.exists():
            data = _json.loads(SIE_OVERRIDES_PATH.read_text(encoding="utf-8"))
        data[knob] = value
        SIE_OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
        SIE_OVERRIDES_PATH.write_text(_json.dumps(data, indent=2), encoding="utf-8")
        return True
    except Exception:  # noqa: BLE001
        return False


def _load_overrides() -> None:
    """Apply persisted meta-optimizer knob overrides at import (survives restarts)."""
    try:
        import json as _json
        data = _json.loads(SIE_OVERRIDES_PATH.read_text(encoding="utf-8"))
        for k, v in data.items():
            if k in SIE_TUNABLE_KNOBS:
                globals()[k] = v
    except Exception:  # noqa: BLE001 -- absent/corrupt -> stock defaults
        pass


_load_overrides()

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
# Adversary "teeth": a 'challenged' verdict on a PASSED subtask triggers ONE bounded
# remediation attempt (concerns injected; never downgrades the passing result), and a
# 'challenged' pre-PR review HOLDS PR creation. Both default on; set False to keep advisory.
ADVERSARY_REMEDIATION_ENABLED: bool = os.getenv("ADVERSARY_REMEDIATION", "1") != "0"
ADVERSARY_PR_HOLD_ENABLED: bool = os.getenv("ADVERSARY_PR_HOLD", "1") != "0"
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

# --- Executor playbook (role-scoped expertise handed to the HANDS) --------
# Deterministically inject a role-scoped briefing into every subtask-execution run via the
# living CLAUDE.md (always-read) and --append-system-prompt (system-level, unforgettable),
# so the executor's expertise never depends on what the 7B brain remembered to include.
EXECUTOR_PLAYBOOK_ENABLED: bool = _envBool("EXECUTOR_PLAYBOOK_ENABLED", True)
EXECUTOR_APPEND_SYSTEM_PROMPT: bool = _envBool("EXECUTOR_APPEND_SYSTEM_PROMPT", True)
# Parse the structured --output-format json envelope (is_error/session_id/usage/cost) -- the
# trustworthy success signal (headless claude exits nonzero for benign reasons) + unblocks resume.
EXECUTOR_OUTPUT_JSON: bool = _envBool("EXECUTOR_OUTPUT_JSON", True)
# Resume the SAME Claude session across a subtask's retries (--resume <session_id>) so attempt 2/3
# fixes the failing assertion instead of re-exploring the repo from scratch.
EXECUTOR_RESUME_RETRIES: bool = _envBool("EXECUTOR_RESUME_RETRIES", True)

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
# Human display labels (single home; discord_bot.effortBar reads these — no private copy).
EFFORT_LABELS: dict[str, str] = {
    "low": "Low", "default": "Standard", "medium": "Standard",
    "high": "High", "xhigh": "Very High", "ultracode": "Max",
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
