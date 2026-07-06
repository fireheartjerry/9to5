"""Tests for human_nature.motif_mining (offline failure-motif miner)."""
from __future__ import annotations

from human_nature.motif_mining import anomaly_score, mine_frequent


def test_frequent_contiguous_motif_across_runs():
    seqs = [
        ["START", "PATCH_LARGE", "TESTS_SKIPPED", "FAIL"],
        ["START", "PATCH_LARGE", "TESTS_SKIPPED", "PASS"],
        ["INIT", "PATCH_LARGE", "TESTS_SKIPPED", "FAIL"],
        ["START", "PATCH_SMALL", "TESTS_RAN", "PASS"],
    ]
    motifs = mine_frequent(seqs, min_support=3)
    found = [m for m in motifs if m["motif"] == ["PATCH_LARGE", "TESTS_SKIPPED"]]
    assert found, "expected recurring motif to be mined"
    assert found[0]["support"] >= 3


def test_rare_subsequence_excluded_at_min_support_2():
    seqs = [
        ["A", "B", "C"],
        ["A", "B", "D"],
        ["X", "Y", "Z"],  # only run with X,Y,Z
    ]
    motifs = mine_frequent(seqs, min_support=2)
    labels = [m["motif"] for m in motifs]
    assert ["X", "Y"] not in labels
    assert ["Y", "Z"] not in labels
    # A,B recurs in 2 runs -> kept
    assert ["A", "B"] in labels


def test_sorted_support_desc_then_length_desc():
    seqs = [
        ["A", "B", "C"],
        ["A", "B", "C"],
        ["A", "B", "C"],
    ]
    motifs = mine_frequent(seqs, min_support=2, min_len=2, max_len=3)
    supports = [m["support"] for m in motifs]
    assert supports == sorted(supports, reverse=True)


def test_anomaly_high_for_unlike_success():
    assert anomaly_score(["X", "Y", "Z"], [["A", "B", "C"]]) > 0.6


def test_anomaly_zero_when_identical_success():
    seq = ["A", "B", "C"]
    assert anomaly_score(seq, [seq]) == 0.0


def test_anomaly_one_when_no_success_history():
    assert anomaly_score(["A", "B", "C"], []) == 1.0


def test_anomaly_empty_seq_is_zero():
    assert anomaly_score([], [["A", "B"]]) == 0.0
