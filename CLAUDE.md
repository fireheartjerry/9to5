# 9TO5 Claude Guide

9TO5 is a personal autonomous AI orchestration system. The local Ollama
orchestrator plans work; Claude Code is the executor that edits, tests, verifies,
and reports results. Keep this file short so every session starts fast.

## Vocabulary

- **Terminal A**: human-operated Claude Code session developing 9TO5.
- **9TO5 Executor**: Claude Code subprocess spawned by 9TO5.
- **Orchestrator**: local Ollama brain that plans, replans, and authors prompts.
- **Nightclaw**: Discord bot and orchestrator-facing bot surface.
- **Run**: one full work session.
- **Subtask**: meaningful unit of work within a run.
- **ExecutionStep**: one concrete Claude/browser/native/local action.
- **Verification**: proof that work succeeded.

## Read When Relevant

- Architecture: `docs/ARCHITECTURE.md`, `LLM_MAP.md`
- Documentation protocol: `docs/DOC_MAINTENANCE.md`
- Test tiers and commands: `docs/TESTING.md`, `.claude/rules/tests.md`
- CI and speed work: `docs/CICD_OPTIMIZATION.md`, `.claude/rules/ci.md`
- Hooks and skills: `docs/CUSTOM_SKILLS_AND_HOOKS.md`
- High-risk boundaries: `docs/DANGER_MAP.md`, `.claude/rules/orchestration.md`
- State and memory: `docs/STATE.md`, `docs/MEMORY.md`
- Repeatable playbooks: `docs/edit_recipes/`, `.claude/skills/`

## Core Rules

- Make the smallest safe change that satisfies the task.
- Preserve unrelated dirty files and generated artifacts.
- Read before editing; match the local style and ownership boundaries.
- Do not invent features, abstractions, config knobs, or broad refactors unless asked.
- Keep source-of-truth ownership intact: state store owns run state, ControlBus owns control commands, verifier owns verification status, dashboards are derived views.
- Hard boundaries are real forbidden paths. Do not touch secrets, `.env`, `.git`, virtualenvs, runtime task state, logs as source, or caches unless explicitly authorized.
- Do not change model or effort routing as part of speed work unless requested.

## Fast Editing Loop

1. Understand the request and inspect the smallest relevant files.
2. Make a narrow patch.
3. Run the narrowest useful validation.
4. If it fails, read the failure and patch only the cause.
5. Escalate to broader tests only after focused checks pass.
6. Update docs when behavior, commands, interfaces, agent workflow, hooks, skills, state, or testing strategy changed.

Useful commands:

```txt
python tools/dev.py check <file>
python tools/dev.py fast
python tools/dev.py ci-local
python tools/dev.py slow-report
python tools/dev.py context-check
python tools/dev.py iteration-health
```

## Documentation Rules

- Regenerate `AGENTS.md` with `python tools/repo_map.py` after exported Python structure changes.
- Do not hand-edit generated module rows.
- Keep procedures in `.claude/skills` or `.claude/rules`; keep this file under 200 lines.
- Update the closest human doc in the same patch when future agents need the new knowledge.

## Final Response After Edits

Report:

- files changed and why
- behavior changed
- docs updated
- verification commands and pass/fail status
- skipped checks or remaining risk
