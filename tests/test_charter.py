"""Tests for human_nature/charter.py — Living Constitution (human-gated).

RUN: python -m pytest tests/test_charter.py -v
"""
from __future__ import annotations

import pathlib

import pytest
from human_nature.charter import (
    active_tenets,
    draft_amendment,
    new_charter,
    ratify,
)

# ---------------------------------------------------------------------------
# new_charter()
# ---------------------------------------------------------------------------

class TestNewCharter:
    def test_version_starts_at_1(self):
        assert new_charter()["version"] == 1

    def test_ratified_list_is_empty(self):
        assert new_charter()["ratified"] == []


# ---------------------------------------------------------------------------
# draft_amendment()
# ---------------------------------------------------------------------------

class TestDraftAmendment:
    def test_returns_proposed_amendment(self):
        a = draft_amendment("Hold composition over inheritance.", "3 runs paid off")
        assert a["text"] == "Hold composition over inheritance."
        assert a["evidence"] == "3 runs paid off"
        assert a["status"] == "proposed"

    def test_amendment_has_uuid_id(self):
        import uuid
        a = draft_amendment("test tenet", "some evidence")
        # must be a valid UUID4 string
        parsed = uuid.UUID(a["id"], version=4)
        assert str(parsed) == a["id"]

    def test_draft_does_not_ratify(self):
        charter = new_charter()
        draft_amendment("some tenet", "evidence")
        # charter must be unchanged
        assert charter["ratified"] == []
        assert charter["version"] == 1

    def test_two_drafts_have_distinct_ids(self):
        a1 = draft_amendment("tenet A", "ev A")
        a2 = draft_amendment("tenet B", "ev B")
        assert a1["id"] != a2["id"]


# ---------------------------------------------------------------------------
# ratify() — requires human_token; raises PermissionError without one
# ---------------------------------------------------------------------------

class TestRatify:
    def test_ratify_without_token_raises_permission_error(self):
        charter = new_charter()
        amendment = draft_amendment("No manipulation.", "clear from spec")
        with pytest.raises(PermissionError, match="human ratification"):
            ratify(charter, amendment, human_token=None)

    def test_ratify_with_empty_string_token_raises_permission_error(self):
        charter = new_charter()
        amendment = draft_amendment("No manipulation.", "clear from spec")
        with pytest.raises(PermissionError, match="human ratification"):
            ratify(charter, amendment, human_token="")

    def test_ratify_with_false_token_raises_permission_error(self):
        charter = new_charter()
        amendment = draft_amendment("No manipulation.", "clear from spec")
        with pytest.raises(PermissionError, match="human ratification"):
            ratify(charter, amendment, human_token=False)

    def test_ratify_with_valid_token_appends_amendment(self):
        charter = new_charter()
        amendment = draft_amendment("Propose, never self-apply.", "core tenet")
        new_c = ratify(charter, amendment, human_token="jerry-2026-06-28")
        assert len(new_c["ratified"]) == 1
        assert new_c["ratified"][0] == {**amendment, "status": "ratified"}
        assert new_c["ratified"][0] is not amendment
        assert new_c["ratified"][0]["status"] == "ratified"

    def test_ratify_bumps_version(self):
        charter = new_charter()
        amendment = draft_amendment("Tenet", "evidence")
        new_c = ratify(charter, amendment, human_token="tok")
        assert new_c["version"] == 2

    def test_ratify_does_not_mutate_input_charter(self):
        charter = new_charter()
        amendment = draft_amendment("Tenet", "evidence")
        ratify(charter, amendment, human_token="tok")
        assert charter["ratified"] == []
        assert charter["version"] == 1

    def test_multiple_ratifications_accumulate(self):
        charter = new_charter()
        a1 = draft_amendment("Tenet A", "ev A")
        a2 = draft_amendment("Tenet B", "ev B")
        c1 = ratify(charter, a1, human_token="tok")
        c2 = ratify(c1, a2, human_token="tok")
        assert len(c2["ratified"]) == 2
        assert c2["version"] == 3

    def test_ratify_amendment_is_isolated_from_later_mutation(self):
        ch = new_charter()
        amd = draft_amendment("keep composition over inheritance", "won 9/10 runs")
        ch2 = ratify(ch, amd, human_token="jerry")
        amd["text"] = "CORRUPTED"
        assert ch2["ratified"][0]["text"] == "keep composition over inheritance"


# ---------------------------------------------------------------------------
# active_tenets()
# ---------------------------------------------------------------------------

class TestActiveTenets:
    def test_empty_charter_has_no_tenets(self):
        assert active_tenets(new_charter()) == []

    def test_returns_ratified_amendment_texts(self):
        charter = new_charter()
        a = draft_amendment("No manipulation.", "evidence")
        charter2 = ratify(charter, a, human_token="tok")
        tenets = active_tenets(charter2)
        assert tenets == ["No manipulation."]

    def test_returns_texts_in_ratification_order(self):
        charter = new_charter()
        a1 = draft_amendment("First.", "ev")
        a2 = draft_amendment("Second.", "ev")
        c1 = ratify(charter, a1, human_token="tok")
        c2 = ratify(c1, a2, human_token="tok")
        assert active_tenets(c2) == ["First.", "Second."]

    def test_only_ratified_amendments_appear(self):
        charter = new_charter()
        a1 = draft_amendment("Ratified.", "ev")
        _draft_only = draft_amendment("Drafted only.", "ev")
        c1 = ratify(charter, a1, human_token="tok")
        # the draft-only amendment was never ratified
        assert active_tenets(c1) == ["Ratified."]


# ---------------------------------------------------------------------------
# cast-charter.md file content test
# ---------------------------------------------------------------------------

CHARTER_PATH = (
    pathlib.Path(__file__).parent.parent / "docs" / "human-nature" / "cast-charter.md"
)


class TestCastCharterDocument:
    def test_file_exists(self):
        assert CHARTER_PATH.exists(), f"cast-charter.md not found at {CHARTER_PATH}"

    def test_contains_no_manipulation_tenet(self):
        text = CHARTER_PATH.read_text(encoding="utf-8")
        assert "manipulation" in text.lower(), "charter must contain no-manipulation tenet"

    def test_contains_propose_not_apply_tenet(self):
        text = CHARTER_PATH.read_text(encoding="utf-8")
        assert "propose" in text.lower(), "charter must contain propose-not-apply language"
        assert "self-apply" in text.lower() or "never self-apply" in text.lower() or "never applies" in text.lower(), (
            "charter must explicitly forbid self-application"
        )

    def test_contains_earned_autonomy_reference(self):
        text = CHARTER_PATH.read_text(encoding="utf-8")
        assert "autonomy" in text.lower()

    def test_contains_access_vs_phenomenal_distinction(self):
        text = CHARTER_PATH.read_text(encoding="utf-8")
        assert "phenomenal" in text.lower()
