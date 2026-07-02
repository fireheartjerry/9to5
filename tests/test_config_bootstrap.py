"""R12 config-v2 regression suite: env bootstrap, typed registry, PEP 562 facade.

Guards the three landmines this rewrite removed:
1. PROJECT_ROOT collapsing to platform_core/app_config/ when no env is present
   (STATE_DIR/LOG_PATH/EXPERIENCE_DB_PATH silently resolved INSIDE the package).
2. set_override mutating config's globals() only, so config.KNOB and the registry
   silently diverged after a live-tune.
3. Model/effort routing defaults drifting during the reorganization (they must be
   byte-identical to the pre-R12 literals).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

import config
import platform_core.app_config.settings as app_settings

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# 1) Bootstrap: PROJECT_ROOT landmine
# ---------------------------------------------------------------------------

def test_project_root_is_repo_root_not_package_dir():
    assert Path(config.PROJECT_ROOT).resolve() == REPO_ROOT
    assert "app_config" not in str(config.PROJECT_ROOT)


def test_derived_paths_live_under_repo_root():
    for name in ("STATE_DIR", "CONTROL_DIR", "EXPERIENCE_DB_PATH", "EVAL_SUITE_DIR",
                 "SIE_OVERRIDES_PATH", "HEARTBEAT_DIR", "LAUNCH_DIR", "IPC_DIR"):
        p = str(getattr(app_settings.settings().paths, name))
        assert str(REPO_ROOT) in p, f"{name} escaped the repo root: {p}"
        assert "app_config" not in p, f"{name} still inside the package dir: {p}"


def test_subprocess_import_from_non_repo_cwd_resolves_repo_root():
    """THE landmine regression: import the paths domain with PROJECT_ROOT env unset,
    from a cwd OUTSIDE the repo -> PROJECT_ROOT must equal the repo root (marker walk
    from __file__), never the package dir and never a .env-file PROJECT_ROOT."""
    env = {k: v for k, v in os.environ.items() if k != "PROJECT_ROOT"}
    env["PYTHONPATH"] = str(REPO_ROOT)
    code = ("import platform_core.app_config.paths as p; "
            "print(p.PROJECT_ROOT); print(p.STATE_DIR)")
    r = subprocess.run([sys.executable, "-c", code], cwd=tempfile.gettempdir(),
                       env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"paths import failed from non-repo cwd:\n{r.stderr}"
    got_root, got_state = r.stdout.strip().splitlines()[-2:]
    assert Path(got_root).resolve() == REPO_ROOT
    assert Path(got_state).resolve() == REPO_ROOT / "state" / "tasks"


def test_dotenv_project_root_never_leaks_to_children():
    """loadEnvOnce scrubs a .env-provided PROJECT_ROOT from os.environ so child
    processes cannot inherit it as a fake process-level override."""
    from platform_core.app_config import _env
    _env.loadEnvOnce()
    if _env._PROCESS_PROJECT_ROOT is None:   # normal case: no real process override
        assert "PROJECT_ROOT" not in os.environ


def test_load_env_once_is_idempotent():
    from platform_core.app_config import _env
    _env.loadEnvOnce()
    snapshot = dict(os.environ)
    _env.loadEnvOnce()
    assert dict(os.environ) == snapshot


# ---------------------------------------------------------------------------
# 2) Facade mechanics
# ---------------------------------------------------------------------------

def test_import_time_from_import_still_works():
    from config import OLLAMA_NUM_CTX, STATE_DIR  # noqa: PLC0415 -- the compat contract
    assert OLLAMA_NUM_CTX == app_settings.settings().ollama.OLLAMA_NUM_CTX
    # from-import snapshots whatever config.X currently resolves to -- including a
    # monkeypatched shadow (conftest isolates STATE_DIR); both views must agree.
    assert STATE_DIR == config.STATE_DIR


def test_monkeypatched_shadow_wins_over_registry(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path, raising=False)
    assert config.STATE_DIR == tmp_path                       # shadow wins (conftest relies on this)
    assert app_settings.settings().paths.STATE_DIR != tmp_path  # registry untouched


def test_unknown_attribute_raises_attribute_error():
    try:
        config.DEFINITELY_NOT_A_KNOB
    except AttributeError as e:
        assert "DEFINITELY_NOT_A_KNOB" in str(e)
    else:
        raise AssertionError("facade must raise AttributeError for unknown names")


def test_namespace_pollution_gone():
    """The old star-import facade leaked config.os / config.Path / config.load_dotenv."""
    for junk in ("os", "load_dotenv"):
        assert not hasattr(config, junk), f"config.{junk} leaked again"


def test_run_flags_route_through_facade():
    flags = app_settings.runFlags()
    saved = flags.WEB_DASHBOARD
    try:
        flags.WEB_DASHBOARD = not saved
        assert config.WEB_DASHBOARD == (not saved)   # facade reads the live flag object
    finally:
        flags.WEB_DASHBOARD = saved


def test_main_cli_overrides_mutate_run_flags_not_config_globals(monkeypatch):
    """main.py no longer pokes config module globals: CLI overrides land on runFlags()."""
    import types

    import main as main_mod
    flags = app_settings.runFlags()
    saved = (flags.NIGHT_MODE, flags.WEB_DASHBOARD, flags.WEB_DASHBOARD_PORT)
    names = ("NIGHT_MODE", "WEB_DASHBOARD", "WEB_DASHBOARD_PORT", "CLAUDE_DOC_FETCH")
    shadows_before = {n: (n in vars(config)) for n in names}
    monkeypatch.setattr(config, "ensureDirs", lambda: None, raising=False)
    args = types.SimpleNamespace(web_port=9999, no_web=True, night_mode=True,
                                 mode="gated", auto_approve=False)
    try:
        main_mod._applyConfigOverrides(args)
        assert flags.WEB_DASHBOARD_PORT == 9999
        assert flags.WEB_DASHBOARD is False
        assert flags.NIGHT_MODE is True
        assert args.mode == "watch" and args.auto_approve is True   # night mode side effects
        assert {n: (n in vars(config)) for n in names} == shadows_before, \
            "main.py wrote a config module global again"
    finally:
        flags.NIGHT_MODE, flags.WEB_DASHBOARD, flags.WEB_DASHBOARD_PORT = saved


def test_legacy_name_surface_is_complete():
    """Spot-check one name per legacy module/group so a lost re-export fails loudly."""
    names = [
        # paths
        "PROJECT_ROOT", "LOG_PATH", "INSTALL_ROOT", "KNOWLEDGE_DIR", "CLAUDE_KNOWLEDGE_PATH",
        "CLAUDE_RECOMMENDATIONS_PATH", "CLAUDE_SCAN_ROOTS", "OBSIDIAN_VAULT_PATH",
        "VAULT_DISK_ROOT", "TASKS_DIR_REL", "SESSIONS_DIR_REL", "STATE_DIR", "CONTROL_DIR",
        "HEARTBEAT_DIR", "LAUNCH_DIR", "IPC_DIR", "BLACKBOARD_DIR", "EXPERIENCE_DB_PATH",
        "EVAL_SUITE_DIR", "EVOLUTION_SUITE_DIR", "EVOLUTION_SKILL_DIR", "EVOLUTION_CANDIDATE_DIR",
        "LORA_OUTPUT_DIR", "ADVERSARY_TRUST_LOG", "SIE_OVERRIDES_PATH", "AUDIT_LOG_PATH",
        "AUDIT_MAX_BYTES", "CLAUDE_DIR", "CLAUDE_SETTINGS_PATH", "VENV_PYTHON",
        # discord
        "DISCORD_BOT_TOKEN", "DISCORD_CHANNEL_ID", "DISCORD_HUMAN_USER_ID", "DISCORD_GUILD_ID",
        "DISCORD_MAX_CONTENT", "DISCORD_MAX_EMBED_DESC", "DISCORD_MAX_FIELD_NAME",
        "DISCORD_MAX_FIELD_VALUE", "DISCORD_EMBED_TOTAL_MAX", "DISCORD_REST_TIMEOUT",
        "DISCORD_RETRY_MAX", "VERSION", "BRAND_COLOR", "BRAND_ICON_URL", "COOLDOWN_RATE",
        "COOLDOWN_PER", "PRESENCE_INTERVAL", "DISCORD_POLL_SECONDS", "DISCORD_DASHBOARD",
        "WEB_DASHBOARD", "WEB_DASHBOARD_PORT", "DISCORD_LAB_MODE", "DASHBOARD_CV2", "CAST_MODE",
        "ASK_ENABLED", "ASK_NL_CONTROL", "POLL_GATES", "RUN_THREADS", "SCHEDULED_EVENTS",
        "AUTOMOD_GUARD", "REACTION_APPROVE", "WATCHDOG_ENABLED", "VISUALS_ENABLED",
        "COCKPIT_THEME", "COCKPIT_IMAGE_MIN_INTERVAL", "DISCORD_MSGFLAG_COMPONENTS_V2",
        "DISCORD_CV2_MAX_COMPONENTS", "DISCORD_CV2_MAX_CHARS", "NIGHT_MODE",
        "NIGHT_MODE_PAUSE_TIMEOUT", "STATUS_COLORS",
        # llm: ollama/gemini
        "OLLAMA_MODEL", "OLLAMA_HOST", "OLLAMA_TIMEOUT_SECONDS", "OLLAMA_NUM_CTX",
        "OLLAMA_GEN_HEADROOM", "OLLAMA_KEEP_ALIVE", "EMBED_MODEL", "BRAIN_MODEL_TAG",
        "BRIEF_MODEL", "GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_ENABLED", "GEMINI_TIMEOUT_MS",
        "GEMINI_MAX_TURNS", "GEMINI_MIN_OUTPUT_CHARS", "GEMINI_JSON_REPAIR_RETRIES",
        "GEMINI_HEALTH_PROBE_RETRIES", "GEMINI_SYSTEM_PREAMBLE",
        # llm: claude cli / effort / knowledge fetch
        "CLAUDE_CLI_TIMEOUT_SECONDS", "CANCEL_POLL_SECONDS", "PRIMARY_MODEL", "FALLBACK_MODEL",
        "MODEL_BY_EFFORT", "SESSION_LIMIT_PAUSE_SECONDS", "SESSION_LIMIT_MAX_RETRIES",
        "GIT_TIMEOUT_SECONDS", "EXECUTOR_PLAYBOOK_ENABLED", "EXECUTOR_APPEND_SYSTEM_PROMPT",
        "EXECUTOR_OUTPUT_JSON", "EXECUTOR_RESUME_RETRIES", "EFFORT_LEVELS", "EFFORT_FLAG_MAP",
        "EFFORT_BARS", "EFFORT_LABELS", "CLAUDE_DOC_FETCH", "CLAUDE_DOC_TIMEOUT_SECONDS",
        "CLAUDE_DOC_FETCH_WORKERS", "CLAUDE_DOC_FETCH_BUDGET_SECONDS",
        "CLAUDE_KNOWLEDGE_MAX_AGE_HOURS", "CLAUDE_CAPABILITIES_MAX_CHARS", "MCP_SERVERS",
        "AVAILABLE_SKILLS", "AVAILABLE_SUBAGENTS", "AVAILABLE_PRE_HOOKS", "AVAILABLE_POST_HOOKS",
        # llm: sie / adversary / orchestration / run control
        "OBSIDIAN_API_KEY", "OBSIDIAN_PORT", "OBSIDIAN_HTTPS", "OBSIDIAN_BASE_URL",
        "OBSIDIAN_ASYNC", "EXPERIENCE_POOL", "EXPERIENCE_LEDGER_ENABLED", "RETRIEVAL_K",
        "RETRIEVAL_MAX_TOKENS", "RETRIEVAL_MIN_SCORE", "RETRIEVAL_CONTENT_MAX_TOKENS",
        "ANN_INDEX_ENABLED", "ANN_INDEX_BACKEND", "ANN_INDEX_DIR", "ANN_EMBED_DIM",
        "RETRIEVAL_W_RECENCY", "RETRIEVAL_W_IMPORTANCE", "RETRIEVAL_W_RELEVANCE",
        "RETRIEVAL_RECENCY_HALFLIFE_DAYS", "COMPACTION_ENABLED", "COMPACTION_TRIGGER_RATIO",
        "COMPACTION_RESERVE_RATIO", "COMPACTION_RESERVE_FLOOR", "COMPACTION_MAX_PASSES",
        "COMPACTION_OFFLOAD_DIR", "REFLECTION_CONSOLIDATE_ENABLED", "EVAL_FITNESS_WEIGHTS",
        "LESSONS_MIN_SUPPORT", "LESSONS_WIN_GAP", "POLICY_REWARD_WEIGHTS",
        "PROMPT_PROMOTE_MIN_USES", "PROMPT_PROMOTE_Z", "SIE_AUTO_MAINTENANCE",
        "SIE_MAINTENANCE_JOIN_SECONDS", "SIE_KILL_SWITCH", "LORA_MIN_EXAMPLES", "DPO_KL_BETA",
        "DPO_MIN_PAIRS", "CONFIDENCE_DEFER_THRESHOLD", "SIE_REFLECTION_ENABLED",
        "SIE_AUTHORING_CONTEXT", "INSIGHT_TRIGGER_BUDGET", "EVOLUTION_ENABLED",
        "EVOLUTION_CONSOLIDATE", "EVOLUTION_ESCALATE", "EVOLUTION_CANARY_FRACTION",
        "EVOLUTION_ESCALATE_MIN_FAILS", "EVOLUTION_PINNED_SKILLS", "EVOLUTION_STALE_DAYS",
        "EVOLUTION_ARCHIVE_DAYS", "SELFMOD_ALLOW_CORE", "SEMANTIC_SAFETY_ENABLED",
        "AUTONOMY_ALLOWANCE_USD", "AUTONOMOUS_DESTRUCTIVE_POLICY",
        "AUTONOMOUS_DESTRUCTIVE_ALLOWANCE_USD", "CLAUDE_ATTEMPT_COST_HINT_USD", "SIE_COMPUTE",
        "LORA_RANK", "LORA_EPOCHS", "SELFPLAY_ENABLED", "SELFPLAY_MAX_PER_DAY", "SELFPLAY_HOURS",
        "SELFPLAY_START_HOUR", "SELFPLAY_END_HOUR", "SIE_BOOTSTRAP", "RUN_MAX_RESTARTS",
        "RUN_RESTART_MAX_BACKOFF", "RUN_STALL_SECONDS", "BROWSER_LAYER_ENABLED",
        "NATIVE_LAYER_ENABLED", "ADVERSARY_REVIEW_PLAN", "ADVERSARY_REVIEW_ARCH",
        "ADVERSARY_REVIEW_PREPR_DIFF", "ADVERSARY_LOWCONF_CONSULT",
        "ADVERSARY_PREPR_DIFF_MAX_CHARS", "ADVERSARY_BLOCKING_SEVERITY",
        "ADVERSARY_REMEDIATION_MAX_ATTEMPTS", "ADVERSARY_TRIGGER_PHRASES",
        "ADVERSARY_HEARTBEAT_EVERY", "ADVERSARY_REMEDIATION_ENABLED", "ADVERSARY_PR_HOLD_ENABLED",
        "MAX_SUBTASK_ATTEMPTS", "MAX_SUBTASKS", "VERIFY_DEFAULT_EXPECT", "VERIFY_TIMEOUT_SECONDS",
        "CONTROL_MODE_DEFAULT", "PLAN_GATE_AUTO_APPROVE_SECONDS", "DEFAULT_PARALLELISM",
        "PREDICTIVE_FLAGS_ENABLED", "PREDICTIVE_FLAG_OLLAMA",
        "PREDICTIVE_FLAG_MIN_INTERVAL_SECONDS", "INSTINCT_ENABLED", "INSTINCT_INTERVAL_SECONDS",
        "SIE_META_AUTOAPPLY", "SIE_TUNABLE_KNOBS",
        # prompts + self-ref safety
        "SELF_IMPROVEMENT_PHILOSOPHY", "ARCHITECTURE_BRIEF", "BRAIN_DIALOGUE_SYSTEM_PROMPT",
        "INSTINCT_SYSTEM_PROMPT", "CORE_PROTECTED_FILES", "SELF_REF_BRANCH_PREFIX",
        "UNIVERSE_DEFAULT_HARD_BOUNDARIES",
        # epic flags (formerly llm_epic_flags.py)
        "TRAJECTORY_ENABLED", "COST_BUDGET_ENABLED", "COST_BUDGET_CEILING_USD",
        "STEP_JOURNAL_ENABLED", "STEP_RESUME_ENABLED", "WORKTREE_ISOLATION_ENABLED",
        "DUAL_LEDGER_PLANNER_ENABLED", "INDEPENDENT_VERIFY_ENABLED", "EVIDENCE_RECEIPT_ENABLED",
        "BRAIN_JSON_RETRY_MAX", "STALL_THRESHOLD", "SOCIETY_ENABLED", "SOCIETY_MAX_WORKERS",
        "SOCIETY_DEBATE_MAX_ROUNDS", "SOCIETY_TOKEN_BUDGET_USD", "SOCIETY_ROLE_MODELS",
        "SOLUTION_FORK_ENABLED", "SOLUTION_FORK_N", "SOLUTION_FORK_MAX_CONCURRENCY",
        "SOLUTION_FORK_COST_CEILING_USD", "SOLUTION_FORK_BRANCH_COST_ESTIMATE_USD",
        "SOLUTION_FORK_GRAFT_ENABLED", "W_FACT", "W_RUBRIC", "W_RISK", "W_COST",
        "EXECUTION_FABRIC_ENABLED", "EXECUTION_BACKEND", "EXECUTION_BACKEND_BY_RISK",
        "DOCKER_EXECUTOR_IMAGE", "EXECUTION_REMOTE_KIND", "EXECUTION_REMOTE_HOST",
        "EXECUTION_PROVISION_TIMEOUT_SECONDS",
        # facade helpers + private compat
        "set_override", "validateEnv", "getLogger", "ensureDirs", "_SIE_BOUNDS",
        "_envInt", "_envFloat", "_envBool",
    ]
    missing = [n for n in names if not hasattr(config, n)]
    assert missing == [], f"legacy config names lost by the facade: {missing}"


# ---------------------------------------------------------------------------
# 3) set_override divergence regression
# ---------------------------------------------------------------------------

def test_set_override_updates_facade_and_registry_and_persists(tmp_path):
    ov = tmp_path / "sie_overrides.json"
    saved = app_settings._SETTINGS
    old_val = config.MAX_SUBTASK_ATTEMPTS
    new_val = 4 if old_val != 4 else 5
    # Re-point persistence at a temp file via a registry swap (frozen -> replace).
    cur = app_settings.settings()
    app_settings._SETTINGS = replace(cur, paths=replace(cur.paths, SIE_OVERRIDES_PATH=ov))
    try:
        assert config.set_override("MAX_SUBTASK_ATTEMPTS", new_val) is True
        # THE divergence regression: facade AND registry move together.
        assert config.MAX_SUBTASK_ATTEMPTS == new_val
        assert app_settings.settings().sie.MAX_SUBTASK_ATTEMPTS == new_val
        assert json.loads(ov.read_text(encoding="utf-8"))["MAX_SUBTASK_ATTEMPTS"] == new_val
    finally:
        app_settings._SETTINGS = saved


def test_set_override_refreshes_an_existing_module_shadow(tmp_path):
    """A prior setattr(config, knob, v) (test/e2e shadow) must not mask a live-tune."""
    ov = tmp_path / "sie_overrides.json"
    saved = app_settings._SETTINGS
    cur = app_settings.settings()
    app_settings._SETTINGS = replace(cur, paths=replace(cur.paths, SIE_OVERRIDES_PATH=ov))
    had_shadow = "RETRIEVAL_K" in vars(config)
    old_shadow = vars(config).get("RETRIEVAL_K")
    setattr(config, "RETRIEVAL_K", 7)
    try:
        assert config.set_override("RETRIEVAL_K", 9) is True
        assert config.RETRIEVAL_K == 9
        assert app_settings.settings().sie.RETRIEVAL_K == 9
    finally:
        app_settings._SETTINGS = saved
        if had_shadow:
            setattr(config, "RETRIEVAL_K", old_shadow)
        else:
            delattr(config, "RETRIEVAL_K")


def test_set_override_still_refuses_unknown_and_out_of_bounds():
    assert config.set_override("PROJECT_ROOT", "C:/evil") is False
    assert config.set_override("MAX_SUBTASK_ATTEMPTS", 9999) is False
    assert config.set_override("MAX_SUBTASK_ATTEMPTS", "garbage") is False


# ---------------------------------------------------------------------------
# 4) Model/effort routing defaults byte-identical (NO routing value changes)
# ---------------------------------------------------------------------------

def test_model_routing_defaults_byte_identical(monkeypatch):
    for k in ("MODEL_LOW", "MODEL_DEFAULT", "MODEL_MEDIUM", "MODEL_HIGH", "MODEL_XHIGH",
              "MODEL_ULTRACODE", "OLLAMA_MODEL"):
        monkeypatch.delenv(k, raising=False)
    from platform_core.app_config.llm import ClaudeCliCfg, OllamaCfg
    cli = ClaudeCliCfg()
    assert cli.PRIMARY_MODEL == "claude-opus-4-8"
    assert cli.FALLBACK_MODEL == "claude-sonnet-4-6"
    assert cli.MODEL_BY_EFFORT == {
        "low":       "claude-haiku-4-5-20251001",
        "default":   "claude-sonnet-4-6",
        "medium":    "claude-sonnet-4-6",
        "high":      "claude-sonnet-4-6",
        "xhigh":     "claude-opus-4-8",
        "ultracode": "claude-opus-4-8",
    }
    assert OllamaCfg().OLLAMA_MODEL == "qwen2.5-coder:7b"


# ---------------------------------------------------------------------------
# 5) reload() rebuilds from env (tests-only seam)
# ---------------------------------------------------------------------------

def test_reload_picks_up_env_changes(monkeypatch):
    saved = app_settings._SETTINGS
    monkeypatch.setenv("RETRIEVAL_MAX_TOKENS", "351")
    try:
        app_settings.reload()
        assert config.RETRIEVAL_MAX_TOKENS == 351
    finally:
        monkeypatch.delenv("RETRIEVAL_MAX_TOKENS", raising=False)
        app_settings._SETTINGS = saved
        app_settings._RUN_FLAGS = None
