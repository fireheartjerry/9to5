# Epic 2 — Trustworthy 7B Loop (Design Spec)

> Harvested from the references catalog (`docs/references-harvest/MASTER.md` steals
> #2, #3, #9). Three stacked changes that make the brittle local-`qwen2.5-coder:7b`
> brain reliable: a **dual-ledger planner**, an **execution-grounded independent
> verifier + Evidence Receipt**, and a **schema-validated JSON self-correction loop**.
> All three port-sources are MIT. READ-ONLY harvest already done; this is the
> integration design. No 9to5 source was changed to write this spec.

---

## 1. Goal + gaps closed

**Goal:** replace 9to5's one-shot-7B planner, narration-only verification, and
ad-hoc JSON salvage with many *small, reliable, fact-grounded* model calls so a
weak local brain produces dependency-aware plans, evidence-backed "done" verdicts,
and self-correcting structured output — without swapping the model.

Gaps closed (per `_9to5-brief.md` §3):

- **Gap #1 — brittle one-shot 7B planner.** Dual-ledger planning (outer Task
  Ledger of facts+plan; tiny per-step Progress Ledger JSON; stall-counter →
  root-cause replan) replaces `authorSubtaskPlan`/`critiqueSubtaskPlan` and the
  greedy `_applyReplan`, and finally authors a real `depends_on` DAG.
- **Gap #2 — shallow/gameable verification.** A separate read-only verifier
  re-runs checks and judges each acceptance criterion by evidence; the green
  headline derives only from re-derivable FACTS (diff sha, exit codes), so the
  same brain can no longer author both the work and the check that blesses it.
- **Cross-cutting 7B-JSON tax.** `ValidationError → RetryPrompt` + `json_repair`
  hand the brain its *exact* field errors instead of a blind re-prompt, draining
  the fallback-scaffolding that saturates the planner today (gap #1's root cause,
  brief §2.9).

---

## 2. Non-Goals

- **NOT swapping the 7B model** or adding a bigger planning model. The whole point
  is reliability *at the current ceiling* (`config.OLLAMA_MODEL`, brief §1).
- **NOT changing model/effort routing** for executor subtasks
  (`config.MODEL_BY_EFFORT`, `.claude/rules/orchestration.md`). The independent
  verifier is a *new* read-only agent at a fixed modest effort; it does not alter
  any existing subtask's effort.
- **NOT** building HTN/tree-search/cost-budgeted scheduling (theme rank-2 "heavy";
  overkill for a 7B today). The DAG stays the existing linear-ish `depends_on`
  graph, just actually authored and cascade-reset.
- **NOT** moving ownership: the deterministic verifier still owns verification
  *status*; `ControlBus` still owns control; the Evidence Receipt is a *derived*
  artifact that gates only through the verifier-owned `state.recordVerify` path.
- **NOT** touching the Gemini second-brain / adversary transport, the surfaces
  layer, or the durability/journal epic (that is Epic 1).

---

## 3. Architecture (small units + interfaces)

### 3a. Dual-ledger planner (replaces one-shot `authorSubtaskPlan`)

Source: autogen Magentic-One
(`references/autogen/python/packages/autogen-agentchat/src/autogen_agentchat/teams/_group_chat/_magentic_one/_magentic_one_orchestrator.py`
+ `_prompts.py`), peer
`references/ms-agent-framework/python/packages/orchestrations/agent_framework_orchestrations/_magentic.py`;
shape-check from `references/bernstein/src/bernstein/core/planning/vertical_slice.py`;
DAG from `references/metagpt/metagpt/actions/di/write_plan.py` (`dependent_task_ids`).

**Task Ledger** (the stable outer plan). New dataclass in
`platform_core/orchestration/task_ledger.py`:

```python
@dataclass
class TaskLedger:
    given_facts: list[str]      # facts stated in the goal
    lookup_facts: list[str]     # facts to look up (+ where)
    derive_facts: list[str]     # facts to derive (compute/deduce)
    guess_facts: list[str]      # educated guesses
    plan: list[str]             # bullet-point plan
    revision: int = 0           # bumped on each root-cause rewrite
```

Authored by two small brain calls mirroring autogen's
`ORCHESTRATOR_TASK_LEDGER_FACTS_PROMPT` then `..._PLAN_PROMPT` (facts first, plan
second — each call answers one bounded question a 7B can handle). Persisted to
`state.meta["task_ledger"]` so a resilience restart and the replan path can read it.

**Subtask DAG.** A deterministic `deriveSubtaskDag(ledger, goal)` turns the bullet
plan into the existing subtask shape with **real `depends_on`** — the schema field
already exists (`state.task_schema.addSubtask(..., depends_on=...)`, honored by
`nextActionable`, line 379) but the planner never authors it today. Each plan
bullet becomes a subtask; sequential bullets get `depends_on=[prev_id]` unless the
brain marks them independent (metagpt `dependent_task_ids` semantics, mapped onto
9to5's `st-NNN` ids).

**Plan shape-check + one corrective re-prompt** (bernstein vertical-slice).
`plan_shape_check.py::checkPlanShape(subtasks) -> list[str]` deterministically
rejects degenerate plans (0 subtasks, >`MAX_SUBTASKS`, a subtask with an empty
verify on a multi-deliverable goal, a `depends_on` cycle, a dangling dep id). On
violation, re-prompt the brain **once** with the structured violation report, then
accept whatever comes back (no infinite loop — exactly bernstein's
`_run_shape_check_with_retry`). This is the "decomposition-with-verification" the
brief asks for, gating quality *without trusting the 7B more*.

**Progress Ledger** (tiny per-step JSON). After each subtask resolves, one small
brain call answers autogen's `ORCHESTRATOR_PROGRESS_LEDGER_PROMPT` schema, parsed
through the JSON loop from §3c:

```json
{
  "is_request_satisfied": {"reason": "...", "answer": false},
  "is_in_loop":           {"reason": "...", "answer": false},
  "is_progress_being_made":{"reason": "...", "answer": true},
  "instruction":          {"reason": "...", "answer": "..."}
}
```

(9to5 has no `next_speaker` — it is a star topology, so that field is dropped; the
`instruction` becomes the next replan/backfill hint.)

**Stall counter → root-cause replan.** `state.meta["stall_count"]` increments when
`is_in_loop.answer` is true or `is_progress_being_made.answer` is false, decrements
on progress (autogen `n_stalls`). At `>= config.STALL_THRESHOLD`, instead of the
greedy title-dedup `_applyReplan`, run autogen's
`ORCHESTRATOR_TASK_LEDGER_FACTS_UPDATE_PROMPT` + `..._PLAN_UPDATE_PROMPT`
("explain the root cause, then rewrite facts+plan"), bump `ledger.revision`,
**freeze the executed prefix** (done/failed subtasks), and re-derive only the
remaining-tail DAG with a **cascade reset** of dependents (metagpt `reset_task`:
removing/replacing a subtask invalidates downstream `depends_on` children). This
replaces "title-dedup add/remove" with genuine task-graph re-derivation.

### 3b. Execution-grounded verifier + Evidence Receipt

Source: eliza
(`references/eliza/plugins/plugin-agent-orchestrator/src/services/completion-envelope.ts`,
`independent-verifier.ts`, `goal-llm-verifier.ts`, `completion-evidence.ts` — MIT);
facts/assessments split from
`references/loki-mode/autonomy/lib/proof-generator.py` (BUSL — **ideas only**, the
Python is reimplemented, not vendored).

**CompletionEnvelope** the executor must emit. Port eliza's schema to
`agents/completion_envelope.py`:

```python
@dataclass
class CompletionEnvelope:
    diff_summary: str
    files_changed: list[str]
    test_results: list[dict]          # [{command, exit_code, summary}]
    acceptance_criteria_status: list[dict]  # [{criterion, met, evidence}]
    residual_risks: list[str]
    screenshot_paths: list[str] = field(default_factory=list)
```

`COMPLETION_ENVELOPE_INSTRUCTION` (a constant) is appended to the executor prompt
in `authorInvocationSpec` (same seam as `reflection.REQUEST`, plan_mixin line 327):
"when FINISHED, end your final message with a fenced ```json block matching this
schema". `parseCompletionEnvelope(text) -> EnvelopeParse` is a pure
parser/validator (last fenced block; absent → fall back to today's heuristic path,
back-compat; present-but-malformed → targeted re-prompt via `envelopeCorrection`).

**Independent read-only verifier** (Agent-as-a-Judge). New `agents/independent_verifier.py`:
- `buildVerifierPrompt(goal, acceptance_criteria, diff_summary)` — eliza's prompt:
  "You are an INDEPENDENT verifier. Do NOT trust narration — confirm by EXECUTION.
  Read-only: run tests/build/typecheck, read files, inspect `git diff`. Output ONLY
  a CompletionEnvelope."
- `runIndependentVerification(...)` spawns a **separate** Claude subprocess via the
  existing `self._run_claude` with `--disallowedTools Edit,Write` (the mechanism
  already used for `CORE_PROTECTED_FILES` self-ref runs, brief §2.6) so read-only is
  enforced by the hands layer, not just the prompt.
- `verdictFromEnvelope(env) -> Verdict{passed, unmet, failed_commands, inconclusive}`:
  `passed` only when every criterion `met` AND every `test_results.exit_code == 0`
  AND ≥1 criterion reported; **no envelope ⇒ inconclusive ⇒ never auto-pass**.

**Evidence Receipt** (facts vs assessments). New `agents/evidence_receipt.py`,
reimplementing loki's `proof.json` model as 9to5-native:
- `facts` (deterministic, re-derivable, NON-LLM): `git.base_sha`, `git.head_sha`,
  `git.diff_sha256` (sha256 of the canonical diffstat), and per-check
  `{command, exit_code, status}` taken from the deterministic verifier's
  `runVerification` result + the independent verifier's `test_results`.
- `assessments` (LLM opinion, explicitly non-binding): the independent verifier's
  per-criterion judgments, the adversary verdict.
- `headline` computed **only from facts** (loki `_compute_headline`):
  `VERIFIED` (every ran-check exit 0, non-empty diff, no degraded items),
  `VERIFIED_WITH_GAPS`, or `NOT_VERIFIED`; a hard-failed check forces `NOT_VERIFIED`;
  inconclusive is surfaced loudly, never silently green.
- `buildReceipt(...) -> dict` is pure; the caller persists it as a per-subtask
  Obsidian note (doubles as the durable audit artifact observability lacks).

**How it slots beside `agents/verifier.py` + adversary (ownership preserved).** The
deterministic `{cmd, expect}` gate (`verifier.py` / `verifier_runner.py`) **still
runs first and still owns verification status** — unchanged. For **code-change
subtasks only**, after a deterministic pass we run the independent verifier + build
the receipt; a `NOT_VERIFIED` headline **downgrades the pass** by mutating `vresult`
and calling `state.recordVerify` — the *exact* pattern the self-ref quality gate
already uses (`execute_mixin._runAttemptVerify`, lines 123-136). The receipt never
writes status directly; it gates through the verifier-owned path. The adversary
stays where it is (advisory remediation), but now reads the receipt instead of raw
narration.

### 3c. JSON self-correction loop (wraps existing extraction)

Source: pydantic-ai
(`references/pydantic-ai/pydantic_ai_slim/pydantic_ai/_output.py::_make_retry_prompt`,
`exceptions.py::ToolRetryError._format_error_details`) + dify `json_repair`
(`references/dify/api/core/workflow/generator/runner.py`).

- **`json_repair` salvage** added to `brain_io.parseJsonText` as a *third* ladder
  rung, after the existing fence-strip and `_firstBalancedObject` attempts (so the
  two most common qwen failure shapes — fenced + truncated/malformed — are salvaged
  before giving up). `json_repair` is a small pip dep (new requirement).
- **Schema-validated retry.** New `platform_core/orchestration/brain_json.py`:
  `chatJsonValidated(ollama_chat, system, user, *, required_keys, validators,
  max_retries) -> dict | None`. It calls `ollama_chat`, parses via the hardened
  `parseJsonText`, runs a *lightweight* schema check (required keys present +
  per-field type/shape validators — no pydantic dependency needed, 9to5 keeps its
  dict-shaped specs), and on failure builds a **retry prompt carrying the exact
  field errors** (`_makeRetryPrompt`, pydantic-ai's `_format_error_details` ported
  to plain strings: `"<key>: <msg> [got <repr>]"`), re-calling up to
  `config.BRAIN_JSON_RETRY_MAX` times. This wraps — does not replace — `_chatJson`;
  the three brain authoring calls (Task Ledger facts/plan, Progress Ledger,
  invocation spec) route through it.

This is the surgical fix for "the code is saturated with fallback scaffolding": the
empty-planner re-derivation in `authorSubtaskPlan` (lines 149-175) and the
"brain authored no batch" fallback in `authorBackfillBatch` become *last-resort*
paths instead of the common case.

---

## 4. Data flow

```
goal_elaborated + architect_doc
  │
  ├─ authorTaskLedger        facts call → plan call        (brain, via chatJsonValidated)
  ├─ deriveSubtaskDag        plan bullets → subtasks w/ real depends_on
  ├─ checkPlanShape          deterministic; on violation → 1 corrective re-prompt
  ▼
state.subtasks (DAG)  ──nextActionable()──▶ per subtask:
        │
        ├─ authorInvocationSpec (+ COMPLETION_ENVELOPE_INSTRUCTION)   [brain]
        ├─ executor runs (Claude)  →  emits CompletionEnvelope
        ├─ verifier.runVerification           [deterministic gate — OWNS status]
        │       └─ pass & code-change?  → runIndependentVerification  [read-only Claude]
        │                                → buildReceipt (facts→headline)
        │                                → NOT_VERIFIED ⇒ downgrade via recordVerify
        ├─ progress-ledger call  → {satisfied, in_loop, progress, instruction}  [brain]
        ▼
   stall_count ±   ──(≥ STALL_THRESHOLD)──▶  root-cause facts+plan rewrite
                                              freeze done prefix → re-derive tail DAG
                                              cascade-reset dependents
```

The pass verdict the run reports is the conjunction: deterministic gate **and**
(for code changes) a fact-derived `VERIFIED`/`VERIFIED_WITH_GAPS` receipt.

---

## 5. Exact file structure

**New modules** (each a small, single-domain unit with an `@AI-MAP v1` header,
≤300 ideal / ≤450 hard lines, funcs ≤70 lines, `camelCase`/`snake_case`/`ALL_CAPS`):

| File | Responsibility | ~lines |
|---|---|---|
| `platform_core/orchestration/task_ledger.py` | `TaskLedger` dataclass + facts/plan prompt constants + (de)serialize to `state.meta` | ~140 |
| `platform_core/orchestration/dual_ledger_planner.py` | `authorTaskLedger`, `deriveSubtaskDag`, `progressLedgerStep`, `rootCauseReplan` (free functions taking an `ollama_chat` callable, mirroring `subtask.py`'s split-out helpers) | ~280 |
| `platform_core/orchestration/plan_shape_check.py` | `checkPlanShape`, `shapeViolationReport` (deterministic; bernstein) | ~120 |
| `platform_core/orchestration/brain_json.py` | `chatJsonValidated`, `_makeRetryPrompt`, `_validateShape` (pydantic-ai retry loop, no pydantic dep) | ~150 |
| `agents/completion_envelope.py` | `CompletionEnvelope`, `COMPLETION_ENVELOPE_INSTRUCTION`, `parseCompletionEnvelope`, `envelopeCorrection`, `summarizeEnvelope` (eliza port) | ~200 |
| `agents/independent_verifier.py` | `buildVerifierPrompt`, `runIndependentVerification`, `verdictFromEnvelope`, `shouldRunIndependentVerify` (eliza port) | ~180 |
| `agents/evidence_receipt.py` | `buildReceipt`, `_computeFacts`, `_computeHeadline`, `_diffSha256` (loki ideas, reimplemented) | ~220 |

**Modified files** (narrow patches; public facades preserved):

| File | Change |
|---|---|
| `platform_core/orchestration/plan_mixin.py` | `authorSubtaskPlan` becomes a thin delegate to `dual_ledger_planner` (signature unchanged — callers in run-phase untouched); `critiqueSubtaskPlan` delegates to `plan_shape_check`; append `COMPLETION_ENVELOPE_INSTRUCTION` in `authorInvocationSpec` beside `reflection.REQUEST`. Route the three brain calls through `brain_json.chatJsonValidated`. |
| `platform_core/orchestration/brain_io.py` | add `json_repair` rung to `parseJsonText` (4 lines). |
| `platform_core/orchestration/run_loop_mixin.py` | `_applyReplan` gains a `_cascadeResetDependents` helper + a stall-driven `rootCauseReplan` branch; greedy add/remove kept only as the non-stall path. |
| `platform_core/orchestration/execute_mixin.py` | in `_runAttemptVerify`, after a code-change pass, call `independent_verifier` + `evidence_receipt`, downgrade on `NOT_VERIFIED` (same shape as the self-ref gate block); in `_runSieAndReplan`, replace the heuristic `_replan` call with `progressLedgerStep` + stall counter. |
| `state/task_schema.py` | small helper `dependentsOf(subtask_id)` for cascade reset (the `depends_on` field already exists). |
| `platform_core/app_config/llm.py` | new `ALL_CAPS` knobs (defaults below). |
| `requirements*.txt` | add `json_repair`. |
| `AGENTS.md` | regenerate via `python tools/repo_map.py` after the new modules land. |

**Config knobs** (`platform_core/app_config/llm.py`, all env-overridable, staged
defaults so the epic ships dark then flips on):

```python
DUAL_LEDGER_PLANNER_ENABLED: bool = _envBool("DUAL_LEDGER_PLANNER_ENABLED", False)
INDEPENDENT_VERIFY_ENABLED:  bool = _envBool("INDEPENDENT_VERIFY_ENABLED", True)  # code-change only
EVIDENCE_RECEIPT_ENABLED:    bool = _envBool("EVIDENCE_RECEIPT_ENABLED", True)
BRAIN_JSON_RETRY_MAX:        int  = _envInt("BRAIN_JSON_RETRY_MAX", 2)
STALL_THRESHOLD:             int  = _envInt("STALL_THRESHOLD", 2)
```

Each new layer is independently flaggable so a regression in one does not block the
others, matching how `SIE_*` and `ADVERSARY_REMEDIATION_ENABLED` already gate.

---

## 6. Error handling + reduced fallback-scaffolding tax

- **Every new brain call degrades to the current behavior, never worse.** If
  `chatJsonValidated` exhausts retries it returns `None` and the caller keeps its
  existing fallback (`authorSubtaskPlan`'s per-requirement decomposition). The
  dual-ledger path is gated by `DUAL_LEDGER_PLANNER_ENABLED`; off ⇒ today's planner.
- **Independent verifier failure is inconclusive, never a false pass** (eliza rule):
  a spawn crash / empty envelope ⇒ `inconclusive=True`, the receipt stays
  `NOT_VERIFIED`/gaps, and the deterministic gate's verdict stands. It can only
  *downgrade* a pass, never upgrade a fail — so adding it cannot make a run greener
  than the facts allow.
- **Receipt generation is best-effort** (loki `generate` swallows all exceptions and
  prints one warning): a receipt failure logs and leaves the deterministic status
  untouched, mirroring the `_postSubtaskEnrich` best-effort contract.
- **Why the tax drops.** Today's planner is "saturated with fallback scaffolding"
  precisely because the 7B emits malformed/fenced/double-encoded JSON and the single
  call has no recovery except blind re-prompt + scaffold. Splitting planning into
  small schema-bounded calls (facts, plan, per-step progress) that each get *exact
  field errors* on failure means each call succeeds far more often, so the empty-
  planner re-derivation (plan_mixin 149-175), the "brain authored no batch" branch
  (authorBackfillBatch 414-415), and the loose-JSON salvage in `_chatJson` move from
  the *common path* to genuine last resorts. Net: fewer mega-subtask collapses,
  fewer unverified `"Implement the goal"` fallbacks, fewer false-green content scans.

---

## 7. Testing strategy

> Local `.env` carries **live Discord/Ollama creds**; the conftest sandbox is
> **pytest-only** (memory note: bare `unittest` fires real side effects). Run
> everything through pytest. Per-file focus: `python tools/dev.py check <file>`.

- **Pure units (no brain, deterministic):**
  - `tests/test_task_ledger.py` — ledger (de)serialize round-trips through `state.meta`.
  - `tests/test_plan_shape_check.py` — degenerate plans (cycle, dangling dep, empty
    multi-deliverable verify, over-cap) flagged; clean plan passes.
  - `tests/test_completion_envelope.py` — port eliza's parser cases: absent ⇒
    fall-back, malformed ⇒ correction, valid ⇒ parsed; `verdictFromEnvelope`
    inconclusive-when-no-criteria.
  - `tests/test_evidence_receipt.py` — `_computeHeadline`: failed check ⇒
    `NOT_VERIFIED`; all-green + non-empty diff ⇒ `VERIFIED`; gap ⇒
    `VERIFIED_WITH_GAPS`; same `diff_sha256` re-derives identically.
  - `tests/test_brain_json.py` — fenced/truncated/double-encoded JSON salvaged;
    retry prompt contains the exact missing-key error; bounded by `BRAIN_JSON_RETRY_MAX`.
- **Mocked-brain integration** (patch `_ollamaChat` like existing
  `tests/test_plan_strengthen.py` / `test_fuzz_brain.py`): dual-ledger produces a DAG
  with `depends_on`; a stalling progress-ledger sequence triggers exactly one
  root-cause replan; independent-verifier downgrade flips a deterministic pass to fail
  via `recordVerify`.
- **Regression guards (must stay green):** `test_verify_multi_requirement.py`,
  `test_verify_shell_safety.py`, `test_apply_replan.py`, `test_chatjson_salvage.py`,
  `test_adversary_*` — proves the deterministic gate, replan cap, and adversary
  contract are unchanged.
- **Gate sequence:** `python tools/dev.py check <changed file>` per patch →
  `python tools/dev.py fast` before handoff → `python tools/size_audit.py` (zero
  `must_split`) → `python tools/repo_map.py` after the new modules.

---

## 8. Risks + sequencing

**Risks & mitigations:**

- **Extra Ollama calls / latency from the dual ledger.** Facts+plan are 2 calls
  (the same count as today's author+critique); the progress ledger adds 1 *tiny*
  JSON call per subtask. Mitigation: progress ledger is a minimal schema, cached
  ledger in `state.meta` (no re-derivation per attempt), shape-check re-prompt only
  fires on violation, and the whole path is flag-gated for A/B against the current
  planner.
- **Independent verifier = an extra Claude subprocess per code subtask** (real token
  + wall-clock cost). Mitigations: gated to **code-change** subtasks via
  `shouldRunIndependentVerify`; **skipped under parallelism on a shared tree** (reuse
  `_remediationTreeShared`, the existing guard for adversary remediation); it re-runs
  only the deterministic verify command + reads the diff (bounded), and reuses the
  deterministic verifier's captured exit codes as facts where possible.
- **Receipt false-downgrade** of correct work. Mitigation: the headline only forces
  `NOT_VERIFIED` on a *hard-failed ran-check* or empty diff; inconclusive ⇒ keeps the
  deterministic verdict (never downgrades on verifier flakiness).
- **`json_repair` masking genuinely-broken output.** Mitigation: it is the *last*
  ladder rung after strict parse; the schema validator still rejects a repaired-but-
  wrong-shape object and triggers the field-error retry.
- **Cascade reset removing in-flight work.** Mitigation: freeze the executed prefix
  (done/failed) and only reset *pending* dependents (cf. `nextActionable`'s
  failed-dependency guard, FX-21).

**Sequencing within the epic** (each step independently shippable + flag-gated):

1. **Steal #9 first — `brain_json` + `json_repair`.** Smallest, lowest-risk, and it
   *de-risks* the other two (their brain calls ride on it). Ship, measure JSON
   failure-rate drop.
2. **Steal #3 — CompletionEnvelope + independent verifier + Evidence Receipt.**
   Additive, gated, only downgrades; closes gap #2 without touching the planner.
3. **Steal #2 — dual-ledger planner + DAG + stall replan.** Largest surface; lands
   last on top of reliable JSON (#9) and a trustworthy verdict (#3) so its plans are
   judged by evidence from day one. Flip `DUAL_LEDGER_PLANNER_ENABLED` after an A/B
   against the current planner on the golden eval suite.

---

## 9. Success criteria

- **JSON reliability (#9):** brain-call JSON-parse-failure rate (the path that today
  hits empty-planner / no-batch fallbacks) drops measurably on the golden eval suite;
  `chatJsonValidated` recovers malformed output within `BRAIN_JSON_RETRY_MAX` in the
  unit suite; `test_chatjson_salvage.py` still green.
- **Verification (#3):** for code-change subtasks every reported pass carries an
  Evidence Receipt whose `VERIFIED`/`VERIFIED_WITH_GAPS` headline is derived only from
  facts (diff sha + exit codes); a verbose-but-wrong implementation that satisfies the
  old content-scan is caught by the independent verifier (regression test); no false
  *upgrade* is possible (inconclusive ⇒ never green).
- **Planning (#2/#1):** the planner authors a non-trivial `depends_on` DAG for
  multi-deliverable goals (today it authors none); `nextActionable` honors it;
  shape-check rejects degenerate plans with one corrective re-prompt; a stalling run
  triggers exactly one root-cause facts+plan rewrite instead of greedy churn.
- **No regressions / ownership intact:** verifier still owns status, ControlBus still
  owns control; `python tools/dev.py fast` green; `python tools/size_audit.py` zero
  `must_split`; `AGENTS.md` regenerated.
- **Cost guardrail:** with all flags on, added Ollama+Claude calls stay within an
  agreed per-run budget (dual-ledger net-neutral on planning calls; independent
  verifier bounded to code subtasks).

---

### Source-path appendix (all MIT unless noted)

- Dual ledger: `references/autogen/.../_magentic_one/_magentic_one_orchestrator.py` + `_prompts.py`; `references/ms-agent-framework/python/packages/orchestrations/agent_framework_orchestrations/_magentic.py`
- Shape-check: `references/bernstein/src/bernstein/core/planning/vertical_slice.py`
- DAG: `references/metagpt/metagpt/actions/di/write_plan.py` (`dependent_task_ids`)
- Envelope/verifier: `references/eliza/plugins/plugin-agent-orchestrator/src/services/{completion-envelope,independent-verifier,goal-llm-verifier,completion-evidence}.ts`
- Receipt: `references/loki-mode/autonomy/lib/proof-generator.py` (**BUSL — ideas only, reimplemented**)
- JSON retry: `references/pydantic-ai/pydantic_ai_slim/pydantic_ai/_output.py::_make_retry_prompt` + `exceptions.py`; `json_repair` per `references/dify/api/core/workflow/generator/runner.py`
</content>
</invoke>
