"""Reusable discord.py UI for the Nightclaw gateway.

- ``views``   -- persistent + ephemeral views (ControlPanel, Blocked, Confirm, ...).
- ``layouts`` -- Components-V2 ``LayoutView`` cockpit + plan-editor layouts.
- ``dynamic`` -- ``DynamicItem`` stateless components (regex custom_id templates).
- ``modals``  -- ``WorkModal`` + plan-edit / ask modals.

All custom_ids stay in sync with the raw-REST component rows in
``notifications.branding`` / ``notifications.cv2`` so a button minted by the
loop-less orchestrator is still routed by the gateway's persistent views.
"""
from __future__ import annotations
