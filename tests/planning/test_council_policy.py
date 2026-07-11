from types import SimpleNamespace

from agents.planning.council_policy import CouncilPolicy, CouncilSeatReceipt, receipts_from_brief


def test_mock_and_fallback_never_count_as_live():
    receipt = CouncilSeatReceipt("gpt", requested_mode="live", actual_mode="degraded", fallback_reason="timeout")
    outcome = CouncilPolicy("advisory").evaluate("normal task", [receipt])
    assert outcome.status == "degraded"
    assert outcome.live_seat_count == 0


def test_risk_gate_pauses_only_typed_high_risk_work():
    live = CouncilSeatReceipt("gemini", requested_mode="live", actual_mode="live")
    assert CouncilPolicy("risk_gate").evaluate("delete a production record", [live]).status == "pause"
    assert CouncilPolicy("risk_gate").evaluate("rename a local helper", [live]).status == "allow"


def test_risk_gate_pauses_high_risk_work_when_live_council_is_degraded():
    degraded = CouncilSeatReceipt("local", requested_mode="live", actual_mode="degraded", fallback_reason="offline")
    assert CouncilPolicy("risk_gate").evaluate("delete a production record", [degraded]).status == "pause"
    assert CouncilPolicy("risk_gate").evaluate("rename a local helper", [degraded]).status == "degraded"


def test_legacy_provider_summary_preserves_actual_live_truth():
    brief = SimpleNamespace(provider_run_summaries=[{
        "seat_name": "Local LLM",
        "requested_live": True,
        "actual_live_any": True,
        "fallback_turn_count": 0,
        "latency_ms": 31,
        "response_digest": "a" * 16,
        "last_provider_state": "fully_live",
    }])

    (receipt,) = receipts_from_brief(brief)

    assert receipt.actual_mode == "live"
    assert receipt.live is True
    assert receipt.latency_ms == 31
    assert receipt.response_digest == "a" * 16
