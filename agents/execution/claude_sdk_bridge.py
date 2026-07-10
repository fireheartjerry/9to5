"""Claude Agent SDK bridge smoke helpers for AskUserQuestion.

@AI-MAP v1
EXPORTS:
  sdkCapabilitySnapshot(permission_mode=None, tools=None) -> dict
  buildAskUserQuestionAllow(input_data: dict, answers: dict) -> object
DEPENDS-ON: config
SIDE-EFFECTS: optional import of claude_agent_sdk
RUN/TEST: python -m pytest tests/execution/test_claude_sdk_bridge.py
"""
from __future__ import annotations

import importlib.metadata
import shutil
import subprocess

import config

LOG = config.getLogger("executor.sdk_bridge")


def _version(dist: str) -> str:
    try:
        return importlib.metadata.version(dist)
    except Exception:  # noqa: BLE001
        return ""


def _claudeVersion() -> str:
    exe = shutil.which("claude")
    if not exe:
        return ""
    try:
        cp = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10)
        return (cp.stdout or cp.stderr or "").strip().splitlines()[0]
    except Exception:  # noqa: BLE001
        return ""


def sdkCapabilitySnapshot(permission_mode=None, tools=None) -> dict:
    tools = list(tools or [])
    restricted = bool(tools)
    contains = (not restricted) or "AskUserQuestion" in tools
    mode = permission_mode or "default"
    can_reach = bool(contains and mode != "dontAsk")
    snap = {
        "claude_cli_version": _claudeVersion(),
        "claude_agent_sdk_version": _version("claude-agent-sdk"),
        "executor_backend": config.CLARIFICATION_EXECUTOR_BACKEND,
        "permission_mode": mode,
        "tools_contains_AskUserQuestion": contains,
        "can_use_tool_reachable": can_reach,
        "ask_user_question_events_seen": 0,
        "warnings": [],
    }
    if mode == "dontAsk":
        snap["warnings"].append("permission_mode=dontAsk denies user-interaction prompts")
    if mode == "bypassPermissions":
        snap["warnings"].append("permission_mode=bypassPermissions can shadow normal can_use_tool expectations")
    if restricted and "AskUserQuestion" not in tools:
        snap["warnings"].append("restricted tools must include AskUserQuestion")
    LOG.info("sdk clarification capability: %s", snap)
    return snap


def buildAskUserQuestionAllow(input_data: dict, answers: dict):
    """Return the SDK PermissionResultAllow shape, or a dict fallback when SDK is absent."""
    updated = {"questions": input_data.get("questions", []), "answers": dict(answers or {})}
    try:
        from claude_agent_sdk.types import PermissionResultAllow
        return PermissionResultAllow(updated_input=updated)
    except Exception:  # noqa: BLE001
        return {"behavior": "allow", "updated_input": updated}
