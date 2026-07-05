"""Rollback-DSU conflict simulation: file-collision grouping + reversible unions."""
from platform_core.orchestration import conflict_sim as cs


def test_disjoint_candidates_stay_separate():
    cands = [{"id": "a", "target_subsystems": ["f1.py"]},
             {"id": "b", "target_subsystems": ["f2.py"]}]
    groups = cs.conflict_groups(cands)
    assert len(groups) == 2
    assert cs.bundle_conflict_free(cands) is True


def test_shared_file_merges_candidates():
    cands = [{"id": "a", "target_subsystems": ["shared.py"]},
             {"id": "b", "target_subsystems": ["shared.py", "b.py"]}]
    groups = cs.conflict_groups(cands)
    assert len(groups) == 1
    assert cs.bundle_conflict_free(cands) is False


def test_transitive_conflict_grouping():
    # a-b share f1, b-c share f2 => all three collide transitively.
    cands = [{"id": "a", "target_subsystems": ["f1"]},
             {"id": "b", "target_subsystems": ["f1", "f2"]},
             {"id": "c", "target_subsystems": ["f2"]}]
    assert len(cs.conflict_groups(cands)) == 1


def test_would_conflict():
    assert cs.would_conflict({"id": "a", "target_subsystems": ["x"]},
                             {"id": "b", "target_subsystems": ["x"]}) is True
    assert cs.would_conflict({"id": "a", "target_subsystems": ["x"]},
                             {"id": "b", "target_subsystems": ["y"]}) is False


def test_rollback_restores_state():
    d = cs.RollbackDSU(["a", "b", "c"])
    d.union("a", "b")
    assert d.connected("a", "b") is True
    d.rollback(1)
    assert d.connected("a", "b") is False           # union undone
    assert d.size["a"] == 1 and d.size["b"] == 1


def test_rollback_to_marker():
    d = cs.RollbackDSU(["a", "b", "c", "d"])
    d.union("a", "b")
    mark = d.snapshot()
    d.union("c", "d")
    d.union("a", "c")
    assert d.connected("a", "d") is True
    d.rollback_to(mark)
    assert d.connected("a", "b") is True            # kept up to the marker
    assert d.connected("c", "d") is False           # everything after undone
    assert d.connected("a", "c") is False


def test_union_of_connected_is_noop_but_counted():
    d = cs.RollbackDSU(["a", "b"])
    d.union("a", "b")
    assert d.union("a", "b") is False               # already connected
    d.rollback(1)                                    # undoes the no-op
    assert d.connected("a", "b") is True            # the real union survives
