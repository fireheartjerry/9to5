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

Merged (consolidation pass, tests/control sprawl reduction):
  - test_hooks_registration.py -- hook-registration parity + fail-closed dispatch (B8, B10)
  - test_hooks_self_path.py    -- hooks.py must add ITS OWN repo root to sys.path (R10)
"""
# NOTE: `from __future__ import annotations` must be the first statement after the module
# docstring (Python requirement) -- hoisted here from the merged test_hooks_registration.py.
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

import pytest

from agents import hooks

REPO = Path(__file__).resolve().parent.parent.parent
HOOKS_PY = REPO / "agents" / "hooks.py"


@pytest.fixture()
def _guard_alerts_to_tmp(tmp_path, monkeypatch):
    """Route the fire-and-forget guard-alert JSONL to tmp for in-process tests.

    NOTE: intentionally NOT autouse -- this module now also hosts tests merged in from
    test_hooks_registration.py and test_hooks_self_path.py that must NOT have
    NINE_TO_FIVE_HOOK_CTX silently injected (e.g. the self-path test asserts hooks.py's
    real config.LOG_PATH-derived default). Requested explicitly by the handful of
    in-process tests below that need it.
    """
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
                          capture_output=True, text=True, env=env, cwd=str(REPO), timeout=30)


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

def test_classifier_crash_blocks_with_exit_2(monkeypatch, _guard_alerts_to_tmp):
    from agents import hooks_destructive

    def _boom(_action):
        raise RuntimeError("classifier exploded")

    monkeypatch.setattr(hooks_destructive, "classifyActionRisk", _boom)
    with pytest.raises(SystemExit) as ei:
        hooks_destructive.blockDestructive(
            {"tool_name": "Bash", "tool_input": {"command": "echo hi"}})
    assert ei.value.code == 2


def test_classifier_crash_writes_guard_alert(monkeypatch, tmp_path, _guard_alerts_to_tmp):
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


def test_non_bash_tool_allows_even_with_broken_classifier(monkeypatch, _guard_alerts_to_tmp):
    """No Bash command present -> provably nothing to classify -> exit 0 (never reaches it)."""
    from agents import hooks_destructive
    monkeypatch.setattr(hooks_destructive, "classifyActionRisk",
                        lambda _a: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(SystemExit) as ei:
        hooks_destructive.blockDestructive({"tool_name": "Read", "tool_input": {}})
    assert ei.value.code == 0


def test_block_writes_guard_alert_jsonl_no_network(tmp_path, _guard_alerts_to_tmp):
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


def test_compose_run_settings_accepts_utf8_bom_base(tmp_path):
    from agents.executor_env import composeRunSettingsDict

    base = tmp_path / "settings.json"
    base.write_text(json.dumps({"model": "bom-model", "hooks": {}}), encoding="utf-8-sig")
    assert composeRunSettingsDict(base)["model"] == "bom-model"


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


# =============================================================================
# Merged from test_hooks_registration.py
# =============================================================================
"""Hook registration parity + fail-closed dispatch (B8, B10).

Guards against a future strip of ``.claude/settings.json`` (the "hooks": {} regression)
and proves a broken BLOCKING guard import fails CLOSED (exit 2), never OPEN (tool runs).
"""

_REPO_ROOT = Path(hooks.__file__).resolve().parent.parent
_SETTINGS = _REPO_ROOT / ".claude" / "settings.json"

# Hooks the dispatcher handles that fire on NON-tool events (Notification / UserPromptSubmit /
# Stop) and so are intentionally NOT part of the PreToolUse/PostToolUse tool-hook surface.
_EVENT_ONLY = {"discord_notify", "log_telemetry", "user_prompt_telemetry", "stop_telemetry"}


def _handledHooks() -> set:
    """Every hook name the dispatcher in agents/hooks.py handles."""
    src = Path(hooks.__file__).read_text(encoding="utf-8")
    names = set(hooks._BLOCKING_HOOKS)
    for m in re.finditer(r'hook_name == "([^"]+)"', src):
        names.add(m.group(1))
    for m in re.finditer(r"hook_name in \(([^)]*)\)", src):
        names.update(re.findall(r'"([^"]+)"', m.group(1)))
    return names


def _registeredHooks() -> set:
    """Every hook name registered in .claude/settings.json (last token of each command)."""
    data = json.loads(_SETTINGS.read_text(encoding="utf-8"))
    names: set = set()
    for groups in (data.get("hooks") or {}).values():
        for group in groups:
            for entry in group.get("hooks", []):
                cmd = entry.get("command", "")
                if "hooks.py" in cmd:
                    names.add(cmd.split()[-1])
    return names


def test_settings_json_is_valid_and_hooks_not_empty():
    assert _registeredHooks(), "settings.json has no hook registrations (stripped?)"


def test_no_dead_registration():
    # Every registered hook must be a hook the dispatcher actually handles.
    assert _registeredHooks() <= _handledHooks()


def test_tool_hook_surface_is_bidirectional():
    # Vice-versa: every tool-triggered hook the dispatcher handles is registered, and no extra.
    assert (_handledHooks() - _EVENT_ONLY) == _registeredHooks()


def test_blocking_guards_are_registered():
    reg = _registeredHooks()
    assert {"block_destructive", "self_modification_guard"} <= reg


@pytest.mark.parametrize("hook_name", ["block_destructive", "self_modification_guard"])
def test_broken_blocking_guard_import_fails_closed(monkeypatch, hook_name):
    def _boom(_name):
        raise ImportError("simulated broken guard sub-module")

    monkeypatch.setattr(hooks, "_importBlockingGuard", _boom)
    monkeypatch.setattr(sys, "argv", ["hooks.py", hook_name])
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    with pytest.raises(SystemExit) as ei:
        hooks.main()
    assert ei.value.code == 2  # fail CLOSED: block the tool call, do not exit 0


def test_broken_guard_exec_error_fails_closed(monkeypatch):
    def _explode(_data):
        raise RuntimeError("guard blew up mid-exec")

    monkeypatch.setattr(hooks, "_importBlockingGuard", lambda _n: _explode)
    monkeypatch.setattr(sys, "argv", ["hooks.py", "block_destructive"])
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    with pytest.raises(SystemExit) as ei:
        hooks.main()
    assert ei.value.code == 2


# =============================================================================
# Merged from test_hooks_self_path.py
# =============================================================================
"""hooks.py must add ITS OWN repo root to sys.path (derived from __file__), never a
hardcoded foreign install root -- otherwise a worktree imports the wrong tree (R10)."""


class TestHooksSelfPath(unittest.TestCase):
    def test_inserts_own_tree_root_not_a_hardcoded_path(self):
        own_root = str(Path(hooks.__file__).resolve().parent.parent)
        # the module's own repo root must be on sys.path (so it imports its OWN siblings)
        self.assertIn(own_root, [str(Path(p).resolve()) for p in sys.path if p])

    def test_source_does_not_hardcode_install_root_for_syspath(self):
        src = Path(hooks.__file__).read_text(encoding="utf-8")
        # The sys.path insert must NOT hardcode a literal drive path.
        self.assertNotIn('sys.path.insert(0, r"C:\\9to5")', src)
        self.assertNotIn("sys.path.insert(0, r'C:\\9to5')", src)

    def test_log_path_is_not_hardcoded_and_derives_from_config(self):
        # BUG-004: the hooks log target must not be a hardcoded C:\9to5 literal -- a relocated
        # install or a git worktree must log under its OWN config.LOG_PATH, not someone else's
        # install root. hooks.LOG_PATH was refactored into the _hooksLogPath() helper; test
        # the current API surface for the same guarantee.
        import config
        log_path = str(hooks._hooksLogPath())
        self.assertEqual(log_path, str(Path(config.LOG_PATH) / "hooks.log"))


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
