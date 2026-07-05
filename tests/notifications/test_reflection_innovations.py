"""Innovation surfacing: reflection seed enrichment, embed rendering, flag-off no-op."""
from types import SimpleNamespace

from notifications import reflection_post
from platform_core.orchestration.invention_types import InnovativeChangeReportEntry


def _state():
    return SimpleNamespace(meta={"codename": "NOVA", "goal_raw": "invent things"}, task_id="r1")


def _shipped(title="Feat X"):
    return InnovativeChangeReportEntry(title=title, status="shipped",
                                       why_innovative={"measured_novelty": 0.9},
                                       evidence_refs=["test_pass:passed@1"])


def test_seed_user_mentions_shipped_innovations():
    seed = reflection_post._seed_user(_state(), [_shipped("Cache Layer")])
    assert "Cache Layer" in seed
    assert "Innovative changes you shipped" in seed


def test_seed_user_plain_without_innovations():
    seed = reflection_post._seed_user(_state(), [])
    assert "Innovative changes" not in seed


def test_write_reflection_threads_innovations_into_prompt():
    captured = {}

    def fake_chat(system, user):
        captured["user"] = user
        return "journal entry"
    text = reflection_post.write_reflection(_state(), chat=fake_chat,
                                            innovative_changes=[_shipped("Naming Engine")])
    assert text == "journal entry"
    assert "Naming Engine" in captured["user"]


def test_post_innovations_empty_is_noop():
    reflection_post.post_innovations(_state(), [])          # must not raise


def test_compile_innovations_flag_off_returns_empty(monkeypatch):
    from platform_core.orchestration import run_phase_outcome as rpo
    import config
    monkeypatch.setattr(config, "INVENTOR_MODE_ENABLED", False, raising=False)
    state = SimpleNamespace(meta={"task_id": "r1"}, subtasks=[], task_id="r1")
    assert rpo._compileInnovations(state) == []
