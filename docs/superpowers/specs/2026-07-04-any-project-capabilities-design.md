# Any-Project Capabilities — Design Spec

> **Date:** 2026-07-04 · **Status:** approved (autonomous run; user granted full architecture
> autonomy) · **Branch:** `feat/any-project-capabilities`
>
> Three interconnected capabilities that let 9TO5 work on ANY project, not just itself:
> **(1) Multi-Project Context Extraction**, **(2) Cross-File Refactoring with Safety**,
> **(3) Solution Space Exploration**. Success = proof-of-concept on 9to5's own codebase AND one
> external project, zero regressions.

---

## 1. Goal & ground truth (from exploration)

9TO5 already abstracts the *target* of a run — `work_dir` is threaded through every invocation
(`agents/executor.py:72`), `platform_core/ops/external_project.py::cloneRepo` checks out external
repos, and the `Universe` contract (`platform_core/core/contracts.py:142`) scopes what a run may
touch. What is missing is *understanding*: everything that knows a project's shape is a 9to5-pinned
dev script.

| Existing asset | Where | Limitation |
|---|---|---|
| AST module extraction (exports/deps/docstrings) | `tools/repo_map.py:223-311` | `REPO_ROOT` pinned, `MANUAL_TEST_MAP`, root="9to5" |
| Load-time import graph + DFS cycle guard | `tools/repo_map.py:348`, `tests/platform/test_repo_map.py:133` | test-only guard, 9to5-pinned |
| File→test mapping | `tools/affected_tests.py`, `tools/repo_map_test_map.py` | manual map is pure 9to5 knowledge |
| AST symbol usages / rename | `tools/codemod.py` | 9to5-pinned, not scope-aware, no safety gate |
| E6 execution forking (fork→judge→merge) | `platform_core/orchestration/{fork_policy,branch_runner,judge_panel,winner_merge,solution_space}.py` (641 LOC, 7 test files) | diversity seeds are generic angle strings; no design-time approach generation or trade-off analysis |
| Verification Receipt + diff-grounded targets | `agents/verification.py:57-85` | per-subtask; no atomic multi-file apply/rollback exists anywhere |

**Gaps to close:** a runtime, root-agnostic project model; runtime circular-import detection +
breaking-change prediction + atomic multi-file transactions; design-time approach
generation/trade-off scoring/synthesis that feeds E6.

## 2. Approaches considered

**Capability shape**
- **A. Generalize `tools/` in place** (make repo_map/codemod take `--root`): least new code, but the
  tools are `sys.path`-hacked dev scripts, return markdown/stdout not typed data, and CI depends on
  their exact behavior — high regression risk, no reusable model. Rejected.
- **B. New runtime packages that reuse the *patterns* (AST extraction, cycle DFS, naming-convention
  test mapping) but not the pinned code; `tools/` untouched.** Typed dataclasses, root passed
  explicitly, stdlib-only. **Chosen.**
- **C. Plugin framework with per-language analyzer entry points**: right for a polyglot IDE, YAGNI
  here. Rejected.

**Refactor rollback**
- **A. `git stash`-based**: endangers unrelated dirty files (Core Rule violation). Rejected.
- **B. worktree-per-transaction**: heavy, git-only, Windows friction. Rejected.
- **C. Per-file content snapshot → apply all → gate → restore-on-failure.** Precise (only touched
  files ever restored), works on non-git projects, preserves unrelated dirty files. **Chosen.**

**Solution exploration placement**
- **A. Independent second engine**: duplicates E6's judge/fork machinery. Rejected.
- **B. Design-time layer that generates/scores/synthesizes approaches and (flag-gated) feeds the
  winners into E6 `forkPlan` as real angle seeds; also usable standalone on any project.** **Chosen.**

## 3. Architecture — three root packages + thin wiring

Product domains live at root (Tree Guide). Three new root packages, stdlib-only, every module
≤300 lines ideal / ≤450 hard, functions ≤70, `@AI-MAP v1` headers, camelCase functions /
snake_case vars / ALL_CAPS consts. Module filenames are globally distinctive so convention-based
test mapping resolves without manual entries.

### 3.1 `introspect/` — Multi-Project Context Extraction

Builds a typed `ProjectModel` for **any** root directory at runtime. Honest tiering: full semantic
analysis for Python (AST), import-statement scan for JS/TS (regex on `import`/`require`), structure
+ config detection for everything else.

| Module | Responsibility |
|---|---|
| `project_model.py` | Frozen dataclasses: `ProjectModel` (root, languages, modules, import_edges, commands, boundaries, stats), `ModuleInfo` (path, lang, exports, imports, loc, side_effects), `ProjectCommands` (test/build/lint/typecheck + source of each), `BoundaryMap`. JSON round-trip (`toJson`/`fromJson`). |
| `project_scanner.py` | Walk tree (respecting `.gitignore`-style default excludes: `.git`, `venv`, `node_modules`, `__pycache__`, build dirs), classify files by language, collect `ModuleInfo` skeletons. Deterministic ordering. |
| `python_import_graph.py` | AST per-module extraction for Python roots: exports (honoring `__all__`), first-party imports (top-level vs lazy, generalizing `repo_map._depends_on`), module-level side-effect heuristic (top-level calls to `open`/`subprocess`/socket/`Path.write_*` ⇒ `side_effects` tags). |
| `generic_import_scan.py` | Regex import edges for JS/TS (`import … from`, `require(`), relative-path resolution; graceful no-op for unknown languages. |
| `project_commands.py` | Detect THE test/build/lint commands from config files, priority-ordered: `pyproject.toml` (+tool sections), `pytest.ini`/`tox.ini`/`setup.cfg`, `package.json` scripts, `Makefile` targets, `Cargo.toml`, `go.mod`. Each detected command carries `source` (which file proved it) — never guessed. |
| `project_test_map.py` | Convention-based file→test mapping for any root (exact `test_<stem>` → prefix → glob, generalizing `repo_map.find_tests`; plus JS `*.test.*`/`*.spec.*` conventions). Optional caller-supplied overrides dict replaces `MANUAL_TEST_MAP`. |
| `project_boundaries.py` | Ownership/interface map: top-level packages, facade detection (modules that only re-export), entrypoints (`__main__`, `main.py`, `bin`/`scripts`, package.json `main`), config surface. |
| `project_extract.py` | Facade: `extractProject(root, *, max_files) -> ProjectModel` orchestrates scanner→graphs→commands→boundaries; `contextForPrompt(model, *, budget_chars) -> str` renders an LLM-ready digest (the AGENTS.md idea, generalized, in-memory); disk cache in `config.STATE_DIR/project_models/` keyed by `(root, git HEAD or mtime-hash)`. |

`introspect/__init__.py` re-exports the public API (`extractProject`, `contextForPrompt`,
`ProjectModel`).

### 3.2 `refactor/` — Cross-File Refactoring with Safety

Depends on `introspect` for the import graph. Never imports orchestration (leaf layer).

| Module | Responsibility |
|---|---|
| `cycle_detect.py` | `buildImportGraph(model) -> dict[str, set[str]]`; `findCycles(graph) -> list[list[str]]` (iterative Tarjan SCC — no recursion-limit risk); `wouldCreateCycle(graph, added_edges, removed_edges) -> list[cycle]` for pre-flight prediction. |
| `symbol_usages.py` | `findUsages(root, symbol, *, lang="python") -> list[Usage(file, line, kind)]` — AST Name/Attribute/ImportFrom scan over an arbitrary root (generalizes `tools/codemod.py::cmd_usages`). |
| `change_impact.py` | `predictImpact(model, planned: list[FileEdit]) -> ImpactReport`: renamed/deleted exports → orphaned import sites (via `symbol_usages`), import edges added/removed → predicted cycles (via `cycle_detect`), touched modules → affected tests (via `project_test_map`), blast-radius stats. Pure prediction, no writes. |
| `refactor_edits.py` | Edit primitives as frozen dataclasses: `WriteFile`, `ReplaceInFile` (exact old→new, must match once), `DeleteFile`, `RenameFile`; validation (paths inside root, no forbidden segments: `.git/`, `.env`, `venv/`, `node_modules/`, `__pycache__/`). |
| `refactor_transaction.py` | `RefactorTransaction(root)`: `.add(edit)` → `.preview() -> ImpactReport` → `.apply(gate=…)`. Apply = snapshot exact current bytes of every touched file → write all edits → run gate (default: `py_compile` every touched `.py` + `findCycles` no-new-cycles + optional caller command e.g. the project's detected test cmd) → on ANY gate failure restore every snapshot byte-for-byte and report `RefactorResult(applied=False, reason, gate_output)`. All-or-nothing; untouched dirty files never touched. |

`refactor/__init__.py` re-exports `RefactorTransaction`, `predictImpact`, `findCycles`,
`findUsages`, edit types.

### 3.3 `explore/` — Solution Space Exploration (design-time layer over E6)

Depends on `introspect` (project traits inform scoring). Brain is **injectable** (existing Brain
protocol shape — any `callable(system, user, want_json=…)`); every function has a deterministic
brain-free fallback so the capability works offline and in tests.

| Module | Responsibility |
|---|---|
| `approach_gen.py` | `ApproachCandidate` dataclass (id, title, summary, steps, files_touched_estimate, archetype). `generateApproaches(goal, model, *, brain=None, n=3)`: with brain → prompt for N distinct approaches as JSON (validated, clamped); without → specialize `APPROACH_ARCHETYPES` (minimal-patch, refactor-first, test-first, new-module, bold-redesign) against project traits (has tests? facade-heavy? entrypoint kind?). |
| `approach_tradeoffs.py` | `scoreApproach(candidate, model) -> TradeoffScore` over measurable proxies: **risk** (estimated blast radius ÷ import-graph fan-in of touched areas), **effort** (step count, files touched), **testability** (do detected test commands + mapped tests cover the touched area), **fit** (archetype vs project kind: CLI/service/library detected from boundaries). Weighted composite (ALL_CAPS weights), deterministic ranking, brain optional for rubric refinement (advisory, mirrors `judge_panel` facts-first discipline). |
| `approach_synthesis.py` | `selectOrSynthesize(scored, *, brain=None) -> SynthesisResult`: winner selection with deterministic tie-break (score → fewer files → lowest id); synthesis = winner + compatible risk-mitigations lifted from runners-up (e.g. adopt runner-up's test-first step when winner lacks coverage); brain path can merge summaries, fallback is mechanical merge. |

`explore/__init__.py` re-exports `exploreSolutionSpace(goal, root_or_model, *, brain=None, n=3)`
one-call facade → generate → score → synthesize.

### 3.4 Wiring into the run loop (narrow, flag-gated, fail-open)

| Touch | Change |
|---|---|
| `platform_core/app_config/settings.py` | `PROJECT_INTROSPECTION_ENABLED` (default **True** — deterministic + cheap), `PROJECT_INTROSPECTION_MAX_FILES` (default 4000), `EXPLORE_APPROACHES_ENABLED` (default **False**, ships dark like E6 — costs brain tokens), `EXPLORE_APPROACHES_N` (default 3). |
| `platform_core/orchestration/plan_mixin.py` | Before authoring the plan, if introspection enabled: `introspect.contextForPrompt(extractProject(work_dir))` appended to the architect/plan prompt (budgeted excerpt, same pattern as the existing `architect_doc[:4000]` at `plan_mixin.py:74`). `try/except → ""` — a broken scan never blocks planning. |
| `platform_core/orchestration/fork_policy.py` | In `forkPlan`, when `EXPLORE_APPROACHES_ENABLED` and approaches are supplied/generable: use ranked `ApproachCandidate.summary` strings as branch `angle_hint`s instead of generic `DIVERSITY_ANGLES` (fail-open to existing angles). E6's judge/merge machinery is unchanged — exploration improves the *seeds*, selection stays execution-grounded. |
| CLI | `python -m introspect <root>` (print digest/JSON), `python -m refactor check <root>` (cycles report), `python -m explore "<goal>" <root>` (ranked approaches, brain-free). Tiny `__main__.py` per package. |

Ownership boundaries intact: verifier still owns verification, state store owns run state, these
packages are pure libraries + two prompt-level touches.

### 3.5 Dependency direction

```
explore ──▶ introspect ◀── refactor          (leaf layer, stdlib-only)
   ▲                            ▲
   └── platform_core/orchestration (fork_policy, plan_mixin) — lazy imports, fail-open
```

No new package imports orchestration/agents/state (no cycles by construction; the load-time cycle
guard in `test_repo_map.py` will enforce it once mapped).

## 4. Error handling

- **Fail-open everywhere in the run loop**: introspection or exploration failure → empty context /
  default angles / linear path. Never blocks or degrades today's behavior.
- **Fail-closed in the transaction**: any gate failure, any snapshot-restore mismatch, any path
  outside root or in forbidden segments → nothing applied, explicit `RefactorResult` with reason.
- **No network**: all three packages are offline; brain is injected by the caller.
- **Windows-safe**: pure `pathlib`, UTF-8 with `errors="replace"` reads, no symlink following.
- **Big-repo safety**: `max_files` cap with explicit `truncated=True` on the model (no silent cap).

## 5. Testing strategy

New domain dirs `tests/introspect/`, `tests/refactor/`, `tests/explore/` (pytest auto-collects;
distinctive module filenames make convention mapping resolve; `tools/repo_map_test_map.py` gets
entries only if the drift check demands them). Fixture projects built in `tmp_path` (pattern:
`tests/execution/test_builder_sim.py:62` git-init precedent), one Python fixture package with a
deliberate import cycle + tests, one mixed JS/Python fixture. All brain-dependent paths tested with
`tests/factories.py::fake_brain`.

Key cases: model extraction correctness on the fixture; command detection per config-file kind;
cycle found / cycle predicted before apply; `ReplaceInFile` must-match-once; transaction rollback
restores byte-identical content and leaves an unrelated dirty file untouched; gate failure → nothing
applied; approaches deterministic without brain; tie-break reproducible; `forkPlan` uses approach
seeds when flag on and generic angles when off (regression); plan_mixin injection fail-open.

Regression guards: `python tools/dev.py fast` green, `python tools/size_audit.py` zero must_split,
`python tools/repo_map.py` regenerated (AGENTS.md rows for three new packages), existing E6 tests
untouched and green.

## 6. Proof of concept (success criteria)

1. **On 9to5 itself**: `extractProject(PROJECT_ROOT)` yields a model whose import edges/commands
   match known truth (pytest detected as test command; no load-time cycles — cross-checked against
   `repo_map.toplevel_import_graph`); `explore` ranks approaches for a real goal; a
   `RefactorTransaction` applies + rolls back a synthetic edit safely.
2. **On one external project**: clone a small real repo (e.g. `pallets/itsdangerous`) into the
   scratchpad (network fallback: generated fixture project), extract model, detect its test command,
   run cycle check, run brain-free exploration. Results recorded in the PR/final report.
3. **No regressions**: full fast lane green, size audit clean, E6/verification behavior with new
   flags off byte-identical.

## 7. Docs

`docs/ARCHITECTURE.md` gains a short "Any-project capabilities" section; `AGENTS.md` regenerated;
`docs/edit_recipes/refactor_multi_file.md` new recipe (how to use `RefactorTransaction` +
`predictImpact` for module splits); `CLAUDE.md` Tree Guide line updated (three new product domains).
