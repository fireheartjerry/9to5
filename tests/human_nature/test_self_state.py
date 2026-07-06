from human_nature.self_state import (
    new_self_state, get_competence, observe_competence, set_affect, migrate,
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

def test_new_self_state_v2_fields():
    ss = new_self_state()
    assert ss["schema"] == 2
    assert ss["affect_manifold"] == {
        "valence": 0.0, "arousal": 0.0, "dominance": 0.0, "certainty": 0.0,
        "novelty": 0.0, "agency": 0.0, "tension": 0.0, "social_exposure": 0.0,
        "cognitive_load": 0.0,
    }
    assert ss["drives"] == {}
    assert ss["personality_ref"] is None
    assert ss["mood"] == {"valence": 0.0, "arousal": 0.0}
    assert ss["scars_ref"] is None

def test_migrate_v1_to_v2_preserves_existing_values():
    ss = {
        "schema": 1,
        "competence": {"x": {"p": 0.9, "n": 3}},
        "affect": {"valence": 0.5, "arousal": 0, "control": 0},
        "morale": 0.2,
        "convictions": [],
        "open_stances": [],
        "dissonance": 0.0,
    }
    migrated = migrate(ss)
    assert migrated is ss
    assert migrated["schema"] == 2
    assert migrated["competence"]["x"]["p"] == 0.9
    assert migrated["morale"] == 0.2
    assert migrated["affect"] == {"valence": 0.5, "arousal": 0, "control": 0}
    assert migrated["affect_manifold"] == {
        "valence": 0.0, "arousal": 0.0, "dominance": 0.0, "certainty": 0.0,
        "novelty": 0.0, "agency": 0.0, "tension": 0.0, "social_exposure": 0.0,
        "cognitive_load": 0.0,
    }
    assert migrated["drives"] == {}
    assert migrated["personality_ref"] is None
    assert migrated["mood"] == {"valence": 0.0, "arousal": 0.0}
    assert migrated["scars_ref"] is None

def test_migrate_is_idempotent_on_v2():
    ss = new_self_state()
    migrated = migrate(ss)
    assert migrated == new_self_state()
