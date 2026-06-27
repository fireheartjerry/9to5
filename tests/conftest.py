"""Shared test-harness defaults for the 9to5 suite.

The suite must NEVER touch the real Discord channel. With live credentials present, every
orchestration test made real REST calls to the configured DISCORD_CHANNEL_ID and got heavily
429 rate-limited -- which stalled the control-poll loop (flaking test_fuzz_control's 'bus'
surface, whose abort couldn't land within the scenario timeout) and added minutes of 429 backoff
to every e2e run.

The fix is test-only and changes NO production behavior: we blank DISCORD_BOT_TOKEN /
DISCORD_CHANNEL_ID for the test process, which makes ``notifications.discord_bot._request``
short-circuit to ``None`` BEFORE any network call -- exactly the path production already takes
when Discord is simply not configured (every caller already handles that ``None`` gracefully).
The 'bus' control surface is unaffected because it drives control through the file-backed
ControlBus, not Discord. Tests that exercise the REST chokepoint itself
(tests/test_discord_rest.py) set their own token via ``mock.patch`` inside each test and so are
unaffected by this ambient default.
"""
import os
import time as _time

import pytest

import config

# Load the real ollama SDK once, before any test module is collected. Production modules now
# import ollama lazily (perf: keeps the ~0.3s SDK import off CLI startup), so without this a
# test module that stubs `sys.modules["ollama"]` when it is absent (e.g. test_living_knowledge)
# could inject a bare ModuleType with __spec__=None and poison ollama for sibling tests on the
# same xdist worker -> "ValueError: ollama.__spec__ is None". Keeping the real module resident
# makes those "ollama missing" stub branches dead, exactly as eager imports used to.
try:  # pragma: no cover - ollama is a hard dep in CI; guard only for stripped-down envs
    import ollama as _ollama  # noqa: F401
except Exception:  # noqa: BLE001
    pass


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch):
    """Cap real ``time.sleep`` so retry/backoff loops don't burn wall-clock in tests.

    The single biggest test-speed lever for this codebase: e.g. orchestrator._ollamaChat retries a
    failed/empty brain call with exponential backoff (2s -> 4s -> 8s); under the fuzz tests (150
    seeds x a garbage brain) that compounds into >15 minutes / an apparent hang. Capping to 1ms
    keeps thread-yield ordering intact while making backoffs instant. Opt out for a test that
    genuinely measures elapsed time with ``NINE_TO_FIVE_REAL_SLEEP=1``."""
    if os.getenv("NINE_TO_FIVE_REAL_SLEEP", "").strip().lower() in {"1", "true", "yes", "on"}:
        yield
        return
    real = _time.sleep

    def _capped(s, _r=real):
        # Cap only LONG sleeps (>1s = retry/backoff territory, e.g. _ollamaChat's 2s->4s->8s).
        # Short sleeps (TTL expiry, thread-yield interleaving) run for real so timing-dependent
        # tests (cache-TTL, concurrency) keep working.
        if isinstance(s, (int, float)) and s > 1.0:
            return _r(0.01)
        return _r(s)

    monkeypatch.setattr(_time, "sleep", _capped)
    yield

# Heavyweight test files auto-marked `slow` (subprocess/e2e/integration/fuzz/sim) so the fast lane
# `pytest -m "not slow"` skips them -- without editing 137 files. Filename-substring based.
_SLOW_PATTERNS = ("e2e", "integration", "fuzz", "simulation", "full_autonomy",
                  "phase2", "phase_3", "selfplay", "_loop")


def pytest_collection_modifyitems(config, items):  # noqa: ARG001 -- pytest hook signature
    for item in items:
        name = str(getattr(item, "fspath", "")).replace("\\", "/").lower()
        if any(p in name for p in _SLOW_PATTERNS):
            item.add_marker(pytest.mark.slow)
            # Slow tests (e.g. the 150-iteration fuzz property tests) legitimately exceed the
            # 60s default; give them headroom while the fast lane keeps the tight hang-catching cap.
            item.add_marker(pytest.mark.timeout(300))


@pytest.fixture(autouse=True)
def _no_real_ollama(monkeypatch):
    """Never let a test hit the real local Ollama model (slow, non-deterministic, may hang on a
    cold model load). Any code path that reaches a real ``ollama.Client.chat/embeddings/generate``
    raises a clear error pointing at the fix -- mirrors the Discord/browser sandboxes. Tests that
    want a brain inject a fake (see tests/factories.fake_brain) or mock the seam. Opt out for a
    deliberate live test with ``NINE_TO_FIVE_ALLOW_OLLAMA=1``."""
    if os.getenv("NINE_TO_FIVE_ALLOW_OLLAMA", "").strip().lower() in {"1", "true", "yes", "on"}:
        yield
        return
    try:
        import ollama
    except Exception:  # noqa: BLE001 -- ollama not installed -> nothing to sandbox
        yield
        return

    def _blocked(*_a, **_k):
        raise RuntimeError("real Ollama call blocked in tests (set NINE_TO_FIVE_ALLOW_OLLAMA=1 to "
                           "allow); inject a fake brain (tests/factories.fake_brain) instead.")

    for meth in ("chat", "embeddings", "generate"):
        if hasattr(ollama.Client, meth):
            monkeypatch.setattr(f"ollama.Client.{meth}", _blocked, raising=False)
    yield


@pytest.fixture(autouse=True)
def _isolate_state(monkeypatch, tmp_path):
    """Give every test its own STATE_DIR / CONTROL_DIR so task + control files never leak between
    tests. Stray task files in the shared state dir caused order-dependent flakiness -- e.g.
    test_views' 'bail if a run is active' check seeing a run left behind by an earlier (slow) test.
    Tests that need their own dirs still monkeypatch locally (this just makes the default safe)."""
    sd = tmp_path / "state_tasks"
    cd = tmp_path / "state_control"
    sd.mkdir(parents=True, exist_ok=True)
    cd.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "STATE_DIR", sd, raising=False)
    monkeypatch.setattr(config, "CONTROL_DIR", cd, raising=False)
    yield


@pytest.fixture(autouse=True)
def _no_real_discord(monkeypatch):
    """Run every test as if Discord is unconfigured -> no live REST calls, no 429 throttling."""
    monkeypatch.setattr(config, "DISCORD_BOT_TOKEN", "")
    monkeypatch.setattr(config, "DISCORD_CHANNEL_ID", 0)
    yield


@pytest.fixture(autouse=True)
def _isolate_experience_db(monkeypatch, tmp_path):
    """Point the experience ledger at a per-test tmp DB so tests never read the real 33 MB
    state/experience.db and -- critically under `pytest -n auto` -- never have two workers write
    the same SQLite file concurrently. Mirrors _isolate_state. Tests that need their own ledger
    still pass an explicit db_path or patch this locally (unaffected)."""
    monkeypatch.setattr(config, "EXPERIENCE_DB_PATH", tmp_path / "experience.db", raising=False)
    yield


@pytest.fixture(autouse=True)
def _no_real_browser(monkeypatch):
    """Never let a test drive the real generic browser (CDP) layer.

    The repo's ``.env`` may set ``BROWSER_LAYER_ENABLED=True`` for real runs; with it on the
    orchestrator's dispatcher can route a subtask to a REAL Chromium via Playwright. Force the
    layer OFF for the test process. Tests that exercise the *routing* logic still
    ``mock.patch`` ``BROWSER_LAYER_ENABLED=True`` locally and mock ``_run_actions`` -- unaffected,
    because they never reach a real launch.

    Also force the Gemini second brain OFF: ``GEMINI_ENABLED`` defaults to ``bool(GEMINI_API_KEY)``,
    so with a key in ``.env`` the orchestrator's run path would probe the second brain during
    sim/e2e tests. ``agents.gemini_driver`` self-blocks the real API under any test runner, but the
    deterministic test path is Ollama-only -- tests that exercise the Gemini path opt in explicitly
    via ``mock.patch`` ``GEMINI_ENABLED=True`` (e.g. test_phase2_second_brain)."""
    monkeypatch.setattr(config, "BROWSER_LAYER_ENABLED", False)
    monkeypatch.setattr(config, "GEMINI_ENABLED", False)
    yield
