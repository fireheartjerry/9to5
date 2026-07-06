"""Tests for human_nature/instinct_signal.py (streaming instinct engine output)."""
from __future__ import annotations

import pytest

from human_nature.instinct_signal import InstinctSignal, from_dict


def _valid_kwargs(**overrides):
    kwargs = dict(
        motif_id="motif-123",
        match_type="exact",
        confidence=0.8,
        severity=0.4,
        expected_loss_if_ignored=0.2,
        recommended_action="pause",
        authority_request="soft",
    )
    kwargs.update(overrides)
    return kwargs


def test_construct_valid_signal():
    sig = InstinctSignal(**_valid_kwargs())
    assert sig.motif_id == "motif-123"
    assert sig.match_type == "exact"
    assert sig.confidence == 0.8
    assert sig.severity == 0.4
    assert sig.recommended_action == "pause"
    assert sig.authority_request == "soft"
    assert sig.evidence_events == []
    assert sig.matched_history_refs == []


def test_to_dict_from_dict_round_trip():
    sig = InstinctSignal(**_valid_kwargs(
        evidence_events=["e1", "e2"],
        matched_history_refs=["h1"],
    ))
    d = sig.to_dict()
    restored = from_dict(d)
    assert restored == sig


def test_bad_match_type_raises():
    with pytest.raises(ValueError):
        InstinctSignal(**_valid_kwargs(match_type="bogus"))


def test_bad_recommended_action_raises():
    with pytest.raises(ValueError):
        InstinctSignal(**_valid_kwargs(recommended_action="bogus"))


def test_bad_authority_request_raises():
    with pytest.raises(ValueError):
        InstinctSignal(**_valid_kwargs(authority_request="bogus"))


def test_confidence_clamps_above_one():
    sig = InstinctSignal(**_valid_kwargs(confidence=1.5))
    assert sig.confidence == 1.0


def test_confidence_clamps_below_zero():
    sig = InstinctSignal(**_valid_kwargs(confidence=-0.5))
    assert sig.confidence == 0.0


def test_severity_clamps_above_one():
    sig = InstinctSignal(**_valid_kwargs(severity=2.0))
    assert sig.severity == 1.0


def test_severity_clamps_below_zero():
    sig = InstinctSignal(**_valid_kwargs(severity=-1.0))
    assert sig.severity == 0.0
