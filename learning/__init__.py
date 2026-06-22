"""Self-Improvement Engine (SIE) -- the learning subsystems.

See docs/superpowers/specs/2026-06-22-self-improvement-engine-design.md and
docs/superpowers/plans/2026-06-22-self-improvement-engine.md. Built phase by phase;
each module is independent and degrades gracefully when its external dependency
(Ollama, a GPU, Discord, Obsidian) is unavailable.
"""
