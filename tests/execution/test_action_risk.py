"""Pure action-risk taxonomy + authorization decider (Epic 4 unit a)."""

import pytest
from platform_core.runtime.action_risk import (
    RiskTier,
    ActionDescriptor,
    classifyActionRisk,
)


def A(tool_name="Bash", command="", file_path="", estimated_cost_usd=None):
    return ActionDescriptor(
        tool_name=tool_name, command=command, file_path=file_path, estimated_cost_usd=estimated_cost_usd
    )


# --- DESTRUCTIVE: the hard set, matched anywhere in the command, fail-closed first ---
@pytest.mark.parametrize(
    "cmd",
    [
        "rm -rf /tmp/x",
        "rm -fr build",
        "git push --force origin main",
        "git push -f",
        "DROP TABLE users;",
        "mkfs.ext4 /dev/sdb",
        "format c:",
        "del /f important.txt",
        ":(){ :|:& };:",
        "echo x >/dev/sda",
    ],
)
def test_destructive_patterns_are_destructive(cmd):
    assert classifyActionRisk(A(command=cmd)) is RiskTier.DESTRUCTIVE


def test_destructive_in_a_permitted_path_is_still_destructive():
    # defense-in-depth: a destructive op inside an in-bounds path is still risky
    assert classifyActionRisk(A(command="cd src && rm -rf node_modules")) is RiskTier.DESTRUCTIVE


def test_secret_family_target_is_destructive():
    assert classifyActionRisk(A(tool_name="Write", file_path="config/.env")) is RiskTier.DESTRUCTIVE
    assert classifyActionRisk(A(command="cat .env.production")) is RiskTier.DESTRUCTIVE


# --- R7b: a .env TARGET is destructive, but a mere textual MENTION (quoted string /
# heredoc body / commit message) is NOT -- the same anti-substring principle as prose. ---
def test_real_env_read_write_delete_stay_destructive():
    # .env as an actual command argument / redirect target must STILL block.
    for cmd in ("cat .env", "rm .env", "echo pwn > .env", "cp config.py .env", "grep SECRET .env.production"):
        assert classifyActionRisk(A(command=cmd)) is RiskTier.DESTRUCTIVE, cmd


@pytest.mark.parametrize(
    "cmd",
    [
        'git commit -m "config: a live .env pinning a flag wins"',  # .env only in the message
        "cat > tests/x.py <<'EOF'\n# a live .env pinning a flag\nEOF",  # .env only in heredoc body
        'echo \'{"file_path":".env"}\' | node check.mjs',  # .env only in a single-quoted arg
        "python -c \"print('sample: echo x > .env')\"",  # .env only inside a -c string
    ],
)
def test_env_mention_in_quotes_or_heredoc_is_not_destructive(cmd):
    """A command that only MENTIONS .env inside a quoted string or heredoc body -- never
    reads/writes the file -- must not classify DESTRUCTIVE (mirrors the prose principle)."""
    assert classifyActionRisk(A(command=cmd)) is not RiskTier.DESTRUCTIVE


def test_grep_pattern_containing_env_is_not_a_secret_read():
    """self_modification_guard shares bashReadsSecret: grepping a NORMAL file for the string
    '.env' must not be mistaken for reading the secret file itself."""
    from platform_core.runtime.action_risk import bashReadsSecret

    assert not bashReadsSecret('grep -n "\\.env" tests/execution/test_action_risk.py')
    assert not bashReadsSecret('git commit -m "note about .env handling"')
    # real secret reads still detected (unquoted .env argument):
    assert bashReadsSecret("cat .env")
    assert bashReadsSecret("grep SECRET .env.production")


# --- R7: anchored command-position taxonomy (ONE source for hooks + executor pre-scan) ---
@pytest.mark.parametrize(
    "cmd",
    [
        "sudo rm -rf /",
        "doas rm -rf /home",
        "echo hi && rm -rf /tmp/x",
        "ls; rmdir /s foo",
        "true | del /s q",
        "first line\nrm -rf ~",
        "cd /x; sudo mkfs /dev/sdb",
    ],
)
def test_destructive_with_privilege_prefix_or_chaining_is_destructive(cmd):
    assert classifyActionRisk(A(command=cmd)) is RiskTier.DESTRUCTIVE


@pytest.mark.parametrize(
    "cmd",
    [
        "please format the output nicely",  # 'format ' substring, prose
        "explain what the del /s flag does",  # 'del /s' substring, prose
        "the docs mention rm -rf as an example",  # 'rm -rf' substring, prose
        "perform a git push to main",  # no force flag
    ],
)
def test_prose_containing_pattern_words_is_not_destructive(cmd):
    """The substring false-positive class is gone: pattern words in prose never classify
    DESTRUCTIVE (they may still be MUTATING via write-verb markers -- that does not block)."""
    assert classifyActionRisk(A(command=cmd)) is not RiskTier.DESTRUCTIVE


def test_scan_destructive_is_the_one_shared_source():
    """Both enforcement layers consume the SAME scanner object (dual enforcement, one taxonomy)."""
    from platform_core.runtime.action_risk import scanDestructive
    from agents.executor_env import scanDestructive as env_scan

    assert env_scan is scanDestructive
    assert scanDestructive("sudo rm -rf /") == ["rm -rf"]
    assert scanDestructive("please format the output nicely") == []


def test_selfmod_helpers_come_from_the_shared_taxonomy():
    from platform_core.runtime.action_risk import bashReadsSecret, isWritingBash

    assert bashReadsSecret("cat .env")
    assert bashReadsSecret("grep SECRET .env.production")
    assert not bashReadsSecret("cat .envrc")
    assert not bashReadsSecret("echo hello")
    assert isWritingBash("echo x > out.txt")
    assert isWritingBash("git reset --hard HEAD")
    assert not isWritingBash("ls -la")


# --- READ / DRY_RUN ---
@pytest.mark.parametrize("tool", ["Read", "Glob", "Grep", "NotebookRead"])
def test_read_tools_are_read(tool):
    assert classifyActionRisk(A(tool_name=tool)) is RiskTier.READ


@pytest.mark.parametrize("cmd", ["ls -la", "pytest tests/ -q", "cat README.md", "grep foo *.py"])
def test_read_only_bash_is_read(cmd):
    assert classifyActionRisk(A(command=cmd)) is RiskTier.READ


@pytest.mark.parametrize(
    "cmd",
    [
        "git status",
        "git diff HEAD~1",
        "git log --oneline",
        "terraform plan --dry-run",
        "npm install --dry-run",
    ],
)
def test_dry_run_bash_is_dry_run(cmd):
    assert classifyActionRisk(A(command=cmd)) is RiskTier.DRY_RUN


# --- MUTATING ---
@pytest.mark.parametrize("tool", ["Edit", "Write", "MultiEdit"])
def test_file_tools_with_path_are_mutating(tool):
    assert classifyActionRisk(A(tool_name=tool, file_path="src/app.py")) is RiskTier.MUTATING


@pytest.mark.parametrize(
    "cmd",
    [
        "echo hi > out.txt",
        "sed -i 's/a/b/' f.py",
        "mv a b",
        "cp a b",
        "tee log.txt",
        "git checkout main",
        "git reset --hard HEAD",
    ],
)
def test_writing_bash_is_mutating(cmd):
    assert classifyActionRisk(A(command=cmd)) is RiskTier.MUTATING


# --- PAID ---
def test_claude_run_is_paid():
    assert classifyActionRisk(A(tool_name="ClaudeRun", command="")) is RiskTier.PAID


def test_destructive_prompt_in_claude_run_overrides_paid():
    # a paid Claude attempt whose implied command is destructive must classify DESTRUCTIVE
    assert classifyActionRisk(A(tool_name="ClaudeRun", command="rm -rf /")) is RiskTier.DESTRUCTIVE


# --- UNKNOWN: fail-closed sentinel ---
def test_unrecognized_tool_is_unknown():
    assert classifyActionRisk(A(tool_name="SomeMcpThing", command="")) is RiskTier.UNKNOWN


def test_file_tool_without_path_is_unknown():
    assert classifyActionRisk(A(tool_name="Edit", file_path="")) is RiskTier.UNKNOWN


def test_empty_bash_is_unknown():
    assert classifyActionRisk(A(tool_name="Bash", command="   ")) is RiskTier.UNKNOWN


# --- B27: fail-closed ordering -- a write signal beats a dry-run marker ---
@pytest.mark.parametrize(
    "cmd",
    [
        "rm foo.txt --dry-run",  # rm is a write verb; --dry-run must NOT downgrade it
        "git checkout main --dry-run",  # git checkout mutates the tree
        "mv a b --check",  # mv + a dry-run-ish marker
        "sed -i 's/a/b/' f.py --dry-run",
    ],
)
def test_mutating_bash_with_dry_run_marker_stays_mutating(cmd):
    assert classifyActionRisk(A(command=cmd)) is RiskTier.MUTATING


from platform_core.runtime.action_risk import decideAuthorization


def D(action, allowance=0.0, spent=0.0, autonomous=False):
    return decideAuthorization(
        action, allowance_usd=allowance, already_spent_usd=spent, autonomous=autonomous
    )


def test_read_auto_authorizes_never_escalates():
    d = D(A(tool_name="Read"))
    assert d.auto_authorize and not d.escalate
    assert d.tier is RiskTier.READ and d.metered_cost_usd is None


def test_dry_run_auto_authorizes():
    d = D(A(command="git diff"))
    assert d.auto_authorize and not d.escalate and d.tier is RiskTier.DRY_RUN


def test_destructive_always_escalates_no_cap_buys_past_it():
    d = D(A(command="rm -rf /"), allowance=1_000_000.0, spent=0.0)
    assert d.escalate and not d.auto_authorize
    assert d.tier is RiskTier.DESTRUCTIVE
    assert d.reason.startswith("destructive-requires-human")


def test_unknown_routes_identically_to_destructive():
    d = D(A(tool_name="MysteryTool"), allowance=1_000_000.0)
    assert d.escalate and not d.auto_authorize and d.tier is RiskTier.UNKNOWN
    assert d.reason.startswith("unknown-requires-human")


def test_mutating_within_allowance_auto_meters_cost():
    d = D(A(tool_name="Edit", file_path="a.py", estimated_cost_usd=0.10), allowance=1.00, spent=0.50)
    assert d.auto_authorize and not d.escalate
    assert d.reason == "within-allowance" and d.metered_cost_usd == 0.10


def test_mutating_over_allowance_escalates():
    d = D(A(tool_name="Edit", file_path="a.py", estimated_cost_usd=0.60), allowance=1.00, spent=0.50)
    assert d.escalate and not d.auto_authorize and d.reason == "over-allowance"


def test_paid_unknown_cost_escalates():
    d = D(A(tool_name="ClaudeRun", estimated_cost_usd=None), allowance=100.0)
    assert d.escalate and d.reason == "unknown-cost" and d.tier is RiskTier.PAID


def test_zero_allowance_means_confirm_everything_for_paid():
    d = D(A(tool_name="ClaudeRun", estimated_cost_usd=0.01), allowance=0.0)
    assert d.escalate and d.reason == "over-allowance"


def test_autonomous_flag_annotates_escalation_reason():
    gated = D(A(command="rm -rf /"), autonomous=False)
    auton = D(A(command="rm -rf /"), autonomous=True)
    assert auton.reason.endswith("-autonomous")
    assert not gated.reason.endswith("-autonomous")


def test_safety_config_defaults_ship_dark(monkeypatch):
    # R12: assert the CODED defaults (env scrubbed) -- a production install .env may
    # legitimately enable the semantic-safety layer / grant an allowance.
    import config

    for k in (
        "SEMANTIC_SAFETY_ENABLED",
        "AUTONOMY_ALLOWANCE_USD",
        "AUTONOMOUS_DESTRUCTIVE_POLICY",
        "AUTONOMOUS_DESTRUCTIVE_ALLOWANCE_USD",
        "CLAUDE_ATTEMPT_COST_HINT_USD",
    ):
        monkeypatch.delenv(k, raising=False)
    from platform_core.app_config.llm import buildSieCfg

    sie = buildSieCfg()
    assert sie.SEMANTIC_SAFETY_ENABLED is False  # ship dark
    assert sie.AUTONOMY_ALLOWANCE_USD == 0.0  # confirm-everything
    assert sie.AUTONOMOUS_DESTRUCTIVE_POLICY == "block"  # fail-closed default
    assert sie.AUTONOMOUS_DESTRUCTIVE_ALLOWANCE_USD == 0.0
    assert sie.CLAUDE_ATTEMPT_COST_HINT_USD == 0.0
    # Facade exposure stays live (env-layered).
    assert isinstance(config.SEMANTIC_SAFETY_ENABLED, bool)
    assert isinstance(config.AUTONOMY_ALLOWANCE_USD, float)


def test_controlbus_has_action_risk_gate_and_spend_default(tmp_path, monkeypatch):
    import config
    from platform_core.runtime.control import ControlBus, GATES

    monkeypatch.setattr(config, "CONTROL_DIR", tmp_path, raising=False)
    assert "action_risk" in GATES
    bus = ControlBus("task-epic4")
    data = bus.load()
    assert data["decisions"]["action_risk"] is None
    assert data["autonomy_spent_usd"] == 0.0
    bus.decide("action_risk", "approve")
    assert bus.getDecision("action_risk") == "approve"


def test_mutating_bash_with_dry_run_marker_is_not_auto_authorized():
    # B27 end-to-end: the mutating classification must route to escalation, never auto-authorize.
    d = D(A(command="rm foo.txt --dry-run"), allowance=1_000_000.0)
    assert not d.auto_authorize and d.escalate
    assert d.tier is RiskTier.MUTATING


# B30's file-lock-era clear() test is obsolete: ControlBus.clear() now delegates to
# control_store.clearTask() (a single SQLite transaction, no _fileLock to spy on). The
# guarantee it checked -- a full reset, including the ledger -- is covered under the new
# backend by tests/control/test_control_store.py::test_ledger_wiped_only_by_explicit_full_clear.
