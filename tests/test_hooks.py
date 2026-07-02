"""R7 guard-layer tests: hooks are REGISTERED (generated from one HOOKS_SPEC), guard hooks
fail CLOSED (any crash -> exit 2 / block), non-guard hooks stay fail-open (crash -> exit 0),
and the per-run settings generation can never lose the guard block.

Fail-closed matrix pinned here (hook x failure mode -> exit code):
  block_destructive        destructive cmd    -> 2
  block_destructive        benign cmd         -> 0
  block_destructive        malformed JSON     -> 2   (fail-closed regression guard)
  block_destructive        classifier crash   -> 2   (fail-closed regression guard)
  self_modification_guard  malformed JSON     -> 2
  log_all / unknown        malformed JSON     -> 0   (telemetry stays non-blocking)
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
HOOKS_PY = REPO / "agents" / "hooks.py"


@pytest.fixture(autouse=True)
def _guard_alerts_to_tmp(tmp_path, monkeypatch):
    """Route the fire-and-forget guard-alert JSONL to tmp for in-process tests."""
    monkeypatch.setenv("NINE_TO_FIVE_HOOK_CTX", json.dumps(
        {"guard_alerts": str(tmp_path / "guard_alerts.jsonl"),
         "log_path": str(tmp_path / "hooks.log")}))


def _runHook(hook: str, stdin_text: str, tmp_path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.pop("NINE_TO_FIVE_TASK_FILE", None)
    env.pop("NINE_TO_FIVE_TASK_ID", None)
    env["NINE_TO_FIVE_HOOK_CTX"] = json.dumps(
        {"guard_alerts": str(tmp_path / "guard_alerts.jsonl"),
         "log_path": str(tmp_path / "hooks.log")})
    return subprocess.run([sys.executable, str(HOOKS_PY), hook], input=stdin_text,
                          capture_output=True, text=True, env=env, cwd=str(REPO), timeout=120)


# ---------------------------------------------------------------------------
# Subprocess matrix: the REAL entrypoint Claude Code invokes.
# ---------------------------------------------------------------------------

def test_destructive_bash_blocks_rc2(tmp_path):
    ev = json.dumps({"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}})
    p = _runHook("block_destructive", ev, tmp_path)
    assert p.returncode == 2, p.stderr
    assert "Blocked destructive" in p.stderr


def test_benign_bash_allows_rc0(tmp_path):
    ev = json.dumps({"tool_name": "Bash", "tool_input": {"command": "pytest tests -q"}})
    p = _runHook("block_destructive", ev, tmp_path)
    assert p.returncode == 0, p.stderr


def test_malformed_event_json_fails_closed_rc2(tmp_path):
    p = _runHook("block_destructive", "this is {{{ not json", tmp_path)
    assert p.returncode == 2, p.stderr
    assert "failing CLOSED" in p.stderr


def test_malformed_event_selfmod_guard_fails_closed_rc2(tmp_path):
    p = _runHook("self_modification_guard", "]][ not json", tmp_path)
    assert p.returncode == 2, p.stderr


def test_malformed_event_nonguard_hook_stays_failopen_rc0(tmp_path):
    p = _runHook("log_all", "]][ not json", tmp_path)
    assert p.returncode == 0, p.stderr


def test_unknown_hook_rc0(tmp_path):
    p = _runHook("no_such_hook", "{}", tmp_path)
    assert p.returncode == 0, p.stderr


# ---------------------------------------------------------------------------
# In-process fail-closed: a crashing CLASSIFIER must block, not allow.
# ---------------------------------------------------------------------------

def test_classifier_crash_blocks_with_exit_2(monkeypatch):
    from agents import hooks_destructive

    def _boom(_action):
        raise RuntimeError("classifier exploded")

    monkeypatch.setattr(hooks_destructive, "classifyActionRisk", _boom)
    with pytest.raises(SystemExit) as ei:
        hooks_destructive.blockDestructive(
            {"tool_name": "Bash", "tool_input": {"command": "echo hi"}})
    assert ei.value.code == 2


def test_classifier_crash_writes_guard_alert(monkeypatch, tmp_path):
    from agents import hooks_destructive
    alerts = tmp_path / "guard_alerts.jsonl"
    monkeypatch.setattr(hooks_destructive, "classifyActionRisk",
                        lambda _a: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(SystemExit):
        hooks_destructive.blockDestructive(
            {"tool_name": "Bash", "tool_input": {"command": "echo hi"}})
    entry = json.loads(alerts.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert entry["hook"] == "block_destructive"
    assert "failing CLOSED" in entry["reason"]


def test_non_bash_tool_allows_even_with_broken_classifier(monkeypatch):
    """No Bash command present -> provably nothing to classify -> exit 0 (never reaches it)."""
    from agents import hooks_destructive
    monkeypatch.setattr(hooks_destructive, "classifyActionRisk",
                        lambda _a: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(SystemExit) as ei:
        hooks_destructive.blockDestructive({"tool_name": "Read", "tool_input": {}})
    assert ei.value.code == 0


def test_block_writes_guard_alert_jsonl_no_network(tmp_path):
    from agents.hooks_destructive import blockDestructive
    alerts = tmp_path / "guard_alerts.jsonl"
    with pytest.raises(SystemExit) as ei:
        blockDestructive({"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}})
    assert ei.value.code == 2
    entry = json.loads(alerts.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert entry["hook"] == "block_destructive" and "rm -rf" in entry["reason"]


# ---------------------------------------------------------------------------
# Registration: generated from HOOKS_SPEC, present in repo settings, drift-proof.
# ---------------------------------------------------------------------------

def test_hooks_spec_names_match_guard_hooks():
    from agents.executor_env import HOOKS_SPEC
    from agents.hooks import GUARD_HOOKS
    assert {name for _e, _m, name in HOOKS_SPEC} == set(GUARD_HOOKS)


def test_repo_settings_registers_guard_hooks_and_keeps_model_pin():
    from agents.executor_env import settingsHasGuardHooks
    data = json.loads((REPO / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert settingsHasGuardHooks(data), "guard hooks not registered in .claude/settings.json"
    assert data.get("model"), "model pin must remain untouched"
    assert data.get("permissions"), "permissions must remain untouched"


def test_compose_run_settings_always_injects_hooks(tmp_path):
    from agents.executor_env import composeRunSettingsDict, settingsHasGuardHooks
    bare = tmp_path / "settings.json"
    bare.write_text(json.dumps({"permissions": {"allow": ["Bash"]}, "hooks": {}}),
                    encoding="utf-8")
    merged = composeRunSettingsDict(bare)
    assert settingsHasGuardHooks(merged)
    assert merged["permissions"] == {"allow": ["Bash"]}  # non-hook keys pass through


def test_compose_run_settings_survives_missing_or_corrupt_base(tmp_path):
    from agents.executor_env import composeRunSettingsDict, settingsHasGuardHooks
    corrupt = tmp_path / "settings.json"
    corrupt.write_text("{{{ not json", encoding="utf-8")
    assert settingsHasGuardHooks(composeRunSettingsDict(corrupt))
    assert settingsHasGuardHooks(composeRunSettingsDict(tmp_path / "missing.json"))


def test_compose_run_settings_does_not_duplicate_existing_registration():
    from agents.executor_env import composeRunSettingsDict
    merged = composeRunSettingsDict(REPO / ".claude" / "settings.json")
    assert len(merged["hooks"]["PreToolUse"]) == 2  # already registered -> no duplicates


def test_compose_run_settings_writes_file(tmp_path):
    from agents.executor_env import composeRunSettings, settingsHasGuardHooks
    out = composeRunSettings(REPO / ".claude" / "settings.json",
                             tmp_path / "run_settings.json")
    assert settingsHasGuardHooks(json.loads(out.read_text(encoding="utf-8")))


def test_build_hook_ctx_env_round_trips():
    from agents.executor_env import buildHookCtxEnv
    ctx = json.loads(buildHookCtxEnv(boundaries=[".env", ".git"]))
    assert ctx["boundaries"] == [".env", ".git"]
    assert ctx["log_path"].endswith("hooks.log")
    assert ctx["guard_alerts"].endswith("guard_alerts.jsonl")


def test_hooks_source_has_no_hardcoded_log_path():
    src = HOOKS_PY.read_text(encoding="utf-8")
    assert r"C:\9to5\logs" not in src


def test_selfmod_merges_ctx_boundaries(monkeypatch):
    from agents import hooks_selfmod
    monkeypatch.setenv("NINE_TO_FIVE_HOOK_CTX",
                       json.dumps({"boundaries": ["super_secret_dir"]}))
    boundaries = hooks_selfmod._buildBoundaries(None, False, False)
    assert "super_secret_dir" in boundaries


# ---------------------------------------------------------------------------
# Health: registration drift is a HARD failure.
# ---------------------------------------------------------------------------

def test_health_hooks_check_passes_on_repo_settings(monkeypatch):
    import config
    from platform_core.ops import health
    monkeypatch.setattr(config, "CLAUDE_SETTINGS_PATH",
                        REPO / ".claude" / "settings.json", raising=False)
    ok, detail, _fix = health._hooks()
    assert ok, detail


def test_health_hooks_check_hard_fails_when_unregistered(tmp_path, monkeypatch):
    import config
    from platform_core.ops import health
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"model": "m", "hooks": {}}), encoding="utf-8")
    monkeypatch.setattr(config, "CLAUDE_SETTINGS_PATH", p, raising=False)
    ok, detail, _fix = health._hooks()
    assert not ok
    assert "NOT registered" in detail
