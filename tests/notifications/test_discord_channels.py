"""Tests for Discord channel helper contracts."""
from __future__ import annotations

from notifications import discord_channels as channels


def test_edit_message_result_classifies_missing_and_transient(monkeypatch):
    monkeypatch.setattr(channels._dc, "_request", lambda *a, **k: None)

    assert channels.editMessageResult("123", {"title": "x"}) == "transient"
    assert channels.editMessageResult("", {"title": "x"}) == "not_found"


def test_send_as_does_not_ping_when_webhook_unavailable(monkeypatch):
    monkeypatch.setattr(channels, "_ensureWebhook", lambda: None)

    assert channels.sendAs({"name": "No Hook"}, content="@everyone") is False
