"""Eval suite 2 (design spec §11) — scar generalization & decay.

Properties under guard:
  * A one-insertion mutation of a known scar motif still triggers detection:
    ``instinct_stream.near_duplicate(orig, mutated) >= 0.7``.
  * An unrelated sequence scores low (well under the trigger threshold).
  * A scar's weight strictly DECREASES under ``scar_graph.decay`` (0 < rate < 1).

Pure: exercises only ``human_nature.instinct_stream`` and
``human_nature.scar_graph``. No I/O.
"""
from __future__ import annotations

from human_nature import instinct_stream as istr
from human_nature import scar_graph as sg

# A representative failure motif over event-type-like tokens.
_MOTIF = ["plan", "edit", "test", "verify_fail", "retry", "edit", "test"]
_TRIGGER = 0.7


def _insert_once(seq: list[str], index: int, token: str) -> list[str]:
    """Return ``seq`` with ``token`` inserted at ``index`` (single insertion)."""
    return seq[:index] + [token] + seq[index:]


def test_single_insertion_still_triggers_at_every_position() -> None:
    """One inserted token anywhere keeps similarity above the trigger gate."""
    for index in range(0, len(_MOTIF) + 1):
        mutated = _insert_once(_MOTIF, index, "noise_event")
        sim = istr.near_duplicate(_MOTIF, mutated)
        assert sim >= _TRIGGER, (index, sim)


def test_single_substitution_still_generalizes() -> None:
    """Swapping one interior token still keeps most of the motif recognizable."""
    mutated = list(_MOTIF)
    mutated[3] = "different_event"
    sim = istr.near_duplicate(_MOTIF, mutated)
    # LCS drops by exactly the substituted token: (n-1) common of n each.
    assert sim >= _TRIGGER, sim


def test_unrelated_sequence_scores_low() -> None:
    """A disjoint-alphabet sequence scores far below the trigger gate."""
    unrelated = ["alpha", "beta", "gamma", "delta", "epsilon"]
    sim = istr.near_duplicate(_MOTIF, unrelated)
    assert sim < _TRIGGER
    assert sim == 0.0  # no shared tokens => LCS 0 => ratio 0


def test_generalization_beats_unrelated_by_a_margin() -> None:
    """The mutated-scar score must dominate the unrelated score."""
    mutated = _insert_once(_MOTIF, 2, "noise_event")
    unrelated = ["x1", "x2", "x3", "x4", "x5", "x6"]
    assert istr.near_duplicate(_MOTIF, mutated) > istr.near_duplicate(
        _MOTIF, unrelated
    )


def test_similarity_is_symmetric_and_bounded() -> None:
    """near_duplicate is symmetric and always within [0, 1]."""
    mutated = _insert_once(_MOTIF, 4, "noise_event")
    forward = istr.near_duplicate(_MOTIF, mutated)
    backward = istr.near_duplicate(mutated, _MOTIF)
    assert abs(forward - backward) < 1e-12
    assert 0.0 <= forward <= 1.0
    assert istr.near_duplicate(_MOTIF, _MOTIF) == 1.0


def test_scar_weight_strictly_decreases_under_decay() -> None:
    """Disconfirming a scar strictly lowers its node weight (0 < rate < 1)."""
    graph = sg.new_graph()
    sg.add_node(graph, "motif_a", "FailureMotif")
    sg.add_node(graph, "recovery_a", "RecoveryStrategy")
    sg.link(graph, "motif_a", "recovery_a", "recovered_by", 1.0)

    before = graph["nodes"]["motif_a"]["weight"]
    sg.decay(graph, ["motif_a"], 0.3)
    after = graph["nodes"]["motif_a"]["weight"]

    assert after < before
    assert after == before * 0.7


def test_repeated_decay_is_monotone_and_never_negative() -> None:
    """Successive decays keep shrinking the weight and never flip sign."""
    graph = sg.new_graph()
    sg.add_node(graph, "motif_b", "FailureMotif")
    prev = graph["nodes"]["motif_b"]["weight"]
    for _ in range(5):
        sg.decay(graph, ["motif_b"], 0.25)
        cur = graph["nodes"]["motif_b"]["weight"]
        assert cur < prev
        assert cur >= 0.0
        prev = cur


def test_incident_edge_weight_also_decays() -> None:
    """Decay also multiplies incident-edge weights of a disconfirmed scar."""
    graph = sg.new_graph()
    sg.add_node(graph, "motif_c", "FailureMotif")
    sg.add_node(graph, "area_c", "CodeArea")
    sg.link(graph, "motif_c", "area_c", "caused_by", 2.0)
    edge_before = graph["edges"][0]["weight"]
    sg.decay(graph, ["motif_c"], 0.5)
    edge_after = graph["edges"][0]["weight"]
    assert edge_after < edge_before
    assert edge_after == edge_before * 0.5
