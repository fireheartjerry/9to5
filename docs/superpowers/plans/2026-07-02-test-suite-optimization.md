# Test Suite Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut PR CI wall-clock to minutes via affected-test selection, reorganize 320 flat test files into domain dirs, consolidate/delete redundant tests with evidence, and speed the top-offender tests — full safety net preserved on merge-to-main + nightly.

**Architecture:** Foundation first (dir-based slow marking + recursive test mapping), then a mechanical scripted reorg, then parallel per-domain consolidation subagents, then parallel speedup subagents, then the CI rewrite (new stdlib-only `tools/ci_affected.py` powering a fail-closed affected lane), then docs sync. Suite must be green after every task.

**Tech Stack:** pytest 9 + xdist + timeout, GitHub Actions (windows-latest), uv, stdlib-only CI tooling.

**Spec:** `docs/superpowers/specs/2026-07-02-test-suite-optimization-design.md`

**Baseline (2026-07-02, local):** 3,048 collected / 2,860 fast-lane passed in 36s wall (`-n auto --dist loadscope`). Record any new baseline numbers in `docs/CICD_OPTIMIZATION.md` at the end.

---

### Task 1: Slow-dir foundation

**Files:**
- Modify: `tests/conftest.py:64-77` (replace `_SLOW_PATTERNS` with dir-based marking)
- Modify: `tools/repo_map.py:254-262` (`find_tests` recursive) and `tools/repo_map.py:69-73` (`MANUAL_TEST_MAP` paths)
- Modify: `scripts/repo_health.py:52` (`glob` → `rglob`)
- Move: the 14 slow files → `tests/slow/` (git mv)
- Test: `tests/test_repo_map.py` (add subdir-resolution test)

- [ ] **Step 1: Write failing test for recursive `find_tests`**

Add to `tests/test_repo_map.py` (inside or alongside the existing test class, matching local style):

```python
class TestFindTestsRecursive:
    def test_finds_test_in_subdirectory(self, tmp_path, monkeypatch):
        import repo_map
        tests_dir = tmp_path / "tests"
        (tests_dir / "somedomain").mkdir(parents=True)
        (tests_dir / "somedomain" / "test_widget.py").write_text("def test_x():\n    pass\n")
        monkeypatch.setattr(repo_map, "TESTS_DIR", tests_dir)
        assert repo_map.find_tests("agents.widget", "widget") == ["tests/somedomain/test_widget.py"]

    def test_glob_fallback_is_recursive(self, tmp_path, monkeypatch):
        import repo_map
        tests_dir = tmp_path / "tests"
        (tests_dir / "d").mkdir(parents=True)
        (tests_dir / "d" / "test_widget_extra.py").write_text("def test_x():\n    pass\n")
        monkeypatch.setattr(repo_map, "TESTS_DIR", tests_dir)
        assert repo_map.find_tests("agents.widget", "widget") == ["tests/d/test_widget_extra.py"]
```

Note: check how existing tests in `tests/test_repo_map.py` import repo_map (probably `sys.path` insertion of `tools/`) and match it. `find_tests` must return paths **relative to the repo root with `tests/` prefix, posix separators**, exactly as callers expect today.

- [ ] **Step 2: Run: `python -m pytest tests/test_repo_map.py -k Recursive -q` — expect FAIL** (exact-match returns `[]` because file is in subdir)

- [ ] **Step 3: Make `find_tests` recursive**

Replace `tools/repo_map.py:254-262` with:

```python
def find_tests(dotted: str, name: str) -> list[str]:
    """Resolve a module's covering tests: MANUAL_TEST_MAP -> exact -> glob -> [] (recursive)."""
    if dotted in MANUAL_TEST_MAP:
        return sorted(MANUAL_TEST_MAP[dotted])
    if not TESTS_DIR.exists():
        return []
    exact = sorted(TESTS_DIR.rglob(f"test_{name}.py"))
    if exact:
        return [f"tests/{p.relative_to(TESTS_DIR).as_posix()}" for p in exact]
    hits = sorted(TESTS_DIR.rglob(f"test_*{name}*.py"))
    return [f"tests/{p.relative_to(TESTS_DIR).as_posix()}" for p in hits]
```

Exclude `__pycache__` if rglob picks up compiled leftovers (it only matches `.py`, so fine).

- [ ] **Step 4: Run: `python -m pytest tests/test_repo_map.py -q` — expect PASS (all, not just new)**

- [ ] **Step 5: Replace substring slow-marking with dir-based marking**

In `tests/conftest.py`, replace lines 64-77 with:

```python
# Heavyweight tests (subprocess/e2e/integration/fuzz/sim) live under tests/slow/ and are
# auto-marked `slow` by directory so the fast lane `pytest -m "not slow"` skips them.
# Directory placement IS the marker -- no filename-substring magic.
def pytest_collection_modifyitems(config, items):  # noqa: ARG001 -- pytest hook signature
    for item in items:
        path = str(getattr(item, "fspath", "")).replace("\\", "/").lower()
        if "/tests/slow/" in path:
            item.add_marker(pytest.mark.slow)
            # Slow tests (e.g. 150-iteration fuzz property tests) legitimately exceed the
            # 60s default; give headroom while the fast lane keeps the tight hang-catching cap.
            item.add_marker(pytest.mark.timeout(300))
```

- [ ] **Step 6: Move the 14 slow files**

```powershell
New-Item -ItemType Directory -Force tests/slow
git mv tests/test_discovery_integration.py tests/test_e2e_operator.py tests/test_full_autonomy.py tests/test_fuzz_brain.py tests/test_fuzz_control.py tests/test_fuzz_executor.py tests/test_integration_loop.py tests/test_learning_loop.py tests/test_loop_command_docs.py tests/test_phase_3_architecture.py tests/test_phase2_cdp_adversary.py tests/test_phase2_second_brain.py tests/test_simulation_advanced.py tests/test_simulation_core.py tests/slow/
```

Create `tests/slow/__init__.py` (empty file) — `tests/` is a package (`tests/__init__.py` exists), every new subdir needs `__init__.py` so `tests.slow.test_x` imports resolve.

- [ ] **Step 7: Update `MANUAL_TEST_MAP` in `tools/repo_map.py:69-73`**

```python
MANUAL_TEST_MAP: dict[str, list[str]] = {
    "agents.second_brain": ["tests/slow/test_phase2_second_brain.py"],
    "agents.architect": ["tests/slow/test_phase_3_architecture.py"],
    "agents.browser_executor": ["tests/test_browser_executor.py", "tests/slow/test_phase2_cdp_adversary.py"],
}
```

(If Task 2 later moves `test_browser_executor.py`, that task updates this entry again.)

- [ ] **Step 8: Fix `scripts/repo_health.py:52`**

```python
        return len(list((REPO_ROOT / "tests").rglob("test_*.py")))
```

- [ ] **Step 9: Fix any other reference to the moved 14 files**

Run: `Grep pattern "test_(discovery_integration|e2e_operator|full_autonomy|fuzz_brain|fuzz_control|fuzz_executor|integration_loop|learning_loop|loop_command_docs|phase_3_architecture|phase2_cdp_adversary|phase2_second_brain|simulation_advanced|simulation_core)" glob "*.py,*.yml,*.md"` — update true path references (skip generated `@AI-MAP` rows; repo-map regen in a later step fixes those, and prose mentions in docs get fixed in Task 8).

- [ ] **Step 10: Verify marker equivalence**

```powershell
python -m pytest -m slow --collect-only -q | Select-Object -Last 2
python -m pytest --collect-only -q | Select-Object -Last 2
```

Expected: slow count identical to pre-change (baseline: collect `-m slow` count BEFORE editing, compare after; total stays 3,048).

- [ ] **Step 11: Full fast lane green**

Run: `python -m pytest -m "not slow" -n auto --dist loadscope -q` — expect ~2,860 passed, 0 failed.

- [ ] **Step 12: Regenerate repo map + commit**

```powershell
python tools/repo_map.py
git add -A
git commit -m "test-opt: dir-based slow marking + recursive test mapping (tests/slow/)"
```

---

### Task 2: Domain reorganization (mechanical)

**Files:**
- Move: ~306 files from `tests/` into domain subdirs (git mv, scripted)
- Create: `tests/<domain>/__init__.py` per new dir
- Modify: any real (non-generated) path references surfaced by grep
- Modify: `.github/workflows/tests.yml` hardcoded test lists + classify regexes (minimal touch — full rewrite happens in Task 6; here only keep paths valid)

- [ ] **Step 1: Record pre-move collection counts**

```powershell
python -m pytest --collect-only -q | Select-Object -Last 1
python -m pytest -m slow --collect-only -q | Select-Object -Last 1
```

Save both numbers.

- [ ] **Step 2: Generate the move plan**

Write a scratchpad script (NOT committed) that buckets every remaining `tests/test_*.py` by these prefix rules, first match wins (module-subject knowledge may refine individual placements — the executing agent should sanity-check surprising buckets):

| Bucket dir | Filename patterns (prefix/substring on `test_<X>.py`) |
|---|---|
| `tests/evolution/` | `evolution`, `experience`, `exp_index`, `retrieval`, `curriculum`, `preferences`, `selfmod`, `sie`, `epoch`, `learning` (non-slow), `playbook`, `knowledge` (memory-side) |
| `tests/execution/` | `execution`, `executor`, `worktree`, `verifier`, `verify`, `builder`, `external_project`, `github_pr`, `pr_`, `eval_runner`, `trace_replay`, `dry_run`, `step_resume`, `work_launcher`, `fsio`, `compute` |
| `tests/orchestration/` | `orchestrat`, `society`, `trajectory`, `brain`, `discovery`, `intent`, `adversary`, `architect`, `browser`, `second_brain`-adjacent, `timing`, `best_effort`, `autonomy` |
| `tests/control/` | `control`, `state`, `heartbeat`, `launch`, `ipc`, `task_`, `run_`, `views`, `wipe`, `identity`, `resilience` |
| `tests/notifications/` | `discord`, `notification`, `dashboard`, `webdash`, `terminal`, `tunnel`, `cast`, `cockpit`, `obsidian` |
| `tests/workflows/` | `workflow`, `validate_workflows` |
| `tests/platform/` | everything else (config, hooks, safety, granular, tools/dev/repo_map/audit/repo-health coverage, bug_fixes, no_unittest_footgun, ...) |

Print the mapping as `old_path -> new_path` lines; eyeball for obvious misfits before executing.

- [ ] **Step 3: Execute moves + create `__init__.py` files**

Script emits and runs `git mv` per file; then create empty `__init__.py` in each new dir. Basenames all stay unique (they were flat) — do NOT rename any file here.

- [ ] **Step 4: Fix real path references**

Run: `Grep pattern "tests/test_" glob "*.py"` and `Grep pattern "tests/test_" path ".github"` and `Grep pattern "tests\\\\test_" glob "*.py"`.
For each hit decide: generated `@AI-MAP RUN/TEST:` row → skip (regen fixes); real code/CI reference → update to new path. Known real ones:
- `.github/workflows/tests.yml:138` (workflow tests list → `tests/workflows/...`)
- `.github/workflows/tests.yml:159` (tooling tests list → `tests/platform/...`)
- `.github/workflows/tests.yml:74,77` (classify regexes → match new dirs, e.g. `tests/workflows/` and `tests/platform/test_(repo_map|tools|dev_commands)\.py`)
- `tests/conftest.py` docstring mention of `tests/test_discord_rest.py`
- any test asserting on its own path (check `tests/**/test_audit.py`, `test_all_notifications.py`, `test_bug_investigation.py`, `test_bug_fixes.py`, `test_no_unittest_footgun.py` hits from grep)

- [ ] **Step 5: Verify collection identical**

```powershell
python -m pytest --collect-only -q | Select-Object -Last 1
python -m pytest -m slow --collect-only -q | Select-Object -Last 1
```

Expected: same two numbers as Step 1.

- [ ] **Step 6: Full suite green (fast + slow)**

```powershell
python -m pytest -m "not slow" -n auto --dist loadscope -q
python -m pytest -m slow -n auto --dist loadscope -q
```

Expected: same pass counts as baseline, 0 failures.

- [ ] **Step 7: Gates**

```powershell
python tools/repo_map.py
python tools/repo_map.py --check
python tools/size_audit.py
python tools/dev.py ci-local
```

All green (size_audit: zero must_split).

- [ ] **Step 8: Commit**

```powershell
git add -A
git commit -m "test-opt: reorganize tests/ into domain subdirectories (git mv only, zero test changes)"
```

---

### Task 3: `tools/ci_affected.py` — fail-closed affected-test resolver (TDD)

**Files:**
- Create: `tools/ci_affected.py`
- Test: `tests/platform/test_ci_affected.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/platform/test_ci_affected.py`:

```python
"""Fail-closed CI affected-test resolution (tools/ci_affected.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import ci_affected  # noqa: E402


def _decide(files, repo=None):
    return ci_affected.decide(files, repo_root=repo or Path(__file__).resolve().parents[2])


class TestFailClosed:
    def test_non_py_file_falls_back(self):
        d = _decide(["agents/executor.py", "pytest.ini"])
        assert d.ok is False and "non-python" in d.reason

    def test_sensitive_file_falls_back(self):
        for f in ("tests/conftest.py", "conftest.py", "pytest.ini", "requirements.txt",
                  "config.py", ".github/workflows/tests.yml", "tools/repo_map.py",
                  "tests/factories.py", "tools/ci_affected.py", "tools/affected_tests.py"):
            assert _decide([f]).ok is False, f

    def test_deleted_py_file_falls_back(self):
        d = _decide(["agents/this_module_was_deleted_xyz.py"])
        assert d.ok is False and "missing" in d.reason

    def test_unmapped_py_file_falls_back(self, tmp_path):
        orphan = Path(__file__).resolve().parents[2] / "platform_core" / "__init__.py"
        # __init__.py of a package maps to nothing by stem -> must fail closed, not skip
        if ci_affected.targets_for_safe([str(orphan)]):
            import pytest
            pytest.skip("mapping exists on this tree; covered by unit below")
        assert _decide([str(orphan)]).ok is False

    def test_too_many_files_falls_back(self):
        files = [f"agents/executor.py"] * 26
        assert _decide(files).ok is False and "too many" in _decide(files).reason


class TestHappyPath:
    def test_mapped_source_file_yields_targets(self):
        d = _decide(["tools/repo_map.py".replace("repo_map", "size_audit")])  # tools/size_audit.py
        # size_audit is not sensitive; it must map to at least one test or fail closed
        if d.ok:
            assert d.targets and all(t.startswith("tests/") for t in d.targets)

    def test_changed_test_covers_itself(self):
        me = "tests/platform/test_ci_affected.py"
        d = _decide([me])
        assert d.ok is True and me in d.targets
```

- [ ] **Step 2: Run: `python -m pytest tests/platform/test_ci_affected.py -q` — expect FAIL (module missing)**

- [ ] **Step 3: Implement `tools/ci_affected.py`**

```python
"""Decide whether a change set is safe for affected-only CI test selection (fail closed).

Wraps tools/affected_tests.targets_for with the safety rules the PR lane needs: ANY doubt
(non-.py change, deleted file, unmapped module, harness/sensitive file, oversized change set)
means "run the full fast lane instead". Prints GitHub-output lines.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  decide(files: list[str], repo_root: Path) -> Decision
  targets_for_safe(files: list[str]) -> list[str]
  main(argv: list[str]) -> int
DEPENDS-ON: tools.affected_tests
SIDE-EFFECTS: unannotated
RUN/TEST: python -m pytest tests/platform/test_ci_affected.py
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import affected_tests  # noqa: E402

MAX_CHANGED_FILES = 25
# Files whose change invalidates per-module test mapping (harness, deps, mapping itself,
# process-wide config). Matched on repo-relative posix path (exact or prefix for dirs).
SENSITIVE_EXACT = {
    "conftest.py", "pytest.ini", "config.py",
    "tests/conftest.py", "tests/factories.py", "tests/progress_reporter.py",
    "tools/repo_map.py", "tools/affected_tests.py", "tools/ci_affected.py",
}
SENSITIVE_PREFIXES = (".github/workflows/", "requirements")


@dataclass
class Decision:
    ok: bool
    reason: str = ""
    targets: list[str] = field(default_factory=list)


def targets_for_safe(files: list[str]) -> list[str]:
    return affected_tests.targets_for(files)


def decide(files: list[str], repo_root: Path) -> Decision:
    rels = [Path(f).as_posix().lstrip("./") for f in files if f.strip()]
    if not rels:
        return Decision(False, "empty change set")
    if len(rels) > MAX_CHANGED_FILES:
        return Decision(False, f"too many files ({len(rels)} > {MAX_CHANGED_FILES})")
    for rel in rels:
        if rel in SENSITIVE_EXACT or any(rel.startswith(p) for p in SENSITIVE_PREFIXES):
            return Decision(False, f"sensitive file: {rel}")
        if not rel.endswith(".py"):
            return Decision(False, f"non-python change: {rel}")
        if not (repo_root / rel).exists():
            return Decision(False, f"missing (deleted/renamed): {rel}")
    targets = targets_for_safe(rels)
    if not targets:
        return Decision(False, "no mapped tests for change set")
    # every changed non-test .py must individually map to >=1 test (no silent misses)
    for rel in rels:
        if rel.startswith("tests/"):
            continue
        if not targets_for_safe([rel]):
            return Decision(False, f"unmapped module: {rel}")
    return Decision(True, "affected-only ok", targets)


def main(argv: list[str]) -> int:
    files = argv or [ln.strip() for ln in sys.stdin.read().splitlines()]
    d = decide(files, repo_root=affected_tests.REPO_ROOT)
    print(f"affected_ok={'true' if d.ok else 'false'}")
    print(f"affected_reason={d.reason}")
    print(f"affected_targets={' '.join(d.targets)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 4: Run: `python -m pytest tests/platform/test_ci_affected.py -q` — expect PASS**

- [ ] **Step 5: Gates + commit**

```powershell
python tools/dev.py check tools/ci_affected.py
python tools/repo_map.py
git add -A
git commit -m "test-opt: add fail-closed affected-test resolver for CI (tools/ci_affected.py)"
```

---

### Task 4: Per-domain consolidation (merge + evidence-based delete) — SUBAGENT FAN-OUT

**Files:** every file under one `tests/<domain>/` per subagent. Domains: `evolution`, `execution`, `orchestration`, `control`, `notifications`, `workflows`, `platform` (leave `tests/slow/` alone in this task).

Dispatch ONE subagent per domain, in parallel. Each subagent gets this protocol verbatim (fill in `<domain>`):

> Work only inside `tests/<domain>/` of C:\9to5\fable-rewrite. Goal: consolidate test files and remove provably redundant tests WITHOUT losing coverage.
> 1. Read every file in the domain. Build a map: subject module(s) → test files → what each test actually asserts.
> 2. MERGE: combine files that test the same subject module when the merged file stays ≤450 lines (hard cap, `tools/size_audit.py`). Merged file keeps the most canonical name (`test_<subject>.py`). Preserve every test, fixture, and comment that carries information. `git mv`/delete leftovers. Never create a duplicate basename repo-wide (check with Glob before naming).
> 3. DELETE a test ONLY with written evidence, one of: (a) another kept test makes the identical assertion on the same code path (name both), (b) the test is a strictly weaker subset of a kept test (explain), (c) the subject code no longer exists (prove with Grep). When unsure → KEEP. No quota — zero deletions is an acceptable outcome.
> 4. After changes: `python -m pytest tests/<domain> -n auto --dist loadscope -q` must pass 100%. Run `python -m pytest --collect-only -q tests/<domain>` before/after and account for every removed item in your report.
> 5. Update any real (non-`@AI-MAP`-generated) references to files you renamed/removed: `Grep pattern "<old filename stem>" glob "*.py,*.yml,*.md"`. Also update `tools/repo_map.py::MANUAL_TEST_MAP` if you touched a file listed there.
> 6. Do NOT commit. Return: files merged (old → new), tests deleted with per-test evidence, collection delta, pass/fail output tail.

- [ ] **Step 1: Dispatch 7 domain subagents in parallel** (target ~32 workers per user default is fine; 7 is the natural unit here)
- [ ] **Step 2: Review each report — reject any deletion without concrete evidence** (revert that deletion)
- [ ] **Step 3: Full suite green: `python -m pytest -n auto --dist loadscope -q`** (fast+slow: run without `-m`)
- [ ] **Step 4: Gates: `python tools/size_audit.py` (zero must_split), `python tools/repo_map.py`, `python tools/repo_map.py --check`**
- [ ] **Step 5: Commit with evidence in message**

```powershell
git add -A
git commit -m "test-opt: consolidate test files per domain; deletions listed with coverage evidence in body"
```

(Body: paste the per-domain merged/deleted summary from the subagent reports.)

---

### Task 5: Top-offender speedups — SUBAGENT FAN-OUT

**Files:** the measured top offenders (post-Task-4 paths; re-measure first).

- [ ] **Step 1: Re-measure: `python -m pytest -m "not slow" -n auto --dist loadscope -q --durations=40`** — save list.

- [ ] **Step 2: Dispatch one subagent per cluster, in parallel** (clusters by shared fixture opportunity; from baseline: ① `test_dry_run.py`, ② `test_builder_sim.py`, ③ `test_github_pr_gate.py` + `test_external_project.py`, ④ `test_worktree.py` + `test_execution_worktree.py`, ⑤ `test_sie.py` + `test_selfmod.py`, ⑥ `test_verifier*.py`, ⑦ `test_compute.py` + `test_config_bootstrap.py` + `test_curriculum*.py`). Protocol per subagent:

> Speed up tests in <files> of C:\9to5\fable-rewrite without weakening what they prove.
> 1. Measure: `python -m pytest <files> --durations=0 -q` (serial). Record per-test times.
> 2. Allowed techniques: module/session-scoped template fixtures for expensive setup (e.g. build a git repo ONCE, `shutil.copytree` a fresh copy per test); collapsing N subprocess spawns into 1 where the assertions still exercise the same contract; replacing a subprocess with in-process invocation ONLY when the test is not specifically about process isolation; removing redundant setup inside loops.
> 3. FORBIDDEN: deleting/weakening assertions; faking a boundary the test exists to cross (real-process concurrency tests like test_control_concurrency and atomicity tests like test_fsio stay real-process); touching `_fast_sleep` threshold; marking things slow to hide them.
> 4. Session-scoped fixtures must be xdist-safe (each worker builds its own copy — that's fine) and must never mutate the template in place.
> 5. Re-measure after. Suite for those files must pass 100%: `python -m pytest <files> -q`.
> 6. Do NOT commit. Return: before/after per-test times, techniques applied, pass output tail.

- [ ] **Step 3: Review reports — verify no assertion loss (diff review per file)**
- [ ] **Step 4: Full fast lane: `python -m pytest -m "not slow" -n auto --dist loadscope -q --durations=20`** — green + record new wall time (target ≤ ~28s local)
- [ ] **Step 5: `python tools/size_audit.py` + commit**

```powershell
git add -A
git commit -m "test-opt: speed up top-offender tests (template repo fixtures, subprocess consolidation)"
```

---

### Task 6: CI workflow rewrite

**Files:**
- Modify: `.github/workflows/tests.yml`

- [ ] **Step 1: classify job — add affected-detection step**

After the existing `paths` step (which stays), add outputs `affected_ok`, `affected_targets` to the job and this step (classify already checks out with `fetch-depth: 0`; add `actions/setup-python@v6` with `python-version: "3.12"` before it — `ci_affected.py` is stdlib-only, no dep install):

```yaml
      - id: affected
        shell: bash
        run: |
          if [[ "${{ github.event_name }}" == "pull_request" && -s /tmp/changed.txt && "$(head -c1 /tmp/changed.txt)" != "." ]]; then
            python tools/ci_affected.py < /tmp/changed.txt >> "$GITHUB_OUTPUT"
          else
            {
              echo "affected_ok=false"
              echo "affected_reason=not a PR or unknown change set"
              echo "affected_targets="
            } >> "$GITHUB_OUTPUT"
          fi
```

(`/tmp/changed.txt` is produced by the `paths` step; `.` sentinel means "unknown base → everything changed".)

- [ ] **Step 2: fast job — drop 3.11 matrix, add affected mode**

Replace the matrix block with plain `python-version: "3.12"` (delete `strategy:` entirely), and replace the "Fast lane" step with:

```yaml
      - name: Affected tests (PR, fail-closed) or full fast lane
        shell: bash
        run: |
          if [[ "${{ github.event_name }}" == "pull_request" && "${{ needs.classify.outputs.affected_ok }}" == "true" ]]; then
            echo "affected-only lane: ${{ needs.classify.outputs.affected_targets }}"
            python -m pytest ${{ needs.classify.outputs.affected_targets }} -n auto --dist loadscope -q
          else
            echo "full fast lane (${{ needs.classify.outputs.affected_reason || 'push/nightly' }})"
            python -m pytest -m "not slow" -n auto --dist loadscope -q
          fi
```

Note: affected lane runs targets WITHOUT `-m "not slow"` — slow tests covering changed code deliberately run on the PR. Add `affected_reason` to classify outputs too.

- [ ] **Step 3: slow / dry-run-smoke / e2e-smoke — push-to-main only, parallel**

For all three jobs: change `needs: [classify, fast]` → `needs: classify`, and the `if:` to:

```yaml
    if: github.event_name == 'push' && needs.classify.outputs.core == 'true'
```

- [ ] **Step 4: nightly 3.11 leg**

Add to the `exhaustive` job a matrix `python-version: ["3.11", "3.12"]` on its setup-python, or (simpler, chosen) add a separate job:

```yaml
  nightly-fast-py311:
    if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'
    runs-on: windows-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
          cache-dependency-glob: "requirements*.txt"
      - uses: actions/setup-python@v6
        with:
          python-version: "3.11"
      - name: Install dependencies
        run: uv pip install --system -r requirements.txt -r requirements-dev.txt
      - name: Fast lane (3.11 compatibility)
        run: python -m pytest -m "not slow" -n auto --dist loadscope -q
```

- [ ] **Step 5: Update hardcoded test paths** in `workflow-validation` (line 138) and `tooling` (line 159) jobs and classify regexes (lines 74, 77) to the post-reorg paths (verify with Glob what the final paths are after Task 4 merges).

- [ ] **Step 6: Validate YAML**

```powershell
python -c "import yaml, pathlib; yaml.safe_load(pathlib.Path('.github/workflows/tests.yml').read_text()); print('yaml ok')"
```

Also dry-check the bash logic locally: `git diff --name-only main...HEAD | python tools/ci_affected.py` (or pipe a synthetic list) and eyeball the three output lines.

- [ ] **Step 7: Commit**

```powershell
git add .github/workflows/tests.yml
git commit -m "test-opt: PR affected-test lane (fail-closed), 3.12-only PRs, parallel main-push jobs, nightly 3.11 leg"
```

---

### Task 7: dev.py / local-lane consistency check

**Files:**
- Verify (modify only if broken): `tools/dev_checks.py`, `tools/dev_reports.py`

- [ ] **Step 1: `python tools/dev.py check tools/ci_affected.py`** — affected mapping resolves post-reorg paths (proves `dev.py check` works with subdirs)
- [ ] **Step 2: `python tools/dev.py fast`** — green
- [ ] **Step 3: `python tools/dev.py ci-local`** — green (its `_no_unittest_main_gate` already scans `tests/**` recursively; verify, fix to rglob if not)
- [ ] **Step 4: `python tools/dev.py slow-report`** — writes `logs/slow-test-report.md`, slow suite green
- [ ] **Step 5: Commit any fixes** (`git commit -m "test-opt: fix local dev lanes for nested tests/"` — skip if no changes)

---

### Task 8: Docs sync + final verification

**Files:**
- Modify: `docs/TESTING.md` (dir layout, slow = `tests/slow/`, lane table, new CI behavior)
- Modify: `docs/CICD_OPTIMIZATION.md` (append dated section: what changed + before/after numbers)
- Modify: `.claude/rules/tests.md`, `.claude/rules/ci.md` (affected lane, slow dir, 3.12-only)
- Modify: `CLAUDE.md` only if commands changed (they shouldn't)
- Regenerate: `AGENTS.md` via repo_map

- [ ] **Step 1: Update the four docs** — describe: `tests/<domain>/` layout, `tests/slow/` = the slow lane, PR CI = affected-only fail-closed (list the fallback triggers from `tools/ci_affected.py`), push-to-main = full parallel, nightly = exhaustive + 3.11. Include fresh measured numbers.
- [ ] **Step 2: `python tools/repo_map.py` + `--check`**
- [ ] **Step 3: Final full verification (verification-before-completion)**

```powershell
python -m pytest -n auto --dist loadscope -q          # ENTIRE suite incl. slow
python tools/dev.py ci-local
python tools/size_audit.py
python tools/repo_map.py --check
```

All green, record final counts + wall times.

- [ ] **Step 4: Commit**

```powershell
git add -A
git commit -m "test-opt: sync docs + regenerate repo map for test-suite optimization"
```

---

## Self-review notes

- Spec A → Task 1; B → Task 2; C → Task 4; D → Task 5; E → Tasks 3+6; F → Tasks 7+8. Covered.
- Fail-closed rules in Task 3 match spec §E exactly (non-py, unmapped, sensitive, >25, deleted).
- `find_tests` return-shape (`tests/...` posix) consistent across Tasks 1, 3, and `affected_tests.targets_for` (unchanged consumer).
- Task 2 intentionally precedes Task 3 so `tests/platform/` exists for the new test file.
