# Theme: Verification & Self-Correction

> Cross-repo synthesis for 9TO5 gap #2 (shallow verification). READ-ONLY harvest across all 23 reference repos.
> Source brief: `docs/references-harvest/_9to5-brief.md` §2.5.

## 1. Theme intro — and how 9TO5 handles this today

Verification is the act of *proving the work is actually correct*, and self-correction is the loop that
re-drives the executor when that proof fails. Across the 23 references this clusters into seven recurring
moves: (a) **execution-grounded evidence** (re-run the tests, read the diff, don't trust narration);
(b) **structured "done" contracts** the verifier can machine-check; (c) **LLM-judge rubrics** scoring spec-vs-diff
on typed dimensions; (d) **deterministic-first gates** that escalate to an LLM only for genuinely semantic
criteria; (e) **anti-reward-hacking** (held-out evals, facts-vs-assessments, judge≠author, sycophancy
detection); (f) **retry-on-validation-error** that feeds the model its *exact* failure; and (g) **test/criteria
generation** so an independent acceptance signal exists at all.

**9TO5 today** runs a deterministic gate (`agents/verifier.py` + `verifier_runner.py`) where the brain authors a
`{cmd, expect}` check with `expect ∈ {exit_zero, stdout_contains, stdout_regex, stdout_contains_all,
stdout_regex_all}`. For enumerated goals it synthesizes a compound **content-scan** verify
(`buildContentScanVerify` / `buildRequirementsVerify`) that word-tokenizes a target file and asserts ≥1 marker
per requirement, marked `strict`. Self-correction is a bounded retry loop with failure-feedback re-prompting
(`execute_mixin.py::_runAttemptLoop`, `MAX_SUBTASK_ATTEMPTS`), brittle-verify repair (`_repairVerify`), a
bounded **adversary remediation** with git snapshot/restore (`_remediate`), clarifier auto-answering, and a
pre-PR adversary + test-suite gate (`run_phase_mixin.py::_resolvePrePrGate`).

**Where it's weak.** The check proves a command exits 0 or that *strings/tokens are present in source* — not
that behavior is correct. `buildContentScanVerify` is satisfiable by a verbose, wrong implementation. There is
no test-generation, no property/semantic check, no spec-vs-diff judge, no execution-grounded evidence, and no
defense against the structural risk that **the same weak 7B brain authors both the work and the verify** (it can
game checks it wrote). The adversary is advisory and reads only narration; remediation is a single bounded
attempt, *disabled entirely under parallelism* (`_remediationTreeShared`). Net: verification certifies markers
exist, not that the job was done.

---

## 2. Ranked technique table (best-of across all repos, deduped)

Rank: 5 = port this first / fills the gap dead-center · 1 = marginal. `steal-effort`: idea-only · port-code · heavy.
Where multiple repos do the same thing, the row names the **best** implementation and lists peers.

| # | technique | best source repo (file) | what | 9to5-fit | steal-effort | rank |
|---|---|---|---|---|---|---|
| 1 | **Independent execution-grounded verifier (Agent-as-a-Judge)** | **eliza** `plugin-agent-orchestrator/src/services/independent-verifier.ts` (peers: claude-code `verificationAgent.ts`, AGX `executeVerifySwarm.js`) | Spawn a SEPARATE read-only agent that *re-runs* tests/build/typecheck + reads the diff and judges per-criterion from output it actually produced; `passed` only if every criterion met AND every command exit 0; `inconclusive`⇒never auto-pass. Verifier ≠ author. | Replaces advisory narration-only adversary with a real second-agent execution check — the core of gap #2. | port-code | 5 |
| 2 | **CompletionEnvelope contract (machine-checkable "done")** | **eliza** `services/completion-envelope.ts` (peer: swarmclaw `task-quality-gate.ts`) | Sub-agent MUST emit structured report: `testResults[{command,exitCode,summary}]`, per-criterion `{met,evidence}`, `filesChanged`, `residualRisks`. Structural validation runs *before* the LLM judge; malformed⇒targeted re-prompt. | Replaces free-prose subtask report; real exit codes vs token-presence scan. | port-code | 5 |
| 3 | **Evidence Receipt — facts vs assessments split** | **loki-mode** `autonomy/lib/proof-generator.py` (peer: hermes `verification_evidence.py`) | Deterministic `proof.json`: re-derivable **facts** (base/head SHA, `diff_sha256`, test cmd+exit, gate verdicts) vs LLM **assessments**; green headline computed ONLY from facts — an LLM opinion can never make it green. "Inconclusive ≠ verified." | Drop-in replacement for `buildContentScanVerify`; also the per-step audit artifact observability lacks. | port-code | 5 |
| 4 | **Completion-evidence assembly (grounded proof string)** | **eliza** `services/completion-evidence.ts` | Pure fn turning signals 9TO5 already has — real git diffstat, captured deliverable, loopback-vs-public-flagged URLs, mined TEST/BUILD/TYPECHECK output, artifacts — into one sectioned, size-capped evidence blob for the judge. | Gives the judge grounded proof; diff-grounding + loopback flag beat source content-scan. | port-code | 5 |
| 5 | **LLM-judge guardrail (NL criterion → {valid, feedback} + bounded retry)** | **crewai** `tasks/llm_guardrail.py` (peers: pydantic-ai `llm_as_a_judge.py`, bernstein `eval/judge.py`, swarmclaw `eval/scorer.ts`) | A plain-English criterion is auto-wrapped into a judge returning `{valid, feedback}`; on fail the task re-runs with the feedback, bounded by `guardrail_max_retries`. Cleanest "behavior not markers" gate. | Brain authors a per-subtask NL rubric; judge gates it; feedback re-prompt mirrors `_runAttemptLoop`. | port-code | 5 |
| 6 | **ValidationError → RetryPrompt structured self-correction** | **pydantic-ai** `_output.py:_make_retry_prompt` + `exceptions.py:ToolRetryError` (peers: dify `runner._invoke_and_parse_json`, autogen `extract_json_from_str`, generative-agents `safe_generate_response`) | On schema-invalid output, serialize the *exact* Pydantic field errors into a `RetryPromptPart` and feed them back; bounded per-tool/per-output retry budgets; lenient `T \| Json[T]` + fence-strip. | Replaces blind re-prompt + fallback scaffolding on bad 7B JSON; attacks the root cause. | port-code | 5 |
| 7 | **Held-out spec evals (anti-reward-hacking)** | **loki-mode** `skills/quality-gates.md` + `autonomy/completion-council.sh` | Deterministically reserve `clamp(round(0.25N),1,5)` checklist items (ranked by `sha256(id)`), HIDE them from the build loop's prompt/counts/gates, evaluate only at the ship gate. The agent can't tune to checks it never sees. | Independent acceptance signal the executor never optimized against; strong for enumerated-deliverable goals. | port-code | 5 |
| 8 | **Verification subagent prompt ("try to break it", VERDICT contract)** | **claude-code** `tools/AgentTool/built-in/verificationAgent.ts` | Read-only adversarial verifier: per-change-type strategies (frontend/API/CLI/migration), mandatory adversarial probe, anti-rationalization list, strict evidence format ending `VERDICT: PASS/FAIL/PARTIAL`, Edit/Write disallowed. A ready prompt. | Concept-port (TS→prompt) upgrade for 9TO5's adversary; far stronger than content-scan. | port-code (prompt) | 5 |
| 9 | **ActionNode per-field self-review / self-revise** | **metagpt** `actions/action_node.py` (`auto_review`/`auto_revise`) (peer: metagpt `write_code_review.py` LGTM/LBTM loop) | Schema-typed artifact: LLM reviews each filled field *against that field's own requirement*, emits mismatch comments, re-fills. A structured spec-vs-output judge fused with reliable structured output. | Replaces loose-JSON brain output AND adds field-level verification in one mechanism. | port-code | 5 |
| 10 | **Verified-completion gate (empty diff / red tests ⇒ cannot complete)** | **loki-mode** `loki-ts/src/runner/council.ts` (peers: AGX `stage-requirements.js`, swarmclaw `looksIncomplete()`) | Before honoring any "done": require a nonzero git diff vs run-start SHA AND green tests; inconclusive disclosed loudly, never silently green. | Cheap universal policy at pre-PR gate; closes fake-green. | idea-only | 5 |
| 11 | **PR-review rubric with hard evidence gate** | **warp** `.agents/skills/review-pr-local/SKILL.md` | Structured review: severity labels, REJECT/Request-changes verdict, "any user-visible change with no screenshot/recording ⇒ auto-REJECT." Evidence-required, not token-presence. | Concrete spec-vs-diff rubric for the adversary; evidence gate is the semantic check 9TO5 lacks. | port-code (template) | 4 |
| 12 | **Deterministic-first verify gate (classify criterion → run programmatically, escalate only semantic)** | **AGX** `lib/verify-gate.js` (peer: loom PostToolsHook lint/format/test) | Regex-classify each criterion into `file_exists/tests_pass/lint/typecheck/build` and run those programmatically; only genuinely **semantic** criteria escalate to the LLM judge; force-action after `MAX_VERIFY_FAILURES`. | Cheap deterministic layer in front of LLM judging; clean upgrade to `buildContentScanVerify`. | port-code | 4 |
| 13 | **Auto acceptance-criteria generation** | **eliza** `services/acceptance-criteria.ts` + `goal-contract.ts` | When a task has no criteria, generate 3–5 measurable ones via deterministic per-task-type templates + optional small-model refine that always falls back to the static set. | Turns ad-hoc `buildRequirementsVerify` into a stable template+refine verify contract. | port-code | 4 |
| 14 | **WriteTest QA test-generation** | **metagpt** `actions/write_test.py` (peers: claude-code `init-verifiers.ts`, pydantic-ai `generation.py:generate_dataset`) | QA role generates a unittest suite for a code file from its design/interfaces; claude-code's `init-verifiers` auto-detects project areas and emits self-updating functional verifier *skills*. | The missing test-gen piece — proves behavior, not marker presence. | port-code | 4 |
| 15 | **Counter-evidence override council (fail-closed, judge≠author)** | **loki-mode** `loki-ts/src/runner/counter_evidence.ts` | On a BLOCK, dev agent emits typed counter-evidence + artifacts; 3 judges on DIFFERENT providers vote 2-of-3 to lift. Self-supplied evidence fails CLOSED — only an adjudicator the agent doesn't control may lift. | Lets the adversary verdict be appealed *with evidence* while keeping the trust property. | port-code | 4 |
| 16 | **Chain-of-Verification (factored CoVe)** | **loki-mode** `skills/quality-gates.md` (peer: owl "verify with a second tool" reminder) | Draft → self-generate verification questions → answer EACH with NO access to the original response (breaks rationalization) → revise. "Verifier sees only the claim + minimal spec, not the impl." | Structured self-correction step before the adversary; the isolation rule is portable to verify authoring. | idea-only | 4 |
| 17 | **Two-stage review: spec-compliance THEN quality** | **loki-mode** `skills/quality-gates.md` (peer: bernstein closed-set failure taxonomy) | Never mix "does it do what spec requires" with "is it well-written." Stage 1 (1 reviewer, spec compliance, must pass) gates Stage 2 (blind quality review). Stops "clean code, wrong feature." | Architect doc = the spec; add a cheap spec-compliance pass before the quality adversary. | idea-only | 4 |
| 18 | **Magentic progress-ledger (per-step satisfaction/loop judgment)** | **autogen** `_magentic_one_orchestrator.py` (peer: ms-agent-framework `orchestrations/_magentic.py`) | Each step, one JSON call answers `is_request_satisfied`, `is_in_loop`, `is_progress_being_made`, `next_speaker`, `instruction`; stall counter triggers root-cause replan. Continuous self-assessment of "are we done / stuck". | Principled replan + done-judgment trigger vs the 40-iter livelock guard. | port-code | 4 |
| 19 | **Verification evidence ledger + verify-on-stop guard** | **hermes** `agent/verification_evidence.py` + `verification_stop.py` | Passive WAL ledger classifying each command (kind/scope/status) as "what was actually proven"; a turn-end guard nudges a bounded verify when the model finishes after editing code with no fresh evidence (suppressed for doc-only edits). | Shifts from "string in source" to "a real check ran and passed"; doubles as the per-run proof trail. | port-code | 4 |
| 20 | **Sycophancy detector (rubber-stamp guard)** | **loki-mode** `swarm/sycophancy.py` (peer: bernstein `eval/calibration.py` Brier) | Pure-deterministic 0–1 score over reviewer votes: blend of verdict unanimity, Jaccard reasoning-similarity, severity uniformity, issue-count spread; high ⇒ fire Devil's-Advocate re-review. No LLM call. | Scores 9TO5's adversary/second-brain for rubber-stamping; cheap; catches "3 approvals = meaningless." | port-code | 4 |
| 21 | **Plan shape-check + corrective re-prompt (verify the decomposition)** | **bernstein** `core/planning/vertical_slice.py` + `planner.py::_run_shape_check_with_retry` (peers: dify `runner._validate_structure`, ms-agent-framework graph validation) | Deterministic post-LLM validator rejects too-coarse / horizontally-layered plans (LOC/files/layer caps); on violation re-prompts the LLM ONCE with a structured violation report. | Verification applied to planning output; reliable task graphs without a bigger brain. | port-code | 4 |
| 22 | **SpanQuery trace-assertion DSL (behavioral facts over strings)** | **pydantic-ai** `pydantic_evals/otel/span_tree.py` | Serializable query language over an execution span tree (`name_matches_regex`, `has_attributes`, `min/max_duration`, `some_child_has`…). A verify can assert "a test-run span exited 0", "no tool ran > N s". | Assert behavioral facts about *what executed* instead of scanning source text. | port-code | 4 |
| 23 | **Agent-regression / scenario harness (held-out behavioral suite)** | **swarmclaw** `eval/{runner,scenarios-swebench,scenarios-gaia}.ts` (peers: crewai `ExperimentRunner`, eliza `packages/scenario-runner`, bernstein `eval/golden.py`) | Scenario runner spins isolated workspace, runs agent end-to-end, scores weighted assertions; ships SWE-bench/GAIA sets; bernstein auto-synthesizes regression cases from incidents. | Turns `experience.db` passing rows into a labeled regression benchmark; detect regressions across constitution swaps. | heavy | 3 |
| 24 | **Autonomy supervisor reflection (incidents → auto-actions)** | **swarmclaw** `autonomy/supervisor-reflection.ts` (peer: loki uncertainty-gated escalation) | Post-run observer emits typed incidents + auto-actions (`block`/`replan`/`compact`/`budget_trim`) folded into next run's context; severity-scored. | Structured replan/compact loop richer than a single advisory adversary verdict. | heavy | 3 |
| 25 | **Structured findings injection + accumulated learnings** | **loki-mode** `loki-ts/src/runner/{findings_injector,learnings_writer}.ts` (peer: metagpt `debug_error.py` console-log feedback loop) | Per-finding records persisted and injected into the NEXT iteration prompt (not just gate-fail tokens); auto-write structured learnings per review cycle. | 9TO5 re-prompts with raw failure text; structured per-finding injection is a richer feedback loop. | port-code | 3 |

---

## 3. If 9TO5 adopts ONE thing for this theme

**Adopt eliza's CompletionEnvelope + independent execution-grounded verifier (Agent-as-a-Judge), with loki's
facts-vs-assessments Evidence Receipt as the deterministic gate underneath it.** Concretely: make every subtask
end by emitting a structured `CompletionEnvelope`
(`references/eliza/plugin-agent-orchestrator/src/services/completion-envelope.ts`) — real `testResults`
with command exit codes, per-criterion `{met, evidence}`, `filesChanged`, `residualRisks` — then spawn a
SEPARATE read-only Claude verifier
(`.../services/independent-verifier.ts`) that *re-runs* the tests/build/typecheck and reads the diff, judging
each criterion only from output it produced itself, and computing the green headline ONLY from re-derivable
facts (`references/loki-mode/autonomy/lib/proof-generator.py`'s facts-vs-assessments split, with
"inconclusive ≠ verified"). This is the single highest-leverage change because it attacks 9TO5's root failure
on two axes at once: it replaces `buildContentScanVerify`'s "markers present in source" theater — which a
verbose wrong implementation trivially satisfies — with execution-grounded proof, AND it breaks the structural
reward-hacking risk that the same 7B brain authors both the work and the verify, since the verdict now comes
from a verifier that didn't write the code and from facts (`diff_sha256`, test exit codes) no LLM opinion can
flip. Both pieces are MIT-licensed, self-contained, pure-ish modules that map directly onto 9TO5's existing
`agents/verifier.py` + adversary slot, and the resulting per-subtask receipt doubles as the durable audit
artifact 9TO5's observability stack is also missing.
