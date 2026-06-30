"""Epic 2 staged-default config knobs are exposed via the config facade."""
import config


def test_dual_ledger_default_off():
    assert config.DUAL_LEDGER_PLANNER_ENABLED is False


def test_independent_verify_default_on():
    assert config.INDEPENDENT_VERIFY_ENABLED is True


def test_evidence_receipt_default_on():
    assert config.EVIDENCE_RECEIPT_ENABLED is True


def test_retry_and_stall_ints():
    assert config.BRAIN_JSON_RETRY_MAX == 2
    assert config.STALL_THRESHOLD == 2
