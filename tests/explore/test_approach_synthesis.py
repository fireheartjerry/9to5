"""Tests for explore.approach_synthesis and the exploreSolutionSpace facade."""
from __future__ import annotations

from introspect import extractProject
from tests.factories import fake_brain

from explore import exploreSolutionSpace
from explore.approach_gen import ApproachCandidate, generateApproaches
from explore.approach_synthesis import MITIGATION_MARKERS, selectOrSynthesize
from explore.approach_tradeoffs import TradeoffScore, scoreApproaches


def _cand(cid: str, files: int, steps: tuple[str, ...]) -> ApproachCandidate:
    return ApproachCandidate(
        approach_id=cid,
        title=f"title {cid}",
        summary=f"summary {cid}",
        steps=steps,
        files_touched_estimate=files,
        archetype="minimal-patch",
    )


def _score(cid: str, total: float) -> TradeoffScore:
    return TradeoffScore(
        approach_id=cid, risk=0.5, effort=0.5, testability=0.5, fit=0.5, total=total
    )


def test_synthesis_tiebreak_and_mitigation(fixture_project):
    r1 = exploreSolutionSpace("add input validation to pkg.core", fixture_project, n=3)
    r2 = exploreSolutionSpace("add input validation to pkg.core", fixture_project, n=3)
    assert r1.winner.approach_id == r2.winner.approach_id  # reproducible
    assert r1.rationale
    assert r1 == r2
    assert len(r1.adopted_mitigations) <= 2
    for step in r1.adopted_mitigations:
        assert any(m in step.lower() for m in MITIGATION_MARKERS)
        assert step not in r1.winner.steps


def test_tiebreak_fewer_files_then_lowest_id():
    cands = [
        _cand("a1", 5, ("do it",)),
        _cand("a2", 2, ("do it smaller",)),
        _cand("a3", 2, ("do it too",)),
    ]
    scores = [_score("a1", 0.8), _score("a2", 0.8), _score("a3", 0.8)]
    result = selectOrSynthesize(cands, scores)
    # equal totals -> fewer files wins; equal files -> lowest approach_id
    assert result.winner.approach_id == "a2"


def test_mitigations_lifted_from_runners_up():
    cands = [
        _cand("a1", 1, ("edit the module",)),
        _cand("a2", 2, ("add a rollback plan", "guard the seam", "verify output")),
    ]
    scores = [_score("a1", 0.9), _score("a2", 0.5)]
    result = selectOrSynthesize(cands, scores)
    assert result.winner.approach_id == "a1"
    assert len(result.adopted_mitigations) == 2  # capped at 2
    for step in result.adopted_mitigations:
        assert step in cands[1].steps


def test_rationale_cites_score_components(fixture_project):
    m = extractProject(fixture_project, use_cache=False)
    cands = generateApproaches("goal", m, n=3)
    scores = scoreApproaches(cands, m)
    result = selectOrSynthesize(cands, scores)
    for word in ("risk", "effort", "testability", "fit"):
        assert word in result.rationale.lower()


def test_brain_rewords_rationale_only(fixture_project):
    m = extractProject(fixture_project, use_cache=False)
    cands = generateApproaches("goal", m, n=3)
    scores = scoreApproaches(cands, m)
    plain = selectOrSynthesize(cands, scores)
    brained = selectOrSynthesize(cands, scores, brain=fake_brain(reply="Nicer words."))
    assert brained.rationale == "Nicer words."
    assert brained.winner == plain.winner
    assert brained.scores == plain.scores
    assert brained.adopted_mitigations == plain.adopted_mitigations


def test_facade_accepts_model_or_path(fixture_project):
    m = extractProject(fixture_project, use_cache=False)
    from_model = exploreSolutionSpace("goal", m, n=3)
    from_path = exploreSolutionSpace("goal", fixture_project, n=3)
    assert from_model.winner.approach_id == from_path.winner.approach_id
    assert from_model.winner.archetype == from_path.winner.archetype
