"""OrchestratorSafetyMixin routing: classify -> decide -> route (Epic 4 unit c)."""
import types
import pytest
import config
from platform_core.runtime.control import ControlBus, AbortRun
from platform_core.runtime import autonomy_allowance as al
from platform_core.runtime.action_risk import ActionDescriptor
from platform_core.orchestration.safety_mixin import OrchestratorSafetyMixin


class _FakeState:
    def __init__(self, mode):
        self.meta = {"control_mode": mode}


class _FakeDash:
    def update(self, *a, **k):
        pass

    def event(self, *a, **k):
        pass


def _orch(monkeypatch, tmp_path, gate_behavior=None):
    """Build a bare object exposing the mixin + a stub _handleOtherGate."""
    monkeypatch.setattr(config, "CONTROL_DIR", tmp_path, raising=False)
    monkeypatch.setattr(config, "SEMANTIC_SAFETY_ENABLED", True, raising=False)
    obj = types.SimpleNamespace()
    obj._authorizeAction = OrchestratorSafetyMixin._authorizeAction.__get__(obj)
    obj._autonomousVerdict = OrchestratorSafetyMixin._autonomousVerdict.__get__(obj)
    obj._handleOtherGate = gate_behavior or (lambda *a, **k: None)  # default: approve
    return obj


def test_read_auto_authorizes(monkeypatch, tmp_path):
    obj = _orch(monkeypatch, tmp_path)
    bus = ControlBus("t-read")
    ok = obj._authorizeAction(_FakeState("gated"), bus, _FakeDash(),
                              ActionDescriptor(tool_name="Read"))
    assert ok is True


def test_disabled_flag_is_passthrough(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SEMANTIC_SAFETY_ENABLED", False, raising=False)
    obj = _orch(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "SEMANTIC_SAFETY_ENABLED", False, raising=False)
    bus = ControlBus("t-off")
    ok = obj._authorizeAction(_FakeState("watch"), bus, _FakeDash(),
                              ActionDescriptor(command="rm -rf /"))
    assert ok is True  # layer disabled -> clean passthrough


def test_gated_destructive_approve_returns_true(monkeypatch, tmp_path):
    obj = _orch(monkeypatch, tmp_path, gate_behavior=lambda *a, **k: None)  # approve
    bus = ControlBus("t-approve")
    ok = obj._authorizeAction(_FakeState("gated"), bus, _FakeDash(),
                              ActionDescriptor(command="rm -rf /"))
    assert ok is True


def test_gated_destructive_reject_returns_false(monkeypatch, tmp_path):
    def _reject(*a, **k):
        raise AbortRun("gate 'action_risk' rejected")
    obj = _orch(monkeypatch, tmp_path, gate_behavior=_reject)
    bus = ControlBus("t-reject")
    ok = obj._authorizeAction(_FakeState("gated"), bus, _FakeDash(),
                              ActionDescriptor(command="rm -rf /"))
    assert ok is False  # blocked attempt, NOT an aborted run


def test_gated_genuine_abort_propagates(monkeypatch, tmp_path):
    def _abort(*a, **k):
        raise AbortRun("aborted at gate")
    obj = _orch(monkeypatch, tmp_path, gate_behavior=_abort)
    bus = ControlBus("t-abort")
    bus.requestAbort()
    with pytest.raises(AbortRun):
        obj._authorizeAction(_FakeState("gated"), bus, _FakeDash(),
                             ActionDescriptor(command="rm -rf /"))


def test_autonomous_destructive_hard_blocks_under_block_policy(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "AUTONOMOUS_DESTRUCTIVE_POLICY", "block", raising=False)
    obj = _orch(monkeypatch, tmp_path)
    bus = ControlBus("t-auton-b")
    ok = obj._authorizeAction(_FakeState("watch"), bus, _FakeDash(),
                              ActionDescriptor(command="rm -rf /"))
    assert ok is False


def test_autonomous_destructive_hard_blocks_even_under_strict_allowance(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "AUTONOMOUS_DESTRUCTIVE_POLICY", "strict_allowance", raising=False)
    monkeypatch.setattr(config, "AUTONOMOUS_DESTRUCTIVE_ALLOWANCE_USD", 1000.0, raising=False)
    obj = _orch(monkeypatch, tmp_path)
    bus = ControlBus("t-auton-s")
    ok = obj._authorizeAction(_FakeState("watch"), bus, _FakeDash(),
                              ActionDescriptor(command="rm -rf /"))
    assert ok is False  # LOCKED: destructive hard-blocks regardless of allowance


def test_autonomous_unknown_hard_blocks(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "AUTONOMOUS_DESTRUCTIVE_POLICY", "strict_allowance", raising=False)
    obj = _orch(monkeypatch, tmp_path)
    bus = ControlBus("t-auton-u")
    ok = obj._authorizeAction(_FakeState("watch"), bus, _FakeDash(),
                              ActionDescriptor(tool_name="MysteryTool"))
    assert ok is False  # UNKNOWN routes identically to DESTRUCTIVE


def test_autonomous_paid_over_allowance_proceeds(monkeypatch, tmp_path):
    # spec §8: allowance escalation is a GATED-mode concern; autonomy keeps running for non-destructive
    monkeypatch.setattr(config, "AUTONOMY_ALLOWANCE_USD", 0.0, raising=False)
    monkeypatch.setattr(config, "AUTONOMOUS_DESTRUCTIVE_POLICY", "block", raising=False)
    obj = _orch(monkeypatch, tmp_path)
    bus = ControlBus("t-auton-paid")
    ok = obj._authorizeAction(_FakeState("watch"), bus, _FakeDash(),
                              ActionDescriptor(tool_name="ClaudeRun", estimated_cost_usd=0.05))
    assert ok is True
