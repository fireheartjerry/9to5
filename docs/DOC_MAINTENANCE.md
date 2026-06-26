# Documentation Maintenance

This repo is designed to be edited by both human-operated Claude Code sessions and 9TO5-spawned Claude Code subprocesses.

Documentation must stay synchronized with code because future LLM sessions use Markdown files as their working map. The point is persistence across every Terminal A and every spawned Executor, not vibes held together by a previous chat context.

## Terms

- **Terminal A**: a human-operated Claude Code terminal used to develop 9TO5 directly.
- **9TO5 Executor**: a Claude Code subprocess spawned by 9TO5 to perform a subtask.
- **Nightclaw**: the Discord bot / orchestrator-facing bot surface inside 9TO5.

Both Terminal A and 9TO5 Executors must preserve documentation consistency.

## Core rule

If a code change affects how future agents should understand, edit, test, run, or debug the system, update the relevant Markdown file in the same patch.

Do not defer documentation updates unless explicitly instructed.

## Canonical documentation map

| File | Purpose |
|---|---|
| `CLAUDE.md` | Editing behavior and Claude Code operating rules |
| `LLM_MAP.md` | Repo navigation, file ownership, module map |
| `docs/DOC_MAINTENANCE.md` | Documentation consistency protocol |
| `docs/ARCHITECTURE.md` | System design, core loop, agents, lifecycle |
| `docs/DANGER_MAP.md` | High-risk files, invariants, forbidden edits |
| `docs/TESTING.md` | Test tiers, canonical commands, CI expectations |
| `docs/NIGHTCLAW.md` | Discord bot, dashboard, cogs, command surfaces |
| `docs/STATE.md` | Task JSON, run state, ControlBus state |
| `docs/MEMORY.md` | Obsidian, vault, experience DB, context handoffs |
| `docs/CUSTOM_SKILLS_AND_HOOKS.md` | Recommended hooks, skills, and automation guardrails |
| `docs/edit_recipes/` | Repeatable task-specific editing playbooks |

## Read-before-edit rule

Before editing code, read the smallest relevant documentation subset.

Always start with:

- `CLAUDE.md`

Then read selectively:

- `LLM_MAP.md` when locating code or understanding repo structure
- `docs/ARCHITECTURE.md` when changing orchestration, agents, lifecycle, state, memory, verification, or execution flow
- `docs/DANGER_MAP.md` when touching high-risk files or hard boundaries
- `docs/TESTING.md` before changing tests, verification, CI, or canonical commands
- `docs/NIGHTCLAW.md` when changing Discord bot, dashboard, command handling, cogs, UI, or Nightclaw behavior
- `docs/STATE.md` when changing task JSON, run state, ControlBus state, or persistence
- `docs/MEMORY.md` when changing Obsidian, experience DB, context handoff, or note-writing behavior
- `docs/CUSTOM_SKILLS_AND_HOOKS.md` when changing hooks, self-modification guard, Claude Code settings, custom commands, or automation helpers
- `docs/edit_recipes/*.md` when the task matches an existing recipe

If a relevant doc does not exist yet, create it only if the change needs a durable explanation. Do not create empty ceremonial docs.

## Update triggers

Update documentation when changing:

- module responsibilities
- public interfaces between modules
- lifecycle/status values
- source-of-truth ownership
- state schema
- ControlBus behavior
- verifier behavior
- executor behavior
- agent roles
- dashboard/Nightclaw behavior
- test commands or test strategy
- config layout
- guard/path policy
- learning/self-improvement behavior
- generated/runtime artifact conventions
- developer workflow
- hooks, custom skills, or Claude Code instructions

## Update mapping

| Change type | Docs to update |
|---|---|
| Repo structure, file ownership, module responsibilities | `LLM_MAP.md` |
| Core architecture, lifecycle, agents, orchestration | `docs/ARCHITECTURE.md` |
| Dangerous files, invariants, forbidden edits | `docs/DANGER_MAP.md` |
| Tests, canonical commands, CI, verification tiers | `docs/TESTING.md` |
| Discord bot, dashboard, cogs, Nightclaw UX | `docs/NIGHTCLAW.md` |
| Task JSON, run state, ControlBus persistence | `docs/STATE.md` |
| Obsidian, vault, experience DB, memory flow | `docs/MEMORY.md` |
| Hooks, skills, Claude Code settings, guard automation | `docs/CUSTOM_SKILLS_AND_HOOKS.md` |
| Repeated workflow/playbook | `docs/edit_recipes/*.md` |
| Claude Code behavior rules | `CLAUDE.md` |

## Anti-duplication rule

Do not paste the same large explanation into multiple docs.

Choose one canonical doc and link to it from the others.

If two docs contradict each other, fix the contradiction immediately or identify the canonical source.

## Documentation acceptance criteria

After a change, a future Terminal A or 9TO5 Executor should be able to answer:

- Where is the relevant code?
- Which docs describe it?
- What contracts does it use?
- What state is canonical?
- What files are risky?
- What tests should be run?
- What behavior changed?
- What docs changed with it?

If not, the documentation is not good enough.
