# 9to5 contribution instructions

- Target Windows-first behavior; do not add Linux/macOS work unless it is necessary for a change.
- Preserve root compatibility facades and edit the narrow implementation module.
- Keep generated runtime data, browser profiles, `.env` files, and `state/` artifacts out of commits.
- Before requesting review, run focused tests for changed modules, `python tools/repo_map.py --check`, and `git diff --check`.
- Do not weaken checks, update test baselines, or mark flaky tests quarantined merely to make CI green. Explain and fix the cause first.
- Keep external-provider and browser paths opt-in; prove live behavior with explicit runtime evidence.
