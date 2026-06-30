# Theme: agent-comms-topology

> Cross-repo synthesis for 9TO5 gap #7 (multi-agent communication, blackboard / shared
> scratchpad, pub/sub message pools, coordinator/worker, handoffs, debate, parallel-safety,
> A2A). Read-only harvest across all 23 reference repos. Source: `_9to5-brief.md` §2.4 + §3.7
> and the per-repo digests in `docs/references-harvest/*.md`.

## 1. Theme intro + how 9TO5 handles this today

Multi-agent topology is *how* the agents in a system talk: through a hub, through a shared
board, through direct messages, through handoffs, or through a protocol. **9TO5 today is a
pure star** (`docs/ARCHITECTURE.md` roster). Every agent — elaborator, architect, planner,
executor, verifier, adversary, replanner — communicates only through the orchestrator and the
canonical task-JSON state (`state/task_schema.py`); there is **no peer-to-peer channel and no
shared scratchpad**. The only fan-out is (a) intra-subtask, delegated wholesale to Claude
Code's own opaque subagent mechanism via the workflow registry (`workflows/registry.py`,
`run_loop_mixin.py::_handleParallelBatch` over a `ThreadPoolExecutor`), and (b) a single
advisory Gemini "second brain" (`agents/second_brain.py`). Cast personas
(`notifications/cast.py`) are cosmetic.

**Where it is weak.** The brief names the failure precisely: concurrent workers **edit one
shared git tree**, so there is no isolation; and because a snapshot/restore would clobber
peers, **adversary remediation is *disabled* under parallelism**
(`execute_mixin.py::_remediationTreeShared`). There is no blackboard for workers to exchange
artifacts, no file-disjointness check to decide what may safely run in parallel, no atomic
claim to stop two workers grabbing the same work, no dynamic spawning, role negotiation,
structured debate, or A2A protocol. The result: parallelism is shallow and *less safe* than
serial execution (it costs you the adversary). Fixing gap #7 means giving parallel workers
(1) **isolation** so they stop clobbering, (2) a **safe claim + disjointness rule** so they
pick non-conflicting work, and (3) a **shared board** so they coordinate — which together
also re-enable remediation under parallelism.

---

## 2. Ranked technique table (best-of across all repos, deduped)

Rank: 5 = highest leverage on 9TO5 gap #7. Effort: idea-only / port-code / heavy.
"Best repo" = the repo that does this technique best; alternates noted.

| # | technique | best source repo | what it is | 9to5-fit | steal-effort | rank |
|---|---|---|---|---|---|---|
| 1 | **File-disjointness parallel-safety + atomic CAS claim** | **guild** (`internal/quest/bounties.go`, `accept.go`) | Two unclaimed tasks may run concurrently **iff their file-sets are disjoint AND neither depends on the other**; claim is a single race-free `UPDATE … WHERE status='next' AND claimed_by IS NULL` (rowcount 0 ⇒ lost race), deliberately not wrapped in a multi-stmt tx. | The exact missing test: lets 9to5 pick provably-non-conflicting subtasks for parallel batches instead of disabling remediation. Pairs with worktrees (#2). *Alt: gnap lock-free claim-via-commit-race.* | port-code | 5 |
| 2 | **Per-worker git worktree isolation (+ merge queue)** | **bernstein** (`core/sandbox/`, merge queue) | Each parallel agent runs in its **own git worktree**; a merge queue serialises landings. Same "deterministic scheduler / replaceable intelligence" thesis as 9to5. | Directly removes the "concurrent workers clobber one tree" pain and re-enables per-worker snapshot/restore → adversary remediation works under parallelism. *Alt: claude-code `EnterWorktreeTool` (9to5 already runs that binary); hermes/openhands process-sandbox.* | port-code (concept; TS/Go→Py) | 5 |
| 3 | **Append-only shared whiteboard (blackboard)** | **bernstein** (`core/communication/whiteboard.py`) | Per-run JSONL scratchpad any agent appends/reads; entries carry `key/scope/value/owner/visibility[roles]/ts_ns`; POSIX `flock` + thread-lock for multi-process atomic appends; role-based read filter; malformed-line tolerant. | The shared scratchpad 9to5 explicitly lacks, and it matches 9to5's file-backed multi-process model (run + bot + web) almost exactly. Smallest, most portable blackboard of the set. | port-code | 5 |
| 4 | **Two-phase-commit shared state (transactional blackboard)** | **MAF** (`_workflows/_state.py`, `_runner_context.py`) | `_committed` dict + `_pending` write buffer; executors `set()` into pending, `commit()` flushes at a superstep boundary, `discard()` rolls back. Last-write-wins on commit; rollback is free. | The cleanest *design* for a blackboard with conflict semantics: concurrent workers stage writes, board resolves at the boundary. More principled than a raw append log; heavier to adopt. *Alt: langgraph channels+reducers.* | port-code | 4 |
| 5 | **Shared message pool + pub/sub by subscription** | **metagpt** (`environment/base_env.py::publish_message`, `roles/role.py::_watch`/`_observe`) | Env broadcasts messages; roles match by `addresses`/`send_to` into a private buffer and react only to messages `cause_by` watched **Action types** — a content-addressed blackboard where the SOP emerges from wiring, no central scheduler. | The canonical message-pool pattern; lets 9to5's pipeline be expressed as watch-edges and lets workers exchange structured artifacts. Bigger architectural shift than #3/#4. *Alt: autogen-core topic/subscription bus.* | port-code | 4 |
| 6 | **Coordinator + task-decomposer over specialized workers** | **owl** (CAMEL Workforce, `examples/run.py`) | Two control agents — `task_agent` (decompose) then `coordinator_agent` (assign) — route subtasks to a roster of single-purpose workers, each with its own model + scoped toolkit. | A real heterogeneous worker topology vs 9to5's star + opaque Claude fan-out; gives a blueprint for capability-routed dispatch. *Best-done alts: metagpt TeamLeader `publish_team_message`; agentscope leader/worker over inbox+wakeup.* | idea-only | 4 |
| 7 | **Subagent swarm primitives (quorum / first / cancel)** | **swarmclaw** (`agents/subagent-swarm.ts`) | Parallel spawn returning `allSettled` / `firstSettled` / `quorumSettled(n, cancelRemaining)` / `cancelAll`; concurrency bucketing via shared exec-locks; persisted snapshots; restart marks in-flight swarms "lost". | Exactly the coordination verbs 9to5's bare `_handleParallelBatch` lacks (first-wins, quorum, cancel-the-losers). *Alt: hermes async delegation via completion queue; bernstein best-of-N.* | port-code | 4 |
| 8 | **Coordinator mode + shared scratchpad dir** | **claude-code** (`coordinator/coordinatorMode.ts`) | Main loop becomes an orchestrator that fans out async workers via the Agent tool, continues them via `SendMessage`, stops via `TaskStop`; results return as `<task-notification>`; workers share a **no-permission scratchpad dir** for durable cross-worker knowledge; explicit continue-vs-spawn-fresh heuristic table by context overlap. | High leverage because **9to5 already runs this exact binary** — much of this is a *configuration* win (drive the executor as a coordinator + scratchpad) not a reimplementation. The continue/spawn matrix maps onto SIE warm-start vs fresh-context. | idea-only | 4 |
| 9 | **Cascade-unblock dep graph that forwards upstream results** | **swarmclaw** (`dag-validation.ts::cascadeUnblock`) / **guild** (`quest/cascade.go`) | On task done, recompute the done-set, flip blocked→ready for tasks whose deps are all satisfied, and **inject completed deps' result previews (`upstreamResults`) into the newly-ready task** — a lightweight blackboard via the dependency edges. | Turns 9to5's greedy title-dedup replan into a readiness-propagating scheduler *and* passes solution content between subtasks (minimal scratchpad) without a full board. | port-code | 4 |
| 10 | **Handoff / swarm routing (decentralized next-speaker)** | **autogen** (`_swarm_group_chat.py`, `HandoffMessage`) | Agents emit `HandoffMessage(target=…)`; the manager simply follows the handoff to set the next speaker — peer-chosen routing, no central planner. | A topology beyond the star: triage-style decomposition where an agent decides who acts next. *Alt: MAF `orchestrations/_handoff.py`.* | idea-only | 3 |
| 11 | **Send / dynamic map-reduce fan-out to a reducer channel** | **langgraph** (`types.py::Send`) | A node returns `Send(node, arg)` objects spawning N parallel instances with *different* per-branch state, aggregated by a reducer channel — the channel **is** the blackboard. | Coordinated parallel workers writing to a shared reducer instead of clobbering one tree; principled conflict-merge. *Alt: MAF Concurrent fan-out + aggregator.* | heavy | 3 |
| 12 | **Secondary-LLM-as-a-tool / debate ensemble** | **loom** (`oracle` tool) / **hermes** (MoA, `agent/moa_loop.py`) | Loom: the primary agent calls an `oracle` tool that consults a *different* model for a second opinion, **peer-level inside the loop** (vs 9to5's orchestrator-side Gemini brain). Hermes: fan out N reference models in parallel (advisory, no tools), flatten transcripts, aggregator acts on the joined advice. | Gives the executor/adversary an in-loop debate channel; the transcript-flattening trick is reusable for "show one model another's work". *Alt: agx multi-provider swarm + aggregator; loki specialist review pool.* | idea-only | 3 |
| 13 | **A2A protocol surface + agent-card discovery** | **swarmclaw** (`src/lib/a2a/*`) | JSON-RPC router (`executeTask`/status), agent cards, `.well-known/agent-card.json` discovery with TTL cache + zod validation + auth. | Standard inter-agent protocol if 9to5 ever exposes agents beyond the star. *Alts: eliza ACP (Agent Client Protocol) pluggable transport; crewai A2A; gnap git-native message/run/task files.* | heavy | 3 |
| 14 | **Cross-task publish/subscribe over tag-indexed memory** | **bernstein** (`core/memory/cross_task_kb.py`) | Explicit `publish(tag,key,value,scope)` / `subscribe(tag,scope)` over SQLite memory; facts carry a lineage triple (producer_task_id, ts_ns, content_hash); run vs project scope; last-write-wins + warning. | A durable, attributable cross-run fact channel — a persistent cousin of the per-run whiteboard; stores actual solution content keyed by tag. | port-code | 3 |
| 15 | **Path-scoped memory as blackboard** | **crewai** (`memory/memory_scope.py`) | `/`-addressed memory tree; `MemoryScope` restricts an agent to a subtree, `MemorySlice` reads across scopes. Shared scope = coordinated scratchpad (workers write `/run/<id>/worker/<n>`, read `/run/<id>/blackboard`). | Clean addressing scheme for a multi-worker board with per-worker private regions. *Alt: agentscope task graph `owner` field for claimable work.* | idea-only | 3 |
| 16 | **Webhook / event-callback pub-sub over an event stream** | **openhands** (`event_callback/*`, `webhook_router.py`) | The sandbox POSTs every event back; registered `EventCallbackProcessor`s fire side-effects with retry + result tracking — decoupled observers over the step stream (a poor-man's blackboard). | Lets observers/alerters/coordinators react to worker events without coupling to the run loop. *9to5 already has `event_bus`; this is the typed-callback discipline on top.* | port-code | 3 |
| 17 | **Bounded parent-orchestrator fan-out with child-proposed branches** | **warp** (`onboarding-verification-skill/SKILL.md`) | Baseline explorers run, each returns a *prioritized follow-up plan*; the parent **dedups overlapping plans** and launches a bounded (≤4) second wave; **children are forbidden from self-recursing** ("record as a later-run suggestion"). | A safe dynamic-spawn pattern with an explicit recursion budget that avoids runaway worker explosions — directly applicable to 9to5 self-improvement backfill. | idea-only | 3 |
| 18 | **Permission inheritance for spawned workers** | **agentscope** (`app/_tool/_agent_create.py::_merge_leader_permissions`) | A spawned worker's permission context = template base merged with the leader's mode/rules/working-dirs per inherit flags, so a worker doesn't re-prompt for grants already given the leader. | Capability scoping for dynamically-spawned 9to5 workers — additive, explicit, no re-approval. | idea-only | 2 |
| 19 | **Capability-scoped isolated children with restricted toolsets** | **hermes** (`tools/delegate_tool.py`) | Child `AIAgent` with fresh context, own terminal, restricted toolset (recursive-delegate/memory/clarify blocked); parent sees only a summary; batch=parallel. | Coordinated parallel workers with per-worker capability scoping; keeps parent context clean — beats opaque Claude subagent delegation. | port-code | 3 |
| 20 | **Agent reputation / sycophancy scoring across reviewers** | **loki-mode** (`swarm/sycophancy.py`, `swarm/bft.py`) | Deterministic 0–1 score over a set of reviewer votes (verdict unanimity + reasoning Jaccard + severity uniformity) that flags rubber-stamping; reputation tracking down-weights a chronically-wrong reviewer. | A usable slice (without full PBFT): score 9to5's brain/adversary/second-brain over time, catch "3 reviewers approved = meaningless". | port-code | 2 |

---

## 3. If 9TO5 adopts ONE thing for this theme

**Adopt guild's file-disjointness parallel-safety rule + atomic CAS claim, executed inside
per-worker git worktrees (bernstein / claude-code `EnterWorktreeTool`).** This is the single
change that converts 9to5's parallelism from "shallow and *less* safe" into "isolated and
fully safe." The brief's stated pain is exact: concurrent subtasks clobber one git tree, so
adversary remediation is disabled under parallelism
(`execute_mixin.py::_remediationTreeShared`). Guild's two rules fix the root cause directly —
two subtasks may run concurrently **iff their file-sets are disjoint and neither depends on the
other** (`internal/quest/bounties.go`), and each is grabbed with a race-free single-statement
claim (`internal/quest/accept.go`) so two workers never collide. Run each claimed subtask in
its **own worktree** (a near drop-in via the very Claude binary 9to5 already drives), and the
per-worker snapshot/restore that remediation needs works again — `_remediationTreeShared` can
be deleted. It is small, deterministic, dependency-light Apache-2.0 code, it needs no stronger
brain, and it composes cleanly with a later blackboard (bernstein's append-only
`whiteboard.py`, rank 3) for richer worker coordination once isolation is in place.
