# 9TO5 Doc Sync

Use this skill when code changes alter how agents should navigate, test, or operate 9TO5.

1. Update the closest human doc for the changed behavior.
2. Update `CLAUDE.md` only for short global rules.
3. Put detailed procedures in `.claude/skills` or `.claude/rules`.
4. Regenerate `AGENTS.md` with `python tools/repo_map.py` after exported Python structure changes.
5. Run `python tools/dev.py context-check` after changing Claude-facing context.
