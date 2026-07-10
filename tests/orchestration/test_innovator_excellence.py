"""Local-only Innovator Excellence: sealed divergence, trace, and final portfolio."""
from agents.discovery import inventor
import llm_io
from types import SimpleNamespace
from unittest import mock
from platform_core.orchestration.run_phase_mixin import OrchestratorRunPhaseMixin


def _idea(seed, n):
    horizon = ("near_term", "asymmetric", "moonshot")[seed % 3]
    return {"title": f"Idea {seed}-{n}", "assumption": "polling is required",
            "mechanism": f"mechanism-{seed}-{n}", "architecture": "event log plus reducer",
            "capability_unlock": "continuous planning", "target_subsystems": [f"pkg/{seed}.py"],
            "metric": "latency < 1s", "experiment": "run focused test", "preconditions": "event bus",
            "risks": "backpressure", "horizon": horizon, "prior_art": "event sourcing",
            "local_novelty": "adapts it to the run loop"}


def test_excellence_seals_roles_and_returns_trace(monkeypatch):
    calls = []

    def chat(system, user, **kw):
        calls.append((system, user, kw))
        seed = kw["generation_options"]["seed"]
        if system.startswith("Score each"):
            return {"message": {"content": '{"scores": []}'}}
        return {"message": {"content": __import__("json").dumps({"ideas": [_idea(seed, 1), _idea(seed, 2)]})}}

    monkeypatch.setattr(inventor.config, "INVENTOR_FINAL_IDEA_COUNT", 6, raising=False)
    events = []
    report = inventor.run_excellence({"architecture": "private architecture"}, events.append, chat_fn=chat)

    assert len(report.findings) == 6
    assert report.innovator_trace[0]["phase"] == "engine"
    assert any(e["phase"] == "selection" and e["status"] == "completed" for e in report.innovator_trace)
    raw_calls = [c for c in calls if "Repository digest" in c[1]]
    assert len(raw_calls) == 6
    assert all("Idea " not in user for _, user, _ in raw_calls)  # no other role result leaked
    recombinations = [c for c in calls if '"parents"' in c[1]]
    assert len(recombinations) == 3
    assert all(f.invention and f.invention.horizon in ("near_term", "asymmetric", "moonshot")
               for f in report.findings)


def test_generation_options_are_sanitized_and_keep_context(monkeypatch):
    seen = []

    class _Client:
        def chat(self, **kwargs):
            seen.append(kwargs)
            return {"message": {"content": "ok"}}

    monkeypatch.setattr(llm_io.config, "OLLAMA_NUM_CTX", 8192)
    llm_io.chat("s", "u", act="test", client=_Client(),
                generation_options={"temperature": 0.9, "top_p": 0.92, "seed": 4, "num_ctx": 1,
                                    "unsafe": "ignored"})
    assert seen[0]["options"] == {"num_ctx": 8192, "temperature": 0.9, "top_p": 0.92, "seed": 4}


def test_finalists_post_one_compact_embed(monkeypatch):
    report = inventor.run_excellence({"architecture": "x"}, chat_fn=lambda system, user, **kw: (
        {"message": {"content": '{"scores": []}'}} if system.startswith("Score each") else
        {"message": {"content": __import__("json").dumps({"ideas": [_idea(kw["generation_options"]["seed"], 1), _idea(kw["generation_options"]["seed"], 2)]})}}))
    state = SimpleNamespace(task_id="abc123", meta={})
    with mock.patch("notifications.discord_bot.sendEmbed") as send:
        OrchestratorRunPhaseMixin._postInnovatorFinalists(object(), state, report)
    assert send.call_count == 1
    embed = send.call_args.args[0]
    assert embed["title"] == "💡 Innovator Finalists"
    assert len(embed["fields"]) == 6
