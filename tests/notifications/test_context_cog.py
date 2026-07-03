"""context_cog gateway shell: imports + setup callable + 3 context-menu builders."""
from notifications.bot.cogs import context_cog


def test_setup_is_callable():
    assert callable(context_cog.setup)


def test_module_defines_three_context_commands():
    # the cog registers exactly three context-menu commands (Explain / Why / Brief here)
    assert len(context_cog.CONTEXT_COMMAND_NAMES) == 3


def test_resolve_target_helper_handles_no_task(monkeypatch):
    # buildReply is a pure helper used by all three context menus; with no task it is graceful
    out = context_cog.buildReply("explain", "st-003", state=None)
    assert isinstance(out, str) and out
