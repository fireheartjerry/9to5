"""CRITICAL regression guard: num_ctx is config.OLLAMA_NUM_CTX on EVERY ollama.chat, even
when compaction + its summarizer fire. Protects the reload-storm fix."""
import pytest

import config
from platform_core.orchestration import llm_mixin
from platform_core.orchestration.llm_mixin import OrchestratorLlmMixin


class _RecordingOllama:
    def __init__(self):
        self.calls = []

    def chat(self, *, model, messages, **kwargs):
        self.calls.append(kwargs)
        return {"message": {"content": '{"ok": 1}'}}


class _Orch(OrchestratorLlmMixin):
    def __init__(self, ollama):
        self.ollama = ollama
        self._brain_tag_override = None
        self._compaction_fail_streak = 0


@pytest.fixture(autouse=True)
def _stub_caps(monkeypatch):
    # injectCapabilities reads the live knowledge base; stub to identity for hermeticity.
    monkeypatch.setattr(llm_mixin, "injectCapabilities", lambda s: s)


def test_numctx_fixed_on_every_call_even_with_compaction(monkeypatch):
    monkeypatch.setattr(config, "COMPACTION_ENABLED", True, raising=False)
    rec = _RecordingOllama()
    orch = _Orch(rec)
    huge_user = "x" * (config.OLLAMA_NUM_CTX * 5)        # forces compaction + a summarizer call
    resp = orch._ollamaChat("system prompt", huge_user, want_json=True)
    assert resp is not None
    assert rec.calls, "ollama.chat was never called"
    for kw in rec.calls:
        assert kw["options"]["num_ctx"] == config.OLLAMA_NUM_CTX   # NEVER per-prompt sized


def test_summarize_circuit_breaker_stops_after_max_passes(monkeypatch):
    monkeypatch.setattr(config, "COMPACTION_MAX_PASSES", 2, raising=False)

    class _Empty:
        def chat(self, *, model, messages, **kwargs):
            return {"message": {"content": ""}}      # always-empty summary -> failure

    orch = _Orch(_Empty())
    orch._compaction_fail_streak = config.COMPACTION_MAX_PASSES   # breaker already tripped
    assert orch._summarizeForCompaction("anything") == ""        # short-circuits, no call
