"""checkPlanShape deterministically rejects degenerate plans (bernstein vertical-slice)."""
from platform_core.orchestration import plan_shape_check as psc


def _sub(sid, deps=None, verify=None):
    return {"subtask_id": sid, "title": sid, "depends_on": deps or [], "verify": verify}


def test_clean_plan_passes():
    subs = [_sub("st-001", verify={"cmd": "python a.py"}),
            _sub("st-002", deps=["st-001"], verify={"cmd": "python b.py"})]
    assert psc.checkPlanShape(subs, multi_deliverable=True) == []


def test_zero_subtasks_flagged():
    assert any("0 subtasks" in v or "no subtasks" in v.lower() for v in psc.checkPlanShape([]))


def test_over_cap_flagged():
    subs = [_sub(f"st-{i:03d}", verify={"cmd": "x"}) for i in range(1, 20)]
    assert any("MAX_SUBTASKS" in v or "too many" in v.lower() for v in psc.checkPlanShape(subs))


def test_dangling_dep_flagged():
    subs = [_sub("st-001", deps=["st-999"], verify={"cmd": "x"})]
    assert any("st-999" in v for v in psc.checkPlanShape(subs))


def test_cycle_flagged():
    subs = [_sub("st-001", deps=["st-002"], verify={"cmd": "x"}),
            _sub("st-002", deps=["st-001"], verify={"cmd": "x"})]
    assert any("cycle" in v.lower() for v in psc.checkPlanShape(subs))


def test_empty_verify_on_multi_deliverable_flagged():
    subs = [_sub("st-001", verify={"cmd": "python a.py"}),
            _sub("st-002", verify=None)]
    assert any("verify" in v.lower() for v in psc.checkPlanShape(subs, multi_deliverable=True))


def test_violation_report_is_string():
    rep = psc.shapeViolationReport(["a", "b"])
    assert "a" in rep and "b" in rep
