from human_nature.instinct_stream import (
    build_matcher,
    scan,
    match_prefix,
    scan_prefixes,
    near_duplicate,
)

M1 = ("m1", ["PATCH_LARGE", "TESTS_SKIPPED", "REGRESSION_FOUND"])


def test_scan_finds_full_motif_contiguous():
    matcher = build_matcher([M1])
    seq = ["SUBTASK_STARTED", "PATCH_LARGE", "TESTS_SKIPPED", "REGRESSION_FOUND", "CONFIDENCE_HIGH"]
    hits = scan(matcher, seq)
    assert len(hits) == 1
    hit = hits[0]
    assert hit["motif_id"] == "m1"
    assert hit["match_type"] == "exact"
    assert hit["score"] == 1.0
    assert hit["end_index"] == 3


def test_scan_finds_multiple_occurrences():
    matcher = build_matcher([M1])
    seq = M1[1] + ["X"] + M1[1]
    hits = scan(matcher, seq)
    assert len(hits) == 2
    assert [h["end_index"] for h in hits] == [2, 6]


def test_scan_unrelated_stream_empty():
    matcher = build_matcher([M1])
    seq = ["SUBTASK_STARTED", "CONFIDENCE_HIGH", "TOOL_TIMEOUT"]
    assert scan(matcher, seq) == []


def test_match_prefix_partial():
    seq = ["A", "PATCH_LARGE", "TESTS_SKIPPED"]
    motif = ["PATCH_LARGE", "TESTS_SKIPPED", "REGRESSION_FOUND"]
    assert abs(match_prefix(seq, motif) - 2 / 3) < 1e-9


def test_match_prefix_full():
    seq = ["X", "PATCH_LARGE", "TESTS_SKIPPED", "REGRESSION_FOUND"]
    motif = ["PATCH_LARGE", "TESTS_SKIPPED", "REGRESSION_FOUND"]
    assert match_prefix(seq, motif) == 1.0


def test_match_prefix_zero_unrelated():
    seq = ["SUBTASK_STARTED", "CONFIDENCE_HIGH"]
    motif = ["PATCH_LARGE", "TESTS_SKIPPED", "REGRESSION_FOUND"]
    assert match_prefix(seq, motif) == 0.0


def test_match_prefix_empty_motif():
    assert match_prefix(["A"], []) == 0.0


def test_scan_prefixes_reports_partial_only():
    seq = ["A", "PATCH_LARGE", "TESTS_SKIPPED"]
    hits = scan_prefixes([M1], seq, threshold=0.5)
    assert len(hits) == 1
    assert hits[0]["motif_id"] == "m1"
    assert hits[0]["match_type"] == "prefix"
    assert abs(hits[0]["score"] - 2 / 3) < 1e-9


def test_scan_prefixes_excludes_full_match():
    seq = ["PATCH_LARGE", "TESTS_SKIPPED", "REGRESSION_FOUND"]
    hits = scan_prefixes([M1], seq, threshold=0.5)
    assert hits == []


def test_scan_prefixes_below_threshold():
    seq = ["A", "PATCH_LARGE"]
    hits = scan_prefixes([M1], seq, threshold=0.5)
    assert hits == []


def test_near_duplicate_mutation_high():
    original = M1[1]
    mutated = ["PATCH_LARGE", "TESTS_SKIPPED", "VERIFIER_WARNING", "REGRESSION_FOUND"]
    assert near_duplicate(original, mutated) > 0.7


def test_near_duplicate_unrelated_low():
    a = ["PATCH_LARGE", "TESTS_SKIPPED", "REGRESSION_FOUND"]
    b = ["CONFIDENCE_HIGH", "TOOL_TIMEOUT"]
    assert near_duplicate(a, b) < 0.5


def test_near_duplicate_both_empty():
    assert near_duplicate([], []) == 1.0


def test_near_duplicate_one_empty():
    assert near_duplicate([], ["A"]) == 0.0


def test_near_duplicate_identical():
    a = ["PATCH_LARGE", "TESTS_SKIPPED"]
    assert near_duplicate(a, list(a)) == 1.0
