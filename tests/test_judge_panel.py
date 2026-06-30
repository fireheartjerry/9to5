"""Facts-first selection: NOT_VERIFIED can never win; tie-break is deterministic."""
from dataclasses import dataclass

from platform_core.orchestration import judge_panel as jp
from platform_core.orchestration import fork_seams as fs


@dataclass
class FakeBranch:
    branch_id: str
    headline: str
    diff_lines: int = 10
    cost_usd: float = 1.0
    crashed: bool = False


def test_facts_gate_excludes_not_verified_and_crashed():
    branches = [
        FakeBranch("b0", fs.VERIFIED),
        FakeBranch("b1", fs.NOT_VERIFIED),
        FakeBranch("b2", fs.VERIFIED_WITH_GAPS),
        FakeBranch("b3", fs.VERIFIED, crashed=True),
    ]
    eligible = jp.factsGate(branches)
    assert {b.branch_id for b in eligible} == {"b0", "b2"}


def test_empty_eligible_returns_none_winner():
    branches = [FakeBranch("b0", fs.NOT_VERIFIED)]
    scores = jp.scoreBranches(jp.factsGate(branches), goal="g", score_with_brain=None)
    assert jp.pickWinner(scores) is None


def test_verified_beats_gapped_on_facts_alone():
    branches = [FakeBranch("b0", fs.VERIFIED_WITH_GAPS), FakeBranch("b1", fs.VERIFIED)]
    scores = jp.scoreBranches(jp.factsGate(branches), goal="g", score_with_brain=None)
    assert jp.pickWinner(scores) == "b1"


def test_smaller_diff_breaks_tie_among_equal_facts():
    branches = [FakeBranch("b0", fs.VERIFIED, diff_lines=200),
                FakeBranch("b1", fs.VERIFIED, diff_lines=20)]
    scores = jp.scoreBranches(jp.factsGate(branches), goal="g", score_with_brain=None)
    assert jp.pickWinner(scores) == "b1"


def test_tie_break_is_reproducible():
    branches = [FakeBranch("b0", fs.VERIFIED, diff_lines=50, cost_usd=2.0),
                FakeBranch("b1", fs.VERIFIED, diff_lines=50, cost_usd=2.0)]
    scores = jp.scoreBranches(jp.factsGate(branches), goal="g", score_with_brain=None)
    first = jp.pickWinner(scores)
    again = jp.pickWinner(jp.scoreBranches(jp.factsGate(branches), goal="g", score_with_brain=None))
    assert first == again == "b0"          # lowest stable branch_id is the final tiebreak


def test_rubric_is_advisory_only():
    # A VERIFIED_WITH_GAPS branch with a glowing rubric cannot beat a plain VERIFIED one.
    def glowing(goal, branch):
        return {d: 5 for d in jp.JUDGE_RUBRIC}
    branches = [FakeBranch("b0", fs.VERIFIED, diff_lines=10),
                FakeBranch("b1", fs.VERIFIED_WITH_GAPS, diff_lines=10)]
    scores = jp.scoreBranches(jp.factsGate(branches), goal="g",
                              score_with_brain=lambda g, b: glowing(g, b) if b.branch_id == "b1" else {d: 1 for d in jp.JUDGE_RUBRIC})
    assert jp.pickWinner(scores) == "b0"   # facts gate dominates rubric


def test_rubric_llm_failure_does_not_block():
    def boom(goal, branch):
        raise RuntimeError("brain down")
    branches = [FakeBranch("b0", fs.VERIFIED)]
    scores = jp.scoreBranches(jp.factsGate(branches), goal="g", score_with_brain=boom)
    assert jp.pickWinner(scores) == "b0"   # rubric_mean=0, still wins on facts
