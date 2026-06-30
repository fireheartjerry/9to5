"""Pure action-risk taxonomy + authorization decider (Epic 4 unit a)."""
import pytest
from platform_core.runtime.action_risk import (
    RiskTier, ActionDescriptor, classifyActionRisk,
)


def A(tool_name="Bash", command="", file_path="", estimated_cost_usd=None):
    return ActionDescriptor(tool_name=tool_name, command=command,
                            file_path=file_path, estimated_cost_usd=estimated_cost_usd)


# --- DESTRUCTIVE: the hard set, matched anywhere in the command, fail-closed first ---
@pytest.mark.parametrize("cmd", [
    "rm -rf /tmp/x", "rm -fr build", "git push --force origin main", "git push -f",
    "DROP TABLE users;", "mkfs.ext4 /dev/sdb", "format c:", "del /f important.txt",
    ":(){ :|:& };:", "echo x >/dev/sda",
])
def test_destructive_patterns_are_destructive(cmd):
    assert classifyActionRisk(A(command=cmd)) is RiskTier.DESTRUCTIVE


def test_destructive_in_a_permitted_path_is_still_destructive():
    # defense-in-depth: a destructive op inside an in-bounds path is still risky
    assert classifyActionRisk(A(command="cd src && rm -rf node_modules")) is RiskTier.DESTRUCTIVE


def test_secret_family_target_is_destructive():
    assert classifyActionRisk(A(tool_name="Write", file_path="config/.env")) is RiskTier.DESTRUCTIVE
    assert classifyActionRisk(A(command="cat .env.production")) is RiskTier.DESTRUCTIVE


# --- READ / DRY_RUN ---
@pytest.mark.parametrize("tool", ["Read", "Glob", "Grep", "NotebookRead"])
def test_read_tools_are_read(tool):
    assert classifyActionRisk(A(tool_name=tool)) is RiskTier.READ


@pytest.mark.parametrize("cmd", ["ls -la", "pytest tests/ -q", "cat README.md", "grep foo *.py"])
def test_read_only_bash_is_read(cmd):
    assert classifyActionRisk(A(command=cmd)) is RiskTier.READ


@pytest.mark.parametrize("cmd", [
    "git status", "git diff HEAD~1", "git log --oneline",
    "terraform plan --dry-run", "npm install --dry-run",
])
def test_dry_run_bash_is_dry_run(cmd):
    assert classifyActionRisk(A(command=cmd)) is RiskTier.DRY_RUN


# --- MUTATING ---
@pytest.mark.parametrize("tool", ["Edit", "Write", "MultiEdit"])
def test_file_tools_with_path_are_mutating(tool):
    assert classifyActionRisk(A(tool_name=tool, file_path="src/app.py")) is RiskTier.MUTATING


@pytest.mark.parametrize("cmd", [
    "echo hi > out.txt", "sed -i 's/a/b/' f.py", "mv a b", "cp a b",
    "tee log.txt", "git checkout main", "git reset --hard HEAD",
])
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


from platform_core.runtime.action_risk import decideAuthorization


def D(action, allowance=0.0, spent=0.0, autonomous=False):
    return decideAuthorization(action, allowance_usd=allowance,
                               already_spent_usd=spent, autonomous=autonomous)


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
    d = D(A(tool_name="Edit", file_path="a.py", estimated_cost_usd=0.10),
          allowance=1.00, spent=0.50)
    assert d.auto_authorize and not d.escalate
    assert d.reason == "within-allowance" and d.metered_cost_usd == 0.10


def test_mutating_over_allowance_escalates():
    d = D(A(tool_name="Edit", file_path="a.py", estimated_cost_usd=0.60),
          allowance=1.00, spent=0.50)
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


def test_safety_config_defaults_ship_dark():
    import config
    assert config.SEMANTIC_SAFETY_ENABLED is False          # ship dark
    assert config.AUTONOMY_ALLOWANCE_USD == 0.0             # confirm-everything
    assert config.AUTONOMOUS_DESTRUCTIVE_POLICY == "block"  # fail-closed default
    assert isinstance(config.AUTONOMOUS_DESTRUCTIVE_ALLOWANCE_USD, float)
    assert isinstance(config.CLAUDE_ATTEMPT_COST_HINT_USD, float)
