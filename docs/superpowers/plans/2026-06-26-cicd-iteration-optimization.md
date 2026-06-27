# CI/CD & Iteration-Speed Hyper-Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Significantly speed up every by-hand feedback loop on the 9TO5 repo — GitHub Actions CI and the local test/verify inner-loop — without losing test coverage.

**Architecture:** Three tiers in increasing risk. Tier 0 = zero production-code risk (CI config + local tooling). Tier 1 = CI restructure (pytest + xdist + lanes). Tier 2 = core hot-path refactors (`identity.py` repo-walk, `selfCodeFiles` caching, retrieval isolation, lazy `ollama` imports) that speed tests *and* production `runFull`. Deliver incrementally; run the focused verification after each task before proceeding.

**Tech Stack:** Python 3.11/3.12, pytest 9.1 + pytest-xdist, GitHub Actions, `uv`, existing `tools/dev.py` / `tools/affected_tests.py` / `tools/repo_map.py`.

**Evidence source:** `docs/CICD_OPTIMIZATION.md` (full audit, file:line citations).

**Branch:** do this work on a dedicated branch `perf/cicd-iteration` cut from the current branch; commit per task. The working tree is already dirty with unrelated changes — only stage files named in each task.

**Pre-existing caveat:** `tests/test_repo_map.py::test_no_drift` fails until `python tools/repo_map.py` is run (24 stale headers from the dirty branch). Regenerate before any commit that adds `@AI-MAP` headers, and re-run after Tier 2 (which edits `identity.py`/`orchestrator.py`/`epoch.py`).

---

## File Structure

| File | Responsibility | Tier |
|---|---|---|
| `.github/workflows/tests.yml` | CI: concurrency, triggers, pytest lanes, matrix, uv | 0,1 |
| `.github/workflows/ci.yml` | DELETE — redundant shim job | 0 |
| `requirements-dev.txt` | Create — dev/test-only deps (pytest, xdist, timeout) | 0 |
| `tools/dev.py` | Make `_xdist()` graceful; add `lf` subcommand | 0 |
| `pytest.ini` | Add `addopts = -ra --strict-markers` | 0 |
| `identity.py` | Prune-during-walk; memoize `_canonical` of constant roots | 2 |
| `epoch.py` | Consume cached `selfCodeFiles`; mtime-aware divergence | 2 |
| `orchestrator.py` | Per-run `selfCodeFiles` cache; lazy `ollama` import | 2 |
| `agents/architect.py`, `agents/replanner.py`, `agents/elaborator.py` | Lazy `ollama` import | 2 |
| `tests/conftest.py` | Add `_isolate_experience_db` autouse fixture | 2 |
| `tests/test_dry_run.py`, `tests/test_builder_sim.py` | Mock retrieval; mark/make-fast | 2 |
| `tests/test_epoch*.py`, `tests/test_identity.py` | Mock `selfCodeFiles` in unit tests | 2 |
| `tests/test_obsidian_atomic_claude_md.py` | Reduce iterations + throttle reader | 2 |
| `tests/test_elaborator.py` | Update 5 patch sites for lazy `_OLLAMA` | 2 |
| `docs/TESTING.md`, `docs/CICD_OPTIMIZATION.md` | Document new lanes/commands | 0,1,2 |

---

## TIER 0 — Zero production-code risk

### Task 1: GitHub CI structural fixes (concurrency, triggers, drop redundant workflow)

**Files:**
- Modify: `.github/workflows/tests.yml:1-9`
- Delete: `.github/workflows/ci.yml`
- Modify: `docs/CICD_OPTIMIZATION.md` (mark Tier-0 CI items done)

- [ ] **Step 1: Add concurrency + split triggers in `tests.yml`**

Replace the header (`tests.yml:1-9`) with:

```yaml
name: tests

on:
  push:
    branches: [main]
  pull_request:
    branches: ["**"]

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
```

Rationale: feature-branch pushes now run once via `pull_request` (not push+PR twice); superseded runs are cancelled. `push` still guards direct pushes to `main`.

- [ ] **Step 2: Delete the redundant workflow**

`ci.yml` runs `python tests/test_registry.py`, a shim over `tests/test_workflows_registry.py` already covered by `unittest discover -s tests`.

Run: `git rm .github/workflows/ci.yml`

- [ ] **Step 3: Verify YAML parses**

Run: `python -c "import yaml,glob; [yaml.safe_load(open(f,encoding='utf-8')) for f in glob.glob('.github/workflows/*.yml')]; print('yaml ok')"`
Expected: `yaml ok`

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/tests.yml docs/CICD_OPTIMIZATION.md
git commit -m "ci: cancel superseded runs, end push+PR double-run, drop redundant ci.yml"
```

---

### Task 2: Unbreak the local fast loop (xdist-graceful `dev.py`, dev deps, addopts)

**Files:**
- Modify: `tools/dev.py:139-149` (`_xdist`), add `lf` subcommand
- Create: `requirements-dev.txt`
- Modify: `pytest.ini:1-16`

- [ ] **Step 1: Read the current `_xdist` and subcommand dispatch**

Run: `python tools/dev.py --help` (note available subcommands) and read `tools/dev.py:139-189`.

- [ ] **Step 2: Make `_xdist()` graceful**

In `tools/dev.py`, change `_xdist()` (around `:139-141`) so `-n auto` is only added when xdist is importable:

```python
def _xdist():
    try:
        import xdist  # noqa: F401
    except ImportError:
        return []
    return ["-n", "auto", "--dist", "loadscope"]
```

This unbreaks `dev.py fast` / `dev.py test` whether or not xdist is installed.

- [ ] **Step 3: Add an `lf` subcommand**

Add a last-failed command mapping to `pytest --lf -q` (mirror an existing `cmd_*` + its dispatch entry):

```python
def cmd_lf(args):
    return _run([sys.executable, "-m", "pytest", "--lf", "-q", *args.extra])
```
Register it in the subcommand table next to `fast`/`affected`.

- [ ] **Step 4: Create `requirements-dev.txt`**

```
pytest>=9
pytest-xdist>=3.6
pytest-timeout>=2.3
```

- [ ] **Step 5: Add `addopts` to `pytest.ini`**

After `testpaths = tests` (`pytest.ini:5`), add:

```
addopts = -ra --strict-markers
```
Do NOT add `-n auto` (would break bare `pytest` until xdist is a hard dep) and do NOT add `-p no:cacheprovider` (would break `--lf`).

- [ ] **Step 6: Install dev deps and verify the loop works**

Run:
```
pip install -r requirements-dev.txt
python tools/dev.py fast
```
Expected: fast lane runs in parallel (no `unrecognized arguments: -n` error), green except the known pre-existing `test_no_drift`.

- [ ] **Step 7: Verify `--strict-markers` didn't reject existing markers**

Run: `python -m pytest --collect-only -q 2>&1 | tail -3`
Expected: 2793 tests collected, no marker errors.

- [ ] **Step 8: Commit**

```bash
git add tools/dev.py requirements-dev.txt pytest.ini
git commit -m "dev: xdist-graceful dev.py + lf subcommand, dev requirements, strict markers"
```

---

## TIER 1 — CI restructure (pytest + xdist + lanes)

### Task 3: Convert `tests.yml` to pytest fast/slow lanes, trim matrix, uv installs

**Files:**
- Modify: `.github/workflows/tests.yml` (jobs)
- Modify: `docs/TESTING.md` (document CI lanes)

- [ ] **Step 1: Rewrite the `unittest` job as fast/slow lanes with uv + xdist**

Replace the `unittest` job body so install uses `uv`, tests use pytest, and the matrix is conditional:

```yaml
  tests:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: >-
          ${{ (github.event_name == 'pull_request')
              && fromJSON('["3.11","3.12"]') || fromJSON('["3.12"]') }}
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - name: Install dependencies
        run: uv pip install --system -r requirements.txt -r requirements-dev.txt
      - name: Fast lane (parallel)
        run: python -m pytest -m "not slow" -n auto --dist loadscope -q
      - name: Slow lane (PR only)
        if: github.event_name == 'pull_request'
        run: python -m pytest -m slow -n auto --dist loadscope -q
      - name: Validate workflow definitions
        run: python validate_workflows.py
```

- [ ] **Step 2: Gate the `smoke` job to PRs only**

Add under `smoke:` (after `smoke:` key, before `runs-on`):

```yaml
  smoke:
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
```

- [ ] **Step 3: Verify YAML parses**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/tests.yml',encoding='utf-8')); print('ok')"`
Expected: `ok`

- [ ] **Step 4: Dry-run the exact fast-lane command locally**

Run: `python -m pytest -m "not slow" -n auto --dist loadscope -q 2>&1 | tail -5`
Expected: parallel run, far below the 183s serial baseline; green except pre-existing `test_no_drift`. If any test fails ONLY under xdist, note it for Task 6's experience-db fixture (most likely culprit) before relying on CI.

- [ ] **Step 5: Document the lanes in `docs/TESTING.md`**

Add a short "CI lanes" subsection: fast lane on every push (py3.12), full matrix + slow + smoke on PR→main; local equivalent `python tools/dev.py fast`.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/tests.yml docs/TESTING.md
git commit -m "ci: pytest fast/slow lanes with xdist, conditional matrix, uv installs, PR-gated smoke"
```

---

## TIER 2 — Core hot-path refactors (DANGER_MAP — read `docs/DANGER_MAP.md` first)

### Task 4: Prune `identity.py` repo-walk + memoize canonical roots

**Files:**
- Modify: `identity.py:31-44` (`_canonical`/`_isUnder`), `identity.py:124-137` (`selfCodeFiles`)
- Test: `tests/test_identity_perf.py` (create)

- [ ] **Step 1: Read the current implementation**

Read `identity.py:20-140` to confirm `selfCodeFiles()` uses `PROJECT_ROOT.rglob("*.py")` then filters, and `_canonical` calls `os.path.realpath` per file against constant roots.

- [ ] **Step 2: Write the failing/guard test**

Create `tests/test_identity_perf.py`:

```python
"""Guards: selfCodeFiles must not descend into excluded trees, and stays correct."""
import identity


def test_excludes_non_self_and_vcs_trees():
    files = {str(p) for p in identity.selfCodeFiles()}
    bad = [f for f in files if any(seg in f.replace("\\", "/")
           for seg in ("/.git/", "/.claude/", "/venv/", "/.venv/", "/node_modules/"))]
    assert bad == [], f"walk descended into excluded trees: {bad[:5]}"


def test_selfcodefiles_still_finds_core_modules():
    names = {p.name for p in identity.selfCodeFiles()}
    assert {"orchestrator.py", "identity.py", "epoch.py"} <= names
```

- [ ] **Step 3: Run it (baseline — may already pass on correctness, will guard the refactor)**

Run: `python -m pytest tests/test_identity_perf.py -v`
Expected: PASS now (establishes the invariant the refactor must preserve).

- [ ] **Step 4: Refactor `selfCodeFiles` to prune during traversal**

Replace the `rglob("*.py")` enumeration with an `os.walk` that prunes excluded dirs in-place before descending (skip `_NON_SELF_TREES`, `.git`, `venv`/`.venv`, `.claude`, `__pycache__`, `node_modules`). Keep the existing post-filter as a safety net. Memoize `_canonical()` of the constant roots (`_DIR_ROLES`, `_NON_SELF_TREES`, `_FINGERPRINT_EXCLUDE_DIRS`) once at import rather than per file.

- [ ] **Step 5: Verify correctness + speed**

Run: `python -m pytest tests/test_identity_perf.py tests/test_identity.py tests/test_epoch.py -v`
Expected: all PASS.
Run: `python -c "import time,identity; t=time.time(); identity.selfCodeFiles(); print('walk', round(time.time()-t,3),'s')"`
Expected: well under 0.5s (was ~3.85s).

- [ ] **Step 6: Regenerate repo-map headers + commit**

```bash
python tools/repo_map.py
git add identity.py tests/test_identity_perf.py AGENTS.md
git commit -m "perf(identity): prune repo-walk during traversal + memoize canonical roots"
```

---

### Task 5: Cache `selfCodeFiles` per run; mtime-aware divergence

**Files:**
- Modify: `epoch.py:94-96` (`diverged`/`fingerprint`), `orchestrator.py:52-63` (`_checkCodeDivergence`)
- Test: `tests/test_epoch.py` (extend)

- [ ] **Step 1: Read `epoch.fingerprint`/`diverged` and `orchestrator._checkCodeDivergence`**

Confirm `_checkCodeDivergence` triggers a full `fingerprint()` walk per subtask boundary (4×/run).

- [ ] **Step 2: Write the failing test (walk called once per run)**

Add to `tests/test_epoch.py`:

```python
def test_divergence_check_does_not_rewalk_each_call(monkeypatch):
    import identity, orchestrator
    calls = {"n": 0}
    real = identity.selfCodeFiles
    def counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)
    monkeypatch.setattr(identity, "selfCodeFiles", counting)
    # simulate repeated divergence checks within one run
    orch = orchestrator._fresh_for_test() if hasattr(orchestrator, "_fresh_for_test") else None
    # fall back: call epoch.fingerprint twice with a per-run cache and assert single walk
    import epoch
    epoch._reset_run_cache()
    epoch.fingerprint(); epoch.fingerprint()
    assert calls["n"] <= 1
```

(If a `_fresh_for_test`/`_reset_run_cache` seam does not exist, add a minimal per-run cache + reset hook to `epoch.py` and use that; keep the public API unchanged.)

- [ ] **Step 3: Run it**

Run: `python -m pytest tests/test_epoch.py::test_divergence_check_does_not_rewalk_each_call -v`
Expected: FAIL (currently re-walks).

- [ ] **Step 4: Implement a per-run `selfCodeFiles` cache + mtime short-circuit**

Add a per-run memo (keyed on run id / explicit reset) so `fingerprint()` reuses the file list and only re-hashes when an mtime changed. Reset at run start in `orchestrator`.

- [ ] **Step 5: Verify**

Run: `python -m pytest tests/test_epoch.py tests/test_epoch_hook.py tests/test_epoch_state.py tests/test_dry_run.py -v`
Expected: PASS.

- [ ] **Step 6: Regenerate headers + commit**

```bash
python tools/repo_map.py
git add epoch.py orchestrator.py tests/test_epoch.py AGENTS.md
git commit -m "perf(epoch): per-run selfCodeFiles cache, mtime-aware divergence (4 walks/run -> 1)"
```

---

### Task 6: Isolate experience DB + mock retrieval in pipeline tests

**Files:**
- Modify: `tests/conftest.py` (add `_isolate_experience_db` autouse fixture)
- Modify: `tests/test_dry_run.py`, `tests/test_builder_sim.py` (mock retrieval)

- [ ] **Step 1: Add the autouse experience-db isolation fixture**

In `tests/conftest.py`, mirroring `_isolate_state` (`:93-105`):

```python
@pytest.fixture(autouse=True)
def _isolate_experience_db(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "EXPERIENCE_DB_PATH", tmp_path / "experience.db", raising=False)
    yield
```

- [ ] **Step 2: Verify no test reads the live 33 MB DB anymore**

Run: `python -m pytest tests/test_dry_run.py tests/test_builder_sim.py -v`
Expected: PASS and visibly faster per test.

- [ ] **Step 3: Mock retrieval in the pipeline tests for the remaining cost**

In `test_dry_run.py` / `test_builder_sim.py`, patch `memory.retrieval.retrieve` and `retrieval.lessons_block` to return `[]`/`""` (only if Step 2 still shows multi-second retrieval cost). Keep assertions intact.

- [ ] **Step 4: Verify timing**

Run: `python -m pytest tests/test_dry_run.py tests/test_builder_sim.py --durations=8 -q`
Expected: top durations well below the prior 12-17s.

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py tests/test_dry_run.py tests/test_builder_sim.py
git commit -m "perf(tests): isolate experience.db per-test + mock retrieval in pipeline tests"
```

---

### Task 7: Lazy `ollama` imports

**Files:**
- Modify: `orchestrator.py:28,379`, `agents/architect.py:21`, `agents/replanner.py:20`, `agents/elaborator.py:19,25`
- Modify: `tests/test_elaborator.py` (5 patch sites)

- [ ] **Step 1: Confirm the patch sites and the module-globals invariant**

Read `tests/test_module_globals.py` (asserts `_OLLAMA` is `None` at import for architect/replanner) and the 5 `mock.patch.object(elaborator._OLLAMA, "chat")` sites in `tests/test_elaborator.py`.

- [ ] **Step 2: Defer the imports**

Move `import ollama` from module top into the function that builds the client: `orchestrator.__init__` (`:379` `else` branch), `architect._getOllama`, `replanner._getOllama`. In `elaborator.py`, convert module-level `_OLLAMA = ollama.Client(...)` (`:25`) to a lazy `_getOllama()` that imports + builds on first use.

- [ ] **Step 3: Update `elaborator` consumers + tests**

Replace `_OLLAMA.chat(...)` usage in `elaborator._chat` with `_getOllama().chat(...)`. Update the 5 test patch sites to patch the lazy seam (e.g. `mock.patch("agents.elaborator._getOllama")` returning a fake client).

- [ ] **Step 4: Verify behavior + startup saving**

Run: `python -m pytest tests/test_elaborator.py tests/test_module_globals.py tests/test_architect.py tests/test_replanner.py -v`
Expected: PASS.
Run: `python -c "import time;t=time.time();import orchestrator;print('import orchestrator',round(time.time()-t,3),'s')"`
Expected: ~0.15s (was ~0.44s).

- [ ] **Step 5: Regenerate headers + commit**

```bash
python tools/repo_map.py
git add orchestrator.py agents/architect.py agents/replanner.py agents/elaborator.py tests/test_elaborator.py AGENTS.md
git commit -m "perf(imports): defer ollama import in orchestrator/architect/replanner/elaborator"
```

---

### Task 8: Make-fast / re-tag the remaining heavy tests

**Files:**
- Modify: `tests/test_obsidian_atomic_claude_md.py:23,28`
- Modify: `tests/test_epoch.py`, `tests/test_epoch_hook.py`, `tests/test_epoch_state.py`, `tests/test_identity.py` (mock `selfCodeFiles` in pure-unit tests)

- [ ] **Step 1: Throttle the obsidian concurrency test**

Reduce writer `range(25)` → `range(5)` (`:23`) and add a sub-ms `time.sleep(0.001)` in the reader spin loop (`:28`). The atomicity assertion is unchanged.

- [ ] **Step 2: Mock `selfCodeFiles` in pure-unit epoch/identity tests**

For tests asserting immutability/roundtrip/boundary-set (not the real file set), wrap with `mock.patch("identity.selfCodeFiles", return_value=[<tmp file>])` — copy the existing pattern at `test_epoch.py:14,52`.

- [ ] **Step 3: Verify correctness + fast-lane time**

Run: `python -m pytest tests/test_obsidian_atomic_claude_md.py tests/test_epoch.py tests/test_identity.py -v`
Expected: PASS.
Run: `python -m pytest -m "not slow" -q --durations=10 2>&1 | tail -14`
Expected: fast lane materially below baseline (target ~65-70s serial / far less parallel); no single fast-lane test >5s except intentionally-kept ones.

- [ ] **Step 4: Commit**

```bash
git add tests/test_obsidian_atomic_claude_md.py tests/test_epoch.py tests/test_epoch_hook.py tests/test_epoch_state.py tests/test_identity.py
git commit -m "perf(tests): throttle obsidian concurrency test, mock selfCodeFiles in unit tests"
```

---

## Final verification (after all tiers)

- [ ] **Full suite green under xdist**

Run: `python -m pytest -n auto --dist loadscope -q 2>&1 | tail -5`
Expected: green (or only the known `test_no_drift` until `python tools/repo_map.py` is run — run it, then re-run).

- [ ] **Repo-map drift clean**

Run: `python -m pytest tests/test_repo_map.py -q`
Expected: PASS (after `python tools/repo_map.py`).

- [ ] **Update `docs/CICD_OPTIMIZATION.md`** marking shipped items and recording the measured before/after fast-lane and `import orchestrator` numbers.

---

## Self-review notes

- **Spec coverage:** every audit surface in `docs/CICD_OPTIMIZATION.md` maps to a task — CI structural (Task 1), local loop (Task 2), CI lanes (Task 3), identity walk (Task 4), selfCodeFiles cache (Task 5), retrieval/db isolation (Task 6), import tax (Task 7), heavy-test make-fast (Task 8).
- **Risk ordering:** zero-risk config first; DANGER_MAP core last, each behind a focused test and `tools/repo_map.py` regen.
- **xdist dependency:** Task 2 installs xdist + makes `dev.py` graceful before Task 3 relies on `-n auto`; CI installs it via `requirements-dev.txt`.
- **Known interaction:** Task 6's experience-db fixture is the most likely fix if any test fails only under xdist in Task 3 Step 4 — Task 6 can be pulled earlier if needed.
