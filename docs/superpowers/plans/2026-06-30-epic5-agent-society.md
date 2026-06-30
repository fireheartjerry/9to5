# Epic 5 — Agent Society / Workforce Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn 9TO5's star topology (one Ollama brain → one Claude executor) into a 9TO5-owned multi-agent workforce: a deterministic Python coordinator decomposes a goal, assigns each ready subtask to a specialized role (planner/coder/tester/reviewer/researcher), runs the roles concurrently on a shared append-only blackboard, and resolves contested results by bounded structured debate — all behind `SOCIETY_ENABLED=False`, with the existing star path byte-identical when off.

**Architecture:** One new product package `society/` at repo root (peer of `agents/`, `workflows/`) holds five small units — `blackboard.py` (durable JSONL coordination surface), `roles.py` (role registry + capability router), `worker.py` (role-scoped wrapper over the *existing* `agents/executor.py::runClaude`), `inbox.py` (message helpers), `debate.py` (speaker selection + arbiter), `coordinator.py` (decompose → assign → parallel-batch → collect → debate). Cross-module wire types are TypedDicts in `platform_core/core/contracts.py`. The coordinator mirrors the existing `run_loop_mixin.py::_handleParallelBatch` ThreadPoolExecutor shape (LOCKED concurrency boundary: **threads + per-worker git worktree filesystem isolation**, NOT process-per-worker). Task JSON stays the single source of truth for subtask status/claim; the blackboard only holds coordination artifacts; ControlBus owns control; the verifier still gates.

**Tech Stack:** Python 3.11+, stdlib only (`concurrent.futures.ThreadPoolExecutor`, `threading.Lock`, `json`, `dataclasses`, `uuid`, `time`, `pathlib`; best-effort cross-process file lock via `msvcrt`/`fcntl`). Tests are **pytest only** (conftest sandbox isolates `STATE_DIR`/DBs and blocks real Ollama/Discord/Gemini — never bare `unittest`, the live `.env` has real creds). Reuses `agents/executor.py::runClaude`, `agents/second_brain.py::consult`, `agents/playbook.py`, `state/task_schema.py::TaskState`, `notifications/event_bus.py`.

---

## Prerequisites & cross-epic seams

Epic 5 is **transformative-first but co-designed with Epic 1 (Durable Execution — worktrees + file-disjointness)**. It must ship and be fully testable *without* Epic 1 landing first. To achieve that, every Epic-1 interface is consumed through a **named seam with a standalone fallback**:

| Epic-1 interface consumed | Seam in this plan | Standalone fallback (no Epic 1) |
|---|---|---|
| Per-worker git **worktree** cwd (`EnterWorktree`) | `WorkerAgent(work_dir=...)` — coordinator passes a per-worker dir | `work_dir = self._work_dir` (the shared tree); workers run **serially** in shared-tree advisory mode |
| **File-disjointness CAS** scheduler (`bounties.go`/`accept.go`) | `Coordinator.selectDisjointBatch(ready, max_workers, file_sets_fn=None)` — Task 9 ships a **STUB seam** (`file_sets_fn=None` ⇒ deps-only batch, today's behavior) | deps-only `_readySet` filtering, exactly like `_handleParallelBatch` today |
| **Trajectory-trace span ids** (steal #7) | `BlackboardEntry.span_id` field (nullable) | left `None`; blackboard still fully durable/queryable |
| `_remediationTreeShared` flip to enable remediation under parallelism | Task 13 leaves it **unchanged** and adds a flag-gated co-design note | remediation stays disabled under parallelism, as today |

**Minimal stub/seam task explicitly marked:** Task 9 Step 0 ships `selectDisjointBatch` with the `file_sets_fn=None` deps-only path — this is the Epic-1 CAS seam stub; when Epic 1 lands, pass its real `file_sets_fn` and no other Epic-5 code changes.

**Ship-dark:** all wiring is gated on `config.SOCIETY_ENABLED` (default `False`). With the flag off, `runExecutionLoop` is byte-identical to today (Task 11 golden test). Standalone fallback = shared-tree advisory mode (coordination + roles + debate surfaces live; workers serial; remediation unchanged).

---

## Source-of-truth ownership (do NOT violate)

- **Task JSON** (`state/task_schema.py::TaskState`) owns subtask **status + claim**. The CAS claim is on task JSON, never the blackboard.
- **Blackboard** (`society/blackboard.py`) owns **coordination artifacts only** (facts, results, questions, proposals, votes, handoffs). It references `subtask_id`; it never stores status.
- **ControlBus** (`platform_core/runtime/control.py`) owns abort/pause/gates — unchanged.
- **Verifier** (`agents/verifier.py`) gates every subtask — unchanged. Debate verdicts are advisory inputs, never the gate.
- **event_bus** (`notifications/event_bus.py`) stays *ephemeral presentation*; the blackboard is the *durable* substrate. The coordinator mirrors each append to the bus; no second state machine.

---

## File structure

### New files (`society/` package)

| File | Responsibility |
|---|---|
| `society/__init__.py` | Thin facade re-exporting `Blackboard`, `BlackboardEntry`, `RoleSpec`, `classifyRole`, `ROLES`, `WorkerAgent`, `Coordinator`, `runDebate`. |
| `society/blackboard.py` | `BlackboardEntry` dataclass + `Blackboard`: append-only JSONL, threadlock + best-effort cross-process file lock, role-filtered `read`/`inbox`, malformed-line tolerant, optional `on_append` hook. |
| `society/inbox.py` | `makeEntry(...)` constructor + `inboxFilter(entries, role, since_ns)` cursor logic (metagpt `_observe` rule). |
| `society/roles.py` | `RoleSpec` dataclass, `ROLES` registry (planner/coder/tester/reviewer/researcher), `classifyRole(subtask, hint)` capability router (reuses `playbook.classifyProfile`). |
| `society/worker.py` | `WorkerAgent`: CAS-claim on task JSON → role-scoped `InvocationSpec` → injectable `run_fn` (default `runClaude`) in `work_dir` → post `result` to blackboard. |
| `society/debate.py` | `selectNextSpeaker`, `runDebate`, `DebateVerdict`, diff-hash oscillation ring; arbiter via `second_brain.consult` (injectable). |
| `society/coordinator.py` | `Coordinator`: `postFacts`, `selectDisjointBatch` (Epic-1 seam), `_handleSocietyBatch`, `collect`, `detectContested`. |

### Modified files (narrow, ownership-preserving)

| File | Change |
|---|---|
| `platform_core/app_config/llm.py` | Add `SOCIETY_ENABLED`, `SOCIETY_MAX_WORKERS`, `SOCIETY_DEBATE_MAX_ROUNDS`, `SOCIETY_TOKEN_BUDGET_USD`, `SOCIETY_ROLE_MODELS`. |
| `platform_core/app_config/paths.py` | Add `BLACKBOARD_DIR`. |
| `platform_core/core/contracts.py` | Add `BlackboardEntry`, `WorkerMessage`, `DebateVerdict` TypedDicts. |
| `platform_core/orchestration/run_loop_mixin.py` | `_societyGate(ready)` helper + route the parallel branch through `_handleSocietyBatch` when gated; star + `_handleParallelBatch` untouched when off. |
| `platform_core/orchestration/review_mixin.py` | Add flag-gated co-design comment in `_remediationTreeShared` (no behavior change). |
| `agents/executor_env.py` | Guard comment on `_composeWorkflowPrompt` (no behavior change). |
| `docs/ARCHITECTURE.md`, `AGENTS.md` | Doc + regenerated repo map after modules land. |

### New tests

`tests/test_society_blackboard.py`, `tests/test_society_inbox.py`, `tests/test_society_roles.py`, `tests/test_society_worker.py`, `tests/test_society_debate.py`, `tests/test_society_coordinator.py`, `tests/test_society_off_invariance.py`.

---

## Task 1: Config knobs + blackboard dir

**Files:**
- Modify: `platform_core/app_config/llm.py` (after line 246, `DEFAULT_PARALLELISM` block)
- Modify: `platform_core/app_config/paths.py` (after line 73, `CONTROL_DIR`)
- Test: `tests/test_society_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_society_config.py
"""Epic 5 config knobs exist with safe OFF defaults and re-export through config."""
import config


def test_society_disabled_by_default():
    assert config.SOCIETY_ENABLED is False


def test_society_numeric_defaults():
    assert config.SOCIETY_MAX_WORKERS >= 1
    assert config.SOCIETY_DEBATE_MAX_ROUNDS >= 1
    assert config.SOCIETY_TOKEN_BUDGET_USD > 0


def test_society_role_models_map_to_effort_keys():
    # Each role routes to an effort key the executor already understands.
    for role, effort in config.SOCIETY_ROLE_MODELS.items():
        assert effort in config.MODEL_BY_EFFORT


def test_blackboard_dir_under_state():
    assert config.BLACKBOARD_DIR.name == "blackboard"
    assert config.BLACKBOARD_DIR.parent.name == "state"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_society_config.py -v`
Expected: FAIL with `AttributeError: module 'config' has no attribute 'SOCIETY_ENABLED'`

- [ ] **Step 3: Add the knobs**

In `platform_core/app_config/llm.py`, immediately after the `DEFAULT_PARALLELISM` line (line 246):

```python

# --- Agent Society / Workforce (Epic 5) — OFF by default -----------------
# A 9to5-owned multi-agent workforce: coordinator + specialized role workers on a
# shared blackboard. When False the existing star/parallel path is unchanged.
SOCIETY_ENABLED: bool = _envBool("SOCIETY_ENABLED", False)
# Hard cap on concurrent role workers. MUST stay <= run parallelism (anti-runaway).
SOCIETY_MAX_WORKERS: int = _envInt("SOCIETY_MAX_WORKERS", 3)
# Max bounded debate rounds before convergence is forced (anti-livelock).
SOCIETY_DEBATE_MAX_ROUNDS: int = _envInt("SOCIETY_DEBATE_MAX_ROUNDS", 3)
# Per-run USD budget governor for the workforce; on breach the coordinator stops
# spawning new workers and finalizes with what landed.
SOCIETY_TOKEN_BUDGET_USD: float = _envFloat("SOCIETY_TOKEN_BUDGET_USD", 5.0)
# role -> effort_level key (resolved through MODEL_BY_EFFORT; narrows, never bypasses).
SOCIETY_ROLE_MODELS: dict[str, str] = {
    "researcher": os.getenv("SOCIETY_MODEL_RESEARCHER", "low"),
    "coder":      os.getenv("SOCIETY_MODEL_CODER", "high"),
    "tester":     os.getenv("SOCIETY_MODEL_TESTER", "default"),
    "reviewer":   os.getenv("SOCIETY_MODEL_REVIEWER", "high"),
    "planner":    os.getenv("SOCIETY_MODEL_PLANNER", "default"),
}
```

In `platform_core/app_config/paths.py`, immediately after the `CONTROL_DIR` line (line 73):

```python
# --- Agent Society / Workforce (Epic 5) blackboard -----------------------
BLACKBOARD_DIR: Path = PROJECT_ROOT / "state" / "blackboard"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_society_config.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add platform_core/app_config/llm.py platform_core/app_config/paths.py tests/test_society_config.py
git commit -m "feat(society): add Epic-5 config knobs + blackboard dir (OFF by default)"
```

---

## Task 2: Cross-module contracts (TypedDicts)

**Files:**
- Modify: `platform_core/core/contracts.py` (add after `AgentDecision`, end of file ~line 249)
- Test: `tests/test_society_contracts.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_society_contracts.py
"""Epic 5 wire-type TypedDicts are importable and structurally usable."""
from platform_core.core.contracts import BlackboardEntry, WorkerMessage, DebateVerdict


def test_blackboard_entry_shape():
    e: BlackboardEntry = {
        "entry_id": "bb-1", "key": "result:st-007", "kind": "result",
        "author": "coder", "to": "coordinator", "subtask_id": "st-007",
        "value": {"ok": True}, "refs": [], "span_id": None, "ts_ns": 1,
    }
    assert e["kind"] == "result"


def test_worker_message_shape():
    m: WorkerMessage = {"role": "coder", "subtask_id": "st-007",
                        "kind": "result", "ok": True, "summary": "done",
                        "refs": [], "value": {}}
    assert m["ok"] is True


def test_debate_verdict_shape():
    v: DebateVerdict = {"resolved": True, "winner": "coder",
                        "reason": "consensus", "rounds": 1,
                        "stopped_reason": "consensus"}
    assert v["stopped_reason"] == "consensus"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_society_contracts.py -v`
Expected: FAIL with `ImportError: cannot import name 'BlackboardEntry'`

- [ ] **Step 3: Add the TypedDicts**

Append to `platform_core/core/contracts.py` (after the `AgentDecision` dataclass, end of file):

```python


# ===========================================================================
# Agent Society / Workforce (Epic 5) cross-module wire types.
# BlackboardEntry mirrors the society/blackboard.py dataclass exactly (kept in
# sync by hand). Role specs stay local to society/roles.py.
# ===========================================================================


class BlackboardEntry(TypedDict, total=False):
    """One append-only coordination artifact on the run blackboard."""
    entry_id: str
    key: str                         # logical slot, e.g. "facts" | "result:st-007"
    kind: str                        # facts|result|question|proposal|vote|handoff|claim
    author: str                      # role name or "coordinator"
    to: str                          # "all" | "coordinator" | "<role>"
    subtask_id: Optional[str]
    value: dict
    refs: list[str]                  # ids of entries this responds to (debate threading)
    span_id: Optional[str]           # Epic 1 trajectory-trace linkage (nullable seam)
    ts_ns: int


class WorkerMessage(TypedDict, total=False):
    """The structured result a WorkerAgent.run() returns and posts to the board."""
    role: str
    subtask_id: str
    kind: str                        # result | question | proposal | claim
    ok: bool
    summary: str
    refs: list[str]
    value: dict


class DebateVerdict(TypedDict, total=False):
    """Advisory outcome of a structured debate. The verifier still gates."""
    resolved: bool
    winner: Optional[str]            # role name of the prevailing proposal, or None
    reason: str
    rounds: int
    stopped_reason: str              # "consensus" | "round_cap" | "oscillation"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_society_contracts.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add platform_core/core/contracts.py tests/test_society_contracts.py
git commit -m "feat(society): add BlackboardEntry/WorkerMessage/DebateVerdict contracts"
```

---

## Task 3: Blackboard — append-only JSONL with attribution

**Files:**
- Create: `society/__init__.py`
- Create: `society/blackboard.py`
- Test: `tests/test_society_blackboard.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_society_blackboard.py
"""Append-only JSONL blackboard: ordering, attribution, malformed tolerance."""
from society.blackboard import Blackboard, BlackboardEntry


def _entry(key, kind, author, to, value):
    return BlackboardEntry(key=key, kind=kind, author=author, to=to,
                           subtask_id=None, value=value, refs=[], span_id=None)


def test_append_then_read_all_in_order(tmp_path):
    bb = Blackboard(tmp_path / "t.jsonl")
    id1 = bb.append(_entry("facts", "facts", "coordinator", "all", {"n": 1}))
    id2 = bb.append(_entry("result:st-1", "result", "coder", "coordinator", {"n": 2}))
    rows = bb.readAll()
    assert [r["entry_id"] for r in rows] == [id1, id2]
    assert rows[0]["author"] == "coordinator" and rows[1]["author"] == "coder"
    assert rows[0]["ts_ns"] <= rows[1]["ts_ns"]


def test_malformed_line_is_skipped(tmp_path):
    p = tmp_path / "t.jsonl"
    bb = Blackboard(p)
    bb.append(_entry("facts", "facts", "coordinator", "all", {"n": 1}))
    with open(p, "a", encoding="utf-8") as fh:
        fh.write("{ this is not json\n")
    bb.append(_entry("result:st-1", "result", "coder", "coordinator", {"n": 2}))
    rows = bb.readAll()
    assert len(rows) == 2  # the garbage line is tolerated, not fatal


def test_on_append_hook_fires(tmp_path):
    seen = []
    bb = Blackboard(tmp_path / "t.jsonl", on_append=seen.append)
    bb.append(_entry("facts", "facts", "coordinator", "all", {"n": 1}))
    assert seen and seen[0]["kind"] == "facts"


def test_for_task_uses_blackboard_dir(tmp_path):
    bb = Blackboard.forTask("abc-123", base_dir=tmp_path)
    bb.append(_entry("facts", "facts", "coordinator", "all", {}))
    assert (tmp_path / "abc-123.jsonl").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_society_blackboard.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'society'`

- [ ] **Step 3: Write minimal implementation**

Create `society/__init__.py`:

```python
"""society -- 9to5-owned multi-agent workforce (Epic 5).

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  Blackboard  -- Append-only JSONL coordination surface.
  BlackboardEntry  -- One coordination artifact (dataclass).
DEPENDS-ON: society.blackboard
SIDE-EFFECTS: writes state/blackboard/<task_id>.jsonl
RUN/TEST: python -m pytest tests/test_society_blackboard.py
"""
from __future__ import annotations

from society.blackboard import Blackboard, BlackboardEntry

__all__ = ["Blackboard", "BlackboardEntry"]
```

Create `society/blackboard.py`:

```python
"""Append-only, per-run JSONL blackboard -- the workforce coordination surface.

Models bernstein core/communication/whiteboard.py: who-wrote-what attribution, a
threadlock + best-effort cross-process file lock for atomic appends, and malformed-
line tolerance. Holds ONLY coordination artifacts (facts/result/question/proposal/
vote/handoff/claim); subtask status + the CAS claim stay in task JSON.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  BlackboardEntry(key, kind, author, to, value, ...) -- One coordination artifact.
  Blackboard(path, on_append=None) -- Append-only JSONL store with role-filtered reads.
DEPENDS-ON: config
SIDE-EFFECTS: writes <path>.jsonl
RUN/TEST: python -m pytest tests/test_society_blackboard.py
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional, Union

import config

LOG = config.getLogger("society.blackboard")

_VALID_KINDS = ("facts", "result", "question", "proposal", "vote", "handoff", "claim")


@dataclass
class BlackboardEntry:
    """One append-only coordination artifact. Mirrors contracts.BlackboardEntry."""
    key: str
    kind: str
    author: str
    to: str = "all"
    subtask_id: Optional[str] = None
    value: dict = field(default_factory=dict)
    refs: list = field(default_factory=list)
    span_id: Optional[str] = None
    entry_id: str = ""
    ts_ns: int = 0


class Blackboard:
    """Append-only JSONL coordination store. Thread-safe; cross-process best-effort."""

    def __init__(self, path: Union[str, Path],
                 on_append: Optional[Callable[[dict], None]] = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._on_append = on_append

    @classmethod
    def forTask(cls, task_id: str, *, base_dir: Optional[Union[str, Path]] = None,
                on_append: Optional[Callable[[dict], None]] = None) -> "Blackboard":
        base = Path(base_dir) if base_dir is not None else config.BLACKBOARD_DIR
        return cls(base / f"{task_id}.jsonl", on_append=on_append)

    def append(self, entry: Union[BlackboardEntry, dict]) -> str:
        """Append one entry atomically; stamp entry_id + ts_ns. Returns the entry_id."""
        rec = asdict(entry) if isinstance(entry, BlackboardEntry) else dict(entry)
        if not rec.get("entry_id"):
            rec["entry_id"] = f"bb-{uuid.uuid4().hex[:12]}"
        rec["ts_ns"] = time.time_ns()
        line = json.dumps(rec, ensure_ascii=False, default=str)
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as fh:
                self._osLock(fh)
                try:
                    fh.write(line + "\n")
                    fh.flush()
                finally:
                    self._osUnlock(fh)
        if self._on_append is not None:
            try:
                self._on_append(rec)
            except Exception:  # noqa: BLE001 -- the mirror must never break coordination
                LOG.warning("blackboard on_append hook failed", exc_info=True)
        return rec["entry_id"]

    def readAll(self) -> list:
        """Return every well-formed entry in append order; skip malformed lines."""
        if not self.path.exists():
            return []
        out = []
        with open(self.path, "r", encoding="utf-8") as fh:
            for ln in fh:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    out.append(json.loads(ln))
                except json.JSONDecodeError:
                    LOG.warning("skipping malformed blackboard line in %s", self.path)
        return out

    def read(self, *, role: str, since_ns: int = 0, kind: Optional[str] = None) -> list:
        """Role-filtered view: entries addressed to {role,'all'} (or authored by role)."""
        out = []
        for r in self.readAll():
            if r.get("ts_ns", 0) <= since_ns:
                continue
            if kind is not None and r.get("kind") != kind:
                continue
            if r.get("to") in (role, "all") or r.get("author") == role:
                out.append(r)
        return out

    def inbox(self, role: str, since_ns: int = 0) -> list:
        """Entries addressed to this role since its last read cursor (metagpt _observe)."""
        return [r for r in self.readAll()
                if r.get("ts_ns", 0) > since_ns and r.get("to") in (role, "all")]

    # ---- best-effort cross-process file lock (Windows msvcrt / POSIX fcntl) ----
    @staticmethod
    def _osLock(fh) -> None:
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        except Exception:  # noqa: BLE001 -- threadlock already serializes in-process
            pass

    @staticmethod
    def _osUnlock(fh) -> None:
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except Exception:  # noqa: BLE001
            pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_society_blackboard.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add society/__init__.py society/blackboard.py tests/test_society_blackboard.py
git commit -m "feat(society): append-only JSONL blackboard with attribution + on_append mirror"
```

---

## Task 4: Blackboard concurrency — N-thread append integrity

**Files:**
- Modify: `tests/test_society_blackboard.py` (add concurrency test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_society_blackboard.py`:

```python
import threading as _threading

from society.blackboard import Blackboard as _BB, BlackboardEntry as _BE


def test_concurrent_append_no_lost_or_torn_lines(tmp_path):
    bb = _BB(tmp_path / "c.jsonl")
    n_threads, per = 8, 25

    def worker(wid):
        for i in range(per):
            bb.append(_BE(key=f"k{wid}", kind="result", author=f"w{wid}",
                          to="coordinator", value={"wid": wid, "i": i}))

    threads = [_threading.Thread(target=worker, args=(w,)) for w in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    rows = bb.readAll()
    assert len(rows) == n_threads * per          # zero lost lines
    ids = {r["entry_id"] for r in rows}
    assert len(ids) == n_threads * per           # zero torn/duplicate ids
    # every line parsed cleanly (no interleaved/torn writes)
    seen = {(r["value"]["wid"], r["value"]["i"]) for r in rows}
    assert len(seen) == n_threads * per
```

- [ ] **Step 2: Run test to verify it fails (or confirm it passes)**

Run: `python -m pytest tests/test_society_blackboard.py::test_concurrent_append_no_lost_or_torn_lines -v`
Expected: PASS (the threadlock already guarantees this). If it FAILS with lost/torn lines, the `_lock` is not wrapping the write — fix by ensuring the `with self._lock:` block encloses the entire `open(...).write(...)` in `append`.

- [ ] **Step 3: (only if Step 2 failed) confirm the lock placement**

No code change expected — `append` already wraps the file write in `with self._lock:`. This step exists to verify the integrity guarantee is real, per success criterion #3.

- [ ] **Step 4: Run the whole blackboard suite**

Run: `python -m pytest tests/test_society_blackboard.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add tests/test_society_blackboard.py
git commit -m "test(society): N-thread blackboard append integrity (criterion #3)"
```

---

## Task 5: Inbox helpers — entry constructor + cursor filter

**Files:**
- Create: `society/inbox.py`
- Modify: `society/__init__.py` (re-export)
- Test: `tests/test_society_inbox.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_society_inbox.py
"""makeEntry constructor + inboxFilter cursor logic (metagpt _observe rule)."""
from society.inbox import makeEntry, inboxFilter


def test_make_entry_defaults():
    e = makeEntry(kind="result", author="coder", to="coordinator",
                  subtask_id="st-1", value={"ok": True})
    assert e.kind == "result" and e.to == "coordinator"
    assert e.key == "result:st-1"            # derived slot when not given
    assert e.refs == [] and e.span_id is None


def test_make_entry_explicit_key_and_refs():
    e = makeEntry(kind="vote", author="reviewer", to="all",
                  value={}, key="vote:debate-3", refs=["bb-1", "bb-2"])
    assert e.key == "vote:debate-3" and e.refs == ["bb-1", "bb-2"]


def test_inbox_filter_role_and_cursor():
    rows = [
        {"entry_id": "a", "to": "all", "ts_ns": 10},
        {"entry_id": "b", "to": "coder", "ts_ns": 20},
        {"entry_id": "c", "to": "tester", "ts_ns": 30},
        {"entry_id": "d", "to": "coder", "ts_ns": 40},
    ]
    got = inboxFilter(rows, role="coder", since_ns=15)
    assert [r["entry_id"] for r in got] == ["b", "d"]  # 'all'@10 cut by cursor; tester excluded
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_society_inbox.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'society.inbox'`

- [ ] **Step 3: Write minimal implementation**

Create `society/inbox.py`:

```python
"""Inbox helpers -- BlackboardEntry constructor + addressing/cursor filter.

A role's inbox = entries where ``to in {role, "all"}`` with ts_ns past its last read
cursor (metagpt _observe). No central router object: addressing is a filter over the
append log.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  makeEntry(kind, author, to, value, *, subtask_id=None, key=None, refs=None, span_id=None) -> BlackboardEntry
  inboxFilter(entries, role, since_ns=0) -> list  -- to in {role,'all'} past the cursor.
DEPENDS-ON: society.blackboard
SIDE-EFFECTS: none
RUN/TEST: python -m pytest tests/test_society_inbox.py
"""
from __future__ import annotations

from typing import Optional

from society.blackboard import BlackboardEntry


def makeEntry(kind: str, author: str, to: str, value: dict, *,
              subtask_id: Optional[str] = None, key: Optional[str] = None,
              refs: Optional[list] = None, span_id: Optional[str] = None) -> BlackboardEntry:
    """Construct a BlackboardEntry, deriving a logical key slot when not supplied."""
    if key is None:
        key = f"{kind}:{subtask_id}" if subtask_id else kind
    return BlackboardEntry(key=key, kind=kind, author=author, to=to,
                           subtask_id=subtask_id, value=value or {},
                           refs=list(refs or []), span_id=span_id)


def inboxFilter(entries: list, role: str, since_ns: int = 0) -> list:
    """Entries addressed to this role (or broadcast) strictly past the read cursor."""
    return [r for r in entries
            if int(r.get("ts_ns", 0)) > since_ns and r.get("to") in (role, "all")]
```

Update `society/__init__.py` imports + `__all__`:

```python
from society.blackboard import Blackboard, BlackboardEntry
from society.inbox import makeEntry, inboxFilter

__all__ = ["Blackboard", "BlackboardEntry", "makeEntry", "inboxFilter"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_society_inbox.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add society/inbox.py society/__init__.py tests/test_society_inbox.py
git commit -m "feat(society): inbox makeEntry constructor + cursor/addressing filter"
```

---

## Task 6: Roles — RoleSpec registry + capability router

**Files:**
- Create: `society/roles.py`
- Modify: `society/__init__.py` (re-export)
- Test: `tests/test_society_roles.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_society_roles.py
"""RoleSpec registry + classifyRole capability router (reuses playbook profiles)."""
from society.roles import ROLES, RoleSpec, classifyRole


def test_registry_has_five_roles():
    assert set(ROLES) == {"planner", "coder", "tester", "reviewer", "researcher"}
    for name, spec in ROLES.items():
        assert isinstance(spec, RoleSpec)
        assert spec.name == name
        assert spec.effort_level  # routes through MODEL_BY_EFFORT


def test_classify_implement_subtask_to_coder():
    st = {"title": "Implement the cache layer", "description": "add an LRU"}
    assert classifyRole(st).name == "coder"


def test_classify_test_subtask_to_tester():
    st = {"title": "Write tests for the parser", "description": "pytest coverage"}
    assert classifyRole(st).name == "tester"


def test_classify_review_subtask_to_reviewer():
    st = {"title": "Audit auth module for vulnerabilities", "description": ""}
    assert classifyRole(st).name == "reviewer"


def test_classify_research_subtask_to_researcher():
    st = {"title": "Research options for the queue", "description": "investigate libraries"}
    assert classifyRole(st).name == "researcher"


def test_brain_hint_overrides_keywords():
    st = {"title": "do the thing", "description": ""}
    assert classifyRole(st, hint="tester").name == "tester"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_society_roles.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'society.roles'`

- [ ] **Step 3: Write minimal implementation**

Create `society/roles.py`:

```python
"""Role registry + capability router for the workforce (owl Workforce coordinator).

Each RoleSpec narrows the executor: a scoped playbook ``profile`` (reused from
agents/playbook.py), an ``effort_level`` (resolved to a model through MODEL_BY_EFFORT),
and optional --allowedTools/--disallowedTools. classifyRole is a deterministic
keyword + brain-hint classifier -- no heavy LLM call.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  RoleSpec(name, profile, effort_level, allowed_tools, disallowed_tools, hint) -- A worker role.
  ROLES -- name -> RoleSpec registry (planner/coder/tester/reviewer/researcher).
  classifyRole(subtask, hint='') -> RoleSpec  -- Capability router over title/description.
DEPENDS-ON: agents.playbook, config
SIDE-EFFECTS: none
RUN/TEST: python -m pytest tests/test_society_roles.py
"""
from __future__ import annotations

from dataclasses import dataclass, field

import config
from agents import playbook


@dataclass(frozen=True)
class RoleSpec:
    """A specialized worker role: scoped playbook profile + model/effort + toolkit."""
    name: str
    profile: str                      # agents/playbook.py profile key
    effort_level: str                 # MODEL_BY_EFFORT key
    allowed_tools: tuple = ()
    disallowed_tools: tuple = ()


def _effort(role: str, default: str) -> str:
    return config.SOCIETY_ROLE_MODELS.get(role, default)


ROLES: dict = {
    "planner":    RoleSpec("planner", "architect", _effort("planner", "default")),
    "coder":      RoleSpec("coder", "implementer", _effort("coder", "high")),
    "tester":     RoleSpec("tester", "tester", _effort("tester", "default")),
    "reviewer":   RoleSpec("reviewer", "reviewer", _effort("reviewer", "high"),
                           disallowed_tools=("Edit", "Write")),
    "researcher": RoleSpec("researcher", "architect", _effort("researcher", "low"),
                           disallowed_tools=("Edit", "Write")),
}

# playbook profile -> society role (capability routing reuse).
_PROFILE_TO_ROLE = {
    "implementer": "coder",
    "tester": "tester",
    "reviewer": "reviewer",
    "architect": "researcher",   # read-only design/research
    "docs": "coder",
    "pr": "coder",
    "generalist": "coder",
}

_RESEARCH_KW = ("research", "investigate", "explore", "survey", "compare options", "evaluate")


def classifyRole(subtask: dict, hint: str = "") -> RoleSpec:
    """Pick the best-fit role. Explicit brain hint wins; else reuse playbook profiles."""
    if hint and hint in ROLES:
        return ROLES[hint]
    hay = f"{(subtask or {}).get('title', '')} {(subtask or {}).get('description', '')}".lower()
    if playbook._hasWord(hay, _RESEARCH_KW):
        return ROLES["researcher"]
    profile = playbook.classifyProfile(None, subtask, None)
    return ROLES[_PROFILE_TO_ROLE.get(profile, "coder")]
```

Update `society/__init__.py`:

```python
from society.blackboard import Blackboard, BlackboardEntry
from society.inbox import makeEntry, inboxFilter
from society.roles import ROLES, RoleSpec, classifyRole

__all__ = ["Blackboard", "BlackboardEntry", "makeEntry", "inboxFilter",
           "ROLES", "RoleSpec", "classifyRole"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_society_roles.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add society/roles.py society/__init__.py tests/test_society_roles.py
git commit -m "feat(society): RoleSpec registry + classifyRole capability router"
```

---

## Task 7: WorkerAgent — CAS claim + role-scoped runClaude wrapper

**Files:**
- Create: `society/worker.py`
- Modify: `society/__init__.py` (re-export)
- Test: `tests/test_society_worker.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_society_worker.py
"""WorkerAgent: CAS-claim on task JSON, injectable run_fn, posts result to board."""
import threading

from society.blackboard import Blackboard
from society.roles import ROLES
from society.worker import WorkerAgent
from state.task import TaskState


def _state_with_subtask():
    st = TaskState.create("goal", 1.0)
    st.addSubtask("Implement x", "do x")
    return st, st.subtasks[0]["subtask_id"]


def test_run_claims_executes_and_posts_result(tmp_path):
    state, sid = _state_with_subtask()
    bb = Blackboard(tmp_path / "b.jsonl")
    calls = {}

    def fake_run(spec, **kw):
        calls["spec"] = spec
        calls["work_dir"] = kw.get("work_dir")
        return {"ok": True, "returncode": 0, "stdout": "done", "cost_usd": 0.01}

    w = WorkerAgent(ROLES["coder"], state.getSubtask(sid), str(tmp_path),
                    bb, state, threading.Lock(), run_fn=fake_run)
    msg = w.run()

    assert msg["ok"] is True and msg["role"] == "coder"
    assert state.getSubtask(sid)["status"] == "in_progress"
    assert state.getSubtask(sid)["claimed_by"] == "coder"
    # role narrows effort/model but does not bypass routing
    assert calls["spec"]["effort_level"] == ROLES["coder"].effort_level
    assert calls["work_dir"] == str(tmp_path)
    posted = bb.readAll()
    assert posted[-1]["kind"] == "result" and posted[-1]["author"] == "coder"


def test_lost_claim_yields_without_running(tmp_path):
    state, sid = _state_with_subtask()
    state.updateSubtask(sid, status="in_progress", claimed_by="other")  # already taken
    bb = Blackboard(tmp_path / "b.jsonl")
    ran = {"n": 0}

    def fake_run(spec, **kw):
        ran["n"] += 1
        return {"ok": True}

    w = WorkerAgent(ROLES["coder"], state.getSubtask(sid), str(tmp_path),
                    bb, state, threading.Lock(), run_fn=fake_run)
    msg = w.run()
    assert msg["ok"] is False and msg["kind"] == "claim"
    assert ran["n"] == 0  # never executed -- lost the race


def test_two_workers_one_winner(tmp_path):
    state, sid = _state_with_subtask()
    bb = Blackboard(tmp_path / "b.jsonl")
    lock = threading.Lock()
    wins = []

    def fake_run(spec, **kw):
        return {"ok": True, "returncode": 0}

    def attempt(role):
        w = WorkerAgent(ROLES[role], state.getSubtask(sid), str(tmp_path),
                        bb, state, lock, run_fn=fake_run)
        m = w.run()
        if m["ok"]:
            wins.append(role)

    t1 = threading.Thread(target=attempt, args=("coder",))
    t2 = threading.Thread(target=attempt, args=("tester",))
    t1.start(); t2.start(); t1.join(); t2.join()
    assert len(wins) == 1  # exactly one worker ever owns the subtask
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_society_worker.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'society.worker'`

- [ ] **Step 3: Write minimal implementation**

Create `society/worker.py`:

```python
"""WorkerAgent -- a role-scoped wrapper over agents/executor.py::runClaude.

The worker performs the atomic CAS claim against TASK JSON (guild accept.go single-
statement claim) under the shared state lock, builds a role-scoped InvocationSpec, runs
the injectable run_fn (default runClaude) in its worktree cwd, then posts a `result`
to its blackboard inbox slot. No new subprocess path -- all hooks/guards/telemetry stay
intact. Workers CANNOT spawn sub-workers (warp recursion rail).

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  WorkerAgent(role, subtask, work_dir, blackboard, state, state_lock, *, run_fn=None) -- One role worker.
DEPENDS-ON: agents.executor, agents.playbook, config, society.inbox, state.task
SIDE-EFFECTS: claims+updates task JSON, runs Claude, appends to the blackboard
RUN/TEST: python -m pytest tests/test_society_worker.py
"""
from __future__ import annotations

from typing import Callable, Optional

import config
from agents import playbook
from society.inbox import makeEntry

LOG = config.getLogger("society.worker")


def _defaultRunFn(spec, **kw):
    # Imported lazily so tests that inject run_fn never import the real executor.
    from agents.executor import runClaude
    return runClaude(spec, **kw)


class WorkerAgent:
    """Claim a subtask, execute it under a role, post the result."""

    def __init__(self, role, subtask: dict, work_dir: str, blackboard,
                 state, state_lock, *, run_fn: Optional[Callable] = None) -> None:
        self._role = role
        self._subtask = subtask
        self._sid = subtask["subtask_id"]
        self._work_dir = work_dir
        self._blackboard = blackboard
        self._state = state
        self._state_lock = state_lock
        self._run_fn = run_fn or _defaultRunFn

    def claim(self) -> bool:
        """CAS claim on task JSON: pending -> in_progress+claimed_by under the state lock."""
        with self._state_lock:
            st = self._state.getSubtask(self._sid)
            if st is None or st.get("status") != "pending":
                return False
            self._state.updateSubtask(self._sid, status="in_progress",
                                      claimed_by=self._role.name)
            return True

    def _buildSpec(self) -> dict:
        """Role-scoped InvocationSpec: narrows effort + toolkit, never bypasses routing."""
        spec: dict = {
            "prompt": self._subtask.get("description") or self._subtask.get("title", ""),
            "effort_level": self._role.effort_level,
            "claude_md_inject": (self._subtask.get("description") or ""),
        }
        if self._role.allowed_tools:
            spec["allowed_tools"] = list(self._role.allowed_tools)
        if self._role.disallowed_tools:
            spec["disallowed_tools"] = list(self._role.disallowed_tools)
        return spec

    def _messageFromResult(self, result: dict) -> dict:
        ok = bool(result.get("ok")) and result.get("returncode", 1) == 0
        return {
            "role": self._role.name, "subtask_id": self._sid, "kind": "result",
            "ok": ok, "summary": (result.get("stdout") or "")[:500],
            "refs": [], "value": {"cost_usd": result.get("cost_usd"),
                                  "returncode": result.get("returncode")},
        }

    def run(self) -> dict:
        """Claim -> execute -> post. Returns a WorkerMessage dict."""
        if not self.claim():
            return {"role": self._role.name, "subtask_id": self._sid, "kind": "claim",
                    "ok": False, "summary": "lost claim", "refs": [], "value": {}}
        result = self._run_fn(self._buildSpec(), work_dir=self._work_dir,
                              task_state=self._state, subtask=self._subtask)
        msg = self._messageFromResult(result)
        self._blackboard.append(makeEntry(
            kind="result", author=self._role.name, to="coordinator",
            subtask_id=self._sid, value=msg))
        return msg
```

Update `society/__init__.py`:

```python
from society.blackboard import Blackboard, BlackboardEntry
from society.inbox import makeEntry, inboxFilter
from society.roles import ROLES, RoleSpec, classifyRole
from society.worker import WorkerAgent

__all__ = ["Blackboard", "BlackboardEntry", "makeEntry", "inboxFilter",
           "ROLES", "RoleSpec", "classifyRole", "WorkerAgent"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_society_worker.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add society/worker.py society/__init__.py tests/test_society_worker.py
git commit -m "feat(society): WorkerAgent CAS-claim + role-scoped runClaude wrapper"
```

---

## Task 8: Debate — speaker selection, arbiter, oscillation guard

**Files:**
- Create: `society/debate.py`
- Modify: `society/__init__.py` (re-export)
- Test: `tests/test_society_debate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_society_debate.py
"""Structured debate: deterministic speaker selection, convergence, round-cap, oscillation."""
from society.blackboard import Blackboard
from society.debate import selectNextSpeaker, runDebate


def test_select_next_speaker_picks_unanswered():
    roster = ["coder", "reviewer"]
    thread = [
        {"entry_id": "p1", "author": "coder", "kind": "proposal", "refs": []},
        {"entry_id": "c1", "author": "reviewer", "kind": "proposal", "refs": ["p1"]},
    ]
    # coder's p1 has been answered (c1 refs it); reviewer's c1 is unanswered -> coder speaks next
    assert selectNextSpeaker(thread, roster) == "coder"


def test_converges_on_consensus(tmp_path):
    bb = Blackboard(tmp_path / "d.jsonl")

    def arbiter(**kw):  # scripted: immediately resolved in favor of coder
        return {"verdict": "approved", "tier": "stub",
                "value": {"is_resolved": True, "next_speaker": "coder",
                          "winner": "coder"}}

    v = runDebate(bb, subtask_id="st-1", roster=["coder", "reviewer"],
                  arbiter_fn=arbiter, max_rounds=3)
    assert v["resolved"] is True and v["winner"] == "coder"
    assert v["stopped_reason"] == "consensus" and v["rounds"] >= 1


def test_stops_on_round_cap(tmp_path):
    bb = Blackboard(tmp_path / "d.jsonl")

    def arbiter(**kw):  # never resolves, always alternates
        return {"verdict": "challenged", "tier": "stub",
                "value": {"is_resolved": False, "next_speaker": "reviewer",
                          "proposal": "x"}}

    v = runDebate(bb, subtask_id="st-1", roster=["coder", "reviewer"],
                  arbiter_fn=arbiter, max_rounds=2)
    assert v["resolved"] is False and v["stopped_reason"] == "round_cap"
    assert v["rounds"] == 2


def test_stops_on_oscillation(tmp_path):
    bb = Blackboard(tmp_path / "d.jsonl")
    seq = iter(["A", "B", "A", "B", "A", "B"])

    def arbiter(**kw):  # proposals cycle A->B->A -> oscillation guard fires
        return {"verdict": "challenged", "tier": "stub",
                "value": {"is_resolved": False, "next_speaker": "coder",
                          "proposal": next(seq)}}

    v = runDebate(bb, subtask_id="st-1", roster=["coder", "reviewer"],
                  arbiter_fn=arbiter, max_rounds=10)
    assert v["resolved"] is False and v["stopped_reason"] == "oscillation"
    assert v["rounds"] < 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_society_debate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'society.debate'`

- [ ] **Step 3: Write minimal implementation**

Create `society/debate.py`:

```python
"""Structured debate / speaker-selection -- bounded convergence for contested results.

selectNextSpeaker (autogen SelectorGroupChat / Magentic-One progress ledger) narrows
candidates from blackboard state, then an arbiter (default agents/second_brain.consult)
emits a small schema-bounded judgment. Bounded by max_rounds + a diff-hash oscillation
ring (loki). Output is an advisory DebateVerdict -- the verifier still gates.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  selectNextSpeaker(thread, roster) -> str  -- Deterministic next speaker (unanswered refs).
  runDebate(blackboard, subtask_id, roster, *, arbiter_fn=None, max_rounds=None, goal='') -> DebateVerdict
DEPENDS-ON: agents.second_brain, config, society.inbox
SIDE-EFFECTS: appends proposal/vote entries to the blackboard
RUN/TEST: python -m pytest tests/test_society_debate.py
"""
from __future__ import annotations

import hashlib
from typing import Callable, Optional

import config
from society.inbox import makeEntry

LOG = config.getLogger("society.debate")


def _defaultArbiter(**kw):
    from agents import second_brain
    return second_brain.consult(**kw)


def selectNextSpeaker(thread: list, roster: list) -> str:
    """Pick the role whose latest proposal is unanswered (no later entry refs it)."""
    answered = set()
    for e in thread:
        for ref in (e.get("refs") or []):
            answered.add(ref)
    # Walk newest-first; the first author whose entry is not yet answered speaks.
    for e in reversed(thread):
        if e.get("entry_id") not in answered and e.get("author") in roster:
            return e["author"]
    return roster[0]


def _diffHash(proposal) -> str:
    return hashlib.sha1(str(proposal).encode("utf-8", "replace")).hexdigest()[:12]


def runDebate(blackboard, subtask_id: str, roster: list, *,
              arbiter_fn: Optional[Callable] = None,
              max_rounds: Optional[int] = None, goal: str = "") -> dict:
    """Run bounded speaker-selected rounds; converge or stop. Returns a DebateVerdict."""
    arbiter_fn = arbiter_fn or _defaultArbiter
    max_rounds = max_rounds or config.SOCIETY_DEBATE_MAX_ROUNDS
    seen_hashes: list = []
    rounds = 0
    speaker = roster[0]
    while rounds < max_rounds:
        rounds += 1
        thread = blackboard.read(role="coordinator", kind="proposal")
        if thread:
            speaker = selectNextSpeaker(thread, roster)
        verdict = arbiter_fn(review_type="subtask", title=f"debate:{subtask_id}",
                             trigger_reason="contested result", content=str(thread),
                             goal=goal)
        judgment = verdict.get("value") or {}
        if judgment.get("is_resolved"):
            blackboard.append(makeEntry(kind="vote", author="coordinator", to="all",
                                        subtask_id=subtask_id,
                                        value={"winner": judgment.get("winner")}))
            return {"resolved": True, "winner": judgment.get("winner"),
                    "reason": "consensus", "rounds": rounds,
                    "stopped_reason": "consensus"}
        proposal = judgment.get("proposal")
        h = _diffHash(proposal)
        if h in seen_hashes:   # oscillation: A->B->A cycle -> force-stop + escalate
            LOG.warning("debate oscillation on %s (round %d); escalating", subtask_id, rounds)
            return {"resolved": False, "winner": None, "reason": "oscillation",
                    "rounds": rounds, "stopped_reason": "oscillation"}
        seen_hashes.append(h)
        blackboard.append(makeEntry(kind="proposal", author=speaker, to="all",
                                    subtask_id=subtask_id, value={"proposal": proposal}))
        speaker = judgment.get("next_speaker") or speaker
    return {"resolved": False, "winner": None, "reason": "round cap reached",
            "rounds": rounds, "stopped_reason": "round_cap"}
```

Update `society/__init__.py`:

```python
from society.blackboard import Blackboard, BlackboardEntry
from society.inbox import makeEntry, inboxFilter
from society.roles import ROLES, RoleSpec, classifyRole
from society.worker import WorkerAgent
from society.debate import runDebate, selectNextSpeaker

__all__ = ["Blackboard", "BlackboardEntry", "makeEntry", "inboxFilter",
           "ROLES", "RoleSpec", "classifyRole", "WorkerAgent",
           "runDebate", "selectNextSpeaker"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_society_debate.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add society/debate.py society/__init__.py tests/test_society_debate.py
git commit -m "feat(society): bounded debate with speaker selection + oscillation guard"
```

---

## Task 9: Coordinator — disjoint batch (Epic-1 seam), parallel spawn, collect

**Files:**
- Create: `society/coordinator.py`
- Modify: `society/__init__.py` (re-export)
- Test: `tests/test_society_coordinator.py`

- [ ] **Step 0 (Epic-1 SEAM STUB — explicitly marked):** `selectDisjointBatch(ready, max_workers, file_sets_fn=None)` ships with `file_sets_fn=None` → deps-only batch (today's `_handleParallelBatch` behavior). This IS the Epic-1 file-disjointness CAS seam. When Epic 1 lands, pass its real `file_sets_fn`; no other Epic-5 code changes.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_society_coordinator.py
"""Coordinator: facts post, disjoint batch seam, parallel spawn, collect, contest detect."""
import threading

from society.blackboard import Blackboard
from society.coordinator import Coordinator
from state.task import TaskState


def _state_two_ready():
    st = TaskState.create("multi goal", 1.0)
    st.addSubtask("Implement a.py", "edit a.py")
    st.addSubtask("Write tests for a", "pytest a")
    return st


def test_post_facts_writes_facts_entry(tmp_path):
    state = _state_two_ready()
    bb = Blackboard(tmp_path / "c.jsonl")
    coord = Coordinator(state, bb, threading.Lock(), work_dir=str(tmp_path))
    coord.postFacts({"given": ["x"], "plan": ["do x"]})
    rows = bb.readAll()
    assert rows[-1]["kind"] == "facts" and rows[-1]["to"] == "all"


def test_select_disjoint_batch_deps_only_seam(tmp_path):
    state = _state_two_ready()
    bb = Blackboard(tmp_path / "c.jsonl")
    coord = Coordinator(state, bb, threading.Lock(), work_dir=str(tmp_path))
    ready = [s for s in state.subtasks if s["status"] == "pending"]
    batch = coord.selectDisjointBatch(ready, max_workers=3, file_sets_fn=None)
    assert len(batch) == 2  # deps-only fallback returns the whole ready set (capped)


def test_select_disjoint_batch_filters_overlap(tmp_path):
    state = _state_two_ready()
    bb = Blackboard(tmp_path / "c.jsonl")
    coord = Coordinator(state, bb, threading.Lock(), work_dir=str(tmp_path))
    ready = [s for s in state.subtasks if s["status"] == "pending"]
    # both subtasks touch a.py -> only the first is schedulable disjointly
    batch = coord.selectDisjointBatch(ready, max_workers=3,
                                      file_sets_fn=lambda st: {"a.py"})
    assert len(batch) == 1


def test_handle_society_batch_runs_workers_and_collects(tmp_path):
    state = _state_two_ready()
    bb = Blackboard(tmp_path / "c.jsonl")
    coord = Coordinator(state, bb, threading.Lock(), work_dir=str(tmp_path))
    ran = []

    def fake_run(spec, **kw):
        ran.append(kw["subtask"]["subtask_id"])
        return {"ok": True, "returncode": 0, "stdout": "ok"}

    ready = [s for s in state.subtasks if s["status"] == "pending"]
    msgs = coord._handleSocietyBatch(ready, parallelism=2, run_fn=fake_run)
    assert len(ran) == 2 and all(m["ok"] for m in msgs)
    assert {s["status"] for s in state.subtasks} == {"in_progress"}  # claimed; verifier lands later


def test_detect_contested_flags_failed_result(tmp_path):
    state = _state_two_ready()
    bb = Blackboard(tmp_path / "c.jsonl")
    coord = Coordinator(state, bb, threading.Lock(), work_dir=str(tmp_path))
    msgs = [{"role": "coder", "subtask_id": "st-001", "ok": True},
            {"role": "reviewer", "subtask_id": "st-001", "ok": False}]
    assert coord.detectContested(msgs) == ["st-001"]


def test_worker_crash_contained(tmp_path):
    state = _state_two_ready()
    bb = Blackboard(tmp_path / "c.jsonl")
    coord = Coordinator(state, bb, threading.Lock(), work_dir=str(tmp_path))

    def boom(spec, **kw):
        if kw["subtask"]["subtask_id"] == "st-001":
            raise RuntimeError("worker exploded")
        return {"ok": True, "returncode": 0}

    ready = [s for s in state.subtasks if s["status"] == "pending"]
    msgs = coord._handleSocietyBatch(ready, parallelism=2, run_fn=boom)
    statuses = {s["subtask_id"]: s["status"] for s in state.subtasks}
    assert statuses["st-001"] == "failed"          # crashed -> failed, peers unaffected
    assert any(m["ok"] for m in msgs)              # the other worker still completed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_society_coordinator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'society.coordinator'`

- [ ] **Step 3: Write minimal implementation**

Create `society/coordinator.py`:

```python
"""Coordinator -- deterministic Python workforce orchestration (NOT a new LLM).

Decompose (reuse OrchestratorPlanMixin.authorSubtaskPlan) -> post the Task-Ledger facts
-> select a file-disjoint batch (Epic-1 seam) -> spawn one WorkerAgent per claim in a
ThreadPoolExecutor mirroring run_loop_mixin._handleParallelBatch (same crash containment)
-> collect results from the blackboard -> flag contested subtasks for debate. Task JSON
owns status/claim; the verifier still gates. Workers never spawn sub-workers.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  Coordinator(state, blackboard, state_lock, *, work_dir, bus=None) -- Workforce orchestrator.
DEPENDS-ON: config, society.inbox, society.roles, society.worker, state.task
SIDE-EFFECTS: claims/updates task JSON, runs workers, appends to the blackboard
RUN/TEST: python -m pytest tests/test_society_coordinator.py
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

import config
from society.inbox import makeEntry
from society.roles import classifyRole
from society.worker import WorkerAgent
from state.task import nowIso

LOG = config.getLogger("society.coordinator")


class Coordinator:
    """Owns workforce orchestration over the blackboard; never owns run state."""

    def __init__(self, state, blackboard, state_lock, *, work_dir: str, bus=None) -> None:
        self._state = state
        self._blackboard = blackboard
        self._state_lock = state_lock
        self._work_dir = work_dir
        self._bus = bus

    def postFacts(self, facts: dict) -> str:
        """Write the Magentic-One Task-Ledger facts once to the board (kind=facts, to=all)."""
        return self._blackboard.append(makeEntry(
            kind="facts", author="coordinator", to="all", value=facts))

    def selectDisjointBatch(self, ready: list, max_workers: int,
                            file_sets_fn: Optional[Callable] = None) -> list:
        """Pick up to max_workers ready subtasks with DISJOINT file-sets (Epic-1 CAS seam).

        SEAM: file_sets_fn(subtask) -> set[str]. When None (no Epic 1), fall back to the
        deps-only batch -- identical to today's _handleParallelBatch scheduling."""
        if file_sets_fn is None:
            return ready[:max_workers]
        chosen, used = [], set()
        for st in ready:
            files = file_sets_fn(st) or set()
            if files & used:
                continue
            used |= files
            chosen.append(st)
            if len(chosen) >= max_workers:
                break
        return chosen

    def _handleSocietyBatch(self, batch: list, parallelism: int,
                            run_fn: Optional[Callable] = None) -> list:
        """Spawn one WorkerAgent per subtask concurrently; collect WorkerMessages.

        Mirrors run_loop_mixin._handleParallelBatch crash containment: a crashed worker
        flips its subtask to 'failed' and records a notification; peers are unaffected."""
        messages: list = []
        with ThreadPoolExecutor(max_workers=max(1, parallelism)) as pool:
            futures = {}
            for st in batch:
                role = classifyRole(st, hint=st.get("assigned_role", ""))
                worker = WorkerAgent(role, st, self._work_dir, self._blackboard,
                                     self._state, self._state_lock, run_fn=run_fn)
                futures[pool.submit(worker.run)] = st
            for f in as_completed(futures):
                st = futures[f]
                try:
                    messages.append(f.result())
                except Exception as e:  # noqa: BLE001 -- a crashed worker must not strand the subtask
                    LOG.error("society worker %s crashed: %s",
                              st.get("subtask_id"), e, exc_info=True)
                    with self._state_lock:
                        self._state.updateSubtask(st["subtask_id"], status="failed",
                                                  completed_at=nowIso())
                        self._state.addNotification(
                            "subtask_crashed", f"{st.get('subtask_id')}: {e}")
        return messages

    def detectContested(self, messages: list) -> list:
        """Subtask ids with conflicting worker verdicts (any not-ok report) -> need debate."""
        contested = []
        for sid in {m.get("subtask_id") for m in messages}:
            verdicts = [m.get("ok") for m in messages if m.get("subtask_id") == sid]
            if any(v is False for v in verdicts):
                contested.append(sid)
        return sorted(c for c in contested if c)
```

Update `society/__init__.py`:

```python
from society.blackboard import Blackboard, BlackboardEntry
from society.inbox import makeEntry, inboxFilter
from society.roles import ROLES, RoleSpec, classifyRole
from society.worker import WorkerAgent
from society.debate import runDebate, selectNextSpeaker
from society.coordinator import Coordinator

__all__ = ["Blackboard", "BlackboardEntry", "makeEntry", "inboxFilter",
           "ROLES", "RoleSpec", "classifyRole", "WorkerAgent",
           "runDebate", "selectNextSpeaker", "Coordinator"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_society_coordinator.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add society/coordinator.py society/__init__.py tests/test_society_coordinator.py
git commit -m "feat(society): Coordinator with Epic-1 disjoint seam + parallel batch + contest detect"
```

---

## Task 10: event_bus mirror — society appends are live-visible

**Files:**
- Modify: `society/coordinator.py` (add `_busMirror`, wire as the blackboard `on_append`)
- Test: `tests/test_society_coordinator.py` (add mirror test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_society_coordinator.py`:

```python
from notifications.event_bus import LiveEventBus
from society.blackboard import Blackboard as _BB
from society.coordinator import Coordinator as _Coord


def test_blackboard_appends_mirror_to_event_bus(tmp_path):
    bus = LiveEventBus()
    state = _state_two_ready()
    bb = _BB(tmp_path / "m.jsonl")
    coord = _Coord(state, bb, __import__("threading").Lock(),
                   work_dir=str(tmp_path), bus=bus)
    coord.attachBus()                     # wires bus mirror as blackboard.on_append
    coord.postFacts({"plan": ["x"]})
    events = bus.history(last_n=10)
    assert any(e["kind"] == "society" for e in events)
    assert events[-1]["data"]["kind"] == "facts"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_society_coordinator.py::test_blackboard_appends_mirror_to_event_bus -v`
Expected: FAIL with `AttributeError: 'Coordinator' object has no attribute 'attachBus'`

- [ ] **Step 3: Write minimal implementation**

In `society/coordinator.py`, add the `Event` import at the top of the imports block:

```python
from notifications.event_bus import Event, get_bus
```

Add these two methods to `Coordinator` (after `__init__`):

```python
    def attachBus(self) -> None:
        """Wire the event_bus mirror as the blackboard's on_append hook (presentation only)."""
        self._blackboard._on_append = self._busMirror

    def _busMirror(self, rec: dict) -> None:
        """Emit a presentation-only mirror Event for every durable blackboard append.

        The blackboard stays the source of truth; event_bus stays ephemeral fan-out."""
        bus = self._bus or get_bus()
        try:
            bus.emit(Event(kind="society",
                           sid=str(getattr(self._state, "task_id", "")),
                           text=f"{rec.get('author')} -> {rec.get('to')}: {rec.get('kind')}",
                           data=rec))
        except Exception:  # noqa: BLE001 -- the mirror must never break coordination
            LOG.warning("society bus mirror failed", exc_info=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_society_coordinator.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add society/coordinator.py tests/test_society_coordinator.py
git commit -m "feat(society): mirror blackboard appends to event_bus for live surfaces"
```

---

## Task 11: Run-loop wiring + society-OFF byte-identical invariance

**Files:**
- Modify: `platform_core/orchestration/run_loop_mixin.py` (add `_societyGate`, `_handleSocietyBatch`; route the parallel branch)
- Test: `tests/test_society_off_invariance.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_society_off_invariance.py
"""SOCIETY_ENABLED=False: the gate is closed and routing is unchanged (star/parallel path)."""
import config
from platform_core.orchestration.run_loop_mixin import OrchestratorRunLoopMixin


class _Stub(OrchestratorRunLoopMixin):
    pass


def test_gate_closed_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "SOCIETY_ENABLED", False)
    s = _Stub()
    # even with 2 disjoint ready subtasks, the gate stays closed when the flag is off
    assert s._societyGate([{"subtask_id": "st-1"}, {"subtask_id": "st-2"}]) is False


def test_gate_needs_two_ready(monkeypatch):
    monkeypatch.setattr(config, "SOCIETY_ENABLED", True)
    s = _Stub()
    assert s._societyGate([{"subtask_id": "st-1"}]) is False        # <2 ready -> star path
    assert s._societyGate([{"subtask_id": "st-1"},
                           {"subtask_id": "st-2"}]) is True


def test_handle_society_batch_delegates_to_coordinator(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SOCIETY_ENABLED", True)
    from state.task import TaskState
    state = TaskState.create("multi", 1.0)
    state.addSubtask("Implement a", "edit a.py")
    state.addSubtask("Test a", "pytest a")
    s = _Stub()
    s._state_lock = __import__("threading").Lock()
    s._parallelism = 2
    s._work_dir = str(tmp_path)
    ran = []

    monkeypatch.setattr("society.worker._defaultRunFn",
                        lambda spec, **kw: ran.append(kw["subtask"]["subtask_id"]) or
                        {"ok": True, "returncode": 0})
    ready = [s2 for s2 in state.subtasks if s2["status"] == "pending"]
    s._handleSocietyBatch(state, ready, str(tmp_path), parallelism=2)
    assert len(ran) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_society_off_invariance.py -v`
Expected: FAIL with `AttributeError: '_Stub' object has no attribute '_societyGate'`

- [ ] **Step 3: Write minimal implementation**

In `platform_core/orchestration/run_loop_mixin.py`, add a top-of-file import (after the existing `from state.task import TaskState, nowIso` line):

```python
from platform_core.app_config.paths import BLACKBOARD_DIR
```

Add these two methods to `OrchestratorRunLoopMixin` (right after `_handleParallelBatch`, before `runExecutionLoop`):

```python
    def _societyGate(self, ready: list) -> bool:
        """True when the workforce should engage: flag ON and >=2 disjoint-ready subtasks.

        Standalone (no Epic 1): disjointness defaults to deps-only, so this is 'flag ON and
        >=2 ready'. When off, the star/parallel path runs unchanged (byte-identical)."""
        return bool(config.SOCIETY_ENABLED) and len(ready) >= 2

    def _handleSocietyBatch(self, state: TaskState, ready: list, work_dir: str,
                            parallelism: int, run_fn=None) -> "tuple[int, AbortRun | None]":
        """Delegate a ready batch to the society Coordinator (worktree-isolated workers).

        Returns (count_started, None) -- the verifier still gates landing downstream. Crash
        containment lives in Coordinator._handleSocietyBatch (mirrors _handleParallelBatch)."""
        from society.blackboard import Blackboard
        from society.coordinator import Coordinator
        bb = Blackboard.forTask(state.task_id, base_dir=BLACKBOARD_DIR)
        coord = Coordinator(state, bb, self._state_lock, work_dir=work_dir)
        coord.attachBus()
        batch = coord.selectDisjointBatch(ready, min(parallelism, config.SOCIETY_MAX_WORKERS))
        messages = coord._handleSocietyBatch(batch, parallelism, run_fn=run_fn)
        try:
            experience.close_pool()   # match _handleParallelBatch SQLite cleanup (CB-3)
        except Exception:  # noqa: BLE001
            pass
        return len(messages), None
```

In `runExecutionLoop`, replace the parallel-branch tail (the block that currently reads
`position, abort = self._handleParallelBatch(...)` after computing `ready`, lines ~267-269)
with a gated route:

```python
            # parallel: run the ready set (deps satisfied) concurrently
            ready = self._readySet(state)
            if not ready:
                if state.nextActionable() is None:
                    cont, dry_backfills = self._continueAfterDrain(
                        state, architect_doc, dashboard, dry_backfills)
                    if cont:
                        continue
                    break
                ready = [state.nextActionable()]
            if self._societyGate(ready):
                # Epic 5: 9to5-owned workforce on the blackboard (flag ON, >=2 ready).
                position2, abort = self._handleSocietyBatch(
                    state, ready[:parallelism], work_dir, parallelism)
                position += position2
            else:
                position, abort = self._handleParallelBatch(
                    state, ready[:parallelism], architect_doc, work_dir,
                    bus, dashboard, position, parallelism)
            if abort is not None:
                raise abort
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_society_off_invariance.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Run the existing run-loop / parallel regression to prove OFF-path invariance**

Run: `python -m pytest tests/ -k "run_loop or parallel or executor" -q`
Expected: PASS (no regressions — the OFF path is unchanged because `_societyGate` returns `False` when `SOCIETY_ENABLED` is `False`)

- [ ] **Step 6: Commit**

```bash
git add platform_core/orchestration/run_loop_mixin.py tests/test_society_off_invariance.py
git commit -m "feat(society): gate run-loop parallel branch through workforce (OFF by default)"
```

---

## Task 12: Co-design notes — review_mixin + executor_env guard comments

**Files:**
- Modify: `platform_core/orchestration/review_mixin.py:119-126` (`_remediationTreeShared`)
- Modify: `agents/executor_env.py` (`_composeWorkflowPrompt` guard comment)
- Test: `tests/test_society_off_invariance.py` (assert no behavior change)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_society_off_invariance.py`:

```python
from platform_core.orchestration.review_mixin import OrchestratorReviewMixin


class _RStub(OrchestratorReviewMixin):
    pass


def test_remediation_tree_shared_unchanged_under_parallelism():
    s = _RStub()
    s._parallelism = 3
    # Co-design with Epic 1: until worktrees land, parallel runs still share the tree.
    assert s._remediationTreeShared() is True


def test_remediation_tree_shared_false_when_sequential():
    s = _RStub()
    s._parallelism = 1
    assert s._remediationTreeShared() is False
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `python -m pytest tests/test_society_off_invariance.py -k remediation -v`
Expected: PASS (behavior is already correct; this test pins it so the doc comment in Step 3 cannot drift into a behavior change).

- [ ] **Step 3: Add the co-design comments (NO behavior change)**

In `platform_core/orchestration/review_mixin.py`, inside `_remediationTreeShared`, replace the
final `return` line with the same return plus a co-design note:

```python
        # EPIC 5 co-design: once Epic 1 per-worker git worktrees land, each society worker
        # edits its OWN tree, so a remediation snapshot/restore can no longer clobber a peer.
        # At that point this becomes: `return getattr(self, "_parallelism", 1) > 1 and not
        # config.SOCIETY_WORKTREES_ACTIVE`. Until then it is UNCHANGED (shared-tree advisory
        # mode) -- a one-line flip, gated by Epic 1.
        return getattr(self, "_parallelism", 1) > 1
```

In `agents/executor_env.py`, find `_composeWorkflowPrompt` and add a one-line guard comment
just under its docstring/first line (no behavior change):

```python
    # EPIC 5: when config.SOCIETY_ENABLED, the coordinator REALIZES a parallel-phase workflow
    # itself as visible 9to5 WorkerAgents (society/coordinator.py) instead of this opaque
    # Claude-internal Task-tool fan-out. With society OFF this path runs exactly as before.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_society_off_invariance.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add platform_core/orchestration/review_mixin.py agents/executor_env.py tests/test_society_off_invariance.py
git commit -m "docs(society): co-design comments for Epic-1 worktree flip + workflow supersession"
```

---

## Task 13: Cost-budget governor + recursion rail

**Files:**
- Modify: `society/coordinator.py` (add `budgetExceeded`, track spend)
- Test: `tests/test_society_coordinator.py` (add governor test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_society_coordinator.py`:

```python
def test_budget_governor_stops_spawning(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "SOCIETY_TOKEN_BUDGET_USD", 0.05)
    state = _state_two_ready()
    bb = Blackboard(tmp_path / "g.jsonl")
    coord = Coordinator(state, bb, threading.Lock(), work_dir=str(tmp_path))

    def fake_run(spec, **kw):
        return {"ok": True, "returncode": 0, "cost_usd": 0.04}

    ready = [s for s in state.subtasks if s["status"] == "pending"]
    coord._handleSocietyBatch(ready, parallelism=2, run_fn=fake_run)
    # two workers each cost 0.04 -> 0.08 > 0.05 budget
    assert coord.spent_usd >= 0.05
    assert coord.budgetExceeded() is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_society_coordinator.py::test_budget_governor_stops_spawning -v`
Expected: FAIL with `AttributeError: 'Coordinator' object has no attribute 'spent_usd'`

- [ ] **Step 3: Write minimal implementation**

In `society/coordinator.py`, add `self.spent_usd = 0.0` at the end of `__init__`:

```python
        self.spent_usd = 0.0
```

Add the governor method to `Coordinator`:

```python
    def budgetExceeded(self) -> bool:
        """True once accumulated worker spend breaches SOCIETY_TOKEN_BUDGET_USD."""
        return self.spent_usd >= config.SOCIETY_TOKEN_BUDGET_USD
```

In `_handleSocietyBatch`, accumulate spend from each collected message (inside the
`messages.append(f.result())` flow). Replace the `messages.append(f.result())` line with:

```python
                    msg = f.result()
                    messages.append(msg)
                    cost = (msg.get("value") or {}).get("cost_usd")
                    if isinstance(cost, (int, float)):
                        self.spent_usd += float(cost)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_society_coordinator.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add society/coordinator.py tests/test_society_coordinator.py
git commit -m "feat(society): per-run USD budget governor on the coordinator"
```

---

## Task 14: Module sizing, repo map, docs

**Files:**
- Modify: `docs/ARCHITECTURE.md` (workforce section + source-of-truth row)
- Regenerate: `AGENTS.md` (via `tools/repo_map.py`)
- Validate: all `society/*.py`

- [ ] **Step 1: Size audit on the new package**

Run: `python tools/size_audit.py`
Expected: ZERO `must_split` violations. If any `society/*.py` exceeds 450 lines or a function exceeds 70 lines, split per the codebase pattern (e.g. `coordinator.py` → `coordinator_assign.py` + `coordinator_collect.py` with `coordinator.py` as a thin facade re-exporting `Coordinator`).

- [ ] **Step 2: Focused per-file validation**

Run:
```bash
python tools/dev.py check society/blackboard.py
python tools/dev.py check society/coordinator.py
python tools/dev.py check society/worker.py
python tools/dev.py check society/debate.py
```
Expected: each PASS (lint + type + mapped tests for the file).

- [ ] **Step 3: Regenerate the repo map**

Run: `python tools/repo_map.py`
Expected: `AGENTS.md` updated with the new `society/` module rows (do NOT hand-edit generated rows).

- [ ] **Step 4: Document the workforce in ARCHITECTURE.md**

Add to `docs/ARCHITECTURE.md` a "Workforce topology (Epic 5)" section describing: the
coordinator/worker/blackboard/debate units, the LOCKED threads+worktree concurrency boundary,
the `SOCIETY_ENABLED` flag + shared-tree advisory fallback, and the Epic-1 dependency. Add one
row to the source-of-truth table: **Blackboard — coordination artifacts (NOT status; task JSON
still owns status/claim)**.

- [ ] **Step 5: Full fast suite + commit**

Run: `python tools/dev.py fast`
Expected: PASS (green before handoff).

```bash
git add docs/ARCHITECTURE.md AGENTS.md society/
git commit -m "docs(society): workforce topology in ARCHITECTURE.md + regenerated repo map"
```

---

## Self-Review

**1. Spec coverage** (each spec §/requirement → task):

| Spec item | Task(s) |
|---|---|
| §3(a) Coordinator (decompose/assign/spawn/collect) | 9 (assign/spawn/collect), 11 (run-loop invocation), `postFacts` Task 9 |
| §3(b) WorkerAgent (RoleSpec, own model routing, runClaude wrapper, CAS claim) | 6 (roles+routing), 7 (worker+claim) |
| §3(c) Blackboard (append-only JSONL, flock+threadlock, read/inbox, ownership, event_bus mirror, report-don't-poll) | 3, 4 (concurrency), 5 (inbox), 10 (mirror) |
| §3(d) Debate (speaker selection, rounds, arbiter=second_brain.consult, oscillation, advisory verdict) | 8 |
| §3(e) Wrapping the Claude-subagent path | 12 (executor_env guard comment) |
| §3 Message/inbox protocol (kind/to/refs/span_id) | 2 (contracts), 5 (inbox) |
| §4 Data flow goal→converge | 9 + 11 (batch), 8 (debate), gate in 11 |
| §5 Exact file structure (7 society files + modifieds + 4 tests) | 1–14 |
| §6 Error handling (worker crash, double-claim, debate livelock, runaway spawning, cost runaway, blackboard corruption) | 7 (claim race), 8 (oscillation/round cap), 9 (crash containment), 13 (budget+recursion rail), 3 (malformed tolerance) |
| §7 Testing strategy (FakeWorker injection, concurrency, claim race, disjointness, debate convergence, speaker selection, society-off invariance) | 3,4,7,8,9,11 |
| §8 Risks/sequencing/Epic-1 dependency (worktree seam, disjointness seam, span_id, remediation flip, advisory fallback) | Prerequisites section + Task 9 seam + Task 12 |
| §9 Success criteria 1–7 | 1: Task 12 note + 11; 2: Task 7 claim-race; 3: Task 4; 4: Task 8; 5: Task 13 budget; 6: Task 11; 7: Task 10 |

No gaps. Success criterion #1 (remediation ON under parallelism) is correctly deferred to the Epic-1 flip and pinned by Task 12's co-design comment + test — this matches the spec's standalone-fallback contract (Epic 5 ships advisory mode; the flip is one line once worktrees exist).

**2. Placeholder scan:** No `TODO`/`TBD`/"similar to"/"add error handling" placeholders. Every code step contains complete, runnable code. The only `_defaultRunFn`/`_defaultArbiter` indirections are deliberate injectable seams (lazily import the real `runClaude`/`consult` so tests never spawn subprocesses), each with a concrete default body — not placeholders.

**3. Type consistency:**
- `BlackboardEntry`: dataclass in `society/blackboard.py` mirrors the `contracts.py` TypedDict (same fields incl. `entry_id`, `ts_ns`, `span_id`). `append()` stamps `entry_id`+`ts_ns`; `makeEntry` returns the dataclass; `Blackboard.append` accepts dataclass-or-dict. Consistent across Tasks 2/3/5/7/8/9.
- `classifyRole(subtask, hint='') -> RoleSpec` — same signature in Task 6 def and Task 9 call (`classifyRole(st, hint=...)`).
- `RoleSpec.effort_level` used identically in Task 6 (registry), Task 7 (`_buildSpec` sets `spec["effort_level"]`), and asserted in Task 7 test.
- `WorkerAgent(role, subtask, work_dir, blackboard, state, state_lock, *, run_fn=None)` — identical constructor in Task 7 def, Task 7 tests, and Task 9 `_handleSocietyBatch`.
- `runDebate(blackboard, subtask_id, roster, *, arbiter_fn=None, max_rounds=None, goal='')` and `DebateVerdict` keys (`resolved`,`winner`,`reason`,`rounds`,`stopped_reason`) match Task 2 contract, Task 8 def, and Task 8 tests.
- `Coordinator(state, blackboard, state_lock, *, work_dir, bus=None)` consistent across Tasks 9/10/11/13; `_handleSocietyBatch(batch, parallelism, run_fn=None)` on Coordinator vs the mixin's `_handleSocietyBatch(state, ready, work_dir, parallelism, run_fn=None)` are deliberately distinct (mixin wraps coordinator) — names disambiguated by receiver, verified by Task 11 test.
- `on_append`/`attachBus` wiring: Task 3 stores `self._on_append`; Task 10 sets `self._blackboard._on_append = self._busMirror`. Consistent attribute name.

One fix applied inline during review: Task 11's mixin `_handleSocietyBatch` uses a distinct local `position2` accumulator (not reusing `_handleParallelBatch`'s in-place `position`) so the OFF-path `position` semantics are untouched — this keeps criterion #6 (byte-identical OFF path) literally true.

---

**Plan complete and saved to `docs/superpowers/plans/2026-06-30-epic5-agent-society.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session with executing-plans, batch execution with checkpoints.

**Which approach?**
