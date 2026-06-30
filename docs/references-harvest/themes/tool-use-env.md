# Theme: Tool-Use & Environment (gap #6)

> Cross-repo synthesis of tool definition/validation, MCP surfaces, sandboxing &
> isolation (Docker / git-worktree / microVM / E2B / K8s), capability-scoped tool
> policy, environment backends, and tool-call repair. Sourced from all 23 per-repo
> digests, with code dives into hermes, openhands, openclaw, agentscope, bernstein,
> claude-code, guild, and loom. READ-ONLY harvest.

## 1. Theme intro + how 9to5 handles this today

This theme is about *where and how the agent's hands actually touch the world*: the
isolation boundary the executor runs inside, the per-tool/per-subtask capability
policy that constrains it, the protocol surface (MCP) it offers and consumes, and
the salvage layer that turns a weak model's malformed tool calls into structured
ones. It is the single area where 9to5 is weakest relative to the field.

**How 9to5 handles it today (`agents/executor.py`, `agents/hooks.py`).** All real
tool use happens *inside the Claude Code subprocess*; the brain controls it only
indirectly through the invocation spec (living CLAUDE.md, named skills, a read-only
subagent, effort→model routing, deterministic `.claude/settings.json` hooks). The
only constraints are coarse: PreToolUse guard hooks that hard-block via exit-2
(`hooks_selfmod`/`hooks_destructive`), `--disallowedTools Edit/Write` for
`CORE_PROTECTED_FILES`, and "universe" path/regex scoping (`allowed_paths`/
`hard_boundaries`). Critically, the executor runs **`--dangerously-skip-permissions`
directly on the real project tree** — no container, no per-run worktree, no
per-subtask capability set, and **no MCP surface of its own**. Tool *selection* is
entirely Claude's; 9to5 learns surfaces only at a coarse `surfaces_used(spec)` level.

**Where it's weak.** (a) *No isolation* — a misbehaving attempt mutates the live
tree with nothing but regex guards between it and disaster. (b) *No per-subtask
capability scoping* — every subtask gets the same god-mode toolset; the brief's gap
#6. (c) *Parallelism is crippled by the shared tree* — adversary remediation is
*disabled under parallelism* (`execute_mixin.py::_remediationTreeShared`) because a
git snapshot/restore would clobber concurrent peers, coupling gap #6 to gap #7. (d)
*Tool-call/JSON salvage is ad-hoc* — the planner layer is "saturated with fallback
scaffolding" for the 7B brain's unreliable output. (e) *Safety is syntactic, not
semantic* — path/regex, not a model of *what an action does*.

## 2. Ranked technique table (best-of across all repos)

Rank 5 = highest 9to5 leverage for this theme. "Best repo" notes dedupe where
several repos do the same thing.

| # | technique | source repo (best) | what | 9to5-fit | steal-effort | rank |
|---|---|---|---|---|---|---|
| 1 | **Pluggable execution-environment backends** (`BaseEnvironment`/`SandboxSession` ABC: local / **worktree** / docker / ssh / E2B / modal / daytona) | **hermes** `tools/environments/*` (also bernstein `core/sandbox/backend.py`, agentscope `workspace/_base.py`, openhands `sandbox/*`) | One `execute()`/snapshot interface, per-backend `_run_bash`/cleanup; backend chosen per-run; serverless backends hibernate-on-idle | Gives the executor a *real* isolation layer instead of `--skip-permissions` on the live tree; backend swappable from worktree→Docker→cloud | port-code | 5 |
| 2 | **Per-subtask git-worktree isolation** (enter/exit a live session into an isolated worktree + branch) | **claude-code** `tools/EnterWorktreeTool/`, `utils/worktree.ts` (also bernstein worktree-per-agent + merge queue) | Switch a running session into its own worktree mid-run; exit restores. The *cheapest* isolation tier — and 9to5's executor IS Claude Code, so it's near-free | Directly removes "operates on real tree"; **unblocks parallelism** so adversary remediation need not be disabled (gap #7) | idea-only (CLI feature 9to5 already has) | 5 |
| 3 | **Capability-scoped tool policy** (layered agent>global>default allow/deny/`alsoAllow`, glob + tool-groups, source-provenance diagnostics) | **openclaw** `src/agents/sandbox/tool-policy.ts` (also agentscope `permission/_engine.py` per-tool/per-mode, hermes toolsets, pydantic-ai toolset wrappers) | Resolve a per-subtask allow/deny set through scopes with auditable "which scope decided"; default-deny re-allowed by explicit allows | The per-subtask capability scoping 9to5 explicitly lacks; far beyond `--disallowedTools` + hook guards | port-code | 5 |
| 4 | **Docker sandbox security validation** (bind-mount/seccomp/apparmor/network/symlink threat model) | **openclaw** `src/agents/sandbox/validate-sandbox-security.ts` | Hard-blocks mounts to creds/system/Docker-socket/`~/.ssh` etc., symlink-escape realpath hardening, blocks `network:host` + unconfined seccomp/apparmor | Turnkey threat-model for the Docker backend (#1) when 9to5 graduates past worktree | port-code | 4 |
| 5 | **Plain-text / Harmony tool-call repair** (promote text-emitted tool calls to structured) | **openclaw** `packages/tool-call-repair/` | Parses bracket/Harmony-channel/XML-ish tool calls weak models emit as prose into structured calls; name allowlist + payload byte cap | A principled salvage layer for the malformed-7B-output tax 9to5 pays everywhere | port-code | 4 |
| 6 | **Validation-error → structured retry-prompt loop** (feed the model its exact schema/field errors) | **pydantic-ai** `_output.py:_make_retry_prompt`, `exceptions.py:ToolRetryError` (also autogen `extract_json_from_str`+retry ladder, dify `json_repair`+nudge) | On invalid tool/output, serialize Pydantic `ValidationError.errors()` into a `RetryPromptPart`; bounded per-tool/per-output budgets; lenient `T \| Json[T]` + markdown-fence strip | Attacks root cause of unreliable brain tool/JSON output vs blind re-prompt; tool-call validation feedback | port-code | 5 |
| 7 | **MCP proxy for privileged actions** (agent never holds creds; PR/push proxied server-side) | **openhands** `mcp/mcp_router.py` (also dify `core/mcp/`, guild MCP-as-substrate, autogen `McpWorkbench`, loom `POST /mcp`) | The sandboxed agent can *request* a PR/MR across GitHub/GitLab/etc.; a server-side MCP router holds the tokens | A semantic capability boundary (request-vs-hold-creds) that beats path/regex; also seeds 9to5's own MCP surface | port-code | 4 |
| 8 | **before/afterToolCall interception + deferred tool resolution** (per-tool policy as data, not exit-2) | **openclaw** `packages/agent-core/src/agent-loop.ts` (also ms-agent-framework `_middleware.py` FunctionMiddleware, pydantic-ai `ApprovalRequiredToolset`) | `beforeToolCall` can `block` with a reason, `afterToolCall` can rewrite/terminate; unknown tools resolved lazily | A real per-tool interception/policy seam 9to5 lacks (only coarse PreToolUse hooks) | port-code | 4 |
| 9 | **Atomic CAS task-claim + file-disjointness parallel-safety test** | **guild** `internal/quest/{accept,bounties}.go` (also gnap lock-free commit-race) | One-statement `UPDATE ... WHERE status='next' AND claimed_by IS NULL`; two tasks parallel-runnable iff file-sets disjoint AND no dep conflict | The exact race-free claim + disjointness test that lets worktree-isolated parallel workers coexist (pairs with #1/#2) | port-code | 4 |
| 10 | **Deferred tools + ToolSearch** (ship tool *names*; load schemas on demand) | **claude-code** `tools/ToolSearchTool/`, `tool.shouldDefer` (also agentscope dynamic ToolGroups via meta-tool) | Model lazy-loads schemas via `select:A,B` or keyword search → `tool_reference` blocks, so hundreds of MCP tools don't bloat the prompt | Lets 9to5 expose a large MCP/tool surface without prompt bloat (mirrors 9to5's own ToolSearch pattern) | idea-only | 3 |
| 11 | **Workspace lifecycle isolation + TTL GC** (per-task scratch dirs, path-scoped safe-remove) | **eliza** `.../services/workspace-lifecycle.ts`, `workspace-service.ts` | Per-task scratch dirs; `gcOrphanedWorkspaces` TTL GC; `removeScratchDir` refuses paths outside allowed roots | A lighter isolation + cleanup tier than full containers; fills part of #6 cheaply | port-code | 3 |
| 12 | **Session-API-key / identity per sandbox** | **openhands** `sandbox/docker_sandbox_service.py`, `session_auth.py` | Each sandbox gets a random session key (env var) used for auth + webhook-callback identity; lookup by key | Per-run credential/identity scoping for the executor surface | idea-only | 3 |
| 13 | **Deterministic descriptor tool planner** (declare tools as descriptors; hide unavailable *with diagnostics*) | **openclaw** `src/tools/planner.ts`, `availability.ts` | Sorts, asserts unique names, hides unavailable tools with explainable diagnostics, throws only on visible-tool contract violations | Clean separation of tool availability from invocation + "why was this hidden" telemetry | idea-only | 3 |
| 14 | **Per-worker scoped toolkits keyed to role** | **owl** `examples/run.py` (also claude-code built-in scoped subagents, metagpt env read/write API registry) | Each worker agent gets only the tools (and model) for its role; coordinator routes by capability description | Maps tool access to subtask role — the per-subtask capability set idea, lighter than #3 | idea-only | 3 |
| 15 | **Sandbox eviction / resource governance** (cap concurrent isolated envs) | **openhands** `sandbox/docker_sandbox_service.py:385` | `max_num_sandboxes` enforced by `pause_old_sandboxes(N-1)` before each start | Governs parallel isolated workers so concurrent subtasks don't exhaust the host | idea-only | 3 |
| 16 | **eBPF / kernel-level syscall audit + escape detection** | **loom** `loom-weaver-ebpf*`, `specs/weaver-ebpf-audit.md` | Aya sidecar captures exec/file/net/privilege syscalls, flags `unshare/setns/mount/bpf` escapes, DNS↔conn correlation | *Semantic* action audit ("what did the action actually do") vs path/regex — the deepest safety tier; heavy/Linux-only | heavy | 2 |
| 17 | **Ephemeral hardened K8s pod sandbox** (TTL-bounded, non-root, readonly-rootfs, drop-ALL-caps) | **loom** `loom-weaver`, `loom-k8s`, `specs/container-system.md` | TTL pods (4h default/48h max), K8s as source of truth, auto-cleanup, max-concurrent gate, REST/MCP provisioning | Strongest isolation but heavy & infra-coupled; reference, not a near-term port for a single-box system | heavy | 2 |
| 18 | **Env-gated / path-confined capability for code-exec** | **crewai** `flow/runtime/_actions.py` (also warp secret-handling skill, eliza `sandbox-policy.ts`, metagpt `mark_as_readable/writeable`) | Inline script exec raises unless an env flag is set; crew-declaration paths confined to the flow's source dir | Cheap env-gate + path-confinement pattern to layer over the executor | idea-only | 2 |

**Notes on dedupe / who does it best:**
- *Sandbox backend abstraction*: **hermes** has the cleanest, most complete ABC (6
  backends incl. serverless); **bernstein** adds a `frozenset[SandboxCapability]`
  (FILE_RW/EXEC/NETWORK/GPU/SNAPSHOT/PERSISTENT_VOLUMES) so the scheduler can reject
  a manifest demanding unsupported features — steal both: hermes' interface +
  bernstein's capability flags. **agentscope** (Local/Docker/**E2B microVM**) and
  **openhands** (Docker + process + remote, with health-grace state machine) are
  the next references.
- *Worktree isolation*: **claude-code** does it best *for 9to5 specifically*
  because 9to5 already runs the Claude Code binary — `EnterWorktreeTool` is a flag
  away. **bernstein** proves the worktree-per-agent + merge-queue topology at scale.
- *Capability-scoped tool policy*: **openclaw** (`tool-policy.ts`) is best — layered
  scopes with source provenance. **agentscope** adds 5 permission *modes*
  (DEFAULT/EXPLORE/ACCEPT_EDITS/BYPASS/DONT_ASK) and per-tool match delegation.
- *MCP surface*: **guild** is the cleanest "MCP server as the shared substrate"
  (one Go binary + SQLite is the blackboard); **openhands** is best for the
  *credential-proxy* pattern; **dify**/**autogen** have full client+server stacks.
- *Tool-call repair*: **openclaw** owns malformed-tool-call→structured;
  **pydantic-ai** owns the validation-error→retry feedback loop. They compose.

## 3. If 9to5 adopts ONE thing for this theme

**Introduce a pluggable executor-environment interface whose first backend is a
per-subtask git worktree** — modeled on hermes' `BaseEnvironment` ABC
(`references/hermes/tools/environments/base.py`) with bernstein's capability-flag
idea, and bootstrapped from a feature 9to5 already owns: Claude Code's
`EnterWorktreeTool` (`references/claude-code/tools/EnterWorktreeTool/`,
`utils/worktree.ts`). This is the highest-leverage, lowest-effort move because it
attacks two gaps with one change: it stops the executor mutating the live tree
behind only regex guards (gap #6), and it gives each parallel worker its own tree so
9to5 can stop *disabling adversary remediation under parallelism*
(`execute_mixin.py::_remediationTreeShared`, gap #7). The worktree backend is nearly
free — the Executor is the Claude Code binary, so it's a CLI/flag drive, not a
rewrite — while the *interface* leaves a clean seam to add Docker (openclaw's
`validate-sandbox-security.ts` threat model) and E2B/microVM (agentscope) backends
later for true untrusted-code isolation. Pair it immediately with guild's atomic-CAS
claim + file-disjointness parallel-safety test
(`references/guild/internal/quest/{accept,bounties}.go`) so worktree-isolated workers
coordinate race-free, and layer openclaw's capability-scoped `tool-policy.ts` on top
once the isolation boundary exists. Start with worktree-per-subtask; earn the
container.
