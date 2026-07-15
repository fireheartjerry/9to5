# tests/test_durable_config.py
# tests/test_epic2_config.py
# tests/test_solution_fork_config.py
"""Epic config knobs ship dark (or with their locked defaults) -- consolidated.

Merges the three former per-epic files (Epic 1 durable-execution, Epic 2
staged-default, Epic 6 solution-fork) since they all exercise the same
subject module: platform_core.app_config.settings.EpicFlags + its config.py
facade exposure.

R12: the registry now genuinely layers .env over the coded defaults, and a
production install .env may legitimately enable/flip these flags -- so the
ships-dark / default-on / default-off guarantees are asserted on the CODED
defaults (env keys scrubbed), while the facade exposure is asserted on the
live values.
"""
import config
from platform_core.app_config import settings as config_settings
from platform_core.app_config.settings import EpicFlags


# ---------------------------------------------------------------------------
# Epic 1: durable-execution config flags (tests/test_durable_config.py)
# ---------------------------------------------------------------------------

def test_galaxy_zero_cost_policy_is_frozen_off_even_when_env_requests_spend(monkeypatch):
    monkeypatch.setenv("EXTERNAL_SPEND_ALLOWED", "1")
    flags = EpicFlags()
    assert flags.EXTERNAL_SPEND_ALLOWED is False


def test_galaxy_shadow_policy_enforcement_ships_dark(monkeypatch):
    monkeypatch.delenv("GALAXY_R3_POLICY_ENFORCEMENT_ENABLED", raising=False)
    assert EpicFlags().GALAXY_R3_POLICY_ENFORCEMENT_ENABLED is False
    assert isinstance(config.GALAXY_R3_POLICY_ENFORCEMENT_ENABLED, bool)


def test_galaxy_policy_enforcement_blocks_unwarranted_behavior_flags(monkeypatch):
    with monkeypatch.context() as scoped:
        scoped.setenv("FULL_STACK", "1")
        scoped.setenv("GALAXY_R3_POLICY_ENFORCEMENT_ENABLED", "1")
        for name in (
            "HUMAN_NATURE_ENABLED",
            "SOCIETY_ENABLED",
            "SOLUTION_FORK_ENABLED",
            "EXECUTION_FABRIC_ENABLED",
            "SIE_AUTO_MAINTENANCE",
            "SIE_FORCE_WEEKLY",
            "SIE_AUTHORING_CONTEXT",
            "ENABLE_PRE_EXECUTION_COUNCIL",
            "PRE_EXECUTION_COUNCIL_LIVE_GPT_ENABLED",
        ):
            scoped.setenv(name, "1")
        config.reload()
        assert all(
            config_settings.lookup(name) is False
            for name in (
                "HUMAN_NATURE_ENABLED",
                "SOCIETY_ENABLED",
                "SOLUTION_FORK_ENABLED",
                "EXECUTION_FABRIC_ENABLED",
                "SIE_AUTO_MAINTENANCE",
                "SIE_FORCE_WEEKLY",
                "SIE_AUTHORING_CONTEXT",
                "ENABLE_PRE_EXECUTION_COUNCIL",
                "PRE_EXECUTION_COUNCIL_LIVE_GPT_ENABLED",
            )
        )
    config.reload()


def test_galaxy_shadow_mode_preserves_incumbent_full_stack_flags(monkeypatch):
    with monkeypatch.context() as scoped:
        scoped.setenv("FULL_STACK", "1")
        scoped.setenv("GALAXY_R3_POLICY_ENFORCEMENT_ENABLED", "0")
        for name in (
            "HUMAN_NATURE_ENABLED",
            "SOCIETY_ENABLED",
            "SOLUTION_FORK_ENABLED",
            "EXECUTION_FABRIC_ENABLED",
            "SIE_FORCE_WEEKLY",
        ):
            scoped.setenv(name, "1")
        config.reload()
        assert config_settings.lookup("HUMAN_NATURE_ENABLED") is True
        assert config_settings.lookup("SOCIETY_ENABLED") is True
        assert config_settings.lookup("SOLUTION_FORK_ENABLED") is True
        assert config_settings.lookup("EXECUTION_FABRIC_ENABLED") is True
        assert config_settings.lookup("SIE_FORCE_WEEKLY") is True
    config.reload()

def test_epic1_flag_defaults(monkeypatch):
    monkeypatch.setenv("FULL_STACK", "0")   # master off -> assert the conservative ship-dark fallback
    for k in ("TRAJECTORY_ENABLED", "STEP_JOURNAL_ENABLED", "STEP_RESUME_ENABLED",
              "WORKTREE_ISOLATION_ENABLED", "COST_BUDGET_ENABLED", "COST_BUDGET_CEILING_USD"):
        monkeypatch.delenv(k, raising=False)
    flags = EpicFlags()   # coded defaults < (no env)
    # Additive observability: on by default (zero behavior change).
    assert flags.TRAJECTORY_ENABLED is True
    assert flags.STEP_JOURNAL_ENABLED is True
    # Behavior-changing units ship dark: OFF by default.
    assert flags.STEP_RESUME_ENABLED is False
    assert flags.WORKTREE_ISOLATION_ENABLED is False
    assert flags.COST_BUDGET_ENABLED is False
    assert flags.COST_BUDGET_CEILING_USD == 0.0   # 0 = no ceiling


def test_epic1_flags_exposed_via_facade():
    for name in ("TRAJECTORY_ENABLED", "STEP_JOURNAL_ENABLED", "STEP_RESUME_ENABLED",
                 "WORKTREE_ISOLATION_ENABLED", "COST_BUDGET_ENABLED"):
        assert isinstance(getattr(config, name), bool)
    assert isinstance(config.COST_BUDGET_CEILING_USD, float)


# ---------------------------------------------------------------------------
# Epic 2: staged-default config knobs (tests/test_epic2_config.py)
# ---------------------------------------------------------------------------

def _cleanFlags(monkeypatch) -> EpicFlags:
    for k in ("DUAL_LEDGER_PLANNER_ENABLED", "INDEPENDENT_VERIFY_ENABLED",
              "EVIDENCE_RECEIPT_ENABLED", "BRAIN_JSON_RETRY_MAX", "STALL_THRESHOLD"):
        monkeypatch.delenv(k, raising=False)
    return EpicFlags()


def test_dual_ledger_default_off(monkeypatch):
    monkeypatch.setenv("FULL_STACK", "0")   # master off -> assert the conservative ship-dark fallback
    assert _cleanFlags(monkeypatch).DUAL_LEDGER_PLANNER_ENABLED is False


def test_independent_verify_default_on(monkeypatch):
    assert _cleanFlags(monkeypatch).INDEPENDENT_VERIFY_ENABLED is True


def test_evidence_receipt_default_on(monkeypatch):
    assert _cleanFlags(monkeypatch).EVIDENCE_RECEIPT_ENABLED is True


def test_retry_and_stall_ints(monkeypatch):
    flags = _cleanFlags(monkeypatch)
    assert flags.BRAIN_JSON_RETRY_MAX == 2
    assert flags.STALL_THRESHOLD == 2


def test_epic2_knobs_exposed_via_facade():
    assert isinstance(config.DUAL_LEDGER_PLANNER_ENABLED, bool)
    assert isinstance(config.INDEPENDENT_VERIFY_ENABLED, bool)
    assert isinstance(config.EVIDENCE_RECEIPT_ENABLED, bool)
    assert isinstance(config.BRAIN_JSON_RETRY_MAX, int)
    assert isinstance(config.STALL_THRESHOLD, int)


# ---------------------------------------------------------------------------
# Epic 6: solution-fork config knobs (tests/test_solution_fork_config.py)
# ---------------------------------------------------------------------------

def test_fork_ships_dark_with_locked_defaults(monkeypatch):
    monkeypatch.setenv("FULL_STACK", "0")   # master off -> assert the conservative ship-dark fallback
    for k in ("SOLUTION_FORK_ENABLED", "SOLUTION_FORK_N", "SOLUTION_FORK_MAX_CONCURRENCY",
              "SOLUTION_FORK_COST_CEILING_USD", "SOLUTION_FORK_GRAFT_ENABLED"):
        monkeypatch.delenv(k, raising=False)
    flags = EpicFlags()
    assert flags.SOLUTION_FORK_ENABLED is False          # ships dark
    assert flags.SOLUTION_FORK_N == 2                    # locked: default 2 branches
    assert flags.SOLUTION_FORK_MAX_CONCURRENCY == 2
    assert flags.SOLUTION_FORK_COST_CEILING_USD == 5.0
    assert flags.SOLUTION_FORK_GRAFT_ENABLED is False
    assert isinstance(config.SOLUTION_FORK_ENABLED, bool)   # facade exposure


def test_judge_weights_present_and_normalized_to_one():
    total = config.W_FACT + config.W_RUBRIC + config.W_RISK + config.W_COST
    assert abs(total - 1.0) < 1e-9
    assert config.W_FACT >= config.W_RUBRIC   # facts outweigh opinion


# ---------------------------------------------------------------------------
# Human-Nature layer: behaviour-coupling config knobs (tests/test_hn_config.py)
# ---------------------------------------------------------------------------

def test_human_nature_flags_default_off(monkeypatch):
    monkeypatch.setenv("FULL_STACK", "0")   # master off -> assert the conservative ship-dark fallback
    for k in ("HUMAN_NATURE_ENABLED", "HN_OPINIONS_BEHAVIOR",
              "HN_EMOTIONS_BEHAVIOR", "HN_INTUITION_SHORTCUT"):
        monkeypatch.delenv(k, raising=False)
    flags = EpicFlags()   # coded defaults < (no env)
    assert flags.HUMAN_NATURE_ENABLED is False
    assert flags.HN_OPINIONS_BEHAVIOR is False
    assert flags.HN_EMOTIONS_BEHAVIOR is False
    assert flags.HN_INTUITION_SHORTCUT is False


def test_human_nature_thresholds_and_paths_present():
    assert config.HN_THETA_HARD > config.HN_THETA_SOFT
    assert config.HN_RECAL_TEMPERATURE > 1.0
    assert str(config.CONVICTION_DB_PATH).endswith("conviction.db")
    assert str(config.AB_HARNESS_DB_PATH).endswith("ab_runs.db")


# ---------------------------------------------------------------------------
# Elaborator excellence tier: foundation config flags
# ---------------------------------------------------------------------------

def test_elaborator_excellence_ships_dark(monkeypatch):
    monkeypatch.setenv("FULL_STACK", "0")
    monkeypatch.delenv("ELABORATOR_EXCELLENCE_ENABLED", raising=False)
    flags = EpicFlags()
    assert flags.ELABORATOR_EXCELLENCE_ENABLED is False


def test_elaborator_excellence_facade_exposed():
    # config.__getattr__ delegates to the live registry (PEP 562).
    assert hasattr(config, "ELABORATOR_EXCELLENCE_ENABLED")


def test_phase234_elaborator_flags_ship_dark(monkeypatch):
    monkeypatch.setenv("FULL_STACK", "0")
    for k in ("ELABORATOR_PRECEDENT_ENABLED", "ELABORATOR_BESTOFN_ENABLED",
              "ELABORATOR_LOOKAHEAD_ENABLED", "ELABORATOR_DEFER_ENABLED",
              "ELABORATOR_CANDIDATES_MAX"):
        monkeypatch.delenv(k, raising=False)
    flags = EpicFlags()
    assert flags.ELABORATOR_PRECEDENT_ENABLED is False
    assert flags.ELABORATOR_BESTOFN_ENABLED is False
    assert flags.ELABORATOR_LOOKAHEAD_ENABLED is False
    assert flags.ELABORATOR_DEFER_ENABLED is False
    assert flags.ELABORATOR_CANDIDATES_MAX == 5


def test_elaborator_defer_model_inert_by_default(monkeypatch):
    monkeypatch.delenv("ELABORATOR_DEFER_MODEL", raising=False)
    assert EpicFlags().ELABORATOR_DEFER_MODEL == ""
