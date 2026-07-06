"""Tests for human_nature.psyche_store — durable cross-run psyche persistence.

TDD: durable SQLite persistence for mood/drives/personality/scars, keyed by a
project string. Must survive a store close + fresh reopen (no stale locks).
"""
from __future__ import annotations

import config
from human_nature.psyche_store import close_store, load_psyche, open_store, save_psyche


# ---------------------------------------------------------------------------
# save_psyche / load_psyche — basic roundtrip
# ---------------------------------------------------------------------------

def test_save_and_load_roundtrip(tmp_path):
    store = open_store(db_path=str(tmp_path / "psyche.db"))
    state = {"mood": {"valence": 0.4}, "drives": {"mastery": 0.6}}
    save_psyche(store, "proj", state)
    assert load_psyche(store, "proj") == state
    close_store(store)


def test_load_missing_returns_empty_dict(tmp_path):
    store = open_store(db_path=str(tmp_path / "psyche.db"))
    assert load_psyche(store, "missing") == {}
    close_store(store)


def test_save_upserts_existing_project(tmp_path):
    store = open_store(db_path=str(tmp_path / "psyche.db"))
    save_psyche(store, "proj", {"mood": {"valence": 0.1}})
    save_psyche(store, "proj", {"mood": {"valence": 0.9}})
    assert load_psyche(store, "proj") == {"mood": {"valence": 0.9}}
    close_store(store)


def test_multiple_projects_are_independent(tmp_path):
    store = open_store(db_path=str(tmp_path / "psyche.db"))
    save_psyche(store, "proj-a", {"mood": {"valence": 0.1}})
    save_psyche(store, "proj-b", {"mood": {"valence": 0.9}})
    assert load_psyche(store, "proj-a") == {"mood": {"valence": 0.1}}
    assert load_psyche(store, "proj-b") == {"mood": {"valence": 0.9}}
    close_store(store)


# ---------------------------------------------------------------------------
# Durability — reopening a second store on the same path sees prior writes
# ---------------------------------------------------------------------------

def test_durability_across_store_reopen(tmp_path):
    db_path = str(tmp_path / "psyche.db")

    store1 = open_store(db_path=db_path)
    save_psyche(store1, "proj", {"mood": {"valence": 0.1}, "scars": ["missed-deadline"]})
    close_store(store1)

    store2 = open_store(db_path=db_path)
    result = load_psyche(store2, "proj")
    assert result == {"mood": {"valence": 0.1}, "scars": ["missed-deadline"]}
    close_store(store2)


def test_two_stores_open_concurrently_on_same_path(tmp_path):
    """No stale Windows file lock: two open stores on the same path coexist."""
    db_path = str(tmp_path / "psyche.db")

    store1 = open_store(db_path=db_path)
    store2 = open_store(db_path=db_path)

    save_psyche(store1, "proj", {"mood": {"valence": 0.3}})
    assert load_psyche(store2, "proj") == {"mood": {"valence": 0.3}}

    close_store(store1)
    close_store(store2)


# ---------------------------------------------------------------------------
# Default db_path derives from config.STATE_DIR (conftest-isolated)
# ---------------------------------------------------------------------------

def test_default_db_path_uses_state_dir():
    store = open_store()
    save_psyche(store, "proj-default", {"mood": {"valence": 0.2}})
    assert str(config.STATE_DIR) in str(store.path)
    assert load_psyche(store, "proj-default") == {"mood": {"valence": 0.2}}
    close_store(store)
