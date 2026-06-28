# Coherent "Big PR" Narrative Planning

## Goal
Each run should tell one story — not "4 unrelated things fixed" but "hardened the orchestration layer today." Makes PRs feel intentional and impactful.

## Design

**Narrative theme selection** at plan time:
- Orchestrator picks a theme before selecting subtasks: e.g. "resilience", "observability", "test coverage", "perf"
- All subtasks must serve that theme
- PR title/description written to reflect the narrative, not just list changes

## What Changes
- `plan_mixin.py` — add theme selection step before subtask authoring
- Subtask selection filters/scores candidates by theme relevance
- PR description generator uses theme as framing

## Open Questions
- Does the theme come from the discovery engine (item 1) or get picked independently?
- How strict is coherence enforcement — veto unrelated subtasks, or just soft-rank?
- Should user be able to set the theme, or always autonomous?

## Status
PARKED — likely depends on Proactive Discovery Engine output; revisit after that ships.
