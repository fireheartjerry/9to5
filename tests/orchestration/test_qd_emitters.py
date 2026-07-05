"""Heterogeneous emitters: valid shapes, fail-open, lineage, recombination matching."""
from platform_core.orchestration import qd_emitters as qe


def _valid(cand):
    return (cand and "target_cell" in cand and "behavior_delta" in cand
            and set(cand["lineage"]) >= {"parents", "emitter", "generation", "mutation_prompt_hash"})


def test_ollama_emitter_valid_shape():
    c = qe.ollama_emitter("cellA")
    assert _valid(c)
    assert c["lineage"]["emitter"] == "ollama"
    assert c["target_cell"] == "cellA"


def test_ollama_emitter_uses_brain_angle():
    c = qe.ollama_emitter("cellA", brain=lambda p: "a wild new mechanism")
    assert c["behavior_delta"] == "a wild new mechanism"


def test_ollama_emitter_fails_open_on_brain_error():
    def boom(_):
        raise RuntimeError("nope")
    c = qe.ollama_emitter("cellA", brain=boom)
    assert _valid(c)                                 # template angle, no crash
    assert "cellA" in c["behavior_delta"]


def test_claude_emitter_marks_deep_bias():
    c = qe.claude_emitter("cellB")
    assert c["lineage"]["emitter"] == "claude"
    assert _valid(c)


def test_random_emitter_targets_underexplored_cell():
    c = qe.random_emitter(["z_cell", "a_cell"])
    assert c["target_cell"] == "a_cell"              # deterministic (sorted)
    assert c["lineage"]["emitter"] == "random"


def test_random_emitter_none_when_no_empty_cells():
    assert qe.random_emitter([]) is None


def test_lineage_records_parents():
    c = qe.ollama_emitter("cellA", parents=["p1", "p2"])
    assert c["lineage"]["parents"] == ["p1", "p2"]


# ── recombination matching ────────────────────────────────────────────────────

A = {"id": "a", "target_subsystems": ["f1"], "target_cell": "cA", "measured_novelty": 0.8}
B = {"id": "b", "target_subsystems": ["f2"], "target_cell": "cB", "measured_novelty": 0.8}
C = {"id": "c", "target_subsystems": ["f1"], "target_cell": "cA", "measured_novelty": 0.8}


def test_compatibility_prefers_disjoint_complementary():
    assert qe.compatibility(A, B) > qe.compatibility(A, C)   # disjoint+different-cell beats overlap


def test_match_parents_pairs_most_compatible():
    matches = qe.match_parents([A, B, C])
    assert matches
    top = {matches[0][0]["id"], matches[0][1]["id"]}
    assert top == {"a", "b"}                          # highest-compatibility disjoint pair


def test_recombination_records_both_parents():
    c = qe.recombination_emitter([A, B, C])
    assert c["lineage"]["emitter"] == "recombination"
    assert set(c["lineage"]["parents"]) == {"a", "b"}


def test_recombination_none_with_one_parent():
    assert qe.recombination_emitter([A]) is None
    assert qe.recombination_emitter([]) is None
