# Theme: Prompt & Context Engineering

Cross-repo synthesis for the 9TO5 agent-tech harvest. Covers hierarchical
summarization/compaction, tool-pair-preserving compaction, model-input budgeting,
structured context contracts, dynamic tool-group selection, structured-output schemas,
and JSON/markdown-fence repair for weak local models. Source: `_9to5-brief.md` §2.9 / gap
#8, plus all 23 per-repo digests and direct code dives into the repos the digests flagged
as thin.

## 1. Theme intro — how 9to5 handles this today, and where it's weak

9to5's context engineering is, by its own admission, **truncation, not compaction**. Every
brain call runs at a *fixed* `num_ctx` (a deliberate fix for an Ollama reload storm) with the
user payload mechanically trimmed to fit (`llm_mixin.py::_ollamaChat` + `_fitUserToCtx`), and
the long-run artifacts that *would* carry history forward are hard-sliced —
`architect_doc[:1500]`, `[:4000]`, a tiny `RETRIEVAL_MAX_TOKENS`. There is real structure on
the *injection* side (live `CLAUDE CODE CAPABILITIES` block via `knowledge.py::injectCapabilities`,
a per-subtask living `CLAUDE.md` via `memory.obsidian.writeClaudioMd`, a role-scoped
playbook/charter through `--append-system-prompt`, SIE-folded authoring context in
`plan_mixin.py::_sieAuthoringContext`, champion/challenger constitutions in `learning/prompts.py`),
and there is *loose* JSON salvage for the unreliable 7B (`brain_io._chatJson`). But four things
are missing and they compound: (1) **no hierarchical/rolling summarization** of accumulating
run history — old context is dropped by slice, not condensed; (2) **retrieval injects metadata,
not solution content** — the `lessons_block` carries effort/model/attempt counts, not the actual
fix; (3) **no model-input budget** — compaction is never *triggered* by a token estimate, it's a
constant slice; (4) **the JSON-reliability tax** — the planner is "saturated with fallback
scaffolding" because the 7B emits malformed/fenced/double-encoded JSON, and the salvage is ad-hoc.
The small, unreliable 7B context window is therefore the structural ceiling on planning, memory,
and verification alike. This theme is where the most external prior art exists, and most of it is
small, self-contained, and directly portable.

## 2. Ranked technique table (best-of across all 23 repos)

Rank 5 = highest 9to5 value. "best repo" notes where a deduped technique is implemented most
cleanly when several repos share it.

| # | technique | source repo (best) | what it does | 9to5-fit | steal-effort | rank |
|---|---|---|---|---|---|---|
| 1 | **Context compaction with offload** | **agentscope** (`agent/_agent.py::_compress_context_impl`, `_split_context_for_compression`) | When est-tokens > `trigger_ratio*ctx`, split history into compress-vs-reserve by `reserve_ratio`, summarize the old half via a *structured-output* tool call into a `summary`, offload raw msgs to disk with a re-readable breadcrumb; fallback = drop-oldest if the compression itself overflows. | The exact rolling-summarization + ratio math 9to5 lacks; replaces `[:1500]`. Self-contained Python, no framework deps. | port-code | 5 |
| 2 | **Tool-pair-preserving token-share chunking** | **openclaw** (`src/agents/compaction-planning.ts`) | Splits a transcript into ~equal token chunks for summarization but **never separates an assistant `tool_use` from its `tool_result`**; adaptive chunk ratio shrinks chunks when avg message is large; oversized single messages get placeholder notes. Prevents "orphaned tool_result" API errors. | The chunking invariant any 9to5 compactor needs once executor tool-event history is summarized. | port-code | 5 |
| 3 | **MUST-PRESERVE structured summary contract** | **openclaw** (`src/agents/compaction.ts`; branch-summarization.ts) | Summary prompt with an explicit `MUST PRESERVE` list (active tasks+status, batch progress "5/17", last user request, decisions+rationale, TODOs, exact file paths/fn names/errors) and a fixed Goal/Constraints/Progress(Done/InProgress/Blocked)/Decisions/NextSteps output shape. | A proven rubric for *what* a long-horizon summary must retain — directly upgrades the Obsidian note + rolling brain memory. Pairs with #1. | idea-only | 5 |
| 4 | **Structured 9-section compaction prompt + no-tools preamble** | **claude-code** (`services/compact/prompt.ts`) | `<analysis>` scratchpad + `<summary>` with fixed sections (intent, files+snippets, errors+fixes, ALL user msgs, pending, current work, verbatim next-step quote); base + partial (`from`/`up_to`) variants; analysis stripped before injection. The "tool calls will be REJECTED, waste your only turn" preamble cut tool-attempt failure 2.79%→~0. | Drop-in shape for the brain's long-run history compactor; the no-tools preamble hardens every text-only brain/judge call. (This is the executor 9to5 already runs.) | port-code (prompt) | 5 |
| 5 | **Structured-output as the transport (forced schema, not free text)** | **metagpt** (`actions/action_node.py::fill/compile`) / **pydantic-ai** (`_output.py` ToolOutput/NativeOutput/PromptedOutput) | Compile a typed field tree into a JSON/markdown schema, LLM-fills, pydantic-validates; or pick output strategy per model capability. Reliable parseable output even from weak models; AgentScope uses the same trick *for the summary itself* (`summary_schema`+`summary_template`). | Replaces loose-JSON salvage (`brain_io._chatJson`) with schema'd output; the single biggest lever on 7B JSON reliability. | port-code | 5 |
| 6 | **ValidationError → RetryPrompt loop** | **pydantic-ai** (`_output.py::_make_retry_prompt`, `exceptions.py::_format_error_details`) | On schema-invalid output, serialize the *exact* Pydantic field errors into a `RetryPromptPart` and feed them back as the next turn, bounded by a retry budget — the model self-corrects against precise errors instead of a blind re-ask. | Directly attacks the "saturated with fallback scaffolding" root cause; small MIT port. | port-code | 5 |
| 7 | **json_repair + single corrective-retry hint** | **dify** (`generator/runner.py::_invoke_and_parse_json`, `_JSON_RETRY_HINT`) | `json_repair` parse, then one terse corrective-retry user nudge on parse failure, plus transient-error backoff (retry 5xx/ratelimit, never auth/badrequest). | Cheapest concrete hardening for Ollama JSON beyond 9to5's loose salvage; `json_repair` is a pip dep. | port-code | 5 |
| 8 | **Model-input budget / `shouldCompact` trigger** | **eliza** (`runtime/model-input-budget.ts`) | Estimate input tokens vs the model's context window; reserve = `max(10k, window*0.20)`; emit a `shouldCompact` threshold. Window-aware, regression-safe (only scales when model resolves). | Gives 9to5 a principled *when-to-compact* signal vs its constant `num_ctx` slice; the trigger that drives #1. | port-code | 4 |
| 9 | **Lenient double-decode + strip-markdown-fences** | **pydantic-ai** (`_output.py` response_validation_typed_dict, `_utils.strip_markdown_fences`) | Accept `T \| Json[T]` so a model returning JSON-as-a-string still validates; peel ` ```json ` fences before parsing. | Hardens `brain_io._chatJson` against the two most common qwen-7B failure shapes (fenced + double-encoded). | idea-only | 4 |
| 10 | **PromptedOutput schema-injection template** | **pydantic-ai** (`profiles/__init__.py::DEFAULT_PROMPTED_OUTPUT_TEMPLATE`) | For models with no native JSON mode, inject the output JSON-schema into instructions ("always respond with a JSON object compatible with this schema… no markdown fencing"). | Battle-tested template for forcing clean JSON from a no-native-mode local model — exactly qwen2.5-coder:7b. | idea-only | 4 |
| 11 | **Tiered compaction with budget-pressure policy** | **bernstein** (`core/memory/compaction/{tiers,policy}.py`) | Four cost-tuned tiers (micro every-turn, auto per-session threshold, durable session_memory, time_based age-prune); a policy selector picks exactly one tier per call from `BudgetPressure` (turn count, context %, idle secs); each tier reports tokens_saved + cost. | The hierarchical/rolling model with explicit cost accounting; a richer destination than a single compaction pass. | port-code | 4 |
| 12 | **Robust JSON ledger extraction (escalating modes)** | **autogen** (`_magentic_one_orchestrator.py` + `core/utils`) | `extract_json_from_str` + a `max_json_retries=10` loop that escalates client modes (`structured_output`→`json_output`→free text), validates required keys/shape, re-prompts on failure. | A cleaner, mode-escalating salvage than 9to5's ad-hoc `_chatJson`; idea maps onto Ollama's format options. | idea-only | 4 |
| 13 | **Plain-text / Harmony tool-call repair** | **openclaw** (`packages/tool-call-repair/`) | Parse tool calls weak/local models emit as *text* (bracket, Harmony channel markers, XML-ish), promote to structured calls; stream-normalizer + name allowlist + payload byte cap. | A principled salvage layer for malformed local-model tool/JSON output — the fallback-scaffolding tax again. | port-code | 4 |
| 14 | **RLM — Recursive Language Model over oversized context** | **eliza** (`runtime/rlm.ts`) | Bounded op set (peek/grep/partition/map_subcall/summarize/stitch/final) over a context too big to fit, under an explicit `RLMBudget{maxIterations,maxDepth,maxInput/OutputTokens,maxLatencyMs}`. | Hierarchical summarize/stitch over long-run history *and* a query strategy over a code index; heavier but the most powerful long-horizon tool here. | heavy | 4 |
| 15 | **Memory-as-untrusted-input sanitization** | **loki-mode** (`memory/rag_injector.py::_sanitize_field`) | Collapse every retrieved memory field to one inline line: strip control chars, collapse newlines/tabs (kills injected `###`/fences/instruction-lines), defang leading markdown markers, per-field cap. Treats retrieved memory as hostile. | 9to5 injects retrieved lessons + Obsidian context raw — a real prompt-injection hole; cheap, direct fix. | port-code | 4 |
| 16 | **Cache-friendly prompt layout (static prefix, mutating tail)** | **guild** (`internal/mcp/instructions.go`) | Static contract is the stable prompt-cache prefix; only the live principles/oath are appended as the mutating tail, so cache hit-rate stays high while durable principles still inject. | 9to5's per-call `CLAUDE CODE CAPABILITIES` + lessons block could adopt this ordering to preserve prompt cache. | idea-only | 4 |
| 17 | **Resume-prompt reconstruction from checkpoint** | **agx** (`lib/prompts/resume.js`) | Rebuild a compact resume prompt: Task / Done-When (`[x]/[!]/[ ]`) / Plan with current-step `[→]`, per-section token budgets, and a "continue from current step, don't rewrite the plan" stability footer. | Turns context into a step-level resume instruction; the stability footer curbs replan thrash — a context-eng + durability twofer. | port-code | 4 |
| 18 | **Budgeted prompt builder (per-section caps + size event)** | **agx** (`lib/storage/prompt_builder.js`) | Assemble the prompt from canonical state with per-section *char caps*, emit a `PROMPT_BUILT` event with per-section byte sizes; "never auto-inject historical logs" rule. | Per-section budgeting + size telemetry beats 9to5's blunt single `[:1500]`; gives prompt-size metrics for free. | idea-only | 3 |
| 19 | **Dynamic tool groups via meta-tool / deferred tools** | **agentscope** (`tool/_tool_group.py`, `_builtin/_meta.py`) / **claude-code** (`tools/ToolSearchTool/`, `shouldDefer`) | Bundle tools/skills/MCPs into named groups the agent activates/deactivates; or ship only a tool *name* and lazy-load the schema on demand (`select:A,B` / keyword search). Shrinks the active tool schema in-context. | Context-window saver when 9to5's invocation spec grows many surfaces/tools; claude-code's is already in the executor 9to5 runs. | idea-only | 3 |
| 20 | **Microcompact — cache-aware tool-result eviction** | **claude-code** (`services/compact/microCompact.ts`) | Evict old tool-results without breaking the prompt cache (`cache_edits`); time-gap trigger clears all but last-N tool results when the server cache has gone cold; keep-recent floor. | Rolling tool-output pruning that preserves cache; concept maps to trimming executor stdout history without a full re-summarize. | idea-only | 3 |
| 21 | **Autocompact threshold + circuit breaker** | **claude-code** (`services/compact/autoCompact.ts`) | Reserve output tokens, compute effective window, fire compaction at threshold; **stop after 3 consecutive failures** (a BQ measured 250K wasted calls/day without it). | The circuit-breaker is exactly what 9to5's compaction/retry loops need to avoid doomed repeats. | idea-only | 3 |
| 22 | **Compaction quality safeguard + post-compaction loop guard** | **openclaw** (`agent-hooks/compaction-safeguard*.ts`, `post-compaction-loop-guard.ts`) | Gate summary output quality (identifier-preservation + token-sanitize checks); guard against infinite-compaction loops post-compaction. | A mini spec-vs-output judge that a summary didn't drop required identifiers — verification applied to context ops. | idea-only | 3 |
| 23 | **Run-context fact ledger surviving compaction** | **swarmclaw** (`run-context.ts`) / **hermes** (`context_compressor.py` Resolved/Pending) | Extract keyFacts/failedApproaches (and Resolved/Pending questions) from dropped messages into a versioned RunContext that *survives* compaction and feeds the next turn; an anti-resume "Historical …" preamble stops a summary reading as live instructions. | Persists *what was learned/tried* (solution content) across compaction instead of dropping it; the anti-resume preamble is load-bearing. | port-code | 3 |
| 24 | **Reflection — importance-triggered hierarchical summary** | **generative-agents** (`reflect.py`) | When accumulated importance crosses a budget, generate focal questions → retrieve evidence → write higher-level "thought" nodes that cite their sources (`filling`/`depth` provenance). Self-paced, not turn-scheduled. | A cross-run "lessons reflection" that compresses raw subtask outcomes into a few cited, durable principles — compaction for `experience.db`. | idea-only | 3 |
| 25 | **Turn-boundary-aware history transform** | **dify** (`prompt/agent_history_prompt_transform.py`) | Drop oldest history at *user-message turn boundaries* (never split a turn) to fit budget, keep system msgs. | Turn-aware truncation; 9to5 already truncates so marginal, but the never-split-a-turn rule prevents corruption (summarization in #1 is the real upgrade). | idea-only | 2 |

**Dedup notes.** Compaction-with-summarization appears in nearly every mature repo —
agentscope, openclaw, claude-code, bernstein, MAF (`_compaction.py` strategy family),
openhands (`LLMSummarizingCondenser` max_size/keep_first), hermes, swarmclaw
(`context-manager.ts` map-reduce). **AgentScope does the algorithm best** (trigger/reserve
ratios + offload + drop-oldest fallback in clean standalone Python); **OpenClaw does the
*contract* best** (tool-pair invariant + MUST-PRESERVE rubric); **claude-code does the *prompt*
best** (9-section fixed shape + no-tools trick). Structured-output/JSON-reliability appears in
pydantic-ai (richest: validate→retry-with-field-errors), metagpt (ActionNode schema+self-review),
dify (json_repair+hint), autogen (mode-escalating extraction), generative-agents
(`safe_generate_response` validate-or-fallback harness), openclaw (text tool-call repair) —
**pydantic-ai is the reference** for the validate→structured-retry loop, **dify is the cheapest
concrete port** (`json_repair`). Model-input budgeting: eliza (cleanest standalone), openhands
(`keep_first`), MAF (token-budget-composed strategy), bernstein (BudgetPressure selector).

## 3. If 9to5 adopts ONE thing for this theme

**Build a real hierarchical-compaction layer modeled on AgentScope's `_compress_context_impl`
(`agent/_agent.py`), governed by a model-input-budget trigger and a MUST-PRESERVE summary
contract.** This is the single named weakness in the brief (§2.9 / gap #8): 9to5 *truncates*
(`architect_doc[:1500]`, `[:4000]`) where it should *condense*, so accumulating long-run history
is lost by slice and the 7B window is a hard ceiling. AgentScope's routine is the right spine —
when estimated tokens exceed `trigger_ratio*ctx`, split history into compress-vs-reserve by
`reserve_ratio`, summarize the old half into a *structured-schema* `summary` (which doubles as the
JSON-reliability win, since the summary itself is forced through a schema, not free text), offload
the raw messages to disk with a re-readable breadcrumb, and drop-oldest only if compression
overflows — all self-contained, Apache-2.0 Python with no framework dependency. Wrap it with
eliza's `model-input-budget.ts` `shouldCompact` threshold so compaction *triggers* on a token
estimate instead of running as a constant slice, and use OpenClaw's `MUST PRESERVE` rubric
(`src/agents/compaction.ts`) plus the tool-pair-preserving chunk invariant
(`compaction-planning.ts`) to define *what the summary must retain* and to keep the executor's
tool-event history API-valid. This one layer lifts the structural ceiling under planning, memory,
and verification at once, replaces metadata-only history with retained solution content, and is
mostly port-code rather than research. (Close second for this theme: the pydantic-ai
`ValidationError → RetryPrompt` loop + dify `json_repair`, which attack the other half — the 7B
JSON-reliability tax that saturates the planner with fallback scaffolding.)
