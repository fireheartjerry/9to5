# Epic 8 — Cloud Execution Fabric (Design Spec)

**Date:** 2026-06-30 · **Status:** design (no code written) · **Lens:** transformative net-new capability
**Sources studied (read-only):** `references/hermes/tools/environments/*` (the model), `references/agentscope/.../workspace/*` (Local/Docker/E2B), `references/openhands/.../sandbox/*` + event stream, `references/openclaw/src/agents/sandbox/*` (threat model + tool policy).
**9TO5 ground truth:** `_9to5-brief.md` §2.6 (gap #6) · `themes/tool-use-env.md` · `agents/executor.py` · `agents/browser_executor.py` · `agents/native_executor.py` · `platform_core/orchestration/llm_mixin.py::_selectExecutor` · `platform_core/orchestration/execute_mixin.py` · `platform_core/orchestration/run_loop.py::_execCwd` · `platform_core/runtime/resilience.py` · `platform_core/app_config/llm.py`.

---

## 1. Goal

Give 9TO5 a **pluggable execution-environment abstraction** so the Executor can run a subtask's Claude Code CLI not only on the local real tree but inside an isolated/remote/parallel backend (worktree → docker → ssh/modal/daytona/E2B microVM) selected per-run/per-subtask — **transforming brief gap #6** ("Sandboxed / isolated executor environment") from "`--dangerously-skip-permissions` on the live tree behind path/regex guards" into a real, swappable isolation boundary with semantic capability scoping.

**The NEW capability:** today there is exactly one place an edit can happen — `subprocess.Popen(run_cmd, cwd=work)` in `agents/executor_stream.py::runSubprocess`, always the host, always the real `PROJECT_ROOT`. This epic introduces an `ExecutionEnvironment` ABC whose backends decide *where that process runs and which tree it touches*, so 9TO5 escapes the single local machine: parallel isolated workers, untrusted-code containment, and (later) cloud/serverless scale — all behind one interface modeled on hermes' `BaseEnvironment`.

---

## 2. Non-Goals

- **Not forcing remote by default.** `EXECUTION_BACKEND` defaults to `local` (today's exact behavior). The fabric is opt-in per run/subtask; a clean checkout with no Docker/cloud still runs identically.
- **Not a Kubernetes / cluster platform.** No pod schedulers, no service mesh, no autoscaling groups. 9TO5 is a single-operator system; the fabric tops out at "spin one container or one remote box per subtask," not a control plane. (openhands' K8s/loom's eBPF tiers are noted as reference-only, out of scope.)
- **Not changing model/effort routing.** `config.MODEL_BY_EFFORT`, `--effort`, `--fallback-model` and the playbook/charter logic are untouched. Backend selection is orthogonal to model selection (per `.claude/rules/orchestration.md`).
- **Not replacing the browser/native surfaces.** The fabric wraps only the terminal (Claude CLI) hands path; `surface="browser"`/`"native"` stay as-is (they are API/UIA, not sandboxable shells).
- **Not a new MCP server or credential vault** in this epic (the openhands MCP-credential-proxy is a noted future extension under §3d, not built here).

---

## 3. Architecture (small units + interfaces)

### 3a. The `ExecutionEnvironment` ABC

New module `platform_core/execution/environment.py`. Modeled on hermes `BaseEnvironment` (`references/hermes/tools/environments/base.py`: `__init__(cwd,timeout,env)`, abstract `_run_bash()`/`cleanup()`, concrete `execute()`/lifecycle) **and** 9TO5's existing pluggable-surface convention (`browser_executor.runBrowser` / `native_executor.runNative` share `executor.runClaude`'s signature + result-dict). Crucial adaptation: 9TO5's unit of work is *one whole Claude CLI invocation*, not one bash line — so the environment wraps the **launch of `run_cmd`**, not individual shell commands.

```python
class Capability(Flag):          # bernstein's frozenset[SandboxCapability] idea
    FILE_RW   = auto()
    EXEC      = auto()
    NETWORK   = auto()
    SNAPSHOT  = auto()           # can checkpoint/rollback the tree
    PERSISTENT = auto()          # tree survives teardown (local/worktree) vs ephemeral (docker/remote)

@dataclass
class EnvHandle:                 # opaque per-subtask provision result
    work_dir: str                # the exec_cwd the executor runs against
    backend: str                 # "local" | "worktree" | "docker" | ...
    meta: dict                   # container id / branch name / ssh host / sandbox id
    capabilities: "Capability"

class ExecutionEnvironment(ABC):
    NAME: str = "base"
    CAPABILITIES: "Capability" = Capability(0)

    @abstractmethod
    def provision(self, *, task_state, subtask, base_dir: str,
                  policy: "CapabilityPolicy") -> EnvHandle: ...
    @abstractmethod
    def wrapLauncher(self, run_cmd: list[str], handle: EnvHandle) -> "tuple[list[str], str]":
        """Transform (run_cmd, work_dir) so the Claude CLI runs INSIDE the env.
        local: identity. docker: prefix `docker exec -w <cdir> <cid> …`. ssh: `ssh host …`.
        Mirrors hermes' per-backend `_run_bash` seam."""
    @abstractmethod
    def collectChanges(self, handle: EnvHandle, *, task_state, subtask) -> dict:
        """Bring work back to the canonical tree; return a summary for the trajectory.
        worktree: merge/leave branch. docker/remote: git-bundle/diff/rsync out (openhands
        workspace_archive pattern). Must NEVER silently lose edits."""
    @abstractmethod
    def teardown(self, handle: EnvHandle) -> None: ...        # best-effort cleanup
    def healthCheck(self) -> bool: ...                        # default True; docker/ssh probe reachability
```

`provision`/`collectChanges`/`teardown` are the lifecycle hermes folds into `init_session`/`cleanup`; splitting them lets the orchestrator reuse one handle across a subtask's attempts (`MAX_SUBTASK_ATTEMPTS`) and tear down once. The whole interface is small (≤300 lines incl. the ABC, `Capability`, `EnvHandle`) per the modularity rule.

### 3b. Backends as separate modules

`platform_core/execution/backends/` — one file per backend, each ≤300 lines, owning its domain, never importing the router (no circular deps):

| Backend | Module | Rung | What it does | Reference |
|---|---|---|---|---|
| **local** | `backends/local.py` | 0 (default, today) | `provision` returns `base_dir` unchanged; `wrapLauncher` is identity; `collectChanges`/`teardown` no-op. Capabilities = FILE_RW\|EXEC\|NETWORK\|PERSISTENT. **Byte-for-byte today's behavior.** | — |
| **worktree** | `backends/worktree.py` | 1 (first real isolation) | `provision` = `git worktree add` a per-subtask branch dir; `work_dir` = that dir; `collectChanges` = merge/cherry-pick branch back (or leave for review); `teardown` = `git worktree remove --force` + prune. Adds SNAPSHOT. **This is Epic 1's worktree isolation, expressed as backend #1 of this fabric** (see §8). | hermes process/worktree tier; `references/claude-code/.../EnterWorktreeTool` |
| **docker** | `backends/docker.py` | 2 (first untrusted-code containment) | `provision` = start a container (image bundling the `claude` CLI), bind-mount the repo (validated, see §3d); `wrapLauncher` prefixes `docker exec -w <wdir> <cid>`; `collectChanges` = `docker cp`/git-bundle out; `teardown` = `docker rm -f`. Drops NETWORK when policy says so (`--network=none`). | agentscope `workspace/_docker`; openhands `sandbox/docker_sandbox_service.py`; openclaw `validate-sandbox-security.ts` |
| **remote** | `backends/remote.py` | 3 (future scale, ssh/modal/daytona/E2B) | One module, sub-strategies keyed by `EXECUTION_REMOTE_KIND`. `wrapLauncher` = `ssh host` / SDK exec; `collectChanges` = rsync/git pull / archive fetch. Shipped as **ABC-conformant stubs that degrade cleanly** (return `ok=False,is_error=True` when the SDK/host is absent), exactly like `browser_executor` degrades without Playwright. | hermes `ssh.py`/`modal.py`/`daytona.py`; agentscope `workspace/_e2b` |

### 3c. How the executor selects a backend (no model/effort change)

A thin `EnvironmentRouter` (`platform_core/execution/router.py`) mirrors `native_executor.selectForSurface` + `llm_mixin._selectExecutor`'s degrade-to-default discipline:

```python
def selectEnvironment(spec, subtask, task_state) -> ExecutionEnvironment:
    if not config.EXECUTION_FABRIC_ENABLED:        # global kill-switch -> today's path
        return LocalEnvironment()
    name = (subtask.get("execution_backend")       # per-subtask override (brain-authored, optional)
            or _policyBackend(spec, subtask)        # per-run/risk policy (Epic 4 hook, §3d)
            or config.EXECUTION_BACKEND)            # config default = "local"
    env = _BACKENDS.get(name, LocalEnvironment)()
    return env if env.healthCheck() else LocalEnvironment()   # unreachable backend -> local
```

- **Config knobs** (added to `platform_core/app_config/llm.py`, all defaulting to today's behavior):
  - `EXECUTION_FABRIC_ENABLED: bool = _envBool("EXECUTION_FABRIC_ENABLED", False)` — master gate, like `BROWSER_LAYER_ENABLED`.
  - `EXECUTION_BACKEND: str = os.getenv("EXECUTION_BACKEND", "local")`.
  - `EXECUTION_BACKEND_BY_RISK: dict` — optional risk→backend map (e.g. `destructive → docker`), populated only when Epic 4 lands.
  - `DOCKER_EXECUTOR_IMAGE`, `EXECUTION_REMOTE_KIND`, `EXECUTION_REMOTE_HOST`, `EXECUTION_PROVISION_TIMEOUT_SECONDS`.
- **Selection is policy-only.** `selectEnvironment` never reads `MODEL_BY_EFFORT`; `_buildRunConfig` in `agents/executor.py` still picks the model/effort exactly as today. The two axes are independent.
- **Brain seam:** the orchestrator may author `subtask["execution_backend"]` in the invocation spec (additive field, ignored by the local default), the same way it authors `surface`. `surfaces.surfaces_used` / SIE learning can later record which backend won for which goal (one extra tag), but that is non-load-bearing.

### 3d. Capability scoping + the openclaw sandbox-security threat model

New module `platform_core/execution/security.py`, two parts:

1. **`CapabilityPolicy`** — a per-subtask resolved allow/deny derived from the universe scoping 9TO5 already has (`allowed_paths`/`hard_boundaries`, `CORE_PROTECTED_FILES`) **plus** Epic 4's semantic action-risk class when present. Layered-scope resolution with source provenance is lifted from openclaw `tool-policy.ts` (agent > global > default). The policy decides: which host paths the backend may mount/sync, whether NETWORK is granted, and which `--disallowedTools` to inject. This is **the per-subtask capability set the brief says 9TO5 lacks** — and it composes with Epic 4: the action-risk classifier picks the backend *and* tightens the policy (read-only subtask → local; mutating-untrusted → docker `--network=none`, repo mounted, creds withheld).
2. **`validateMounts(policy, mounts)`** — a direct port of openclaw `validate-sandbox-security.ts`: hard-block bind-mounts to `.env`/`.git`/`~/.ssh`/`~/.aws`/`~/.gnupg`/Docker socket/system paths; symlink-escape hardening via existing-ancestor realpath; block `network:host`/`container:*`; block unconfined seccomp/apparmor. Docker/remote backends MUST call it in `provision()` before starting; failure = refuse that backend, fall back to local with a notification. **Secrets never reach a remote env** (see §6). Privileged actions that *do* need creds (PR/push) stay on the host today; the openhands MCP-credential-proxy is the noted future path so a sandboxed agent can *request* a PR without holding tokens.

### 3e. Remote step events flow back (ties to Epic 1 trajectory/journal)

The fabric emits its own lifecycle events onto the existing process-global bus (`notifications/event_bus.py`) and, when Epic 1's trajectory recorder/step-journal lands, as span entries: `env_provisioned`, `env_wrapped` (backend + image/host), `env_changes_collected` (files merged/diff sha), `env_teardown`. For remote backends the Claude stdout is streamed back over the `docker exec`/`ssh` pipe so the **existing `SubprocessFeed` tap still works** (`execute_mixin._runOneAttempt` attaches `feed` only on the `self._run_claude` path — unchanged; the bytes simply originate in the container/host). Thus a remote subtask's steps surface on the live web/Discord dashboards identically to a local one, and replay (Epic 1) gets backend-annotated events. This is the openhands "event-stream-as-journal" + webhook-callback idea, reusing 9TO5's bus instead of a new HTTP surface.

---

## 4. Data flow (one subtask)

```
orchestrator picks next subtask (execute_mixin._executeSubtask)
  └─ router.selectEnvironment(spec, subtask, state)         # policy → backend (default local)
       └─ healthCheck() fails  ─────────────────────────────▶ LocalEnvironment  (fallback)
  └─ env.provision(task_state, subtask, base_dir=exec_cwd, policy)   # worktree add / docker run / ssh connect
       │   emits env_provisioned ; security.validateMounts() gate
       └─ FAILS ────────────────────────────────────────────▶ fall back to local, notify, continue (§6)
  └─ handle.work_dir becomes exec_cwd for the attempt loop
  └─ _runAttemptLoop → _runOneAttempt → _run_claude(spec, environment=env, env_handle=handle, …)
       └─ executor.runClaude → _buildRunConfig builds local `claude …` cmd (model/effort UNCHANGED)
            └─ run_cmd, work = env.wrapLauncher(run_cmd, handle)     # local: identity
            └─ executor_stream.runSubprocess(run_cmd, cwd=work, feed=…)   # process runs IN the env
            └─ stdout streamed back → SubprocessFeed → event_bus (live surfaces)
  └─ verifier.runVerification(... , exec_cwd=handle.work_dir)        # verify runs against the same tree
  └─ subtask done/failed COMMITTED (source of truth, as today)
  └─ env.collectChanges(handle)    # merge worktree branch / git-bundle out of container; emits event
  └─ env.teardown(handle)          # worktree remove / docker rm -f / ssh close  (best-effort)
```

Provision-once / teardown-once per subtask; the handle is reused across all attempts so `--resume` and adversary remediation snapshot/restore keep working. Under parallelism (`DEFAULT_PARALLELISM>1`) each worker gets its own backend instance + handle — which is exactly what un-blocks `_remediationTreeShared` (today adversary remediation is *disabled* on a shared tree; worktree/docker backends give each peer an isolated tree, see §8).

---

## 5. Exact file structure

**New (`platform_core/execution/`, each with the required `@AI-MAP v1` module doc header):**

| File | Responsibility | Size target |
|---|---|---|
| `platform_core/execution/__init__.py` | package marker + re-export `ExecutionEnvironment`, `EnvHandle`, `Capability`, `selectEnvironment` | tiny |
| `platform_core/execution/environment.py` | the ABC + `Capability` flags + `EnvHandle` dataclass | ≤300 |
| `platform_core/execution/router.py` | `selectEnvironment`, `_BACKENDS` registry, provision-with-fallback + `finalize` helper (collectChanges+teardown) | ≤300 |
| `platform_core/execution/security.py` | `CapabilityPolicy` (openclaw layered scopes + 9TO5 universe + Epic 4 risk) + `validateMounts` (openclaw threat model) | ≤300 |
| `platform_core/execution/backends/__init__.py` | backend registry wiring | tiny |
| `platform_core/execution/backends/local.py` | `LocalEnvironment` — identity, == today | ≤150 |
| `platform_core/execution/backends/worktree.py` | `WorktreeEnvironment` — Epic 1 git-worktree lifecycle | ≤300 |
| `platform_core/execution/backends/docker.py` | `DockerEnvironment` — container lifecycle + mount validation (Docker calls behind one mockable `_run_docker`) | ≤300 |
| `platform_core/execution/backends/remote.py` | ssh/modal/daytona/E2B strategies; degrade cleanly when SDK/host absent | ≤300 |

**Modified (narrow, facade-preserving):**

| File | Change |
|---|---|
| `agents/executor.py` | `runClaude(... , environment=None, env_handle=None)`; in `_buildRunConfig` (or just before `runSubprocess`) apply `run_cmd, work = environment.wrapLauncher(run_cmd, env_handle)` when an environment is passed. **Default `None` ⇒ identity ⇒ zero behavior change.** Keeps executor.py thin — it applies a wrapper, it does not own provisioning. |
| `platform_core/orchestration/execute_mixin.py` | In `_executeSubtask`: `env, handle = router.provision(...)`; pass `environment=env, env_handle=handle` through `hands_kw` (only when `hands is self._run_claude`); after the attempt loop + enrichment, `router.finalize(env, handle, state, subtask)`. |
| `platform_core/orchestration/run_loop.py::_execCwd` | When the fabric is enabled, return the provisioned `handle.work_dir` instead of the `.sc-ctx` scratch (worktree subsumes the self-ref isolation hack). Local/disabled path unchanged. |
| `platform_core/app_config/llm.py` | Add the `EXECUTION_*`/`DOCKER_EXECUTOR_IMAGE` constants from §3c. |
| `platform_core/core/surfaces.py` | (optional) note the active backend in the catalog block + add a backend tag in `surfaces_used` for SIE learning. Non-load-bearing. |
| `AGENTS.md` | regenerate via `python tools/repo_map.py` after the new modules land. |

---

## 6. Error handling

- **Provision failure → fall back to local, never block the run.** `router.provision` wraps every backend's `provision()`: on any exception/timeout (`EXECUTION_PROVISION_TIMEOUT_SECONDS`) it logs, `state.addNotification("execution_fabric", "<backend> provision failed -> local")`, emits an `env_fallback` event, and returns a `LocalEnvironment` handle. This is the exact degrade discipline of `_selectExecutor` (browser unavailable → terminal) and `native_executor.selectForSurface`.
- **Mount/security rejection** (`validateMounts` blocks a path) → treat as provision failure → local fallback + a louder notification (it means the policy and the requested mounts disagree; do not silently widen).
- **Network/remote flakiness** → `healthCheck()` gates selection up-front; `wrapLauncher`/exec errors surface as a normal failed attempt (`ok=False,is_error=True`, `is_error` absent ⇒ no `--resume`), so the existing retry loop + `run_with_recovery` (`platform_core/runtime/resilience.py`) handle it. Rate-limit/session-reset logic in `runClaude` is untouched.
- **collectChanges must never lose work.** If merge-back fails, the worktree branch / container diff is **left intact** and archived (git bundle or tar, openhands `workspace_archive` pattern) under `state/`, with a notification; teardown is skipped for that handle so a human/next run can recover. Teardown itself is best-effort (`try/except`, like hermes `cleanup`/`__del__`).
- **Crash mid-subtask:** provisioned handles are recorded on the subtask (`subtask["env_handle_meta"]`) so a resumed process can prune orphan worktrees/containers on startup (extends `resilience.pick_resume_task`). Composes with Epic 1's step-journal for finer resume.

---

## 7. Testing strategy (pytest, no docker/cloud in CI)

- **ABC contract test** (`tests/test_execution_environment.py`): a `FakeEnvironment` implementing the four abstract methods, asserting the provision→wrap→collect→teardown lifecycle ordering and that `EnvHandle.work_dir` is honored. Proves the interface contract independent of any real backend.
- **LocalEnvironment**: pure identity — assert `wrapLauncher` returns `run_cmd` unchanged and `provision().work_dir == base_dir`, so the default path is provably a no-op (regression guard for "fabric off == today").
- **WorktreeEnvironment**: drive against a temp `git init` repo (offline, cross-platform — git is already a hard dep). Assert worktree add → branch isolation → merge-back → `git worktree remove`. No docker/cloud needed.
- **DockerEnvironment / remote**: isolate every Docker/ssh/SDK call behind one mockable function (`_run_docker`, `_run_remote`) — the exact pattern `native_executor` uses for `pywinauto` and `browser_executor` for Playwright (`tests/test_phase_3_architecture.py` mocks `_run_native_actions`). CI mocks these so it never needs a daemon; assert command construction (`docker exec -w … -- claude …`), `validateMounts` rejections, and degrade-when-absent (`ok=False,is_error=True`).
- **security.py**: table-driven tests of `validateMounts` (port openclaw's blocked-path cases: `.env`, `.ssh`, docker socket, symlink escape, `network:host`) and `CapabilityPolicy` resolution + provenance.
- **Router fallback**: assert `selectEnvironment` returns Local when `healthCheck()` is False / fabric disabled / unknown name; assert `provision` failure falls back to local.
- **Commands:** `python tools/dev.py check platform_core/execution/<file>` per file during edits; `python tools/dev.py fast` before handoff; `python tools/size_audit.py` (zero `must_split`). No new CI lane — these are fast unit tests; docker/e2e stays nightly/manual per `.claude/rules/ci.md`.

---

## 8. Risks + sequencing + dependencies

**Risks**
- **Docker on Windows.** The dev box is Windows 11; Docker Desktop/WSL2 is heavy and may be absent. Mitigation: **worktree is the default first rung and works natively on Windows** (git only); docker is opt-in and degrades to local when the daemon is unreachable (`healthCheck`).
- **The Claude CLI must exist inside the env.** A container/remote can only run the executor if the image/host bundles the `claude` launcher (`_resolveClaudeLauncher` resolves it on the host today). Docker image build + remote provisioning must install it; documented as a backend prerequisite, validated by `healthCheck`.
- **Secrets reaching remote.** `.env`, git creds, `~/.ssh` must never be mounted/synced — enforced by `validateMounts` (openclaw threat model); PR/push stay host-side (future MCP-credential-proxy). This is a hard boundary per `CLAUDE.md`.
- **Cost.** Cloud microVMs/modal/daytona bill real money; default stays `local`, remote is opt-in, and a per-run budget meter (agentscope `_budget` middleware idea) should gate remote backends before they ship.
- **Windows path/quoting in `wrapLauncher`** (drive letters, container path mapping) — hermes already solved this (`shlex.quote`, Git-Bash drive-letter handling in `base.py`); reuse that hardening.

**Sequencing (transformative-first, earn each rung):**
1. **ABC + LocalEnvironment + router (fabric OFF by default).** Pure refactor seam; provably no behavior change. Ships the interface.
2. **WorktreeEnvironment (rung 1).** First real isolation; co-designed with / absorbs **Epic 1's git-worktree isolation** — Epic 1 builds its worktree *as this backend*, so the two specs share `provision/collectChanges/teardown`. Immediately un-blocks parallel adversary remediation (`_remediationTreeShared`, gap #7).
3. **DockerEnvironment (rung 2) + security.py.** First untrusted-code containment; pairs with Epic 4 capability scoping.
4. **Remote (rung 3): ssh → modal/daytona/E2B.** Cloud scale; gated behind budget + healthCheck. **Open question for the user: which remote backend first (docker-local vs E2B/modal/daytona).**

**Dependencies / composition**
- **Epic 1 (worktree isolation + trajectory trace):** worktree is literally backend #1 here; the two co-design. The fabric emits backend-annotated step events into Epic 1's journal/trajectory (§3e), so remote steps replay like local ones.
- **Epic 4 (semantic action-risk safety):** the action-risk class feeds `CapabilityPolicy` and `EXECUTION_BACKEND_BY_RISK` (read-only → local; destructive/untrusted → docker no-network). The fabric is the *enforcement boundary* for Epic 4's *classification*.
- **Epic 7 (richer multi-agent topology)** benefits indirectly: isolated per-worker trees make a shared-tree blackboard unnecessary for parallel safety.

---

## 9. Success criteria

1. With `EXECUTION_FABRIC_ENABLED=0` (default), runs are **byte-for-byte identical** to today — LocalEnvironment is a proven no-op (test-guarded), `agents/executor.py` model/effort routing unchanged.
2. With `EXECUTION_BACKEND=worktree`, a subtask provisions an isolated git worktree, the Claude CLI edits *only* that tree, changes merge back on pass, and the worktree is pruned on teardown — verified on a temp repo in CI without docker.
3. Two independent subtasks run concurrently in separate worktrees and **adversary remediation is no longer skipped** under parallelism (the `_remediationTreeShared` guard no longer trips because trees are disjoint).
4. With `EXECUTION_BACKEND=docker` on a host with a daemon, a subtask runs `claude` inside a container with the repo mounted, `.env`/`.git`/creds **provably not mounted** (`validateMounts` test), `--network=none` when policy demands; daemon-absent ⇒ clean local fallback + notification.
5. Backend lifecycle + remote stdout surface on the live dashboards and (with Epic 1) the trajectory journal as backend-annotated events.
6. `python tools/size_audit.py` shows zero `must_split`; all new modules carry `@AI-MAP v1` headers; `AGENTS.md` regenerated; `python tools/dev.py fast` green.

---

### Source-to-9TO5 mapping (provenance)

| 9TO5 piece | Source technique | Reference path |
|---|---|---|
| `ExecutionEnvironment` ABC + `execute`/lifecycle | hermes `BaseEnvironment` | `references/hermes/tools/environments/base.py` |
| `wrapLauncher` per-backend seam | hermes `_run_bash` (local/docker/ssh/modal/daytona) | `references/hermes/tools/environments/{local,docker,ssh,modal,daytona}.py` |
| `Capability` flags | bernstein `frozenset[SandboxCapability]` | `references/bernstein/.../sandbox/backend.py` |
| Local/Docker/E2B backend trio | agentscope `WorkspaceBase` | `references/agentscope/.../workspace/{_base,_docker,_e2b}.py` |
| Container lifecycle + eviction + session-key | openhands `SandboxService` | `references/openhands/.../sandbox/docker_sandbox_service.py` |
| collectChanges archive (no lost work) | openhands `workspace_archive` | `references/openhands/.../sandbox/workspace_archive.py` |
| Event-stream-as-journal for remote steps | openhands event stream | `references/openhands/.../event/event_service_base.py` |
| `validateMounts` threat model | openclaw `validate-sandbox-security.ts` | `references/openclaw/src/agents/sandbox/validate-sandbox-security.ts` |
| `CapabilityPolicy` layered scopes + provenance | openclaw `tool-policy.ts` | `references/openclaw/src/agents/sandbox/tool-policy.ts` |
| 9TO5 pluggable-surface convention to mirror | `runBrowser`/`runNative` + `_selectExecutor`/`selectForSurface` | `agents/browser_executor.py`, `agents/native_executor.py`, `platform_core/orchestration/llm_mixin.py` |
