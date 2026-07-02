"""Epic 2 staged-default config knobs: coded defaults locked, facade exposure live.

R12: a production install .env may legitimately flip the staged flags, so the
default-off/on guarantees are asserted on the CODED defaults (env keys scrubbed).
"""
import config
from platform_core.app_config.settings import EpicFlags


def _cleanFlags(monkeypatch) -> EpicFlags:
    for k in ("DUAL_LEDGER_PLANNER_ENABLED", "INDEPENDENT_VERIFY_ENABLED",
              "EVIDENCE_RECEIPT_ENABLED", "BRAIN_JSON_RETRY_MAX", "STALL_THRESHOLD"):
        monkeypatch.delenv(k, raising=False)
    return EpicFlags()


def test_dual_ledger_default_off(monkeypatch):
    assert _cleanFlags(monkeypatch).DUAL_LEDGER_PLANNER_ENABLED is False


def test_independent_verify_default_on(monkeypatch):
    assert _cleanFlags(monkeypatch).INDEPENDENT_VERIFY_ENABLED is True


def test_evidence_receipt_default_on(monkeypatch):
    assert _cleanFlags(monkeypatch).EVIDENCE_RECEIPT_ENABLED is True


def test_retry_and_stall_ints(monkeypatch):
    flags = _cleanFlags(monkeypatch)
    assert flags.BRAIN_JSON_RETRY_MAX == 2
    assert flags.STALL_THRESHOLD == 2


def test_epic2_knobs_exposed_via_facade():
    assert isinstance(config.DUAL_LEDGER_PLANNER_ENABLED, bool)
    assert isinstance(config.INDEPENDENT_VERIFY_ENABLED, bool)
    assert isinstance(config.EVIDENCE_RECEIPT_ENABLED, bool)
    assert isinstance(config.BRAIN_JSON_RETRY_MAX, int)
    assert isinstance(config.STALL_THRESHOLD, int)
