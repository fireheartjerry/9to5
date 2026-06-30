"""RoleSpec registry + classifyRole capability router (reuses playbook profiles)."""
from society.roles import ROLES, RoleSpec, classifyRole


def test_registry_has_five_roles():
    assert set(ROLES) == {"planner", "coder", "tester", "reviewer", "researcher"}
    for name, spec in ROLES.items():
        assert isinstance(spec, RoleSpec)
        assert spec.name == name
        assert spec.effort_level  # routes through MODEL_BY_EFFORT


def test_classify_implement_subtask_to_coder():
    st = {"title": "Implement the cache layer", "description": "add an LRU"}
    assert classifyRole(st).name == "coder"


def test_classify_test_subtask_to_tester():
    st = {"title": "Write tests for the parser", "description": "pytest coverage"}
    assert classifyRole(st).name == "tester"


def test_classify_review_subtask_to_reviewer():
    st = {"title": "Audit auth module for vulnerabilities", "description": ""}
    assert classifyRole(st).name == "reviewer"


def test_classify_research_subtask_to_researcher():
    st = {"title": "Research options for the queue", "description": "investigate libraries"}
    assert classifyRole(st).name == "researcher"


def test_brain_hint_overrides_keywords():
    st = {"title": "do the thing", "description": ""}
    assert classifyRole(st, hint="tester").name == "tester"
