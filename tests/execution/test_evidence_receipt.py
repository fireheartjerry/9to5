"""Evidence Receipt headline is derived ONLY from facts (diff sha + exit codes), never LLM opinion."""
from agents import evidence_receipt as er


def _facts(checks, files_changed=2, diff="a.py | 3 +++"):
    git = {"base_sha": "b", "head_sha": "h", "diff_sha256": er._diffSha256(diff)}
    return {"git": git, "files_changed": files_changed, "criteria_reported": 1, "checks": checks}


def test_failed_check_forces_not_verified():
    f = _facts([{"command": "pytest", "exit_code": 1, "status": "fail"}])
    assert er._computeHeadline(f) == "NOT_VERIFIED"


def test_all_green_nonempty_diff_is_verified():
    f = _facts([{"command": "pytest", "exit_code": 0, "status": "pass"}])
    assert er._computeHeadline(f) == "VERIFIED"


def test_inconclusive_check_is_gaps():
    f = _facts([{"command": "pytest", "exit_code": None, "status": "inconclusive"}])
    assert er._computeHeadline(f) == "VERIFIED_WITH_GAPS"


def test_no_criteria_reported_is_gaps():
    f = _facts([{"command": "pytest", "exit_code": 0, "status": "pass"}])
    f["criteria_reported"] = 0
    assert er._computeHeadline(f) == "VERIFIED_WITH_GAPS"


def test_empty_diff_forces_not_verified():
    f = _facts([{"command": "pytest", "exit_code": 0, "status": "pass"}], files_changed=0, diff="")
    assert er._computeHeadline(f) == "NOT_VERIFIED"


def test_diff_sha_is_stable():
    assert er._diffSha256("a.py | 3 +++") == er._diffSha256("a.py | 3 +++")


def test_build_receipt_separates_facts_and_assessments():
    rec = er.buildReceipt(
        goal="g",
        git_info={"base_sha": "b", "head_sha": "h", "diff_text": "a.py | 3 +++", "files_changed": 2},
        det_check={"command": "python a.py", "exit_code": 0},
        indep_checks=[{"command": "pytest", "exit_code": 0, "summary": "1 passed"}],
        criteria_reported=1,
        assessments={"criteria": [{"criterion": "x", "met": True}], "adversary_verdict": "approved"})
    assert rec["headline"] == "VERIFIED"
    assert "git" in rec["facts"] and "criteria" in rec["assessments"]
    assert rec["assessments"]["non_binding"] is True
