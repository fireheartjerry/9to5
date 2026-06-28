from human_nature.gating import is_expression_allowed, ACCURACY_CRITICAL

def test_verifier_surfaces_are_blocked():
    for surface in ("verifier", "verdict", "test_judgment", "diff_correctness"):
        assert surface in ACCURACY_CRITICAL
        assert is_expression_allowed(surface) is False

def test_human_facing_surfaces_allowed():
    for surface in ("discord", "narration", "brief", "psyche", "pr"):
        assert is_expression_allowed(surface) is True

def test_case_and_whitespace_insensitive():
    assert is_expression_allowed("  VERIFIER ") is False
