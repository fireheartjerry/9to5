"""Generational fork selection: best-winner-across-generations + safe fallback (dark path)."""
from types import SimpleNamespace

import config
from platform_core.orchestration import fork_policy
from platform_core.orchestration import solution_space as ss


def _win(bid):
    return SimpleNamespace(branch_id=bid, worktree_path="")


def _install_fakes(monkeypatch, results):
    calls = {"n": 0}

    def fake_batch(*a, **k):
        r = results[min(calls["n"], len(results) - 1)]
        calls["n"] += 1
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(ss, "_competeBatch", fake_batch)
    monkeypatch.setattr(ss, "_genAngles", lambda b, s: ())
    monkeypatch.setattr(fork_policy, "forkPlan", lambda *a, **k: object())
    monkeypatch.setattr(ss, "_reclaimBatch", lambda *a, **k: None)
    return calls


def _run():
    return ss._bestAcrossGenerations(None, SimpleNamespace(meta={}), {}, "", ".", None, None,
                                     "sid", None, object(), object())


def test_generations_enabled_reflects_config(monkeypatch):
    monkeypatch.setattr(config, "QD_GENERATIONS_ENABLED", True, raising=False)
    monkeypatch.setattr(config, "SOLUTION_FORK_GENERATIONS", 3, raising=False)
    assert ss._generationsEnabled() is True
    monkeypatch.setattr(config, "SOLUTION_FORK_GENERATIONS", 1, raising=False)
    assert ss._generationsEnabled() is False           # 1 generation == today
    monkeypatch.setattr(config, "SOLUTION_FORK_GENERATIONS", 3, raising=False)
    monkeypatch.setattr(config, "QD_GENERATIONS_ENABLED", False, raising=False)
    assert ss._generationsEnabled() is False           # flag off


def test_flag_off_runs_single_batch(monkeypatch):
    monkeypatch.setattr(config, "QD_GENERATIONS_ENABLED", False, raising=False)
    calls = _install_fakes(monkeypatch, [(_win("g0"), [], 1.0)])
    winner, _ = _run()
    assert winner.branch_id == "g0"
    assert calls["n"] == 1                              # exactly one batch (byte-identical path)


def test_generational_picks_best_scoring_winner(monkeypatch):
    monkeypatch.setattr(config, "QD_GENERATIONS_ENABLED", True, raising=False)
    monkeypatch.setattr(config, "SOLUTION_FORK_GENERATIONS", 3, raising=False)
    calls = _install_fakes(monkeypatch, [
        (_win("g0"), [], 1.0), (_win("g1"), [], 3.0), (_win("g2"), [], 2.0)])
    winner, _ = _run()
    assert winner.branch_id == "g1"                     # highest score across generations
    assert calls["n"] == 3                              # ran all generations


def test_generational_falls_back_to_gen0_on_error(monkeypatch):
    monkeypatch.setattr(config, "QD_GENERATIONS_ENABLED", True, raising=False)
    monkeypatch.setattr(config, "SOLUTION_FORK_GENERATIONS", 3, raising=False)
    _install_fakes(monkeypatch, [(_win("g0"), [], 1.0), RuntimeError("boom")])
    winner, _ = _run()
    assert winner.branch_id == "g0"                     # never worse than a single batch


def test_branch_elite_marks_unmeasured_metrics_unknown():
    branch = SimpleNamespace(
        branch_id="b1",
        passed=True,
        seed=SimpleNamespace(angle_hint="minimal"),
        diff_lines=12,
        cost_usd=0.0,
        headline="VERIFIED",
    )
    elite = ss._branchElite(branch, {})
    assert elite is not None
    assert elite.metrics == {"verification_score": 1.0}
    assert set(elite.unknown_metrics) == {
        "impact_score",
        "maintainability_score",
        "adoption_score",
        "cost_efficiency_score",
        "reversibility_score",
        "measured_novelty",
        "risk_inverse",
    }
