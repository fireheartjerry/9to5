# Theme: Orchestration & Planning

> Cross-repo synthesis for 9TO5's #1 gap. Covers planning, replanning, task
> decomposition, task graphs/DAGs, HTN/search, and role pipelines/SOPs.
> Pulls the best techniques from all 23 harvested repos. READ-ONLY analysis.

## 1. Theme intro + how 9TO5 does this today

Orchestration/planning is the act of turning a one-sentence goal into a reliable,
dependency-aware, executable plan and then *re-deriving* that plan as reality
diverges. **This is 9TO5's single biggest weakness.** Today the pipeline is a fixed
linear chain — `elaborator → architect (Claude writes a design doc) → planner` — where
the planner is **one Ollama JSON call plus one self-critique pass**
(`OrchestratorPlanMixin.authorSubtaskPlan` → `critiqueSubtaskPlan` in
`platform_core/orchestration/plan_mixin.py`), governed by `ORCHESTRATOR_CONSTITUTION`,
producing 1–4 subtasks (`MAX_SUBTASKS`). Phases are sequenced in
`run_phase_mixin.py::_freshRunPhase` and executed by `run_loop_mixin.py::runExecutionLoop`;
replanning is per-subtask add/remove (`_applyReplan`) plus horizon-fill backfill
(`_backfill`/`_continueAfterDrain`); `depends_on` lives in `state/task_schema.py` and is
honored by `state.nextActionable`.

**Where it's weak (from the brief).** Planning is shallow and brittle: one-shot LLM
decomposition with **no tree-search / HTN / look-ahead / cost-budgeted planning**, the
whole layer bottlenecked on a 7B brain whose JSON is unreliable — so the code is
saturated with fallback scaffolding (empty-planner re-derivation, "brain authored no
batch" open-ended fallback). The planner **does not really author `depends_on` graphs**;
replan is **greedy title-dedup add/remove**, not a re-derivation of the task graph; and
there is **no notion of subtask cost/risk in scheduling**. The fix the brief asks for:
iterative or search-based **decomposition-with-verification** that yields reliable task
graphs with dependencies, runnable on a weak brain.

## 2. Ranked technique table (best across all repos, deduped)

Rank 5 = highest fit/leverage for the planning gap; effort = idea-only / port-code / heavy.

| # | technique | source repo (best) | what it does | 9to5-fit | steal-effort | rank |
|---|---|---|---|---|---|---|
| 1 | **Magentic-One dual ledger** | autogen (also ms-agent-framework) | Outer **Task Ledger** (facts: given/look-up/derive/guess + bullet plan) vs inner **Progress Ledger** (one small JSON/step: `is_request_satisfied`, `is_in_loop`, `is_progress_being_made`, `next_speaker`, `instruction`); stall counter → root-cause fact+plan rewrite | Replaces brittle one-shot 7B plan AND greedy replan with iterative facts+plan + per-step re-assessment; decomposes the giant-JSON problem into many *small reliable* JSON judgments a 7B can emit. Prompts copy-pasteable | port-code | 5 |
| 2 | **Vertical-slice plan shape-check + corrective re-prompt** | bernstein | Deterministic post-LLM validator rejects coarse/horizontally-layered plans (LOC/files/≥2-layers-per-slice caps); on violation re-prompts the brain **once** with a structured violation report, else accepts | The "decomposition-with-verification" the brief names; a cheap deterministic gate that raises plan quality **without trusting the 7B more** — exactly 9to5's structural ceiling. Same "deterministic scheduler / replaceable intelligence" thesis | port-code | 5 |
| 3 | **Plan/Task dependency DAG + topo sort + cascade reset** | metagpt | Tasks carry `dependent_task_ids`; plan topologically sorts, tracks `current_task`; `reset_task` recursively invalidates downstream dependents on replan | Gives the **real `depends_on` graph + cascading replan** 9to5's planner barely authors; replaces title-dedup add/remove with graph re-derivation | port-code | 5 |
| 4 | **Two-stage planner→builder + structural validation** | dify | Short PLANNER call emits node list → structured BUILDER call emits full DAG JSON → validate (cycle / dangling-id / unresolved-ref / unknown-tool, classified fixable-vs-user) before running | Complete *plan→expand→validate* pipeline that makes an LLM a reliable task-graph emitter; `graph_topology.py` BFS reusable for honoring `depends_on` | port-code | 5 |
| 5 | **Typed execution DAG (work/gate/fork/join/conditional)** | agx | First-class node types + `hard/soft` edges with `on_success/on_failure/always` + per-graph `ExecutionPolicy` (concurrency, replan/verify budgets, priorityMode=fifo/critical_path/shortest_first, node/graph timeouts) + `DoneCriteria` | The **cost/risk-aware scheduling** 9to5 lacks ("no notion of subtask cost/risk"); fork/join enable parallel batches that today clobber one tree | port-code (TS→Py) | 5 |
| 6 | **Just-in-time hierarchical decomposition + schedule-splice replan** | generative-agents | Top-down daily→hourly→on-demand: decompose a block only when about to execute it (~2h horizon); on interrupt, **freeze executed prefix, insert new action, re-derive only the remaining tail** | Multi-level decomposition vs one-shot; the "freeze done prefix, re-plan only the unexecuted tail" recipe directly fixes brittle planner + greedy replan thrash | port-code | 5 |
| 7 | **ActionNode structured-artifact + auto_review/auto_revise** | metagpt | Typed field tree → compiled JSON/markdown schema → LLM fill → pydantic-validate → **per-field self-review against each field's own requirement** → re-fill | Schema-validated brain output (vs loose-JSON salvage in `brain_io._chatJson`) + structured spec-vs-output check baked into authoring | port-code | 5 |
| 8 | **ValidationError → RetryPrompt structured self-correction** | pydantic-ai | On schema-invalid output, serialize exact Pydantic field errors into a `RetryPromptPart` fed back next turn; bounded retry budget; lenient `T \| Json[T]` + markdown-fence strip | Attacks the root cause of 9to5's fallback-tax: hand the 7B its *exact* errors instead of blind re-prompt. Smallest, most surgical fix for unreliable JSON | port-code | 5 |
| 9 | **plan_and_act iterative planner loop** | metagpt | WritePlan → precheck validity → (review) → update plan → execute task → confirm/replan, repeat | Iterative decompose-validate-execute-replan vs 9to5's one-shot + single critique | port-code | 4 |
| 10 | **Two-doc PRODUCT.md + TECH.md spec template** | warp | Behavioral spec (goals/non-goals/success criteria/validation) + tech spec (pre-resolved `file:line` anchors, numbered changes, **phased plan**, risks+mitigations, testing) | A reviewable, phased decomposition artifact the architect/elaborator could emit; phases = resumable subtask boundaries; validation section = verify rubric | port-code (template) | 4 |
| 11 | **GraphFlow DiGraph (conditional edges + all/any joins + cycle-exit validation)** | autogen | Real task DAG: edges carry string/callable conditions, activation groups with all/any join semantics, start/leaf detection, **every cycle must have a conditional exit** | Genuine dependency graph with branching/join; the cycle-with-exit check is a safety win for replan loops | port-code | 4 |
| 12 | **Dependency-aware task graph as incrementally-editable LLM tools** | agentscope | `Task{blocks, blocked_by, owner, status}`; brain authors/mutates the graph via `TaskCreate/Update/Get/List` (bidirectional edge consistency) instead of one upfront blob | Incremental, dependency-honest planning the executor refines as it learns; `owner` is the seam for multi-worker claiming | port-code | 4 |
| 13 | **Cascade-unblock dep graph + upstream-result passing** | guild (also swarmclaw) | On task done: recompute done-set, flip blocked→ready for tasks whose deps are fully satisfied, emit `unblocked` event; swarmclaw injects completed-dep result previews into dependents | Readiness propagation for a real graph; result-passing = lightweight blackboard so parallel subtasks share output | port-code | 4 |
| 14 | **Scheduler with budgets / priority / timeouts** | agx | `tick()` promotes only dependency-satisfied nodes up to maxConcurrent; policy carries replan/verify budgets, priorityMode (critical_path/shortest_first), node/graph deadlines | Caps runaway loops; adds the cost/risk-aware scheduling dimension 9to5 has none of | port-code | 4 |
| 15 | **Robust JSON extraction ladder** | autogen (also dify) | `extract_json` + `max_json_retries=10` escalating client modes (structured_output → json_output → free text), key/shape validation, single-agent shortcut; dify adds `json_repair` + corrective-retry hint | Hardens 9to5's weak-7B JSON planning beyond the ad-hoc salvage; principled fallback ladder | idea-only | 4 |
| 16 | **Stall/loop counter → outer-loop replan trigger** | autogen (also loki, swarmclaw) | `n_stalls` increments on no-progress/in-loop, decrements on progress; at threshold re-derives facts+plan; loki uses multi-signal oscillation (diff-hash A→B→A ring) + council-split | Principled replan trigger vs 9to5's flat 40-iter livelock guard; feeds the dual-ledger replan | port-code | 4 |
| 17 | **Dual-agent instruct/solve decomposition loop** | owl | Planner agent (no tools) issues one `Instruction:` at a time; executor agent replies `Solution:` with tools; loop until `<TASK_DONE>` — decomposition emerges turn-by-turn | Robust on a weak brain, needs **no valid up-front task graph**; ~250 lines Apache-2.0, portable | port-code | 4 |
| 18 | **Workforce: coordinator + task-decomposer over specialized workers** | owl | `task_agent` decomposes → `coordinator_agent` assigns each subtask to the best-fit worker (own model + scoped toolkit); `process_task` orchestrates | A real decompose-then-route topology vs star-only; per-worker capability scoping | idea-only | 4 |
| 19 | **Watch / cause_by SOP wiring (pub/sub pipeline)** | metagpt | Roles subscribe to upstream **Action types** and react only to messages `cause_by` them; the SOP pipeline emerges from wiring, no central scheduler | Could express 9to5's elaborator→architect→planner→executor chain as declarative watch edges vs hardcoded phase order | idea-only | 4 |
| 20 | **Parent-orchestrator bounded fan-out w/ child-proposed branches** | warp | Baseline explorers run → each returns a *prioritized follow-up plan* → parent dedups overlaps → launches a bounded (≤N) second wave; children forbidden to self-recurse | Coordinated dynamic-spawn planning with an explicit **recursion budget** — safe look-ahead expansion | idea-only | 4 |
| 21 | **Semantic plan cache** | bernstein | Before the planner call, look up a prior similar goal by embedding similarity; on hit, reuse the stored decomposition (records a `cache` metric) | Cuts the slow 7B planner's latency/cost and adds determinism for repeated goals | idea-only | 3 |
| 22 | **TaskType prior-injection registry** | metagpt | Each task type carries a `guidance` prompt; selected type injects human priors (edit/test/refactor/docs heuristics) into the coder's context | 9to5 could tag subtasks and inject per-type playbook guidance beyond the flat invocation spec | idea-only | 3 |
| 23 | **Capability router + scored delegation advisory** | swarmclaw | Classify intent (coding/research/browsing/…) → preferred tools + delegate order; advisory scores candidate agents by capability/role/availability + self-execution penalty → `shouldDelegate` | A real "who/what should do this" routing layer vs single-brain spec authoring | port-code | 3 |
| 24 | **PromptedOutput schema injection for dumb models** | pydantic-ai | Inject the output JSON-schema into instructions via a tested template ("respond with JSON compatible with this schema, no fencing") when the model has no native structured mode | Direct template for forcing clean JSON out of `qwen2.5-coder:7b`; pairs with #8 | idea-only | 3 |
| 25 | **Plan-per-task / separate planning persona** | crewai (also openhands) | Optional `planning=True` adds a `CrewPlanner` pass emitting structured tool-aware `PlanPerTask[]`; openhands gives planning its own condenser + prompt + context budget | A cheap second decomposition layer (author per-subtask step plans) that strengthens `critiqueSubtaskPlan` | idea-only | 3 |
| 26 | **Pre-planning web-research hook** | bernstein | Planner first asks "need to search to plan this? query or NONE"; if a query, runs search and folds results into planning context | Grounds decomposition in fresh docs before committing the task graph | idea-only | 2 |
| 27 | **Duration/cost predictor for budgeted scheduling** | bernstein | Predicts task wall-clock/cost to inform scheduling + preflight budget estimation | Adds the "subtask cost/risk in scheduling" notion 9to5 explicitly lacks | idea-only | 2 |
| 28 | **ToT / solver / search_space scaffolding** | metagpt | Tree-of-Thought planning primitives (search space, thinking commands, solver) | The actual HTN/look-ahead/search the brief lists as missing; heavier and likely overkill for a 7B today | heavy | 2 |

**Dedupe notes.** The **dual-ledger** (#1) is identical in autogen and ms-agent-framework — autogen has the more readable prompts. **Dependency-DAG + cascade replan** appears as metagpt (#3, cleanest Python), agx typed-DAG (#5, richest schema), autogen GraphFlow (#11, best conditional/join semantics), agentscope editable-tools (#12), guild/swarmclaw cascade-unblock (#13), plus crewai Flow DSL, langgraph subgraph-nesting, pydantic-graph, ms-agent-framework builder — all the same idea at different fidelity; **port metagpt's for the schema, steal agx's budget/timeout policy and autogen's cycle-exit check.** **Structured-JSON reliability** is pydantic-ai (#8, best), autogen (#15), dify (#15), plus metagpt ActionNode (#7), openclaw tool-call-repair, agentscope structured-output, generative-agents `safe_generate_response` — one family. **Stall→replan** is autogen (#16), loki (multi-signal), swarmclaw supervisor — autogen's is the canonical form.

## 3. If 9TO5 adopts ONE thing for this theme

**Adopt the Magentic-One dual-ledger orchestrator** (`autogen` —
`autogen-agentchat/.../_magentic_one/_magentic_one_orchestrator.py` + `_prompts.py`),
replacing `authorSubtaskPlan`/`critiqueSubtaskPlan` and the greedy `_applyReplan`.
The reason it's the top pick over a richer DAG engine (agx) or a deterministic gate
(bernstein) is structural: 9TO5's ceiling is a 7B brain that cannot reliably emit one
large correct plan JSON — and the dual-ledger **dissolves that exact problem** by
splitting planning into a stable outer *Task Ledger* (facts: given / look-up / derive /
guess, plus a bullet plan) and a tiny inner *Progress Ledger* that asks the brain one
small, schema-bounded JSON question per step (`is_request_satisfied`, `is_in_loop`,
`is_progress_being_made`, `next_speaker`, `instruction`), with a stall counter that
triggers a root-cause facts-and-plan rewrite. That is "iterative
decomposition-with-verification" (the brief's literal ask) built from many *small
reliable* model calls instead of one brittle big one, and it upgrades **planning and
replanning together** — the per-step progress judgment is precisely the brain
re-assessment 9TO5 lacks, and the stall-driven rewrite is a principled replacement for
title-dedup add/remove. The prompts are copy-pasteable into `ORCHESTRATOR_CONSTITUTION`,
and it composes cleanly with the two best supporting steals: wrap each emitted plan in
**bernstein's deterministic vertical-slice shape-check + one corrective re-prompt** (gate
quality without trusting the 7B more) and persist the plan as **metagpt's
`dependent_task_ids` DAG with cascading `reset_task`** so `depends_on` finally becomes a
real, re-derivable graph rather than a barely-authored field.
