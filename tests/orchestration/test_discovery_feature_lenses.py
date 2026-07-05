"""Feature-seeking lenses: invention-field parsing, corpus injection, moonshot under transformative.

The LLM seam (_brain_call) is monkeypatched so these run offline and deterministically.
"""
from agents.discovery import lenses


def test_invention_fields_parsed():
    raw = {"title": "X", "type": "new_capability", "candidate_kind": "architecture_unlock",
           "impact": 5, "specificity": 4, "innovation": 5, "confidence": 0.9, "risk": "low",
           "target_subsystems": ["memory/x.py"], "design_sketch": "do X", "verification_plan": "test X"}
    f = lenses._to_finding(raw, "lens_3")
    assert f.candidate_kind == "architecture_unlock"
    assert f.design_sketch == "do X"
    assert f.verification_plan == "test X"
    assert f.target_subsystems == ["memory/x.py"]
    assert f.risk == "low" and f.confidence == 0.9


def test_invalid_candidate_kind_and_risk_defaulted():
    raw = {"title": "X", "impact": 3, "specificity": 3, "innovation": 3, "candidate_kind": "bogus",
           "risk": "spicy", "design_sketch": "s", "target_subsystems": ["a"]}
    f = lenses._to_finding(raw, "lens_4")
    assert f.candidate_kind == ""            # unknown kind dropped
    assert f.risk == "medium"                # unknown risk defaulted


def test_build_tasks_adds_moonshot_only_when_transformative():
    names_t = {n for _, n in lenses._build_tasks({}, None, "", True)}
    names_f = {n for _, n in lenses._build_tasks({}, None, "", False)}
    assert "_lens_6_moonshot" in names_t
    assert "_lens_6_moonshot" not in names_f
    assert "_lens_3_architectural_reimagining" in names_f  # feature lenses always present


def test_feature_lens_injects_corpus(monkeypatch):
    captured = {}

    def fake_brain(system, user, retries=2, chat=None):
        captured["user"] = user
        return []
    monkeypatch.setattr(lenses, "_brain_call", fake_brain)
    lenses._lens_4_missing_capabilities({"architecture": "arch"}, None, "PRIOR_ART_XYZ")
    assert "PRIOR_ART_XYZ" in captured["user"]


def test_feature_lens_produces_concrete_feature(monkeypatch):
    def fake_brain(system, user, retries=2, chat=None):
        return [{"title": "New cap", "type": "new_capability", "candidate_kind": "new_capability",
                 "impact": 5, "specificity": 4, "innovation": 5, "confidence": 0.8, "risk": "low",
                 "target_subsystems": ["memory/x.py"], "design_sketch": "build it",
                 "verification_plan": "prove it"}]
    monkeypatch.setattr(lenses, "_brain_call", fake_brain)
    out = lenses._lens_3_architectural_reimagining({}, None, "")
    assert len(out) == 1
    assert out[0].candidate_kind == "new_capability"
    assert out[0].design_sketch == "build it"
    assert out[0].target_subsystems == ["memory/x.py"]


def test_run_lens_panel_transformative_runs_moonshot(monkeypatch):
    seen = []

    def fake_brain(system, user, retries=2, chat=None):
        seen.append(system)
        return []
    monkeypatch.setattr(lenses, "_brain_call", fake_brain)
    monkeypatch.setattr(lenses, "_corpus_for", lambda d: "")
    lenses.run_lens_panel({}, None, transformative=True)
    assert any("MOONSHOT" in s for s in seen)          # moonshot lens actually ran


def test_run_lens_panel_non_transformative_skips_moonshot(monkeypatch):
    seen = []

    def fake_brain(system, user, retries=2, chat=None):
        seen.append(system)
        return []
    monkeypatch.setattr(lenses, "_brain_call", fake_brain)
    lenses.run_lens_panel({}, None, transformative=False)
    assert not any("MOONSHOT" in s for s in seen)
