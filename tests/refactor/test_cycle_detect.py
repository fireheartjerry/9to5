"""Tests for refactor.cycle_detect: graph build, Tarjan cycles, cycle prediction."""
from __future__ import annotations


def test_find_cycles_on_fixture(fixture_project):
    from developer_tools.introspection import extractProject
    from developer_tools.refactoring.cycle_detect import buildImportGraph, findCycles

    g = buildImportGraph(extractProject(fixture_project, use_cache=False))
    cycles = findCycles(g)
    assert ["pkg/cycle_a.py", "pkg/cycle_b.py"] in [sorted(c) for c in cycles]


def test_find_cycles_deterministic_and_self_loop():
    from developer_tools.refactoring.cycle_detect import findCycles

    g = {"a": {"b"}, "b": {"a"}, "c": {"c"}, "d": set()}
    first = findCycles(g)
    second = findCycles(g)
    assert first == second
    assert ["c"] in first                      # self-loop counts as a cycle
    assert ["a", "b"] in first                 # rotated to start at min node
    assert len(first) == 2


def test_would_create_cycle():
    from developer_tools.refactoring.cycle_detect import wouldCreateCycle

    g = {"a": {"b"}, "b": set()}
    assert wouldCreateCycle(g, added_edges=[("b", "a")])          # predicts a->b->a
    assert not wouldCreateCycle(g, added_edges=[("b", "a")], removed_edges=[("a", "b")])


def test_would_create_cycle_ignores_preexisting():
    from developer_tools.refactoring.cycle_detect import wouldCreateCycle

    g = {"x": {"y"}, "y": {"x"}, "a": {"b"}, "b": set()}
    # x<->y already cycles; an unrelated safe edge must not re-report it.
    assert wouldCreateCycle(g, added_edges=[("b", "c")]) == []
    # ...but a genuinely new cycle is still caught.
    assert wouldCreateCycle(g, added_edges=[("b", "a")]) == [["a", "b"]]


def test_would_create_cycle_does_not_mutate_input():
    from developer_tools.refactoring.cycle_detect import wouldCreateCycle

    g = {"a": {"b"}, "b": set()}
    wouldCreateCycle(g, added_edges=[("b", "a")], removed_edges=[("a", "b")])
    assert g == {"a": {"b"}, "b": set()}
