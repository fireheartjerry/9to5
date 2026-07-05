"""Tests for explore.approach_gen -- brainless + brain-backed approach generation."""
from __future__ import annotations

from introspect import extractProject
from tests.factories import fake_brain

from explore.approach_gen import APPROACH_ARCHETYPES, generateApproaches


def test_generate_brainless_deterministic(fixture_project):
    m = extractProject(fixture_project, use_cache=False)
    a = generateApproaches("add input validation to pkg.core", m, n=3)
    b = generateApproaches("add input validation to pkg.core", m, n=3)
    assert [c.approach_id for c in a] == [c.approach_id for c in b]
    assert len(a) == 3
    assert [c.approach_id for c in a] == ["a1", "a2", "a3"]
    assert len({c.archetype for c in a}) == 3  # distinct archetypes
    assert a == b  # full determinism, not just ids


def test_generate_brainless_uses_project_traits(fixture_project):
    m = extractProject(fixture_project, use_cache=False)
    out = generateApproaches("add input validation to pkg.core", m, n=3)
    test_first = next(c for c in out if c.archetype == "test-first")
    test_cmds = [c.cmd for c in m.commands if c.kind == "test"]
    assert test_cmds, "fixture must expose a detected test command"
    assert any(test_cmds[0] in step for step in test_first.steps)
    for cand in out:
        assert cand.title and cand.summary and cand.steps
        assert cand.files_touched_estimate >= 1


def test_generate_n_larger_than_archetypes_clamps(fixture_project):
    m = extractProject(fixture_project, use_cache=False)
    out = generateApproaches("goal", m, n=99)
    assert len(out) == len(APPROACH_ARCHETYPES)
    assert len({c.archetype for c in out}) == len(APPROACH_ARCHETYPES)


def test_generate_with_brain(fixture_project):
    brain = fake_brain(
        as_json=[
            {
                "title": "T",
                "summary": "S",
                "steps": ["s1"],
                "files_touched_estimate": 2,
                "archetype": "minimal-patch",
            }
        ]
    )
    out = generateApproaches(
        "goal", extractProject(fixture_project, use_cache=False), brain=brain, n=1
    )
    assert len(out) == 1
    assert out[0].title == "T"
    assert out[0].summary == "S"
    assert out[0].steps == ("s1",)
    assert out[0].files_touched_estimate == 2
    assert out[0].archetype == "minimal-patch"
    assert out[0].approach_id == "a1"


def test_generate_brain_unknown_archetype_clamped(fixture_project):
    brain = fake_brain(
        as_json=[
            {
                "title": "T",
                "summary": "S",
                "steps": ["s1"],
                "files_touched_estimate": 2,
                "archetype": "yolo-rewrite",
            }
        ]
    )
    out = generateApproaches(
        "goal", extractProject(fixture_project, use_cache=False), brain=brain, n=1
    )
    assert out[0].archetype == "minimal-patch"


def test_generate_brain_missing_fields_dropped_and_topped_up(fixture_project):
    brain = fake_brain(
        as_json=[
            {"title": "no steps", "summary": "S", "files_touched_estimate": 1},
            {
                "title": "OK",
                "summary": "S",
                "steps": ["s1"],
                "files_touched_estimate": 1,
                "archetype": "new-module",
            },
        ]
    )
    m = extractProject(fixture_project, use_cache=False)
    out = generateApproaches("goal", m, brain=brain, n=3)
    assert len(out) == 3
    assert out[0].title == "OK"  # invalid item dropped, valid kept
    assert [c.approach_id for c in out] == ["a1", "a2", "a3"]
    # topped up from archetypes not already used
    assert len({c.archetype for c in out}) == 3


def test_generate_brain_invalid_json_falls_back(fixture_project):
    brain = fake_brain(reply="not json at all {{{")
    m = extractProject(fixture_project, use_cache=False)
    out = generateApproaches("goal", m, brain=brain, n=3)
    brainless = generateApproaches("goal", m, n=3)
    assert out == brainless
