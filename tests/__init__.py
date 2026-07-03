# 9TO5 test package.
# Disable the SIE auto-maintenance dispatch globally for tests: integration tests call
# runFull many times and the implicit background learning pass would add GIL contention.
# learning/sie.py is still exercised directly by tests/evolution/test_sie.py.
import config as _config
_config.SIE_AUTO_MAINTENANCE = False
# Don't exercise the heavy per-authoring SIE context injection in unit tests (it does
# per-call ledger queries that make orchestrator-driving tests slow/flaky under load).
# Its own pieces are covered directly by the SIE test modules.
_config.SIE_AUTHORING_CONTEXT = False

# Isolate every default-path Experience Ledger write to a throwaway temp DB so the test
# suite never pollutes (or is slowed by) the real state/experience.db. Tests that need to
# assert ledger contents pass an explicit db_path and are unaffected.
import pathlib as _pathlib
import tempfile as _tempfile
_config.EXPERIENCE_DB_PATH = _pathlib.Path(_tempfile.mkdtemp(prefix="9to5_test_")) / "experience.db"

# Blank the Discord credentials process-wide for the WHOLE test package so no test can post to the
# live channel. conftest._no_real_discord only applies under pytest, but `unittest discover` (the
# CI-canonical command) bypasses conftest -- so a sim/e2e test (runFull -> milestone embeds, which
# gate on these creds in discord_bot._request) would otherwise hit the real channel under unittest.
# This is the runner-independent guard. Production never imports `tests`, so it has zero runtime impact.
_config.DISCORD_BOT_TOKEN = ""
_config.DISCORD_CHANNEL_ID = 0

# Same reasoning for the generic browser surface: conftest._no_real_browser (pytest-only) disables
# it, but `unittest discover` bypasses conftest -- so the layer would stay at its config default
# under unittest. Disable it process-wide so no real Chromium is launched; production never imports
# `tests`.
_config.BROWSER_LAYER_ENABLED = False
# The Gemini second brain defaults ON whenever GEMINI_API_KEY is in .env (GEMINI_ENABLED ==
# bool(key)), so the orchestrator's run path would activate the second-brain probe during sim/e2e
# tests. gemini_driver self-blocks the real API under any test runner, but we still force the gate
# OFF process-wide so e2e/sim runs take the deterministic Ollama-only path -- tests that exercise
# the Gemini path opt in explicitly via `mock.patch(config, "GEMINI_ENABLED", True)`.
_config.GEMINI_ENABLED = False
