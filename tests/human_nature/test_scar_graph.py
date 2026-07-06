"""Tests for the Scar-Tissue Failure Graph (pure graph ops)."""
from __future__ import annotations

from human_nature import scar_graph as sg


def _base_graph() -> dict:
    g = sg.new_graph()
    sg.add_node(g, "F", "FailureMotif")
    sg.add_node(g, "R", "RecoveryStrategy")
    sg.add_node(g, "M1", "SubtaskType")
    sg.add_node(g, "M2", "CodeArea")
    sg.add_node(g, "R2", "RecoveryStrategy")
    # short strong path F -> R
    sg.link(g, "F", "R", "recovered_by", weight=2.0)
    # longer alternative path F -> M1 -> M2 -> R2
    sg.link(g, "F", "M1", "usually_precedes", weight=1.0)
    sg.link(g, "M1", "M2", "usually_precedes", weight=1.0)
    sg.link(g, "M2", "R2", "resolved_by", weight=1.0)
    return g


def test_new_graph_shape():
    g = sg.new_graph()
    assert g == {"nodes": {}, "edges": []}


def test_add_node():
    g = sg.new_graph()
    sg.add_node(g, "F", "FailureMotif", label="oops")
    assert g["nodes"]["F"]["type"] == "FailureMotif"
    assert g["nodes"]["F"]["weight"] == 1.0
    assert g["nodes"]["F"]["attrs"]["label"] == "oops"


def test_link_ignores_unknown_relation():
    g = sg.new_graph()
    sg.add_node(g, "A", "FailureMotif")
    sg.add_node(g, "B", "RecoveryStrategy")
    sg.link(g, "A", "B", "not_a_relation", weight=3.0)
    assert g["edges"] == []
    sg.link(g, "A", "B", "recovered_by", weight=3.0)
    assert len(g["edges"]) == 1


def test_recovery_path_returns_shortest_route():
    g = _base_graph()
    path = sg.recovery_path(g, "F")
    assert path == ["F", "R"]
    assert g["nodes"][path[-1]]["type"] == "RecoveryStrategy"


def test_recovery_path_empty_when_unreachable():
    g = sg.new_graph()
    sg.add_node(g, "F", "FailureMotif")
    assert sg.recovery_path(g, "F") == []


def test_loops_finds_cycle():
    g = sg.new_graph()
    sg.add_node(g, "A", "FailureMotif")
    sg.add_node(g, "B", "SubtaskType")
    sg.add_node(g, "C", "CodeArea")
    sg.link(g, "A", "B", "usually_precedes")
    sg.link(g, "B", "A", "caused_by")
    sg.link(g, "C", "A", "similar_to")
    comps = sg.loops(g)
    assert len(comps) == 1
    assert set(comps[0]) == {"A", "B"}


def test_decay_halves_weight():
    g = _base_graph()
    before = g["nodes"]["F"]["weight"]
    edge_before = g["edges"][0]["weight"]
    sg.decay(g, ["F"], 0.5)
    assert g["nodes"]["F"]["weight"] == before * 0.5
    # incident edge (F->R) also decays
    assert g["edges"][0]["weight"] == edge_before * 0.5


def test_toxic_patterns_ranks_hub_first():
    g = sg.new_graph()
    sg.add_node(g, "HUB", "FailureMotif")
    sg.add_node(g, "OTHER", "FailureMotif")
    for i in range(5):
        nid = f"S{i}"
        sg.add_node(g, nid, "SubtaskType")
        sg.link(g, nid, "HUB", "usually_precedes", weight=1.0)
    sg.link(g, "OTHER", "HUB", "usually_precedes", weight=1.0)
    top = sg.toxic_patterns(g, k=2)
    assert top[0] == "HUB"
    assert set(top) <= {"HUB", "OTHER"}
