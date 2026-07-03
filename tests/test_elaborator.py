"""Tests for resilient elaboration (the run must not die at the starting line)."""
import os
import unittest
from unittest import mock

from agents import elaborator

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestElaborate(unittest.TestCase):
    def test_success_returns_content(self):
        with mock.patch.object(elaborator, "_getOllama", return_value=mock.Mock(
                chat=mock.Mock(return_value={"message": {"content": "  the spec  "}}))):
            self.assertEqual(elaborator.elaborate("do a thing"), "the spec")

    def test_falls_back_when_ollama_down(self):
        with mock.patch.object(elaborator, "_getOllama", return_value=mock.Mock(
                chat=mock.Mock(side_effect=ConnectionError("refused")))), \
             mock.patch("time.sleep"):
            spec = elaborator.elaborate("fix the bug in foo.py")
        self.assertIn("Objective", spec)
        self.assertIn("fix the bug in foo.py", spec)   # raw goal preserved

    def test_retries_then_succeeds(self):
        calls = {"n": 0}

        def flaky(*a, **k):
            calls["n"] += 1
            if calls["n"] < 2:
                raise TimeoutError("slow")
            return {"message": {"content": "recovered spec"}}

        with mock.patch.object(elaborator, "_getOllama",
                               return_value=mock.Mock(chat=mock.Mock(side_effect=flaky))), \
             mock.patch("time.sleep"):
            self.assertEqual(elaborator.elaborate("g"), "recovered spec")
        self.assertEqual(calls["n"], 2)


class TestUniverse(unittest.TestCase):
    def test_defaults_when_brain_unavailable(self):
        with mock.patch.object(elaborator, "_getOllama", return_value=mock.Mock(
                chat=mock.Mock(side_effect=RuntimeError("down")))), \
             mock.patch("time.sleep"):
            u = elaborator.extractUniverse("g", "spec", "/work/dir")
        self.assertEqual(u["allowed_paths"], ["/work/dir"])
        # Baseline hard boundaries always enforced.
        for d in __import__("config").UNIVERSE_DEFAULT_HARD_BOUNDARIES:
            self.assertIn(d, u["hard_boundaries"])

    def test_parses_brain_json(self):
        payload = '{"description":"d","allowed_paths":["a.py"],"allowed_to_expand_to":[],"hard_boundaries":["secret"]}'
        with mock.patch.object(elaborator, "_getOllama", return_value=mock.Mock(
                chat=mock.Mock(return_value={"message": {"content": payload}}))):
            u = elaborator.extractUniverse("g", "spec", "/w")
        self.assertEqual(u["allowed_paths"], ["a.py"])
        self.assertIn("secret", u["hard_boundaries"])


class TestRepoGrounding(unittest.TestCase):
    """The elaborator must ground its prompts in the REAL repository so the brain
    stops inventing placeholder paths (e.g. /path/to/app, src/features/, *.java)."""

    def _capture_prompt(self, fn):
        captured = {}

        def fake_chat(model, messages, **kw):
            captured["messages"] = messages
            return {"message": {"content":
                    '{"description":"d","allowed_paths":["platform_core/"],'
                    '"allowed_to_expand_to":[],"hard_boundaries":[]}'}}

        # Ensure a fresh grounding read for the real repo root.
        getattr(elaborator, "_REPO_CTX_CACHE", {}).pop(REPO_ROOT, None)
        with mock.patch.object(elaborator, "_getOllama",
                               return_value=mock.Mock(chat=fake_chat)):
            fn()
        return "\n".join(m.get("content", "") for m in captured.get("messages", []))

    def test_elaborate_grounds_prompt_in_real_repo(self):
        prompt = self._capture_prompt(
            lambda: elaborator.elaborate("improve everything", REPO_ROOT))
        # Real top-level packages (from AGENTS.md) must appear in the model prompt.
        self.assertIn("platform_core", prompt)
        self.assertIn("notifications", prompt)

    def test_extract_universe_grounds_prompt_in_real_repo(self):
        prompt = self._capture_prompt(
            lambda: elaborator.extractUniverse(
                "improve everything", "# Objective\nx", REPO_ROOT))
        self.assertIn("platform_core", prompt)


class TestRepoContextCacheStaleness(unittest.TestCase):
    """BUG-018: a cache entry populated before an AGENTS.md write must not be reused after the
    write -- otherwise a self-referential run that regenerates AGENTS.md mid-process keeps
    injecting the FIRST task's now-stale snapshot into every later elaboration."""

    def setUp(self):
        import tempfile
        self.dir = tempfile.mkdtemp()
        elaborator._REPO_CTX_CACHE.pop(self.dir, None)

    def tearDown(self):
        elaborator._REPO_CTX_CACHE.pop(self.dir, None)

    def test_cache_invalidates_after_agents_md_write(self):
        import os
        import time
        agents_md = os.path.join(self.dir, "AGENTS.md")
        with open(agents_md, "w", encoding="utf-8") as fh:
            fh.write("# v1 map\npackage_a/\n")
        first = elaborator._repoContext(self.dir)
        self.assertIn("package_a", first)

        time.sleep(0.01)   # ensure a distinct mtime on filesystems with coarse resolution
        with open(agents_md, "w", encoding="utf-8") as fh:
            fh.write("# v2 map\npackage_b/\n")
        os.utime(agents_md, None)   # force mtime forward even under a very coarse clock
        second = elaborator._repoContext(self.dir)
        self.assertIn("package_b", second)
        self.assertNotIn("package_a", second, "stale cache entry was reused after AGENTS.md changed")


if __name__ == "__main__":
    unittest.main()
