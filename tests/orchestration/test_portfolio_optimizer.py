"""Portfolio optimizer: max-weight closure, dependency unlock, conflict repair, safety."""
from platform_core.orchestration import portfolio_optimizer as po


def _w(c):
    return c["w"]


# ── pure max_closure ──────────────────────────────────────────────────────────

def test_closure_rejects_standalone_negative():
    selected, obj = po.max_closure({"bad": -1.0}, [])
    assert selected == set()
    assert obj == 0.0


def test_closure_selects_standalone_positive():
    selected, obj = po.max_closure({"a": 3.0}, [])
    assert selected == {"a"}
    assert obj == 3.0


def test_closure_weak_foundation_selected_when_it_unlocks_high_value():
    # feature (+5) requires foundation (-1); net +4 => both selected.
    selected, obj = po.max_closure({"found": -1.0, "feat": 5.0}, [("feat", "found")])
    assert selected == {"found", "feat"}
    assert obj == 4.0


def test_closure_rejects_foundation_when_dependent_not_worth_it():
    # feature (+0.5) requires foundation (-3); net negative => select nothing.
    selected, obj = po.max_closure({"found": -3.0, "feat": 0.5}, [("feat", "found")])
    assert selected == set()
    assert obj == 0.0


# ── optimize (candidates + deps + conflicts) ─────────────────────────────────

def test_optimize_dependency_selected_with_dependent():
    cands = [{"id": "found", "w": -1.0}, {"id": "feat", "w": 5.0}]
    sel = po.optimize(cands, deps=[("feat", "found")], weight_fn=_w)
    assert set(sel.selected_candidate_ids) == {"found", "feat"}
    assert sel.objective_value == 4.0


def test_optimize_rejects_negative_utility():
    sel = po.optimize([{"id": "bad", "w": -1.0}], weight_fn=_w)
    assert sel.selected_candidate_ids == []
    assert sel.demoted_candidate_ids == ["bad"]


def test_optimize_repairs_conflicts_deterministically():
    cands = [{"id": "a", "w": 3.0}, {"id": "b", "w": 2.0}]
    sel = po.optimize(cands, conflicts=[("a", "b")], weight_fn=_w)
    assert sel.selected_candidate_ids == ["a"]      # higher-utility kept
    assert "b" in sel.demoted_candidate_ids
    assert sel.conflicts_repaired == [["a", "b"]]


def test_optimize_cascades_prune_when_prerequisite_demoted():
    # a(+5) requires b(+1); conflict (b,c) with c(+3) demotes b -> a must also drop.
    cands = [{"id": "a", "w": 5.0}, {"id": "b", "w": 1.0}, {"id": "c", "w": 3.0}]
    sel = po.optimize(cands, deps=[("a", "b")], conflicts=[("b", "c")], weight_fn=_w)
    assert "a" not in sel.selected_candidate_ids
    assert "b" not in sel.selected_candidate_ids
    assert "c" in sel.selected_candidate_ids


def test_optimize_safe_only_excludes_unsafe_candidate():
    unsafe = {"id": "x", "risk": "high", "blast_bin": "high"}
    sel = po.optimize([unsafe], weight_fn=lambda c: 5.0, safe_only=True)
    assert sel.selected_candidate_ids == []          # unsafe never enters auto-run bundle


def test_optimize_safe_only_keeps_safe_candidate():
    safe = {"id": "x", "risk": "low", "blast_bin": "low", "reversible": True}
    sel = po.optimize([safe], weight_fn=lambda c: 5.0, safe_only=True)
    assert sel.selected_candidate_ids == ["x"]


# ── candidate_weight sign ─────────────────────────────────────────────────────

def test_candidate_weight_positive_for_strong_candidate():
    good = {"impact": 1.0, "measured_novelty": 1.0, "confidence": 1.0, "feasibility": 1.0,
            "risk": "low", "blast_bin": "low"}
    assert po.candidate_weight(good) > 0


def test_candidate_weight_negative_for_weak_risky_candidate():
    bad = {"impact": 0.0, "measured_novelty": 0.0, "confidence": 0.0, "feasibility": 0.0,
           "risk": "high", "blast_bin": "high"}
    assert po.candidate_weight(bad) < 0
