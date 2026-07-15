# GALAXY Revision 3: Evidence-Routed Autonomous Systems Architecture

> **Date:** 2026-07-14 (revision pass; supersedes the 2026-07-13 freeze)
>
> **Status:** frozen target architecture with frozen companion plans; runtime implementation is not yet authorized
>
> **Branch:** `main`
>
> **Hard constraint:** exactly zero incremental external operating cost — zero paid API calls, zero metered hosted inference, and zero recurring SaaS in the zero-cost profile. ("Essentially zero" elsewhere in prose is shorthand for this exact-zero measurable target, not a looser allowance; §2, §18, and §19 are the normative statements.)
> **Capability boundary:** existing local Ollama, Claude Code subscription, and Codex/ChatGPT subscription are permitted; paid APIs, metered hosted inference, and recurring SaaS are not
>
> **Host platform:** the reference host is Windows-first (PowerShell 5.1 anchor, private ConPTY operator surface, NTFS 8.3/ADS/reparse handling, kernel-owned handle-relative materializer). POSIX equivalents (`TIOCEXCL` PTY, no-follow handles) are called out where they exist; any platform lacking a required fail-closed equivalent makes the affected capability `unavailable`, never silently degraded.

## 1. Executive decision

GALAXY Revision 3 replaces 9to5's aging “Ollama brain, Claude hands” hierarchy with an **evidence-routed autonomous systems kernel**:

1. A small deterministic run kernel owns authority, state transitions, capability checks, isolation, merge, verification, and recovery. Its root of trust is an OS-installed **Polaris Anchor** outside every target repository, with a protected pinned capsule/controller digest and monotone generation. The anchor verifies an immutable Singularity Boot Capsule and last-known-good controller bundle; self-referential 9to5 work never imports the checkout being modified.
2. Claude and Codex become peer execution drivers with distinct, measured capability profiles. Neither is subordinate to the other, and neither owns truth.
3. Ollama becomes the zero-cost reflex tier: classification, compression, retrieval shaping, low-risk drafting, and degraded planning. It may propose; it does not become an unquestioned sovereign.
4. Every adaptive mechanism begins in shadow mode and earns production authority through matched experiments and independently resolved receipts.
5. Rich graph, memory, society, innovation, and dashboard surfaces may transform or project immutable advisory artifacts over canonical facts. They do not create additional writers or parallel truth systems.
6. Repository-derived elaboration, discovery, planning context, validation, and review operate only on an immutable source snapshot through a credentialless read broker. Canonical is an attested object source and eventual promotion target, never a host execution or introspection working directory.
7. The purpose-distinct capability target expands the audited 71-node / 95-edge base through provider-neutral Flare teams, Magnetosphere admission, Nebula, [Pulsar R1](2026-07-14-galaxy-r3-pulsar-r1-qualified-topology.md), and [Quark Portfolio R2](2026-07-14-galaxy-r3-quark-portfolio-r2-qualified-topology.md) into a **131-node / 250-edge GALAXY core**. A separately counted, disabled Voyager boundary yields **134 nodes / 256 unique typed edges** without widening mutation authority. These are exact structural target counts, not manifest-qualified or runtime-enabled counts.

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

RigorBench's five process pillars—planning fidelity, verification coverage, recovery efficiency, abstention quality, and atomic transition integrity—are useful external dimensions, but GALAXY will keep the dimensions separate instead of hiding failure behind one composite score. SecureVibeBench, MemoryAgentBench, MemSyco-Bench, scope-discipline fixtures, and repo-local outcome suites provide complementary failure surfaces.

## 3. Brownfield truth: what exists now

### 3.1 Foundations worth preserving

The live codebase already contains unusually strong primitives:

- In the brownfield baseline, Task JSON is the run-state authority and the run process is its intended single writer. Pulsar may supersede only its scheduling fields after the externally anchored field-level cutover defined in the [Pulsar R1 annex](2026-07-14-galaxy-r3-pulsar-r1-qualified-topology.md#14-field-level-taskstate-cutover).
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
11. **Pre-execution host escape.** Discovery, repository grounding, planning context, council context, and path verification can read or execute repository-controlled content on the host before attempt isolation exists.
12. **Canonical preamble mutation.** Self-referential setup can check out a branch and the timed knowledge refresh can rewrite a tracked file before transactional admission, making both rollback truth and later clean-tree promotion unreliable.
13. **Post-verification host escape.** Legacy self-mod/pre-PR validation can execute tests and repository scripts on the host after candidate verification, outside the universal verifier authority.
14. **Post-seal rewrite.** Automatic PR creation can run checkout/add/commit/push after promotion, silently creating a second writer and invalidating the sealed revision.
15. **Import-before-admission bootstrap.** `main.py` imports the repository controller graph before any in-function guard can run. For self-referential work, a modified target checkout can therefore execute top-level controller code before attestation unless the root launcher is physically and cryptographically outside that checkout.

Revision 3 treats these as architectural blockers, not cleanup.

### 3.3 Blocker-to-resolution traceability

Each numbered blocker in §3.2 must be closeable against a named mechanism. An
implementing agent should treat this as an acceptance checklist: no blocker is
"resolved" until the cited section and the migration wave that lands it both
have receipts.

| # | Blocker | Primary resolving mechanism | Lands in |
|---|---|---|---|
| 1 | Completion before collection | Honest attempt transaction boundary (§8.1); collect/stage before completion | Wave 1 |
| 2 | Silent failed winner merge | `PromotionReceipt` CAS + fenced promotion (§7.7) | Wave 1 |
| 3 | Privilege-widening fallback | Fail-closed `CapabilityProfile` (§7.2), `CapabilityEnforcer` (§5.2); E2 escape matrix | Wave 1 |
| 4 | Delete-before-apply commands | Durable command lifecycle (§8.4) | Command/effect wave |
| 5 | Opaque effects | Non-goal on per-tool exactly-once (§19); attempt-level boundary (§8.1) | Wave 1 |
| 6 | Provider monoculture | Lensing peer fabric (§5.2, §9) | Wave 2 |
| 7 | Unenforced zero-cost policy | Zero-cost preflight (§9.1) | Wave 0 |
| 8 | Confounded learning | `RoutingDecision` provenance (§7.4), causal credit (§11.5) | Wave 5 |
| 9 | Synthetic metrics | Complexity-theatre kill list (§13) | Wave 0 |
| 10 | All-on activation | GraphWarrant-gated admission (§6.1), graph admission (Wave 7) | Wave 7 |
| 11 | Pre-execution host escape | Immutable source snapshot + credentialless broker (§5.1, §8.2) | Wave 1 (slice step 3) |
| 12 | Canonical preamble mutation | External state root; no run rewrites tracked paths (§5.1) | Wave 1 (slice steps 11–12) |
| 13 | Post-verification host escape | Exact-revision universal verifier (§8, slice step 12) | Wave 1 |
| 14 | Post-seal rewrite | Deferred PR publication; typed effect deferral (§8.3–8.4) | Command/effect wave |
| 15 | Import-before-admission bootstrap | OS-installed Polaris Anchor outside the checkout (§5.1, §18) | Wave 1 (slice step 1) |

## 4. Alternatives considered

| Architecture | Description | Real gain | Fatal limitation | Decision |
|---|---|---|---|---|
| **A. Add Codex beneath the current Ollama manager** | Keep Ollama-authored specs, send some tasks or reviews to Codex | Fastest integration | Codex remains ornamental; the 7B/8K planning bottleneck and single-model authority survive | Rejected |
| **B. Always run Claude and Codex in a competitive swarm** | Parallel plans, implementations, debates, and judges for every task | Maximum raw search | Doubles scarce subscription usage, amplifies broken merge/effect semantics, and rewards theatre on simple work | Rejected as default; retained as a selective mode |
| **C. Deterministic kernel plus heterogeneous driver fabric** | Typed contracts, hard capability eligibility, isolated attempt transactions, peer Claude/Codex drivers, Ollama reflex tier, shadow experiments, selective tournaments | Real independence, failover, measurable routing, safe expansion | Requires contract migration and disciplined rollout | **Selected** |

Architecture C can invoke B when expected value justifies it: high-risk changes, repeated failures, high uncertainty, or an experiment explicitly measuring search diversity. Routine work remains single-writer.

## 5. The three authoritative layers

### 5.1 Singularity Kernel: deterministic run authority

The Singularity Kernel owns:

- goal/acceptance digests;
- task and subtask status;
- capability profiles;
- clone/transaction and provider-capacity leases;
- command state;
- attempt state and its linked immutable receipts;
- promotion receipts;
- provider-independent capability-enforcement receipts;
- deterministic verification;
- external-effect authorization;
- finalization;
- abort/kill authority.

The kernel executes from a last-known-good controller bundle verified by an OS-installed Singularity
Anchor, never from the target checkout. On startup the Boot Capsule may invoke only that external
bundle's minimal recovery entrypoint with a one-use `RecoveryAuthority`. Recovery can no-follow-read
kernel metadata, quiesce registered resources, hash/type/identity-check only the exact journal-bound
changed paths, and finish that already-journaled ref/index/worktree or state transition under the
normal locks; it cannot return arbitrary content, call a model or network, migrate state, create an
attempt, or select a revision. An optional separate `LegacyStateMigrationAuthority` first permits
the host kernel to snapshot an explicit quota-bound legacy-state allowlist through retained native
handle-relative no-follow handles, rejecting reparse/symlink/mount/identity-race/multi-link input.
A credentialless offline container normalizes only that immutable blob snapshot, never target paths;
target config/secrets never become live config. After immutable receipts, the capsule re-attests
canonical and creates the source snapshot before normal controller startup. Direct `main.py`/`runFull`
cannot mint or invoke either authority.

All mutable controller state and configuration are external to the target. An anchor-attested,
per-repository state root holds TaskState, commands/control, receipts, heartbeat/IPC, logs, databases,
caches, sessions, generated knowledge, vault projections, and learning artifacts through no-follow,
hardlink/reparse-safe, quota-bound durable stores. Production configuration is protected typed anchor
input; target `.env`, overrides, `state/`, logs, and vault paths are inert snapshot or bounded legacy
migration data and can never redirect controller I/O. Fenced promotion is the only target-worktree
writer.

The first root is established by a fresh, digest-specific trust-on-first-install (TOFU) ceremony rather than
by repository self-approval. `TrustOnFirstInstallReceipt` has two closed submanifests:
`source_leaves`, whose policy-canonical bytes must equal the exact Task 1 proposal blobs, and
`artifact_leaves`, whose interpreter/runtime/OCI/config/layer/SBOM bytes must equal the exact hashes
named by proposal-bound locks and manifests. Text source canonicalization is strict UTF-8,
parent-BOM-preserving and CRLF-to-LF only; binary leaves are exact. A child-inaccessible operator
surface displays one Merkle root over both subroots and requires the full digest plus a fresh nonce.
Generic advance approval, including unattended approval given before those bytes exist, cannot mint
this root.

After Task 1, the anchor/client/capsule/closed-harness source and production image-input leaves are
frozen. Their final navigation headers are stabilized before the ceremony. Final activation proves
both source- and artifact-leaf equality to the protected receipt; any difference aborts the wave and
requires a new reviewed Task 1 proposal and fresh trust ceremony, not an invented in-place root
rotation. Production images likewise come only from independently verified offline OCI archives, or
from an already-owned local builder operating network/registry-disabled over completely hash-pinned
local inputs. If that closure is absent, preparation and review may continue, but TOFU, the Task 1
source commit, and cutover stop as typed unavailable.

Models can propose plans, claims, commands, patches, reviews, and experiments. They cannot directly:

- mark work complete;
- merge a branch;
- widen a capability;
- spend through a metered provider;
- promote a policy;
- turn an unresolved memory into trusted knowledge;
- mutate the authoritative graph.

### 5.2 Lensing Fabric: heterogeneous intelligence and execution

Lensing is a provider-neutral driver fabric.

- **Claude driver:** planning, writing, repair, review, and long-context execution through the locally authenticated Claude Code CLI.
- **Codex driver:** planning, writing, repair, review, and repository work through the locally authenticated Codex CLI.
- **Ollama driver:** cheap local classification, compression, retrieval shaping, deterministic-schema drafting, low-risk hypothesis generation, and degraded fallback where its capability is sufficient. Every call crosses an anchor-controlled local broker that accepts only protected local IPC or pinned loopback, disables proxies/redirects, and binds the exact model content plus runtime/binary digest/version to a live run or analysis authority.
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
merge restrictions. Hostile or unknown workload eligibility requires an enforcement receipt
from that layer, not a provider flag claiming that the restriction was honored. An explicitly
trusted-Local exception is a different, narrow tier. It requires an operator-issued
`WorkloadTrustReceipt` from the external control plane, bound to the canonical repository
attestation, expected base revision, task/spec digest, permitted capability profile, issuer,
expiry, and revocation generation. The receipt authorizes only that exact scope and records
`os_enforced=False`; it can never satisfy or inherit hostile-workload eligibility. Repository or
model-authored backend/risk fields are untrusted inputs: they may tighten the resolved tier but
can never create, widen, replay, or replace an operator trust grant. Missing, stale, mismatched,
or revoked authority resolves to unknown, never trusted. The serialized receipt/control-store
row and a command-line flag are audit/request evidence rather than executable authority. Every
new OS process, including resume, requires fresh outer authority. The outer launcher proves it is
outside all registered no-breakaway model Job Objects/cgroups and alone owns operator interaction.
A model-bearing pre-spec worker receives pipe-only bounded I/O, no TTY/console/input handles, and
only credential-separated contained analysis authority. After it emits a proposal, every worker,
driver, broker, container, descendant, and credential channel must be proven quiescent/revoked;
failure refuses approval. Raw launch intent is not approval of a model-produced acceptance spec.

Only after quiescence does the outer process strictly decode bounded UTF-8, reject duplicate keys,
ANSI escape, bidi, noncharacter, and non-NFC hazards, validate the schema, deterministically
reserialize canonical bytes, and independently compute the full digest. It opens a fresh exclusive
child-inaccessible operator surface (private non-inherited ConPTY/app channel on Windows,
`TIOCEXCL` PTY on POSIX, or a fail-closed equivalent), discards input predating this phase, generates a random nonce,
and displays outer-owned ASCII-safe line-numbered content with every C0/C1 character escaped.
Approval requires exactly `APPROVE SPEC <full-digest> NONCE <full-nonce>`. Concurrent child output,
console reopen/descendants, prequeued or synthesized input, stale responses, `--auto-approve`, EOF,
generic confirmation, hostile rendering, task state, a model decision, or a child-only digest fail.

Only then does the launcher spawn a different `main.py` execution child with no controlling
terminal and closed pipe/`DEVNULL` stdio. Fresh one-time `OperatorLaunchCapability` and
`OperatorSpecApprovalCapability` values travel over anonymous non-inheritable handles and bind the
new PID, repository attestation/base, raw intent/task, schema/length, recomputed digest, nonce, and
issuer generation. The child consumes both once before any model call and derives the narrower
process-local grant. Resume has no pre-spec worker: the outer launcher revalidates the persisted
canonical bytes, uses a fresh nonce/approval channel, then spawns a new terminal-less execution
child. Without fresh approval, Local is unavailable and only a proven contained tier may continue.

Spec elaboration cannot bootstrap this authority. Its grant binds raw operator intent, repository
attestation, base, and an immutable read-only source snapshot, with no canonical/clone write,
shell, Task/subagent, MCP, promotion, terminal, or execution-child surface. Its output is an
untrusted proposal. If containment or complete quiescence is unavailable, elaboration stops or
uses an operator-supplied spec; trusted Local is never the fallback.

For hostile/unknown work, credential possession and repository access are disjoint. The pinned
provider driver starts in an empty safe-boot projection with no clone mount, built-in file/shell
tools, project/user hooks, plugins, LSP, MCP discovery, or background agents. A bounded credential
lease reaches only that driver. Every repository read/search/patch/write/exec operation crosses a
closed broker into a separate credentialless hardened container; provider configuration tracked in
the repository is inert data. If a real Claude or Codex subscription-auth canary cannot prove this
separation, that provider is unavailable for hostile work rather than silently widened.

### 5.3 Supernova: experimental control plane

Supernova owns no production state. It:

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
    H["Human goal and hard constraints"] --> OA["OS-installed Polaris Anchor and protected generation"]
    OA --> BC["External manifest-verified Singularity Boot Capsule"]
    BC --> CB["Last-known-good external controller bundle"]
    CB --> RR["Recovery-only authority and immutable receipt"]
    RR --> CA["Post-recovery no-follow canonical attestation"]
    CA --> SS["Immutable standalone source snapshot"]
    SS --> A["Quiesced approval and authority envelope"]
    A --> RA["First-statement normal-run admission authority"]
    SS --> RB["Credentialless bounded read and static-analysis broker"]
    RA --> RB
    KC["External immutable product-knowledge generation"] --> RB
    RB --> I["Intent compiler and grounded elaborator"]
    I --> C{"Ambiguity and risk gate"}
    C -->|"safe and grounded"| G["Typed mission DAG"]
    C -->|"read-only evidence useful"| P["Trust-tiered no-write probe"]
    P --> C
    C -->|"material unresolved choice"| Q["Clarification or blocked state"]

    G --> K["Singularity controller"]
    K --> M["Evidence-scoped memory retrieval"]
    K --> R["Capability and provider router"]
    K --> V["Value-of-information planner"]
    K --> B["Provider-capacity and zero-cost leases"]

    R --> O["Ollama reflex or draft"]
    R --> CL["Claude driver"]
    R --> CX["Codex driver"]
    V --> T{"Selective tournament?"}
    T -->|"no"| W["Single writer in standalone clone"]
    T -->|"yes"| WC["Claude candidate clone"]
    T -->|"yes"| WX["Codex candidate clone"]
    O --> W
    CL --> W
    CX --> W
    WC --> W
    WX --> W

    W --> EI["Attempt intent and lease"]
    EI --> TR{"Resolved workload trust tier"}
    TR -->|"explicitly trusted"| TL["Trusted-Local clone runner"]
    TR -->|"hostile or unknown"| MD["Credentialed model driver capsule (no process tools)"]
    MD --> SB["Typed sandbox command broker"]
    SB --> DS["Credentialless hardened Docker tool sandbox"]
    TL --> AR["Immutable execution and enforcement receipts"]
    MD --> AR
    DS --> AR
    AR --> NS["Native no-follow full candidate snapshot"]
    NS --> NP["Pinned networkless parser: canonical manifest plus inert blobs"]
    NP --> OS["Memory-safe loose-object writer and deterministic GitIndex"]
    OS --> VI["Fresh universal credentialless verification container"]
    VI -->|"fail"| FC["Failure classifier"]
    FC -->|"repair"| W
    FC -->|"provider failure"| R
    FC -->|"unsafe or ambiguous"| Z["Blocked or quarantined"]
    VI -->|"pass"| XR["Semantic review or explicit policy-skip receipt"]
    XR -->|"material finding"| FC
    XR -->|"acceptable"| J{"Tournament candidate?"}
    J -->|"yes"| FJ["Facts-first judge over verified and reviewed receipts"]
    FJ --> SR["Durable selection receipt and branch-journal links"]
    SR --> RS["Pure global-slot and purpose-result resolver"]
    J -->|"no"| RS
    RR --> RS
    PA["Protected purpose outcome archive"] --> RS
    RS -->|"first or nonrepeatable"| TP["Service-issued transition-purpose receipt"]
    RS -->|"new or same retryable batch"| RI["Durable repeatable-invocation receipt"]
    RI --> TP
    RS -->|"occupied recoverable slot"| RC["Fenced settle, reconcile, or rollback"]
    RS -->|"ambiguous, live-owned, or pending"| Z
    TP --> GS["One repository-global all-generation transition slot"]
    GS --> BI["Persisted exact-purpose begin intent"]
    BI --> OF["Owner lease and monotone fencing generation"]
    OF --> MG["Fenced ref/index/worktree promotion"]
    MG -->|"CAS or materialization failed"| RC
    MG -->|"promoted"| VC["Non-executing canonical postconditions"]
    VC -->|"fail"| RC
    VC -->|"pass"| FR["Immutable finalization receipt"]
    FR --> TJ["Monotone operation journal and live-state proof"]
    RC --> TJ
    TJ --> TO["Closed operation-specific terminal observation"]
    TO --> TA["Atomic revalidation and terminal acknowledgement"]
    TA --> PA
    PA -->|"achieved"| PS["Persist promotion-pending receipt chain"]
    PA -->|"retryable exact old"| FC
    PA -->|"rollback or safe failed"| Z
    PS --> JA["Acknowledge attempt journal"]
    JA --> F["Persist terminal done"]

    F --> E["Outcome and evidence graph"]
    E --> CR["Supernova experiments and causal credit"]
    CR --> PM{"Promotion gate"}
    PM -->|"earned"| RP["Routing, memory, or policy update"]
    PM -->|"not earned"| SH["Remain shadow or reject"]

    E --> OB["GALAXY Orrery projection"]
    RP --> K
    SH --> K

    OC["Operator command inbox"] --> DL["Future command/effect wave: durable claim, apply, acknowledge"]
    DL --> K
    EG["Brokered external-effect gateway"] --> K
    K --> EG
~~~

The capability graph deliberately contains repair, routing, learning and recovery feedback loops; the
mutation-authority graph does not. Its only spine is `RS -> RI? -> TP -> GS -> BI -> OF -> (MG | RC)
-> TJ -> TO -> TA -> PA`: pure lookup, optional repeatable-invocation identity, exact purpose, one
all-generation slot, durable begin intent, current owner fence, one promotion-or-recovery action,
monotone journal, closed terminal observation, atomic acknowledgement, then immutable archive. `PA`
may inform a later pure lookup, but no archived or feedback edge carries a live mutation capability.
Every writer, model, judge, dashboard, memory learner and retry remains outside that spine.

The dashboard requested by the user is the `GALAXY Orrery` projection of this flow. It will highlight the current node, active leases, causal parents, uncertainty, provider route, verification state, recovery edges, and evidence behind every displayed score. It is deliberately implemented after the kernel emits trustworthy events.

### 6.1 Qualified Flare, Nebula, and federation overlay

The Mermaid graph above is the audited 71-node / 95-edge R3 base. The exhaustive
target and qualification contract is defined in
[GALAXY R3 Target and Qualification Topology](2026-07-14-galaxy-r3-qualified-capability-topology.md),
with the scheduler and solver ledgers defined in the Pulsar and Quark annexes:

| Layer | Added nodes | Added unique typed edges | Cumulative |
|---|---:|---:|---:|
| Flare and Magnetosphere admission | 16 | 31 | 87 / 126 |
| Nebula | 21 | 44 | **108 / 170** |
| Pulsar R1 | 19 | 68 | **127 / 238** |
| Quark Portfolio R2 | 4 | 12 | **131 / 250** |
| Disabled Voyager federation boundary | 3 | 6 | **134 / 256** |

Count reconciliation (a linter must reproduce these exactly):
nodes `71 + 16 + 21 + 19 + 4 = 131` core, `+ 3 = 134` federation-ready;
edges `95 + 31 + 44 + 68 + 12 = 250` core, `+ 6 = 256` federation-ready;
overlay-only `16 + 21 + 19 + 4 = 60` nodes and `31 + 44 + 68 + 12 = 155` edges.
The base `71 / 95` layer is not yet materialized row-by-row anywhere in this
package (only the `60 / 155` overlay is enumerated, across this file's annexes);
producing the base ledger is a prerequisite of the single validated manifest and
is tracked as an explicit open item, not an audited artifact.

The core quota excludes Voyager internals, ephemeral instances, retries, aliases,
schema fields, and Gaia/Orrery presentation. Every new overlay node
and edge has an architecture contract, independent lifecycle or transformation,
bounded failure behavior, authority class, measurable consumer effect, and
knockout test. The base is structurally audited but the full graph must not be
called manifest-qualified until its one machine-readable contract validates.
Nothing here is runtime-enabled, and the overlay adds no ingress to the
mutation-authority spine.

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
| `plan_readonly` | disposable clone | no canonical write | deny by default | no | no | no |
| `review_readonly` | immutable diff and receipts | no | allowlisted checks only | no | no | no |
| `writer_clone` | one leased clone | one leased clone | brokered sandbox only | no by default | no | no |
| `trusted_local` | explicitly classified scope | explicitly classified clone | allowlisted host | explicit | kernel only | broker only |
| `external_effect` | required evidence | broker-owned | broker-owned | explicit target | no | one typed effect |

An unavailable capability fails closed. Provider failover is allowed only to a driver that supports the same profile. Environment failover may never widen from isolated to canonical or from hostile/unknown to trusted Local. For hostile writers, the credential-bearing model driver has no general process tool; shell and test execution cross a typed broker into a separate credentialless hardened container.

### 7.3 `ProviderNeutralSpec`

The provider-neutral spec contains:

- role: plan, write, repair, review, or summarize;
- objective and acceptance criteria;
- context artifact references;
- capability profile;
- clone/transaction lease;
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

- `CapabilityEnforcementReceipt` binds provider/CLI/auth mode, exact launch-plan/image/base/SBOM,
  broker/environment/mount/network/security digests, host runtime/kernel facts, real canary
  evidence, expiry, and revocation generation. Production revalidates an exact match immediately
  before launch and mints a non-serializable process-local enforcement grant; serialized receipt
  JSON alone is never authority. Drift or stale evidence is typed unavailable.
- `ExecutionReceipt` records attempt/routing IDs, provider and versions, requested and
  evidence-backed actual model, auth/billing mode, capability-enforcement receipt,
  prompt/schema digests, role-tagged runtime resource leases, session hash, run revision,
  clone/base/native-snapshot/parser-manifest/blob-set digests, timings, usage/cost knowledge,
  observed tool events, and normalized execution failure.
- `StagingReceipt` records the native snapshot and contained-parser receipts, complete canonical
  path/mode/blob manifest, strong per-object digests, deterministic loose-object closure,
  proposed-index artifact digest, expected parent, proposed commit/tree/diff digests, policy
  digest, and immutable staged ref. Host Git never parses candidate patch/pack/index/object bytes;
  staging executes no candidate code and never uses canonical as a working directory.
- `RevisionVerificationReceipt` (compatibility alias `VerificationReceipt`) records the tree revision and artifact digests it evaluated,
  commands/oracles, evidence, verdict, verifier identity, universal credentialless verifier
  authority/container identity, and the candidate's separate execution-origin tier as evidence.
  Executable checks always run in a fresh no-link clone inside the pinned verifier; canonical checks are non-executing Git
  postconditions rather than a second chance to run candidate-authored code on the host.
- `ReviewReceipt` records the reviewer provider, clean-room context digest, findings,
  contamination controls, and advisory/hard-gate decision. Every promotable candidate has
  exactly one durable review node before selection or promotion; a legitimate policy skip is
  represented by an explicit versioned policy-skip receipt, never a null link.
- `SelectionReceipt` binds a tournament's complete candidate/eligible sets, judge evidence and
  policy digests, selected winner, and every loser disposition before any winner promotion.
- `PromotionReceipt` records the promotion transaction/fence, expected and observed target
  SHA, verified proposed SHA, ref-CAS/materialization result, canonical head/index/tree,
  recovery intent/evidence, and error. `MergeReceipt` remains only a compatibility name.
- `ReconciliationReceipt` and `CleanupReceipt` append later observations/actions/warnings without
  rewriting the content-addressed PromotionReceipt.
- `FinalizationReceipt` links the accepted execution, staging, verification, review, and promotion
  receipts to the terminal state.

`AttemptView` is a recomputable materialized projection over this chain for dashboards,
routing, and analysis. It is not another writer or authoritative record.

Receipts are stored through a host-owned content-addressed, create-only `ReceiptStore` outside
every repository/provider mount and re-hashed on read. The deepest promotion boundary accepts
only a typed `PromotionAuthorization` and re-reads the exact staging, verification, review, and
required tournament-selection chain plus journal linkage before taking any canonical lock. No
caller Boolean, bare verification result, null review, or stale/cross-transaction receipt can land.
Evidence is necessary but never live authority: the same boundary also requires a non-serializable
`LandingAuthority` bound to the active run, transaction/task, exact proposed SHA/tree/receipts,
watchdog, deadline, and controller generation. It revalidates that authority before mutation and
under the held fences immediately before the one loose-ref CAS. Cancellation, expiry, revocation,
watchdog loss, or generation change before CAS leaves canonical byte-identical. A separate narrow
recovery authority may finish consistency only after journal plus ref prove that exact CAS already
occurred; it cannot select or promote a revision.

### 7.6 Run-revision authority

`RunAdmissionAuthority` begins at immutable run revision `R0`, canonical base `B0`, and one exact
source-snapshot receipt. It is never widened merely because the same run promoted a new base. A
promotion may advance the run only after its `PromotionReceipt` and the complete
`persistAttemptTransaction()` chain prove acknowledgement, terminal persistence, and no mandatory
reconciliation or cleanup. The external kernel then closes old-revision admission, quiesces every
driver, broker, container, parser, verifier, reviewer, state worker, clone and lease, re-attests `B1`
through native no-follow handles, creates and re-reads a new immutable snapshot, and persists a
content-addressed `RunRevisionAdvanceReceipt` linking all of that evidence. Only then may it derive
non-serializable `RunRevisionAuthority` for `R1/B1`.

All old-base leases, artifacts and pending candidates become stale and cannot be rebased or chained;
retryable work is rescheduled as fresh transactions after the advance receipt. A crash before
terminal persistence is recovery-only. Drift not proven by this run's promotion chain requires a new
operator-approved run. Because trusted-Local grants bind an exact base, an `R0/B0` grant is invalid at
`R1/B1`; `R1/B1` needs a fresh exact-base operator grant or the work uses the hostile contained tier
or is unavailable. No descendant wildcard or caller assertion widens it.

### 7.7 `PromotionReceipt`

Contains the staged source SHA/tree, expected target SHA, observed target SHA, promotion
transaction, Git index-fence ownership, atomic ref-CAS result, resulting canonical
head/index/worktree postconditions, recovery intent/evidence, and error. Promotion is compare-and-swap:
the canonical ref must still equal the expected target SHA while the custom merge lock and
Git-standard index writer fence are held. Drift requires new object staging plus fresh
universal credentialless authority-bound re-verification or quarantine; it never silently lands stale evidence. No subtask can enter
`done` without a durable successful promotion receipt.

### 7.8 Source-update scope receipt

Complete path sets never travel on a command line. The request-only external client uploads a
transaction-bound canonical path manifest using four mutually exclusive record roles:
`allowed-only`, `test-only`, `required-change`, and `required-test`. The external service reconstructs
and enforces `Required ⊆ Allowed` and `Tests ⊆ Allowed`, rejects duplicates, reordering, replay,
traversal, invalid set relationships and unregistered paths, and seals a create-only SHA-256 receipt.
Because Windows PowerShell 5.1 native argument passing strips embedded JSON quotes, canonical JSON is
never sent as a raw argv value. The helper strict-UTF-8 encodes it and transports canonical unpadded
base64url only. The client and service reject padding, noncanonical alphabet/forms, malformed UTF-8,
or decode ambiguity; the service parses and canonically reserializes the decoded JSON and requires
byte equality before accepting it. Uploads are bounded to 24 records per request, below 4 KiB for the
decoded records payload and at most 8 KiB for the exact encoded protected-pipe envelope; both client
and service independently measure the relevant bytes. A real pinned-PowerShell native-process canary
round-trips quotes, backslashes and non-ASCII paths across the exact client boundary. Every later
normalization, proposal, CAS and activation step carries only the opaque receipt ID and digest, which
the service re-reads and re-hashes.

## 8. Transaction and recovery semantics

### 8.1 Honest transaction boundary

Claude and Codex are opaque agent processes. Revision 3 does **not** claim exactly-once semantics for their internal tool calls.

The first honest transaction boundary is an isolated attempt:

~~~text
prepared
-> leased
-> running
-> captured
-> object_staged
-> verified_in_tier
-> promotion_prepared
-> index_fenced
-> ref_moved
-> materialized
-> promoted
-> state_pending
-> journal_acknowledged
-> finalized
~~~

Terminal alternatives:

~~~text
blocked | failed | cancelled | quarantined | superseded
~~~

A crash can leave a private clone, immutable native snapshot, parser/blob manifest, generated object/index artifacts, staged ref, and receipt recoverable without marking the task complete. Session resume is transaction-scoped only: it compares transaction ID, run revision, clone/base revision, capability digest, provider/role, plan signature, and attempt state. A retry or new transaction creates a fresh sanitized session and clone, carrying prior diagnostics as immutable evidence rather than projecting a host profile or stale filesystem path.

Every top-level cutover, source-update and controller-update is serialized through one
repository-global transition slot spanning **all** source/controller generations and all three
operation names. The service-owned slot is a monotone state machine:
`reserved -> started_old -> advanced_recovery -> terminal_unacknowledged -> acknowledged`. Only
acknowledged terminal state releases the live slot; its protected tombstone remains discoverable, and
source-generation advance never changes the mutex key. A pure repository lookup always happens before
settlement and returns no slot or the occupied slot's exact operation, purpose, phase, owner lease,
owner fencing generation and terminal evidence. A live or liveness-unknown owner blocks. Only an exact
same-owner recovery capability or a durable dead/expired-owner-and-quiescence receipt can authorize
takeover. The service revalidates that proof under the slot lock, advances the owner fencing generation
and persists a replacement recovery fence before mutation. Every subsequent manifest, normalization,
proposal, verification, CAS, finish, reconciliation, ingress release, observation and acknowledgement
mutation rejects an older owner generation, so an expired but still-running client cannot continue.

Transition purpose is never a caller-chosen label. The external service create-or-returns and persists
before response a content-addressed `TransitionPurposeReceipt`, which a fresh process can independently
resolve read-only. It binds the protected reviewed-wave epoch, closed plan-DAG node, operation contract,
requested fences, exact expected old source/controller state, and an external native no-follow batch
snapshot plus canonicalization-policy digest. A full restart after frozen trust-leaf correction uses an
explicit reviewed restart edge and a new wave epoch. Repeatable review corrections bind their exact
pre-normalization dirty batch; the later `NormalizationReceipt` chains that immutable snapshot and
policy to canonical change records. Purpose issuance/resolution, intent issuance/resolution, begin,
every child mutation, settlement, observation and acknowledgement exact-match the purpose receipt and
current owner fencing generation. Ambiguous purpose records or archives fail closed.

Recovery is ordered ahead of every caller-side dirty-tree, untracked-report or nonempty-batch gate.
Those gates are advisory validation of a genuinely new invocation, never prerequisites for discovering
or settling an already-started transition. A repeatable node first uses a pure, ambiguity-rejecting
result-state resolver to distinguish an exact achieved-and-clean result, an invocation persisted before
purpose issuance, an exact clear-never-started or still-retryable purpose, a new batch after one achieved
predecessor, and a first invocation. Before purpose issuance the
service persists a content-addressed `RepeatableInvocationReceipt` that binds the predecessor outcome,
exact old state, native no-follow pre-normalization batch and canonicalization policy. The same input
resolves the same invocation and purpose after response loss; a later dirty batch receives a different
invocation and purpose. Nonrepeatable nodes use an exact current-result-to-purpose archive resolver that
distinguishes never-issued from clear-never-started, achieved, retryable, rollback, failed, divergent
and ambiguous states.
Caller classifications grant no authority: invocation and purpose issuance atomically recapture and
revalidate their inputs under service ownership before mutation. Begin then rechecks the purpose-bound
old state and pre-normalization input under the repository slot lock before `started_old`; later drift
cannot be swept into the proposal or overwritten during materialization.

A fresh shell may settle a prior slot only after the lookup and fenced-owner protocol above, using its
existing monotone journal and already-bound authorization. It may abort an untouched old-state begin or
finish/reconcile/roll back an advanced transition, but cannot select a candidate, adopt new state or
create a transition. Exact-old-state and live-fence checks govern immediate begin resume only; they do
not rediscover advanced transactions. Terminal observation is closed by recorded operation:

| Operation | achieved | retryable old | verified rollback | safe failed |
|---|---|---|---|---|
| cutover | exact proposed source/index/tree, verified inactive handoff, no legacy process/listener, production/Discord disabled, developer ingress open | exact old source/config and legacy generation, no residue, old ingress open | monotone source rollback, no legacy restart, all ingress closed | exact named safe generation and failure receipt, all ingress closed |
| source | exact proposed source/index/tree and receipt, developer ingress open, production inactive, Discord disabled | exact old source/index/tree, developer ingress open, production inactive, Discord disabled | exact prior source by monotone rollback, developer ingress closed, production inactive, Discord disabled | exact named generation and failure receipt, developer ingress closed, production inactive, Discord disabled |
| controller | exact reviewed controller/anchor generation and activation receipt, CLI/run ingress open, Discord disabled | exact prior controller and proven prior CLI/run ingress, Discord disabled | monotone verified LKG, CLI/run ingress closed, Discord disabled | exact named safe generation and failure receipt, CLI/run ingress closed, Discord disabled |

Anything outside this map is `recovery_pending` and cannot be acknowledged. Acknowledge atomically
revalidates the observation against the latest journal, live generation, ingress, operation, purpose,
wave epoch and owner generation under the slot lock. Cross-operation/purpose/epoch or stale-token replay
fails. Successful acknowledgement appends the exact classified outcome to the protected purpose ledger;
pure lookup then returns `archived_achieved`, `archived_retryable`, `archived_rollback`, or
`archived_failed`, while an unattempted purpose alone returns `clear_never_started`. Only afterward does
a separate resolver classify the occupied-to-desired relationship as same purpose, one explicit allowed
predecessor edge, or unrelated/new epoch. A predecessor's success is never the desired purpose's success.
Response loss and parent death are recovered from the slot, terminal tombstone and purpose ledger, never
from a volatile client ID or mutating response. Unresolved or ambiguous state blocks all new mutation.

Every transaction-level abort, finish, rollback, reconciliation and ingress-release call that can
change canonical/controller/ingress disposition is followed by a read-only transaction-disposition
lookup that re-reads the latest monotone journal sequence, persisted
receipts, protected live fence bits and exact ref/index/tree/controller generation, rejecting stale
receipts or disagreement. Its result names exact old/new generation truth and independently names
each ingress as open, held closed or recovery-pending. A failed lookup is `disposition_unknown`: it
must never be rendered as either open or fenced, and recovery uses the printed transaction ID.
Requested fence flags and lost client responses are not evidence of actual fence state.
Every source-update disposition additionally fails closed unless the protected live state proves the
production run inactive and the Discord listener disabled; a developer-ingress classification alone
can never authorize continuation or finish.
Terminal disposition does not retire discovery: it creates the terminal tombstone, and only the
observation-receipt acknowledgement protocol above can release the repository-global transition slot.

Canonical promotion is serialized by a custom merge lock plus Git-standard index writer
fence and expected-old-OID ref compare-and-swap. Verification performed against one staged
SHA cannot authorize a different restaged revision or promotion into a newer canonical tree.
Before the CAS, the complete tree must also be injective on the real filesystem and safe under
no-follow handles: case/Unicode/trailing-dot-or-space/device/ADS/8.3/path-length aliases, sparse or
special index modes, reparse/junction races, and unsupported index extensions fail closed. On
Windows, canonical files are written by a kernel-owned handle-relative materializer from one
immutable operation manifest. A memory-safe codec constructs the deterministic complete index;
the kernel copies and re-verifies it into a journal-owned same-directory sibling before atomic
installation. Git neither computes that index nor performs `read-tree -u` or checkout in canonical.

The live index contract accepts ordinary DIRC v2 entries and only explicitly supported optional
extensions. A `TREE` extension is bounded and structurally validated but treated as a derived,
non-authoritative accelerator and omitted or recomputed; malformed data, unknown required
extensions, split-index and sparse-index state fail closed. A stable one-to-one live 8.3 alias may be
recorded as metadata for the same file, never as a second logical path; collisions, alias drift,
support ambiguity and races reject the transaction. Existing linked-worktree registry entries are
captured as bounded opaque metadata without following their external `gitdir`, and user worktrees
are preserved. Other observed Git administrative files are accepted only by an explicit inert-file
policy and cannot become configuration, authority or code.

### 8.2 Public-source acquisition

Public HTTPS intake is a two-container protocol. The host and engine are default-deny for egress.
The credentialless fetcher receives one controller-validated public numeric destination tuple and
has no container DNS; each redirect tears down the connection, normalizes and revalidates the new
URL, resolves and fences a new tuple, and registers it before reconnecting. Numeric rewriting is
connect-only: the normalized URL hostname remains TLS SNI and is checked against an OS-trusted,
time-valid server-auth certificate chain, while HTTP/1.1 `Host` or HTTP/2 `:authority` is fixed to the
same normalized URL authority and effective port. Userinfo, conflicting host fields, private or
ambiguous addresses, certificate bypass, cross-authority reuse and plaintext downgrade fail closed.
The receipt binds URL/HTTP authority, numeric tuple, TLS policy, chain/leaf-SPKI evidence and every
redirect relationship.

Raw bounded bytes then cross a digest/size manifest into a different network-disabled parser. It
emits only a bounded canonical relative-path/mode/content-digest manifest and inert content-addressed
blobs under hard wall/idle/wire/disk/object/inflation/tree/path/file quotas. Host Git never parses
candidate pack/index/object syntax; the native no-follow materializer alone may create a newly
attested external target. All resources and cleanup are journaled, so malformed input, rebinding,
bombs, quota breach or cancellation kill both resource trees and end with a durable cleanup receipt.

### 8.3 Brokered external effects

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

The first kernel slice does not pretend this lifecycle already exists. It installs a deepest-boundary
deny guard and returns an in-memory typed deferral for every run-originated Discord/webhook/Cast
response or attachment, Obsidian/vault mutation, public tunnel download/process, Jerry/remote/SSH
action, browser/native artifact action, PR/publication, and automatic maintenance/model mutation.
The guard returns before constructing or reading any effect-facing path, payload, DNS/socket,
process, browser/UI object, or external action. Only afterward may it append the internal deferral
receipt through the already-authorized, pre-attested external `ControllerStateStore`; that one
best-effort append is the sole permitted path write, and its failure degrades to the in-memory result
rather than reaching the effect. The external Discord gateway stays ingress-disabled until the command/effect wave; the local dashboard
and event projection expose only authority-bound loopback GET/SSE; POST/control handlers refuse
before ControlBus/TaskState mutation and their token/logs live in external state. Remote execution
is unavailable even when caller-labeled read-only. This is deliberate capability closure, not a
claim that effects were implemented.

### 8.4 Durable operator commands (next wave)

This protocol is the next command/effect wave, not an implemented claim of the transactional-kernel
slice. Until it lands, command mutation remains disabled or typed-deferred.

`drainOps` is replaced by a lifecycle in the existing control store:

~~~text
received -> claimed -> decided -> applied/rejected -> acknowledged
~~~

Claims have expirations and fencing tokens. Stable command IDs make replay safe. A command is never deleted before its applied/rejected result is durably recorded. `control.db` remains the operator-intent authority. Task JSON remains authority for legacy command-application fields until their separately reviewed field-level cutover; scheduling fields follow the externally anchored Pulsar scheduler-cutover phase instead.

Before any Pulsar scheduler-field cutover, the stable command ID is persisted inside the same
crash-safe TaskState save as the command mutation. After scheduler-field cutover, a legacy command
writer must use its separate authority sidecar or the cutover receipt's sealed per-writer field
matrix. A protected field-mask CAS binds the expected TaskState generation, that writer's exact
allowed paths, and an unchanged KSJ-projection digest; unknown, aliased, nested-prefix-overlapping,
or another owner's path is rejected. A whole-document legacy save and an "all non-KSJ fields"
complement are forbidden. Presentation state lives in its own non-authoritative sidecar and cannot
write TaskState. Reapplication checks the stable ID and is a no-op when already present. After restart, a reconciler compares the legacy
applied-ID set with `control.db` and repairs missing acknowledgements. A later command/effect cutover
must replace this with its own explicit authority matrix and phase receipt; it cannot infer ownership
from the scheduler cutover. This keeps the unavoidable dual write idempotent and convergent rather
than pretending it is one transaction.

## 9. Claude–Codex peer fabric

### 9.1 Zero-cost preflight

The current machine was verified to have:

- Claude Code 2.1.197 authenticated through `claude.ai` Max;
- Codex CLI 0.144.1 authenticated through ChatGPT;
- no Anthropic/OpenAI API keys or Bedrock/Vertex/Foundry selectors in the process environment.

These exact version strings are freeze-time observations, not a hard-coded
equality gate. The authoritative check is the machine-readable preflight and the
per-provider CLI-contract adapter, which validate auth/billing mode and command
surface; a later CLI version that passes the same preflight is eligible, and an
earlier or drifted version that fails it is not. Do not implement literal
version-string equality as the eligibility predicate.

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
- high-risk or repeatedly failing work may run independent Claude and Codex proposals in separate standalone clones.

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
| `SNAPSHOT_OR_MANIFEST_CONFLICT` | Refuse restaging, retain snapshot/parser/blob/ref evidence, quarantine result |
| `CANCELLED` | Kill process tree, preserve non-final receipt, do not consume success credit |

## 10. Adaptive orchestration without confounding

### 10.1 Operational modes

1. **Static single writer:** cheapest reliable eligible driver.
2. **Crossover review:** one writer, other provider reviews immutable diff.
3. **Parallel tournament:** multiple isolated candidates, deterministic verification and review receipts, then a facts gate and evidence-based judge.
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

The rich GALAXY graph contains:

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
| Innovator | Hypothesis emitter feeding Supernova; ideas need experiment, owner, lifecycle, and outcome |
| Discovery | Evidence and opportunity ingestion; never authoritative without attestation |
| Council/Society | Selective value-of-information protocol, local Claude/Codex seats, not an always-on external-provider parliament |
| Human Nature/Psyche | Shadow assessments and bounded priors until each coupling wins a real control-arm experiment |
| Clarification Gate | Moves before execution; uses deterministic/read-only probes, blocks high-risk unknowns |
| Adversary | Cross-provider semantic critique with measured catch precision |
| Verifier | Deterministic receipt authority; semantic models may downgrade or request repair, never fabricate a pass |
| Solution space/QD | Truthful measured branch search; synthetic metrics removed or marked unknown |
| Self-evolution/SIE | Proposal and experiment generation; promotion remains external to the candidate |
| Browser/native | Optional capability adapters with semantic postcondition receipts |
| Dashboard | GALAXY Orrery, a read-only projection of canonical events |

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

### 13.1 Distributed-SaaS scaling patterns, mapped honestly

Classic web-backend scaling advice (stateless servers, load balancers,
horizontal scale-out, API gateways, object-storage buckets, message brokers,
CDNs, Redis caches, per-user rate limits) targets a multi-tenant distributed
cloud service answering untrusted public traffic. GALAXY is the opposite class of
system: one trusted operator, one local host, and a hard zero-cost,
no-recurring-SaaS constraint. Each pattern therefore either already exists here
in hardened form or is excluded on purpose; importing an excluded one would be
exactly the complexity theatre this section forbids and would forfeit a core
invariant.

| Distributed-SaaS pattern | GALAXY posture | Where |
|---|---|---|
| Stateless compute, state in a decoupled store | Implemented, hardened: all mutable controller state is external to the target; the current-root pointer advances only by generation-bound CAS | §5.1, §7.5 |
| "Data coupled to the machine = no scale/resilience" | Implemented: canonical is an attested object source, never a host working directory | §1, §5.1 |
| Message broker / pub-sub, at-least-once, dead-letter queue | Implemented as a transactional outbox: DIO and the durable command lifecycle use idempotency keys, create-or-return, fencing tokens, and `launch_unknown`/quarantine terminals — stronger than fire-and-forget queueing | §8.4, Pulsar DIO |
| Cache-aside (cache metadata, not blobs) | Implemented: validation cache, content-addressed caches, and Accretion treating the context window as a disposable cache over immutable state | §11.4, Accretion |
| Backpressure / rate limiting | Implemented, different driver: capacity leases, provider circuits, and the Pulsar backpressure controller throttle scarce subscription capacity rather than defend against abusive tenants | §9, Pulsar BSC |
| Health checks / sticky sessions / routing | Implemented as capability routing: driver `health()`, provider circuits, and session identity keyed by run+subtask+provider+role play the load balancer's role over providers, not a server fleet | §5.2, §7.4, §9.3 |
| Single authenticated entry / private network (VPC) | Analog: the Singularity Kernel is the one authority entry and the effect gateway the one egress; ingress stays loopback-only or disabled. It gates capability, not multi-tenant HTTP auth | §5.1, §8.3 |
| Horizontal scale-out across a server fleet + load balancer | N/A by design: one host; parallelism is within-host (tournaments, worktree clones), a concurrency axis, not machine scale-out. A fleet would breach the zero-cost/local-first constraint | §10 |
| Object-storage buckets (S3/GCS, presigned upload URLs) | N/A as a cloud dependency; local analog only: large artifacts are local content-addressed blobs outside SQLite — the same "don't stream big blobs through the app or the relational DB" lesson with no recurring bill | §8.2, ReceiptStore |
| CDN / edge geo-distribution, multi-region, autoscaling, serverless | N/A: one operator, one machine, no geo-distributed readers; excluded by the zero-cost, local-first boundary | — |

This matches the source material's own warning against premature optimization:
the patterns that fit GALAXY's problem are already present, and the rest are
excluded deliberately. Adopting them would mean becoming a different product — a
hosted, multi-tenant service — which forfeits the zero-cost and local-first
invariants and is out of scope for R3.

## 14. Brownfield transfers

Canonical external-source membership is owned by the
[Brownfield and Frontier Evidence Registry R1](2026-07-14-galaxy-r3-brownfield-frontier-registry.md):
exactly `BR01..BR50` repositories and `FR01..FR35` frontier papers. Foundational
or historical citations elsewhere in this design remain useful but do not enter
those counts. A new external repository or frontier paper cannot be introduced by
an annex projection alone.

Package-wide projections are intentionally small:

| Projection | Canonical IDs | Design use |
|---|---|---|
| harness and provider contracts | BR11, BR13-BR18 | delegation lifecycle, traces, typed state/messages, MCP negotiation |
| isolation | BR19-BR23 | disposable sandbox lifecycle, syscall/microVM boundaries, policy fixtures |
| scheduler and durable execution | BR12, BR24-BR35; FR01-FR08 | deterministic replay, fair/critical ordering, work stealing, backpressure, timers, placement |
| memory and context | BR01, BR07-BR09, BR36-BR37; FR09-FR16, FR30 | typed context, temporal/causal retrieval, workflow memory, memory leakage |
| evaluation, provenance, and security | BR38-BR43; FR17-FR29 | executable tasks, traces, signatures, roots, attestations, telemetry, security oracles |
| algorithm and verification quarries | BR02, BR04-BR06, BR10, BR33-BR34, BR44-BR50 | exact oracles, contest-grade implementations, generators, validators, and checkers |

Revision 3 reuses patterns, not mythology. The legacy summary below is
non-counting; where it names an external source, the registry record and pin
govern:

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
| Attention Is All You Need v7 | research paper | Paper evidence: Q/K/V attention, multi-head projections, decoder future masking, explicit positions, residual connections, and non-monotonic fixed-compute head ablation. GALAXY separately hypothesizes sparse typed routing, security masks, and an independent hard-constraint channel; not a claim that the orchestration graph is a neural network. |
| Anthropic Global Workspace / J-space, 2026-07-06 | research paper | Paper evidence: a small, causally involved, workspace-like representational component with limited capacity and broadcast-like connectivity. GALAXY separately hypothesizes typed specialists/admission, targeted external broadcast, relational frames, and recurrent immutable epochs; not internal access to Claude/Codex or evidence of consciousness. |
| Anthropic jacobian-lens commit 581d398 | Apache-2.0 reference, unmaintained | Optional digest-pinned experiments on license-compatible local open-weight Hugging Face models only; never a production monitor, verifier, or authority gate. Model weights and corpora retain separate licenses. |
| TigerBeetle VOPR / "Tiger Style" | Apache-2.0 reference | Deterministic simulation testing: injectable clock/disk/RNG, seed+commit reproducibility, time compression, systematic fault injection, assertions retained in production. Transferred as the §15.1 harness. GALAXY is single-host, so the simulated fault domain is host/storage/provider/CLI, **not** a consensus cluster; VSR/replication content is explicitly out of scope. |
| Temporal / Cadence / DBOS durable execution; Restate semantics only | MIT / Apache-2.0 / MIT; Restate is BSL-1.1 | BR24-BR26 provide permissive source quarries for journaled control-flow replay, workflow-safe clock/RNG, retries, and idempotent activity boundaries. Restate corroborates public semantics only: its current BSL source is quarantined and cannot be copied. No engine is a dependency, and external side effects remain at-least-once plus idempotency rather than being relabeled exactly-once. |
| Letta / MemGPT (`letta-ai/letta`) | Apache-2.0 reference | Prior art for Accretion: OS-style virtual context management, two-tier main/external context, paging and page-fault vocabulary. **Deliberately not transferred:** MemGPT's defining mechanism is *self-editing memory* — the model itself decides via tool calls what to page in and out, and compaction is recursive summarization. Accretion inverts this: compilation is mechanical and the model holds no memory authority, and eviction is publish-before-evict against an immutable record rather than summary-of-summary. The divergence is an authority requirement (AC-R01), not a preference. |
| TUF, in-toto, SLSA | open specifications | Polaris Anchor root lifecycle: threshold (M-of-N) signing, role separation, key rotation, self-updating root metadata, and — most relevant to the fail-closed posture — *explicit and implicit revocation*, so a formerly valid root cannot be replayed as current. in-toto's attestation predicate shape informs receipt structure. Specifications only; no registry, transparency log, or hosted signing service is adopted. |
| Varghese & Lauck timing wheels; Kafka request purgatory | paper / BR30 Apache-2.0 reference | O(1) start/stop/per-tick timer facility; the `ORBIT` candidate for Pulsar's wakeup path (Quark catalog §14). |

No proprietary Claude Code source is copied. Public CLI contracts and ideas are
reimplemented. Hermes, Guild, and AGX in the legacy summary describe already
harvested local/historical seams; they are not floating additions to the canonical
50-repository registry. Any renewed upstream source transfer requires a BR record.

Selected recent evidence (the complete 35-paper set, claim boundaries,
experiments, and falsifiers are `FR01..FR35` in the registry):

- [RigorBench](https://arxiv.org/abs/2606.22678)
- [TraceLab paper](https://arxiv.org/abs/2606.30560) and [repository](https://github.com/uw-syfi/TraceLab)
- [SecureVibeBench](https://aclanthology.org/2026.acl-long.1107/)
- [MemoryAgentBench](https://openreview.net/forum?id=DT7JyQC3MR)
- [MemSyco-Bench](https://arxiv.org/abs/2607.01071)
- [OpenAI Codex plugin for Claude Code](https://github.com/openai/codex-plugin-cc)
- [Code as Agent Harness survey repository](https://github.com/YennNing/Awesome-Code-as-Agent-Harness-Papers)

Systems and algorithms evidence adopted in R3:

- [TigerBeetle VOPR internals](https://github.com/tigerbeetle/tigerbeetle/blob/main/docs/internals/vopr.md) and [safety model](https://docs.tigerbeetle.com/concepts/safety/) — deterministic simulation testing, seed+commit replay, time compression
- [Jepsen analysis of TigerBeetle 0.16.11](https://jepsen.io/analyses/tigerbeetle-0.16.11) — independent audit of a DST-built system
- [Demystifying Determinism in Durable Execution](https://jack-vanlightly.com/blog/2025/11/24/demystifying-determinism-in-durable-execution) — where determinism is and is not required; control flow vs. side effects
- [Varghese & Lauck, Hashed and Hierarchical Timing Wheels (SOSP '87)](https://www.cs.columbia.edu/~nahum/w6998/papers/sosp87-timing-wheels.pdf) — O(1) timer facility
- [MemGPT: Towards LLMs as Operating Systems](https://arxiv.org/abs/2310.08560) and [Letta](https://github.com/letta-ai/letta) — virtual context management; self-editing memory rejected per AC-R01
- [The Update Framework](https://theupdateframework.io/) and [in-toto attestations](https://in-toto.io/) — root rotation, threshold signing, revocation

Recent community evidence is used only to generate hypotheses. Low-ranked or comment-poor items from the last-30-days pass are not treated as proof.

## 15. Experiment program

| Order | Experiment | Key ablations | Promotion/falsification |
|---|---|---|---|
| E0 | Reproducible manifest and immutable receipt chain | remove provenance, seed, or policy version | deterministic replay of the same raw artifacts must reproduce classification; repeated live model runs must stay within preregistered distributional bounds; overhead under 1% |
| E1 | Attempt/promotion crash matrix | remove promotion receipt, canonical postcondition, or index/ref fencing | 1,000 seeded attempt/promotion transitions; zero false done, lost promotion truth, or duplicate canonical promotion |
| E2 | Capability escape matrix | each driver/profile/backend failure | zero forbidden writes, canonical-tree launches, network escapes, or privilege widening |
| E3 | Claude/Codex CLI contract and zero-cost preflight | auth mismatch, hidden fallback, malformed schema | all launches prove subscription/local mode; metered mode hard-blocks |
| E4 | Cross-over quality benchmark | Claude-only, Codex-only, crossover, routed | routed lower bound non-inferior to best static; material verified gain or latency/recovery gain |
| E5 | Truthful branch scorer | single branch, cheapest verified, diversity off | must beat cheapest verified baseline without safety/cost regression |
| E6 | Anytime search | fixed-N, adaptive allocation, restarts/diversity off | higher verified wins per capacity minute; behavioral, not label-only, diversity |
| E7 | Forecast and causal credit | base rate, unpaired, no drift, no intervention | beat base-rate calibration; recover injected causes; stable under cohort reweighting |
| E8 | Evidence-preserving memory | vector-only, recency-only, contradiction off | improved paired task success; zero poisoned trusted memories; rare failures retained |
| E9 | Anytime-valid promotion and observatory | unpaired test, visible fixtures, provenance hidden | A/A false promotion within target; hidden canary inaccessible; every panel recomputable |
| E10 | Qualified graph admission | incumbent, equal-budget incumbent, sham topology, real topology, every node and edge knockout | zero authority regression; non-inferior verified quality; material gain over both incumbent controls; externally issued expiring workload-scoped GraphWarrant with fresh revocation resolution |
| E11 | Flare and Nebula mechanism trial | off/on factorial, 8/16/32 slots, 1/4/8 specialists, duplicated/shuffled charters, full context, no bypass, flat claim bags | higher paired verified wins per occupied provider-minute or equal quality with a material resource reduction |
| E12 | Workspace integrity and causality | remove each mask, stale/injected/correlated evidence, pivotal-frame swaps, negative controls | unique seeded-fault catch signatures, causal mediation evidence, zero simple-task or authority regression |
| E13 | Disabled Voyager boundary | malformed, replayed, stale, oversized, forbidden-payload, unavailable, and terminal-feedback canaries | observational equivalence to absence for repository/canonical/provider/data/controller/evidence effects, with at most one bounded audit receipt; no replay while disabled and no raw data, training, RSI, host mutation, paid egress, direct import, or authority path |

Security and scope suites are hard constraints, not terms in a scalar objective.

### 15.1 Deterministic simulation testing harness

E1, E2, and the Pulsar/command-lifecycle crash matrices are seeded fault
campaigns. Run as ordinary tests they explore a negligible fraction of the
interleaving space and, worse, a failure found once may never reproduce. R3
therefore specifies a deterministic simulation testing (DST) harness as the
substrate those experiments run on. This is a **verification method, not a new
authority**: it introduces no node, no edge, and no runtime capability, and it is
excluded from the topology quota.

The design transfer from TigerBeetle's VOPR is the discipline, not the domain.
GALAXY has no consensus cluster to simulate; its fault domain is the single host.

Requirements:

1. **All non-determinism is injectable.** Wall clock, monotonic clock, RNG seeds,
   filesystem, subprocess/CLI results, provider latency and failure, and SQLite
   I/O are reached only through interfaces the harness can substitute. Any
   component that reads ambient time or randomness directly is untestable here
   and must be refactored before its wave lands.
2. **Seed + revision reproduces exactly.** A failure is reported as a
   `(seed, source_revision_digest, harness_digest)` triple that replays the exact
   schedule. A failing seed that does not reproduce is itself a defect: it means
   an uninjected non-determinism source survives.
3. **Simulated time compresses.** Lease expiry, backoff, heartbeat loss,
   `max_late_wakeup_ms`, and generation expiry are driven by virtual time, so
   long-horizon schedules are exercised in seconds without wall-clock waits.
4. **Faults are injected systematically, not incidentally**: process kill at every
   transaction boundary, SQLite write failure and partial write, CLI non-zero
   exit, hang, and malformed output, provider circuit trip, disk-full, clock jump
   (forward and backward), and torn snapshot.
5. **Properties are asserted, not eyeballed.** Every campaign checks the
   invariants that already exist in this specification: no completion before
   collection, no lost or duplicate canonical promotion, no privilege widening,
   no effect without an authorizing command, monotonic phase order, and lease
   non-overlap. The harness is a falsifier for the §3.2 blocker list.
6. **The harness is not the product.** A DST pass is necessary, not sufficient:
   it cannot observe real CLI contracts, real provider behaviour, or real host
   semantics. It never substitutes for E3's zero-cost preflight or for live
   qualification, and a green simulation authorizes nothing on its own.
7. **Safety mode and liveness mode are separate campaigns.** Uniformly injecting
   faults proves safety properties — nothing bad happens — but a system that
   never dispatches also never violates one. Liveness mode therefore stops fault
   injection at a declared point, restores a healthy host, and asserts that the
   scheduler *makes progress*: every admitted contract eventually reaches a
   terminal or an explicit blocked state with a reason, no eligible cohort spins
   in recompute indefinitely, and no work is starved past its capped-aging
   bound. This directly targets Pulsar's recompute paths (§12.3 of the Pulsar
   annex), where every failure resolves to "recompute; no dispatch" and safety is
   therefore trivially satisfiable by never running anything.

Zero-cost posture: the harness runs local, deterministic, and offline; it calls
no model and no paid service. Simulated provider responses are fixtures, and a
DST campaign must never open a provider session.

Standing exit criterion: before any wave lands, its invariants hold across a
preregistered seed budget, and every discovered seed is retained as a permanent
regression fixture with its triple recorded in the receipt chain.

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

- Finalize/collect/object-stage before subtask completion.
- Require exact revision- and authority-bound universal credentialless verification plus a successful fenced promotion receipt.
- Make model launch, isolated execution, and executable verification fail closed.
- Keep command mutation disabled/deferred in this wave; implement claim/apply/ack only in the next command/effect wave.
- Add local typed deferral receipts for externally visible operations; the brokered lifecycle follows in the command/effect wave.
- Preserve partial branches and ambiguous outcomes.

### Wave 2: Lensing driver contract

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

### Wave 6: GALAXY Orrery projection scaffolding (dark only)

- Dark-only graph position and transition animation over fixture/canonical
  projection DTOs.
- Attempt/provider/clone lenses.
- Recovery and incident replay.
- Evidence and uncertainty inspection.
- Budget/capacity view.
- Dedicated GET/SSE-only routes; no dashboard-derived writes or control
  callback.
- No production endpoint or runtime activation before Wave 7 graph admission
  and dependency-closed activation succeed.

### Wave 7: benchmark campaign, graph admission, and world-class claim gate

- Pinned repo-local, RigorBench-style, security, scope, memory, crash, and multi-project suites.
- Same-resource comparison against the current baseline and representative open harnesses.
- Admit only dependency-closed node/edge subsets under externally issued,
  expiring, workload-scoped GraphWarrants; activation remains last.
- Publish a reproducible evidence dossier.
- Claim “world-class” only if the predefined gates pass.

## 17. First implementation slice

The first code slice must be small enough to verify and foundational enough to change what can safely follow:

At this design freeze the Docker client exists, but the daemon is unreachable and no reviewed OCI
archive closure is present. That observation is a fail-closed deployment prerequisite, not permission
to substitute a mock, pull from a registry, build from unpinned input, or weaken containment.
Task 1 cutover may reopen developer-only source-update ingress only after a persisted and re-read
inactive-readiness receipt; production run admission and Discord listener ingress remain closed.

1. install a tiny audited PowerShell Polaris Anchor with protected source/OS-host digest, plus a standard-library-only self-hashing Boot Capsule, pinned interpreter/stdlib, full manifest-attested Python/native dependency and asset closure, and last-known-good controller bundle outside the target; official services enter through the external anchor, while the ignored machine-local `run.ps1` remains user-owned and untouched, tracked developer redirects and `main.py` remain untrusted conveniences, and none can obtain production authority;
2. introduce typed preparation, universal credentialless verification, promotion, and finalization receipts;
3. invoke a recovery-only entrypoint from the previously trusted external controller before snapshot creation, then re-attest canonical; make run admission the first normal-controller operation and create an attested immutable source snapshot before any repository-derived elaboration, discovery, council, planning, or path inspection;
4. require every repository-capable Claude/Codex launch to carry registered clone authority;
5. replace linked integration worktrees with native no-follow candidate snapshots, contained parsing, canonical inert manifests/blob sets, and memory-safe object/index construction;
6. verify the exact proposed SHA in a fresh no-link clone inside a universal pinned credentialless/network-disabled hardened container, regardless of candidate origin;
7. fence canonical ref/index/worktree promotion with a crash-reconcilable journal;
8. preserve live TaskState object identity, persist a receipt-linked pending state, acknowledge the journal, and only then persist `done`; promotion persistence failures are recovery-only and never launch a retry;
9. migrate Society, parallel, and tournament workers under the same sole promotion authority;
10. add pinned Claude/Codex safe-boot adapters whose credentialed drivers have no repository mount and whose repository operations are brokered into credentialless containers;
11. move all mutable controller state plus generated product knowledge to an anchor-attested external per-repository root with no-follow durable stores and project knowledge read-only; a run never rewrites tracked state/knowledge/log/vault paths;
12. route incremental, pre-PR, and self-mod checks through the exact-revision verifier, delete self-referential branch/scaffolding mutation, and defer automatic PR publication until a durable effect authority exists;
13. acquire public HTTPS sources through separate pinned credentialless networked fetch and network-disabled parser containers with SSRF, redirect, wire/disk/object/inflation/tree/time quotas and receipted cleanup; the parser emits only inert blobs/manifest and the host native no-follow materializer creates a newly attested external target;
14. route every Ollama use through a pinned local-only, model-content-and-runtime-digest-bound broker; target env/proxy/tag changes cannot redirect or replace the local model;
15. install deepest-boundary typed deferral for Discord/Cast/bot responses, Obsidian/vault mutation, tunnels, Jerry/remote/SSH, browser/native artifacts, PR publication, and automatic maintenance until durable effect commands exist;
16. preserve public facades only where they cannot retain an unsafe fallback.

This kernel slice includes the minimum pinned safe-boot adapters and credential-separated broker canaries for both locally authenticated Claude and Codex; either provider may write only through the exact clone/broker/verification/promotion path after its real canary earns availability. The next Lensing slice generalizes those adapters into the full provider-neutral routing, normalized telemetry, shadow experimentation, and adaptive authority surface. Durable command claim/apply/ack remains the next kernel slice.

## 18. Acceptance gates

### Kernel

- 1,000 seeded crashes across every attempt/promotion transition produce zero false `done`, lost promotion receipts, or duplicate canonical promotions. Command claim/apply/ack crash guarantees belong to the explicitly next kernel slice.
- No `done` subtask lacks a durable successful canonical promotion receipt.
- No canonical promotion lacks a same-transaction, exact-revision passing verification and semantic-or-explicit-policy-skip review chain; tournament promotion also requires a fully journal-linked SelectionReceipt.
- No mutating subprocess launches in the canonical tree after an isolation failure.
- TOFU proves exact Task 1 proposal equality for every `source_leaves` blob and proposal-lock equality for every runtime/OCI `artifact_leaves` hash before installing one protected combined root. It requires the fresh full-digest-and-nonce operator response; generic preapproval fails. Frozen trust leaves remain equal through final activation, or the entire wave restarts at reviewed Task 1 and fresh TOFU.
- Production launch begins from the OS-installed external anchor, which validates its protected expected digest/generation before the capsule starts under isolated Python with a closed environment/current directory. Replacing the capsule, its sidecar manifest, and its writable generation record together still fails against the anchor. A poisoned repository wrapper, `main.py`, `sitecustomize.py`, package initializer, or top-level import is outside the trusted entrypoint and cannot mint production authority. Self-referential promotion never hot-swaps the running controller; controller activation is a separately verified, operator-authorized restart transaction. Same-user malware or an operator deliberately bypassing the anchor remains outside the target-repository threat claim.
- The protected activation manifest covers the pinned interpreter, stdlib, every Python/native dependency and DLL, dynamic module/entrypoint, schema, prompt/template, and asset. Empty-cwd closed-environment import plus recovery/fresh/resume/config/broker smokes pass before a generation CAS; ambient host/venv/site packages and target code are never executed by build or activation.
- Restart invokes only the previously trusted controller's recovery entrypoint with a one-use authority, reconciles registered resources and existing journaled ref/index/worktree/state transitions, records a receipt, then re-attests and snapshots. Crash canaries prove no snapshot/model call precedes that recovery and direct main/runFull cannot invoke it.
- Every separately committed pre-activation state refuses the entire autonomous run as the first `runFull` operation, before ControlBus/dashboard construction, knowledge refresh, elaboration, discovery, self-referential setup, backend selection, or provider inference. Direct true non-agent version/auth probes remain separate; only the atomic fully migrated activation wave may replace that embargo with exact run/transaction/analysis authority.
- During that embargo, every brain-authored acceptance/verification subprocess is also refused before path creation or process start; command names, wrappers, interpreters, aliases, and caller labels are never treated as proof that a child cannot transitively launch a provider.
- Before the immutable source-snapshot receipt, only the installed external recovery/attestation/snapshot kernel may no-follow-read the exact journal-bound recovery metadata and the bounded inert config/ref/index/object/worktree bytes required to finish an already-journaled transition, attest canonical and construct that snapshot. Optional legacy migration has its separately bounded authority. Neither path executes repository code/configuration nor returns arbitrary content to the normal controller or a model. All other repository-controlled path probes, reads and execution remain forbidden; discovery, elaboration, council, planning and replanning consume bounded repo-relative context receipts from the credentialless broker with no host fallback.
- Production import never loads target `.env`, overrides, or target-derived paths. All TaskState/control/heartbeat/IPC/receipt/log/database/cache/session/knowledge/vault/learning writes use an anchor-attested external root with no-follow/hardlink/reparse-safe durable stores; poisoned target state paths remain byte-identical and only fenced promotion writes the target worktree.
- A stale startup refresh leaves every tracked knowledge file byte-identical and canonical clean. Generated knowledge lives in a content-addressed external runtime cache, is projected read-only, and cannot enter a candidate manifest or proposed tree.
- Self-referential runs never checkout a branch or create `.sc-ctx` in canonical. Incremental/self-mod/pre-PR checks consume the exact revision and universal-verifier authority; post-seal host test execution and revert are impossible.
- Automatic PR publication is explicitly deferred in this slice. No checkout/add/commit/push/`gh` process runs after promotion until a later durable claim/apply/ack publication authority can consume the immutable PromotionReceipt.
- After activation, acceptance commands still never run on the host: `_runVector` requires watchdog-bound verification authority and brokers typed argv into the universal credentialless verifier. Nested test workers remain contained, while wrapper/interpreter/pytest children have no provider binary, credential, config, external path, or network; semantic model checks use the separately guarded review driver.
- Every hostile or unknown mutating/analysis launch has an OS/container-backed capability-enforcement receipt; driver self-report alone never satisfies eligibility. Trusted Local is explicitly labeled `os_enforced=False`, requires a trusted-workload classification, and is ineligible for hostile work.
- Every trusted-Local launch has a live exact-scope grant in a newly spawned terminal-less execution PID after the separate pre-spec worker/resource tree is fully quiesced; approval uses outer-validated canonical bytes, outer-recomputed digest, and a post-quiescence nonce on an exclusive child-inaccessible channel. Concurrent output/input races, console reopen/descendants, prequeued or stale responses, auto-approve, EOF/generic confirmation, hostile rendering, ambiguous serialization, copied receipts/control rows, child-only digests, and model-authored spec/risk/backend fields cannot authorize it.
- Credential materialization is preceded by a durable non-secret cleanup registration; crashes during issuance, injection, revocation, or destruction leave no untracked recoverable secret artifact.
- Concurrent promotions are serialized by the custom lock, Git index fence, and expected-target-SHA compare-and-swap.
- Lost responses before and after durable acknowledgement for begin/abort/finish/rollback/reconcile/release never fabricate ingress truth: request/transaction lookup rechecks the latest journal, protected live fence bits, exact ref/index/tree/controller generation and receipt chain, or returns unknown without asserting open or closed.
- A same-run base advance is impossible until promotion, acknowledgement, terminal persistence, no-mandatory-recovery proof, complete old-revision resource quiescence, native re-attestation, a fresh snapshot, and a persisted/re-read `RunRevisionAdvanceReceipt` all agree. Old-base leases and trusted-Local grants are invalid at the new revision and can never authorize chained work.
- Before ref CAS, complete-tree case/Unicode/trailing-dot-or-space/device/ADS/8.3/path-length mapping is injective on the actual filesystem, canonical index modes are ordinary and fully supported, DIRC v2 optional extensions obey the derived-`TREE`/fail-closed policy, and every path ancestor is held/revalidated no-follow. Windows materialization is handle-relative kernel code; Git never checks out or `read-tree -u`s into canonical.
- Public source acquisition uses distinct pinned credentialless networked fetch and network-disabled parser containers. Every connection uses a controller-fenced public numeric tuple while preserving the normalized URL hostname for TLS SNI/OS-chain hostname validation and exact HTTP `Host`/`:authority`; every redirect gets a new fence. SSRF/rebinding defenses and hard time/wire/disk/pack/object/inflation/tree/path/file quotas cover every stage; the parser emits only inert content-addressed blobs plus a bounded manifest, and the host's native no-follow materializer writes a new external target. Malformed packs and bombs kill registered resources and leave a durable cleanup receipt.
- Every Ollama prompt crosses the anchor-controlled protected-local/loopback broker and exact-matches a live run/analysis authority plus model-content/runtime digest. Remote/proxied/redirected/tag-retargeted or raw client/API/CLI paths are unavailable before prompt transmission.
- Until effect-command claim/apply/ack exists, Discord/Cast/bot responses and attachments, Obsidian/vault mutations, tunnels, Jerry/remote/SSH, browser/native artifacts, PR publication, and automatic maintenance all return an in-memory deferral at their deepest boundary before any effect-facing path/payload read or construction, DNS/socket, process, UI, or external action. The sole permitted write is a later best-effort append of that internal receipt through the pre-attested external `ControllerStateStore`; append failure cannot reach the effect. The local dashboard remains read-only.
- Snapshot/manifest conflict, malformed receipt, quota exhaustion, partial materialization, or acknowledgement failure ends as blocked, failed, cancelled, or quarantined—not success.

### Driver fabric

- 100% of attempts record provider, version, auth/billing mode, capability, spec hash, run revision, base, native snapshot/parser/blob/object/index digests, lease, execution receipt, verification, and terminal state.
- Capability escape tests show zero forbidden filesystem, shell, network, promotion, or sibling-clone effects.
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
- No replacement of TaskState, ControlBus, verifier receipts, or human authority with Gaia.
- No claim that GALAXY Nebula is Claude/Codex internal J-space, hidden chain of thought, or evidence of phenomenal consciousness.
- No active Voyager integration while its canonical status remains standalone, partially unimplemented, training-unauthorized, or RSI-non-operational.
- No dashboard work before the event and receipt contracts are trustworthy.
- No reduction of the test suite as part of this program; that is explicitly owned elsewhere.

## 20. Final architectural invariant

GALAXY Revision 3 may become extraordinarily complex in the **space of hypotheses, evidence, experiments, recovery paths, and projections**.

It remains deliberately simple in the **space of authority**:

~~~text
human authority
  > constitution and kill switches
  > deterministic capabilities and zero-cost policy
  > leases, commands, and effect authorization
  > isolated attempts, staged revisions, and promotion receipts
  > deterministic verification
  > evidence-backed promotion
  > model proposals, memories, councils, and projections
~~~

That ordering is the foundation for aggressive innovation without self-deception.

## Appendix A. Astro naming migration (R3 rename)

The R3 roster was renamed to a single astrophysical-object convention. Every name
below is a real astronomical object or phenomenon chosen so the name *states the
component's job*; no name is decorative. This appendix is normative: the old names
are retired and must not appear in new work.

### A.1 Subsystem and component map

| Retired | Current | Object, and why it names this job |
|---|---|---|
| AURA / `aura.*` | **GALAXY** / `galaxy.*` | A gravitationally bound system of many bodies orbiting a central mass; it contains the objects below |
| Omega Kernel | **Singularity Kernel** | The central point of ultimate density that everything orbits and nothing escapes — inescapable authority |
| Omega Anchor | **Polaris Anchor** | The fixed navigational star: referenced by everything, moved by nothing; the out-of-tree trust root |
| Prism Fabric | **Lensing Fabric** | Gravitational lensing bends one source into multiple images along different paths — one request, many provider paths |
| Spectrum | **Flare** | Solar flares are the eruptive events that stress a magnetosphere — the adversarial teams |
| Aegis | **Magnetosphere** | The field that deflects harmful particles and admits safe ones — admission and containment |
| Cortex | **Nebula** | The bounded cloud in which structure condenses — the bounded working set |
| Khronos | **Pulsar** | A neutron star's beamed emission: the most precise natural clock — the scheduler |
| Daedalus | **Quark** | Fundamental confined constituents that never exist unbound — certified, proof-carrying primitives |
| Mnemosyne | **Accretion** | Infalling matter accumulating in a disk — the append-only record state is reconstructed from |
| Pneuma | **Voyager** | The probe that crossed the heliopause into interstellar space — the (disabled) federation boundary |
| Crucible | **Supernova** | The extreme event that forges elements; only the strongest remnant survives — candidate trials |
| Chronicle | **Gaia** | The mission cataloguing a billion objects' positions and history — the read-only temporal projection |
| Constellation | **Orrery** | A model that displays orbital motion and drives nothing — a strictly read-only projection |
| Lattice | **Filament** | The cosmic web's filaments linking structure across space — evidence and causal-relation projections |
| Sentinel | **Goldstone** | The Deep Space Network complex that listens for spacecraft carrier signal and declares loss-of-signal — liveness detection |
| Relay | **Odyssey** | Mars Odyssey, the orbiter that relays surface transmissions — selective typed broadcast |
| Proteus | **Chamaeleon** | The southern constellation named for the colour-shifting animal — per-provider packet materialization |
| Atlas | **Ephemeris** | A table of positions indexed by time — the capacity calendar |
| Themis | **Lagrange** | Lagrange points: the provably stable positions in a gravitational system — the finite safety game |
| Oracle / Oracle-0 | **Cepheid / Cepheid-0** | Cepheid variables are standard candles, the absolute ground-truth reference — the exact differential oracle |
| Moirai | **Horizon** | An event horizon: an irreversible selection boundary — the complete-packet selector |
| Janus | **Lightcone** | A past light cone is exactly the causally closed region of an event — the causally closed cut |
| Kairos | **Transit** | A planet crossing its star: a precise, fleeting window — kinetic priority |
| Argus | **Roche** | The Roche limit, where tidal forces tear a body apart — the adversarial event-order generator |
| Ariadne | **Worldline** | An object's complete traced path through spacetime — replay and provenance |
| Lethe | **Evaporation** | Hawking evaporation: a body radiating mass and information away — compaction and eviction |
| Anamnesis | **Light-Echo** | Delayed light revealing a past event — bounded recall from the record |
| Palimpsest | **Everett** | Everett branches: coexisting alternative histories — persistent counterfactual state |

Retired prose aliases (must not reappear): `AURA`, `Omega`, `Khronos`, `Chronos`,
`Daedalus`, `Mnemosyne`, `Pneuma`, `Cortex`, `Spectrum`, `Prism`, `Aegis`,
`Crucible`, and the concept names listed above.

### A.2 Identifier families renamed

| Family | Retired | Current |
|---|---|---|
| Contract namespace | `aura.node.*`, `aura.payload.*` | `galaxy.node.*`, `galaxy.payload.*` |
| Scheduler edges | `KH01`–`KH68` | `PU01`–`PU68` |
| Solver edges | `DA01`–`DA12` | `QK01`–`QK12` |
| Adversarial edges | `SP01`–`SP31` | `FL01`–`FL31` |
| Workspace edges | `CT01`–`CT44` | `NB01`–`NB44` |
| Federation edges | `PN01`–`PN06` | `VG01`–`VG06` |
| Context requirements | `MN-R01`–`MN-R34` | `AC-R01`–`AC-R34` |

### A.3 Deliberately **not** renamed

1. **Three-letter node codes** (`KSJ`, `KHA`, `DIO`, `DSC`, `DSE`, `DOA`, `DPV`,
   `CQC`, `BCW`, `SSP`, `LVS`, …) are opaque structural identifiers. They are
   preserved verbatim to keep the manifest, `contract_version`, and
   `ablation_key` surfaces stable across the rename. Their letters no longer
   spell their subsystem, and **no meaning may be inferred from them**; the node
   ledgers are the sole source of a node's purpose.
2. **Inherited single-letter base symbols** (`OA`, `K`, `R`, `B`, `G`, `M`, `E`,
   `V`, `EG`, `RA`, `PA`, `TR`) are unchanged. Note `OA` now reads "Polaris
   Anchor" and `K` reads "Singularity controller": the letter is historical.
3. **All structural counts and invariants** are unchanged: `131 / 250` core,
   `134 / 256` federation-ready, the `>= 105 / 160` floor, `93 / 529` Cepheid-0
   universe maxima, and every gate, threshold, and authority rule. This rename is
   nomenclature-only and changes no behaviour.

### A.4 Required follow-up outside this package

The rename is complete for the original six specification documents. The new
brownfield/frontier registry was authored directly under GALAXY naming. The companion plan
and research artifacts are **not** in this package and still carry retired names
in their paths; they must be renamed on disk to match before the readiness ledger
can be re-asserted:

| Retired path | Required path |
|---|---|
| `plans/2026-07-13-aura-omega-r3-transactional-kernel.md` | `plans/2026-07-13-galaxy-r3-transactional-kernel.md` |
| `plans/2026-07-13-aura-omega-r3-khronos-r1-implementation-plan.md` | `plans/2026-07-13-galaxy-r3-pulsar-r1-implementation-plan.md` |
| `plans/2026-07-13-aura-omega-r3-daedalus-r2-implementation-plan.md` | `plans/2026-07-13-galaxy-r3-quark-r2-implementation-plan.md` |
| `plans/2026-07-13-aura-omega-r3-mnemosyne-r1-implementation-plan.md` | `plans/2026-07-13-galaxy-r3-accretion-r1-implementation-plan.md` |
| `state/research/.../…-raw-khronos-r1-2026-07-13.md` | `state/research/.../…-raw-pulsar-r1-2026-07-13.md` |

Those files' bodies must also be transformed with §A.1–A.2, after which their
recorded SHA-256 values must be recomputed (see the readiness ledger §7.2).
