# Update Docs Consistently

Use when a code change affects multiple documentation files.

## Read first

- `CLAUDE.md`
- `docs/DOC_MAINTENANCE.md`

## Process

1. Identify the behavior/structure change.
2. Find the canonical doc for that topic.
3. Update the canonical doc.
4. Update other docs only with short pointers or necessary summaries.
5. Remove contradictions.
6. Report docs checked but unchanged.

## Canonical mapping

- Claude behavior: `CLAUDE.md`
- Repo navigation: `LLM_MAP.md`
- Architecture: `docs/ARCHITECTURE.md`
- Danger/invariants: `docs/DANGER_MAP.md`
- Testing: `docs/TESTING.md`
- Nightclaw: `docs/NIGHTCLAW.md`
- State: `docs/STATE.md`
- Memory: `docs/MEMORY.md`
- Hooks/skills: `docs/CUSTOM_SKILLS_AND_HOOKS.md`
- Recipes: `docs/edit_recipes/`

## Verification

Run docs drift checker if available. Otherwise manually inspect for contradiction.
