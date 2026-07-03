"""Work-profile control plane: parsing, presets, and compiled policy."""
import pytest

from platform_core.orchestration import work_profile as wp


def test_default_profile_is_balanced():
    p = wp.resolve()
    assert p.preset == "balanced"
    assert p.axes["momentum"] == 55
    assert wp.policy(p).planner_posture == "blended"


def test_presets_resolve_exactly():
    p = wp.resolve("auditor")
    assert p.axes["stability"] == 90
    assert p.axes["evidence"] == 85
    assert wp.policy(p).planner_posture == "audit"


def test_compact_string_accepts_aliases_and_clamps():
    p = wp.resolve("safe=110,tests=80,arch=-5,ship=77,innovation=66")
    assert p.axes["stability"] == 100
    assert p.axes["evidence"] == 80
    assert p.axes["architecture"] == 0
    assert p.axes["momentum"] == 77
    assert p.axes["discovery"] == 66


def test_json_profile_resolves():
    p = wp.resolve('{"preset":"shipper","axes":{"evidence":90}}')
    assert p.preset == "shipper"
    assert p.axes["momentum"] == 95
    assert p.axes["evidence"] == 90


def test_unknown_axis_fails_cleanly():
    with pytest.raises(ValueError):
        wp.resolve("nonsense=50")


def test_policy_contains_brownfield_knobs():
    p = wp.resolve("inventor")
    pol = wp.policy(p)
    assert pol.discovery_depth == "transformative"
    assert pol.fork_strategy["prefer_forks"] is True
    assert "researcher" in pol.society_strategy["preferred_roles"]
    assert pol.execution_environment_preference == "worktree"


def test_guidance_mentions_dominant_axes():
    text = wp.guidance_block(wp.resolve("test-review"), context="planner")
    assert "Evidence" in text
    assert "tests" in text
    assert "never override user scope" in text
    assert "Context: planner" in text


def test_summary_and_surface_tags_are_human_and_machine_readable():
    p = wp.resolve("auditor")
    assert p.summary().startswith("Stab 90")
    assert "profile:auditor" in wp.surface_tags(p)
    assert "profile_axis:stability" in wp.surface_tags(p)
