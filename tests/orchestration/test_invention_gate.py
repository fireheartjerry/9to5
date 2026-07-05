"""Hybrid-by-confidence autonomy gate: only the ideal + safe + non-self-referential auto-run."""
import pytest

import config
from platform_core.orchestration import invention_gate as ig


def _ideal(**over):
    d = dict(id="c", measured_novelty=0.9, confidence=0.9, risk="low", blast_bin="low",
             reversible=True, target_subsystems=["memory/x.py"], lineage={"emitter": "ollama"})
    d.update(over)
    return d


@pytest.fixture()
def auto_on(monkeypatch):
    monkeypatch.setattr(config, "INVENTION_AUTO_RUN_ENABLED", True, raising=False)
    monkeypatch.setattr(config, "INVENTION_AUTONOMY", "hybrid", raising=False)
    monkeypatch.setattr(config, "INVENTION_AUTO_NOVELTY_MIN", 0.75, raising=False)
    monkeypatch.setattr(config, "INVENTION_AUTO_CONFIDENCE_MIN", 0.80, raising=False)
    monkeypatch.setattr(config, "INVENTION_AUTO_RISK_MAX", "low", raising=False)


def test_default_is_proposal(monkeypatch):
    monkeypatch.setattr(config, "INVENTION_AUTO_RUN_ENABLED", False, raising=False)
    monkeypatch.setattr(config, "INVENTION_AUTONOMY", "proposal", raising=False)
    r = ig.routeInvention(_ideal())
    assert r["decision"] == "proposal"
    assert "auto_run_disabled" in r["reasons"]


def test_ideal_candidate_auto_runs(auto_on):
    r = ig.routeInvention(_ideal())
    assert r["decision"] == "auto_run"
    assert r["reasons"] == ["all_guards_passed"]
    assert r["lineage"] == {"emitter": "ollama"}


def test_low_confidence_is_proposal(auto_on):
    r = ig.routeInvention(_ideal(confidence=0.4))
    assert r["decision"] == "proposal"
    assert "confidence_below_min" in r["reasons"]


def test_low_novelty_is_proposal(auto_on):
    assert ig.routeInvention(_ideal(measured_novelty=0.3))["decision"] == "proposal"


def test_high_risk_is_proposal(auto_on):
    r = ig.routeInvention(_ideal(risk="high"))
    assert r["decision"] == "proposal"
    assert "risk_above_max" in r["reasons"]


def test_high_blast_is_proposal(auto_on):
    r = ig.routeInvention(_ideal(blast_bin="high"))
    assert r["decision"] == "proposal"
    assert "blast_not_low" in r["reasons"]


def test_not_reversible_is_proposal(auto_on):
    assert ig.routeInvention(_ideal(reversible=False))["decision"] == "proposal"


def test_destructive_is_proposal(auto_on):
    r = ig.routeInvention(_ideal(destructive=True))
    assert r["decision"] == "proposal"
    assert "destructive" in r["reasons"]


def test_self_referential_is_blocked(auto_on):
    r = ig.routeInvention(_ideal(target_subsystems=["platform_core/orchestration/execute_mixin.py"]))
    assert r["decision"] == "proposal"
    assert "self_referential" in r["reasons"]


def test_self_referential_flag_blocks(auto_on):
    assert ig.routeInvention(_ideal(is_self_referential=True))["decision"] == "proposal"


def test_auto_run_disabled_blocks_even_ideal(monkeypatch, auto_on):
    monkeypatch.setattr(config, "INVENTION_AUTO_RUN_ENABLED", False, raising=False)
    assert ig.routeInvention(_ideal())["decision"] == "proposal"


def test_is_self_referential_detects_core_files():
    assert ig.is_self_referential({"target_subsystems": ["config.py"]}) is True
    assert ig.is_self_referential({"target_subsystems": ["main.py"]}) is True
    assert ig.is_self_referential({"target_subsystems": ["memory/x.py"]}) is False
