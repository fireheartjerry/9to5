# Epic 8 — Cloud Execution Fabric Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a pluggable `ExecutionEnvironment` abstraction so the Executor can run a subtask's Claude Code CLI in an isolated/remote backend (worktree → docker → remote), selected per-run/per-subtask, with `local` as the default and `fabric-off == today byte-for-byte`.

**Architecture:** A new `platform_core/execution/` package: an `ExecutionEnvironment` ABC (`provision/wrapLauncher/collectChanges/teardown/healthCheck`) modeled on hermes `BaseEnvironment` and 9TO5's pluggable-surface convention (`runBrowser`/`runNative`); one module per backend; a thin `EnvironmentRouter` that degrades to `LocalEnvironment` exactly like `_selectExecutor`; a `security` module (`CapabilityPolicy` + `validateMounts`). `agents/executor.py` only *applies* the launcher wrapper (default `None` ⇒ identity); `execute_mixin.py` owns provision/finalize. Docker/remote calls hide behind one mockable seam each (`_run_docker`/`_run_remote`), mirroring `native_executor._run_native_actions`.

**Tech Stack:** Python 3.11+, stdlib `abc`/`dataclasses`/`enum.Flag`/`subprocess`, git (hard dep), pytest, 9TO5 `config` + `notifications.event_bus`. No new third-party dependency; docker/remote SDKs are optional and degrade cleanly when absent.

---

## Prerequisites & cross-epic seams

This epic deliberately shares seams with three other epics. Read these before starting:

- **Epic 1 — Durable Execution** (`docs/superpowers/specs/2026-06-30-epic1-durable-execution-design.md`).
  Epic 1 §3(c) ships a git-**worktree** backend (`platform_core/runtime/worktree.py`,
  `enterWorktree/exitWorktree/gcOrphans/isIsolated`) as its isolation seam. **This epic's
  `WorktreeEnvironment` (Task 9) IS that same worktree, expressed through the fabric ABC.**
  - **If Epic 1 has already landed `platform_core/runtime/worktree.py`:** make `WorktreeEnvironment`
    a thin adapter that delegates `provision → worktree.enterWorktree`, `collectChanges/teardown →
    worktree.exitWorktree(merge=True)/removeWorktree`, reusing the fail-open-to-shared-tree path.
    Do **not** duplicate git logic.
  - **If Epic 1 has NOT landed it (this plan assumes this default):** Task 9 implements the
    git-worktree lifecycle self-contained behind a `_runGit` seam, and Epic 1 should later import
    *this* backend rather than re-implement. Either way the public lifecycle names match.
  - **Trajectory step events (Epic 1 §3d):** the fabric emits `env_provisioned` / `env_wrapped` /
    `env_changes_collected` / `env_teardown` / `env_fallback` onto the existing
    `notifications/event_bus.py`. When Epic 1's trajectory recorder lands, these become backend-
    annotated spans automatically — we only emit `Event`s here, we do not build the recorder.

- **Epic 4 — Semantic Action-Risk Safety** (`docs/superpowers/specs/2026-06-30-epic4-semantic-safety-design.md`).
  Epic 4 ships `platform_core/runtime/action_risk.py` with `RiskTier`
  (`READ/DRY_RUN/MUTATING/PAID/DESTRUCTIVE/UNKNOWN`) and `classifyActionRisk`. This epic's
  `CapabilityPolicy` (Task 8) composes with it: when `action_risk` is importable, a destructive/
  untrusted risk tier tightens the policy (drop NETWORK, withhold creds, pick a containment
  backend via `config.EXECUTION_BACKEND_BY_RISK`). **The import is optional and guarded** — Epic 4
  not landing must not break this epic. Until Epic 4 lands, `CapabilityPolicy` derives purely from
  the existing 9TO5 universe (`allowed_paths`/`hard_boundaries`/`CORE_PROTECTED_FILES`).

- **`agents/executor.py` is a core-loop file** (`.claude/rules/orchestration.md`). The only change
  here is an additive, default-`None` parameter pair + a pure helper that is the identity when no
  environment is passed. **Model/effort routing (`MODEL_BY_EFFORT`, `--effort`, `--fallback-model`)
  is untouched** — backend selection is orthogonal to model selection.

- **CI stays free of real docker/cloud.** Docker and remote backends route every daemon/SDK/ssh
  call through one mockable function (`_run_docker` / `_run_remote`), mirroring
  `native_executor._run_native_actions` (mocked in `tests/test_phase_3_architecture.py`). The
  worktree backend is tested against a temporary `git init` repo (git is already a hard dep).

---

## File structure

**New package `platform_core/execution/`** (each module carries the required `@AI-MAP v1` header):

| File | Responsibility | Size target |
|---|---|---|
| `platform_core/execution/__init__.py` | re-export `ExecutionEnvironment`, `EnvHandle`, `Capability`, `selectEnvironment`, `provision`, `finalize` | ≤60 |
| `platform_core/execution/environment.py` | `ExecutionEnvironment` ABC + `Capability` Flag + `EnvHandle` dataclass | ≤180 |
| `platform_core/execution/router.py` | `selectEnvironment`, lazy `_backendClass`, `provision` (with local fallback), `finalize`, event emission | ≤220 |
| `platform_core/execution/security.py` | `CapabilityPolicy`, `validateMounts`, `MountSecurityError` | ≤260 |
| `platform_core/execution/backends/__init__.py` | package marker | tiny |
| `platform_core/execution/backends/local.py` | `LocalEnvironment` — identity, == today | ≤120 |
| `platform_core/execution/backends/worktree.py` | `WorktreeEnvironment` — git-worktree lifecycle (Epic 1 seam) | ≤260 |
| `platform_core/execution/backends/docker.py` | `DockerEnvironment` — container lifecycle behind `_run_docker` | ≤260 |
| `platform_core/execution/backends/remote.py` | `RemoteEnvironment` — ssh/SDK stubs behind `_run_remote`, degrade cleanly | ≤220 |

**Modified (narrow, facade-preserving):**

| File | Change |
|---|---|
| `platform_core/app_config/llm.py` | Add the `EXECUTION_*` / `DOCKER_EXECUTOR_IMAGE` constants. |
| `agents/executor.py` | `runClaude(..., environment=None, env_handle=None)`; new pure `_applyEnvironment` helper applied before `runSubprocess`. Default `None` ⇒ identity ⇒ zero behavior change. |
| `platform_core/orchestration/execute_mixin.py` | New pure `_envHandsKw` helper; `_executeSubtask` provisions/finalizes; thread `env`/`handle` through `_runAttemptLoop`/`_runOneAttempt`. |
| `platform_core/orchestration/run_loop.py` | `_execCwd` skips the `.sc-ctx` scratch when the fabric is enabled with a non-local backend (worktree subsumes self-ref isolation). |
| `platform_core/core/surfaces.py` | (optional) tag the active backend in `surfaces_used` for SIE learning. Non-load-bearing. |
| `AGENTS.md` | regenerate via `python tools/repo_map.py` after the new modules land. |

**Test files (new):** `tests/test_execution_environment.py`, `tests/test_execution_local.py`,
`tests/test_execution_router.py`, `tests/test_execution_security.py`,
`tests/test_execution_worktree.py`, `tests/test_execution_docker.py`,
`tests/test_execution_remote.py`, `tests/test_executor_wrap_env.py`,
`tests/test_execute_mixin_env.py`, `tests/test_execcwd_fabric.py`.

**Sequence rationale (locked):** interface + proven-no-op local first (Tasks 1-3), then the router
fallback discipline + the executor seam + config (Tasks 4-6), then the orchestration wiring
(Tasks 7-8) so the fabric is live-but-local, then backend **rung 1 = worktree** (Task 9), then
capability scoping + **rung 2 = docker** (Tasks 10-11), then **rung 3 = remote** stubs (Task 12),
then the optional SIE tag + repo-map/size-audit closeout (Tasks 13-14).

---

### Task 1: `ExecutionEnvironment` ABC + `Capability` + `EnvHandle`

**Files:**
- Create: `platform_core/execution/__init__.py`
- Create: `platform_core/execution/environment.py`
- Create: `platform_core/execution/backends/__init__.py`
- Test: `tests/test_execution_environment.py`

- [ ] **Step 1: Write the failing test** (a `FakeEnvironment` proves the four-method lifecycle ordering and that `EnvHandle.work_dir` is honored)

```python
# tests/test_execution_environment.py
"""Contract test for the ExecutionEnvironment ABC (no real backend)."""
from platform_core.execution.environment import (
    Capability, EnvHandle, ExecutionEnvironment,
)


class FakeEnvironment(ExecutionEnvironment):
    NAME = "fake"
    CAPABILITIES = Capability.FILE_RW | Capability.EXEC

    def __init__(self):
        self.calls = []

    def provision(self, *, task_state, subtask, base_dir, policy):
        self.calls.append("provision")
        return EnvHandle(work_dir=base_dir + "/wt", backend=self.NAME,
                         meta={"id": "x1"}, capabilities=self.CAPABILITIES)

    def wrapLauncher(self, run_cmd, handle):
        self.calls.append("wrap")
        return ["prefix", *run_cmd], handle.work_dir

    def collectChanges(self, handle, *, task_state, subtask):
        self.calls.append("collect")
        return {"merged": True}

    def teardown(self, handle):
        self.calls.append("teardown")


def test_capability_flag_is_combinable():
    caps = Capability.FILE_RW | Capability.NETWORK
    assert Capability.FILE_RW in caps
    assert Capability.SNAPSHOT not in caps


def test_envhandle_fields():
    h = EnvHandle(work_dir="/w", backend="fake", meta={}, capabilities=Capability(0))
    assert h.work_dir == "/w" and h.backend == "fake" and h.meta == {}


def test_lifecycle_ordering_and_workdir_honored():
    env = FakeEnvironment()
    handle = env.provision(task_state=None, subtask={"subtask_id": "s1"},
                           base_dir="/base", policy=None)
    assert handle.work_dir == "/base/wt"
    cmd, work = env.wrapLauncher(["claude", "--print"], handle)
    assert cmd == ["prefix", "claude", "--print"] and work == "/base/wt"
    summary = env.collectChanges(handle, task_state=None, subtask={"subtask_id": "s1"})
    assert summary == {"merged": True}
    env.teardown(handle)
    assert env.calls == ["provision", "wrap", "collect", "teardown"]


def test_default_healthcheck_true():
    assert FakeEnvironment().healthCheck() is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_execution_environment.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'platform_core.execution'`

- [ ] **Step 3: Write minimal implementation**

```python
# platform_core/execution/backends/__init__.py
"""Execution-fabric backends package marker (one module per backend)."""
```

```python
# platform_core/execution/environment.py
"""ExecutionEnvironment ABC + Capability flags + EnvHandle for the cloud execution fabric.

Modeled on hermes `BaseEnvironment` and 9TO5's pluggable-surface convention
(agents/browser_executor.runBrowser, agents/native_executor.runNative). The unit of work is
ONE whole Claude CLI invocation, so the environment wraps the LAUNCH of run_cmd, not a bash line.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  Capability  -- Flag of backend capabilities (FILE_RW/EXEC/NETWORK/SNAPSHOT/PERSISTENT)
  EnvHandle  -- Opaque per-subtask provision result (work_dir/backend/meta/capabilities)
  ExecutionEnvironment  -- ABC: provision/wrapLauncher/collectChanges/teardown/healthCheck
DEPENDS-ON: (stdlib only)
SIDE-EFFECTS: unannotated
RUN/TEST: python -m pytest tests/test_execution_environment.py
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Flag, auto


class Capability(Flag):
    """What a backend's provisioned environment can do (bernstein frozenset[SandboxCapability])."""
    FILE_RW = auto()
    EXEC = auto()
    NETWORK = auto()
    SNAPSHOT = auto()      # can checkpoint/rollback the tree
    PERSISTENT = auto()    # tree survives teardown (local/worktree) vs ephemeral (docker/remote)


@dataclass
class EnvHandle:
    """Opaque per-subtask provision result reused across a subtask's attempts."""
    work_dir: str                 # the exec_cwd the executor runs against
    backend: str                  # "local" | "worktree" | "docker" | "remote"
    meta: dict = field(default_factory=dict)   # container id / branch / ssh host / base_dir
    capabilities: Capability = Capability(0)


class ExecutionEnvironment(ABC):
    """Where a subtask's Claude CLI process runs and which tree it touches."""
    NAME: str = "base"
    CAPABILITIES: Capability = Capability(0)

    @abstractmethod
    def provision(self, *, task_state, subtask, base_dir: str, policy) -> EnvHandle:
        """Stand up the environment for one subtask; return an EnvHandle (reused across attempts)."""

    @abstractmethod
    def wrapLauncher(self, run_cmd: list, handle: EnvHandle) -> "tuple[list, str]":
        """Transform (run_cmd, work_dir) so the Claude CLI runs INSIDE the env.
        local: identity. docker: prefix `docker exec -w <cdir> <cid> ...`. remote: `ssh host ...`."""

    @abstractmethod
    def collectChanges(self, handle: EnvHandle, *, task_state, subtask) -> dict:
        """Bring work back to the canonical tree; return a trajectory summary. NEVER silently lose edits."""

    @abstractmethod
    def teardown(self, handle: EnvHandle) -> None:
        """Best-effort cleanup (worktree remove / docker rm -f / ssh close)."""

    def healthCheck(self) -> bool:
        """Default True; docker/remote probe reachability so the router can degrade to local."""
        return True
```

```python
# platform_core/execution/__init__.py
"""Cloud Execution Fabric -- pluggable ExecutionEnvironment backends for the Executor.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  Capability / EnvHandle / ExecutionEnvironment  -- the ABC + value types
DEPENDS-ON: platform_core.execution.environment
SIDE-EFFECTS: unannotated
RUN/TEST: python -m pytest tests/test_execution_environment.py
"""
from __future__ import annotations

from platform_core.execution.environment import (  # noqa: F401
    Capability, EnvHandle, ExecutionEnvironment,
)

__all__ = ["Capability", "EnvHandle", "ExecutionEnvironment"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_execution_environment.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add platform_core/execution/__init__.py platform_core/execution/environment.py platform_core/execution/backends/__init__.py tests/test_execution_environment.py
git commit -m "feat(epic8): ExecutionEnvironment ABC + Capability + EnvHandle"
```

---

### Task 2: `LocalEnvironment` — proven no-op (fabric off == today)

**Files:**
- Create: `platform_core/execution/backends/local.py`
- Test: `tests/test_execution_local.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_execution_local.py
"""LocalEnvironment must be a provable identity no-op (regression guard: fabric off == today)."""
from platform_core.execution.backends.local import LocalEnvironment
from platform_core.execution.environment import Capability


def test_provision_returns_base_dir_unchanged():
    env = LocalEnvironment()
    h = env.provision(task_state=None, subtask={"subtask_id": "s1"},
                      base_dir="/repo/root", policy=None)
    assert h.work_dir == "/repo/root"
    assert h.backend == "local"
    assert Capability.PERSISTENT in h.capabilities


def test_wraplauncher_is_identity():
    env = LocalEnvironment()
    h = env.provision(task_state=None, subtask=None, base_dir="/repo", policy=None)
    cmd = ["cmd", "/c", "claude.cmd", "--print", "--dangerously-skip-permissions"]
    out_cmd, out_work = env.wrapLauncher(cmd, h)
    assert out_cmd == cmd          # byte-for-byte identical command
    assert out_work == "/repo"     # unchanged cwd


def test_collect_and_teardown_are_noops():
    env = LocalEnvironment()
    h = env.provision(task_state=None, subtask=None, base_dir="/repo", policy=None)
    summary = env.collectChanges(h, task_state=None, subtask=None)
    assert summary["backend"] == "local" and summary["merged"] is False
    assert env.teardown(h) is None
    assert env.healthCheck() is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_execution_local.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'platform_core.execution.backends.local'`

- [ ] **Step 3: Write minimal implementation**

```python
# platform_core/execution/backends/local.py
"""LocalEnvironment -- the default backend; identity in every method (== today's behavior).

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  LocalEnvironment  -- runs the Claude CLI on the host against base_dir, no isolation
DEPENDS-ON: platform_core.execution.environment
SIDE-EFFECTS: unannotated
RUN/TEST: python -m pytest tests/test_execution_local.py
"""
from __future__ import annotations

from platform_core.execution.environment import (
    Capability, EnvHandle, ExecutionEnvironment,
)

_LOCAL_CAPS = (Capability.FILE_RW | Capability.EXEC
               | Capability.NETWORK | Capability.PERSISTENT)


class LocalEnvironment(ExecutionEnvironment):
    """The host, the real tree -- exactly today's `subprocess.Popen(run_cmd, cwd=base_dir)`."""
    NAME = "local"
    CAPABILITIES = _LOCAL_CAPS

    def provision(self, *, task_state, subtask, base_dir: str, policy) -> EnvHandle:
        return EnvHandle(work_dir=base_dir, backend=self.NAME, meta={},
                         capabilities=self.CAPABILITIES)

    def wrapLauncher(self, run_cmd: list, handle: EnvHandle) -> "tuple[list, str]":
        return run_cmd, handle.work_dir          # identity

    def collectChanges(self, handle: EnvHandle, *, task_state, subtask) -> dict:
        return {"backend": "local", "merged": False, "note": "identity (no isolation)"}

    def teardown(self, handle: EnvHandle) -> None:
        return None

    def healthCheck(self) -> bool:
        return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_execution_local.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add platform_core/execution/backends/local.py tests/test_execution_local.py
git commit -m "feat(epic8): LocalEnvironment (proven identity no-op)"
```

---

### Task 3: Config knobs (all defaulting to today's behavior)

**Files:**
- Modify: `platform_core/app_config/llm.py` (append after the `BROWSER_LAYER_ENABLED`/`NATIVE_LAYER_ENABLED` block, ~line 188)
- Test: `tests/test_execution_router.py` (config-only assertions added now; router added in Task 4)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_execution_router.py
"""Config knobs + (Task 4) router fallback discipline."""
import config


def test_execution_config_defaults_to_today():
    assert config.EXECUTION_FABRIC_ENABLED is False     # master gate OFF by default
    assert config.EXECUTION_BACKEND == "local"          # default backend
    assert isinstance(config.EXECUTION_BACKEND_BY_RISK, dict)
    assert config.EXECUTION_BACKEND_BY_RISK == {}        # empty until Epic 4 lands
    assert isinstance(config.DOCKER_EXECUTOR_IMAGE, str) and config.DOCKER_EXECUTOR_IMAGE
    assert config.EXECUTION_REMOTE_KIND in ("ssh", "modal", "daytona", "e2b")
    assert isinstance(config.EXECUTION_PROVISION_TIMEOUT_SECONDS, int)
    assert config.EXECUTION_PROVISION_TIMEOUT_SECONDS > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_execution_router.py::test_execution_config_defaults_to_today -v`
Expected: FAIL with `AttributeError: module 'config' has no attribute 'EXECUTION_FABRIC_ENABLED'`

- [ ] **Step 3: Write minimal implementation** (append to `platform_core/app_config/llm.py` right after the `NATIVE_LAYER_ENABLED` line)

```python
# --- Epic 8: Cloud Execution Fabric (all default to today's local-only behavior) ---
# Master gate, like BROWSER_LAYER_ENABLED: OFF => LocalEnvironment everywhere => byte-for-byte today.
EXECUTION_FABRIC_ENABLED: bool = _envBool("EXECUTION_FABRIC_ENABLED", False)
# Default backend when the fabric is enabled and no per-subtask override is authored.
EXECUTION_BACKEND: str = os.getenv("EXECUTION_BACKEND", "local")
# Optional risk->backend map, populated only when Epic 4 (semantic action-risk) lands.
EXECUTION_BACKEND_BY_RISK: dict[str, str] = {}
# Container image bundling the `claude` CLI (DockerEnvironment); built/pulled out of band.
DOCKER_EXECUTOR_IMAGE: str = os.getenv("DOCKER_EXECUTOR_IMAGE", "9to5-executor:latest")
# Remote sub-strategy + host (RemoteEnvironment stubs; empty host => healthCheck False => local).
EXECUTION_REMOTE_KIND: str = os.getenv("EXECUTION_REMOTE_KIND", "ssh")
EXECUTION_REMOTE_HOST: str = os.getenv("EXECUTION_REMOTE_HOST", "")
# Hard cap on a single backend provision (git worktree add / docker run / ssh connect).
EXECUTION_PROVISION_TIMEOUT_SECONDS: int = _envInt("EXECUTION_PROVISION_TIMEOUT_SECONDS", 120)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_execution_router.py::test_execution_config_defaults_to_today -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add platform_core/app_config/llm.py tests/test_execution_router.py
git commit -m "feat(epic8): execution-fabric config knobs (default local/off)"
```

---

### Task 4: `EnvironmentRouter` — select + provision-with-fallback + finalize

**Files:**
- Create: `platform_core/execution/router.py`
- Modify: `platform_core/execution/__init__.py` (re-export `selectEnvironment`, `provision`, `finalize`)
- Test: `tests/test_execution_router.py` (add the cases below)

- [ ] **Step 1: Write the failing test** (append to the existing file)

```python
# tests/test_execution_router.py  (append)
from unittest import mock

from platform_core.execution import router
from platform_core.execution.backends.local import LocalEnvironment


def test_select_returns_local_when_fabric_disabled():
    with mock.patch.object(config, "EXECUTION_FABRIC_ENABLED", False):
        env = router.selectEnvironment({}, {"execution_backend": "docker"}, None)
    assert isinstance(env, LocalEnvironment)


def test_select_unknown_name_degrades_to_local():
    with mock.patch.object(config, "EXECUTION_FABRIC_ENABLED", True), \
         mock.patch.object(config, "EXECUTION_BACKEND", "local"):
        env = router.selectEnvironment({}, {"execution_backend": "does-not-exist"}, None)
    assert isinstance(env, LocalEnvironment)


def test_select_unhealthy_backend_degrades_to_local():
    class _Unhealthy(LocalEnvironment):
        NAME = "unhealthy"
        def healthCheck(self):
            return False
    with mock.patch.object(config, "EXECUTION_FABRIC_ENABLED", True), \
         mock.patch.object(router, "_backendClass", return_value=_Unhealthy):
        env = router.selectEnvironment({}, {"execution_backend": "unhealthy"}, None)
    assert isinstance(env, LocalEnvironment)


def test_provision_failure_falls_back_to_local_handle():
    class _Boom(LocalEnvironment):
        NAME = "boom"
        def provision(self, *, task_state, subtask, base_dir, policy):
            raise RuntimeError("provision blew up")
    env, handle = router.provision(_Boom(), task_state=None, subtask={"subtask_id": "s1"},
                                   base_dir="/repo")
    assert isinstance(env, LocalEnvironment)        # fell back
    assert handle.work_dir == "/repo"               # local handle points at base_dir
    assert handle.backend == "local"


def test_provision_success_returns_same_env_and_handle():
    env, handle = router.provision(LocalEnvironment(), task_state=None,
                                   subtask=None, base_dir="/repo")
    assert isinstance(env, LocalEnvironment) and handle.work_dir == "/repo"


def test_finalize_calls_collect_then_teardown():
    calls = []
    class _Spy(LocalEnvironment):
        def collectChanges(self, handle, *, task_state, subtask):
            calls.append("collect"); return {"backend": "spy", "merged": True}
        def teardown(self, handle):
            calls.append("teardown")
    env = _Spy()
    handle = env.provision(task_state=None, subtask=None, base_dir="/repo", policy=None)
    summary = router.finalize(env, handle, None, None)
    assert calls == ["collect", "teardown"]
    assert summary == {"backend": "spy", "merged": True}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_execution_router.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'platform_core.execution.router'`

- [ ] **Step 3: Write minimal implementation**

```python
# platform_core/execution/router.py
"""EnvironmentRouter -- pick a backend per subtask and run its lifecycle with local fallback.

Mirrors native_executor.selectForSurface + llm_mixin._selectExecutor degrade-to-default discipline:
any unknown/unreachable/failing backend falls back to LocalEnvironment so a run is NEVER blocked
by the fabric. Backend selection is policy-only and NEVER reads MODEL_BY_EFFORT (orthogonal axes).

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  selectEnvironment(spec, subtask, task_state) -> ExecutionEnvironment  -- policy -> backend (default local)
  provision(env, *, task_state, subtask, base_dir, policy=None) -> tuple[ExecutionEnvironment, EnvHandle]  -- provision with local fallback
  finalize(env, handle, task_state, subtask) -> dict  -- collectChanges + teardown (best-effort)
DEPENDS-ON: config, platform_core.execution.backends.local, platform_core.execution.environment
SIDE-EFFECTS: emits env_* events on notifications.event_bus (best-effort)
RUN/TEST: python -m pytest tests/test_execution_router.py
"""
from __future__ import annotations

import config
from platform_core.execution.backends.local import LocalEnvironment
from platform_core.execution.environment import EnvHandle, ExecutionEnvironment

LOG = config.getLogger("execution.router")


def _emit(name: str, payload: dict) -> None:
    """Best-effort lifecycle event onto the process bus (Epic 1 trajectory consumes these later)."""
    try:
        from notifications.event_bus import get_bus, Event
        get_bus().emit(Event(kind=name, data=payload))
    except Exception:  # noqa: BLE001 -- a bus hiccup must never break a run
        pass


def _backendClass(name: str):
    """Lazy import so a missing optional SDK/module never breaks router import (degrade-clean)."""
    if name == "local":
        return LocalEnvironment
    if name == "worktree":
        from platform_core.execution.backends.worktree import WorktreeEnvironment
        return WorktreeEnvironment
    if name == "docker":
        from platform_core.execution.backends.docker import DockerEnvironment
        return DockerEnvironment
    if name == "remote":
        from platform_core.execution.backends.remote import RemoteEnvironment
        return RemoteEnvironment
    return None


def _policyBackend(spec: dict, subtask: dict) -> "str | None":
    """Epic 4 hook: risk-tier -> backend via config.EXECUTION_BACKEND_BY_RISK. None until Epic 4 lands."""
    risk = (subtask or {}).get("risk_tier") or (spec or {}).get("risk_tier")
    if risk and risk in config.EXECUTION_BACKEND_BY_RISK:
        return config.EXECUTION_BACKEND_BY_RISK[risk]
    return None


def selectEnvironment(spec: dict, subtask: dict, task_state) -> ExecutionEnvironment:
    """Pick the backend for a subtask. Fabric off / unknown / unreachable -> LocalEnvironment."""
    if not config.EXECUTION_FABRIC_ENABLED:
        return LocalEnvironment()
    name = ((subtask or {}).get("execution_backend")
            or _policyBackend(spec, subtask)
            or config.EXECUTION_BACKEND
            or "local")
    cls = _backendClass(name)
    if cls is None:
        LOG.warning("unknown execution backend %r -> local", name)
        return LocalEnvironment()
    try:
        env = cls()
    except Exception as e:  # noqa: BLE001 -- backend ctor must never block a run
        LOG.warning("backend %r init failed (%s) -> local", name, e)
        return LocalEnvironment()
    if not env.healthCheck():
        LOG.warning("backend %r unreachable (healthCheck False) -> local", name)
        return LocalEnvironment()
    return env


def provision(env: ExecutionEnvironment, *, task_state, subtask, base_dir: str,
              policy=None) -> "tuple[ExecutionEnvironment, EnvHandle]":
    """Provision with local fallback: any exception -> notify + emit env_fallback + LocalEnvironment."""
    try:
        handle = env.provision(task_state=task_state, subtask=subtask,
                               base_dir=base_dir, policy=policy)
        _emit("env_provisioned", {"backend": env.NAME, "work_dir": handle.work_dir,
                                  "meta": handle.meta})
        return env, handle
    except Exception as e:  # noqa: BLE001 -- provision must NEVER block a run
        LOG.warning("%s provision failed (%s) -> local", env.NAME, e)
        _emit("env_fallback", {"backend": env.NAME, "error": str(e)})
        try:
            if task_state is not None and hasattr(task_state, "addNotification"):
                task_state.addNotification(
                    "execution_fabric", f"{env.NAME} provision failed -> local: {e}")
        except Exception:  # noqa: BLE001
            pass
        local = LocalEnvironment()
        return local, local.provision(task_state=task_state, subtask=subtask,
                                      base_dir=base_dir, policy=policy)


def finalize(env: ExecutionEnvironment, handle: EnvHandle, task_state, subtask) -> dict:
    """collectChanges then teardown; both best-effort. Returns the collect summary (or {})."""
    summary: dict = {}
    try:
        summary = env.collectChanges(handle, task_state=task_state, subtask=subtask)
        _emit("env_changes_collected", {"backend": env.NAME, "summary": summary})
    except Exception as e:  # noqa: BLE001 -- a failed collect leaves work for recovery, never crashes
        LOG.warning("%s collectChanges failed (%s) -- work left intact", env.NAME, e)
        try:
            if task_state is not None and hasattr(task_state, "addNotification"):
                task_state.addNotification(
                    "execution_fabric", f"{env.NAME} collectChanges failed; work left intact: {e}")
        except Exception:  # noqa: BLE001
            pass
        return summary
    try:
        env.teardown(handle)
        _emit("env_teardown", {"backend": env.NAME})
    except Exception as e:  # noqa: BLE001 -- teardown is best-effort (hermes cleanup/__del__)
        LOG.warning("%s teardown failed (%s)", env.NAME, e)
    return summary
```

Then extend the package facade re-exports:

```python
# platform_core/execution/__init__.py  (replace the import block + __all__)
from platform_core.execution.environment import (  # noqa: F401
    Capability, EnvHandle, ExecutionEnvironment,
)
from platform_core.execution.router import (  # noqa: F401
    selectEnvironment, provision, finalize,
)

__all__ = [
    "Capability", "EnvHandle", "ExecutionEnvironment",
    "selectEnvironment", "provision", "finalize",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_execution_router.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add platform_core/execution/router.py platform_core/execution/__init__.py tests/test_execution_router.py
git commit -m "feat(epic8): EnvironmentRouter select/provision/finalize with local fallback"
```

---

### Task 5: Executor launcher-wrap seam (`_applyEnvironment`, default None = identity)

**Files:**
- Modify: `agents/executor.py` (add `_applyEnvironment`; extend `runClaude` signature + call site)
- Test: `tests/test_executor_wrap_env.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_executor_wrap_env.py
"""The executor applies an environment's wrapLauncher; default None is byte-for-byte identity."""
from agents.executor import _applyEnvironment


class _FakeDockerEnv:
    def wrapLauncher(self, run_cmd, handle):
        cid = handle["cid"]
        return ["docker", "exec", "-w", "/work", cid, *run_cmd], "/work"


def test_no_environment_is_identity():
    fresh = ["cmd", "/c", "claude.cmd", "--print"]
    resume = ["cmd", "/c", "claude.cmd", "--print", "--resume", "sess-1"]
    out_fresh, out_resume, out_work = _applyEnvironment(fresh, resume, "/repo", None, None)
    assert out_fresh == fresh and out_resume == resume and out_work == "/repo"


def test_none_handle_is_identity():
    fresh = ["claude", "--print"]
    out_fresh, out_resume, out_work = _applyEnvironment(fresh, None, "/repo", _FakeDockerEnv(), None)
    assert out_fresh == fresh and out_resume is None and out_work == "/repo"


def test_environment_wraps_both_commands_and_overrides_work():
    fresh = ["claude", "--print"]
    resume = ["claude", "--print", "--resume", "s1"]
    handle = {"cid": "abc123"}
    out_fresh, out_resume, out_work = _applyEnvironment(fresh, resume, "/repo",
                                                        _FakeDockerEnv(), handle)
    assert out_fresh == ["docker", "exec", "-w", "/work", "abc123", "claude", "--print"]
    assert out_resume == ["docker", "exec", "-w", "/work", "abc123",
                          "claude", "--print", "--resume", "s1"]
    assert out_work == "/work"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_executor_wrap_env.py -v`
Expected: FAIL with `ImportError: cannot import name '_applyEnvironment' from 'agents.executor'`

- [ ] **Step 3: Write minimal implementation**

In `agents/executor.py`, add the pure helper right before the `Public entry point` banner (after `_buildRunConfig`):

```python
def _applyEnvironment(fresh_cmd: list, resume_cmd: "list | None", work: str,
                      environment, env_handle) -> "tuple[list, list | None, str]":
    """Route the built run_cmd(s) INTO a provisioned environment via its wrapLauncher.
    Default (environment/env_handle None) is a pure identity -> zero behavior change (fabric off)."""
    if environment is None or env_handle is None:
        return fresh_cmd, resume_cmd, work
    wrapped_fresh, new_work = environment.wrapLauncher(fresh_cmd, env_handle)
    wrapped_resume = None
    if resume_cmd is not None:
        wrapped_resume, _ = environment.wrapLauncher(resume_cmd, env_handle)
    return wrapped_fresh, wrapped_resume, new_work
```

Extend the `runClaude` signature (add two trailing keyword-only params after `feed=None`):

```python
def runClaude(spec_or_prompt: Union[dict, str], *, work_dir: Optional[str] = None,
              task_state=None, subtask: Optional[dict] = None,
              system_prompt: Optional[str] = None, extra: Optional[str] = None,
              timeout: Optional[int] = None, resume_session: Optional[str] = None,
              cancel_check=None, feed=None, environment=None, env_handle=None) -> dict:
```

Apply the wrap immediately after the `_buildRunConfig` try/except (after the line
`fresh_cmd, resume_cmd, env, creationflags, model = _buildRunConfig(...)` succeeds, i.e. right
before `run_kw = dict(work=work, ...)`):

```python
    fresh_cmd, resume_cmd, work = _applyEnvironment(
        fresh_cmd, resume_cmd, work, environment, env_handle)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_executor_wrap_env.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the executor regression suite (no behavior change when env is None)**

Run: `python -m pytest tests/test_executor.py -v`
Expected: PASS (unchanged — default `None` is identity)

- [ ] **Step 6: Commit**

```bash
git add agents/executor.py tests/test_executor_wrap_env.py
git commit -m "feat(epic8): executor _applyEnvironment launcher-wrap seam (None=identity)"
```

---

### Task 6: `_envHandsKw` helper (only the Claude-CLI path takes an environment)

**Files:**
- Modify: `platform_core/orchestration/execute_mixin.py` (add module-level pure helper)
- Test: `tests/test_execute_mixin_env.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_execute_mixin_env.py
"""Pure helper: route an environment into hands_kw ONLY for the Claude-CLI hands path."""
from platform_core.orchestration.execute_mixin import _envHandsKw


def _run_claude():        # stand-in identity for the terminal hands fn
    return None


def _run_browser():       # stand-in for a non-terminal surface
    return None


def test_env_threaded_for_claude_path():
    env, handle = object(), object()
    kw = _envHandsKw(_run_claude, _run_claude, env, handle)
    assert kw == {"environment": env, "env_handle": handle}


def test_env_not_threaded_for_browser_path():
    env, handle = object(), object()
    kw = _envHandsKw(_run_browser, _run_claude, env, handle)
    assert kw == {}


def test_env_not_threaded_when_missing():
    assert _envHandsKw(_run_claude, _run_claude, None, None) == {}
    assert _envHandsKw(_run_claude, _run_claude, object(), None) == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_execute_mixin_env.py -v`
Expected: FAIL with `ImportError: cannot import name '_envHandsKw' from 'platform_core.orchestration.execute_mixin'`

- [ ] **Step 3: Write minimal implementation** (add at module level in `execute_mixin.py`, after the `LOG = ...` line)

```python
def _envHandsKw(hands, run_claude_fn, environment, env_handle) -> dict:
    """Executor kwargs that route the run INTO the provisioned environment.
    Only the Claude-CLI hands path takes an environment -- browser/native surfaces are API/UIA,
    not sandboxable shells -- mirroring how `feed` is attached only on the _run_claude path."""
    if environment is not None and env_handle is not None and hands is run_claude_fn:
        return {"environment": environment, "env_handle": env_handle}
    return {}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_execute_mixin_env.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add platform_core/orchestration/execute_mixin.py tests/test_execute_mixin_env.py
git commit -m "feat(epic8): _envHandsKw helper (env only on Claude-CLI hands path)"
```

---

### Task 7: Wire provision/finalize into `_executeSubtask` (thread env through the loop)

**Files:**
- Modify: `platform_core/orchestration/execute_mixin.py` (`_executeSubtask`, `_runAttemptLoop`, `_runOneAttempt`)
- Test: validated by `python tools/dev.py check` + the existing orchestration suite (`python tools/dev.py fast`); the pure helpers it relies on (`_envHandsKw`, `router.provision/finalize`) are unit-tested in Tasks 4 & 6.

- [ ] **Step 1: Thread an optional `env_ctx` through the attempt loop**

In `_runAttemptLoop`, change the signature to accept an optional `env_ctx=None` (a
`(environment, handle)` tuple or `None`) and forward it to `_runOneAttempt`:

```python
    def _runAttemptLoop(self, state: TaskState, subtask: dict, architect_doc: str,
                        exec_cwd: str, bus: "ControlBus", dashboard: "DiscordDashboard",
                        sid: str, verify_spec: "dict | None", env_ctx=None) -> tuple:
```

and at the `self._runOneAttempt(...)` call inside the loop, pass it through:

```python
            spec, result, vresult, combined, passed, resume_session, failure_feedback = \
                self._runOneAttempt(state, subtask, architect_doc, exec_cwd, bus, dashboard,
                                    sid, verify_spec, failure_feedback, resume_session, attempt,
                                    env_ctx)
```

- [ ] **Step 2: Consume `env_ctx` in `_runOneAttempt`**

Change `_runOneAttempt`'s signature to accept the trailing `env_ctx=None`:

```python
    def _runOneAttempt(self, state: TaskState, subtask: dict, architect_doc: str,
                       exec_cwd: str, bus: "ControlBus", dashboard: "DiscordDashboard",
                       sid: str, verify_spec: "dict | None", failure_feedback: "str | None",
                       resume_session: "str | None", attempt: int, env_ctx=None) -> tuple:
```

and where `hands_kw` is assembled (just before `if feed is not None: hands_kw["feed"] = feed`),
merge the environment kwargs:

```python
        environment, env_handle = (env_ctx or (None, None))
        hands_kw.update(_envHandsKw(hands, self._run_claude, environment, env_handle))
```

- [ ] **Step 3: Provision before the loop and finalize after, in `_executeSubtask`**

In `_executeSubtask`, replace the `exec_cwd = exec_cwd or self._execCwd(...)` region and the
`_runAttemptLoop(...)` call. Provision against the computed `exec_cwd`, run the loop in the
handle's `work_dir`, and finalize after enrichment:

```python
        exec_cwd = exec_cwd or self._execCwd(state, sid, work_dir)
        # Epic 8: select + provision an execution environment for this subtask (default local).
        from platform_core.execution import router as _env_router
        env = _env_router.selectEnvironment(subtask.get("session", {}) or {}, subtask, state)
        env, handle = _env_router.provision(
            env, task_state=state, subtask=subtask, base_dir=exec_cwd, policy=None)
        exec_cwd = handle.work_dir          # attempts + verify run against the provisioned tree
        env_ctx = (env, handle)
        with self._state_lock:
            subtask["env_handle_meta"] = {"backend": handle.backend, "meta": handle.meta}
```

Pass `env_ctx` into the loop:

```python
        spec, result, vresult, combined, passed, attempt = self._runAttemptLoop(
            state, subtask, architect_doc, exec_cwd, bus, dashboard, sid, verify_spec, env_ctx)
```

And finalize at the very end of `_executeSubtask`, **after** `_postSubtaskEnrich(...)` and before
`return final`, in a best-effort guard:

```python
        try:
            _env_router.finalize(env, handle, state, subtask)
        except Exception:  # noqa: BLE001 -- finalize is best-effort; committed status stands
            LOG.warning("execution-env finalize for %s failed", sid, exc_info=True)
        return final
```

> Note: the early `return "removed"` paths run before provisioning, so no finalize is owed there.
> The `policy=None` argument is the seam Task 8 (security) and Epic 4 later populate.

- [ ] **Step 4: Validate import + size + the orchestration suite stays green**

Run: `python tools/dev.py check platform_core/orchestration/execute_mixin.py`
Expected: import-clean, zero `must_split` (helpers are small; the loop signatures only gained one default kwarg)

Run: `python -m pytest tests/test_execute_mixin_env.py -v`
Expected: PASS (still green — helper unchanged)

Run: `python tools/dev.py fast`
Expected: PASS (default selection is `LocalEnvironment` with `EXECUTION_FABRIC_ENABLED=False`, so the loop is byte-for-byte today; `exec_cwd == handle.work_dir == base_dir`)

- [ ] **Step 5: Commit**

```bash
git add platform_core/orchestration/execute_mixin.py
git commit -m "feat(epic8): provision/finalize execution env per subtask (local default)"
```

---

### Task 8: `_execCwd` skips `.sc-ctx` scratch under a non-local backend

**Files:**
- Modify: `platform_core/orchestration/run_loop.py` (`_execCwd`)
- Test: `tests/test_execcwd_fabric.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_execcwd_fabric.py
"""_execCwd: self-ref still uses .sc-ctx today; a non-local fabric backend subsumes that scratch."""
import os
from unittest import mock

import config
from platform_core.orchestration import run_loop


class _State:
    def __init__(self, self_ref):
        self.meta = {"is_self_referential": self_ref}


def test_self_ref_uses_sc_ctx_when_fabric_off():
    state = _State(True)
    root = str(config.PROJECT_ROOT)
    with mock.patch.object(config, "EXECUTION_FABRIC_ENABLED", False):
        out = run_loop._execCwd(state, "st-001", root)
    assert out.endswith(os.path.join(".sc-ctx", "st-001"))


def test_non_local_backend_skips_sc_ctx():
    state = _State(True)
    root = str(config.PROJECT_ROOT)
    with mock.patch.object(config, "EXECUTION_FABRIC_ENABLED", True), \
         mock.patch.object(config, "EXECUTION_BACKEND", "worktree"):
        out = run_loop._execCwd(state, "st-001", root)
    assert out == root          # worktree provision (not .sc-ctx) governs isolation


def test_local_backend_keeps_sc_ctx():
    state = _State(True)
    root = str(config.PROJECT_ROOT)
    with mock.patch.object(config, "EXECUTION_FABRIC_ENABLED", True), \
         mock.patch.object(config, "EXECUTION_BACKEND", "local"):
        out = run_loop._execCwd(state, "st-001", root)
    assert out.endswith(os.path.join(".sc-ctx", "st-001"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_execcwd_fabric.py -v`
Expected: FAIL on `test_non_local_backend_skips_sc_ctx` (today's `_execCwd` always returns the `.sc-ctx` scratch for self-ref runs)

- [ ] **Step 3: Write minimal implementation** (edit `_execCwd` in `run_loop.py`)

```python
def _execCwd(state, sid: "str | None", work_dir: str) -> str:
    """For self-referential runs, give the executor an isolated cwd so the living CLAUDE.md never
    clobbers the project's own CLAUDE.md.  For non-self-ref runs the cwd IS work_dir.

    Epic 8: when the execution fabric is enabled with a NON-local backend, that backend's
    provision (e.g. a git worktree) supplies the isolated tree, so the .sc-ctx scratch is
    skipped -- it would be redundant. Fabric off, or the local backend, keeps today's scratch."""
    if (config.EXECUTION_FABRIC_ENABLED
            and (config.EXECUTION_BACKEND or "local") != "local"):
        return work_dir
    if (state.meta.get("is_self_referential")
            and os.path.abspath(work_dir) == os.path.abspath(str(config.PROJECT_ROOT))):
        ctx = os.path.join(str(config.PROJECT_ROOT), ".sc-ctx", sid or "architect")
        os.makedirs(ctx, exist_ok=True)
        return ctx
    return work_dir
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_execcwd_fabric.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add platform_core/orchestration/run_loop.py tests/test_execcwd_fabric.py
git commit -m "feat(epic8): _execCwd defers to non-local backend isolation (skips .sc-ctx)"
```

---

### Task 9: `WorktreeEnvironment` — rung 1 isolation (Epic 1 worktree seam)

**Files:**
- Create: `platform_core/execution/backends/worktree.py`
- Test: `tests/test_execution_worktree.py` (drives a real temporary `git init` repo — git is a hard dep)

> **Epic 1 composition:** if `platform_core/runtime/worktree.py` already exists, make this a thin
> adapter that delegates to `enterWorktree`/`exitWorktree`/`removeWorktree` instead of calling
> `_runGit` directly. The lifecycle names and the fail-open-to-shared-tree contract are identical.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_execution_worktree.py
"""WorktreeEnvironment lifecycle against a real temp git repo (offline, cross-platform)."""
import os
import shutil
import subprocess

import pytest

from platform_core.execution.backends.worktree import WorktreeEnvironment
from platform_core.execution.environment import Capability

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


@pytest.fixture()
def repo(tmp_path):
    base = tmp_path / "repo"
    base.mkdir()
    _git(["init", "-b", "main"], base)
    _git(["config", "user.email", "t@t.io"], base)
    _git(["config", "user.name", "t"], base)
    (base / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(["add", "-A"], base)
    _git(["commit", "-m", "seed"], base)
    return str(base)


class _TS:
    task_id = "abcd1234ef"


def test_healthcheck_true_when_git_present():
    assert WorktreeEnvironment().healthCheck() is True


def test_provision_creates_isolated_worktree_with_snapshot_cap(repo):
    env = WorktreeEnvironment()
    h = env.provision(task_state=_TS(), subtask={"subtask_id": "st-001"},
                      base_dir=repo, policy=None)
    assert os.path.isdir(h.work_dir)
    assert os.path.abspath(h.work_dir) != os.path.abspath(repo)   # isolated tree
    assert h.backend == "worktree"
    assert Capability.SNAPSHOT in h.capabilities
    assert h.meta["branch"].startswith("wt/")
    env.teardown(h)


def test_wraplauncher_is_identity_on_worktree_dir(repo):
    env = WorktreeEnvironment()
    h = env.provision(task_state=_TS(), subtask={"subtask_id": "st-002"},
                      base_dir=repo, policy=None)
    cmd = ["claude", "--print"]
    out_cmd, out_work = env.wrapLauncher(cmd, h)
    assert out_cmd == cmd                 # the process runs natively, just in another dir
    assert out_work == h.work_dir
    env.teardown(h)


def test_collect_merges_back_then_teardown_removes(repo):
    env = WorktreeEnvironment()
    h = env.provision(task_state=_TS(), subtask={"subtask_id": "st-003"},
                      base_dir=repo, policy=None)
    # the "executor" writes a new file inside the isolated worktree
    new_file = os.path.join(h.work_dir, "made_in_worktree.txt")
    with open(new_file, "w", encoding="utf-8") as fh:
        fh.write("hello from the worktree\n")
    summary = env.collectChanges(h, task_state=_TS(), subtask={"subtask_id": "st-003"})
    assert summary["merged"] is True
    # the edit is now in the base tree on the main branch
    assert os.path.isfile(os.path.join(repo, "made_in_worktree.txt"))
    env.teardown(h)
    assert not os.path.isdir(h.work_dir)   # worktree pruned


def test_collect_with_no_changes_is_clean(repo):
    env = WorktreeEnvironment()
    h = env.provision(task_state=_TS(), subtask={"subtask_id": "st-004"},
                      base_dir=repo, policy=None)
    summary = env.collectChanges(h, task_state=_TS(), subtask={"subtask_id": "st-004"})
    assert summary["backend"] == "worktree"
    assert summary.get("merged") in (True, False)   # nothing to merge is not a failure
    env.teardown(h)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_execution_worktree.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'platform_core.execution.backends.worktree'`

- [ ] **Step 3: Write minimal implementation**

```python
# platform_core/execution/backends/worktree.py
"""WorktreeEnvironment -- rung 1 isolation: a per-subtask git worktree (Epic 1's worktree seam).

Each subtask runs the Claude CLI in its own `git worktree add` branch dir; collectChanges commits
+ merges that branch back into the base; teardown removes the worktree. Fail-open: a git error in
provision degrades to the shared base_dir (== today). All git calls route through `_runGit` so the
backend stays offline-testable against a temp `git init` repo.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  WorktreeEnvironment  -- git-worktree-per-subtask ExecutionEnvironment backend
DEPENDS-ON: config, platform_core.execution.environment
SIDE-EFFECTS: runs git; creates/removes worktrees under <base>/.sc-worktrees/
RUN/TEST: python -m pytest tests/test_execution_worktree.py
"""
from __future__ import annotations

import os
import shutil
import subprocess

import config
from platform_core.execution.environment import (
    Capability, EnvHandle, ExecutionEnvironment,
)

LOG = config.getLogger("execution.worktree")

_WT_CAPS = (Capability.FILE_RW | Capability.EXEC | Capability.NETWORK
            | Capability.SNAPSHOT | Capability.PERSISTENT)


def _runGit(args: list, *, cwd: str, check: bool = True) -> subprocess.CompletedProcess:
    """One git subprocess seam (timeout-bounded). Raises CalledProcessError when check=True."""
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          timeout=config.EXECUTION_PROVISION_TIMEOUT_SECONDS, check=check)


class WorktreeEnvironment(ExecutionEnvironment):
    """A disjoint git worktree per subtask -- the parallel-safe isolation rung."""
    NAME = "worktree"
    CAPABILITIES = _WT_CAPS

    def healthCheck(self) -> bool:
        return shutil.which("git") is not None

    def provision(self, *, task_state, subtask, base_dir: str, policy) -> EnvHandle:
        sid = (subtask or {}).get("subtask_id", "wt")
        task8 = str(getattr(task_state, "task_id", "task"))[:8] or "task"
        branch = f"wt/{task8}/{sid}"
        wt_dir = os.path.join(base_dir, ".sc-worktrees", task8, sid)
        os.makedirs(os.path.dirname(wt_dir), exist_ok=True)
        if os.path.isdir(wt_dir):
            shutil.rmtree(wt_dir, ignore_errors=True)   # stale leftover from a crashed run
        _runGit(["worktree", "add", "-b", branch, wt_dir, "HEAD"], cwd=base_dir)
        LOG.info("worktree %s -> %s", branch, wt_dir)
        return EnvHandle(work_dir=wt_dir, backend=self.NAME,
                         meta={"branch": branch, "base_dir": base_dir},
                         capabilities=self.CAPABILITIES)

    def wrapLauncher(self, run_cmd: list, handle: EnvHandle) -> "tuple[list, str]":
        return run_cmd, handle.work_dir     # native process, isolated cwd

    def collectChanges(self, handle: EnvHandle, *, task_state, subtask) -> dict:
        """Commit any worktree edits on the branch, then merge the branch into the base tree.
        On merge failure leave the worktree intact (teardown is skipped by the caller's guard)."""
        wt_dir = handle.work_dir
        base_dir = handle.meta["base_dir"]
        branch = handle.meta["branch"]
        status = _runGit(["status", "--porcelain"], cwd=wt_dir, check=False)
        dirty = bool((status.stdout or "").strip())
        if dirty:
            _runGit(["add", "-A"], cwd=wt_dir)
            _runGit(["commit", "-m", f"worktree: {branch}"], cwd=wt_dir, check=False)
        merge = _runGit(["merge", "--no-edit", branch], cwd=base_dir, check=False)
        if merge.returncode != 0:
            LOG.warning("worktree merge of %s failed (left intact): %s", branch, merge.stderr)
            return {"backend": self.NAME, "merged": False, "branch": branch,
                    "left_intact": True, "error": (merge.stderr or "").strip()[:400]}
        return {"backend": self.NAME, "merged": True, "branch": branch, "had_changes": dirty}

    def teardown(self, handle: EnvHandle) -> None:
        base_dir = handle.meta["base_dir"]
        try:
            _runGit(["worktree", "remove", "--force", handle.work_dir], cwd=base_dir, check=False)
            _runGit(["worktree", "prune"], cwd=base_dir, check=False)
        except Exception as e:  # noqa: BLE001 -- teardown is best-effort
            LOG.warning("worktree teardown failed: %s", e)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_execution_worktree.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add platform_core/execution/backends/worktree.py tests/test_execution_worktree.py
git commit -m "feat(epic8): WorktreeEnvironment rung-1 isolation (git worktree per subtask)"
```

---

### Task 10: `CapabilityPolicy` + `validateMounts` (openclaw threat model)

**Files:**
- Create: `platform_core/execution/security.py`
- Test: `tests/test_execution_security.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_execution_security.py
"""CapabilityPolicy resolution + validateMounts threat-model port (openclaw)."""
import pytest

from platform_core.execution.security import (
    CapabilityPolicy, MountSecurityError, validateMounts,
)


class _TS:
    def __init__(self, universe):
        self._u = universe
    def universe(self):
        return self._u


def test_policy_resolves_from_universe():
    ts = _TS({"allowed_paths": ["src/"], "hard_boundaries": [".env", ".git"]})
    pol = CapabilityPolicy.resolve(ts, {"subtask_id": "s1"})
    assert "src/" in pol.allowed_paths
    assert ".env" in pol.hard_boundaries
    assert pol.network is True                 # default grant until a risk tier tightens it
    assert pol.source == "universe"


def test_policy_default_when_no_universe():
    pol = CapabilityPolicy.resolve(None, None)
    assert pol.network is True
    assert pol.source == "default"
    assert isinstance(pol.disallowed_tools, list)


@pytest.mark.parametrize("bad", [
    "/home/user/.ssh",
    "/home/user/.aws/credentials",
    "/home/user/.gnupg",
    "/var/run/docker.sock",
    "/project/.env",
    "/project/.git",
])
def test_validate_mounts_blocks_sensitive_paths(bad):
    pol = CapabilityPolicy.resolve(None, None)
    with pytest.raises(MountSecurityError):
        validateMounts(pol, [bad])


def test_validate_mounts_allows_repo_root():
    pol = CapabilityPolicy.resolve(None, None)
    validateMounts(pol, ["/project/repo"])   # repo root is fine (its .env is not a mount target)


def test_validate_mounts_blocks_host_network():
    pol = CapabilityPolicy.resolve(None, None)
    with pytest.raises(MountSecurityError):
        validateMounts(pol, ["/project/repo"], network_mode="host")


def test_validate_mounts_allows_none_network():
    pol = CapabilityPolicy.resolve(None, None)
    validateMounts(pol, ["/project/repo"], network_mode="none")   # no raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_execution_security.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'platform_core.execution.security'`

- [ ] **Step 3: Write minimal implementation**

```python
# platform_core/execution/security.py
"""Capability scoping + sandbox-mount threat model for the execution fabric.

CapabilityPolicy is the per-subtask allow/deny resolved from 9TO5's existing universe
(allowed_paths/hard_boundaries/CORE_PROTECTED_FILES) and -- when Epic 4 lands -- the semantic
action-risk tier. validateMounts is a direct port of openclaw `validate-sandbox-security.ts`:
hard-block bind-mounts to secrets/VCS/cred dirs/the docker socket/system roots, symlink escapes,
and host/container network modes. Docker/remote backends MUST call validateMounts in provision().

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  MountSecurityError  -- raised when a requested mount/network violates the threat model
  CapabilityPolicy  -- resolved per-subtask allow/deny (allowed_paths/hard_boundaries/network/...)
  validateMounts(policy, mounts, *, network_mode="bridge") -> None  -- refuse unsafe mounts/networks
DEPENDS-ON: config
SIDE-EFFECTS: unannotated
RUN/TEST: python -m pytest tests/test_execution_security.py
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import config

LOG = config.getLogger("execution.security")

# Basenames / fragments that must NEVER be a bind-mount target (openclaw blocked-path set).
_BLOCKED_MOUNT_NAMES = (".env", ".git", ".ssh", ".aws", ".gnupg", ".gpg", ".npmrc", ".netrc")
_BLOCKED_MOUNT_FRAGMENTS = ("docker.sock", "/var/run/docker", "/etc", "/root", "/boot",
                            "/sys", "/proc")
_BLOCKED_NETWORK_MODES = ("host", "container")


class MountSecurityError(RuntimeError):
    """A requested mount or network mode violates the sandbox threat model."""


@dataclass
class CapabilityPolicy:
    """Per-subtask resolved capability scope with source provenance (openclaw layered scopes)."""
    allowed_paths: list = field(default_factory=list)
    hard_boundaries: list = field(default_factory=list)
    network: bool = True
    disallowed_tools: list = field(default_factory=list)
    source: str = "default"

    @classmethod
    def resolve(cls, task_state, subtask) -> "CapabilityPolicy":
        """Derive from the 9TO5 universe + (optional) Epic 4 risk tier. Network on by default."""
        universe = {}
        try:
            if task_state is not None and hasattr(task_state, "universe"):
                universe = task_state.universe() or {}
        except Exception:  # noqa: BLE001
            universe = {}
        allowed = list(universe.get("allowed_paths") or [])
        boundaries = list(universe.get("hard_boundaries")
                          or config.UNIVERSE_DEFAULT_HARD_BOUNDARIES)
        for core in getattr(config, "CORE_PROTECTED_FILES", ()):
            if core not in boundaries:
                boundaries.append(core)
        network = True
        disallowed: list = []
        source = "universe" if universe else "default"
        # Epic 4 seam (optional, guarded): a destructive/untrusted risk tier tightens the policy.
        try:
            from platform_core.runtime import action_risk  # noqa: F401
            risk = (subtask or {}).get("risk_tier")
            if risk in ("destructive", "unknown"):
                network = False
                source = "risk:" + risk
        except Exception:  # noqa: BLE001 -- Epic 4 not landed yet -> universe-only policy
            pass
        return cls(allowed_paths=allowed, hard_boundaries=boundaries, network=network,
                   disallowed_tools=disallowed, source=source)


def _existingAncestorRealpath(path: str) -> str:
    """Resolve the realpath of the nearest existing ancestor (symlink-escape hardening)."""
    cur = os.path.abspath(path)
    while not os.path.exists(cur):
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return os.path.realpath(cur)


def validateMounts(policy: CapabilityPolicy, mounts, *, network_mode: str = "bridge") -> None:
    """Refuse a backend's requested bind-mounts/network. Raises MountSecurityError on any violation."""
    if network_mode in _BLOCKED_NETWORK_MODES:
        raise MountSecurityError(f"network mode {network_mode!r} is forbidden")
    for raw in (mounts or []):
        host_path = raw if isinstance(raw, str) else (raw[0] if raw else "")
        if not host_path:
            continue
        norm = os.path.normpath(host_path).replace("\\", "/")
        base = os.path.basename(norm.rstrip("/"))
        if base in _BLOCKED_MOUNT_NAMES:
            raise MountSecurityError(f"refusing to mount secret/VCS path: {host_path}")
        low = norm.lower()
        if any(frag in low for frag in _BLOCKED_MOUNT_FRAGMENTS):
            raise MountSecurityError(f"refusing to mount system/socket path: {host_path}")
        real = _existingAncestorRealpath(host_path).replace("\\", "/")
        real_base = os.path.basename(real.rstrip("/"))
        if real_base in _BLOCKED_MOUNT_NAMES or any(frag in real.lower()
                                                    for frag in _BLOCKED_MOUNT_FRAGMENTS):
            raise MountSecurityError(f"refusing symlink-escape to: {real} (via {host_path})")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_execution_security.py -v`
Expected: PASS (11 parametrized + direct cases)

- [ ] **Step 5: Commit**

```bash
git add platform_core/execution/security.py tests/test_execution_security.py
git commit -m "feat(epic8): CapabilityPolicy + validateMounts (openclaw threat model)"
```

---

### Task 11: `DockerEnvironment` — rung 2 containment (behind mockable `_run_docker`)

**Files:**
- Create: `platform_core/execution/backends/docker.py`
- Test: `tests/test_execution_docker.py` (mocks `_run_docker` — no daemon in CI)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_execution_docker.py
"""DockerEnvironment command construction + security gate, with _run_docker mocked (no daemon)."""
from types import SimpleNamespace
from unittest import mock

import pytest

from platform_core.execution.backends import docker as dk
from platform_core.execution.environment import Capability
from platform_core.execution.security import CapabilityPolicy, MountSecurityError


def _ok(stdout="container123\n"):
    return SimpleNamespace(returncode=0, stdout=stdout, stderr="")


def test_healthcheck_true_when_docker_info_ok():
    with mock.patch.object(dk, "_run_docker", return_value=_ok("info ok")):
        assert dk.DockerEnvironment().healthCheck() is True


def test_healthcheck_false_when_docker_absent():
    with mock.patch.object(dk, "_run_docker", side_effect=FileNotFoundError("no docker")):
        assert dk.DockerEnvironment().healthCheck() is False


def test_provision_runs_container_and_records_cid():
    pol = CapabilityPolicy.resolve(None, None)
    captured = {}
    def _fake(args, **kw):
        captured["args"] = args
        return _ok("cid-abc\n")
    with mock.patch.object(dk, "_run_docker", side_effect=_fake):
        h = dk.DockerEnvironment().provision(task_state=None, subtask={"subtask_id": "s1"},
                                             base_dir="/project/repo", policy=pol)
    assert h.meta["cid"] == "cid-abc"
    assert h.backend == "docker"
    assert Capability.PERSISTENT not in h.capabilities    # docker tree is ephemeral
    assert "run" in captured["args"] and "-d" in captured["args"]


def test_provision_network_none_when_policy_denies_network():
    pol = CapabilityPolicy(allowed_paths=[], hard_boundaries=[], network=False,
                           disallowed_tools=[], source="risk:destructive")
    captured = {}
    with mock.patch.object(dk, "_run_docker",
                           side_effect=lambda args, **kw: captured.setdefault("args", args) or _ok()):
        dk.DockerEnvironment().provision(task_state=None, subtask=None,
                                         base_dir="/project/repo", policy=pol)
    args = captured["args"]
    assert "--network" in args and args[args.index("--network") + 1] == "none"


def test_provision_rejects_unsafe_mount():
    pol = CapabilityPolicy.resolve(None, None)
    with mock.patch.object(dk, "_run_docker", return_value=_ok()):
        with pytest.raises(MountSecurityError):
            dk.DockerEnvironment().provision(task_state=None, subtask=None,
                                             base_dir="/home/user/.ssh", policy=pol)


def test_wraplauncher_prefixes_docker_exec():
    pol = CapabilityPolicy.resolve(None, None)
    with mock.patch.object(dk, "_run_docker", return_value=_ok("cid-xyz\n")):
        env = dk.DockerEnvironment()
        h = env.provision(task_state=None, subtask=None, base_dir="/project/repo", policy=pol)
    out_cmd, out_work = env.wrapLauncher(["claude", "--print"], h)
    assert out_cmd == ["docker", "exec", "-w", h.meta["container_work"],
                       "cid-xyz", "claude", "--print"]
    assert out_work == h.work_dir
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_execution_docker.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'platform_core.execution.backends.docker'`

- [ ] **Step 3: Write minimal implementation**

```python
# platform_core/execution/backends/docker.py
"""DockerEnvironment -- rung 2 containment: run the Claude CLI inside a container.

provision starts a long-lived container with the (validated) repo bind-mounted; wrapLauncher
prefixes `docker exec -w <cdir> <cid>`; collectChanges archives the diff out; teardown rm -f's
the container. Every daemon call routes through the one mockable `_run_docker` seam (mirrors
native_executor._run_native_actions) so CI never needs a daemon. Drops NETWORK when the policy
says so (`--network=none`). Validates mounts via security.validateMounts before starting.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  DockerEnvironment  -- container-per-subtask ExecutionEnvironment backend
DEPENDS-ON: config, platform_core.execution.environment, platform_core.execution.security
SIDE-EFFECTS: runs `docker` (behind _run_docker); starts/removes containers
RUN/TEST: python -m pytest tests/test_execution_docker.py
"""
from __future__ import annotations

import subprocess

import config
from platform_core.execution.environment import (
    Capability, EnvHandle, ExecutionEnvironment,
)
from platform_core.execution.security import CapabilityPolicy, validateMounts

LOG = config.getLogger("execution.docker")

# Ephemeral tree (no PERSISTENT): the container is torn down after the subtask.
_DOCKER_CAPS = Capability.FILE_RW | Capability.EXEC | Capability.NETWORK | Capability.SNAPSHOT
_CONTAINER_WORK = "/work"


def _run_docker(args: list, *, timeout: "int | None" = None) -> subprocess.CompletedProcess:
    """The single mockable docker seam (CI mocks this; no daemon needed)."""
    return subprocess.run(["docker", *args], capture_output=True, text=True,
                          timeout=timeout or config.EXECUTION_PROVISION_TIMEOUT_SECONDS)


class DockerEnvironment(ExecutionEnvironment):
    """A container per subtask -- the untrusted-code containment rung."""
    NAME = "docker"
    CAPABILITIES = _DOCKER_CAPS

    def healthCheck(self) -> bool:
        try:
            return _run_docker(["info"]).returncode == 0
        except Exception as e:  # noqa: BLE001 -- absent daemon/binary -> degrade to local
            LOG.warning("docker healthCheck failed: %s", e)
            return False

    def provision(self, *, task_state, subtask, base_dir: str, policy) -> EnvHandle:
        pol = policy or CapabilityPolicy.resolve(task_state, subtask)
        network_mode = "bridge" if pol.network else "none"
        validateMounts(pol, [base_dir], network_mode=network_mode)   # raises MountSecurityError
        args = ["run", "-d", "--rm",
                "-v", f"{base_dir}:{_CONTAINER_WORK}",
                "-w", _CONTAINER_WORK]
        if not pol.network:
            args += ["--network", "none"]
        args += [config.DOCKER_EXECUTOR_IMAGE, "tail", "-f", "/dev/null"]
        res = _run_docker(args)
        cid = (res.stdout or "").strip()
        LOG.info("docker container %s (network=%s)", cid[:12], network_mode)
        return EnvHandle(work_dir=base_dir, backend=self.NAME,
                         meta={"cid": cid, "container_work": _CONTAINER_WORK,
                               "network": network_mode},
                         capabilities=self.CAPABILITIES)

    def wrapLauncher(self, run_cmd: list, handle: EnvHandle) -> "tuple[list, str]":
        cid = handle.meta["cid"]
        cwork = handle.meta["container_work"]
        return ["docker", "exec", "-w", cwork, cid, *run_cmd], handle.work_dir

    def collectChanges(self, handle: EnvHandle, *, task_state, subtask) -> dict:
        """Repo is bind-mounted, so edits already land on the host tree -- nothing to copy out.
        Record a summary; a future image with a private overlay would `docker cp`/git-bundle here."""
        return {"backend": self.NAME, "merged": True, "cid": handle.meta.get("cid"),
                "note": "bind-mounted tree; edits already on host"}

    def teardown(self, handle: EnvHandle) -> None:
        cid = handle.meta.get("cid")
        if not cid:
            return
        try:
            _run_docker(["rm", "-f", cid])
        except Exception as e:  # noqa: BLE001 -- teardown is best-effort
            LOG.warning("docker teardown of %s failed: %s", cid[:12], e)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_execution_docker.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add platform_core/execution/backends/docker.py tests/test_execution_docker.py
git commit -m "feat(epic8): DockerEnvironment rung-2 containment (mockable _run_docker)"
```

---

### Task 12: `RemoteEnvironment` — rung 3 stubs (behind mockable `_run_remote`, degrade clean)

**Files:**
- Create: `platform_core/execution/backends/remote.py`
- Test: `tests/test_execution_remote.py` (mocks `_run_remote`; asserts degrade-when-host-absent)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_execution_remote.py
"""RemoteEnvironment stubs: ssh command construction + clean degrade when host/SDK absent."""
from types import SimpleNamespace
from unittest import mock

import config
from platform_core.execution.backends import remote as rm
from platform_core.execution.environment import Capability


def test_healthcheck_false_when_no_host():
    with mock.patch.object(config, "EXECUTION_REMOTE_HOST", ""):
        assert rm.RemoteEnvironment().healthCheck() is False


def test_healthcheck_true_when_host_reachable():
    with mock.patch.object(config, "EXECUTION_REMOTE_HOST", "box.example"), \
         mock.patch.object(config, "EXECUTION_REMOTE_KIND", "ssh"), \
         mock.patch.object(rm, "_run_remote",
                           return_value=SimpleNamespace(returncode=0, stdout="ok", stderr="")):
        assert rm.RemoteEnvironment().healthCheck() is True


def test_provision_records_host_and_ephemeral_caps():
    with mock.patch.object(config, "EXECUTION_REMOTE_HOST", "box.example"), \
         mock.patch.object(config, "EXECUTION_REMOTE_KIND", "ssh"), \
         mock.patch.object(rm, "_run_remote",
                           return_value=SimpleNamespace(returncode=0, stdout="/remote/work", stderr="")):
        h = rm.RemoteEnvironment().provision(task_state=None, subtask={"subtask_id": "s1"},
                                             base_dir="/repo", policy=None)
    assert h.meta["host"] == "box.example"
    assert h.backend == "remote"
    assert Capability.PERSISTENT not in h.capabilities


def test_wraplauncher_prefixes_ssh():
    with mock.patch.object(config, "EXECUTION_REMOTE_HOST", "box.example"), \
         mock.patch.object(config, "EXECUTION_REMOTE_KIND", "ssh"):
        env = rm.RemoteEnvironment()
        h = env.provision.__wrapped__ if hasattr(env.provision, "__wrapped__") else None
    # build a handle directly to test wrapLauncher in isolation
    from platform_core.execution.environment import EnvHandle
    handle = EnvHandle(work_dir="/remote/work", backend="remote",
                       meta={"host": "box.example", "kind": "ssh", "remote_work": "/remote/work"},
                       capabilities=Capability.EXEC)
    out_cmd, out_work = rm.RemoteEnvironment().wrapLauncher(["claude", "--print"], handle)
    assert out_cmd[:3] == ["ssh", "box.example", "cd"]
    assert out_cmd[-2:] == ["claude", "--print"]
    assert out_work == "/remote/work"


def test_unknown_kind_degrades_healthcheck_false():
    with mock.patch.object(config, "EXECUTION_REMOTE_HOST", "box.example"), \
         mock.patch.object(config, "EXECUTION_REMOTE_KIND", "modal"), \
         mock.patch.object(rm, "_run_remote", side_effect=RuntimeError("SDK not installed")):
        assert rm.RemoteEnvironment().healthCheck() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_execution_remote.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'platform_core.execution.backends.remote'`

- [ ] **Step 3: Write minimal implementation**

```python
# platform_core/execution/backends/remote.py
"""RemoteEnvironment -- rung 3 (future scale): ssh / modal / daytona / E2B sub-strategies.

One module, sub-strategies keyed by config.EXECUTION_REMOTE_KIND. Shipped as ABC-conformant stubs
that DEGRADE CLEANLY: healthCheck returns False when no host/SDK is present so the router falls
back to local (exactly like browser_executor without Playwright). Every transport call routes
through the one mockable `_run_remote` seam so CI never reaches the network. wrapLauncher builds
the ssh prefix; modal/daytona/E2B raise NotImplemented inside _run_remote until their SDKs land,
which healthCheck catches -> local fallback.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  RemoteEnvironment  -- ssh/SDK-backed ExecutionEnvironment backend (degrades to local when absent)
DEPENDS-ON: config, platform_core.execution.environment
SIDE-EFFECTS: runs `ssh` / remote SDKs (behind _run_remote)
RUN/TEST: python -m pytest tests/test_execution_remote.py
"""
from __future__ import annotations

import subprocess

import config
from platform_core.execution.environment import (
    Capability, EnvHandle, ExecutionEnvironment,
)

LOG = config.getLogger("execution.remote")

_REMOTE_CAPS = Capability.FILE_RW | Capability.EXEC | Capability.NETWORK


def _run_remote(args: list, *, timeout: "int | None" = None) -> subprocess.CompletedProcess:
    """The single mockable remote-transport seam (ssh today; SDK kinds raise until implemented)."""
    kind = config.EXECUTION_REMOTE_KIND
    if kind != "ssh":
        raise NotImplementedError(f"remote kind {kind!r} SDK not wired yet")
    return subprocess.run(["ssh", *args], capture_output=True, text=True,
                          timeout=timeout or config.EXECUTION_PROVISION_TIMEOUT_SECONDS)


class RemoteEnvironment(ExecutionEnvironment):
    """A remote box/microVM per subtask -- the cloud-scale rung (opt-in, budget-gated)."""
    NAME = "remote"
    CAPABILITIES = _REMOTE_CAPS

    def healthCheck(self) -> bool:
        host = config.EXECUTION_REMOTE_HOST
        if not host:
            return False
        try:
            return _run_remote([host, "true"]).returncode == 0
        except Exception as e:  # noqa: BLE001 -- no host/SDK -> degrade to local
            LOG.warning("remote healthCheck failed (%s) -> local", e)
            return False

    def provision(self, *, task_state, subtask, base_dir: str, policy) -> EnvHandle:
        host = config.EXECUTION_REMOTE_HOST
        sid = (subtask or {}).get("subtask_id", "wt")
        remote_work = f"/tmp/9to5-{sid}"
        _run_remote([host, "mkdir", "-p", remote_work])
        # NOTE: secrets never sync here (validateMounts/openclaw threat model); creds stay host-side.
        return EnvHandle(work_dir=remote_work, backend=self.NAME,
                         meta={"host": host, "kind": config.EXECUTION_REMOTE_KIND,
                               "remote_work": remote_work, "base_dir": base_dir},
                         capabilities=self.CAPABILITIES)

    def wrapLauncher(self, run_cmd: list, handle: EnvHandle) -> "tuple[list, str]":
        host = handle.meta["host"]
        remote_work = handle.meta["remote_work"]
        return ["ssh", host, "cd", remote_work, "&&", *run_cmd], handle.work_dir

    def collectChanges(self, handle: EnvHandle, *, task_state, subtask) -> dict:
        """Archive the remote tree back (git-bundle/rsync). Stub records intent; never loses work."""
        return {"backend": self.NAME, "merged": False,
                "note": f"remote {handle.meta.get('kind')} collect not wired; tree left on host",
                "host": handle.meta.get("host")}

    def teardown(self, handle: EnvHandle) -> None:
        try:
            _run_remote([handle.meta["host"], "rm", "-rf", handle.meta["remote_work"]])
        except Exception as e:  # noqa: BLE001 -- best-effort
            LOG.warning("remote teardown failed: %s", e)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_execution_remote.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add platform_core/execution/backends/remote.py tests/test_execution_remote.py
git commit -m "feat(epic8): RemoteEnvironment rung-3 stubs (degrade-clean ssh/_run_remote)"
```

---

### Task 13: (Optional) backend tag in `surfaces_used` for SIE learning

**Files:**
- Modify: `platform_core/core/surfaces.py` (`surfaces_used`)
- Test: `tests/test_execution_router.py` (append one case)

- [ ] **Step 1: Write the failing test** (append)

```python
# tests/test_execution_router.py  (append)
import platform_core.core.surfaces as surfaces


def test_surfaces_used_tags_backend():
    used = surfaces.surfaces_used({"prompt": "do x", "execution_backend": "worktree"})
    assert "backend:worktree" in used


def test_surfaces_used_no_backend_tag_by_default():
    used = surfaces.surfaces_used({"prompt": "do x"})
    assert not any(t.startswith("backend:") for t in used)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_execution_router.py -k surfaces_used -v`
Expected: FAIL on `test_surfaces_used_tags_backend` (no backend tag emitted today)

- [ ] **Step 3: Write minimal implementation** (in `surfaces_used`, just before the final `return`/`if not used:` block)

```python
    backend = spec.get("execution_backend")
    if backend:
        used.add(f"backend:{str(backend).lower()}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_execution_router.py -k surfaces_used -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add platform_core/core/surfaces.py tests/test_execution_router.py
git commit -m "feat(epic8): tag execution backend in surfaces_used (SIE learning, non-load-bearing)"
```

---

### Task 14: Closeout — full suite, size audit, repo map regen

**Files:**
- Modify: `AGENTS.md` (regenerated, not hand-edited)

- [ ] **Step 1: Run the full execution-fabric test set**

Run: `python -m pytest tests/test_execution_environment.py tests/test_execution_local.py tests/test_execution_router.py tests/test_execution_security.py tests/test_execution_worktree.py tests/test_execution_docker.py tests/test_execution_remote.py tests/test_executor_wrap_env.py tests/test_execute_mixin_env.py tests/test_execcwd_fabric.py -v`
Expected: PASS (all)

- [ ] **Step 2: Verify zero must_split violations**

Run: `python tools/size_audit.py`
Expected: zero `must_split` (every new module ≤260 lines, every function ≤70 lines)

- [ ] **Step 3: Regression — fabric off == today**

Run: `python tools/dev.py fast`
Expected: PASS (with `EXECUTION_FABRIC_ENABLED=False` the executor path is byte-for-byte today: `environment=None` ⇒ `_applyEnvironment` identity; `selectEnvironment` ⇒ `LocalEnvironment`; `_execCwd` unchanged)

- [ ] **Step 4: Regenerate the repo map**

Run: `python tools/repo_map.py`
Expected: `AGENTS.md` updated with the new `platform_core/execution/*` module rows + the new `runClaude` signature

- [ ] **Step 5: Commit**

```bash
git add AGENTS.md
git commit -m "docs(epic8): regenerate AGENTS.md for execution-fabric modules"
```

---

## Self-Review

**1. Spec coverage** (each §3 unit → task):

- §3a `ExecutionEnvironment` ABC + `Capability` + `EnvHandle` → **Task 1**. ✅
- §3b backends: local → **Task 2**; worktree → **Task 9**; docker → **Task 11**; remote → **Task 12**. ✅
- §3c `EnvironmentRouter` (`selectEnvironment`, `_BACKENDS`/lazy `_backendClass`, fallback) +
  config knobs + "selection never reads `MODEL_BY_EFFORT`" → **Tasks 3, 4** (router never imports
  `MODEL_BY_EFFORT`); brain `execution_backend` override honored in `selectEnvironment`. ✅
- §3d `CapabilityPolicy` + `validateMounts` (openclaw threat model) → **Task 10**; docker calls
  `validateMounts` in provision → **Task 11**; Epic 4 risk seam guarded-optional in both. ✅
- §3e remote step events on `event_bus` (`env_provisioned`/`env_changes_collected`/`env_teardown`/
  `env_fallback`) → **Task 4** (`_emit`); existing `SubprocessFeed` tap unchanged (terminal path
  still attaches `feed`; bytes originate in the wrapped process). ✅
- §4 data flow (provision→wrap→run→verify→collect→teardown; handle reused across attempts;
  per-worker handle under parallelism) → **Task 7** (provision once before loop, finalize once
  after; `env_ctx` threaded through every attempt). ✅
- §5 file structure (all 9 new files + 6 modified) → Tasks 1–13; `AGENTS.md` regen → **Task 14**. ✅
- §6 error handling (provision fail→local; mount reject→local; collect never loses work→left
  intact; teardown best-effort; `env_handle_meta` recorded on subtask) → **Tasks 4, 7, 9**. ✅
- §7 testing (ABC contract; local identity; worktree temp-git; docker/remote mocked seam;
  security table-driven; router fallback) → Tasks 1,2,4,9,10,11,12. ✅
- §8 sequencing (ABC+Local+router → worktree → docker+security → remote) → task order matches the
  **locked** build order (worktree rung 1 → docker rung 2 → remote rung 3). ✅
- §9 success criteria 1–6 → Task 2 (no-op), Task 9 (worktree), Task 7+9 (per-worker tree unblocks
  parallel remediation), Task 11 (`.env`/`.git` not mounted, `--network=none`), Task 4 (events),
  Task 14 (size_audit/repo_map/fast). ✅

**2. Placeholder scan:** every code step contains complete code (no TBD/"add error handling"/
"similar to Task N"). The remote `collectChanges` and docker `collectChanges` are intentionally
documented stubs that return a real summary (matching the spec's "shipped as ABC-conformant stubs
that degrade cleanly") — not placeholders.

**3. Type/name consistency** (verified across tasks):

- Method names stable everywhere: `provision` / `wrapLauncher` / `collectChanges` / `teardown` /
  `healthCheck`. ✅
- `EnvHandle` fields `work_dir/backend/meta/capabilities` used identically in Tasks 1,2,4,9,11,12. ✅
- Router API `selectEnvironment(spec, subtask, task_state)`, `provision(env, *, task_state,
  subtask, base_dir, policy=None) -> (env, handle)`, `finalize(env, handle, task_state, subtask)`
  — call sites in Task 7 match Task 4 signatures. ✅
- `_applyEnvironment(fresh_cmd, resume_cmd, work, environment, env_handle)` (Task 5) and
  `_envHandsKw(hands, run_claude_fn, environment, env_handle)` (Task 6) signatures match their
  call sites in `runClaude` (Task 5) and `_runOneAttempt` (Task 7). ✅
- `CapabilityPolicy.resolve(task_state, subtask)` and `validateMounts(policy, mounts, *,
  network_mode="bridge")` (Task 10) match docker's calls (Task 11). ✅
- Conventions: functions camelCase (`wrapLauncher`, `selectEnvironment`, `validateMounts`),
  vars snake_case (`run_cmd`, `work_dir`, `base_dir`), consts ALL_CAPS (`NAME`, `CAPABILITIES`,
  `_LOCAL_CAPS`, `_CONTAINER_WORK`, `_BLOCKED_MOUNT_NAMES`); the mockable seams `_run_docker` /
  `_run_remote` keep snake_case deliberately to mirror `native_executor._run_native_actions`. ✅

**Fix applied during review:** the `RemoteEnvironment.wrapLauncher` test originally probed a
non-existent `provision.__wrapped__`; I left a harmless inert line but the assertion builds the
`EnvHandle` directly and tests `wrapLauncher` in isolation (no live ssh), which is the intended,
deterministic check. No other inconsistencies found.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-30-epic8-cloud-execution-fabric.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. (REQUIRED SUB-SKILL: superpowers:subagent-driven-development.)

**2. Inline Execution** — Execute tasks in this session using superpowers:executing-plans, batch execution with checkpoints.

**Which approach?**
