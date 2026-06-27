# CI/CD & Iteration-Speed Optimization

Living doc tracking bottlenecks and fixes to speed up every feedback loop in 9TO5
(GitHub CI, local test runs, and the autonomous orchestrate→execute→verify loop).

Status: **initial findings captured; full multi-surface audit pending.**

---

## Surface 1 — GitHub Actions test CI (`.github/workflows/tests.yml`)

### Findings (measured 2026-06-26)

| Fact | Value |
|---|---|
| Test files | 190 |
| Tests collected | 2793 |
| Fast lane (`-m "not slow"`) | 2564 tests, **183s serial** (local) |
| Slow lane (`-m slow`) | 229 tests; individual tests 4–17s (subprocess/e2e/dry-run) |
| CI runner | `python -m unittest discover -s tests -v` |
| Parallelism | none (serial); `pytest-xdist` not installed |
| Python matrix | 3.11 **and** 3.12 on **every push and PR** (2× cost) |
| Extra job | `smoke`: `main.py --dry-run` + `main.py --e2e` |

### Root cause
CI slowness is **not** test count. It is execution strategy:
1. Runs serially via `unittest` — ignores the `slow`/`not slow` split already defined in `pytest.ini`.
2. Runs the **entire** suite (incl. slow subprocess/e2e tests) on every push.
3. Doubles everything across a 2-version matrix on every push.

The repo already built a fast/slow split + per-test 60s timeout in `pytest.ini`, but CI
never uses pytest, so that investment is wasted.

### Candidate fixes (no coverage loss)
- Add `pytest-xdist`; run `pytest -n auto` → parallel across runner cores (183s serial → est. ~40–60s).
- Use the existing split: fast lane (`-m "not slow"`) on every branch push; full suite (incl. slow) only on PR→main / main.
- Trim the routine matrix: 3.12 on push; both 3.11+3.12 only on PR→main.
- Switch `unittest discover` → `pytest` so split + timeout + xdist all apply.

### Slowest fast-lane tests (top, local)
```
17.30s test_builder_sim.py::test_builder_produces_and_really_verifies_files
16.00s test_dry_run.py::test_full_simulated_run_completes
15.72s test_builder_sim.py::test_no_scaffolding_left_behind
14.24s test_dry_run.py::test_garbage_brain_spec_does_not_crash_the_run
12.77s test_dry_run.py::test_failing_executor_degrades_to_partial_without_hanging
12.14s test_dry_run.py::test_resume_completes_a_stranded_run
10.82s test_obsidian_atomic_claude_md.py::test_concurrent_writes_are_never_torn
```
Several heavyweight integration tests are NOT marked `slow` and run in the fast lane — candidate for re-tagging.

### Note (pre-existing, unrelated)
`tests/test_repo_map.py::test_no_drift` currently fails because the uncommitted branch is
out of sync with committed repo-map/AGENTS.md headers (24 files). Fix before commit:
`python tools/repo_map.py`.

---

### GitHub Actions structural fixes (audit 2026-06-26)

> **Status:** P0s shipped on `perf/cicd-iteration` — concurrency cancel-in-progress + `push.branches:[main]` (`tests.yml`), `ci.yml` deleted. P1/P2 in Task 3.

Worst case **8 runner jobs per push** to a PR branch: `tests.yml` fires on `push` AND
`pull_request` for `["**"]` (2 unittest matrix + 1 smoke = 3 each) + `ci.yml` (1 each).
~half are exact duplicates, and superseded runs are never cancelled.

| Pri | Change | Saving | Risk | File |
|---|---|---|---|---|
| P0 | Add `concurrency: {group, cancel-in-progress: true}` | kills superseded runs (often 50%+ of minutes for rapid iteration) | none | `tests.yml`, `ci.yml` top |
| P0 | Stop push+PR double-run: `push.branches: [main]` (was `["**"]`) | ~50% of jobs per feature push | very low | `tests.yml:3-7` |
| P0 | Delete `ci.yml` — `tests/test_registry.py` is a shim already covered by `unittest discover` | 1-2 jobs | none | `ci.yml` (whole) |
| P1 | Test cmd → `pytest -m "not slow" -n auto -q` (drop `-v`, use fast/slow split) | ~3-4× on test phase | medium (confirm green under xdist) | `tests.yml:31` |
| P1 | Trim matrix: 3.12 on push; 3.11+3.12 only on PR→main | halves unittest job per push | low | `tests.yml:12-15` |
| P1 | Swap `pip` → `uv` (`astral-sh/setup-uv`, `uv pip install --system`) | install ~60-120s → ~5-15s | low | `tests.yml:25-28,49-52` |
| P2 | Gate `smoke` (incl. `main.py --e2e`, the most expensive step) + slow lane to PR→main only | drops smoke from routine pushes | low | `tests.yml:36-39` |
| P2 | Split heavy deps (`playwright`, `google-genai`) out of test job via `requirements-test.txt` | ~10-30s install | medium (verify no import needs them) | `requirements.txt` |

**Target end state:** feature push → 1 job (`pytest -m "not slow" -n auto`, py3.12). PR→main → fast lane (both py) + slow lane + smoke. Full coverage preserved at the merge gate.

---

## Surface 2 — Local dev verify inner-loop (Terminal A / by-hand Claude Code)

**Big finding: the fast loop is already built but disabled.** `tools/dev.py` ships
`check` / `fast` / `test` / `affected` / `watch`, and `tools/affected_tests.py::targets_for()`
→ `tools/repo_map.py::find_tests()` already maps a changed file → its tests.

- **BUG:** `tools/dev.py:139-149` `_xdist()` unconditionally injects `-n auto`, but
  `pytest-xdist` is **not installed** → `dev.py fast` and `dev.py test` error
  `unrecognized arguments: -n`. This is the exact command `docs/TESTING.md:19,22` prescribes.
  `dev.py check` / `affected` / `watch` use plain `pytest -q` and work today.
- `pytest.ini` has **no `addopts`**; cache provider enabled → `--lf` / `--ff` work now
  (`.pytest_cache` already holds 13 last-failed).

### Fixes (mostly zero-setup)
| Pri | Change | Impact |
|---|---|---|
| P0 | Use today: `pytest --lf -q` (re-run only failures), `python tools/dev.py check <file>` (changed-only) | 190 tests → seconds |
| P0 | Make `tools/dev.py:_xdist()` graceful — inject `-n auto` only if `xdist` importable | unbreaks `dev.py fast`/`test` |
| P1 | `pip install pytest-xdist` + add to dev requirements | full fast lane → tens of seconds |
| P1 | Add `addopts = -ra --strict-markers` to `pytest.ini` (NOT `-n auto`, NOT `-p no:cacheprovider`) | catches typo'd markers; keeps `--lf` |
| P2 | Add `dev.py lf` subcommand → `pytest --lf -q` | one-word red→green loop |

---

## Surface 3 — Test runtime: 143s of the 183s is ~19 tests (and it's a PRODUCTION cost too)

`slow` auto-tagging (`tests/conftest.py:51-64`) is **filename-substring only**
(`e2e/integration/fuzz/simulation/...`) — structurally blind to what a test does, so
heavy tests like `test_builder_sim.py` (`"sim"` ≠ `"simulation"`) and `test_dry_run.py`
run full `runFull` pipelines in the fast lane.

**Two unmocked subsystems dominate — and the autonomous loop pays them live:**
- **Epoch fingerprint repo-walk** — `identity.py:129` `PROJECT_ROOT.rglob("*.py")` enumerates
  **14,337 files** to keep 143; `_canonical()` (`identity.py:31-38`) `realpath` called **238,496×**;
  `_isUnder` re-canonicalizes constant roots per file. `epoch.fingerprint()` = 3.85s cold, run
  **4×/run** via `orchestrator.py:59 _checkCodeDivergence` (~15-19s/run).
- **Memory retrieval scans real 33 MB `state/experience.db`** — `memory/retrieval.py:116-165`
  cosines **7,803 rows** (~6-13s) even under the no-Ollama sandbox; `_isolate_state` does not
  redirect `experience.db`.

### Fixes (ranked; #1-#3 also speed production `runFull`)
| # | Change | File:line | Saving |
|---|---|---|---|
| 1 | Prune during traversal (`os.walk`, skip non-self/venv/.git/.claude before descending) instead of `rglob` then filter | `identity.py:124-137` | 3.85s → ~0.1-0.3s/walk |
| 2 | Memoize `_canonical()` for the constant roots (compute once at import) | `identity.py:31-44` | ~200k syscalls gone |
| 3 | Cache `selfCodeFiles()` per run; compare mtimes instead of re-walk+re-hash each subtask | `orchestrator.py:59`, `epoch.py:94-96` | 4 walks/run → 1 |
| 4 | Mock `retrieval.retrieve` / `lessons_block` (or empty tmp `db_path`) in pipeline tests | `test_dry_run.py`, `test_builder_sim.py` | ~6-13s/test |
| 5 | `mock.patch("identity.selfCodeFiles", ...)` in epoch/identity unit tests (copy `test_epoch.py:14,52`) | `test_epoch*.py`, `test_identity.py` | ~3.8s → ~0.05s each |
| 6 | Obsidian test: writer `range(25)→5` + throttle reader spin | `test_obsidian_atomic_claude_md.py:23,28` | 9s → ~1s |

**Outcomes:** re-tag only → fast lane ~40s (cost hidden in slow lane). **Make-fast (#1-#6,
recommended) → fast lane ~65-70s with zero tests moved, AND ~15s off every production run.**

---

## Surface 4 — Parallelization (`pytest -n auto`)

**Verdict: SAFE-WITH-FIXES.** xdist is process-based, so module globals
(`monitoring/tracker.py:34-37`, `webdash._SERVER`) are per-worker and safe. conftest already
isolates state/Discord/Ollama/browser per `tmp_path`.

- Use **`pytest -n auto --dist loadscope`** (group by module → keeps a file's tests on one
  worker; covers the lone fixed-port test `test_webdash_control.py:79` and module-global tests).
- One optional belt-and-suspenders autouse fixture to isolate the shared experience DB
  (`config.EXPERIENCE_DB_PATH` → `tmp_path`), mirroring `_isolate_state` (`tests/conftest.py:93-105`).
- `pytest-xdist` + `execnet` are pure-Python, <1 MB. `timeout_method=thread` is xdist-compatible.

---

## Surface 5 — Per-process import tax

`import ollama` at module top costs **~0.30s/process** but is only needed when a real brain
Client is built (never under test). Deferring drops `import orchestrator` 0.44s → 0.145s.

| File:line | Action | Risk |
|---|---|---|
| `orchestrator.py:28` | move `import ollama` into `__init__` (`else ollama.Client(...)`, `:379`) | low |
| `agents/architect.py:21` | move `import ollama` into `_getOllama()` | low |
| `agents/replanner.py:20` | move `import ollama` into `_getOllama()` | low |
| `agents/elaborator.py:19,25` | lazy `_getOllama()` for module-level `_OLLAMA = ollama.Client(...)`; update 5 patch sites in `test_elaborator.py` | medium |

All four use `from __future__ import annotations` (string hints), none catch `ollama.*`.
All must land together to fully kill the tax. `google.genai` (1.56s) / `playwright` already lazy.
pytest collection 1.22s (healthy); bytecode cache on.

---

## Prioritized roadmap (consolidated)

- **Tier 0 — zero production risk, biggest immediate relief:** CI P0s (concurrency, trigger
  split, drop `ci.yml`); fix `tools/dev.py` xdist-graceful; `pip install pytest-xdist` + dev reqs;
  `addopts = -ra --strict-markers`; start using `pytest --lf` / `dev.py check <file>`.
- **Tier 1 — CI restructure:** pytest + `-n auto --dist loadscope` + fast/slow lanes; matrix trim;
  `uv` installs; gate smoke/slow to PR→main.
- **Tier 2 — deeper, touches core (DANGER_MAP):** `identity.py` walk + canonical memoization +
  `selfCodeFiles` caching; retrieval mock/isolation + experience-db fixture; `ollama` lazy imports;
  re-tag/make-fast the heavy tests. Speeds tests **and** production `runFull`.
