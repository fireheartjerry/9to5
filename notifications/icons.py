"""Application-emoji icon registry -- professional icons for Discord TEXT surfaces.

Renders the icon set (iconset.py) and uploads it as APPLICATION emojis (app-owned, so no
server emoji-list clutter; usable in any guild/DM by the app). Idempotent + cached.
``icon(concept)`` returns ``<:nc_<concept>:id>`` once ready, else ``""`` -- so every text
surface degrades gracefully to clean typography when icons are unavailable (no perms / DM /
Discord disabled). Best-effort; never raises.

Call ``ensureIcons()`` once at gateway startup (and best-effort at run start) to provision.
"""
from __future__ import annotations

import base64
from typing import Optional

import config
from notifications import discord_bot as discord
from notifications import iconset

LOG = config.getLogger("icons")

PREFIX = "nc_"
_MAP: Optional[dict] = None       # concept -> "<:nc_x:id>"
_APP_ID: Optional[str] = None


def _appId() -> Optional[str]:
    global _APP_ID
    if _APP_ID:
        return _APP_ID
    r = discord._request("GET", "/applications/@me")
    if r is not None and 200 <= r.status_code < 300:
        try:
            _APP_ID = str(r.json().get("id"))
        except Exception:  # noqa: BLE001
            _APP_ID = None
    return _APP_ID


def _listExisting(app_id: str) -> dict:
    r = discord._request("GET", f"/applications/{app_id}/emojis")
    out: dict = {}
    if r is not None and 200 <= r.status_code < 300:
        try:
            body = r.json()
            items = body.get("items", []) if isinstance(body, dict) else body
            for e in items:
                out[e["name"]] = str(e["id"])
        except Exception:  # noqa: BLE001
            pass
    return out


def ensureIcons(force: bool = False) -> dict:
    """Provision the app-emoji icon set (render+upload missing); return concept->ref map. Cached."""
    global _MAP
    if _MAP is not None and not force:
        return _MAP
    _MAP = {}
    app = _appId()
    if not app:
        return _MAP
    existing = _listExisting(app)
    for concept in iconset.EMOJI_CONCEPTS:
        name = PREFIX + concept
        eid = existing.get(name)
        if not eid:
            png = iconset.renderIcon(concept)
            if not png:
                continue
            data = "data:image/png;base64," + base64.b64encode(png).decode()
            r = discord._request("POST", f"/applications/{app}/emojis", json={"name": name, "image": data})
            if r is not None and 200 <= r.status_code < 300:
                try:
                    eid = str(r.json().get("id"))
                except Exception:  # noqa: BLE001
                    eid = None
        if eid:
            _MAP[concept] = f"<:{name}:{eid}>"
    LOG.info("app-emoji icons ready: %d/%d", len(_MAP), len(iconset.EMOJI_CONCEPTS))
    return _MAP


def icon(concept: str) -> str:
    """The custom-emoji ref for ``concept`` (e.g. '<:nc_done:123>'), or '' if not provisioned."""
    return (_MAP or {}).get(concept, "")


def prefix(concept: str, sep: str = " ") -> str:
    """``icon(concept) + sep`` when available, else '' -- convenient for prefixing a text line."""
    ic = icon(concept)
    return f"{ic}{sep}" if ic else ""
