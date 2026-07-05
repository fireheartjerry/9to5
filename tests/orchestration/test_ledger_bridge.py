"""Finder-to-ledger bridge: pure routing + registration of invention seeds."""
import pytest

from agents.discovery import ledger_bridge as lb
from agents.discovery.models import Finding
from memory import experience
from memory import experience_evolution as ee
from platform_core.orchestration.invention_types import FindingCandidate


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "exp.db"
    experience._reset_schema_cache()
    experience.init(p)
    yield p
    experience._reset_schema_cache()


def _fc(**kw):
    d = dict(id="", kind="feature", title="T", design_sketch="do it",
             target_subsystems=["memory/x.py"], measured_novelty=0.9, impact=0.9,
             confidence=0.9, risk="low")
    d.update(kw)
    return FindingCandidate(**d)


_TH = dict(novelty_floor=0.55, novelty_hi=0.75, conf_hi=0.80)


def test_route_audit_shaped_is_skipped():
    assert lb.route_candidate(_fc(design_sketch="", target_subsystems=[]), **_TH) == "skipped"


def test_route_low_novelty_is_improvement():
    assert lb.route_candidate(_fc(measured_novelty=0.2), **_TH) == "improvement"


def test_route_low_confidence_is_proposal():
    assert lb.route_candidate(_fc(confidence=0.3), **_TH) == "proposal"


def test_route_ideal_is_auto_run_eligible():
    assert lb.route_candidate(_fc(measured_novelty=0.9, risk="low", confidence=0.9), **_TH) \
        == "auto_run_eligible"


def test_route_novel_but_risky_is_proposal():
    assert lb.route_candidate(_fc(measured_novelty=0.9, risk="high", confidence=0.9), **_TH) \
        == "proposal"


def test_route_high_impact_mid_novelty_is_qd_seed():
    assert lb.route_candidate(_fc(measured_novelty=0.6, impact=0.9, confidence=0.6, risk="low"),
                              **_TH) == "qd_seed"


def _finding(title, **kw):
    d = dict(title=title, type="new_capability", impact=5, specificity=4, innovation=5,
             rationale="r", affected_files=[], source_lens="l", candidate_kind="new_capability",
             design_sketch="build", target_subsystems=["memory/x.py"], measured_novelty=0.9,
             confidence=0.9, risk="low")
    d.update(kw)
    return Finding(**d)


class _Report:
    def __init__(self, findings):
        self.findings = findings


def test_bridge_registers_inventions_and_skips_audit(db):
    findings = [
        _finding("Feat"),                                            # -> auto_run_eligible (feature)
        Finding(title="Audit", type="health", impact=3, specificity=3, innovation=1,
                rationale="r", affected_files=[], source_lens="l"),  # -> skipped
        _finding("Improve", measured_novelty=0.2),                   # -> improvement
    ]
    out = lb.bridge_report(_Report(findings), run_id="r1", db_path=db, record=False)
    assert out["routes"]["Feat"] == "auto_run_eligible"
    assert out["routes"]["Audit"] == "skipped"
    assert out["routes"]["Improve"] == "improvement"

    feats = ee.fetch_candidates(kind="feature", db_path=db)
    assert len(feats) == 1
    assert feats[0]["measured_novelty"] == 0.9
    assert feats[0]["subsystem"] == "memory/x.py"
    # provenance preserved (route + lens + run_id)
    import json
    prov = json.loads(feats[0]["provenance_json"])
    assert prov["route"] == "auto_run_eligible" and prov["run_id"] == "r1"

    improvements = ee.fetch_candidates(kind="improvement", db_path=db)
    assert len(improvements) == 1
    assert out["counts"]["skipped"] == 1


def test_finding_to_candidate_normalizes_scales():
    fc = lb.finding_to_candidate(_finding("F"), run_id="r1")
    assert 0.0 <= fc.impact <= 1.0 and fc.impact == 1.0        # 5/5
    assert fc.specificity == 0.8                                # 4/5
    assert fc.kind == "feature"
    assert fc.provenance["run_id"] == "r1"
