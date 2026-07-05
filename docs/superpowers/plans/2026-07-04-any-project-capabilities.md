# Any-Project Capabilities Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three new root packages — `introspect/` (runtime project model for any root), `refactor/` (cycle detection, impact prediction, atomic multi-file transactions), `explore/` (approach generation → trade-off scoring → synthesis) — plus flag-gated wiring into plan_mixin and fork_policy, tests, docs, and a PoC on 9to5 + one external project.

**Architecture:** Pure stdlib leaf-layer libraries (`explore → introspect ← refactor`; none imports orchestration). Wiring is two narrow fail-open touches in `platform_core/orchestration/`. Spec: `docs/superpowers/specs/2026-07-04-any-project-capabilities-design.md` — read it first; it is the source of truth for behavior.

**Tech Stack:** Python 3.12 stdlib only (`ast`, `pathlib`, `dataclasses`, `json`, `re`, `py_compile`, `subprocess` for gate commands). Pytest via `python tools/dev.py check <file>` / domain dirs `tests/{introspect,refactor,explore}/`.

**Conventions (every task):** `@AI-MAP v1` module doc header (format: `.claude/rules/modularity.md`), `from __future__ import annotations`, camelCase functions / snake_case variables / ALL_CAPS constants, files ≤300 lines ideal (450 hard), functions ≤70 lines. Run tests with **pytest only** (never bare unittest — live `.env` creds). Commit after each task.

---

## Locked interfaces (single source of truth — all tasks conform to these)

```python
# ---- introspect/project_model.py ----
LANG_PYTHON = "python"; LANG_JAVASCRIPT = "javascript"; LANG_TYPESCRIPT = "typescript"; LANG_OTHER = "other"
KIND_TEST = "test"; KIND_BUILD = "build"; KIND_LINT = "lint"; KIND_TYPECHECK = "typecheck"

@dataclass(frozen=True)
class ModuleInfo:
    path: str                          # POSIX relpath from root — the universal module id
    lang: str
    loc: int
    exports: tuple[str, ...] = ()
    imports: tuple[str, ...] = ()      # first-party imports as relpath module ids
    lazy_imports: tuple[str, ...] = () # python in-function imports (not load-time)
    side_effects: tuple[str, ...] = () # subset of {"subprocess","file-write","network","env-read"}

@dataclass(frozen=True)
class DetectedCommand:
    kind: str        # KIND_* above
    cmd: str         # e.g. "python -m pytest"
    source: str      # relpath of the config file that proved it (never guessed)

@dataclass(frozen=True)
class BoundaryMap:
    packages: tuple[str, ...] = ()     # top-level package dirs
    facades: tuple[str, ...] = ()      # modules that only re-export
    entrypoints: tuple[str, ...] = ()  # __main__.py / main.py / package.json "main" / bin scripts
    config_files: tuple[str, ...] = ()

@dataclass(frozen=True)
class ProjectModel:
    root: str                          # absolute path, POSIX separators
    languages: tuple[str, ...]         # descending by file count
    modules: tuple[ModuleInfo, ...]
    import_edges: tuple[tuple[str, str], ...]   # (from relpath, to relpath), load-time only
    commands: tuple[DetectedCommand, ...]
    boundaries: BoundaryMap
    truncated: bool = False            # True when max_files cap hit
    git_head: str = ""                 # "" when not a git repo
    def toJson(self) -> str: ...
    @staticmethod
    def fromJson(text: str) -> "ProjectModel": ...

# ---- introspect facade (project_extract.py, re-exported by introspect/__init__.py) ----
def extractProject(root: str | Path, *, max_files: int = 4000, use_cache: bool = True) -> ProjectModel
def contextForPrompt(model: ProjectModel, *, budget_chars: int = 4000) -> str

# ---- refactor/cycle_detect.py ----
def buildImportGraph(model: ProjectModel) -> dict[str, set[str]]
def findCycles(graph: dict[str, set[str]]) -> list[list[str]]           # iterative Tarjan SCC, sorted output
def wouldCreateCycle(graph, added_edges: list[tuple[str, str]], removed_edges: list[tuple[str, str]] = []) -> list[list[str]]

# ---- refactor/symbol_usages.py ----
@dataclass(frozen=True)
class Usage:
    file: str; line: int; kind: str    # kind in {"name","attr","import"}
def findUsages(root: str | Path, symbol: str) -> list[Usage]            # python files only

# ---- refactor/refactor_edits.py ----
@dataclass(frozen=True)
class WriteFile:      path: str; content: str
@dataclass(frozen=True)
class ReplaceInFile:  path: str; old: str; new: str    # old must occur EXACTLY once
@dataclass(frozen=True)
class DeleteFile:     path: str
@dataclass(frozen=True)
class RenameFile:     path: str; new_path: str
FORBIDDEN_SEGMENTS = (".git", ".env", "venv", ".venv", "node_modules", "__pycache__")
def validateEdit(root: Path, edit) -> str | None       # None = ok, else reason string

# ---- refactor/change_impact.py ----
@dataclass(frozen=True)
class ImpactReport:
    files_touched: tuple[str, ...]
    orphaned_usages: tuple[Usage, ...]        # references to exports a planned edit deletes/renames
    new_cycles: tuple[tuple[str, ...], ...]
    affected_tests: tuple[str, ...]
    ok: bool                                   # no orphans and no new cycles
def predictImpact(model: ProjectModel, edits: list) -> ImpactReport

# ---- refactor/refactor_transaction.py ----
@dataclass(frozen=True)
class RefactorResult:
    applied: bool
    reason: str = ""
    gate_output: str = ""
    files_touched: tuple[str, ...] = ()
class RefactorTransaction:
    def __init__(self, root: str | Path): ...
    def add(self, edit) -> None                                  # raises ValueError on invalid edit
    def preview(self, model: ProjectModel | None = None) -> ImpactReport
    def apply(self, *, gate_cmd: str | None = None, check_cycles: bool = True,
              timeout_s: int = 300) -> RefactorResult

# ---- explore/approach_gen.py ----
APPROACH_ARCHETYPES = ("minimal-patch", "refactor-first", "test-first", "new-module", "bold-redesign")
@dataclass(frozen=True)
class ApproachCandidate:
    approach_id: str        # "a1","a2",...
    title: str
    summary: str            # 1-3 sentences, used as E6 angle_hint
    steps: tuple[str, ...]
    files_touched_estimate: int
    archetype: str
def generateApproaches(goal: str, model: ProjectModel, *, brain=None, n: int = 3) -> list[ApproachCandidate]

# ---- explore/approach_tradeoffs.py ----
W_RISK = 0.35; W_EFFORT = 0.20; W_TESTABILITY = 0.25; W_FIT = 0.20   # composite weights
@dataclass(frozen=True)
class TradeoffScore:
    approach_id: str
    risk: float; effort: float; testability: float; fit: float       # each in [0,1], higher = better
    total: float
def scoreApproaches(candidates: list[ApproachCandidate], model: ProjectModel) -> list[TradeoffScore]  # sorted total desc

# ---- explore/approach_synthesis.py ----
@dataclass(frozen=True)
class SynthesisResult:
    winner: ApproachCandidate
    scores: tuple[TradeoffScore, ...]
    adopted_mitigations: tuple[str, ...]   # steps lifted from runners-up
    rationale: str
def selectOrSynthesize(candidates: list[ApproachCandidate], scores: list[TradeoffScore], *, brain=None) -> SynthesisResult

# ---- explore/__init__.py facade ----
def exploreSolutionSpace(goal: str, root_or_model, *, brain=None, n: int = 3) -> SynthesisResult
```

`brain` is any callable with the existing Brain protocol shape (`platform_core/core/protocols.py`):
`brain(system: str, user: str, *, want_json: bool = False) -> str`. `None` ⇒ deterministic fallback.

**Shared test fixture** (Task 1 creates it; later tasks reuse): `tests/introspect/conftest.py` defines
`fixture_project(tmp_path)` building this tree:

```
proj/
  pyproject.toml            # [tool.pytest.ini_options] present
  pkg/__init__.py           # re-exports from pkg.core (facade)
  pkg/core.py               # def coreFunc(): ...  imports pkg.util
  pkg/util.py               # def helper(): ...    top-level `import subprocess` + subprocess.run at module level
  pkg/cycle_a.py            # imports pkg.cycle_b at top level
  pkg/cycle_b.py            # imports pkg.cycle_a at top level  (deliberate cycle)
  app.js                    # `import {x} from './lib.js'`
  lib.js
  tests/test_core.py        # def test_core(): from pkg.core import coreFunc
```

---

### Task 1: introspect package — model + scanner + shared fixture

**Files:**
- Create: `introspect/__init__.py`, `introspect/project_model.py`, `introspect/project_scanner.py`
- Create: `tests/introspect/__init__.py` (empty), `tests/introspect/conftest.py` (fixture above)
- Test: `tests/introspect/test_project_model.py`, `tests/introspect/test_project_scanner.py`

- [ ] **Step 1: Write failing tests.** `test_project_model.py`: construct a `ProjectModel` with one `ModuleInfo`; assert `ProjectModel.fromJson(m.toJson()) == m` (frozen dataclass equality); assert defaults (`truncated is False`, `git_head == ""`). `test_project_scanner.py` (uses `fixture_project`):

```python
def test_scanner_classifies_and_excludes(fixture_project):
    from introspect.project_scanner import scanProject
    mods = scanProject(fixture_project, max_files=100)
    paths = {m.path for m in mods}
    assert "pkg/core.py" in paths and "app.js" in paths
    assert not any(".git" in p or "__pycache__" in p for p in paths)
    js = next(m for m in mods if m.path == "app.js")
    assert js.lang == "javascript"

def test_scanner_truncates_deterministically(fixture_project):
    from introspect.project_scanner import scanProject
    a = scanProject(fixture_project, max_files=3)
    b = scanProject(fixture_project, max_files=3)
    assert [m.path for m in a] == [m.path for m in b] and len(a) == 3
```

- [ ] **Step 2: Run, verify FAIL** (`python -m pytest tests/introspect/ -v` → import errors).
- [ ] **Step 3: Implement.** `project_model.py` exactly per locked interfaces (toJson via `dataclasses.asdict` + json; fromJson rebuilds nested tuples). `project_scanner.py`: `scanProject(root, *, max_files) -> list[ModuleInfo]` — `os.walk` with `EXCLUDE_DIRS = FORBIDDEN-like set + build/dist/.tox/.pytest_cache/target`, extension→lang map (`.py`→python, `.js/.mjs/.cjs`→javascript, `.ts/.tsx`→typescript), `loc` = line count (UTF-8, `errors="replace"`), sorted by path, cap at `max_files` (scanner returns list; the *facade* sets `truncated`). Exports/imports stay `()` here — filled by graph modules.
- [ ] **Step 4: Run, verify PASS.**
- [ ] **Step 5: Commit** `feat(introspect): project model dataclasses + scanner`.

### Task 2: introspect — python import graph + generic import scan

**Files:**
- Create: `introspect/python_import_graph.py`, `introspect/generic_import_scan.py`
- Test: `tests/introspect/test_python_import_graph.py`, `tests/introspect/test_generic_import_scan.py`

- [ ] **Step 1: Failing tests.**

```python
def test_python_graph_edges_and_lazy(fixture_project):
    from introspect.python_import_graph import analyzePython
    mods = analyzePython(fixture_project, ["pkg/__init__.py","pkg/core.py","pkg/util.py",
                                           "pkg/cycle_a.py","pkg/cycle_b.py","tests/test_core.py"])
    core = mods["pkg/core.py"]
    assert "pkg/util.py" in core.imports            # top-level first-party import resolved to relpath
    assert "coreFunc" in core.exports
    util = mods["pkg/util.py"]
    assert "subprocess" in util.side_effects        # module-level subprocess.run call
    a = mods["pkg/cycle_a.py"]
    assert "pkg/cycle_b.py" in a.imports

def test_generic_scan_js(fixture_project):
    from introspect.generic_import_scan import analyzeGeneric
    mods = analyzeGeneric(fixture_project, ["app.js", "lib.js"])
    assert "lib.js" in mods["app.js"].imports
```

- [ ] **Step 2: Run, verify FAIL.**
- [ ] **Step 3: Implement.** `analyzePython(root, relpaths) -> dict[str, ModuleInfo]`: per file `ast.parse` (SyntaxError ⇒ skeleton info, no crash); exports = public top-level defs/classes honoring `__all__` (pattern: `tools/repo_map.py:223`); imports = `ast.Import/ImportFrom` resolved dotted→relpath **only if the target file is in `relpaths`** (first-party test), split top-level vs in-function (walk with parent tracking; pattern: `tools/repo_map.py:245` `toplevel_only`); relative imports resolved against the module's package; side-effects = module-level `ast.Call` whose func dotted-name starts with `subprocess`/`os.system` ⇒ "subprocess", `open`/`Path(...).write_` ⇒ "file-write", `socket`/`urllib`/`requests`/`httpx` ⇒ "network", `os.environ`/`os.getenv` ⇒ "env-read". `analyzeGeneric`: regex `^\s*import\b.*?from\s+['"](.+?)['"]|require\(\s*['"](.+?)['"]` per line, resolve `./`-relative specifiers against the file's dir (try exact, `+.js`, `+.ts`, `/index.js`), keep only in-set targets.
- [ ] **Step 4: Run, verify PASS.**
- [ ] **Step 5: Commit** `feat(introspect): python AST import graph + generic JS/TS import scan`.

### Task 3: introspect — command detection + test mapping + boundaries

**Files:**
- Create: `introspect/project_commands.py`, `introspect/project_test_map.py`, `introspect/project_boundaries.py`
- Test: `tests/introspect/test_project_commands.py`, `tests/introspect/test_project_test_map.py`, `tests/introspect/test_project_boundaries.py`

- [ ] **Step 1: Failing tests.** Commands: fixture has `pyproject.toml` with pytest section ⇒ `DetectedCommand(kind="test", cmd="python -m pytest", source="pyproject.toml")`; a `package.json` written by the test with `{"scripts":{"test":"jest","lint":"eslint ."}}` ⇒ test+lint commands with `source="package.json"`; empty dir ⇒ `[]` (never guessed). Test map: `mapFileToTests(root, "pkg/core.py", test_globs) → ["tests/test_core.py"]` (exact stem); unknown file → `[]`; JS convention `src/foo.js` → `src/foo.test.js` when present. Boundaries: fixture ⇒ `packages == ("pkg",)`, `"pkg/__init__.py"` in facades (re-export-only), `config_files` contains `pyproject.toml`.
- [ ] **Step 2: Run, verify FAIL.**
- [ ] **Step 3: Implement.** `detectCommands(root) -> list[DetectedCommand]` — parse `pyproject.toml` (`tomllib`), `pytest.ini`/`tox.ini`/`setup.cfg` (configparser presence ⇒ pytest), `package.json` scripts (test/build/lint/typecheck keys), `Makefile` targets (`^(test|build|lint):` lines ⇒ `make <target>`), `Cargo.toml` ⇒ `cargo test/build`, `go.mod` ⇒ `go test ./...`. `mapFileToTests(root, relpath, test_files) -> list[str]` — exact `test_<stem>.py` → progressively shorter prefixes (min 4 chars) → glob `test_*<stem>*.py` (pattern: `tools/repo_map.py:293`), plus `<stem>.test.<ext>`/`<stem>.spec.<ext>` for JS; `overrides: dict[str, list[str]] | None` param checked first. `detectBoundaries(root, modules) -> BoundaryMap` — packages = top-level dirs containing `__init__.py` or ≥3 same-lang files; facade = `.py` whose AST has only imports/`__all__`/docstring; entrypoints = `__main__.py`, root `main.py`, package.json `main`/`bin`; config_files = known names present.
- [ ] **Step 4: Run, verify PASS.**
- [ ] **Step 5: Commit** `feat(introspect): command detection, test mapping, boundary map`.

### Task 4: introspect — extract facade + prompt digest + cache + CLI

**Files:**
- Create: `introspect/project_extract.py`, `introspect/__main__.py`
- Modify: `introspect/__init__.py` (re-export `extractProject`, `contextForPrompt`, `ProjectModel`)
- Test: `tests/introspect/test_project_extract.py`

- [ ] **Step 1: Failing tests.**

```python
def test_extract_full_model(fixture_project):
    from introspect import extractProject
    m = extractProject(fixture_project, use_cache=False)
    assert ("pkg/core.py", "pkg/util.py") in m.import_edges
    assert any(c.kind == "test" for c in m.commands)
    assert m.languages[0] == "python" and not m.truncated

def test_extract_cache_hit(fixture_project, tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "state" / "tasks", raising=False)
    from introspect import extractProject
    m1 = extractProject(fixture_project); m2 = extractProject(fixture_project)
    assert m1 == m2                        # second call served from cache, identical

def test_context_for_prompt_budget(fixture_project):
    from introspect import extractProject, contextForPrompt
    text = contextForPrompt(extractProject(fixture_project, use_cache=False), budget_chars=800)
    assert len(text) <= 800 and "pkg" in text and "pytest" in text
```

- [ ] **Step 2: Run, verify FAIL.**
- [ ] **Step 3: Implement.** `extractProject`: scan → analyzePython/analyzeGeneric → merge ModuleInfos → edges from top-level imports only → commands → boundaries → git_head via `git -C root rev-parse HEAD` (failure ⇒ ""); `truncated=True` when scanner hit cap. Cache: JSON file under `config.STATE_DIR.parent / "project_models" / <sha256(root)[:16]>.json` storing `{key: root+git_head-or-mtimehash, model: …}`; import config lazily inside the function (keep package importable without 9to5 config for external reuse — `try: from config import STATE_DIR; except Exception: cache disabled`). `contextForPrompt`: sections (name/root/languages/commands/packages/entrypoints/top fan-in modules/cycles-count) rendered then hard-truncated at budget. `__main__.py`: `python -m introspect <root> [--json]` prints digest or JSON.
- [ ] **Step 4: Run, verify PASS.** Also run `python -m introspect .` in repo root manually — sanity: pytest detected.
- [ ] **Step 5: Commit** `feat(introspect): extract facade, prompt digest, model cache, CLI`.

### Task 5: refactor — cycle detection + symbol usages

**Files:**
- Create: `refactor/__init__.py`, `refactor/cycle_detect.py`, `refactor/symbol_usages.py`
- Create: `tests/refactor/__init__.py`, `tests/refactor/conftest.py` (imports/reuses the introspect fixture via `from tests.introspect.conftest import *` or a copied fixture)
- Test: `tests/refactor/test_cycle_detect.py`, `tests/refactor/test_symbol_usages.py`

- [ ] **Step 1: Failing tests.**

```python
def test_find_cycles_on_fixture(fixture_project):
    from introspect import extractProject
    from refactor.cycle_detect import buildImportGraph, findCycles
    g = buildImportGraph(extractProject(fixture_project, use_cache=False))
    cycles = findCycles(g)
    assert ["pkg/cycle_a.py", "pkg/cycle_b.py"] in [sorted(c) for c in cycles]

def test_would_create_cycle():
    from refactor.cycle_detect import wouldCreateCycle
    g = {"a": {"b"}, "b": set()}
    assert wouldCreateCycle(g, added_edges=[("b", "a")])          # predicts a→b→a
    assert not wouldCreateCycle(g, added_edges=[("b", "a")], removed_edges=[("a", "b")])

def test_find_usages(fixture_project):
    from refactor.symbol_usages import findUsages
    hits = findUsages(fixture_project, "coreFunc")
    assert any(u.file == "tests/test_core.py" and u.kind == "import" for u in hits)
```

- [ ] **Step 2: Run, verify FAIL.**
- [ ] **Step 3: Implement.** `findCycles`: iterative Tarjan (explicit stack, no recursion), return SCCs of size >1 plus self-loops, each cycle rotated to start at min node, list sorted — fully deterministic. `wouldCreateCycle`: copy graph, apply removed then added edges, `findCycles` on the union of affected nodes' reachable subgraph (or whole graph — fixture-scale fine; note complexity in docstring). `findUsages`: walk `.py` files under root (same EXCLUDE_DIRS), `ast.walk`, `ast.Name` ⇒ "name", `ast.Attribute.attr` ⇒ "attr", `ast.ImportFrom` names ⇒ "import" (generalizes `tools/codemod.py:43`).
- [ ] **Step 4: Run, verify PASS.**
- [ ] **Step 5: Commit** `feat(refactor): cycle detection (Tarjan) + cross-root symbol usages`.

### Task 6: refactor — edit primitives + impact prediction

**Files:**
- Create: `refactor/refactor_edits.py`, `refactor/change_impact.py`
- Test: `tests/refactor/test_refactor_edits.py`, `tests/refactor/test_change_impact.py`

- [ ] **Step 1: Failing tests.** Edits: `validateEdit` rejects absolute paths outside root, `../` escapes, any `FORBIDDEN_SEGMENTS` component (e.g. `WriteFile(".git/hook","x")` and `venv/x.py`); accepts normal relpaths. Impact:

```python
def test_impact_detects_orphans_and_cycle(fixture_project):
    from introspect import extractProject
    from refactor.change_impact import predictImpact
    from refactor.refactor_edits import ReplaceInFile, WriteFile
    model = extractProject(fixture_project, use_cache=False)
    edits = [ReplaceInFile("pkg/core.py", "def coreFunc():", "def coreFn():")]   # rename breaks test_core import
    rep = predictImpact(model, edits)
    assert not rep.ok and any(u.file == "tests/test_core.py" for u in rep.orphaned_usages)
    edits2 = [WriteFile("pkg/util2.py", "from pkg.core import coreFunc\n")]      # util2←core no cycle
    rep2 = predictImpact(model, edits2)
    assert rep2.ok and "tests/test_core.py" in rep2.affected_tests or rep2.affected_tests == ()
```

- [ ] **Step 2: Run, verify FAIL.**
- [ ] **Step 3: Implement.** `predictImpact`: compute post-edit content per touched file (apply edits in memory), re-run `analyzePython` on changed/new files to get new exports/imports; deleted-or-renamed exports = old exports minus new ⇒ `findUsages` each across root, excluding definitions inside the edited file itself ⇒ `orphaned_usages`; edges diff ⇒ `wouldCreateCycle` ⇒ `new_cycles`; touched modules ⇒ `mapFileToTests` ⇒ `affected_tests`; `ok = not orphans and not new_cycles`.
- [ ] **Step 4: Run, verify PASS.**
- [ ] **Step 5: Commit** `feat(refactor): edit primitives + breaking-change impact prediction`.

### Task 7: refactor — atomic transaction + CLI

**Files:**
- Create: `refactor/refactor_transaction.py`, `refactor/__main__.py`
- Modify: `refactor/__init__.py` (re-export all public names per locked interfaces)
- Test: `tests/refactor/test_refactor_transaction.py`

- [ ] **Step 1: Failing tests.**

```python
def test_apply_all_or_nothing_rollback(fixture_project):
    from refactor import RefactorTransaction, WriteFile, ReplaceInFile
    unrelated = fixture_project / "scratch.txt"; unrelated.write_text("dirty", encoding="utf-8")
    before = (fixture_project / "pkg/core.py").read_bytes()
    tx = RefactorTransaction(fixture_project)
    tx.add(ReplaceInFile("pkg/core.py", "def coreFunc():", "def coreFunc():  # touched"))
    tx.add(WriteFile("pkg/broken.py", "def x(:\n"))               # syntax error → gate must fail
    res = tx.apply()
    assert not res.applied and "broken.py" in res.reason + res.gate_output
    assert (fixture_project / "pkg/core.py").read_bytes() == before      # byte-identical restore
    assert not (fixture_project / "pkg/broken.py").exists()              # created file removed
    assert unrelated.read_text(encoding="utf-8") == "dirty"              # unrelated file untouched

def test_apply_success_and_gate_cmd(fixture_project):
    from refactor import RefactorTransaction, WriteFile
    tx = RefactorTransaction(fixture_project)
    tx.add(WriteFile("pkg/extra.py", "VALUE = 1\n"))
    res = tx.apply(gate_cmd='python -c "import sys; sys.exit(0)"')   # shlex-split, run without shell
    assert res.applied and "pkg/extra.py" in res.files_touched

def test_replace_must_match_once(fixture_project):
    from refactor import RefactorTransaction, ReplaceInFile
    tx = RefactorTransaction(fixture_project)
    tx.add(ReplaceInFile("pkg/core.py", "NO_SUCH_TEXT", "x"))
    res = tx.apply()
    assert not res.applied and "match" in res.reason.lower()

def test_new_cycle_blocked(fixture_project):
    from refactor import RefactorTransaction, WriteFile
    tx = RefactorTransaction(fixture_project)
    tx.add(WriteFile("pkg/c1.py", "import pkg.c2\n")); tx.add(WriteFile("pkg/c2.py", "import pkg.c1\n"))
    res = tx.apply()
    assert not res.applied and "cycle" in res.reason.lower()
```

- [ ] **Step 2: Run, verify FAIL.**
- [ ] **Step 3: Implement.** `apply()` phases: (1) validate all edits (`validateEdit`, ReplaceInFile occurrence count == 1 against current content) — any failure ⇒ return before touching disk; (2) snapshot: for each touched path record `bytes | MISSING`; (3) write all edits (parents mkdir'd; RenameFile = read+write+delete); (4) gate: `py_compile.compile(f, doraise=True)` for every touched `.py` → `findCycles` over re-extracted model when `check_cycles` (only flag NEW cycles vs pre-apply graph — pre-existing cycles don't block unrelated edits) → optional `gate_cmd` via `subprocess.run(shlex.split(gate_cmd), cwd=root, timeout=timeout_s, capture_output=True)` (no `shell=True` — command-injection guard) rc 0 required; (5) failure ⇒ restore every snapshot byte-for-byte (MISSING ⇒ unlink), return `applied=False`; success ⇒ `applied=True`. Rollback itself wrapped so a restore error reports loudly in `reason` (never silent). `__main__.py`: `python -m refactor check <root>` prints cycles + module count, exit 1 when cycles found.
- [ ] **Step 4: Run, verify PASS.**
- [ ] **Step 5: Commit** `feat(refactor): atomic multi-file transaction with snapshot rollback + CLI`.

### Task 8: explore — generation, trade-offs, synthesis, facade, CLI

**Files:**
- Create: `explore/__init__.py`, `explore/approach_gen.py`, `explore/approach_tradeoffs.py`, `explore/approach_synthesis.py`, `explore/__main__.py`
- Create: `tests/explore/__init__.py`, `tests/explore/conftest.py` (reuse fixture)
- Test: `tests/explore/test_approach_gen.py`, `tests/explore/test_approach_tradeoffs.py`, `tests/explore/test_approach_synthesis.py`

- [ ] **Step 1: Failing tests.**

```python
def test_generate_brainless_deterministic(fixture_project):
    from introspect import extractProject
    from explore.approach_gen import generateApproaches
    m = extractProject(fixture_project, use_cache=False)
    a = generateApproaches("add input validation to pkg.core", m, n=3)
    b = generateApproaches("add input validation to pkg.core", m, n=3)
    assert [c.approach_id for c in a] == [c.approach_id for c in b] and len(a) == 3
    assert len({c.archetype for c in a}) == 3                    # distinct archetypes

def test_generate_with_brain(fixture_project):
    from tests.factories import fake_brain
    from introspect import extractProject
    from explore.approach_gen import generateApproaches
    brain = fake_brain(as_json=[{"title": "T", "summary": "S", "steps": ["s1"],
                                 "files_touched_estimate": 2, "archetype": "minimal-patch"}])
    out = generateApproaches("goal", extractProject(fixture_project, use_cache=False), brain=brain, n=1)
    assert out[0].title == "T"

def test_scores_sorted_and_bounded(fixture_project): ...   # all fields in [0,1]; sorted total desc; deterministic
def test_synthesis_tiebreak_and_mitigation(fixture_project):
    from explore import exploreSolutionSpace
    r1 = exploreSolutionSpace("add input validation to pkg.core", fixture_project, n=3)
    r2 = exploreSolutionSpace("add input validation to pkg.core", fixture_project, n=3)
    assert r1.winner.approach_id == r2.winner.approach_id       # reproducible
    assert r1.rationale
```

- [ ] **Step 2: Run, verify FAIL.**
- [ ] **Step 3: Implement.** Brainless generation: pick first `n` archetypes; each candidate's steps/summary templated from project traits (has test cmd? facade-heavy? cycles present? entrypoint kind) — e.g. test-first candidate's step 1 references the detected test command. Brain path: one `brain(system, user, want_json=True)` call requesting a JSON list; validate/clamp each item (unknown archetype ⇒ "minimal-patch"; missing fields ⇒ candidate dropped); fewer than n valid ⇒ top up from archetypes. Scoring: risk = 1 − min(1, files_estimate × mean-fan-in-of-project / modules); effort = 1 − min(1, (len(steps) + files_estimate) / 20); testability = 1.0 if project has test command AND archetype=="test-first" else 0.7 with test cmd else 0.2; fit = archetype-vs-project-kind lookup table (library/cli/service inferred from boundaries: setup/pyproject+no main ⇒ library, __main__/bin ⇒ cli, server deps in config ⇒ service). `total = W_RISK*risk + W_EFFORT*effort + W_TESTABILITY*testability + W_FIT*fit`, round 4dp. Synthesis: winner = max total, tie-break (total, −files_estimate, approach_id); adopted_mitigations = steps from runners-up matching MITIGATION_MARKERS ("test", "rollback", "guard", "verify") absent from winner steps (≤2 adopted); rationale = one deterministic sentence citing score components; brain optional to reword rationale only. Facade `exploreSolutionSpace`: accept `ProjectModel` or path (extract if path) → generate → score → synthesize. `__main__.py`: `python -m explore "<goal>" <root>` prints ranked table + winner.
- [ ] **Step 4: Run, verify PASS.**
- [ ] **Step 5: Commit** `feat(explore): approach generation, trade-off scoring, synthesis + CLI`.

### Task 9: config knobs + plan_mixin injection wiring

**Files:**
- Modify: `platform_core/app_config/settings.py` (add 4 knobs beside SOLUTION_FORK_*; follow the exact `_envBool/_envInt` idiom already in that file)
- Modify: `platform_core/orchestration/plan_mixin.py` (inject project context into the plan prompt near line 74)
- Test: `tests/orchestration/test_plan_project_context.py`

- [ ] **Step 1: Read first** `platform_core/app_config/settings.py` (find SOLUTION_FORK block for idiom + placement) and `plan_mixin.py:60-90`. Confirm how `config` re-exports settings (check `config.py`).
- [ ] **Step 2: Failing tests.**

```python
def test_plan_prompt_includes_project_context(pin_flags, monkeypatch, tmp_path):
    pin_flags(PROJECT_INTROSPECTION_ENABLED=True)
    # build tiny project in tmp_path, point work-dir resolution at it, capture the user prompt
    # passed to a fake ollama chat; assert "PROJECT CONTEXT" section present
def test_plan_prompt_fail_open(pin_flags, monkeypatch):
    pin_flags(PROJECT_INTROSPECTION_ENABLED=True)
    monkeypatch.setattr("introspect.project_extract.extractProject", boom)  # raises
    # plan authoring still returns; prompt has no PROJECT CONTEXT section
def test_flag_off_no_injection(pin_flags): ...
```

- [ ] **Step 3: Implement.** Knobs: `PROJECT_INTROSPECTION_ENABLED=True`, `PROJECT_INTROSPECTION_MAX_FILES=4000`, `EXPLORE_APPROACHES_ENABLED=False`, `EXPLORE_APPROACHES_N=3` (env-overridable, same naming style). plan_mixin: private helper `_projectContextBlock(self, work_dir) -> str` — lazy `import introspect` inside function, `try/except Exception: return ""`, budget 3000 chars; append non-empty block to the plan user prompt. Keep helper ≤25 lines.
- [ ] **Step 4: Run** new tests + `python -m pytest tests/orchestration/ -x -q` (regression). PASS required.
- [ ] **Step 5: Commit** `feat(orchestration): project-context injection into planning (flag-gated, fail-open)`.

### Task 10: fork_policy approach-seed wiring

**Files:**
- Modify: `platform_core/orchestration/fork_policy.py` (`forkPlan` only)
- Test: extend `tests/orchestration/test_fork_policy.py` (new test class, do not modify existing tests)

- [ ] **Step 1: Read** `fork_policy.py` fully (110 lines) — understand `forkPlan` signature, `DIVERSITY_ANGLES`, work_profile handling.
- [ ] **Step 2: Failing tests.** Flag on + monkeypatched `explore.exploreSolutionSpace`-level generator returning candidates ⇒ seeds' `angle_hint`s equal candidate summaries (ranked order). Flag off ⇒ byte-identical to current behavior (compare against existing angle bank). Explore raising ⇒ fallback to `DIVERSITY_ANGLES` (fail-open).
- [ ] **Step 3: Implement.** Inside `forkPlan`: when `config.EXPLORE_APPROACHES_ENABLED`, lazy-import `explore`, `generateApproaches(goal_text, extractProject(work_dir), n=n_branches)` → `scoreApproaches` → ranked summaries as angle hints; any Exception ⇒ existing angle logic untouched. Keep the function under 70 lines (extract `_angleHintsFromExplore` helper if needed).
- [ ] **Step 4: Run** `python -m pytest tests/orchestration/test_fork_policy.py -v` — new + old all PASS.
- [ ] **Step 5: Commit** `feat(orchestration): E6 fork seeds from explore approaches (flag-gated)`.

### Task 11: repo-map registration, size audit, docs

**Files:**
- Modify: `tools/repo_map_test_map.py` (MANUAL_TEST_MAP entries ONLY IF `python tools/dev.py check` shows unmapped modules — convention naming should resolve most)
- Modify: `docs/ARCHITECTURE.md` (new short section "Any-project capabilities"), `CLAUDE.md` (Tree Guide line: add introspect/refactor/explore to product domains)
- Create: `docs/edit_recipes/refactor_multi_file.md` (how to split a module safely: predictImpact → RefactorTransaction → gate with detected test cmd; include a worked example)
- Regenerate: `AGENTS.md` + headers via `python tools/repo_map.py`

- [ ] **Step 1:** `python tools/repo_map.py` (splices @AI-MAP headers + regenerates AGENTS.md). Review diff — only expected files.
- [ ] **Step 2:** `python tools/size_audit.py` — zero must_split; split any offender now.
- [ ] **Step 3:** Write the docs listed above (recipe shows real code calling the locked interfaces).
- [ ] **Step 4:** `python tools/dev.py context-check` (CLAUDE.md stays <200 lines).
- [ ] **Step 5: Commit** `docs: register any-project capabilities (AGENTS.md, architecture, recipe)`.

### Task 12: PoC — 9to5 itself + external project

**Files:**
- Create: `scripts/poc_any_project.py` (runnable demo, also serves as living documentation)

- [ ] **Step 1:** Script part A (self): `extractProject(config.PROJECT_ROOT)` → print digest; assert test command detected contains "pytest"; `findCycles` on the model → print count (cross-check vs `tools/repo_map.py` toplevel graph: no NEW load-time cycles among mapped first-party modules); `exploreSolutionSpace("reduce notification latency", PROJECT_ROOT, n=3)` → print ranked approaches; `RefactorTransaction` on a scratch copy (copy 3 files to scratchpad dir, apply+rollback demo) — never mutates the real tree.
- [ ] **Step 2:** Script part B (external): `git clone --depth 1 https://github.com/pallets/itsdangerous` into the scratchpad (skip with clear message if network fails; fallback = generate the fixture project there); extract → digest, detected test cmd, cycle count, 3 brain-free approaches for "add a new serializer".
- [ ] **Step 3:** Run `python scripts/poc_any_project.py` — capture output for the final report.
- [ ] **Step 4: Commit** `feat(scripts): any-project PoC (self + external)`.

### Task 13: full verification

- [ ] **Step 1:** `python tools/size_audit.py` — zero must_split.
- [ ] **Step 2:** `python tools/dev.py fast` — full fast lane green (fix regressions before proceeding).
- [ ] **Step 3:** `python tools/repo_map.py --check` (or rerun + `git diff --stat` empty) — no drift.
- [ ] **Step 4:** Re-run PoC script once more post-everything.
- [ ] **Step 5: Commit** any fixes; final state clean.

---

## Self-review notes

- Spec coverage: §3.1→Tasks 1-4, §3.2→Tasks 5-7, §3.3→Task 8, §3.4→Tasks 9-10 + CLIs in 4/7/8, §5→per-task tests, §6→Task 12, §7→Task 11. No gaps.
- Types cross-checked against the locked-interfaces block (single source of truth all tasks cite).
- Worker independence: Tasks 1-4 sequential (same package, shared fixture); Tasks 5-7 sequential; Task 8 independent of 5-7; Tasks 9-10 independent of each other after 4+8; 11-13 sequential last.
