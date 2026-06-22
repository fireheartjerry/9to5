"""Architect (Step 1).

Two pieces:
  * ARCHITECT_SYSTEM_PROMPT -- a *locked* system prompt prepended to the Claude
    Code CLI call so the Executor behaves as a software architect.
  * authorArchitectPrompt   -- an Orchestrator-brain step: Ollama writes the
    architecture-framed prompt that is then fired at Claude Code CLI.

The Claude invocation itself is performed by agents.executor.runClaude with
``system_prompt=ARCHITECT_SYSTEM_PROMPT``; its stdout becomes architect.md.
"""
from __future__ import annotations

import ollama

import config
import knowledge

LOG = config.getLogger("architect")
_OLLAMA = ollama.Client(host=config.OLLAMA_HOST, timeout=config.OLLAMA_TIMEOUT_SECONDS)

ARCHITECT_SYSTEM_PROMPT = (
    "You are the Architect. You produce a single, thorough architecture and design "
    "document for the specification you are given. Cover: high-level approach; component "
    "/ module breakdown; key files and their responsibilities; data flow; external "
    "dependencies; risks and mitigations; and an ordered implementation outline. "
    "Do NOT write application code or create files -- output ONLY the markdown design "
    "document. Begin directly with a top-level heading."
)


def authorArchitectPrompt(goal_elaborated: str) -> str:
    """Ollama authors the prompt that will be sent to Claude Code CLI."""
    LOG.info("Authoring architecture prompt via %s", config.OLLAMA_MODEL)
    resp = _OLLAMA.chat(
        model=config.OLLAMA_MODEL,
        messages=[
            {
                "role": "system",
                "content": knowledge.injectCapabilities(
                    "You author a single prompt instructing a coding agent to design the "
                    "architecture for the given specification. The prompt must ask only for a "
                    "design document, not code. Output ONLY the prompt text."
                ),
            },
            {"role": "user", "content": f"Specification:\n{goal_elaborated}\n\nWrite the architecture-design prompt."},
        ],
    )
    return resp["message"]["content"].strip()
