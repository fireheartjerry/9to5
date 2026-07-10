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


# --- auditor / stability axis coverage ---

def test_auditor_dominant_axis_is_stability():
    p = wp.resolve("auditor")
    assert p.dominant_axis() == "stability"


def test_auditor_policy_planner_posture_is_audit():
    p = wp.resolve("auditor")
    pol = wp.policy(p)
    assert pol.planner_posture == "audit"


def test_auditor_policy_safety_posture():
    pol = wp.policy(wp.resolve("auditor"))
    assert pol.safety_posture["destructive_tolerance"] == "low"
    assert pol.safety_posture["risky_actions_need_extra_justification"] is True
    assert pol.safety_posture["speculative_requires_isolation"] is False


def test_auditor_policy_verify_requirements():
    pol = wp.policy(wp.resolve("auditor"))
    assert pol.verify_requirements["affected_tests"] is True
    assert pol.verify_requirements["evidence_receipt_strict"] is True
    assert pol.verify_requirements["regression_checks"] is True
    assert pol.verify_requirements["keep_sufficient_not_sprawling"] is False


def test_auditor_policy_review_thresholds():
    pol = wp.policy(wp.resolve("auditor"))
    assert pol.review_thresholds["review_short_outputs"] is True
    assert pol.review_thresholds["skip_repeat_reviews"] is False
    assert pol.review_thresholds["architecture_review_weighted"] is False


def test_auditor_policy_execution_env_is_isolated():
    pol = wp.policy(wp.resolve("auditor"))
    assert pol.execution_environment_preference == "isolated"


def test_auditor_policy_fork_strategy():
    pol = wp.policy(wp.resolve("auditor"))
    assert pol.fork_strategy["conservative_forks"] is True
    assert pol.fork_strategy["prefer_forks"] is False
    assert pol.fork_strategy["rare_forks"] is False


def test_auditor_policy_discovery_depth_is_digest():
    pol = wp.policy(wp.resolve("auditor"))
    assert pol.discovery_depth == "digest"


def test_auditor_policy_society_strategy_debate_rounds():
    pol = wp.policy(wp.resolve("auditor"))
    assert pol.society_strategy["debate_rounds"] == 2


def test_preferred_roles_auditor_includes_reviewer_and_tester():
    roles = wp.preferred_roles(wp.resolve("auditor"))
    assert "coder" in roles
    assert "reviewer" in roles
    assert "tester" in roles
    assert roles[0] == "coder"


# --- WorkProfile data methods ---

def test_work_profile_compact_format():
    p = wp.resolve("auditor")
    compact = p.compact()
    assert "Stab=90" in compact
    assert "Evid=85" in compact
    assert "Mom=20" in compact


def test_work_profile_to_meta_has_required_keys():
    p = wp.resolve("auditor")
    meta = p.to_meta()
    assert meta["preset"] == "auditor"
    assert meta["axes"]["stability"] == 90
    assert "version" in meta
    assert "source" in meta


def test_surface_tags_includes_per_axis_values():
    p = wp.resolve("auditor")
    tags = wp.surface_tags(p)
    assert "profile_stability:90" in tags
    assert "profile_evidence:85" in tags
    assert "profile_momentum:20" in tags


# --- resolve edge cases ---

def test_resolve_with_preset_kwarg():
    p = wp.resolve(preset="auditor")
    assert p.preset == "auditor"
    assert p.axes["stability"] == 90


def test_resolve_passthrough_returns_same_object():
    original = wp.resolve("auditor")
    result = wp.resolve(original)
    assert result is original


def test_resolve_dict_with_preset_and_axis_override():
    p = wp.resolve({"preset": "auditor", "axes": {"stability": 70}})
    assert p.preset == "auditor"
    assert p.axes["stability"] == 70
    assert p.axes["evidence"] == 85


def test_resolve_unknown_preset_kwarg_fails():
    with pytest.raises(ValueError, match="unknown work-profile preset"):
        wp.resolve(preset="nonexistent")


def test_compact_string_colon_separator():
    p = wp.resolve("safe:80,tests:70")
    assert p.axes["stability"] == 80
    assert p.axes["evidence"] == 70


# --- from_state and policy_from_state ---

class _FakeState:
    def __init__(self, meta=None):
        self.meta = meta or {}


def test_from_state_fallback_when_no_work_profile():
    state = _FakeState()
    p = wp.from_state(state)
    assert p.preset == "balanced"


def test_from_state_resolves_stored_preset():
    state = _FakeState({"work_profile": "auditor"})
    p = wp.from_state(state)
    assert p.preset == "auditor"
    assert p.axes["stability"] == 90


def test_from_state_falls_back_on_corrupt_meta():
    class _Bad:
        meta = None
    p = wp.from_state(_Bad())
    assert p.preset == "balanced"


def test_policy_from_state_uses_cached_policy_when_version_matches():
    stored = {
        "version": wp.VERSION,
        "discovery_depth": "none",
        "planner_posture": "audit",
        "effort_floor_by_task_kind": {},
        "review_thresholds": {},
        "verify_requirements": {},
        "fork_strategy": {},
        "society_strategy": {},
        "execution_environment_preference": "isolated",
        "safety_posture": {},
        "horizon_fill_strategy": "audit",
        "learning_tags": {},
    }
    state = _FakeState({"run_intent_policy": stored})
    pol = wp.policy_from_state(state)
    assert pol.planner_posture == "audit"
    assert pol.execution_environment_preference == "isolated"
    assert pol.discovery_depth == "none"


def test_policy_from_state_falls_back_on_stale_version():
    stored = {"version": 999, "planner_posture": "stale"}
    state = _FakeState({"run_intent_policy": stored, "work_profile": "auditor"})
    pol = wp.policy_from_state(state)
    assert pol.planner_posture == "audit"


# --- guidance_block ---

def test_guidance_block_auditor_mentions_stability_and_evidence():
    text = wp.guidance_block(wp.resolve("auditor"), context="executor")
    assert "Stability" in text
    assert "Evidence" in text
    assert "Context: executor" in text
    assert "never override user scope" in text


def test_guidance_block_auditor_omits_discovery_line():
    text = wp.guidance_block(wp.resolve("auditor"), context="run")
    assert "- Discovery:" not in text


# --- profile_help_embed_fields ---

def test_profile_help_embed_fields_contains_all_axes_and_presets():
    fields = wp.profile_help_embed_fields()
    titles = [f[0] for f in fields]
    assert "Stability" in titles
    assert "Evidence" in titles
    assert "Presets" in titles
    presets_text = next(v for k, v in fields if k == "Presets")
    assert "auditor" in presets_text
