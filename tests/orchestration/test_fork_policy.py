"""shouldFork is opt-in: fork_eligible flag is the ONLY trigger (fork-as-retry OFF).

forkPlan emits N distinct seeds spanning effort x angle.
"""
from platform_core.orchestration import fork_policy as fp


def _kwargs(**over):
    base = dict(enabled=True, projected_cost=2.0, cost_ceiling=5.0,
                worktree_isolated=True, goal_elaborated="build a feature spanning multiple files",
                is_self_referential=False)
    base.update(over)
    return base


def test_forks_only_when_eligible_flag_set():
    assert fp.shouldFork({"fork_eligible": True}, **_kwargs()) is True
    assert fp.shouldFork({"fork_eligible": False}, **_kwargs()) is False
    assert fp.shouldFork({}, **_kwargs()) is False


def test_high_effort_alone_does_not_fork():   # fork-as-retry / auto triggers OFF
    assert fp.shouldFork({"effort_level": "xhigh"}, **_kwargs()) is False


def test_global_flag_off_never_forks():
    assert fp.shouldFork({"fork_eligible": True}, **_kwargs(enabled=False)) is False


def test_over_cost_ceiling_downgrades():
    assert fp.shouldFork({"fork_eligible": True}, **_kwargs(projected_cost=9.0)) is False


def test_no_isolation_never_forks():
    assert fp.shouldFork({"fork_eligible": True}, **_kwargs(worktree_isolated=False)) is False


def test_single_deliverable_excluded():
    assert fp.shouldFork({"fork_eligible": True},
                         **_kwargs(goal_elaborated="edit config.py")) is False


def test_self_referential_excluded():
    assert fp.shouldFork({"fork_eligible": True}, **_kwargs(is_self_referential=True)) is False


def test_discovery_profile_can_opt_in_design_fork():
    st = {"title": "Explore transformative architecture", "description": "ambiguous design options"}
    assert fp.shouldFork(st, **_kwargs(work_profile="inventor")) is True


def test_plan_emits_n_distinct_seeds():
    plan = fp.forkPlan({"subtask_id": "st-001"}, n=2)
    assert plan.n == 2
    assert len(plan.branch_seeds) == 2
    ids = [s.branch_id for s in plan.branch_seeds]
    assert ids == ["b0", "b1"]
    # No two seeds identical on (effort, angle).
    fingerprints = {(s.effort_level, s.angle_hint) for s in plan.branch_seeds}
    assert len(fingerprints) == 2


def test_plan_seeds_carry_routed_model():
    import config
    plan = fp.forkPlan({"subtask_id": "st-001"}, n=2)
    for s in plan.branch_seeds:
        assert s.model == config.MODEL_BY_EFFORT[s.effort_level]


def test_plan_caps_at_angle_bank_but_stays_distinct():
    plan = fp.forkPlan({"subtask_id": "st-001"}, n=3)
    assert len(plan.branch_seeds) == 3
    fingerprints = {(s.effort_level, s.angle_hint) for s in plan.branch_seeds}
    assert len(fingerprints) == 3


def test_profile_shapes_fork_angles():
    plan = fp.forkPlan({"subtask_id": "st-001"}, n=3, work_profile="auditor")
    assert any("test-first" in s.angle_hint for s in plan.branch_seeds)
    assert any("conservative" in s.angle_hint for s in plan.branch_seeds)


class TestExploreSeededAngles:
    """EXPLORE_APPROACHES_ENABLED seeds angle hints from ranked explore summaries (fail-open)."""

    ST = {"subtask_id": "st-001", "title": "Add a widget", "description": "spanning files"}

    def _patch_explore(self, monkeypatch, candidates, scores):
        import config
        import explore
        import introspect
        monkeypatch.setattr(config, "EXPLORE_APPROACHES_ENABLED", True, raising=False)
        monkeypatch.setattr(introspect, "extractProject", lambda root, **kw: object())
        monkeypatch.setattr(explore, "generateApproaches", lambda goal, model, **kw: candidates)
        monkeypatch.setattr(explore, "scoreApproaches", lambda cands, model: scores)

    def test_flag_on_uses_ranked_summaries_in_order(self, monkeypatch):
        from types import SimpleNamespace as NS
        cands = [NS(approach_id=f"a{i}", summary=f"Summary {i}") for i in (1, 2, 3)]
        scores = [NS(approach_id="a2"), NS(approach_id="a3"), NS(approach_id="a1")]
        self._patch_explore(monkeypatch, cands, scores)
        plan = fp.forkPlan(dict(self.ST), n=3)
        hints = [s.angle_hint for s in plan.branch_seeds]
        assert hints == ["Summary 2", "Summary 3", "Summary 1"]

    def test_flag_off_byte_identical_to_existing_angles(self, monkeypatch):
        import config
        monkeypatch.setattr(config, "EXPLORE_APPROACHES_ENABLED", False, raising=False)
        plan = fp.forkPlan(dict(self.ST), n=3)
        expected = [
            (f"b{i}", fp.EFFORT_CYCLE[i % len(fp.EFFORT_CYCLE)],
             fp.DIVERSITY_ANGLES[i % len(fp.DIVERSITY_ANGLES)],
             config.MODEL_BY_EFFORT[fp.EFFORT_CYCLE[i % len(fp.EFFORT_CYCLE)]])
            for i in range(3)
        ]
        got = [(s.branch_id, s.effort_level, s.angle_hint, s.model) for s in plan.branch_seeds]
        assert got == expected

    def test_explore_raising_falls_back_to_bank(self, monkeypatch):
        import config
        import introspect
        monkeypatch.setattr(config, "EXPLORE_APPROACHES_ENABLED", True, raising=False)

        def _boom(root, **kw):
            raise RuntimeError("scan failed")

        monkeypatch.setattr(introspect, "extractProject", _boom)
        plan = fp.forkPlan(dict(self.ST), n=3)
        assert [s.angle_hint for s in plan.branch_seeds] == list(fp.DIVERSITY_ANGLES)

    def test_explore_empty_summaries_falls_back_to_bank(self, monkeypatch):
        from types import SimpleNamespace as NS
        cands = [NS(approach_id="a1", summary="")]
        scores = [NS(approach_id="a1")]
        self._patch_explore(monkeypatch, cands, scores)
        plan = fp.forkPlan(dict(self.ST), n=3)
        assert [s.angle_hint for s in plan.branch_seeds] == list(fp.DIVERSITY_ANGLES)

    def test_work_dir_param_scopes_exploration_root(self, monkeypatch, tmp_path):
        """forkPlan(work_dir=...) must explore that dir, not config.PROJECT_ROOT."""
        import config
        import explore
        import introspect
        seen_roots = []
        monkeypatch.setattr(config, "EXPLORE_APPROACHES_ENABLED", True, raising=False)
        monkeypatch.setattr(introspect, "extractProject",
                            lambda root, **kw: seen_roots.append(root) or object())
        monkeypatch.setattr(explore, "generateApproaches", lambda goal, model, **kw: [])
        monkeypatch.setattr(explore, "scoreApproaches", lambda cands, model: [])
        fp.forkPlan(dict(self.ST), n=1, work_dir=str(tmp_path))
        assert seen_roots == [str(tmp_path)]

    def test_no_work_dir_falls_back_to_project_root(self, monkeypatch):
        """Omitting work_dir preserves today's behavior: explore config.PROJECT_ROOT."""
        import config
        import explore
        import introspect
        seen_roots = []
        monkeypatch.setattr(config, "EXPLORE_APPROACHES_ENABLED", True, raising=False)
        monkeypatch.setattr(introspect, "extractProject",
                            lambda root, **kw: seen_roots.append(root) or object())
        monkeypatch.setattr(explore, "generateApproaches", lambda goal, model, **kw: [])
        monkeypatch.setattr(explore, "scoreApproaches", lambda cands, model: [])
        fp.forkPlan(dict(self.ST), n=1)
        assert seen_roots == [config.PROJECT_ROOT]
