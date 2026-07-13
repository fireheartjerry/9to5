# AURA Ω Revision 3: Evidence-Routed Autonomous Systems Architecture

> **Date:** 2026-07-13
>
> **Status:** preapproved design; implementation follows without another approval pause
>
> **Branch:** `main`
>
> **Hard constraint:** essentially zero incremental external operating cost
> **Capability boundary:** existing local Ollama, Claude Code subscription, and Codex/ChatGPT subscription are permitted; paid APIs, metered hosted inference, and recurring SaaS are not

## 1. Executive decision

AURA Ω Revision 3 replaces 9to5's aging “Ollama brain, Claude hands” hierarchy with an **evidence-routed autonomous systems kernel**:

1. A small deterministic run kernel owns authority, state transitions, capability checks, isolation, merge, verification, and recovery.
2. Claude and Codex become peer execution drivers with distinct, measured capability profiles. Neither is subordinate to the other, and neither owns truth.
3. Ollama becomes the zero-cost reflex tier: classification, compression, retrieval shaping, low-risk drafting, and degraded planning. It may propose; it does not become an unquestioned sovereign.
4. Every adaptive mechanism begins in shadow mode and earns production authority through matched experiments and independently resolved receipts.
5. Rich graph, memory, society, innovation, and dashboard surfaces are projections over canonical facts. They do not create additional writers or parallel truth systems.

This is not a cosmetic provider adapter. It changes the unit of autonomy from “a model session that probably succeeded” to **an isolated, leased, verified attempt whose effects and evidence are explicit**.

The architectural maxim remains:

> **Strict protocol, replaceable intelligence, earned authority.**

The deliberate compression of operational authority is not a reduction in ambition. It is what makes much more aggressive search, parallelism, invention, recovery, and self-improvement safe enough to activate.

## 2. What “world-class” means here

Revision 3 must not call itself world-class because it has more agents, nodes, model names, or dashboards. It earns that claim only if it demonstrates all of the following under the same pinned local resources:

- higher verified task completion than the current 9to5 baseline;
- no false success when worktree collection or canonical merge fails;
- zero privilege widening when an isolation backend is unavailable;
- zero lost or duplicated operator commands under injected crashes;
- recovery that distinguishes “not executed,” “executed but unrecorded,” and “recorded but not finalized” at the attempt boundary;
- better abstention and clarification on genuinely under-specified work;
- cross-provider review that is actually independent;
- calibrated forecasts and routing decisions that beat static baselines out of sample;
- memory that improves later task behavior without importing unresolved or contradictory claims as truth;
- exactly zero paid API or recurring SaaS calls in the zero-cost profile;
- an evidence trail sufficient to reproduce, falsify, and roll back every promoted behavior change.

RigorBench's five process pillars—planning fidelity, verification coverage, recovery efficiency, abstention quality, and atomic transition integrity—are useful external dimensions, but AURA will keep the dimensions separate instead of hiding failure behind one composite score. SecureVibeBench, MemoryAgentBench, MemSyco-Bench, scope-discipline fixtures, and repo-local outcome suites provide complementary failure surfaces.

## 3. Brownfield truth: what exists now

### 3.1 Foundations worth preserving

The live codebase already contains unusually strong primitives:

- Task JSON is the run-state authority and the run process is its intended single writer.
- `control.db` provides SQLite/WAL serialization and stable command/spend deduplication seams.
- Typed verifier receipts separate observed facts from annotations.
- Worktree leases exist, and the parallel path already demonstrates merge-before-finalize ordering.
- Validation caching fingerprints repository state.
- Outcome evaluation records semantic result, duration, policy evidence, actual mode, and cost truth.
- The project model injects bounded repository structure into planning.
- Clarification recovery can persist exact decisions and block high-risk unknowns.
- Elaborator, Architect, Innovator, Council/Society, Human Nature, discovery, adversary, verifier, and self-evolution capabilities all have reusable seams.

Revision 3 keeps these capabilities. It changes their authority, evidence requirements, and routing.

### 3.2 Critical truth gaps

The live architecture currently permits several false claims:

1. **Completion before collection.** `_executeSubtask` can mark a subtask done before its environment is collected and merged.
2. **Silent failed winner merge.** `exitWorktree` returns `merged=False` rather than raising, while the winner merge caller ignores the result and records verification.
3. **Privilege-widening fallback.** A failed or unknown isolated backend can degrade to `LocalEnvironment` in the canonical tree.
4. **Delete-before-apply commands.** `drainOps` deletes commands before the run process applies and saves them.
5. **Opaque effects.** Claude's internal tool calls are observed at request time, not completion time; a step journal cannot honestly promise per-tool exactly-once behavior.
6. **Provider monoculture.** Invocation specs are authored by Ollama, terminal execution always routes to Claude, and “independent verification” is another Claude session.
7. **Unenforced zero-cost policy.** Cost accounting is post-hoc, advisory, disabled by default, and autonomous mode may proceed over allowance.
8. **Confounded learning.** Provider, assignment probability, quota state, capability profile, and policy version are missing from outcome rows.
9. **Synthetic metrics.** Several quality-diversity fields are constants; UCB emitters have no production reward updates; Human Nature “A/B” lacks an off arm; reflections can become trusted without positive verification.
10. **All-on activation.** `FULL_STACK` and inherited flags can activate behavior-changing systems without outcome receipts proving they help.

Revision 3 treats these as architectural blockers, not cleanup.

## 4. Alternatives considered

| Architecture | Description | Real gain | Fatal limitation | Decision |
|---|---|---|---|---|
| **A. Add Codex beneath the current Ollama manager** | Keep Ollama-authored specs, send some tasks or reviews to Codex | Fastest integration | Codex remains ornamental; the 7B/8K planning bottleneck and single-model authority survive | Rejected |
| **B. Always run Claude and Codex in a competitive swarm** | Parallel plans, implementations, debates, and judges for every task | Maximum raw search | Doubles scarce subscription usage, amplifies broken merge/effect semantics, and rewards theatre on simple work | Rejected as default; retained as a selective mode |
| **C. Deterministic kernel plus heterogeneous driver fabric** | Typed contracts, hard capability eligibility, isolated attempt transactions, peer Claude/Codex drivers, Ollama reflex tier, shadow experiments, selective tournaments | Real independence, failover, measurable routing, safe expansion | Requires contract migration and disciplined rollout | **Selected** |

Architecture C can invoke B when expected value justifies it: high-risk changes, repeated failures, high uncertainty, or an experiment explicitly measuring search diversity. Routine work remains single-writer.

## 5. The three authoritative layers

### 5.1 Omega Kernel: deterministic run authority

The Omega Kernel owns:

- goal/acceptance digests;
- task and subtask status;
- capability profiles;
- worktree and provider-capacity leases;
- command state;
- attempt state and its linked immutable receipts;
- merge receipts;
- provider-independent capability-enforcement receipts;
- deterministic verification;
- external-effect authorization;
- finalization;
- abort/kill authority.

Models can propose plans, claims, commands, patches, reviews, and experiments. They cannot directly:

- mark work complete;
- merge a branch;
- widen a capability;
- spend through a metered provider;
- promote a policy;
- turn an unresolved memory into trusted knowledge;
- mutate the authoritative graph.

### 5.2 Prism Fabric: heterogeneous intelligence and execution

Prism is a provider-neutral driver fabric.

- **Claude driver:** planning, writing, repair, review, and long-context execution through the locally authenticated Claude Code CLI.
- **Codex driver:** planning, writing, repair, review, and repository work through the locally authenticated Codex CLI.
- **Ollama driver:** cheap local classification, compression, retrieval shaping, deterministic-schema drafting, low-risk hypothesis generation, and degraded fallback where its capability is sufficient.
- **Browser/native drivers:** optional execution surfaces selected only when terminal or local programmatic paths cannot satisfy the task.

Each driver implements:

~~~python
class ExecutionDriver(Protocol):
    def health(self) -> DriverHealth: ...
    def supports(self, profile: CapabilityProfile) -> bool: ...
    def invoke(self, spec: ProviderNeutralSpec, lease: AttemptLease) -> ExecutionReceipt: ...
    def resume(self, session: SessionIdentity, spec: ProviderNeutralSpec) -> ExecutionReceipt: ...
    def cancel(self, attempt_id: str) -> CancelReceipt: ...
~~~

Provider output is normalized before it can influence orchestration.

Driver self-attestation is never sufficient to prove confinement. A provider-independent
`CapabilityEnforcer` applies and verifies OS, container, process, filesystem, network, and
merge restrictions. Eligibility requires an enforcement receipt from that layer, not a
provider flag claiming that the restriction was honored.

### 5.3 Crucible: experimental control plane

Crucible owns no production state. It:

- creates immutable experiment manifests;
- assigns matched or randomized treatments;
- records assignment probability and policy version;
- evaluates champion versus challenger on the same hidden fixtures;
- resolves forecasts and claims;
- computes paired uncertainty intervals;
- recommends promotion, continued shadowing, or rejection.

Promotion remains a deterministic policy over receipts. The system being evaluated cannot promote itself.

## 6. Target flow

~~~mermaid
flowchart TD
    H["Human goal and hard constraints"] --> A["Authority envelope"]
    A --> I["Intent compiler and grounded elaborator"]
    I --> C{"Ambiguity and risk gate"}
    C -->|"safe and grounded"| G["Typed mission DAG"]
    C -->|"read-only evidence useful"| P["Local probe"]
    P --> C
    C -->|"material unresolved choice"| Q["Clarification or blocked state"]

    G --> K["Omega controller"]
    K --> M["Evidence-scoped memory retrieval"]
    K --> R["Capability and provider router"]
    K --> V["Value-of-information planner"]
    K --> B["Provider-capacity and zero-cost leases"]

    R --> O["Ollama reflex or draft"]
    R --> CL["Claude driver"]
    R --> CX["Codex driver"]
    V --> T{"Selective tournament?"}
    T -->|"no"| W["Single writer in isolated worktree"]
    T -->|"yes"| WC["Claude candidate worktree"]
    T -->|"yes"| WX["Codex candidate worktree"]
    O --> W
    CL --> W
    CX --> W
    WC --> J["Facts-first candidate judge"]
    WX --> J
    J --> W

    W --> EI["Attempt intent and lease"]
    EI --> EX["Opaque model execution"]
    EX --> AR["Immutable execution receipt"]
    AR --> VI["Verification in isolated tree"]
    VI -->|"fail"| FC["Failure classifier"]
    FC -->|"repair"| W
    FC -->|"provider failure"| R
    FC -->|"unsafe or ambiguous"| Z["Blocked or quarantined"]
    VI -->|"pass"| XR["Cross-provider semantic review"]
    XR -->|"material finding"| FC
    XR -->|"acceptable"| MG["Kernel-controlled merge"]
    MG -->|"merge failed"| Z
    MG -->|"merged"| VC["Verification in canonical tree"]
    VC -->|"fail"| Z
    VC -->|"pass"| FR["Immutable finalization receipt"]
    FR --> F["Finalize subtask"]

    F --> E["Outcome and evidence graph"]
    E --> CR["Crucible experiments and causal credit"]
    CR --> PM{"Promotion gate"}
    PM -->|"earned"| RP["Routing, memory, or policy update"]
    PM -->|"not earned"| SH["Remain shadow or reject"]

    E --> OB["AURA Constellation projection"]
    RP --> K
    SH --> K

    OC["Operator command inbox"] --> DL["Durable claim, apply, acknowledge"]
    DL --> K
    EG["Brokered external-effect gateway"] --> K
    K --> EG
~~~

The dashboard requested by the user is the `AURA Constellation` projection of this flow. It will highlight the current node, active leases, causal parents, uncertainty, provider route, verification state, recovery edges, and evidence behind every displayed score. It is deliberately implemented after the kernel emits trustworthy events.

## 7. Canonical contracts

### 7.1 `TaskEnvelope`

Contains:

- task/run/subtask IDs;
- raw and elaborated goal digests;
- acceptance-criteria digest;
- base revision;
- project-model version;
- deadline and work profile;
- required capability;
- allowed paths and forbidden effects;
- risk and uncertainty assessments with provenance;
- human-authority reference.

### 7.2 `CapabilityProfile`

Profiles are named, versioned, and closed:

| Profile | Read | Write | Shell | Network | Merge | External effect |
|---|---:|---:|---:|---:|---:|---:|
| `classify_local` | bounded artifact | no | no | no | no | no |
| `plan_readonly` | repo/worktree | no | deny by default | no | no | no |
| `review_readonly` | immutable diff and receipts | no | allowlisted checks only | no | no | no |
| `writer_worktree` | one leased worktree | one leased worktree | allowlisted | no by default | no | no |
| `trusted_local` | explicitly scoped | explicitly scoped | allowlisted | explicit | kernel only | broker only |
| `external_effect` | required evidence | broker-owned | broker-owned | explicit target | no | one typed effect |

An unavailable capability fails closed. Provider failover is allowed only to a driver that supports the same profile. Environment failover may never widen from isolated to canonical.

### 7.3 `ProviderNeutralSpec`

The provider-neutral spec contains:

- role: plan, write, repair, review, or summarize;
- objective and acceptance criteria;
- context artifact references;
- capability profile;
- worktree lease;
- output schema;
- effort/resource class;
- resume policy;
- required skills as semantic capabilities, not Claude-specific command names;
- cancellation and deadline contract.

Claude-specific fields such as `claude_md_inject`, hooks, effort flags, settings files, and model names belong in the Claude adapter. Codex sandbox, profile, schema, JSONL, and session flags belong in the Codex adapter.

### 7.4 `RoutingDecision`

The router first applies hard eligibility:

- zero-cost auth mode;
- CLI health and version;
- capability support;
- isolation availability;
- quota/circuit state;
- session compatibility;
- model/role support;
- deadline feasibility.

Only then may it score eligible drivers using:

- matched first-pass rate;
- verified success;
- recovery rate;
- latency;
- provider-capacity pressure;
- reviewer catch precision;
- task-family uncertainty;
- recent drift.

The record includes all candidate scores, rejected reasons, selected provider, selection probability, policy version, and whether the decision was static, shadow, randomized, or adaptive.

### 7.5 Receipt chain and `AttemptView`

An attempt is represented by linked immutable records, never by mutating one “final”
receipt as later phases occur:

- `ExecutionReceipt` records attempt/routing IDs, provider and versions, requested and
  evidence-backed actual model, auth/billing mode, capability-enforcement receipt,
  prompt/schema digests, resource lease, session hash, worktree/base/head/diff digests,
  timings, usage/cost knowledge, observed tool events, and normalized execution failure.
- `VerificationReceipt` records the tree revision and artifact digests it evaluated,
  commands/oracles, evidence, verdict, and verifier identity. Isolated and canonical
  verification are separate records.
- `ReviewReceipt` records the reviewer provider, clean-room context digest, findings,
  contamination controls, and advisory/hard-gate decision.
- `MergeReceipt` records the merge lease, expected and observed target SHA, source SHA,
  result, canonical head, recovery artifact, and error.
- `FinalizationReceipt` links the accepted execution, verification, review, and merge
  receipts to the terminal state.

`AttemptView` is a recomputable materialized projection over this chain for dashboards,
routing, and analysis. It is not another writer or authoritative record.

### 7.6 `MergeReceipt`

Contains the source branch/head, expected target SHA, observed target SHA, canonical-merge
lease/fencing token, merge result, resulting canonical head, conflict/error, retained
recovery artifact, and post-merge verification reference. Merge is a compare-and-swap:
the canonical HEAD must still equal the expected target SHA while the exclusive merge lease
is held. Drift requires a rebase plus re-verification or quarantine; it never silently
merges a stale verified candidate. No subtask can enter `done` without a successful merge
receipt when its execution occurred outside the canonical tree.

## 8. Transaction and recovery semantics

### 8.1 Honest transaction boundary

Claude and Codex are opaque agent processes. Revision 3 does **not** claim exactly-once semantics for their internal tool calls.

The first honest transaction boundary is an isolated attempt:

~~~text
prepared
-> leased
-> running
-> captured
-> verified_isolated
-> merged
-> verified_canonical
-> finalized
~~~

Terminal alternatives:

~~~text
blocked | failed | cancelled | quarantined | superseded
~~~

A crash can leave a worktree and receipt recoverable without marking the task complete. Resume compares base revision, capability digest, provider/role, plan signature, and attempt state before deciding whether to resume, retry, quarantine, or create a fresh branch.

Canonical merge is serialized by an exclusive lease and fenced compare-and-swap on the
expected target SHA. Verification performed against a stale base cannot authorize a merge
into a newer canonical tree.

### 8.2 Brokered external effects

Irreversible or externally visible actions—PR creation, push, Discord posts, publication, remote mutation—must go through a kernel effect gateway:

~~~text
intent
-> authorized
-> reserved
-> leased
-> prepared
-> preverified
-> committed
-> postverified
-> finalized
~~~

Failure states are `compensated`, `quarantined`, or `ambiguous`. Every effect has an idempotency key, target fingerprint, fencing token, verification rule, and optional compensation. The gateway can provide exactly-once *intent handling* and at-most-once commit where the target supports idempotency. It must report ambiguity honestly when the external target cannot prove the outcome.

### 8.3 Durable operator commands

`drainOps` is replaced by a lifecycle in the existing control store:

~~~text
received -> claimed -> decided -> applied/rejected -> acknowledged
~~~

Claims have expirations and fencing tokens. Stable command IDs make replay safe. A command is never deleted before its applied/rejected result is durably recorded. Task JSON remains the run-state authority; `control.db` remains the operator-intent authority.

Because applying a command spans both authorities, the stable command ID is persisted inside
the same crash-safe TaskState save as the command mutation. Reapplication checks that ID and
is a no-op when already present. After restart, a reconciler compares TaskState's applied-ID
set with `control.db` and repairs missing acknowledgements. This turns the unavoidable dual
write into an idempotent, convergent protocol rather than pretending it is one transaction.

## 9. Claude–Codex peer fabric

### 9.1 Zero-cost preflight

The current machine was verified to have:

- Claude Code 2.1.197 authenticated through `claude.ai` Max;
- Codex CLI 0.144.1 authenticated through ChatGPT;
- no Anthropic/OpenAI API keys or Bedrock/Vertex/Foundry selectors in the process environment.

Every production launch repeats a machine-readable preflight and persists the result. The zero-cost profile:

- rejects API-key billing modes;
- strips provider override variables from child environments;
- forbids hidden model/provider fallback;
- disables external council seats;
- records subscription capacity as a scarce lease even when dollar cost is zero;
- never relabels unknown cost as zero.

### 9.2 Roles, not personalities

Provider choice is empirical. Revision 3 does not hard-code “Claude is architect” or “Codex is reviewer” as truth.

Initial deterministic crossover policy:

- a Claude-authored diff receives a fresh Codex semantic review;
- a Codex-authored diff receives a fresh Claude semantic review;
- deterministic verification remains primary;
- a same-provider second session is “additional review,” not independent review;
- low-risk mechanical work may skip semantic cross-review when the evidence policy permits;
- high-risk or repeatedly failing work may run independent Claude and Codex proposals in separate worktrees.

Cross-provider review is clean-room review, not merely a fresh process. The reviewer receives
only the immutable task/acceptance contract, diff digest and content, deterministic evidence,
and permitted repository snapshot. It does not receive writer chain-of-thought, transcript,
self-authored tests as ground truth, or memory derived from the attempt. The review receipt
records the context digest and contamination controls so independence can be tested.

### 9.3 Sessions

Session identity is keyed by:

~~~text
run + subtask + provider + role + generation + capability_digest + base_sha
~~~

Sessions never resume across provider, role, capability, or base-SHA changes. Exact session IDs are protected state; telemetry carries a hash. Capacity state is provider-specific, so a Claude usage-window pause does not stall safe Codex or Ollama work.

### 9.4 Failure classes

| Failure | Required behavior |
|---|---|
| `AUTH_OR_BILLING_MISMATCH` | Disable provider; never switch to a metered key |
| `QUOTA_OR_RATE_LIMIT` | Open provider circuit until verified reset; route compatible alternate |
| `LAUNCH_OR_TRANSIENT` | One bounded retry, then fresh alternate-provider attempt |
| `TOOL_OR_SANDBOX_DENIAL` | Fail closed; never widen capability |
| `MALFORMED_OUTPUT` | Preserve raw artifact; bounded schema repair or alternate provider |
| `VERIFICATION_FAIL` | One same-writer repair, then classified failover or fresh branch |
| `PARTIAL_WRITE` | Preserve branch/diff artifact; never merge automatically |
| `MERGE_CONFLICT` | Abort canonical merge, retain branch, quarantine result |
| `CANCELLED` | Kill process tree, preserve non-final receipt, do not consume success credit |

## 10. Adaptive orchestration without confounding

### 10.1 Operational modes

1. **Static single writer:** cheapest reliable eligible driver.
2. **Crossover review:** one writer, other provider reviews immutable diff.
3. **Parallel tournament:** multiple isolated candidates, facts gate, deterministic verification, then evidence-based judge.
4. **Recovery failover:** alternate provider after classified failure.
5. **Shadow routing:** alternate decision is recorded or evaluated on fixtures but cannot control production.

### 10.2 Value of information

Additional deliberation is invoked only when expected information gain exceeds its provider-capacity and latency cost. Inputs include:

- calibrated uncertainty;
- action reversibility;
- blast radius;
- prior disagreement rate;
- predicted branch diversity;
- verification strength;
- remaining deadline/capacity.

This converts Council/Society from an always-on cast of characters into a selective protocol. The local two-seat form is Claude plus Codex; Ollama can cheaply screen whether escalation is worthwhile.

### 10.3 Search

Once receipts are truthful:

- use successive halving or Hyperband to allocate time among candidate branches;
- update UCB/Thompson arms only from marginal verified gain per capacity unit;
- use deterministic max-min selection on behavioral diff features to preserve real diversity;
- use restart schedules after measured stagnation;
- keep unknown metrics unknown.

No search mechanism is promoted if it merely changes labels or produces larger diffs without better verified outcomes.

## 11. Evidence, claims, memory, and causal credit

### 11.1 Evidence graph

The rich AURA graph contains:

- task, subtask, attempt, artifact, command, effect, verification, review, incident, forecast, claim, experiment, policy, memory, and promotion nodes;
- caused-by, derived-from, contradicts, resolves, verifies, invalidates, attempted-by, reviewed-by, merged-as, compensated-by, and promoted-from edges.

A node becomes canonical only if it has:

- stable identity;
- an independent lifecycle or resolution;
- provenance and integrity;
- a non-derivable relationship that matters across objects.

Confidence, novelty, risk, intelligence, health, and authority are versioned assessments over evidence, not free-standing truths.

### 11.2 Claims

Claims follow:

~~~text
proposed -> evidenced -> contested -> resolved_true/resolved_false/unresolved -> superseded
~~~

An attestation is a receipt reference from an authorized resolver, not a forgeable string. Model-authored text remains a proposal until independently resolved.

### 11.3 Forecasts and calibration

Every forecast has:

- stable ID;
- context and policy version;
- probability;
- horizon;
- resolution rule;
- outcome receipt.

Evaluation uses Brier/log loss, empirical base-rate baselines, interval coverage, and drift detection. Human Nature confidence, world-model probabilities, and router confidence remain shadow signals until they beat those baselines.

### 11.4 Memory

Memory is split by function:

- **episodic:** immutable attempt/outcome history;
- **semantic:** resolved facts with provenance and contradiction edges;
- **procedural:** promoted recipes that passed hidden evaluation;
- **prospective:** unresolved forecasts and commitments;
- **operator:** human preferences and authority, never inferred from model prose.

Trust fails closed: `verify_passed is True` and a resolving receipt are required for durable procedural memory. Consolidation retains negative and contradictory evidence, uses bounded sampling, and can always reconstruct a lesson's lineage.

### 11.5 Causal credit

Terminal reward is not assigned to every preceding node. Credit requires an event DAG and matched interventions:

- paired replay changing one policy;
- randomized shadow assignment where safe;
- leave-one-decision-out analysis for small decision sets;
- cohort stratification by workload;
- sensitivity to reweighting.

If the method cannot recover injected causal factors in simulation, it cannot control production.

## 12. Existing feature migration

Revision 3 includes the old features explicitly:

| Existing feature | Revision 3 role |
|---|---|
| Elaborator | Intent compiler and grounded acceptance-contract author; one pass by default, extra candidates earned by uncertainty |
| Architect | Provider-neutral architecture/proposal role served by Claude, Codex, or both |
| Innovator | Hypothesis emitter feeding Crucible; ideas need experiment, owner, lifecycle, and outcome |
| Discovery | Evidence and opportunity ingestion; never authoritative without attestation |
| Council/Society | Selective value-of-information protocol, local Claude/Codex seats, not an always-on external-provider parliament |
| Human Nature/Psyche | Shadow assessments and bounded priors until each coupling wins a real control-arm experiment |
| Clarification Gate | Moves before execution; uses deterministic/read-only probes, blocks high-risk unknowns |
| Adversary | Cross-provider semantic critique with measured catch precision |
| Verifier | Deterministic receipt authority; semantic models may downgrade or request repair, never fabricate a pass |
| Solution space/QD | Truthful measured branch search; synthetic metrics removed or marked unknown |
| Self-evolution/SIE | Proposal and experiment generation; promotion remains external to the candidate |
| Browser/native | Optional capability adapters with semantic postcondition receipts |
| Dashboard | AURA Constellation, a read-only projection of canonical events |

## 13. Complexity-theatre kill list

Freeze or remove from production authority until proven:

- constant-filled QD metrics;
- UCB schedulers without reward updates;
- observational telemetry labelled A/B;
- raw challenge-rate suppression as fitness;
- plan stability as an unconditional reward;
- trusted reflections with unknown verification;
- “world model” probabilities without resolution;
- external council seats in the zero-cost profile;
- full-stack flags that inherit production activation without receipts;
- intelligence/health/aura composites that cannot be recomputed from canonical events;
- per-tool exactly-once claims for opaque CLI processes;
- adaptive routing trained from non-random, provider-unlabelled history.

The code may remain available for experiments. It does not steer production.

## 14. Brownfield transfers

Revision 3 reuses patterns, not mythology:

| Source | License/posture | Transfer |
|---|---|---|
| Existing 9to5 TaskState, ControlBus, receipts, worktrees, validation cache, outcome evaluator | native | Canonical authority and migration base |
| OpenAI `codex-plugin-cc` | Apache-2.0 | Codex health/delegation lifecycle and background-job lessons; reimplemented behind a neutral driver rather than nesting under Claude |
| UW SyFi TraceLab | open repository | Common Claude/Codex trace schema, sanitization, workload/capacity analysis |
| Hermes | MIT | environment and restricted background-review patterns already harvested locally |
| Guild | Apache-2.0 | stable local task identity, SQLite coordination, and atomic claim patterns |
| LangGraph | permissive local reference | journal/checkpoint concepts, adapted to attempt-level honesty |
| OpenHands | permissive local reference | sandbox/artifact recovery and event-stream patterns |
| AGX | MIT | typed DAG, event-sourced runtime, resume checks |
| Code as Agent Harness survey repository | research index | Treat orchestration as executable, inspectable harness mechanisms |

No proprietary Claude Code source is copied. Public CLI contracts and ideas are reimplemented.

Primary recent evidence:

- [RigorBench](https://arxiv.org/abs/2606.22678)
- [TraceLab paper](https://arxiv.org/abs/2606.30560) and [repository](https://github.com/uw-syfi/TraceLab)
- [SecureVibeBench](https://aclanthology.org/2026.acl-long.1107/)
- [MemoryAgentBench](https://openreview.net/forum?id=DT7JyQC3MR)
- [MemSyco-Bench](https://arxiv.org/abs/2607.01071)
- [OpenAI Codex plugin for Claude Code](https://github.com/openai/codex-plugin-cc)
- [Code as Agent Harness survey repository](https://github.com/YennNing/Awesome-Code-as-Agent-Harness-Papers)

Recent community evidence is used only to generate hypotheses. Low-ranked or comment-poor items from the last-30-days pass are not treated as proof.

## 15. Experiment program

| Order | Experiment | Key ablations | Promotion/falsification |
|---|---|---|---|
| E0 | Reproducible manifest and immutable receipt chain | remove provenance, seed, or policy version | deterministic replay of the same raw artifacts must reproduce classification; repeated live model runs must stay within preregistered distributional bounds; overhead under 1% |
| E1 | Attempt/merge crash matrix | remove merge receipt, canonical verify, or lease fencing | 1,000 seeded transition crashes; zero false done, lost command, or duplicate brokered effect |
| E2 | Capability escape matrix | each driver/profile/backend failure | zero forbidden writes, canonical-tree launches, network escapes, or privilege widening |
| E3 | Claude/Codex CLI contract and zero-cost preflight | auth mismatch, hidden fallback, malformed schema | all launches prove subscription/local mode; metered mode hard-blocks |
| E4 | Cross-over quality benchmark | Claude-only, Codex-only, crossover, routed | routed lower bound non-inferior to best static; material verified gain or latency/recovery gain |
| E5 | Truthful branch scorer | single branch, cheapest verified, diversity off | must beat cheapest verified baseline without safety/cost regression |
| E6 | Anytime search | fixed-N, adaptive allocation, restarts/diversity off | higher verified wins per capacity minute; behavioral, not label-only, diversity |
| E7 | Forecast and causal credit | base rate, unpaired, no drift, no intervention | beat base-rate calibration; recover injected causes; stable under cohort reweighting |
| E8 | Evidence-preserving memory | vector-only, recency-only, contradiction off | improved paired task success; zero poisoned trusted memories; rare failures retained |
| E9 | Anytime-valid promotion and observatory | unpaired test, visible fixtures, provenance hidden | A/A false promotion within target; hidden canary inaccessible; every panel recomputable |

Security and scope suites are hard constraints, not terms in a scalar objective.

## 16. Migration waves

### Wave 0: truth freeze and shadow instrumentation

- Declare `external_spend_allowed=False` in the zero-cost run policy.
- Stop unknown cost from rendering as zero.
- Add experiment manifests and the immutable receipt chain in shadow mode.
- Move ambiguity scoring and read-only clarification probes before planning so every later
  route operates on a resolved or explicitly blocked acceptance contract.
- Mark synthetic metrics unknown.
- Put Human Nature behavior couplings, external council seats, and adaptive evolution behind evidence states.
- Establish the current baseline before behavior changes.

### Wave 1: Transactional Attempt Kernel

- Finalize/collect/merge before subtask completion.
- Require a successful merge receipt and canonical verification.
- Make isolated execution fail closed.
- Replace delete-before-apply commands with claim/apply/ack.
- Add brokered effect records for externally visible operations.
- Preserve partial branches and ambiguous outcomes.

### Wave 2: Prism driver contract

- Introduce `ExecutionDriver`, `ProviderNeutralSpec`, `CapabilityProfile`, `RoutingDecision`,
  the immutable receipt types, and the recomputable `AttemptView`.
- Adapt the current Claude executor without changing baseline behavior first.
- Add first-class Codex health, launch, JSONL/schema, resume, cancel, and receipt normalization.
- Give Ollama a bounded reflex adapter.
- Use immutable per-attempt settings and provider-specific capacity circuits.

### Wave 3: deterministic crossover and selective deliberation

- Enable Claude-writer/Codex-review and Codex-writer/Claude-review in shadow evaluation.
- Reduce council to conditional local two-seat deliberation.
- Add high-risk parallel tournaments behind value-of-information thresholds.

### Wave 4: epistemic spine

- Stable claims, forecasts, resolution receipts, calibration, contradiction edges.
- Fail-closed procedural memory.
- Evidence-scoped retrieval.
- Human Nature signals remain shadow until independently promoted.

### Wave 5: adaptive search and causal learning

- Truthful branch metrics.
- Paired routing trials and capacity-aware bandits.
- Successive halving, diversity, and restart policies.
- Causal credit only after intervention tests pass.

### Wave 6: AURA Constellation

- Live graph position and transition animation.
- Attempt/provider/worktree lenses.
- Recovery and incident replay.
- Evidence and uncertainty inspection.
- Budget/capacity view.
- No dashboard-derived writes.

### Wave 7: benchmark campaign and world-class claim gate

- Pinned repo-local, RigorBench-style, security, scope, memory, crash, and multi-project suites.
- Same-resource comparison against the current baseline and representative open harnesses.
- Publish a reproducible evidence dossier.
- Claim “world-class” only if the predefined gates pass.

## 17. First implementation slice

The first code slice must be small enough to verify and foundational enough to change what can safely follow:

1. introduce a typed environment finalization/merge receipt;
2. move completion after successful finalization;
3. make winner merge fail when `merged=False`;
4. make required worktree isolation fail closed;
5. add focused crash/merge/fallback tests;
6. preserve the current public facades.

The next slice adds durable command claim/apply/ack. The first Prism slice then adds provider-neutral contracts and a Codex adapter in shadow/read-only mode before permitting Codex writes.

## 18. Acceptance gates

### Kernel

- 1,000 seeded crashes across every command and attempt transition produce zero lost or duplicate commands.
- No `done` subtask lacks a successful canonical merge receipt when isolation was used.
- No mutating subprocess launches in the canonical tree after an isolation failure.
- Every mutating launch has an OS/container-backed capability-enforcement receipt; driver
  self-report alone never satisfies eligibility.
- Concurrent merge attempts are serialized and fenced by expected-target-SHA compare-and-swap.
- Merge conflict, malformed receipt, quota exhaustion, or partial write ends as blocked, failed, cancelled, or quarantined—not success.

### Driver fabric

- 100% of attempts record provider, version, auth/billing mode, capability, spec hash, base/head/diff, lease, execution receipt, verification, and terminal state.
- Capability escape tests show zero forbidden filesystem, shell, network, merge, or sibling-worktree effects.
- Hidden provider/model fallback is zero.
- Cross-provider reviewer independence is explicit and fresh-session.
- Reviewer context excludes writer rationale/transcript and records contamination controls.

### Capability

- On preregistered paired tasks, routed policy is non-inferior within five percentage points on first-pass success and has a positive lower-bound gain on at least one of verified outcome, recovery, quota-stall avoidance, or p95 completion time.
- Parallel tournaments improve verified wins per provider-capacity unit over the cheapest verified static baseline.
- Clarification cuts wrong-path execution by at least 50% on the ambiguity corpus without exceeding a 20% user-question rate.
- Memory improves paired success and admits zero unresolved records into trusted procedural memory.

### Cost

- Process/environment/network audit shows exactly zero paid API or recurring SaaS calls.
- Subscription capacity is leased and bounded; over-capacity work waits, reroutes, or degrades locally.
- Unknown monetary or capacity data remains unknown.

### Promotion

- Each experiment preregisters one primary endpoint, minimum material effect, confidence
  level, risk-tiered power calculation, sequential stopping rule, and correction for any
  secondary-endpoint multiplicity.
- A/A trials meet an explicit preregistered false-promotion ceiling.
- Hidden fixture canaries prove acceptance logic is outside model-readable/writable scope.
- Evidence sufficiency follows the preregistered power calculation; a small pilot may validate
  instrumentation but can never authorize promotion merely by reaching a fixed row count.
- Rollback is deterministic and tested.

## 19. Non-goals

- No claim of per-tool exactly-once semantics for opaque Claude/Codex internals.
- No paid API fallback.
- No external multi-provider council in the zero-cost profile.
- No graph growth whose nodes lack identity, lifecycle, or evidence.
- No self-promotion by the proposing model or subsystem.
- No replacement of TaskState, ControlBus, verifier receipts, or human authority with Chronicle.
- No dashboard work before the event and receipt contracts are trustworthy.
- No reduction of the test suite as part of this program; that is explicitly owned elsewhere.

## 20. Final architectural invariant

AURA Ω Revision 3 may become extraordinarily complex in the **space of hypotheses, evidence, experiments, recovery paths, and projections**.

It remains deliberately simple in the **space of authority**:

~~~text
human authority
  > constitution and kill switches
  > deterministic capabilities and zero-cost policy
  > leases, commands, and effect authorization
  > isolated attempts and merge receipts
  > deterministic verification
  > evidence-backed promotion
  > model proposals, memories, councils, and projections
~~~

That ordering is the foundation for aggressive innovation without self-deception.
