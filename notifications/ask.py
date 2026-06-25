"""Ask Nightclaw -- a natural-language interface to the live run, answered by the
LOCAL Ollama brain (zero marginal cost). Pure, testable core:

  * ``buildContext(state, question)`` -- assemble a compact prompt from TaskState.
  * ``answer(question, state, chat=...)`` -- query the brain (chat fn is injectable
    for tests / for reusing the orchestrator's client), degrade gracefully on failure.
  * ``detectControlIntent(text)`` -- conservative NL->control-verb mapping (only short
    imperative messages map to a control action; guarded + always confirmed by callers).

The gateway ``/ask`` cog (bot/cogs/ask_cog) is a thin shell over this module.
"""
from __future__ import annotations

import re
from typing import Callable, Optional

import config
import llm_io

LOG = config.getLogger("ask")

SYSTEM = (
    "You are Nightclaw, the resident assistant for the 9to5 autonomous coding orchestrator. "
    "Answer the operator's question about the CURRENT run using ONLY the run state provided. "
    "Be concise (1-4 sentences), concrete, and honest about uncertainty. Use the subtask ids "
    "(st-00N) when relevant. Never invent results the state does not show."
)

# Conservative NL -> control verb. A control action is only inferred from a SHORT imperative
# message (so 'why did it pause?' never pauses). Callers must still confirm + authorize + audit.
_INTENTS = [
    (("pause", "hold"), "pause"),
    (("resume", "unpause", "continue"), "resume"),
    (("abort", "stop", "cancel", "kill"), "abort"),
    (("approve", "approved", "lgtm"), "approve"),
    (("reject", "deny", "rejected"), "reject"),
    (("retry",), "retry"),
]


def detectControlIntent(text: str) -> Optional[str]:
    """Return a control verb if ``text`` is a short imperative control command, else None."""
    t = (text or "").strip().lower()
    if not t or len(t.split()) > 6:
        return None
    if t.endswith("?"):                      # a question is never a command
        return None
    for words, verb in _INTENTS:
        if any(re.search(rf"\b{re.escape(w)}\b", t) for w in words):
            return verb
    return None


def buildContext(state, question: str) -> str:
    m = state.meta
    subtasks = [s for s in state.subtasks if s.get("status") != "removed"]
    done = sum(1 for s in subtasks if s.get("status") == "done")
    total = max(len(subtasks), 1)
    cur = next((s for s in subtasks if s.get("status") == "in_progress"), None) \
        or next((s for s in subtasks if s.get("status") == "pending"), None)
    notifs = state.data.get("notifications", []) or []
    advs = state.data.get("adversary_reviews", []) or []

    lines = [
        f"GOAL: {m.get('goal_raw', '')}",
        f"STATUS: {m.get('status', '?')}  |  MODE: {m.get('control_mode', 'watch')}  |  "
        f"PROGRESS: {done}/{total}",
        f"CURRENT: {(cur['subtask_id'] + ' ' + cur['title']) if cur else '—'}",
        "SUBTASKS:",
    ]
    for s in subtasks[:25]:
        vr = s.get("verify_result") or {}
        mark = " PASS" if vr.get("passed") else (" FAIL" if vr else "")
        lines.append(f"  {s['subtask_id']} [{s.get('status')}]{mark} {s.get('title', '')}")
    if advs:
        lines.append("RECENT ADVERSARY REVIEWS:")
        for a in advs[-3:]:
            lines.append(f"  [{a.get('trigger_reason', '?')}] -> {a.get('verdict', '?')}")
    if notifs:
        lines.append("RECENT EVENTS:")
        for n in notifs[-8:]:
            lines.append(f"  {n.get('kind', '?')}: {n.get('detail', '')}")
    lines.append("")
    lines.append(f"QUESTION: {question}")
    return "\n".join(lines)


def _defaultChat(system: str, user: str) -> str:  # pragma: no cover -- needs a live Ollama
    import ollama
    client = ollama.Client(host=config.OLLAMA_HOST, timeout=config.OLLAMA_TIMEOUT_SECONDS)
    resp = client.chat(
        model=config.OLLAMA_MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        options={"num_ctx": config.OLLAMA_NUM_CTX}, keep_alive=config.OLLAMA_KEEP_ALIVE)
    return llm_io.responseText(resp)


def answer(question: str, state, *, chat: Optional[Callable[[str, str], str]] = None) -> str:
    """Answer ``question`` about ``state`` via the local brain. Never raises; degrades to a
    friendly offline message so /ask is always safe to call."""
    chat = chat or _defaultChat
    ctx = buildContext(state, question)
    try:
        out = (chat(SYSTEM, ctx) or "").strip()
        return out or "🧠 The brain returned an empty answer — try rephrasing."
    except Exception:  # noqa: BLE001
        LOG.warning("ask.answer failed", exc_info=True)
        return "🧠 Brain offline (Ollama unreachable). Use `/status` for the raw run state."
