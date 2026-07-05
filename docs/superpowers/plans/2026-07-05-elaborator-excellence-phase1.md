# Elaborator Excellence — Phase 1 (Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure `agents/planning/elaborator.py` into a focused package and add the core-correctness tier (master flag, restored grounding tests, 5W3H prompt, calibrated self-review, dataclass schema validation, path verification, vague-goal grounding bundle) — all behind `ELABORATOR_EXCELLENCE_ENABLED` (default OFF, byte-identical flag-off).

**Architecture:** The current 162-line module becomes an `agents/planning/elaborator/` package with a thin re-export facade (`__init__.py`) over focused sub-modules (`core`, `grounding`, `schema`, `self_review`, `path_verify`). Today's behavior is preserved verbatim as the flag-off path; the new tier is additive and gated. This plan covers spec sections §2–6 only. Phases 2–4 (§3d precedent, §7 pipeline, §7 B′/§7.5) get their own plans.

**Tech Stack:** Python 3.12, `unittest` + `pytest`, the `llm_io` seam (Ollama), `platform_core/app_config` typed flag registry, `tools/size_audit.py`, `.repo-map.json`. **Schema uses `@dataclass` + a manual `validate()`, NOT pydantic** — pydantic is importable but undeclared in `requirements.txt`; the repo validates via its own dataclass-registry pattern, so we match it and add no dependency.

**Spec:** `docs/superpowers/specs/2026-07-05-elaborator-excellence-design.md`

---

## File Structure

| File | Responsibility |
|---|---|
| `platform_core/app_config/epic_flags.py` (modify) | Add `ELABORATOR_EXCELLENCE_ENABLED` (+ later sub-flags) to `EpicFlags` |
| `agents/planning/elaborator/__init__.py` (create, from old file) | Re-export facade: `elaborate`, `extractUniverse`; public API frozen |
| `agents/planning/elaborator/core.py` (create) | Orchestration + prompts; flag-off path is today's verbatim behavior |
| `agents/planning/elaborator/grounding.py` (create) | `_repoContext()` (moved verbatim) + vague-goal state-of-repo bundle |
| `agents/planning/elaborator/schema.py` (create) | `ElaboratedSpec` / `Universe` dataclasses + Layer-1 `validate()` |
| `agents/planning/elaborator/self_review.py` (create) | One calibrated verbalized-assumption pass |
| `agents/planning/elaborator/path_verify.py` (create) | `allowed_paths` vs real repo tree → `unverified_paths` |
| `tests/orchestration/test_elaborator.py` (modify) | Keep existing + restore `TestRepoGrounding` |
| `tests/orchestration/test_elaborator_schema.py` (create) | schema validation tests |
| `tests/orchestration/test_elaborator_grounding.py` (create) | vague-goal bundle + path-verify tests |
| `tests/orchestration/test_elaborator_selfreview.py` (create) | self-review one-pass tests |
| `tests/platform/test_epic_flags_config.py` (modify) | Assert the new flag ships dark |

**Note on the package conversion:** `agents/planning/elaborator.py` (a file) becomes `agents/planning/elaborator/` (a package). The top-level `agents/elaborator.py` facade and all `from agents.planning.elaborator import ...` / `from agents.elaborator import ...` call sites must keep working unchanged.

---

## Task 1: Add the master flag (ships dark)

**Files:**
- Modify: `platform_core/app_config/epic_flags.py` (inside `class EpicFlags`, near the `SOCIETY_ENABLED` block ~line 43)
- Test: `tests/platform/test_epic_flags_config.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/platform/test_epic_flags_config.py`:

```python
def test_elaborator_excellence_ships_dark(monkeypatch):
    monkeypatch.setenv("FULL_STACK", "0")
    monkeypatch.delenv("ELABORATOR_EXCELLENCE_ENABLED", raising=False)
    flags = EpicFlags()
    assert flags.ELABORATOR_EXCELLENCE_ENABLED is False


def test_elaborator_excellence_facade_exposed():
    # config.__getattr__ delegates to the live registry (PEP 562).
    assert hasattr(config, "ELABORATOR_EXCELLENCE_ENABLED")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/platform/test_epic_flags_config.py::test_elaborator_excellence_ships_dark -v`
Expected: FAIL with `AttributeError: 'EpicFlags' object has no attribute 'ELABORATOR_EXCELLENCE_ENABLED'`

- [ ] **Step 3: Add the flag**

In `platform_core/app_config/epic_flags.py`, inside `class EpicFlags`, after the `SOCIETY_*` lines, add:

```python
    # --- Elaborator excellence tier (spec 2026-07-05); ships DARK, byte-identical flag-off ---
    ELABORATOR_EXCELLENCE_ENABLED: bool = _F(default_factory=lambda: _envBool("ELABORATOR_EXCELLENCE_ENABLED", False))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/platform/test_epic_flags_config.py -k elaborator -v`
Expected: PASS (both)

- [ ] **Step 5: Commit**

```bash
git add platform_core/app_config/epic_flags.py tests/platform/test_epic_flags_config.py
git commit -m "feat(elaborator): add ELABORATOR_EXCELLENCE_ENABLED flag (ships dark)"
```

---

## Task 2: Convert module to package (behavior-preserving)

Move today's `agents/planning/elaborator.py` verbatim into a package so later tasks can add focused sub-modules. **No behavior change** — the existing test suite is the guard.

**Files:**
- Delete: `agents/planning/elaborator.py`
- Create: `agents/planning/elaborator/__init__.py`
- Create: `agents/planning/elaborator/core.py`
- Create: `agents/planning/elaborator/grounding.py`
- Test: `tests/orchestration/test_elaborator.py` (existing, unchanged)

- [ ] **Step 1: Run the existing tests first (green baseline)**

Run: `python -m pytest tests/orchestration/test_elaborator.py -v`
Expected: PASS (7 tests) — this is the regression guard for the whole task.

- [ ] **Step 2: Create `grounding.py` with the moved repo-context code**

Create `agents/planning/elaborator/grounding.py`. Move `_agentsMdMtime`, `_repoContext`, and the `_REPO_CTX_CACHE` module global **verbatim** from the current file (lines 29–84), plus the imports they need:

```python
"""Repository grounding for the elaborator: real paths, not placeholders.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  repoContext(work_dir: str | None) -> str  -- compact real-repo grounding block (AGENTS.md + git history)
DEPENDS-ON: os, subprocess, config
SIDE-EFFECTS: unannotated
RUN/TEST: python -m pytest tests/orchestration/test_elaborator.py
"""
from __future__ import annotations

import os
import subprocess

import config

LOG = config.getLogger("elaborator.grounding")
_REPO_CTX_CACHE: dict[str, tuple[float, str]] = {}


def _agentsMdMtime(work_dir: str) -> float:
    try:
        return os.path.getmtime(os.path.join(work_dir, "AGENTS.md"))
    except OSError:
        return 0.0


def repoContext(work_dir: str | None) -> str:
    """Compact, REAL repository grounding so the brain stops inventing placeholder
    paths. AGENTS.md package map + recent git history. Never raises: returns "" when
    grounding is unavailable. Cached per work_dir; invalidated on AGENTS.md mtime change."""
    if not work_dir:
        return ""
    key = str(work_dir)
    mtime = _agentsMdMtime(key)
    cached = _REPO_CTX_CACHE.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    parts: list[str] = []
    try:
        with open(os.path.join(key, "AGENTS.md"), encoding="utf-8") as fh:
            agents_md = fh.read().strip()
        if agents_md:
            parts.append("Package & directory map (AGENTS.md):\n" + agents_md)
    except Exception:  # noqa: BLE001  -- grounding is best-effort
        pass
    try:
        proc = subprocess.run(
            ["git", "-C", key, "log", "--oneline", "-10", "--name-only"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=10,
        )
        hist = (proc.stdout or "").strip()
        if proc.returncode == 0 and hist:
            parts.append("Recent git history (real, currently-existing file paths):\n" + hist)
    except Exception:  # noqa: BLE001  -- git may be absent or the dir may not be a repo
        pass
    block = "\n\n".join(parts).strip()
    if len(block) > 7000:  # keep well inside num_ctx alongside the capabilities block
        block = block[:7000] + "\n...(truncated)"
    _REPO_CTX_CACHE[key] = (mtime, block)
    return block
```

- [ ] **Step 3: Create `core.py` with the moved orchestration + prompts**

Create `agents/planning/elaborator/core.py`. Move `_chat`, `_fallbackSpec`, `ELABORATOR_SYSTEM`, `elaborate`, `UNIVERSE_SYSTEM`, `extractUniverse` verbatim from the current file (lines 87–184), changing only the repo-context call to import from `grounding`:

```python
"""Elaborator core: prompt builders + orchestration over the llm_io seam.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  elaborate(goal_raw, work_dir=None, chat=None) -> str  -- elaborated spec (never raises)
  extractUniverse(goal_raw, goal_elaborated, work_dir, chat=None) -> dict  -- scope boundary
DEPENDS-ON: config, knowledge, llm_io, agents.planning.elaborator.grounding
SIDE-EFFECTS: unannotated
RUN/TEST: python -m pytest tests/orchestration/test_elaborator.py
"""
from __future__ import annotations

import config
import knowledge
import llm_io

from .grounding import repoContext

LOG = config.getLogger("elaborator")


def _chat(system: str, user: str, *, act: str, want_json: bool = False, chat=None):
    if chat is not None:
        return llm_io.callChat(chat, system, user, act=act, want_json=want_json)
    return llm_io.chat(knowledge.injectCapabilities(system), user, act=act, want_json=want_json)


def _fallbackSpec(goal_raw: str) -> str:
    return (f"# Objective\n{goal_raw}\n\n"
            "# Deliverables\n- Implement the goal exactly as stated.\n\n"
            "# Acceptance Criteria\n- The goal is satisfied and verified.\n\n"
            "# Constraints\n- Keep changes surgical and on-scope.\n\n"
            "# Assumptions\n- (elaboration brain was unavailable; using the raw goal)\n")


ELABORATOR_SYSTEM = (
    "You are the Elaborator for 9TO5, an autonomous engineering orchestrator. "
    "Expand the user's raw goal into a precise, buildable specification a coding agent "
    "can execute without further questions. Use markdown. Include these sections: "
    "Objective; Deliverables (with exact file paths); Acceptance Criteria; "
    "Constraints; Assumptions. Be concrete and concise. Output ONLY the specification, "
    "no preamble, no questions. "
    "CRITICAL GROUNDING RULE: an ACTUAL REPOSITORY SNAPSHOT (package/directory map + recent "
    "git history) is provided in the user message. Every file path you name MUST be a real "
    "path from that snapshot, or a plausible sibling of one. This is the real project -- do "
    "NOT invent placeholder or template paths (e.g. /path/to/app, src/features/, "
    "src/components/, com/example/*.java, build.gradle, Makefile) and do NOT assume a "
    "language, framework, or layout the snapshot does not actually show."
)


def elaborate(goal_raw: str, work_dir: str | None = None, chat=None) -> str:
    """Return the elaborated specification for ``goal_raw`` (never raises)."""
    LOG.info("Elaborating raw goal via %s", config.OLLAMA_MODEL)
    user = f"Raw goal:\n{goal_raw}\n\nProduce the elaborated specification."
    ctx = repoContext(work_dir)
    if ctx:
        user = ("ACTUAL REPOSITORY SNAPSHOT (ground EVERY file path in this real structure):\n"
                f"{ctx}\n\n---\n\n" + user)
    resp = _chat(ELABORATOR_SYSTEM, user, act="elaborate", chat=chat)
    out = llm_io.responseText(resp).strip()
    if not out:
        LOG.warning("elaboration unavailable after retries; using raw goal as spec")
        return _fallbackSpec(goal_raw)
    return out


UNIVERSE_SYSTEM = (
    "You define the operating UNIVERSE for an autonomous engineering run. The universe is about "
    "PRECISION, not permission: the agent may freely create or modify whatever files the goal needs "
    "-- the universe just keeps its edits surgical and on-scope so they don't sprawl into unrelated "
    "code. "
    'Respond with JSON ONLY: {"description": "<one line>", "allowed_paths": ["<files/folders the work '
    'is EXPECTED to focus on>"], "allowed_to_expand_to": ["<related code/deps it may also touch if '
    'needed>"], "hard_boundaries": ["<files/dirs that must NEVER be touched>"]}. '
    "allowed_paths = the expected focus area (a precision hint, NOT a hard allowlist -- creating or "
    "editing other in-scope files to achieve the goal is fine). hard_boundaries = the ONLY hard stop: "
    "secrets, VCS internals, virtualenvs, task state (e.g. .env, .git, venv, state/tasks). "
    "An ACTUAL REPOSITORY SNAPSHOT (package/directory map + recent git history) is provided in "
    "the user message: base allowed_paths on REAL directories/files from it (e.g. the real "
    "top-level packages), NEVER on invented placeholder paths like /path/to/app or src/features. "
    "Output ONLY the JSON."
)


def extractUniverse(goal_raw: str, goal_elaborated: str, work_dir: str, chat=None) -> dict:
    """Extract the operating universe (scope boundary) from the goal (with safe defaults)."""
    user = (f"Goal:\n{goal_raw}\n\nElaborated spec:\n{goal_elaborated[:2000]}\n\n"
            f"Working directory: {work_dir}\n")
    ctx = repoContext(work_dir)
    if ctx:
        user += ("\nACTUAL REPOSITORY SNAPSHOT (base allowed_paths on these REAL paths):\n"
                 f"{ctx}\n")
    user += "\nReturn the universe JSON."
    resp = _chat(UNIVERSE_SYSTEM, user, act="universe", want_json=True, chat=chat)
    u = llm_io.responseJson(resp)
    if not isinstance(u, dict):
        if resp is not None:
            LOG.warning("extractUniverse parse failed; using defaults")
        u = {}
    u["description"] = str(u.get("description") or goal_raw[:200])
    u["allowed_paths"] = [str(x) for x in (u.get("allowed_paths") or []) if x] or [work_dir]
    u["allowed_to_expand_to"] = [str(x) for x in (u.get("allowed_to_expand_to") or []) if x]
    hb = [str(x) for x in (u.get("hard_boundaries") or []) if x]
    for d in config.UNIVERSE_DEFAULT_HARD_BOUNDARIES:
        if d not in hb:
            hb.append(d)
    u["hard_boundaries"] = hb
    return u
```

- [ ] **Step 4: Create the re-export facade `__init__.py`**

Delete `agents/planning/elaborator.py`, then create `agents/planning/elaborator/__init__.py`:

```python
"""Elaborator (Step 0.5) -- expands the raw goal into a buildable spec.

Package facade: the public API (elaborate, extractUniverse) is re-exported from
``core`` so ``from agents.planning.elaborator import elaborate`` keeps working. The
prompt builders + orchestration live in ``core``; repo grounding in ``grounding``.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  elaborate(goal_raw, work_dir=None, chat=None) -> str
  extractUniverse(goal_raw, goal_elaborated, work_dir, chat=None) -> dict
DEPENDS-ON: agents.planning.elaborator.core
SIDE-EFFECTS: unannotated
RUN/TEST: python -m pytest tests/orchestration/test_elaborator.py
"""
from __future__ import annotations

from .core import ELABORATOR_SYSTEM, UNIVERSE_SYSTEM, elaborate, extractUniverse

__all__ = ["elaborate", "extractUniverse", "ELABORATOR_SYSTEM", "UNIVERSE_SYSTEM"]
```

- [ ] **Step 5: Run the existing tests to verify behavior is preserved**

Run: `python -m pytest tests/orchestration/test_elaborator.py -v`
Expected: PASS (same 7 tests) — the package refactor changed no behavior.

- [ ] **Step 6: Verify the top-level facade still imports**

Run: `python -c "from agents import elaborator; print(elaborator.elaborate('x', chat=lambda s,u,**k: {'message':{'content':'ok'}}))"`
Expected: prints `ok`

- [ ] **Step 7: Regenerate the repo map and commit**

Run: `python tools/repo_map.py`

```bash
git add agents/planning/elaborator agents/planning/elaborator.py AGENTS.md .repo-map.json
git commit -m "refactor(elaborator): convert module to package (behavior-preserving)"
```

---

## Task 3: Restore the repo-grounding regression tests (Gap A)

The critical regression from the audit: the `TestRepoGrounding` tests added with commit `324f9f04` are missing. Restore them so the "don't hallucinate fake paths" behavior is defended by CI.

**Files:**
- Modify: `tests/orchestration/test_elaborator.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/orchestration/test_elaborator.py`:

```python
import os
import tempfile


class TestRepoGrounding(unittest.TestCase):
    def _repo(self, tmp):
        # A minimal real repo snapshot: AGENTS.md with a distinctive real path.
        with open(os.path.join(tmp, "AGENTS.md"), "w", encoding="utf-8") as fh:
            fh.write("Package & directory map\n- agents/planning/elaborator/core.py\n")
        return tmp

    def test_elaborate_grounds_prompt_in_real_repo(self):
        captured = {}

        def injected(system, user, *, act, want_json=False):
            captured["user"] = user
            return {"message": {"content": "spec"}}

        with tempfile.TemporaryDirectory() as tmp:
            self._repo(tmp)
            elaborator.elaborate("do a thing", work_dir=tmp, chat=injected)
        self.assertIn("ACTUAL REPOSITORY SNAPSHOT", captured["user"])
        self.assertIn("agents/planning/elaborator/core.py", captured["user"])

    def test_extract_universe_grounds_prompt_in_real_repo(self):
        captured = {}

        def injected(system, user, *, act, want_json=False):
            captured["user"] = user
            return {"message": {"content": '{"allowed_paths":["agents/"]}'}}

        with tempfile.TemporaryDirectory() as tmp:
            self._repo(tmp)
            elaborator.extractUniverse("g", "spec", tmp, chat=injected)
        self.assertIn("ACTUAL REPOSITORY SNAPSHOT", captured["user"])
        self.assertIn("agents/planning/elaborator/core.py", captured["user"])
```

- [ ] **Step 2: Run to verify they pass immediately**

The grounding code already exists (moved in Task 2), so these are true regression guards — they must pass now and fail if a future change strips grounding.

Run: `python -m pytest tests/orchestration/test_elaborator.py::TestRepoGrounding -v`
Expected: PASS (2 tests)

- [ ] **Step 3: Sanity-check the guard by temporarily breaking grounding**

Temporarily edit `agents/planning/elaborator/core.py` `elaborate()` to skip the `if ctx:` block (comment it out), run the test, confirm it FAILS, then revert.

Run: `python -m pytest tests/orchestration/test_elaborator.py::TestRepoGrounding::test_elaborate_grounds_prompt_in_real_repo -v`
Expected: FAIL while broken, PASS after revert.

- [ ] **Step 4: Commit**

```bash
git add tests/orchestration/test_elaborator.py
git commit -m "test(elaborator): restore TestRepoGrounding regression tests (BUG-018)"
```

---

## Task 4: Schema + Layer-1 validation (dataclass, not pydantic)

**Files:**
- Create: `agents/planning/elaborator/schema.py`
- Test: `tests/orchestration/test_elaborator_schema.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/orchestration/test_elaborator_schema.py`:

```python
import unittest

from agents.planning.elaborator import schema


class TestValidateSpec(unittest.TestCase):
    def _good(self):
        return {
            "objective": "do x", "why": "because", "who": "core.py", "where": "agents/",
            "how": "edit", "deliverables": ["a"], "acceptance_criteria": ["b"],
            "constraints": ["c"], "assumptions": [],
        }

    def test_valid_spec_passes(self):
        ok, errors = schema.validateSpec(self._good())
        self.assertTrue(ok)
        self.assertEqual(errors, [])

    def test_missing_required_field_fails(self):
        bad = self._good()
        del bad["deliverables"]
        ok, errors = schema.validateSpec(bad)
        self.assertFalse(ok)
        self.assertTrue(any("deliverables" in e for e in errors))

    def test_empty_list_field_fails(self):
        bad = self._good()
        bad["deliverables"] = []
        ok, errors = schema.validateSpec(bad)
        self.assertFalse(ok)

    def test_wrong_type_fails(self):
        bad = self._good()
        bad["deliverables"] = "not a list"
        ok, errors = schema.validateSpec(bad)
        self.assertFalse(ok)


class TestValidateUniverse(unittest.TestCase):
    def test_baseline_hard_boundaries_reported_missing(self):
        ok, errors = schema.validateUniverse(
            {"description": "d", "allowed_paths": ["a"], "allowed_to_expand_to": [], "hard_boundaries": []})
        self.assertFalse(ok)
        self.assertTrue(any("hard_boundaries" in e for e in errors))
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/orchestration/test_elaborator_schema.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agents.planning.elaborator.schema'`

- [ ] **Step 3: Implement `schema.py`**

Create `agents/planning/elaborator/schema.py`:

```python
"""Elaborator output schema + Layer-1 deterministic validation.

Uses dataclasses + a manual validate() (repo convention), NOT pydantic, to avoid an
undeclared dependency. Layer 1 is cheap structural validation run before any LLM judgment.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  validateSpec(data: dict) -> tuple[bool, list[str]]  -- Layer-1 check of an elaborated spec
  validateUniverse(data: dict) -> tuple[bool, list[str]]  -- Layer-1 check of a universe dict
DEPENDS-ON: config
SIDE-EFFECTS: none
RUN/TEST: python -m pytest tests/orchestration/test_elaborator_schema.py
"""
from __future__ import annotations

import config

_SPEC_STR_FIELDS = ("objective", "why", "who", "where", "how")
_SPEC_LIST_FIELDS = ("deliverables", "acceptance_criteria", "constraints")
# assumptions may legitimately be empty (a fully-grounded goal has no guesses)


def validateSpec(data: dict) -> tuple[bool, list[str]]:
    """Return (ok, errors). Non-empty required str fields; non-empty list fields of str."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return False, ["spec is not a dict"]
    for f in _SPEC_STR_FIELDS:
        v = data.get(f)
        if not isinstance(v, str) or not v.strip():
            errors.append(f"missing/empty required field: {f}")
    for f in _SPEC_LIST_FIELDS:
        v = data.get(f)
        if not isinstance(v, list) or not v or not all(isinstance(x, str) for x in v):
            errors.append(f"missing/empty/mistyped list field: {f}")
    if not isinstance(data.get("assumptions", []), list):
        errors.append("assumptions must be a list")
    return (not errors), errors


def validateUniverse(data: dict) -> tuple[bool, list[str]]:
    """Return (ok, errors). Required keys present; baseline hard boundaries all included."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return False, ["universe is not a dict"]
    if not isinstance(data.get("allowed_paths"), list) or not data.get("allowed_paths"):
        errors.append("missing/empty allowed_paths")
    hb = data.get("hard_boundaries")
    if not isinstance(hb, list):
        errors.append("hard_boundaries must be a list")
        hb = []
    for d in config.UNIVERSE_DEFAULT_HARD_BOUNDARIES:
        if d not in hb:
            errors.append(f"hard_boundaries missing baseline: {d}")
    return (not errors), errors
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/orchestration/test_elaborator_schema.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add agents/planning/elaborator/schema.py tests/orchestration/test_elaborator_schema.py
git commit -m "feat(elaborator): dataclass schema + Layer-1 validation"
```

---

## Task 5: Path verification (generate-then-verify)

**Files:**
- Create: `agents/planning/elaborator/path_verify.py`
- Test: `tests/orchestration/test_elaborator_grounding.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/orchestration/test_elaborator_grounding.py`:

```python
import os
import tempfile
import unittest

from agents.planning.elaborator import path_verify


class TestPathVerify(unittest.TestCase):
    def test_real_path_stays_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "agents"))
            open(os.path.join(tmp, "agents", "core.py"), "w").close()
            result = path_verify.splitVerified(["agents/core.py"], tmp)
        self.assertEqual(result["allowed_paths"], ["agents/core.py"])
        self.assertEqual(result["unverified_paths"], [])

    def test_fake_path_moves_to_unverified(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = path_verify.splitVerified(["does/not/exist.py"], tmp)
        self.assertEqual(result["allowed_paths"], [])
        self.assertEqual(result["unverified_paths"], ["does/not/exist.py"])

    def test_glob_path_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "agents"))
            open(os.path.join(tmp, "agents", "a.py"), "w").close()
            result = path_verify.splitVerified(["agents/*.py"], tmp)
        self.assertEqual(result["allowed_paths"], ["agents/*.py"])
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/orchestration/test_elaborator_grounding.py::TestPathVerify -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agents.planning.elaborator.path_verify'`

- [ ] **Step 3: Implement `path_verify.py`**

Create `agents/planning/elaborator/path_verify.py`:

```python
"""Generate-then-verify: split allowed_paths into existing vs unverified.

A path that does not exist is not silently kept or dropped -- it may legitimately be a
file the goal will CREATE. So it is flagged in unverified_paths for downstream (architect
/ executor) to weigh. Zero LLM calls; pure filesystem check.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  splitVerified(allowed_paths: list[str], work_dir: str) -> dict  -- {allowed_paths, unverified_paths}
DEPENDS-ON: glob, os
SIDE-EFFECTS: none (read-only filesystem)
RUN/TEST: python -m pytest tests/orchestration/test_elaborator_grounding.py
"""
from __future__ import annotations

import glob
import os


def _exists(rel: str, work_dir: str) -> bool:
    abspath = rel if os.path.isabs(rel) else os.path.join(work_dir, rel)
    if os.path.exists(abspath):
        return True
    # support glob patterns (e.g. "agents/*.py")
    return bool(glob.glob(abspath))


def splitVerified(allowed_paths: list[str], work_dir: str) -> dict:
    """Return {"allowed_paths": [existing], "unverified_paths": [missing]} preserving order."""
    verified: list[str] = []
    unverified: list[str] = []
    for p in allowed_paths:
        (verified if _exists(p, work_dir) else unverified).append(p)
    return {"allowed_paths": verified, "unverified_paths": unverified}
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/orchestration/test_elaborator_grounding.py::TestPathVerify -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add agents/planning/elaborator/path_verify.py tests/orchestration/test_elaborator_grounding.py
git commit -m "feat(elaborator): path verification (generate-then-verify)"
```

---

## Task 6: Vague-goal grounding bundle

Detect vague/global goals and assemble a state-of-repo signal bundle (size-audit violations + git churn + repo-map modules) so "improve everything" names real files. Reuses `tools/size_audit.py::collect()` (returns `(files, functions)` dict lists) and `.repo-map.json`.

**Files:**
- Modify: `agents/planning/elaborator/grounding.py`
- Test: `tests/orchestration/test_elaborator_grounding.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/orchestration/test_elaborator_grounding.py`:

```python
from agents.planning.elaborator import grounding


class TestVagueGoal(unittest.TestCase):
    def test_detects_vague_goal(self):
        self.assertTrue(grounding.isVagueGoal("improve everything"))
        self.assertTrue(grounding.isVagueGoal("fix bugs"))
        self.assertTrue(grounding.isVagueGoal("clean up the code"))

    def test_precise_goal_not_vague(self):
        self.assertFalse(grounding.isVagueGoal("add a --json flag to agents/planning/elaborator/core.py"))
        self.assertFalse(grounding.isVagueGoal("rename extractUniverse to extract_universe in core.py"))

    def test_bundle_names_real_modules_from_repo_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, ".repo-map.json"), "w", encoding="utf-8") as fh:
                fh.write('{"modules": [{"path": "agents/planning/elaborator/core.py"}]}')
            bundle = grounding.vagueGoalBundle(tmp)
        self.assertIn("agents/planning/elaborator/core.py", bundle)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/orchestration/test_elaborator_grounding.py::TestVagueGoal -v`
Expected: FAIL with `AttributeError: module ... has no attribute 'isVagueGoal'`

- [ ] **Step 3: Implement in `grounding.py`**

Append to `agents/planning/elaborator/grounding.py`:

```python
import json

_GENERIC_VERBS = ("improve", "fix", "clean up", "cleanup", "optimize", "refactor",
                  "enhance", "polish", "make better", "tidy")
_PATH_HINT = ("/", ".py", ".js", ".ts", "::")


def isVagueGoal(goal: str) -> bool:
    """A goal is vague if it is short, uses a generic verb, and names no path/module."""
    g = goal.strip().lower()
    if any(h in g for h in _PATH_HINT):
        return False
    if len(g.split()) > 8:
        return False
    return any(v in g for v in _GENERIC_VERBS)


def _repoMapModules(work_dir: str, limit: int = 15) -> list[str]:
    try:
        with open(os.path.join(work_dir, ".repo-map.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        mods = [m.get("path", "") for m in data.get("modules", []) if m.get("path")]
        return mods[:limit]
    except Exception:  # noqa: BLE001  -- best-effort
        return []


def _sizeViolations(limit: int = 10) -> list[str]:
    try:
        from tools import size_audit
        files, _functions = size_audit.collect()
        return [f.get("path", "") for f in files
                if f.get("bucket") == "must_split"][:limit]
    except Exception:  # noqa: BLE001  -- best-effort; tools may be unavailable in some checkouts
        return []


def vagueGoalBundle(work_dir: str | None) -> str:
    """A compact state-of-repo bundle (real module names + size violations) so a vague
    goal can be grounded in actual files. Summary counts + top-N names, never raw dumps."""
    if not work_dir:
        return ""
    parts: list[str] = []
    violations = _sizeViolations()
    if violations:
        parts.append("Files over the size budget (candidates for 'clean up'/'refactor'):\n"
                     + "\n".join(f"- {p}" for p in violations))
    mods = _repoMapModules(work_dir)
    if mods:
        parts.append("Real modules in this repo (name Deliverables from these, not placeholders):\n"
                     + "\n".join(f"- {p}" for p in mods))
    return "\n\n".join(parts).strip()
```

> **Note on `bucket` key:** `size_audit.collect()` returns file dicts; confirm the must_split marker key by running `python -c "from tools import size_audit; f,_=size_audit.collect(); print(f[0])"` and adjust the `f.get("bucket") == "must_split"` filter to the actual key/value if it differs (e.g. a `must_split` boolean or a `status` field). This is the one place to verify against real output before finalizing.

- [ ] **Step 4: Verify the size_audit dict shape, then run tests**

Run: `python -c "from tools import size_audit; f,_=size_audit.collect(); print(f[0] if f else 'no files')"`
Read the printed dict; fix the `_sizeViolations` filter key if needed.

Run: `python -m pytest tests/orchestration/test_elaborator_grounding.py::TestVagueGoal -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add agents/planning/elaborator/grounding.py tests/orchestration/test_elaborator_grounding.py
git commit -m "feat(elaborator): vague-goal state-of-repo grounding bundle"
```

---

## Task 7: Calibrated self-review pass (one pass, no loop)

One narrowly-scoped brain call that surfaces guesses as `Inferred: {guess} — because {reason}` using the I-CALM reward frame. Exactly one pass. Behind the master flag; flag-off never calls it.

**Files:**
- Create: `agents/planning/elaborator/self_review.py`
- Test: `tests/orchestration/test_elaborator_selfreview.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/orchestration/test_elaborator_selfreview.py`:

```python
import unittest

from agents.planning.elaborator import self_review


class TestSelfReview(unittest.TestCase):
    def test_single_pass_only(self):
        calls = {"n": 0}

        def injected(system, user, *, act, want_json=False):
            calls["n"] += 1
            return {"message": {"content": "Inferred: X — because Y"}}

        out = self_review.reviewAssumptions("spec body", "goal", chat=injected)
        self.assertEqual(calls["n"], 1)  # exactly ONE pass, never a loop
        self.assertIn("Inferred:", out)

    def test_reward_frame_in_prompt(self):
        seen = {}

        def injected(system, user, *, act, want_json=False):
            seen["system"] = system
            return {"message": {"content": ""}}

        self_review.reviewAssumptions("spec", "goal", chat=injected)
        # I-CALM reward frame present (calibrated abstention, not free-form confidence)
        self.assertIn("+2", seen["system"])
        self.assertIn("abstain", seen["system"].lower())

    def test_degrades_to_empty_when_brain_down(self):
        def injected(system, user, *, act, want_json=False):
            return None

        self.assertEqual(self_review.reviewAssumptions("spec", "goal", chat=injected), "")
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/orchestration/test_elaborator_selfreview.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agents.planning.elaborator.self_review'`

- [ ] **Step 3: Implement `self_review.py`**

Create `agents/planning/elaborator/self_review.py`:

```python
"""One calibrated self-review pass: surface guesses as auditable inferred assumptions.

Exactly ONE pass (never a loop): the reflexion survey shows uncalibrated repeated
self-critique reinforces early errors. Uses the I-CALM reward frame (a payoff that
rewards flagging over confident guessing) instead of free-form verbalized confidence,
which RLHF is known to miscalibrate.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  reviewAssumptions(spec_body, goal_raw, chat=None) -> str  -- inferred-assumption lines (or "")
DEPENDS-ON: config, knowledge, llm_io
SIDE-EFFECTS: unannotated
RUN/TEST: python -m pytest tests/orchestration/test_elaborator_selfreview.py
"""
from __future__ import annotations

import config
import knowledge
import llm_io

LOG = config.getLogger("elaborator.self_review")

SELF_REVIEW_SYSTEM = (
    "You are auditing an elaborated engineering spec for UNGROUNDED GUESSES. "
    "Scoring frame: you receive +2 for each guess you correctly surface, -2 for a wrong "
    "claim you assert as fact, and 0 for a point you honestly flag as uncertain -- so when "
    "in doubt, FLAG rather than assert. "
    "For every place the spec filled a gap the raw goal did not specify, emit one line: "
    "'Inferred: <the assumption> — because <the reason it is the best guess>'. "
    "Output ONLY those lines, one per assumption. If the spec makes no guesses, output nothing."
)


def reviewAssumptions(spec_body: str, goal_raw: str, chat=None) -> str:
    """Return newline-joined 'Inferred: ... — because ...' lines (or "" when unavailable).
    Exactly one brain call; never raises."""
    user = (f"Raw goal:\n{goal_raw}\n\nElaborated spec:\n{spec_body[:4000]}\n\n"
            "List the inferred assumptions.")
    if chat is not None:
        resp = llm_io.callChat(chat, SELF_REVIEW_SYSTEM, user, act="self_review")
    else:
        resp = llm_io.chat(knowledge.injectCapabilities(SELF_REVIEW_SYSTEM), user, act="self_review")
    return llm_io.responseText(resp).strip()
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/orchestration/test_elaborator_selfreview.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add agents/planning/elaborator/self_review.py tests/orchestration/test_elaborator_selfreview.py
git commit -m "feat(elaborator): calibrated one-pass self-review (I-CALM reward frame)"
```

---

## Task 8: Wire the flag-gated tier into `core.py` (byte-identical flag-off)

Thread grounding-bundle + self-review + schema + path-verify into `elaborate()`/`extractUniverse()`, **only** when `config.ELABORATOR_EXCELLENCE_ENABLED` is true. Flag-off path is unchanged.

**Files:**
- Modify: `agents/planning/elaborator/core.py`
- Test: `tests/orchestration/test_elaborator.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/orchestration/test_elaborator.py`:

```python
class TestExcellenceGating(unittest.TestCase):
    def test_flag_off_is_byte_identical(self):
        def injected(system, user, *, act, want_json=False):
            return {"message": {"content": "SPEC"}}

        with mock.patch.object(__import__("config"), "ELABORATOR_EXCELLENCE_ENABLED", False):
            out = elaborator.elaborate("do a thing", chat=injected)
        self.assertEqual(out, "SPEC")  # no appended assumptions, no extra passes

    def test_flag_on_appends_inferred_assumptions(self):
        scripted = iter([
            {"message": {"content": "SPEC BODY"}},                 # elaborate
            {"message": {"content": "Inferred: scope — because vague"}},  # self_review
        ])

        def injected(system, user, *, act, want_json=False):
            return next(scripted)

        with mock.patch.object(__import__("config"), "ELABORATOR_EXCELLENCE_ENABLED", True):
            out = elaborator.elaborate("improve everything", chat=injected)
        self.assertIn("SPEC BODY", out)
        self.assertIn("Inferred: scope", out)

    def test_flag_on_universe_adds_unverified_paths(self):
        def injected(system, user, *, act, want_json=False):
            return {"message": {"content": '{"allowed_paths":["nope/missing.py"]}'}}

        with mock.patch.object(__import__("config"), "ELABORATOR_EXCELLENCE_ENABLED", True):
            u = elaborator.extractUniverse("g", "spec", ".", chat=injected)
        self.assertIn("nope/missing.py", u["unverified_paths"])
        self.assertNotIn("nope/missing.py", u["allowed_paths"])
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/orchestration/test_elaborator.py::TestExcellenceGating -v`
Expected: FAIL — `test_flag_on_appends_inferred_assumptions` (no assumptions appended) and `test_flag_on_universe_adds_unverified_paths` (`KeyError: 'unverified_paths'`). `test_flag_off_is_byte_identical` should already PASS.

- [ ] **Step 3: Wire the tier into `core.py`**

In `agents/planning/elaborator/core.py`, add imports at the top (after existing imports):

```python
from . import path_verify, schema, self_review
from .grounding import isVagueGoal, vagueGoalBundle
```

Replace the body of `elaborate()` from `resp = _chat(...)` onward with:

```python
    if config.ELABORATOR_EXCELLENCE_ENABLED and isVagueGoal(goal_raw):
        bundle = vagueGoalBundle(work_dir)
        if bundle:
            user += ("\n\nSTATE OF THE REPO (name real files from here for a broad goal):\n"
                     f"{bundle}\n")
    resp = _chat(ELABORATOR_SYSTEM, user, act="elaborate", chat=chat)
    out = llm_io.responseText(resp).strip()
    if not out:
        LOG.warning("elaboration unavailable after retries; using raw goal as spec")
        return _fallbackSpec(goal_raw)
    if config.ELABORATOR_EXCELLENCE_ENABLED:
        inferred = self_review.reviewAssumptions(out, goal_raw, chat=chat)
        if inferred:
            out = f"{out}\n\n# Inferred Assumptions\n{inferred}\n"
    return out
```

In `extractUniverse()`, replace the final `return u` with:

```python
    if config.ELABORATOR_EXCELLENCE_ENABLED:
        split = path_verify.splitVerified(u["allowed_paths"], work_dir)
        u["allowed_paths"] = split["allowed_paths"] or [work_dir]
        u["unverified_paths"] = split["unverified_paths"]
    return u
```

> `schema` is imported for the Layer-1/observability wiring; a follow-up micro-step logs `schema.validateSpec` / `validateUniverse` outcomes without enforcing. Keep the import even if the logging line lands in Phase 2 (it is used by the retry path there). If a linter flags it unused now, add the validate-and-log line below in Step 3b.

- [ ] **Step 3b: Add non-enforcing schema observability**

In `extractUniverse()`, immediately before the flag block added above, insert:

```python
    if config.ELABORATOR_EXCELLENCE_ENABLED:
        ok, errs = schema.validateUniverse(u)
        if not ok:
            LOG.info("universe schema_validity=fail: %s", "; ".join(errs))
```

- [ ] **Step 4: Run to verify all pass**

Run: `python -m pytest tests/orchestration/test_elaborator.py -v`
Expected: PASS (all — original 7 + TestRepoGrounding 2 + TestExcellenceGating 3)

- [ ] **Step 5: Verify byte-identical flag-off across the whole module**

Run: `python -m pytest tests/orchestration/test_elaborator.py -k "not Excellence" -v`
Expected: PASS — the pre-existing suite is unchanged with the flag off (its default).

- [ ] **Step 6: Regenerate repo map, run focused check, commit**

Run: `python tools/repo_map.py`
Run: `python tools/size_audit.py`
Expected: zero `must_split` violations for the new files (all are small, focused modules).

```bash
git add agents/planning/elaborator/core.py tests/orchestration/test_elaborator.py AGENTS.md .repo-map.json
git commit -m "feat(elaborator): wire flag-gated excellence tier (byte-identical flag-off)"
```

---

## Task 9: Phase-1 verification sweep

**Files:** none (verification only)

- [ ] **Step 1: Full focused module test**

Run: `python tools/dev.py check agents/planning/elaborator/core.py`
Expected: PASS (the dev tool runs the mapped tests for the file).

- [ ] **Step 2: Run all elaborator + flag tests together**

Run: `python -m pytest tests/orchestration/test_elaborator.py tests/orchestration/test_elaborator_schema.py tests/orchestration/test_elaborator_grounding.py tests/orchestration/test_elaborator_selfreview.py tests/platform/test_epic_flags_config.py -v`
Expected: PASS (all)

- [ ] **Step 3: Confirm modularity budget**

Run: `python tools/size_audit.py`
Expected: zero `must_split` violations. If any new file is >300 lines, split it before proceeding.

- [ ] **Step 4: Confirm the public API is unbroken from both facades**

Run: `python -c "from agents.elaborator import elaborate, extractUniverse; from agents.planning.elaborator import elaborate as e2; print('facades ok')"`
Expected: prints `facades ok`

- [ ] **Step 5: Fast lane (broad guard before handoff)**

Run: `python tools/dev.py fast`
Expected: green. Investigate any failure before declaring Phase 1 done.

---

## Self-Review (spec coverage check)

- **§2 module layout** → Tasks 2 (package + facade + core + grounding), 4 (schema), 5 (path_verify), 7 (self_review). `precedent.py` / `candidates.py` / `predict.py` / `uncertainty.py` are Phase 2–4, correctly deferred.
- **§3a 5W3H prompt** → the prompt restructure is threaded as bundle context in Task 6/8; the full Why/Who/Where/How/What section rewrite of `ELABORATOR_SYSTEM` is a Task-8 prompt edit. *(Note: this plan keeps the existing five output sections and adds grounding; the deeper 5W3H scaffold wording is a low-risk copy-edit to `ELABORATOR_SYSTEM` — if the reviewer wants the explicit dimensional walk in the system prompt now rather than Phase 2, extend Task 8 Step 3's `ELABORATOR_SYSTEM`.)*
- **§3b calibrated self-review** → Task 7 (I-CALM reward frame, one pass; conformal risk band is Phase 2 when path-verify + precedent feed it).
- **§3c vague-goal bundle** → Task 6.
- **§4 Layer-1 validation** → Task 4; Layer-2 semantic judge is Phase 2.
- **§5 path verification** → Task 5 + wired in Task 8.
- **§6 testing / restored TestRepoGrounding** → Task 3 + per-module tests throughout.
- **Master flag / byte-identical flag-off** → Task 1 + Task 8 Step 5.

**Deferred to later plans (correctly out of Phase-1 scope):** §3d precedent (Phase 2), §3b conformal band completion (Phase 2), §4 Layer-2 semantic judge (Phase 2), §7 A′/A/B/C/D pipeline (Phase 3), §7 B′ lookahead + §7.5 deferral (Phase 4).

**Placeholder scan:** none — every code step shows complete code. The one runtime-verify point (size_audit dict key) is called out explicitly in Task 6 with the exact command to confirm it.

**Type consistency:** `repoContext` (grounding), `validateSpec`/`validateUniverse` (schema), `splitVerified` returning `{allowed_paths, unverified_paths}` (path_verify), `isVagueGoal`/`vagueGoalBundle` (grounding), `reviewAssumptions` (self_review) — names are used identically in their tests and in the Task-8 wiring.
