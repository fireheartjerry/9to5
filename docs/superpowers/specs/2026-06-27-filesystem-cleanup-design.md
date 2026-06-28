# Filesystem Bloat Cleanup — Design Spec

Date: 2026-06-27

## Goal

Remove structural bloat from the 9to5 codebase without changing runtime behavior.
Three commits, straight to main.

---

## Commit 1 — Easy Wins

### Delete dead folders
Both have zero imports anywhere in the codebase.

- `src/` — `workflow_registry.py`, `__init__.py`, `AGENTS.md`
- `scheduling/` — `recurring.py`, `__init__.py`, `AGENTS.md`

### Delete test stub
- `tests/test_notification_service.py` — 7 lines, no assertions, just redirects to `_basic` and `_advanced`

### Move maintenance scripts out of docs/
Five Python scripts that belong in `tools/`, not `docs/`:

- `docs/check_skill_gap_analysis_docs.py` → `tools/check_skill_gap_analysis_docs.py`
- `docs/check_trace_replay_docs.py` → `tools/check_trace_replay_docs.py`
- `docs/check_trace_replay_subagent_docs.py` → `tools/check_trace_replay_subagent_docs.py`
- `docs/update-skill-gap-analysis.py` → `tools/update-skill-gap-analysis.py`
- `docs/update-trace-replay.py` → `tools/update-trace-replay.py`

### Remove zero-byte __init__.py files
Python 3 namespace packages don't need `__init__.py`. Remove only files that:
- Are zero bytes (no exports, no imports)
- Are not required by any existing import statement

Candidates: `platform_core/` subfolders (14 files), `workflows/`, `tests/notification/`, `tests/skill_gap_analysis_enhancements/`.

Verify each with `grep -r "from <package> import"` before deleting.

### Out of scope for Commit 1
- `scripts/` folder — usage pattern unconfirmed, leave for now
- `nightclaw.py` — valid `python -m nightclaw` entrypoint, keep
- `validate_workflows.py` — CI compatibility shim, keep

---

## Commit 2 — Untrack AGENTS.md

### Problem
21 auto-generated `AGENTS.md` files are tracked in git. Real source of truth is `.repo-map.json`. They diverge silently between `repo_map.py` runs.

### Solution
- Add pattern to `.gitignore` that covers repo AGENTS.md files but NOT `.agents/skills/*/AGENTS.md` or `.claude/skills/*/AGENTS.md` (those are plugin files, different purpose)
- `git rm --cached` all 21 repo AGENTS.md files
- Add `python tools/repo_map.py` step to CI pipeline so they regenerate on every checkout
- Update `docs/DOC_MAINTENANCE.md` to note AGENTS.md is no longer tracked

### Files affected
```
AGENTS.md
agents/AGENTS.md
learning/AGENTS.md
memory/AGENTS.md
monitoring/AGENTS.md
notifications/AGENTS.md
platform_core/AGENTS.md
platform_core/app_config/AGENTS.md
platform_core/cli/AGENTS.md
platform_core/core/AGENTS.md
platform_core/knowledge_base/AGENTS.md
platform_core/ops/AGENTS.md
platform_core/orchestration/AGENTS.md
platform_core/runtime/AGENTS.md
platform_core/simulator/AGENTS.md
scheduling/AGENTS.md  (gone with Commit 1)
src/AGENTS.md         (gone with Commit 1)
state/AGENTS.md
testing/AGENTS.md
tests/AGENTS.md
workflows/AGENTS.md
```

---

## Commit 3 — Test Consolidation

### Problem
Test files were split into `_a`/`_b`/`_basic`/`_advanced` variants purely to stay under the 450-line `size_audit.py` threshold. This creates navigation friction and unclear ownership.

### Solution
Merge splits into logical groups. Exempt `tests/` from `size_audit.py` so merged files don't re-trigger the violation.

### Merges

| Merged into | Sources consumed |
|---|---|
| `test_notification_service.py` | `_basic`, `_advanced` (stub already deleted in Commit 1) |
| `test_notification_enhancements.py` | `_a`, `_b` |
| `test_notification_integration.py` | `_basic`, `_advanced` |
| `test_notification_entry.py` | `_entry`, `_schema`, `_ui` |
| `test_notification_docs.py` | `_docs`, `test_notification_bus_docs` |
| `test_skill_gap_analysis_improvement.py` | `_improvement_a`, `_improvement_b` |
| `test_skill_gap_analysis_workflow.py` | `_workflow_analysis`, `_workflow_tokens` |
| `test_trace_replay_subagent_enhancements.py` | `_enhancements_spec`, `_enhancements_workflow` |
| `test_trace_replay_subagent.py` | `_subagent_extract`, `_subagent_spec_gdp` |

### Files kept as-is
`test_notification_bus`, `test_notification_config`, `test_notification_infrastructure`,
`test_notification_schema`, `test_skill_gap_analysis`, `test_skill_gap_analysis_core`,
`test_skill_gap_analysis_enhancements`, `test_skill_gap_analysis_io`,
`test_trace_replay`, `test_trace_replay_json_utils`, `test_trace_replay_parallel_render`,
`test_trace_replay_workflow`

### size_audit.py change
Add `"tests"` to the exclusion set in `_tracked_py_files()` so test files are excluded from file-size auditing.

### Verification
Run `python tools/dev.py fast` after merges to confirm no regressions.

---

## Success Criteria

- `size_audit.py` reports 0 `must_split` violations (unchanged)
- `git ls-files | grep AGENTS.md` returns only `.agents/` and `.claude/` paths
- `src/` and `scheduling/` folders are gone
- Test suite passes: `python tools/dev.py fast`
- `docs/` contains no `.py` files
