"""vlm_healer -- local-VLM perception for self-healing chatgpt.com selectors.

The deterministic DOM path (agents/chatgpt_selectors.py) is fast and free but brittle: when
OpenAI ships a UI change, a selector misses. Rather than break, the driver hands a screenshot +
trimmed DOM to a LOCAL vision-language model (Ollama ``VLM_MODEL``, zero marginal cost, on-brand
for 9to5) and asks it to (a) classify the page state and (b) propose a CSS selector for the role
that's missing. The driver then VALIDATES the proposal against the live DOM before trusting or
caching it -- the VLM only proposes, the DOM decides.

This is strictly off the hot path: the driver calls it only on a genuine selector miss, capped
per run. It degrades cleanly (returns ``{}``) when Ollama or the vision model is unavailable, so
a review never crashes on a heal attempt.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

import config

LOG = config.getLogger("vlm_healer")

_MAX_DOM_CHARS = 12000

_PROMPT = (
    "You are a browser-automation perception module. You are shown a screenshot of a chatgpt.com "
    "page and a truncated DOM snippet. Your counterpart is an automated agent, not a human -- "
    "reply with JSON ONLY, no prose.\n"
    "Tasks:\n"
    "1. Classify the page state as one of: ready, login_wall, cloudflare, rate_limited, modal, unknown.\n"
    "2. Propose ONE robust CSS selector that uniquely targets the element for role '{want}'.\n"
    "   Roles: composer=message input box; send_button=submit; stop_button=stop generating; "
    "assistant_msg=the assistant's reply container.\n"
    "Reply exactly: {{\"state\": \"...\", \"selectors\": {{\"{want}\": \"<css>\"}}, "
    "\"confidence\": 0.0-1.0}}"
)


def _loadJson(text: object) -> Optional[dict]:
    if isinstance(text, dict):
        return text
    if not isinstance(text, str):
        return None
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.IGNORECASE).strip()
    try:
        return json.loads(t)
    except Exception:  # noqa: BLE001
        m = re.search(r"\{.*\}", t, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:  # noqa: BLE001
                return None
    return None


def heal(screenshot_png: bytes, dom_html: str, *, want: str) -> dict:
    """Ask the local VLM to classify the page + propose a selector for role ``want``.

    Returns ``{"state": str, "selectors": {want: css}, "confidence": float}`` or ``{}`` on any
    failure. The caller MUST validate the proposed selector against the live DOM before using it.
    """
    try:
        import ollama  # type: ignore
    except Exception as e:  # noqa: BLE001 -- no ollama -> no heal, degrade cleanly
        LOG.warning("VLM heal unavailable (ollama import failed): %s", e)
        return {}

    prompt = _PROMPT.format(want=want)
    dom = (dom_html or "")[:_MAX_DOM_CHARS]
    try:
        client = ollama.Client(host=config.OLLAMA_HOST, timeout=config.OLLAMA_TIMEOUT_SECONDS)
        resp = client.chat(
            model=config.VLM_MODEL,
            messages=[{"role": "user", "content": f"{prompt}\n\nDOM snippet:\n{dom}",
                       "images": [screenshot_png]}],
            format="json",
            options={"num_ctx": config.OLLAMA_NUM_CTX},
            keep_alive=config.OLLAMA_KEEP_ALIVE,
        )
        content = (resp.get("message") or {}).get("content") if isinstance(resp, dict) else None
        data = _loadJson(content)
        if not isinstance(data, dict):
            return {}
        selectors = data.get("selectors") or {}
        css = selectors.get(want)
        out = {
            "state": str(data.get("state") or "unknown"),
            "selectors": {want: str(css)} if css else {},
            "confidence": float(data["confidence"]) if data.get("confidence") is not None else None,
        }
        LOG.info("VLM heal for role=%s -> state=%s proposal=%s", want, out["state"],
                 out["selectors"].get(want))
        return out
    except Exception as e:  # noqa: BLE001 -- a heal failure is never fatal
        LOG.warning("VLM heal call failed for role=%s: %s", want, e)
        return {}
