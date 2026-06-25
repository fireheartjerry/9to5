"""config.py parses ~40 numeric constants from .env. A bare int()/float() meant one malformed value
(e.g. OLLAMA_TIMEOUT_SECONDS= with nothing after it) raised at IMPORT time, taking down every entry
point. _envInt/_envFloat fall back to the default instead."""
import os
import subprocess
import sys
import unittest

import config


class TestEnvHelpers(unittest.TestCase):
    def test_envint(self):
        with self._set("X9", "not-a-number"):
            self.assertEqual(config._envInt("X9", 42), 42)
        with self._set("X9", ""):
            self.assertEqual(config._envInt("X9", 42), 42)
        with self._set("X9", "  99 "):
            self.assertEqual(config._envInt("X9", 42), 99)

    def test_envfloat(self):
        with self._set("Y9", "nope"):
            self.assertEqual(config._envFloat("Y9", 1.5), 1.5)
        with self._set("Y9", "3.25"):
            self.assertEqual(config._envFloat("Y9", 1.5), 3.25)

    def _set(self, k, v):
        return _EnvCtx(k, v)


class _EnvCtx:
    def __init__(self, k, v): self.k, self.v = k, v
    def __enter__(self): self._old = os.environ.get(self.k); os.environ[self.k] = self.v
    def __exit__(self, *a):
        if self._old is None:
            os.environ.pop(self.k, None)
        else:
            os.environ[self.k] = self._old


class TestImportSurvivesMalformedEnv(unittest.TestCase):
    def test_config_import_does_not_crash_on_garbage(self):
        env = {**os.environ, "OLLAMA_TIMEOUT_SECONDS": "garbage", "OBSIDIAN_PORT": "",
               "CLAUDE_DOC_FETCH_BUDGET_SECONDS": "xx"}
        r = subprocess.run(
            [sys.executable, "-c", "import config; print(config.OLLAMA_TIMEOUT_SECONDS, config.OBSIDIAN_PORT)"],
            cwd=str(config.PROJECT_ROOT), env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, f"config import crashed on malformed .env:\n{r.stderr}")
        self.assertEqual(r.stdout.strip(), "180 27124")   # both fell back to their defaults


if __name__ == "__main__":
    unittest.main()
