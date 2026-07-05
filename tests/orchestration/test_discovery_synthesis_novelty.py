"""Novelty-weighted synthesis scoring: MEASURED novelty dominates self-reported innovation."""
from agents.discovery import synthesis
from agents.discovery.models import Finding


def _f(title, impact, spec, innov, nov):
    return Finding(title=title, type="new_capability", impact=impact, specificity=spec,
                   innovation=innov, rationale="r", affected_files=[], source_lens="l",
                   measured_novelty=nov)


def test_novelty_blend_weights_measured_over_self():
    assert synthesis._W_MEASURED_NOVELTY > synthesis._W_SELF_INNOV
    hi = _f("a", 5, 5, 1, 1.0)      # low self-innov, HIGH measured novelty
    lo = _f("b", 5, 5, 5, 0.0)      # high self-innov, ZERO measured novelty
    assert synthesis._score_novelty(hi) > synthesis._score_novelty(lo)


def test_score_novelty_scale_matches_legacy_magnitude():
    f = _f("a", 4, 3, 5, 1.0)       # blend = 0.25*1 + 0.75*1 = 1.0 -> 4*3*5 = 60
    assert abs(synthesis._score_novelty(f) - 60.0) < 1e-6


def test_synthesize_ranks_by_novelty_when_measured(monkeypatch):
    findings = [_f("boring", 5, 5, 5, 0.0), _f("novel", 4, 4, 1, 1.0)]
    monkeypatch.setattr(synthesis, "_apply_measured_novelty", lambda fs: True)   # already set
    monkeypatch.setattr(synthesis, "_get_theme", lambda fs, chat=None: "t")
    rep = synthesis.synthesize(findings)
    assert rep.findings[0].title == "novel"       # novelty beat higher self-reported innovation


def test_synthesize_falls_back_to_legacy_when_unmeasured(monkeypatch):
    findings = [_f("boring", 5, 5, 5, 0.0), _f("novel", 4, 4, 1, 1.0)]
    monkeypatch.setattr(synthesis, "_apply_measured_novelty", lambda fs: False)  # no embeddings
    monkeypatch.setattr(synthesis, "_get_theme", lambda fs, chat=None: "t")
    rep = synthesis.synthesize(findings)
    assert rep.findings[0].title == "boring"      # legacy: high impact*spec*innovation wins
