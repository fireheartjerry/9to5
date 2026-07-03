from learning.evolution import evolver_prompts as ep


def test_do_not_capture_rules_present():
    rules = ep.DO_NOT_CAPTURE.lower()
    for needle in ("environment", "negative", "transient", "one-off"):
        assert needle in rules


def test_authoring_standards_cap_description():
    assert "60" in ep.AUTHORING_STANDARDS


def test_preference_order_is_class_level():
    assert "class-level" in ep.REVIEW_DISCIPLINE.lower()
