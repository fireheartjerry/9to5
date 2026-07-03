"""Tests for Discord embed builder helpers."""
from __future__ import annotations

from notifications import discord_embeds as embeds


def test_progress_bar_clamps_done_and_formats_percent():
    assert "100%" in embeds.progressBar(10, 2)
    assert "(2/2)" in embeds.progressBar(10, 2)
    assert "0%" in embeds.progressBar(-5, 2)


def test_notice_embed_is_informational():
    embed = embeds.noticeEmbed("handled automatically", "Notice")

    assert embed["title"] == "Notice"
    assert "handled automatically" in embed["description"]
    assert "timestamp" in embed
