"""Regression guard for the Ollama model-reload storm (empty-completion bug).

ROOT CAUSE: ollama tears down and RELOADS the whole model runner whenever the
requested ``num_ctx`` changes between calls. The old _ollamaChat sized num_ctx
to each prompt, so it oscillated (8192<->16384) against the static 8192 used by
elaborator/architect/replanner -- forcing a 4.7GB reload on nearly every call.
Under VRAM pressure a slow reload's connection is dropped -> 'Load failed' ->
the chat returns an EMPTY completion (the "Brain (Ollama) unavailable" notice).

INVARIANT: every brain call must use ONE stable num_ctx so the runner loads once
and stays resident, and must pin keep_alive so it is not unloaded between calls.
"""
import unittest
from unittest import mock

import config
import orchestrator as O
from orchestrator import Orchestrator


class _CapturingBrain:
    def __init__(self):
        self.calls = []

    def chat(self, *, model=None, messages=None, **kw):
        self.calls.append({"options": kw.get("options") or {},
                           "format": kw.get("format"),
                           "keep_alive": kw.get("keep_alive")})
        return {"message": {"content": '{"ok": true}'}}


class TestOllamaNumCtxStable(unittest.TestCase):
    def setUp(self):
        # Neutralize capability injection so we control the prompt size exactly.
        self._p = mock.patch.object(O, "injectCapabilities", lambda s: s)
        self._p.start()
        self.brain = _CapturingBrain()
        self.orch = Orchestrator(brain=self.brain, obs=mock.MagicMock(),
                                 run_claude=lambda *a, **k: {},
                                 replan=lambda *a, **k: {"action": "keep"},
                                 review=lambda *a, **k: {})

    def tearDown(self):
        self._p.stop()

    def test_num_ctx_is_constant_across_prompt_sizes(self):
        self.orch._ollamaChat("sys", "hi")                                 # tiny
        self.orch._ollamaChat("sys", "X" * 200_000, want_json=True)        # huge embed
        self.orch._ollamaChat("sys", "Y" * 40_000)                         # medium
        ctxs = {c["options"].get("num_ctx") for c in self.brain.calls}
        self.assertEqual(
            len(ctxs), 1,
            f"num_ctx must be CONSTANT to avoid ollama model-reload storm; got {sorted(ctxs)}")
        self.assertEqual(ctxs.pop(), config.OLLAMA_NUM_CTX)

    def test_keep_alive_is_pinned(self):
        self.orch._ollamaChat("sys", "hi")
        self.assertTrue(
            all(c["keep_alive"] for c in self.brain.calls),
            "keep_alive must be set so the runner is not unloaded during long Claude runs")
