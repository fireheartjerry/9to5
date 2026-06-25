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
import pytest

import config


@pytest.fixture(autouse=True)
def _no_real_discord(monkeypatch):
    """Run every test as if Discord is unconfigured -> no live REST calls, no 429 throttling."""
    monkeypatch.setattr(config, "DISCORD_BOT_TOKEN", "")
    monkeypatch.setattr(config, "DISCORD_CHANNEL_ID", 0)
    yield


@pytest.fixture(autouse=True)
def _no_real_browser(monkeypatch, tmp_path):
    """Never let a test drive the real Phase-2 browser layer or touch the live ChatGPT profile.

    The repo's ``.env`` may set ``BROWSER_LAYER_ENABLED=True`` for real runs; with it on, the
    orchestrator's run path probes a REAL Chromium on the single logged-in profile (and
    ``profile_hygiene.sanitize()`` kills any other Chromium on it). So for the test process we
    force the layer OFF and redirect the profile dir to a throwaway temp dir. The hard backstop
    in ``agents.chatgpt_driver._realBrowserBlocked`` refuses a real launch under pytest even if a
    test flips the flag back on. Tests that exercise the *routing* logic still
    ``mock.patch`` ``BROWSER_LAYER_ENABLED=True`` locally and mock the browser calls -- unaffected,
    because they never reach a real launch."""
    monkeypatch.setattr(config, "BROWSER_LAYER_ENABLED", False)
    monkeypatch.setattr(config, "CHATGPT_USER_DATA_DIR", tmp_path / "chatgpt_profile_test")
    yield
