from unittest import mock
import pytest

from agents.discovery import models
import agents.discovery as discovery


def _fake_report():
    f = models.Finding("Bold reimagining", "reimagining", 5, 4, 5, "r", [], "lens_3")
    f.rank = 1
    return models.DiscoveryReport(theme_suggestion="transform the orchestrator", findings=[f])


def test_should_run_full_discovery_vague_goal():
    assert discovery.shouldRunFullDiscovery("improve everything") is True
    assert discovery.shouldRunFullDiscovery("") is True
    assert discovery.shouldRunFullDiscovery("do your best") is True
    assert discovery.shouldRunFullDiscovery("optimize") is True


def test_should_run_full_discovery_specific_goal():
    assert discovery.shouldRunFullDiscovery("fix the bug in run_loop.py") is False
    assert discovery.shouldRunFullDiscovery("add unit tests for elaborator.py") is False


def test_run_discovery_full_returns_report(tmp_path):
    fake = _fake_report()
    with mock.patch("agents.discovery.digest.compile_digest", return_value={}) as md, \
         mock.patch("agents.discovery.lenses.run_lens_panel", return_value=fake.findings) as ml, \
         mock.patch("agents.discovery.synthesis.synthesize", return_value=fake) as ms:
        result = discovery.run_discovery(str(tmp_path), "improve everything")
    assert result is not None
    assert result.theme_suggestion == "transform the orchestrator"
    md.assert_called_once()
    ml.assert_called_once()
    ms.assert_called_once()


def test_run_discovery_specific_goal_returns_none(tmp_path):
    with mock.patch("agents.discovery.digest.compile_digest", return_value={}) as md, \
         mock.patch("agents.discovery.lenses.run_lens_panel") as ml:
        result = discovery.run_discovery(str(tmp_path), "fix the bug in elaborator.py line 42")
    assert result is None
    md.assert_called_once()   # digest always compiled
    ml.assert_not_called()    # lenses skipped for specific goals


def test_run_discovery_never_raises(tmp_path):
    with mock.patch("agents.discovery.digest.compile_digest", side_effect=RuntimeError("boom")):
        result = discovery.run_discovery(str(tmp_path), "improve everything")
    assert result is None
