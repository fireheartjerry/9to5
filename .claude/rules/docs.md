# 9TO5 Docs Rules

- Update docs when behavior changes how future agents should work.
- Regenerate navigation with `python tools/repo_map.py` after changing exported Python structure.
- Keep `CLAUDE.md` short and directive; move procedures into skills or path-scoped rules.
- Use `docs/CUSTOM_SKILLS_AND_HOOKS.md` for hook, skill, and Claude settings changes.
- Do not hand-edit generated module rows in `AGENTS.md`; regenerate them.
