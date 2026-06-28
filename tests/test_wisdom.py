"""Wisdom trail + growth summary pure helpers (reflections injected, no DB)."""
from learning import wisdom


class _State:
    meta = {"goal_raw": "fix windows subprocess timing"}
    task_id = "t1"


def test_wisdom_trail_keyword_matches_goal():
    refs = [
        {"approach": "windows subprocess timing under load is unreliable", "run_id": "r9",
         "confidence": 0.8, "subtask_id": "st-002"},
        {"approach": "unrelated css refactor", "run_id": "r3", "confidence": 0.5,
         "subtask_id": "st-001"},
    ]
    out = wisdom.wisdomTrail(_State(), reflections=refs)
    assert "windows subprocess timing" in out
    assert "css refactor" not in out


def test_wisdom_trail_empty_message():
    out = wisdom.wisdomTrail(_State(), reflections=[])
    assert "no" in out.lower()


def test_growth_summary_reads_reflections():
    refs = [{"approach": "learned a thing", "run_id": "r9", "confidence": 0.7}]
    out = wisdom.growthSummary(reflections=refs, runs=[{"task_id": "r9", "status": "done"}])
    assert "learned a thing" in out or "r9" in out


def test_growth_summary_empty_is_graceful():
    out = wisdom.growthSummary(reflections=[], runs=[])
    assert isinstance(out, str) and out


def test_growth_summary_domain_filter():
    refs = [
        {"approach": "subprocess timing lesson", "run_id": "r9", "confidence": 0.8},
        {"approach": "css spacing lesson", "run_id": "r8", "confidence": 0.6},
    ]
    out = wisdom.growthSummary(domain="subprocess", reflections=refs, runs=[])
    assert "subprocess" in out.lower()
    assert "css" not in out.lower()
