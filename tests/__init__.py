# 9TO5 test package.
# Disable the SIE auto-maintenance dispatch globally for tests: integration tests call
# runFull many times and the implicit background learning pass would add GIL contention.
# learning/sie.py is still exercised directly by tests/test_sie.py.
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
