from agents.planning import question_memory


def test_exact_reuse_maps_to_current_question_text():
    session = question_memory.remember({}, [{
        "decision_id": "public_api_compatibility",
        "question_text": "Should public API compatibility be preserved?",
        "selected_label": "Preserve compatibility",
    }])
    q = {"question": "Should public API compatibility be preserved?",
         "options": [{"label": "Preserve compatibility"}, {"label": "Break API"}]}
    assert question_memory.findReusable(session, q)["selected_label"] == "Preserve compatibility"


def test_decision_id_exact_reuse_beats_wording_drift_even_high_risk():
    session = question_memory.remember({}, [{
        "decision_id": "public_api_compatibility",
        "question_text": "Should public API compatibility be preserved?",
        "selected_label": "Preserve compatibility",
        "risk": "high",
    }])
    q = {"decision_id": "public_api_compatibility",
         "question": "Do we preserve compatibility for the public API?",
         "risk": "high",
         "options": [{"label": "Preserve compatibility"}, {"label": "Allow breaking changes"}]}
    assert question_memory.findReusable(session, q)["selected_label"] == "Preserve compatibility"


def test_semantic_duplicate_reuses_when_labels_compatible():
    session = question_memory.remember({}, [{
        "question_text": "Should public API compatibility be preserved?",
        "selected_label": "Preserve compatibility",
    }])
    q = {"question": "Do we preserve compatibility for the public API?",
         "options": [{"label": "Preserve compatibility"}, {"label": "Allow breaking changes"}]}
    assert question_memory.findReusable(session, q)["selected_label"] == "Preserve compatibility"


def test_incompatible_options_do_not_reuse():
    session = question_memory.remember({}, [{
        "question_text": "Should public API compatibility be preserved?",
        "selected_label": "Preserve compatibility",
    }])
    q = {"question": "Do we preserve compatibility for the public API?",
         "options": [{"label": "Fast path"}, {"label": "Deep rewrite"}]}
    assert question_memory.findReusable(session, q) is None


def test_high_risk_semantic_duplicate_does_not_reuse_without_exact_match():
    session = question_memory.remember({}, [{
        "question_text": "Should public API compatibility be preserved?",
        "selected_label": "Preserve compatibility",
        "risk": "high",
    }])
    q = {"question": "Do we preserve compatibility for the public API?",
         "risk": "high",
         "options": [{"label": "Preserve compatibility"}, {"label": "Allow breaking changes"}]}
    assert question_memory.findReusable(session, q) is None
