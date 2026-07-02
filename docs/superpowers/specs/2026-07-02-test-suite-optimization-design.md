# Test Suite Optimization — Design

Date: 2026-07-02
Status: Approved (user pre-approved recommended options, then delegated remaining judgment)
Branch: `fable/first-principles-rewrite`

## Problem

- 3,048 collected test items across 320 flat files in `tests/`; ~2,860 run in the "fast" lane.
- The fast/slow split excludes only 14 files (filename-substring auto-tagging in
  `tests/conftest.py::_SLOW_PATTERNS`), so nearly the whole suite runs on every core change.
- PR CI runs the fast lane **twice** (python 3.11 + 3.12 matrix) on 2-core `windows-latest`
  runners, then `slow`, `dry-run-smoke`, and `e2e-smoke` all wait behind `fast`
  (`needs: fast`), serializing the pipeline.
- Fresh local baseline (2026-07-02): fast lane = **36s wall / 2,860 passed** with
  `-n auto --dist loadscope`. Local is acceptable; CI wall-clock and suite bloat are the pain.
- No test-impact selection in CI: the `classify` job gates *jobs* by path buckets, never *tests*.
- Real per-test cost centers: subprocess/git-spawning tests (top: 8.1s, 6.9s, 6.5s), 132
  subprocess spawn sites across 33 files.

## Decisions (user-approved)

1. **PR CI = affected tests only, fail-closed.** Changed files map to covering tests via
   `tools/affected_tests.py`; any ambiguity falls back to the full fast lane. Merge-to-main
   and nightly always run everything.
2. **Bloat: reorg + merge + delete.** Move flat files into domain subdirs, merge
   near-duplicate files, delete redundant tests — deletions require written evidence of
   equivalent coverage elsewhere.
3. **Python 3.12 only on PRs.** 3.11 leg moves to the nightly exhaustive lane.
4. Remaining choices delegated: parallel CI job graph, directory-based slow marking,
   top-offender speedups.

## Design

### A. Slow-marking redesign (foundation)

Replace `_SLOW_PATTERNS` filename-substring matching with **directory-based marking**:
everything under `tests/slow/` gets `@pytest.mark.slow` + 300s timeout, applied in
`tests/conftest.py::pytest_collection_modifyitems`. Move the 14 currently-auto-tagged files
into `tests/slow/`. No other file may be implicitly slow; substring matching is deleted.
Rationale: substring matching would misfire on domain subdir names (`integration`,
`simulation`) and is invisible at the file level.

### B. Directory reorganization

Move the remaining ~306 files into domain subdirs chosen by filename prefix and subject
module (final mapping decided during execution; indicative set):

```
tests/
  conftest.py, factories.py, progress_reporter.py   (stay at root)
  slow/          e2e, fuzz, simulation, integration-loop, phase2/3 files
  evolution/     test_evolution_*, test_experience_*, test_exp_index*, test_retrieval_*, ...
  execution/     test_execution_*, test_executor_*, test_worktree*, test_verifier*, ...
  orchestration/ orchestrator, society, trajectory, brain, ...
  control/       control bus, state, heartbeat, launch, ipc, ...
  notifications/ discord, dashboards, terminal surfaces, ...
  workflows/     workflow registry + validation, ...
  knowledge/     knowledge base, living knowledge, obsidian, ...
  platform/      config, hooks, safety, fsio, tools/dev/repo_map coverage, ...
```

Constraints:
- Test **basenames stay unique** repo-wide (pytest importmode=prepend, no `__init__.py`).
- `tests/conftest.py` stays at `tests/` root and governs the whole subtree.
- `tools/repo_map.py::find_tests` becomes recursive (`TESTS_DIR.rglob`), returns
  subdir-relative posix paths; `MANUAL_TEST_MAP` values updated.
- All hardcoded `tests/test_*.py` references updated: CI yml job commands + classify
  regexes, `tools/dev_checks.py`, `scripts/repo_health.py`, `validate_workflows.py`,
  `tests/conftest.py`. Generated `@AI-MAP RUN/TEST:` rows fixed by `tools/repo_map.py` regen.
- Suite must collect the same item count (± explicit merges/deletions) after the move.

### C. Merge + evidence-based deletion

Per-domain subagents consolidate:
- **Merge**: many-small-files covering one module → one file per subject area where natural;
  no behavioral change, imports/fixtures preserved.
- **Delete**: only with written evidence per deletion (exact-duplicate assertion, strictly
  weaker variant of a kept test, or dead subject code). Evidence recorded in the PR/commit
  message. When unsure → keep. Target is meaningful consolidation, not a line-count quota.
- Suite green after every domain's consolidation; collected-count delta accounted for.

### D. Top-offender speedups

Optimize the measured top ~15 tests (~60s of CPU) without weakening intent:
- Session-scoped **template git repos** (create once in tmp, `shutil.copytree` per test)
  for the git/PR/clone tests (`test_github_pr_gate`, `test_external_project`,
  `test_builder_sim`, `test_worktree`).
- Collapse redundant subprocess spawns where an in-process call verifies the same contract;
  keep genuinely cross-process tests (`test_control_concurrency`, `test_fsio` atomicity) real.
- Leave `_fast_sleep` threshold (1.0s) alone — sub-second sleeps widen race windows on purpose.

### E. CI workflow restructure (`.github/workflows/tests.yml`)

- **classify** gains an `affected` step (stdlib-only `tools/affected_tests.py`, no dep
  install): emits `affected_targets` and `affected_ok`.
  Fail-closed → full fast lane when ANY of:
  - a changed file is non-`.py` (except pure-docs/workflow/tooling buckets already handled),
  - a changed `.py` maps to zero tests,
  - `tests/conftest.py`, `tests/factories.py`, `pytest.ini`, `requirements*.txt`,
    `conftest.py` (root), or `.github/workflows/**` changed,
  - more than 25 files changed.
- **PR (core)**: one job, python 3.12 —
  `affected_ok == true` → `pytest <affected_targets> -n auto --dist loadscope -q` (no `-m`
  filter: slow tests covering changed code DO run);
  otherwise → full fast lane (`-m "not slow"`). Plus `compileall` + `validate_workflows.py`.
- **push to main**: full fast + slow + dry-run-smoke + e2e-smoke, all **parallel**
  (drop `needs: fast`; wall = max(jobs), not sum).
- **nightly / dispatch**: exhaustive as today **plus** a 3.11 fast-lane leg.
- Specialized docs/workflow/tooling lanes unchanged (paths updated for the reorg).

### F. Docs + tooling sync

- `docs/TESTING.md`, `docs/CICD_OPTIMIZATION.md` (append dated section), `.claude/rules/tests.md`,
  `.claude/rules/ci.md`, `CLAUDE.md` if commands change.
- `python tools/repo_map.py` regen; `python tools/size_audit.py` stays zero must_split.

## Execution order

1. A (slow-dir foundation) → 2. B (mechanical reorg + ref fixes, suite green) →
3. C (per-domain merge/delete, parallel subagents, green after each) →
4. D (speedups, parallel subagents) → 5. E (CI rewrite) → 6. F (docs/regen) →
7. Full verification: `dev.py ci-local`, full suite incl. slow, `repo_map.py --check`,
   `size_audit.py`.

## Success criteria

- PR CI (typical small change): affected-only lane, minutes not tens of minutes;
  fail-closed fallback verified by test.
- Fast lane local: ≤ baseline 36s (target ~25s after D).
- Test files: 320 → meaningfully consolidated, organized in domain dirs; zero unexplained
  loss of assertions; suite fully green including slow lane.
- Full safety net intact on merge-to-main + nightly.

## Risks

- Reorg blast radius (hardcoded paths): mitigated by grep-driven ref fix + same-count
  collection check + green-suite gate before proceeding.
- Affected-mapping misses cross-module regressions on PRs: accepted by design; caught on
  merge-to-main full run + nightly. Fail-closed triggers are deliberately broad.
- Merged files could exceed size thresholds: size_audit gate in final verification.
