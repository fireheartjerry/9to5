"""Integration: discovery runs before architect in _freshRunPhase."""
from unittest import mock


def _make_minimal_state(goal="improve everything"):
    from state.task import TaskState
    s = TaskState.create(goal, 1.0)
    s.meta["goal_elaborated"] = goal
    return s


def test_discovery_called_before_architect(tmp_path):
    """When goal is vague, discovery.run_discovery is called in _freshRunPhase."""
    from platform_core.orchestration.run_phase_mixin import OrchestratorRunPhaseMixin

    call_order = []
    fake_report = mock.Mock()
    fake_report.findings = []   # a real DiscoveryReport.findings is a list; _runDiscoveryPhase does len(report.findings)
    fake_report.to_dict.return_value = {
        "theme_suggestion": "t", "findings": [], "innovation_ratio": 0.5
    }

    with mock.patch("agents.discovery.run_discovery",
                    side_effect=lambda *a, **k: (call_order.append("discovery"), fake_report)[1]), \
         mock.patch("agents.architect.authorArchitectPrompt",
                    side_effect=lambda *a, **k: (call_order.append("architect"), "arch prompt")[1]):

        mixin = OrchestratorRunPhaseMixin.__new__(OrchestratorRunPhaseMixin)
        mixin._checkControl = mock.Mock()
        mixin._ollamaChat = mock.Mock(return_value="")
        mixin._run_claude = mock.Mock(return_value={"content": "# Architecture\n" + "x" * 300})
        mixin._execCwd = mock.Mock(return_value=str(tmp_path))
        mixin.obs = mock.Mock()
        mixin.obs.readNote = mock.Mock(return_value=None)
        mixin.obs.writeNote = mock.Mock()
        mixin._architectureReview = mock.Mock(side_effect=lambda state, doc, dash: doc)
        mixin.authorSubtaskPlan = mock.Mock(return_value=[])
        mixin.critiqueSubtaskPlan = mock.Mock(return_value=[])
        mixin._strengthenPlanVerifies = mock.Mock(return_value=[])
        mixin._planReview = mock.Mock()
        mixin.writeIndex = mock.Mock()
        mixin._state_lock = mock.Mock()

        state = _make_minimal_state("improve everything")
        bus = mock.Mock()
        bus.isAbort.return_value = False
        dashboard = mock.Mock()

        with mock.patch("notifications.discord_bot.sendEmbed"), \
             mock.patch("notifications.cast.speak"), \
             mock.patch("agents.verifier.sanitizeVerify", side_effect=lambda v: v):
            try:
                mixin._freshRunPhase(state, str(tmp_path), bus, dashboard, "improve everything")
            except Exception:
                pass  # partial execution OK — we only care about call order

    assert "discovery" in call_order
    assert call_order.index("discovery") < call_order.index("architect")


def test_discovery_report_stored_in_state(tmp_path):
    """Discovery report is saved to state.meta['discovery_report'] when it runs."""
    from platform_core.orchestration.run_phase_mixin import OrchestratorRunPhaseMixin

    fake_report = mock.Mock()
    fake_report.findings = []
    fake_report.to_dict.return_value = {
        "theme_suggestion": "transform orchestrator",
        "findings": [{"rank": 1, "title": "Rewrite run loop"}],
        "innovation_ratio": 0.8,
    }

    with mock.patch("agents.discovery.run_discovery", return_value=fake_report), \
         mock.patch("agents.architect.authorArchitectPrompt", return_value="arch prompt"), \
         mock.patch("notifications.discord_bot.sendEmbed"), \
         mock.patch("notifications.cast.speak"):

        mixin = OrchestratorRunPhaseMixin.__new__(OrchestratorRunPhaseMixin)
        mixin._checkControl = mock.Mock()
        mixin._ollamaChat = mock.Mock(return_value="")
        mixin._run_claude = mock.Mock(return_value={"content": "# Architecture\n" + "x" * 300})
        mixin._execCwd = mock.Mock(return_value=str(tmp_path))
        mixin.obs = mock.Mock()
        mixin.obs.writeNote = mock.Mock()
        mixin._architectureReview = mock.Mock(side_effect=lambda state, doc, dash: doc)
        mixin.authorSubtaskPlan = mock.Mock(return_value=[])
        mixin.critiqueSubtaskPlan = mock.Mock(return_value=[])
        mixin._strengthenPlanVerifies = mock.Mock(return_value=[])
        mixin._planReview = mock.Mock()
        mixin.writeIndex = mock.Mock()

        state = _make_minimal_state("improve everything")
        bus = mock.Mock()
        bus.isAbort.return_value = False
        dashboard = mock.Mock()

        with mock.patch("agents.verifier.sanitizeVerify", side_effect=lambda v: v):
            try:
                mixin._freshRunPhase(state, str(tmp_path), bus, dashboard, "improve everything")
            except Exception:
                pass

    assert state.meta.get("discovery_report") is not None
