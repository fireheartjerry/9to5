"""Emitter scheduler: UCB value, flow allocation under hard caps, cheap-vs-deep selection."""
from platform_core.orchestration import emitter_scheduler as es


def test_ucb_optimistic_for_unpulled():
    u = es.UCB(c=1.0)
    assert u.score("claude") == 1.0            # never tried -> explore
    u.update("claude", 0.2)
    assert u.score("claude") < 1.0             # now reflects the low observed reward


def test_ucb_reflects_mean_reward():
    u = es.UCB(c=0.0)                            # no exploration term
    u.update("ollama", 1.0)
    u.update("ollama", 1.0)
    assert abs(u.score("ollama") - 1.0) < 1e-9


def _total(allocs):
    return sum(a.budget["forks"] for a in allocs)


def test_allocation_never_exceeds_budget():
    cells = [{"key": "a", "qd_gain": 0.9}, {"key": "b", "qd_gain": 0.9}]
    allocs = es.allocate(["ollama", "claude"], cells, fork_budget=2)
    assert _total(allocs) <= 2


def test_scarce_budget_goes_to_highest_qd_gain():
    cells = [{"key": "hi", "qd_gain": 0.9}, {"key": "lo", "qd_gain": 0.1}]
    allocs = es.allocate(["ollama"], cells, fork_budget=1)
    assert _total(allocs) == 1
    assert allocs[0].target_cell == "hi"


def test_rare_cell_receives_exploration_when_valuable():
    cells = [{"key": "common", "qd_gain": 0.2, "rarity": 0.0},
             {"key": "rare", "qd_gain": 0.2, "rarity": 0.8}]
    allocs = es.allocate(["ollama"], cells, fork_budget=1)
    assert allocs[0].target_cell == "rare"      # rarity bonus wins the single slot


def test_cheap_emitter_preferred_then_deep_when_capacity_exhausted():
    cells = [{"key": "a", "qd_gain": 0.9}, {"key": "b", "qd_gain": 0.9}]
    # ollama can only take 1 fork; budget 2 -> the 2nd beneficial slot must go to claude.
    allocs = es.allocate(["ollama", "claude"], cells, fork_budget=2,
                         emitter_caps={"ollama": 1})
    emitters = {a.emitter for a in allocs}
    assert "ollama" in emitters
    assert "claude" in emitters                 # deep emitter used only after cheap is capped
    assert _total(allocs) == 2


def test_deep_emitter_not_used_when_unjustified():
    # ollama capped at 1, but the 2nd cell's value can't cover claude's cost -> no claude.
    cells = [{"key": "a", "qd_gain": 0.9}, {"key": "b", "qd_gain": 0.3}]
    allocs = es.allocate(["ollama", "claude"], cells, fork_budget=3,
                         emitter_caps={"ollama": 1})
    assert "claude" not in {a.emitter for a in allocs}


def test_allocation_is_deterministic():
    cells = [{"key": "a", "qd_gain": 0.7}, {"key": "b", "qd_gain": 0.5}]
    a1 = es.allocate(["ollama", "claude"], cells, fork_budget=2)
    a2 = es.allocate(["ollama", "claude"], cells, fork_budget=2)
    assert [(a.emitter, a.target_cell, a.budget["forks"]) for a in a1] == \
           [(a.emitter, a.target_cell, a.budget["forks"]) for a in a2]


def test_empty_inputs_return_empty():
    assert es.allocate([], [{"key": "a"}], fork_budget=1) == []
    assert es.allocate(["ollama"], [], fork_budget=1) == []
    assert es.allocate(["ollama"], [{"key": "a"}], fork_budget=0) == []
