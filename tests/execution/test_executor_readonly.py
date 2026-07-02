"""A spec with read_only=True must disallow Edit/Write at the hands layer (enforced read-only verify)."""
from unittest import mock

import config
from agents import executor


def _build(spec):
    with mock.patch.object(executor, "_resolveClaudeLauncher", return_value=["claude"]):
        fresh_cmd, _resume, _env, _flags, _model = executor._buildRunConfig(
            spec, task_state=None, subtask=None, resume_session=None,
            work=str(config.PROJECT_ROOT), effort="default", flag=None,
            charter="", claude_md_path=None)
    return fresh_cmd


def test_read_only_disallows_edit_write():
    cmd = _build({"read_only": True})
    assert "--disallowedTools" in cmd
    i = cmd.index("--disallowedTools")
    assert cmd[i + 1] == "Edit" and cmd[i + 2] == "Write"


def test_normal_spec_has_no_global_disallow():
    cmd = _build({})
    # no bare 'Edit'/'Write' disallow tokens for a normal write subtask
    assert "Edit" not in cmd and "Write" not in cmd
