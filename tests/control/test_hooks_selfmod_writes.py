"""Bash write-detection must cover PowerShell verbs and downloaders (B11).

If a write command is not recognised as a write, ``_parseBashGuardInput`` returns
``should_exit0=True`` (treated as read-only, safe) and the boundary check is skipped.
"""
from __future__ import annotations

import pytest

from agents.hooks_selfmod import _parseBashGuardInput

_POWERSHELL_WRITES = [
    "Set-Content -Path foo.txt -Value bar",
    "Out-File -FilePath foo.txt",
    "Add-Content foo.txt 'x'",
    "New-Item -ItemType File foo.txt",
    "Remove-Item foo.txt",
    "Clear-Content foo.txt",
]

_DOWNLOADERS = [
    "curl -o out.bin https://example.com/x",
    "curl -O https://example.com/x",
    "iwr https://example.com/x -OutFile out.bin",
    "wget https://example.com/x",
]


@pytest.mark.parametrize("cmd", _POWERSHELL_WRITES + _DOWNLOADERS)
def test_write_command_is_not_flagged_readonly(cmd):
    _bash, is_secret, should_exit0 = _parseBashGuardInput({"command": cmd})
    assert is_secret is False
    # should_exit0 True would mean "read-only, skip boundary check" -- a write must NOT be that.
    assert should_exit0 is False, f"write command treated as read-only: {cmd!r}"


def test_plain_read_still_readonly():
    _bash, is_secret, should_exit0 = _parseBashGuardInput({"command": "cat README.md"})
    assert is_secret is False
    assert should_exit0 is True


def test_bare_curl_get_still_readonly():
    # curl without -o just prints to stdout -- not a write.
    _bash, _is_secret, should_exit0 = _parseBashGuardInput({"command": "curl https://example.com"})
    assert should_exit0 is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
