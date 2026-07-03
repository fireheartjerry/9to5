from human_nature.self_state import (
    new_self_state, get_competence, observe_competence, set_affect,
)

def test_new_self_state_defaults():
    ss = new_self_state()
    assert ss["morale"] == 0.0
    assert ss["competence"] == {}
    assert ss["affect"] == {"valence": 0.0, "arousal": 0.0, "control": 0.0}
    assert ss["open_stances"] == []
    assert ss["convictions"] == []

def test_observe_competence_is_incremental_mean():
    ss = new_self_state()
    observe_competence(ss, "async", True)
    observe_competence(ss, "async", False)
    c = get_competence(ss, "async")
    assert c["n"] == 2
    assert abs(c["p"] - 0.5) < 1e-9

def test_unknown_domain_defaults_to_half():
    ss = new_self_state()
    assert get_competence(ss, "never_seen") == {"p": 0.5, "n": 0}

def test_set_affect_writes_pad_vector():
    ss = new_self_state()
    set_affect(ss, -0.4, 0.8, -0.2)
    assert ss["affect"] == {"valence": -0.4, "arousal": 0.8, "control": -0.2}
