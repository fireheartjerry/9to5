"""Deterministic evidence extraction: Aho-Corasick matching + fact-vs-risk signals."""
from platform_core.orchestration import evidence_extract as ee


def test_aho_corasick_finds_all_patterns():
    ac = ee.AhoCorasick()
    ac.add("he", "x")
    ac.add("she", "y")
    ac.add("hers", "z")
    ac.build()
    found = {(p, t) for _, p, t in ac.find("ushers")}
    assert ("she", "y") in found
    assert ("he", "x") in found
    assert ("hers", "z") in found


def test_extract_finds_test_pass_evidence():
    e = ee.extract_evidence("=== 5 passed in 1.20s ===")
    assert e["supported"] is True
    assert "test_pass" in e["counts"]
    assert any(r.startswith("test_pass") for r in e["evidence_refs"])


def test_extract_finds_factsgate_receipt():
    e = ee.extract_evidence("VERIFIED — receipt sha abc123")
    assert ee.supports_claim(e) is True
    assert "factsgate" in e["counts"]


def test_extract_rejects_unsupported_prose():
    e = ee.extract_evidence("I think this is a really nice improvement to the system.")
    assert e["supported"] is False
    assert ee.supports_claim(e) is False


def test_todo_fixme_lowers_confidence():
    e = ee.extract_evidence("added feature # TODO handle edge case, FIXME later")
    assert e["risk_markers"] >= 2
    assert ee.confidence_adjust(0.9, e) < 0.9
    # penalty is capped at 3 markers
    assert ee.confidence_adjust(0.9, {"risk_markers": 99}) == 0.6


def test_module_names_become_refs():
    e = ee.extract_evidence("edited memory/x.py and platform_core/foo.py",
                            module_names=["memory/x.py", "notpresent.py"])
    assert "memory/x.py" in e["modules"]
    assert "notpresent.py" not in e["modules"]
    assert "module:memory/x.py" in e["evidence_refs"]


def test_empty_text_is_unsupported():
    e = ee.extract_evidence("")
    assert e["supported"] is False
    assert e["evidence_refs"] == []
