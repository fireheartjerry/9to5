# Epic 5 — Agent Society / Workforce — Design Spec

**Date:** 2026-06-30
**Status:** Draft (design spec) — pending brainstorming + writing-plans before implementation
**Owner:** Terminal A
**Type:** NET-NEW subsystem (transforms gap #7, agent-comms / topology)
**Harvest sources (MIT / Apache-2.0, portable ideas + code):** metagpt, owl/CAMEL, autogen, agentscope, bernstein
**Reads:** `docs/references-harvest/MASTER.md`, `_9to5-brief.md` §2.4, `themes/agent-comms-topology.md`, `themes/orchestration-planning.md`

---

## 1. Goal

Turn 9TO5's star topology — one Ollama orchestrator driving **one** Claude executor, with any fan-out delegated wholesale to Claude Code's own opaque subagent mechanism (`workflows/registry.py` → `agents/executor_env.py::_composeWorkflowPrompt`) — into a real **9TO5-owned multi-agent organization**: a coordinator that decomposes a goal and assigns subtasks to a roster of **specialized worker agents** (planner / coder / tester / reviewer / researcher), each with a role-scoped toolkit and its own model routing, collaborating over an **append-only shared blackboard**, with **structured debate** for contested decisions.

**New capability:** peer-to-peer coordination 9TO5 can see, persist, and govern — workers exchange structured artifacts on a blackboard 9TO5 owns, claim disjoint work atomically, and resolve conflicts by bounded debate, instead of "the brain hands Claude a workflow JSON and Claude privately dispatches Task-tool subagents 9TO5 never observes."

**Transforms gap #7** (`_9to5-brief.md` §3.7 / §2.4): *"a shared blackboard/scratchpad and coordinated parallel workers (or structured debate) so concurrent subtasks stop clobbering one shared git tree and adversary remediation need not be disabled under parallelism."*

---

## 2. Non-Goals

- **Not** replacing the dual-brain split. The Ollama orchestrator still owns decisions/planning; the coordinator is a thin role *over* the existing brain, not a new brain. Claude remains the only code-writing intelligence.
- **Not** re-deriving the planner. The coordinator reuses `OrchestratorPlanMixin.authorSubtaskPlan` / `critiqueSubtaskPlan` (`platform_core/orchestration/plan_mixin.py`); planner depth is the separate "trustworthy 7B loop" epic.
- **Not** owning run state. Task JSON (`state/task_schema.py`) stays the single source of truth for subtask status; the blackboard is a coordination surface, never a status store.
- **Not** owning control or verification. ControlBus (`platform_core/runtime/control.py`) still owns abort/pause/gates; the verifier (`agents/verifier.py`) still gates every subtask. Debate verdicts are advisory inputs, never the gate.
- **Not** building the worktree/sandbox itself. Per-worker git-worktree isolation + file-disjointness is **Epic 1 "Durable Execution"** (steal #5); Epic 5 *consumes* that seam (§8).
- **Not** an A2A network protocol, cross-process agent service, MCP surface, or dynamic worker self-recursion. Workers cannot spawn sub-workers (warp recursion-budget rail).
- **Not** on by default. `SOCIETY_ENABLED=False`; the star path is unchanged when off.

---

## 3. Architecture

Five small units behind one new product package `society/` (a product domain at root, like `agents/`, `workflows/`), plus a thin coordinator seam in `platform_core/orchestration/`. Cross-module wire types live in `platform_core/core/contracts.py`; role definitions stay local to `society/`.

```
goal
 └─ Coordinator (society/coordinator.py)  ── reuses authorSubtaskPlan + dual-ledger
     ├─ decompose → post subtasks + Task-Ledger facts to Blackboard
     ├─ assign each ready subtask to best-fit Role (society/roles.py)
     ├─ spawn WorkerAgent per claim (society/worker.py) in its own worktree (Epic 1)
     ├─ workers post results/questions/proposals to Blackboard inbox (report-don't-poll)
     ├─ on contested decision → Debate (society/debate.py) → converge
     └─ verifier gates → merge queue lands (Epic 1)
```

### (a) Coordinator role — `society/coordinator.py`

A deterministic Python coordinator (NOT a new LLM) that:
1. **Decomposes** by calling the existing brain (`authorSubtaskPlan`), persisting the result as the normal task JSON subtask graph (`depends_on` honored by `state.nextActionable`). It also writes the Magentic-One-style **Task Ledger** (facts: given / look-up / derive / guess + bullet plan; autogen `_magentic_one`) once to the blackboard as the shared `facts` entry.
2. **Assigns** each ready subtask to a role via `society/roles.py::classifyRole` (capability routing, owl Workforce `coordinator_agent`; deterministic keyword + brain-hint classifier, no heavy call).
3. **Spawns + supervises** workers through a `_handleSocietyBatch` that mirrors `run_loop_mixin.py::_handleParallelBatch` (same `ThreadPoolExecutor`, same `as_completed`, same crash containment) but each future is a `WorkerAgent.run()` bound to a role + worktree cwd.
4. **Collects** results from the blackboard and drives debate/convergence before letting the verifier gate.

The coordinator is invoked from `runExecutionLoop` only when `SOCIETY_ENABLED` and the ready-set has ≥2 disjoint subtasks (else the star path runs unchanged).

### (b) WorkerAgent abstraction — `society/worker.py`

```python
class WorkerAgent:
    def __init__(self, role: RoleSpec, subtask: dict, work_dir: str,
                 blackboard: Blackboard): ...
    def run(self) -> WorkerMessage: ...     # claim → execute → post result
```

- **role** (`RoleSpec` from `society/roles.py`): name, scoped toolkit (allowed `skills_to_invoke` + Claude `--allowedTools`/`--disallowedTools`), default `effort_level`, model override, and a system charter (`agents/playbook.py` charter, role-specialized).
- **own model routing:** role → `effort_level` → `config.MODEL_BY_EFFORT` (researcher → cheap haiku-tier; coder/reviewer → sonnet; arbiter-grade → opus). Reuses the existing routing in `agents/executor.py::_buildRunConfig`; the worker only *narrows* it per role, never bypasses it.
- **execution:** `WorkerAgent.run()` builds a role-scoped `InvocationSpec` and calls the **existing** `agents/executor.py::runClaude(spec, work_dir=<worktree>, task_state=..., subtask=..., feed=...)`. No new subprocess path — the worker is a role-scoped wrapper over `runClaude`, so all hooks/guards/telemetry stay intact.
- **claim:** before running, the worker performs the atomic CAS claim against **task JSON** (`state.updateSubtask(sid, status="in_progress", claimed_by=role)` under `_state_lock`) — guild `accept.go` single-statement claim semantics. Lost race (already `in_progress`) ⇒ the worker yields and re-reads the ready-set. Task JSON, not the blackboard, owns the claim.

### (c) Shared Blackboard — `society/blackboard.py` (NEW owned surface)

Modeled on **bernstein `core/communication/whiteboard.py`** (Apache-2.0, smallest portable blackboard of the harvest) and metagpt's message pool. An **append-only, per-run JSONL** scratchpad with who-wrote-what attribution and subscribe-by-filter.

```python
@dataclass
class BlackboardEntry:           # → also a TypedDict in contracts.py for cross-module use
    key: str                     # logical slot, e.g. "facts", "result:st-007", "vote:debate-3"
    kind: str                    # facts | result | question | proposal | vote | handoff | claim
    author: str                  # role name or "coordinator"
    to: str                      # "all" | "coordinator" | "<role>"  (inbox addressing)
    subtask_id: str | None
    value: dict
    refs: list[str]              # ids of entries this responds to (debate threading)
    span_id: str | None          # Epic 1 trajectory-trace linkage (see §8)
    ts_ns: int

class Blackboard:
    def append(self, entry: BlackboardEntry) -> str: ...      # flock + threadlock, atomic
    def read(self, *, role: str, since_ns: int = 0,
             kind: str | None = None) -> list[BlackboardEntry]: ...   # role-filtered view
    def inbox(self, role: str, since_ns: int = 0) -> list[BlackboardEntry]: ...  # to in {role,"all"}
```

- **Atomicity:** POSIX `flock` + in-process `threading.Lock` for multi-process atomic appends (run + Discord bot + web), malformed-line tolerant (skip + warn) — exactly bernstein's discipline, which matches 9TO5's file-backed three-process model.
- **Storage:** `state/blackboard/<task_id>.jsonl`. Run-scoped, append-only, durable.
- **Ownership — does NOT violate existing owners:**
  - **vs task JSON state:** the blackboard holds *coordination artifacts* (proposals, votes, result summaries, questions). Canonical subtask **status/claim** stays in task JSON; the blackboard only references `subtask_id`. The CAS claim is on task JSON, not the board.
  - **vs `event_bus.py`:** `LiveEventBus` is the *ephemeral in-memory* fan-out for surfaces (ring buffers, SSE, Discord). The blackboard is the *durable on-disk coordination substrate*. The coordinator **emits a mirror `Event`** to `get_bus().emit(...)` for every blackboard append (kind `society`) so the existing web/Discord surfaces visualize the society live — but the durable record is the blackboard. event_bus stays presentation; blackboard stays coordination. No bypass, no second state machine.
- **report-don't-poll** (agentscope): workers never poll task JSON; they write a `result`/`question` to their inbox slot, and the coordinator wakes via `ThreadPoolExecutor.as_completed` (already the wake mechanism) then drains the inbox.

### (d) Structured debate / speaker-selection — `society/debate.py`

Triggered when a decision is **contested**: a `reviewer` worker challenges a `coder` result (verdict `challenged`), two workers' proposals touch overlapping files, or the verifier-vs-reviewer disagree.

- **Speaker selection:** autogen `SelectorGroupChat` / Magentic-One progress-ledger pattern. A deterministic `selectNextSpeaker(thread, roster)` narrows candidates from blackboard state (who has unanswered `refs`), then the brain picks one with a small schema-bounded JSON judgment (`is_resolved`, `next_speaker`, `instruction`) — many small reliable 7B calls, not one big one.
- **Rounds:** bounded by `SOCIETY_DEBATE_MAX_ROUNDS`; each round appends a `proposal`/`vote` entry. Convergence = consensus among voting roles OR round cap.
- **Arbiter:** reuse the **existing independent critic** `agents/second_brain.py::consult` (Gemini → Ollama → stub fallback chain) as the tie-breaking vote — no new reviewer infrastructure. `second_brain.is_blocking()` already maps a verdict to "hold/remediate."
- **Oscillation guard:** diff-hash ring (loki-mode pattern) — if proposals cycle A→B→A, force-stop and escalate to the coordinator (which records a `replan_removed`-style notification and lets the verifier gate the last good state).
- **Output:** a `DebateVerdict` (advisory) the coordinator applies; the verifier still gates. Debate never writes run state directly.

### (e) Replacing / wrapping the "delegate to Claude subagents" path

Today: brain sets `InvocationSpec.use_workflow=True` + `workflow_definition`; `agents/executor_env.py::_composeWorkflowPrompt` renders it into a prompt telling **Claude** to dispatch its own Task-tool subagents — opaque, single-tree, un-observable.

Epic 5 keeps that path as a **fallback** but adds an owned path:
- When `SOCIETY_ENABLED` and a subtask's `workflow_definition` has a `parallel` phase, the coordinator **realizes the workflow itself**: each `WorkflowAgent` (label/prompt/effort, `contracts.py::WorkflowAgent`) becomes a 9TO5 `WorkerAgent` with a role derived from its label, run in its own worktree, posting to the blackboard. The phase's `parallel` flag drives `_handleSocietyBatch`; `synthesis` becomes a coordinator debate/merge step.
- Net effect: the *same* brain-authored `WorkflowDefinition` schema (`workflows/registry.py` validation unchanged) now executes as a **visible 9TO5 workforce** instead of an opaque Claude-internal fan-out. When society is off, `_composeWorkflowPrompt` runs exactly as today.

### Message / inbox protocol (summary)

| field | meaning |
|---|---|
| `kind` | `claim` · `result` · `question` · `proposal` · `vote` · `handoff` · `facts` |
| `to` | `"all"` (broadcast) · `"coordinator"` · `"<role>"` (direct) |
| `refs` | entry ids this message answers (threads debate + Q&A) |
| `span_id` | links to Epic 1 trajectory span (provenance) |

Routing rule (metagpt `_observe`): a role's inbox = entries where `to ∈ {role, "all"}` since its last read cursor. Coordinator's inbox = `to ∈ {"coordinator","all"}`. No central message router object — addressing is a filter over the append log.

---

## 4. Data flow (goal → converge)

1. **Goal** enters `runExecutionLoop`. If `SOCIETY_ENABLED` and the elaborated goal is multi-deliverable (`subtask._singleDeliverable` is False), the coordinator engages; else star path.
2. **Decompose:** coordinator calls `authorSubtaskPlan` → subtasks persisted to task JSON (existing). Coordinator writes the Task-Ledger `facts` entry to the blackboard (`kind=facts`, `to=all`).
3. **Ready-set + disjointness:** coordinator computes `_readySet(state)` (deps done) and filters to a **file-disjoint** batch (Epic 1 disjointness rule; until Epic 1 lands, falls back to "deps-only" like today). Picks up to `SOCIETY_MAX_WORKERS`.
4. **Assign + claim:** each subtask → `classifyRole` → `WorkerAgent`. Worker CAS-claims it in task JSON (`in_progress`); losers re-read.
5. **Produce:** each worker runs `runClaude` in its **own worktree**, edits files, posts a `result` summary (+ artifact refs) to its inbox slot on the blackboard. Crash containment = existing `_handleParallelBatch` try/except (marks `failed`, peers unaffected).
6. **Review / contest:** a `reviewer` worker (or the adversary path `review_mixin`) reads the coder's `result` from the blackboard and either approves or posts a `challenge` proposal.
7. **Debate (only if contested):** `society/debate.py` runs bounded speaker-selected rounds; arbiter = `second_brain.consult`; converge or oscillation-stop.
8. **Verify + land:** the **verifier** gates the (possibly remediated) subtask; on green, Epic 1's merge queue lands the worktree. Coordinator marks `done` in task JSON; `_readySet` re-derives; loop continues.

---

## 5. Exact file structure

### New files (`society/` package — product domain at root)

| File | Responsibility | Owns |
|---|---|---|
| `society/__init__.py` | Thin facade re-exporting `Blackboard`, `WorkerAgent`, `Coordinator`, `classifyRole`, role specs. Keeps callers stable. | — |
| `society/blackboard.py` | `Blackboard` + `BlackboardEntry`: append-only JSONL, `flock`+threadlock atomic append, role-filtered `read`/`inbox`, malformed-tolerant. **NEW owned surface.** | coordination artifacts |
| `society/roles.py` | `RoleSpec` registry (planner/coder/tester/reviewer/researcher): scoped toolkit, model/effort, charter; `classifyRole(subtask, hint)` capability router (owl). | role definitions |
| `society/worker.py` | `WorkerAgent`: CAS-claim → role-scoped `InvocationSpec` → `runClaude` in worktree → post result. | per-worker run |
| `society/inbox.py` | `WorkerMessage` helpers + inbox-cursor filter logic (metagpt `_observe` rule). Small. | message routing |
| `society/debate.py` | `runDebate`, `selectNextSpeaker`, `DebateVerdict`, oscillation guard; arbiter via `second_brain.consult`. | debate orchestration |
| `society/coordinator.py` | `Coordinator`: decompose → assign → `_handleSocietyBatch` → collect → debate hook. Reuses planner + parallel-batch shape. | workforce orchestration |

Each new module gets the required `@AI-MAP v1` doc header (EXPORTS / DEPENDS-ON / SIDE-EFFECTS / RUN/TEST). All files ≤300 lines (ideal); `coordinator.py`/`debate.py` watched against the 450 cap — split into `coordinator_assign.py` / `coordinator_collect.py` if they grow (mixin/sub-module pattern). Funcs ≤70 lines, camelCase; vars snake_case; consts ALL_CAPS.

### Modified files (narrow, ownership-preserving)

| File | Change |
|---|---|
| `platform_core/orchestration/run_loop_mixin.py` | In `runExecutionLoop`, when `SOCIETY_ENABLED` and ready-set ≥2 disjoint, route through `Coordinator._handleSocietyBatch` instead of `_handleParallelBatch`. Existing star + `_handleParallelBatch` paths untouched when off. |
| `platform_core/orchestration/review_mixin.py` | `_remediationTreeShared`: when Epic 1 worktrees are active each worker has its own tree → returns `False` (remediation ON). Co-designed with Epic 1; until then unchanged. |
| `platform_core/core/contracts.py` | Add cross-module TypedDicts: `BlackboardEntry`, `WorkerMessage`, `DebateVerdict`. (Role specs stay in `society/roles.py`.) |
| `config.py` (`config_llm.py`) | Add `SOCIETY_ENABLED=False`, `SOCIETY_MAX_WORKERS`, `SOCIETY_DEBATE_MAX_ROUNDS`, `SOCIETY_ROLE_MODELS`, `SOCIETY_TOKEN_BUDGET_USD`, `BLACKBOARD_DIR`. |
| `agents/executor_env.py` | `_composeWorkflowPrompt` gains a guard comment noting the society path supersedes it when `SOCIETY_ENABLED`; no behavior change when off. |
| `docs/ARCHITECTURE.md` | Add the society to the agent roster + a "Workforce topology" section; note blackboard ownership row in the source-of-truth table. |
| `AGENTS.md` | Regenerate via `python tools/repo_map.py` after the new modules land. |

### New tests

`tests/test_society_blackboard.py`, `tests/test_society_coordinator.py`, `tests/test_society_debate.py`, `tests/test_society_roles.py`.

---

## 6. Error handling + containment (livelock guards)

- **Worker crash:** contained by the existing `_handleParallelBatch` try/except (re-used by `_handleSocietyBatch`): the subtask flips `failed`, a `subtask_crashed` notification is recorded, peers continue. With Epic 1 worktrees, a crash cannot corrupt peers' trees.
- **Worker stall:** per-worker `runClaude(timeout=...)` (`config.CLAUDE_CLI_TIMEOUT_SECONDS`) + process-tree kill already exist; the coordinator additionally caps wall-clock per role.
- **Double-claim race:** prevented by the CAS claim on task JSON under `_state_lock` (guild semantics). Rowcount-0 ⇒ lost race ⇒ re-read. Two workers never edit the same subtask.
- **Debate livelock:** `SOCIETY_DEBATE_MAX_ROUNDS` cap + diff-hash oscillation ring (loki). On stop, escalate to coordinator; verifier gates the last good state. Never an infinite vote loop.
- **Coordinator livelock:** extend `_livelockGuard` — no blackboard `result`/`done` progress in N iterations ⇒ `AbortRun` (existing 40-no-progress / 2000-iter guard reused).
- **Runaway spawning:** workers **cannot** spawn sub-workers (warp recursion rail); only the coordinator spawns, bounded by `SOCIETY_MAX_WORKERS` (≤ run `parallelism`).
- **Cost runaway:** per-run token/USD budget governor (agentscope `_budget` pattern) reading `result.cost_usd`; on breach the coordinator stops spawning new workers and finalizes with what landed.
- **Blackboard corruption:** malformed JSONL lines skipped + warned (bernstein); append-only ⇒ no torn updates; `flock` serializes cross-process writes.

---

## 7. Testing strategy

Deterministic multi-agent testing without real Claude/Ollama:

- **FakeWorker injection:** `WorkerAgent` takes an injectable `run_fn` (default `runClaude`); tests pass a scripted `run_fn` returning canned `result` dicts — exercises claim → post → collect with zero subprocesses.
- **Blackboard concurrency:** spawn N threads appending to one `Blackboard`; assert append-only ordering, no lost lines, `flock` atomicity, malformed-line tolerance. Pure-Python, fast.
- **Claim race:** two `WorkerAgent`s CAS-claim the same subtask against a real `TaskState`; assert exactly one wins, loser re-reads. Deterministic via `_state_lock`.
- **Disjointness scheduling:** given a ready-set with overlapping file-sets, assert the coordinator batches only disjoint subtasks (stub the Epic 1 disjointness fn).
- **Debate convergence:** scripted votes via a fake arbiter (monkeypatch `second_brain.consult`); assert convergence on consensus AND on round-cap AND oscillation-stop. No network.
- **Speaker selection:** deterministic `selectNextSpeaker` over a fixed blackboard thread → fixed next speaker.
- **Society-off invariance:** with `SOCIETY_ENABLED=False`, assert `runExecutionLoop` behaves byte-identically to today (golden test on the star path).
- **Focused loop:** `python tools/dev.py check society/blackboard.py` (etc.) per file; `python tools/dev.py fast` before handoff. Tests are pytest-only (conftest sandbox; never bare unittest — live `.env` creds).

---

## 8. Risks, sequencing, Epic 1 dependency

**Risks**
- **Cost explosion** (N specialized agents × Claude calls vs one Claude). Mitigations: `SOCIETY_MAX_WORKERS` cap, per-run `SOCIETY_TOKEN_BUDGET_USD` governor, role-scoped cheap models (researcher → haiku-tier), debate round cap, society engaged only for multi-deliverable goals with ≥2 disjoint subtasks.
- **Coordination overhead > benefit** on small goals. Mitigation: society is opt-in and gated on disjoint-ready ≥2; single-deliverable goals stay star (`_singleDeliverable`).
- **Windows process limits.** Worktrees + multiple `claude` subprocesses multiply OS handles; `ThreadPoolExecutor(max_workers=parallelism)` already bounds concurrency, and `SOCIETY_MAX_WORKERS ≤ parallelism`. New-process-group + tree-kill (`executor_stream.py`) already handle Windows teardown.
- **Blackboard vs state drift.** Mitigated by strict ownership: task JSON owns status, blackboard owns artifacts; CAS claim is on task JSON only.

**Sequencing within the epic**
1. `society/blackboard.py` + contracts (self-contained, fully testable alone) — the smallest, highest-corroboration steal (bernstein rank-5).
2. `society/roles.py` + `society/worker.py` (role-scoped `runClaude` wrapper) — additive, no loop change.
3. `society/coordinator.py` + `_handleSocietyBatch` wiring (flag default OFF).
4. `society/debate.py` (reuses `second_brain.consult`).
5. Flip remediation ON under society once Epic 1 worktrees land.

**Dependency on Epic 1 (Durable Execution — worktrees + disjointness)**
- Epic 5 is **transformative-first but co-designed with Epic 1's worktree seam.** Today `review_mixin.py::_remediationTreeShared` returns `True` whenever `parallelism>1` because all workers share one real edit tree, so a remediation snapshot/`git checkout` would clobber peers — that is why remediation is disabled under parallelism. Epic 5's full value (parallel specialized workers writing disjoint files **with remediation ON**) requires Epic 1's **per-worker git-worktree isolation + file-disjointness CAS** (steal #5: guild `bounties.go`/`accept.go` + bernstein `core/sandbox/` + claude-code `EnterWorktree`). 
- **Standalone fallback:** without Epic 1, Epic 5 ships in **"shared-tree advisory" mode** — the blackboard, roles, debate, and coordinator all run, but workers execute **serially** in the shared tree (remediation still disabled, `_remediationTreeShared` unchanged). This delivers the coordination + debate surfaces immediately; flipping to true parallel-with-remediation is a one-line change to `_remediationTreeShared` once worktrees exist.
- **Composition with Epic 1's trajectory trace:** every `BlackboardEntry.span_id` links to the Epic 1 JSON span-tree (steal #7), so the blackboard becomes a *queryable, replayable* record of who-proposed-what — the coordination layer and the trace layer share one provenance spine.

---

## 9. Success criteria (measurable)

1. **Parallel specialized workers on disjoint files with remediation ON:** on a multi-deliverable benchmark goal, ≥2 distinct roles (e.g. coder + tester) run concurrently in their own worktrees editing disjoint file-sets, and `_remediationTreeShared` returns `False` (adversary remediation runs under parallelism) — the exact thing impossible today.
2. **No double-claim:** under the claim-race test, exactly one worker ever owns a subtask; zero conflicting edits to the same subtask across 100 randomized runs.
3. **Blackboard integrity:** append-only JSONL survives N-thread concurrent append with zero lost/torn lines and tolerates injected malformed lines.
4. **Debate determinism:** the debate test converges deterministically on consensus, round-cap, and oscillation-stop with a scripted arbiter (no flakiness).
5. **Quality non-regression:** the society path produces an equal-or-higher verifier pass-rate than the star path on the multi-deliverable benchmark, within the `SOCIETY_TOKEN_BUDGET_USD` cap.
6. **Off-path invariance:** with `SOCIETY_ENABLED=False`, the star path is byte-identical to pre-epic behavior (golden test green).
7. **Observability:** every society action appears live on the existing web/Discord surfaces via mirrored `event_bus` events, and is durably reconstructable from `state/blackboard/<task_id>.jsonl`.
