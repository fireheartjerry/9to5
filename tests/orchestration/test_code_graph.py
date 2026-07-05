"""Code-graph blast radius: SCC condensation + dependency reachability risk scoring.

All tests use synthetic import graphs (edge A->B = 'A imports B'), so they are deterministic
and need no repo scan.
"""
from platform_core.orchestration import code_graph as cg


def test_tarjan_collapses_cycle_into_one_scc():
    g = {"a": ["b"], "b": ["a"], "c": ["a"]}   # a<->b cycle; c imports a
    sccs = cg.tarjan_scc(g)
    comps = [set(s) for s in sccs]
    assert {"a", "b"} in comps                 # cycle is one component
    assert {"c"} in comps
    comp_of = cg.component_index(sccs)
    assert comp_of["a"] == comp_of["b"]        # same component


def test_touching_either_cycle_member_scores_identically():
    g = {"a": ["b"], "b": ["a"], "c": ["a"]}
    ra = cg.blast_radius(["a"], graph=g)
    rb = cg.blast_radius(["b"], graph=g)
    assert ra["bin"] == rb["bin"]
    assert ra["downstream_scc"] == rb["downstream_scc"]


def test_leaf_helper_is_low_blast_radius():
    g = {"app": ["api", "core"], "api": ["core"], "core": ["util"], "util": [], "leaf": ["util"]}
    r = cg.blast_radius(["leaf"], graph=g)     # nothing imports leaf
    assert r["bin"] == "low"
    assert r["downstream_scc"] == 0


def test_core_module_is_high_blast_radius():
    g = {f"m{i}": ["core"] for i in range(12)}  # 12 modules depend on core
    g["core"] = ["util"]
    g["util"] = []
    r = cg.blast_radius(["core"], graph=g)
    assert r["bin"] == "high"
    assert r["downstream_scc"] >= 12


def test_entrypoint_impact_raises_score():
    g = {"app": ["core"], "core": []}
    with_ep = cg.blast_radius(["core"], graph=g, entrypoints=["app"])
    without_ep = cg.blast_radius(["core"], graph=g)
    assert with_ep["entrypoints_impacted"] == 1
    assert with_ep["score"] > without_ep["score"]


def test_public_api_touch_bonus():
    g = {"x": [], "y": []}
    r = cg.blast_radius(["x"], graph=g, public_api=["x"])
    assert r["public_api_touches"] == 1


def test_empty_graph_fails_open_to_medium():
    r = cg.blast_radius(["anything.py"], graph={})
    assert r["bin"] == "medium"
    assert r["degraded"] is True


def test_disabled_flag_degrades(monkeypatch):
    import config
    monkeypatch.setattr(config, "CODE_GRAPH_ENABLED", False, raising=False)
    r = cg.blast_radius_for(["x.py"])
    assert r["degraded"] is True and r["bin"] == "medium"


def test_reverse_condensation_points_to_dependents():
    g = {"app": ["core"], "core": []}
    sccs = cg.tarjan_scc(g)
    comp_of = cg.component_index(sccs)
    radj = cg.reverse_condensation(g, comp_of)
    # core's dependents include app (app imports core)
    assert comp_of["app"] in radj[comp_of["core"]]
