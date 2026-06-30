# Theme: Observability — structured span-tree tracing, gen_ai cost metrics, threshold alerting, trajectory replay, trace-assertion DSLs

> Cross-repo synthesis for 9TO5 gap #5. Sources: all 23 per-repo digests under
> `docs/references-harvest/`, with code dives into `references/{eliza,pydantic-ai,openclaw,swarmclaw}`.
> READ-ONLY harvest — nothing here is wired into 9TO5 yet.

## 1. Theme intro + how 9TO5 handles this today

Observability for an autonomous agent run means: a **structured span tree** of the run
(Goal → subtask → ExecutionStep → model-call / tool / verify), a **consistent per-step
token/cost metric series**, **threshold alerting** on cost/error/stall, the ability to
**record a trajectory and replay a failed attempt**, and ideally a **trace-assertion
language** so verification can assert facts about *what actually executed* rather than
scanning source text.

**9TO5 today** has a rich *presentation* layer and almost no *trace* layer. One
process-global nervous system (`notifications/event_bus.py` `LiveEventBus` ring buffers +
SSE), `notifications/subprocess_feed.py` taps Claude stdout JSONL into tool events + a 30s
heartbeat, `notifications/webdash*.py` serves a live terminal-style page, and Discord
dashboards/embeds + narrative surfaces (`run_arc.py`, `narration.py`, `health_aura.py`)
dramatize the run. Hook-driven telemetry (`tools/claude_metrics.py`) and the
`experience.db` ledger persist some signal, and `agents/trace_replay*.py` exists for replay.
**Where it's weak** (per the brief, §2.7): there is no distributed **span tree** spanning a
run — the executor is a Claude subprocess with *no trace continuity* back to the
orchestrator; per-step token/**cost is captured opportunistically** (`cost_usd` when it
happens to be available), not a consistent metric series; there is **no threshold alerting**
(no cost ceiling, error-rate, or stall alarm beyond a flat 40-iteration livelock guard);
logs are explicitly forbidden as a source of truth; and **failed-attempt replay** is limited
because there is no durable per-step journal of what the executor actually did. The
machinery is theater-heavy and trace-poor.

## 2. Ranked technique table (best across all repos)

Rank 5 = highest-value steal for this theme. "best-in" = the repo that does it best when
several overlap. Effort: idea-only / port-code / heavy.

| # | technique | source repo (best-in) | what it gives | 9to5-fit | steal-effort | rank |
|---|---|---|---|---|---|---|
| 1 | **JSON span-tree trajectory recorder w/ per-call token+USD cost + parent→child spawn linking** | **eliza** (`packages/core/src/runtime/trajectory-recorder.ts`, `features/trajectories/pricing`, `services/spawn-trajectory`) | One JSON file per run = an append-only span tree of typed stage kinds (planner/tool/toolSearch/evaluation/subPlanner/compaction); each model call records `RecordedUsage` (incl. cache tokens) + `costUsd` from a snapshot-versioned price table (`priceTableId`); local-inference records a **real 0** (not "missing"); atomic tmp+rename; **never crashes the runtime**; parent step id propagated across the spawn boundary (`ELIZA_PARENT_TRAJECTORY_STEP_ID`) so a child subprocess stitches into the parent tree. | Directly fills gap #5: structured span tree + consistent cost series; the spawn-linking solves 9TO5's Claude-subprocess trace-continuity hole; file-based + never-crash matches 9TO5's file-state, no-logs-as-truth ethos; Ollama records 0 cost but keeps the token series. | port-code | **5** |
| 2 | **Per-agent rolling cost budgets (h/d/m) with 80% warn + hard exceed** | **swarmclaw** (`src/lib/server/cost.ts`); also metagpt `team.py` NoMoneyException, agentscope `middleware/_budget.py`, eliza `spend-allowance.ts` | Rolling hourly/daily/monthly spend windows over a usage ledger + model cost table; warn-at-80%, hard-stop on exceed; tagged-record + double-count guard. The **threshold-alerting** piece the brief says is absent. | High: pairs with #1's cost series to give cost ceilings + alerts per run/subtask; 9TO5 has no budgets or alerts today. | port-code | **5** |
| 3 | **SpanQuery / SpanTree trace-assertion DSL** | **pydantic-ai** (`pydantic_evals/otel/span_tree.py`, `evaluators/common.py:HasMatchingSpan`) | A serializable TypedDict query language over a span tree: `name_matches_regex`, `has_attributes`, `min/max_duration`, `some_child_has`, `no_descendant_has`, `min_depth`, logical `and_/or_/not_`, `stop_recursing_when`. Lets a verify assert *behavioral* facts about the trace ("a test-run span exited 0", "no tool ran > N s"). | High and near-unique: turns the span tree from #1 into a verification surface (also hits gap #2) — assert what executed, not what strings appear in source. | port-code | **4** |
| 4 | **Record/replay gateway for every LLM + tool dispatch** | **bernstein** (`core/replay/gateway.py`); also openclaw versioned JSONL + export manifest, langgraph time-travel | `dispatch(kind,key,invoke)` wraps every provider/tool call; RECORD appends `(kind,key,response)` to per-run `events.jsonl`, REPLAY serves recorded responses without calling the provider; stable hashed keys + FIFO fallback for jittered prompts; ordering preserved. Deterministic **failed-attempt replay** + offline debugging + a test-fixture engine. | High: gap #5's "failed-attempt replay" done right; also a regression-test substrate over `experience.db`. | port-code | **4** |
| 5 | **OTel `gen_ai.*` semantic-convention spans + metrics, trace-context propagated through messages** | **ms-agent-framework** (`core/agent_framework/observability.py`); near-identical in **autogen** (`_telemetry/_genai.py`), **agentscope** (`middleware/_tracing/*`), **pydantic-ai** (`_instrumentation.py`), **swarmclaw** (`observability/otel-tracing.ts`) | Standardized span attrs + token-usage counter + operation-duration histogram (cache/reasoning token splits); W3C `trace_contexts` ride on each message (plural, for fan-in) so spans link across executors. Standard schema → off-the-shelf Jaeger/Grafana/Phoenix backends + alerting. | High *if* 9TO5 wants a standard backend; heavier and async-centric vs 9TO5's single-host file model. Adopt the **schema** (`gen_ai.*` attrs) even if not the OTel SDK. | port-code/heavy | **4** |
| 6 | **Per-role / per-model cost attribution by `usage_id`** | **openhands** (`utils/llm_metadata.py`, `live_status_*:1371`); also claude-code `cost-tracker.ts` (persist/restore across resume), hermes `agent/insights.py` (cache-aware pricing) | Every LLM (agent / condenser / planning) carries a distinct `usage_id` + metadata `{conversation_id, llm_type}` so spend is broken out per role; claude-code's tracker persists+restores cost state across resume. | High: lets 9TO5 attribute cost to brain vs executor vs adversary vs second-brain; resume-safe cost series. | port-code | **4** |
| 7 | **Run-as-attempt ledger + structured commit-as-event journal** | **gnap** (spec; `runs/*.json`); realized in **loom** (post-tool auto-commit), **claude-code** (`fileHistory.ts`), **openhands** (event-stream-as-journal) | Each execution *attempt* is its own immutable record (tokens, `cost_usd`, timings, `commits[]`, `artifacts[]`, `error`), decoupled from the task: "failed run ≠ failed task, sum-of-runs = budget." A `<agent>: <action> <entity>` commit per step makes git history a tamper-evident, replayable step journal. | High framing fit: cleaner than 9TO5's opportunistic `cost_usd`; doubles as the gap #3 step journal. | idea-only/port-code | **4** |
| 8 | **Granular runaway/stall detection (7 tool-loop detectors)** | **swarmclaw** (`src/lib/server/tool-loop-detection.ts`); also loki uncertainty-gated escalation, eliza task-watchdog | Pre-call `preview` + post-call `record` across circuit-breaker, per-tool frequency, generic-repeat, polling-stall, ping-pong, output-stagnation, error-convergence — each ok/warn/critical with injected guidance. | High: upgrades 9TO5's flat 40-iteration livelock guard into multi-signal alerting feeding remediation. | port-code | **4** |
| 9 | **Self-measuring hint/eval engine (follow-through scoring)** | **guild** (`internal/hints/engine.go`) | A nudge fires when an agent breaks contract, then the engine **measures whether the agent actually followed through within N calls** and persists hit/miss — a built-in eval loop for whether guidance changes behavior. | Novel: 9TO5 has presentation but no mechanism that grades whether its own constitution/playbook guidance moves the executor. | port-code | 3 |
| 10 | **Closed-set failure taxonomy + signed drift** | **bernstein** (`eval/taxonomy.py`, `core/orchestration/failure_taxonomy.py`) | Classify every failure into 8 fixed categories via priority-ordered rules; aggregate counts and compute signed **drift** vs the previous run. Deterministic, cheap, feeds replan + alerting. | High: `experience.db` stores failures but has no taxonomy/drift series for trend alerting. | port-code | 3 |
| 11 | **Versioned trajectory trace + replay export bundle/manifest** | **openclaw** (`src/trajectory/{types,runtime,export}.ts`) | Single JSONL schema (`schemaVersion`, `traceId`, `seq/sourceSeq`, `entryId/parentEntryId`, runtime-vs-transcript source) + an export **manifest** with event counts and parse-warning rows, built for external replay-debugging. | High: schema-versioned, parent/seq-linked alternative to #1 if 9TO5 prefers JSONL streaming + an export bundle. | port-code | 3 |
| 12 | **Async batched trace pipeline + unified `*TraceInfo` schema** | **dify** (`core/ops/ops_trace_manager.py`) | Typed `*TraceInfo` per activity (Workflow/Node/Tool/Retrieval/Message); `TraceQueueManager` batches (size 100 / 5s) and fans out to pluggable APM backends; `@trace_span` decorator + `_propagate_otel_context` re-attaches parent context **inside threadpool workers**. | High for 9TO5's `ThreadPoolExecutor` parallel subtasks — spans survive the fan-out; decouples cheap emission from delivery. | port-code | 3 |
| 13 | **Per-artefact lineage (Sigstore-style transparency log) + per-call cost meter w/ predictive alerts** | **bernstein** (`core/lineage/`, `core/observability/{cost_meter,slo,predictive_alerts}`) | Every file write records producer + inputs + prompt SHA + model + cost, chained + verifiable; provider responses wrapped in a cost+observability envelope with SLO tracking, predictive alerts, circuit breakers. | Strong direction for "what did this action actually do" attribution + alerting; heavier than 9TO5 needs now. | heavy | 3 |
| 14 | **Loki OTEL span tree (project→task→rarv→gate/agent/council) + Evidence Receipt facts-vs-assessments** | **loki-mode** (`src/observability/spans.js`, `autonomy/lib/proof-generator.py`) | A lightweight typed child-span hierarchy with status codes, plus a deterministic per-step proof artifact whose green headline derives only from re-derivable **facts** (diff sha, exit codes, gate verdicts), LLM opinions fenced as non-binding. | Good: the span hierarchy maps onto Goal→subtask→step→verify; the receipt is a per-step audit artifact (overlaps gap #2). | port-code | 3 |
| 15 | **Typed per-tool execution status + engine-call trace events** | **agx** (`lib/storage/events.js`); **loom** (`ToolExecutionStatus`) | NDJSON `ENGINE_CALL_STARTED/COMPLETED` carrying `trace_id`, provider/model/role, pid, `duration_ms`, `exit_code`, stdout/stderr tails; per-tool Pending→Running→Completed status records. | Direct: structured per-step span series with trace_id correlation, replayable not theatrical. | port-code | 3 |
| 16 | **Per-round token accounting + resumable checkpoint-after-task runner** | **owl** (`enhanced_role_playing.py::run_society`, `gaia.py::run`) | Sums prompt/completion tokens per round into `token_info`; benchmark runner checkpoints results JSON after each task and skips completed ids. | Modest: simple consistent per-step token series; coarser than #1. | idea-only | 2 |
| 17 | **Critical/observability write split + privacy-by-construction telemetry** | **guild** (`internal/quest/accept.go::writeAcceptTrail`, `internal/telemetry/usage.go`) | The core operation commits alone; the observability event/trail goes in a separate retrying tx whose failure only logs — telemetry loss can never abort a run action. Telemetry `Record()` signature structurally cannot log content. | Good principle for 9TO5's event_bus so a feed write never kills a run; the atomic-append pattern is reusable. | idea-only | 2 |
| 18 | **Typed event spine w/ first-class checkpoint/llm-cost event types** | **crewai** (`events/types/*.py`, `telemetry/telemetry.py`) | One bus emits typed `flow/llm/memory/checkpoint/agent` events; `checkpoint_events` and llm-cost spans are first-class types consumed by tracing/OTEL listeners. | 9TO5 already has an event bus; steal the **typed taxonomy** (cost/checkpoint spans) to build a span tree instead of presentation events. | idea-only | 2 |

**Dedup notes.** Structured trajectory/span recording is independently reinvented by eliza
(#1, best — typed stages + price table + spawn linking + never-crash), openclaw (#11, best
schema-versioned JSONL + export bundle), openhands (event-stream-as-journal), agx (#15,
best NDJSON engine-call events), loki (#14), and loom. **eliza is the best-in for the span
tree because it natively handles local inference, atomic non-crashing writes, and
cross-process spawn linking — exactly 9TO5's shape.** OTel `gen_ai.*` semantics are shared
by ms-agent-framework / autogen / agentscope / pydantic-ai / swarmclaw — **ms-agent-framework
is best-in** for the cache/reasoning token splits + trace-context-through-messages fan-in
linking. Cost budgets/alerting appear in swarmclaw (#2, best — h/d/m windows), metagpt,
agentscope, eliza spend-allowance, bernstein. Trajectory replay: bernstein record/replay
gateway (#4, best — deterministic dispatch wrapper) vs langgraph time-travel vs openclaw
export bundle. The trace-assertion DSL (#3) is **unique to pydantic-ai** — no other repo
ships a serializable query language over a span tree.

## 3. If 9TO5 adopts ONE thing for this theme

**Port eliza's JSON span-tree trajectory recorder with per-call token/USD cost and
parent→child spawn linking** (`references/eliza/packages/core/src/runtime/trajectory-recorder.ts`
+ `features/trajectories/pricing` + `services/spawn-trajectory.ts`) as the canonical run
trace, written per-run as `RecordedStage` nodes (planner / tool / evaluation / subPlanner /
compaction) under `state/trajectories/<run>/`. It is the single highest-leverage steal
because it is the one mechanism that produces *all three* missing pieces at once — a real
span tree, a consistent per-step token/cost series, and the durable artifact that makes
failed-attempt replay possible — and it fits 9TO5's constraints almost exactly: it is
file-based with atomic tmp+rename and **never crashes the runtime** (matching the
no-logs-as-truth, file-state ethos), it records a **real `0` cost for local Ollama
inference** while still capturing the token series (so the metric is honest, not "missing"),
and its `ELIZA_PARENT_TRAJECTORY_STEP_ID` spawn-linking is the direct cure for 9TO5's worst
observability hole — the Claude executor subprocess having no trace continuity back to the
orchestrator. Once that span tree exists, the rest of the theme bolts on cheaply: layer
**pydantic-ai's `SpanQuery` DSL** (`pydantic_evals/otel/span_tree.py`) so verifies assert
behavioral facts about the trace, and **swarmclaw's per-agent cost budgets**
(`src/lib/server/cost.ts`) so the now-consistent cost series drives 80%-warn / hard-stop
threshold alerting — turning 9TO5's presentation-heavy theater into an actual, queryable,
cost-aware, replayable trace spine.
