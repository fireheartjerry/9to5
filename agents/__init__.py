"""9TO5 agent roster.

Orchestrator (brain, Ollama) authors prompts; these modules wrap each role:
  * elaborator -- expand raw goal into a buildable spec (Ollama)
  * architect  -- author architecture prompt (Ollama) + locked system prompt for Claude
  * executor   -- run Claude Code CLI subprocess (the hands)
  * adversary  -- Phase-1 STUB; logs trigger + auto-approves
  * replanner  -- mutate subtask list after each subtask (Ollama)
"""
