"""Unit tests for health.collectHealth (structured results)."""
import unittest
import threading
from unittest import mock

import platform_core.ops.health as health


class TestCollectHealth(unittest.TestCase):
    def test_shape(self):
        fake = [("x", lambda: (True, "ok", "")), ("y", lambda: (False, "bad", "fixit"))]
        with mock.patch.object(health, "CHECKS", fake):
            checks = health.collectHealth()
        self.assertEqual(len(checks), 2)
        for c in checks:
            self.assertEqual(set(c), {"name", "ok", "detail", "fix"})
            self.assertIsInstance(c["ok"], bool)
        self.assertFalse(checks[1]["ok"])
        self.assertEqual(checks[1]["fix"], "fixit")

    def test_check_exception_captured(self):
        def boom():
            raise RuntimeError("nope")
        with mock.patch.object(health, "CHECKS", [("z", boom)]):
            checks = health.collectHealth()
        self.assertFalse(checks[0]["ok"])
        self.assertIn("errored", checks[0]["detail"])

    def test_checks_fan_out_without_reordering_results(self):
        started = threading.Barrier(2)

        def slow(name):
            started.wait(timeout=2)
            return True, name, ""

        with mock.patch.object(health, "CHECKS", [("first", lambda: slow("first")), ("second", lambda: slow("second"))]):
            checks = health.collectHealth()
        self.assertEqual([check["name"] for check in checks], ["first", "second"])
def test_health_claude_diagnostic_uses_neutral_probe_not_an_inference_process(monkeypatch):
    from platform_core.execution import provider_probe
    calls = []
    monkeypatch.setattr(provider_probe, "runProviderProbe", lambda kind: (
        calls.append(kind), type("R", (), {"ok": True, "stdout": "ok", "stderr": ""})())[1])
    assert health._claudeCli()[0] is True
    assert calls and all(kind in provider_probe.ProviderProbe for kind in calls)


def test_health_real_delegation_uses_neutral_auth_probe_process(tmp_path):
    import sys
    probe = tmp_path / "provider.py"
    probe.write_text("import sys; print('AUTH_OK' if sys.argv[1:] else 'BAD')", encoding="utf-8")
    ok, detail, _fix = health._claudeCli(probe_executable=[sys.executable, str(probe)])
    assert ok and "AUTH_OK" in detail
