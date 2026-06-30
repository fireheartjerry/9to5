"""Pure helper: route an environment into hands_kw ONLY for the Claude-CLI hands path."""
from platform_core.orchestration.execute_mixin import _envHandsKw


def _run_claude():        # stand-in identity for the terminal hands fn
    return None


def _run_browser():       # stand-in for a non-terminal surface
    return None


def test_env_threaded_for_claude_path():
    env, handle = object(), object()
    kw = _envHandsKw(_run_claude, _run_claude, env, handle)
    assert kw == {"environment": env, "env_handle": handle}


def test_env_not_threaded_for_browser_path():
    env, handle = object(), object()
    kw = _envHandsKw(_run_browser, _run_claude, env, handle)
    assert kw == {}


def test_env_not_threaded_when_missing():
    assert _envHandsKw(_run_claude, _run_claude, None, None) == {}
    assert _envHandsKw(_run_claude, _run_claude, object(), None) == {}
