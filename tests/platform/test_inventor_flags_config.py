"""Inventor Mega-Build config flags: additive-ON vs ship-dark defaults + facade exposure.

Mirrors tests/platform/test_epic_flags_config.py: coded defaults asserted on a fresh
InventorFlags() (env scrubbed), env overrides asserted by setting the env then rebuilding,
and facade exposure asserted on ``config.<NAME>``. Inventor defaults are independent of
FULL_STACK by design (additive features ON, behavior-changers DARK regardless).
"""
import config
from platform_core.app_config import settings
from platform_core.app_config.inventor_flags import InventorFlags

_ALL = (
    "NOVELTY_INDEX_ENABLED", "NOVELTY_DEDUP_THRESHOLD", "NOVELTY_FINDER_FLOOR",
    "INVENTION_CORPUS_ENABLED", "INVENTION_CORPUS_TOPK", "INVENTOR_MODE_ENABLED",
    "INVENTOR_EXPLORE_APPROACHES_ENABLED", "CODE_GRAPH_ENABLED", "PORTFOLIO_OPTIMIZER_ENABLED",
    "INVENTOR_EXCELLENCE_ENABLED", "INVENTOR_MODEL", "INVENTOR_RAW_IDEA_COUNT",
    "INVENTOR_FINAL_IDEA_COUNT", "INVENTOR_TEMPERATURE", "INVENTOR_TOP_P",
    "INVENTOR_DISCORD_TELEMETRY_ENABLED", "INVENTOR_DISCORD_FINALISTS_ENABLED",
    "QD_ARCHIVE_ENABLED", "QD_GENERATIONS_ENABLED", "QD_EMITTER_BANDIT_ENABLED",
    "QD_PARETO_CAP", "QD_PLATEAU_PATIENCE", "EMITTER_UCB_C", "SOLUTION_FORK_GENERATIONS",
    "SOLUTION_FORK_GEN_COST_CEILING_USD", "SOLUTION_FORK_GEN_WALLCLOCK_CEILING_SEC",
    "INVENTION_AUTONOMY", "INVENTION_AUTO_RUN_ENABLED", "INVENTION_AUTO_NOVELTY_MIN",
    "INVENTION_AUTO_CONFIDENCE_MIN", "INVENTION_AUTO_RISK_MAX",
)


def _clean(monkeypatch) -> InventorFlags:
    for k in _ALL:
        monkeypatch.delenv(k, raising=False)
    return InventorFlags()


def test_additive_features_default_on(monkeypatch):
    f = _clean(monkeypatch)
    assert f.NOVELTY_INDEX_ENABLED is True
    assert f.INVENTION_CORPUS_ENABLED is True
    assert f.CODE_GRAPH_ENABLED is True           # read-only analysis, safe
    assert f.PORTFOLIO_OPTIMIZER_ENABLED is True  # read-only selection, safe
    assert f.INVENTOR_EXPLORE_APPROACHES_ENABLED is True


def test_behavior_changers_ship_dark(monkeypatch):
    f = _clean(monkeypatch)
    assert f.INVENTOR_MODE_ENABLED is False
    assert f.INVENTOR_EXCELLENCE_ENABLED is False
    assert f.QD_ARCHIVE_ENABLED is False
    assert f.QD_GENERATIONS_ENABLED is False
    assert f.QD_EMITTER_BANDIT_ENABLED is False
    assert f.INVENTION_AUTO_RUN_ENABLED is False
    assert f.INVENTION_AUTONOMY == "proposal"     # safest routing by default
    assert f.SOLUTION_FORK_GENERATIONS == 1       # one-shot == today's behavior


def test_numeric_defaults(monkeypatch):
    f = _clean(monkeypatch)
    assert f.NOVELTY_DEDUP_THRESHOLD == 0.88
    assert f.NOVELTY_FINDER_FLOOR == 0.55
    assert f.INVENTION_CORPUS_TOPK == 3
    assert f.EMITTER_UCB_C == 1.4
    assert f.QD_PARETO_CAP == 4
    assert f.INVENTION_AUTO_NOVELTY_MIN == 0.75
    assert f.INVENTION_AUTO_CONFIDENCE_MIN == 0.80
    assert f.INVENTION_AUTO_RISK_MAX == "low"
    assert f.INVENTOR_MODEL == "qwen2.5:7b"
    assert f.INVENTOR_RAW_IDEA_COUNT == 18
    assert f.INVENTOR_FINAL_IDEA_COUNT == 6


def test_env_override_applies(monkeypatch):
    monkeypatch.setenv("NOVELTY_DEDUP_THRESHOLD", "0.5")
    monkeypatch.setenv("QD_ARCHIVE_ENABLED", "1")
    monkeypatch.setenv("INVENTION_AUTONOMY", "hybrid")
    f = InventorFlags()
    assert f.NOVELTY_DEDUP_THRESHOLD == 0.5
    assert f.QD_ARCHIVE_ENABLED is True
    assert f.INVENTION_AUTONOMY == "hybrid"


def test_autonomy_choice_rejects_garbage(monkeypatch):
    monkeypatch.setenv("INVENTION_AUTONOMY", "yolo")
    assert InventorFlags().INVENTION_AUTONOMY == "proposal"
    monkeypatch.setenv("INVENTION_AUTO_RISK_MAX", "nonsense")
    assert InventorFlags().INVENTION_AUTO_RISK_MAX == "low"


def test_flags_exposed_via_facade():
    assert isinstance(config.NOVELTY_INDEX_ENABLED, bool)
    assert isinstance(config.NOVELTY_DEDUP_THRESHOLD, float)
    assert isinstance(config.INVENTION_AUTONOMY, str)
    assert isinstance(config.SOLUTION_FORK_GENERATIONS, int)
    assert isinstance(config.EMITTER_UCB_C, float)
    assert isinstance(config.INVENTOR_EXCELLENCE_ENABLED, bool)
    assert isinstance(config.INVENTOR_MODEL, str)


def test_inventor_domain_registered_without_name_collision():
    # _nameMap() raises RuntimeError on a duplicate constant across domains.
    name_map = settings._nameMap()
    assert "inventor" in settings._DOMAINS
    assert name_map["NOVELTY_INDEX_ENABLED"] == "inventor"
    assert name_map["INVENTION_AUTONOMY"] == "inventor"
