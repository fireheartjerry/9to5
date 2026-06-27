"""Nightclaw — Discord bot entrypoint.

Usage:
    python -m nightclaw

Runs the gateway bot that handles Discord commands, dashboard updates, and control operations.
"""
from __future__ import annotations

from notifications.command_bot import runCommandBot

if __name__ == "__main__":
    runCommandBot()
