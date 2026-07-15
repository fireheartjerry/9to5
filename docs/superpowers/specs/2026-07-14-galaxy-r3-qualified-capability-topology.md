# GALAXY Revision 3: Target Capability Topology and Qualification Contract

> **Date:** 2026-07-14 (revision pass; supersedes the 2026-07-13 freeze)
>
> **Status:** frozen R3 target architecture, extended by Pulsar R1 and Quark Portfolio R2; runtime implementation remains deferred
>
> **Parent:** [GALAXY Revision 3](2026-07-14-galaxy-r3-design.md)
>
> **Structural contract annexes:** [Pulsar R1](2026-07-14-galaxy-r3-pulsar-r1-qualified-topology.md) and [Quark Portfolio R2](2026-07-14-galaxy-r3-quark-portfolio-r2-qualified-topology.md)
>
> **Hard constraints:** at least 105 purpose-distinct GALAXY-core target nodes and 160 unique typed
> edges (this is the contractual *floor*; the delivered target is 131 / 250 GALAXY-core,
> 134 / 256 federation-ready — see §1); exactly zero incremental external operating
> cost; no paid API, metered hosted inference, or recurring SaaS dependency

## 1. Decision

The exact purpose-distinct target topology contains:

| Layer | Added nodes | Added edges | Cumulative nodes | Cumulative edges |
|---|---:|---:|---:|---:|
| Audited R3 base | - | - | 71 | 95 |
| Flare and Magnetosphere admission | 16 | 31 | 87 | 126 |
| Nebula | 21 | 44 | **108** | **170** |
| Pulsar R1 | 19 | 68 | **127** | **238** |
| Quark Portfolio R2 | 4 | 12 | **131** | **250** |
| Disabled Voyager federation boundary | 3 | 6 | **134** | **256** |

Count reconciliation (a manifest linter must reproduce these exactly):
core nodes `71 + 16 + 21 + 19 + 4 = 131`; core edges `95 + 31 + 44 + 68 + 12 = 250`;
federation-ready `+ 3 / + 6 = 134 / 256`; overlay-only `60 / 155`. This satisfies
the `>= 105 / 160` floor with a `+26 / +90` margin.

Contract ownership of the 155 overlay edges is split across files: this document
enumerates Flare `31`, Nebula `44`, and Voyager `6` (`81` rows in §7); the
[Pulsar annex](2026-07-14-galaxy-r3-pulsar-r1-qualified-topology.md)
owns `68` and the [Quark annex](2026-07-14-galaxy-r3-quark-portfolio-r2-qualified-topology.md)
owns `12` (`80` rows). `81 + 80 = 161 = 155` GALAXY-core `+ 6` Voyager. No ordered
pair may appear in more than one file. Node ownership splits the same way: this
file owns Flare `16` + Nebula `21` + Voyager `3` = `40`; the annexes own
Pulsar `19` + Quark `4` = `23`; `40 + 23 = 63 = 60` GALAXY-core `+ 3` Voyager.

The independent GALAXY core exceeds the 105-node / 160-edge quota without counting:

- Voyager internals;
- retries, replicas, provider sessions, or ephemeral runtime instances;
- Gaia, Orrery, or other presentation labels;
- aliases, placeholders, schema fields, or dormant compatibility wrappers;
- generic awareness, informs, shares, or all-to-all context relationships.

| Truth surface | Current status |
|---|---|
| exact structural target | GALAXY core 131 / 250; federation-ready 134 / 256 |
| new architecture-contract coverage | 60 / 155 GALAXY-core overlay across this contract and its annexes, plus 3 / 6 disabled Voyager boundary |
| full graph validated structural-manifest count | not reportable until the 71 / 95 base and overlay compile into one validated manifest |
| runtime-qualified, eligible, and active new nodes | zero; every new node remains `specified` |

The graph is complex in capability and sparse in authority. No Flare, Magnetosphere,
Nebula, Pulsar, Quark, or Voyager edge enters the mutation-authority spine:

~~~text
RS -> RI? -> TP -> GS -> BI -> OF -> (MG | RC) -> TJ -> TO -> TA -> PA
~~~

## 2. What earns a counted node or edge

The numeric quota applies to purpose-distinct target topology, not boxes in a
diagram. The 71-node / 95-edge base is structurally audited in the parent design
but is not yet materialized row-by-row in one validated structural manifest.
The normative rows, inherited
profiles, and exact ledgers in this contract and its two annexes provide
architecture-contract coverage for the 60-node / 155-edge GALAXY-core overlay and
the separately counted 3-node / 6-edge disabled Voyager boundary. Full-graph
qualification requires a future machine-readable manifest and linter over base
plus all three ledgers; runtime qualification then additionally requires
implementation receipts and a GraphWarrant.

### 2.1 QualifiedTopologyNode

A node counts only when its contract fixes all of:

~~~text
node_id
semantic_name
contract_version
typed_input_schemas
typed_output_schemas
activation_lifecycle
terminal_lifecycle
state_owner_or_explicit_statelessness
authority_class
forbidden_effects
resource_ceiling
timeout
failure_terminal
observable_consumer_decision_effect
ablation_key
replacement_or_removal_path
source_implementation_maturity
~~~

Source implementation maturity is one of `specified`, `implemented_dark`,
`retired`, or `unavailable`. It describes bytes, never permission. Runtime
`qualified`, `eligible`, and `active` states exist only in an OA-owned overlay
resolved from externally persisted receipts binding the exact node/edge,
controller/runtime digest, GraphWarrant, activation generation, expiry, and
revocation generation. No source manifest edit can activate anything. Target,
implemented, qualified, eligible, and active counts are always reported
separately.

Runtime overlays are immutable scoped records, not one mutable global blob. The
OA-owned `RuntimeActivationOverlaySet` is an append-only CAS journal mapping a
closed `scope_id` to one current overlay-entry head. Each entry binds its exact
qualified/eligible/active node-edge set, governing warrant,
controller/runtime and contract digests, availability, revocation, and
mandatory parent-overlay references. An update advances one scope head; it
cannot rewrite another scope or require the whole set generation to remain
fixed forever.

The first authority-bearing entry in a scope creates immutable
`activation_root_id` and `authority_digest` values plus a monotone leaf
generation. The root fixes source/controller/runtime/contracts,
qualified/eligible/active sets, ablations, workload and budget ceilings,
evidence and rollback bindings, any cutover binding, and parent activation-root
references. A permitted warrant renewal is one external, atomic
create-or-return transaction that issues the successor warrant and advances
that scope to a **renewal-only successor**. The successor preserves every
authority-bearing field byte-for-byte; only warrant/attestation lifetime,
renewal nonce/generation, revocation cursor, and the overlay leaf generation may
advance within the original maximum-lifetime policy. It must be issued while
its unique predecessor is current, unexpired, unrevoked, and renewal-eligible.
Branches, gaps, rewinds, post-expiry renewal, changed sets or parents, or widened
authority are inert. A widening or other semantic change requires a new fully
admitted activation root; it cannot masquerade as renewal.

An authority receipt may anchor an activation root while runtime gates resolve
the unique OA-attested current descendant of that root. A child scope binds the
required parent root and, on every use, resolves that parent's current valid
descendant; advancing an unrelated scope or a valid parent renewal therefore
does not invalidate the child. The effective graph is the union only when every
resolved parent and child head is current and unexpired/unrevoked, all scopes
are contract-compatible, the union is dependency-closed, and no node/edge has
conflicting state. Within each entry and the union,
`active ⊆ eligible ⊆ qualified`; parent membership may satisfy a child
dependency without duplicating ownership. Repeated membership is compatible
only with identical contract/controller/runtime/availability bindings and joins
by the strongest nested membership. Different digests, incompatible
availability, or contradictory ablation is a hard conflict. Parent
expiry/revocation, replacement by a new root, broken lineage, or incompatible
drift makes the dependent scope inert.

Expiry or revocation closes new admission/launch immediately; bounded
drain/containment/recovery may continue, but source metadata never substitutes.
Reactivation requires a fresh externally issued activation root and a
per-scope CAS from the inert entry; the old lineage remains terminal and no old
child automatically follows the new root. Counts report both per-scope state
and the validated effective union.

Activation artifacts never require an impossible hash fixed point. Before
issuance, OA canonicalizes an `ActivationProposal` containing the authority
envelope, scope and proposed root ID, parent roots, exact overlay payload sets,
immutable catalog content entries when applicable, controller/runtime/contracts,
workload and budget bounds, evidence, rollback, and a unique nonce. Its
`activation_binding_digest` contains no not-yet-issued receipt digest. Content
digests are therefore computable first; the GraphWarrant references that binding
and those content digests; overlay and catalog attestations reference the same
binding plus the issued warrant; and one atomic activation/join receipt records
the exact resulting artifact digests. “Mutually bound” everywhere in the R3
contracts means this common canonical binding plus the external join receipt,
never circular inclusion. A renewal derives a new binding from the prior root
and leaf and joins its permitted successor artifacts in one CAS transaction.

A provider invocation, cell instance, retry, workspace epoch, dashboard label,
alias, field, or future placeholder does not create another node. RED, ORG, BLU,
and GRN count separately because their charters, outputs, failure signatures, and
knockout hypotheses are non-interchangeable; their individual runtime instances
do not count.

### 2.2 QualifiedTopologyEdge

An edge counts only when its contract fixes all of:

~~~text
edge_id
source_node_id
target_node_id
closed_payload_schema
source_and_target_contract_versions
activation_guard
causal_epoch_and_phase_rule
authority_and_security_class
provenance_binding
replay_and_deduplication_rule
expiry
timeout_and_failure_behavior
queue_and_backpressure_ceiling
edge_ablation_key
source_implementation_maturity
~~~

Multiple payload variants between the same ordered pair form one closed tagged
union and count once. Duplicate pairs, dangling endpoints, self-loops, visual
grouping lines, generic context sharing, and unbounded feedback arrows do not
count. A conditional or disabled edge counts only when its eligibility,
terminal behavior, and knockout test are complete.

The topology generator must reject duplicate IDs, duplicate ordered pairs,
missing endpoints, incompatible schemas, authority amplification, and every new
ingress into the mutation spine.

### 2.3 Manifest-qualification definition of done

The single machine-readable manifest is "validated" only when a linter over the
base ledger plus all three annex ledgers proves every one of the following. This
is the exit criterion for the "full graph validated structural-manifest count"
truth surface above; until it passes, only `specified` may be reported.

1. every node fixes all 16 `QualifiedTopologyNode` fields; every edge fixes all
   14 `QualifiedTopologyEdge` fields; no field is inherited at runtime;
2. node and edge counts equal the reconciliation above (`131 / 250` core,
   `134 / 256` federation-ready), with the base `71 / 95` ledger materialized
   row-by-row;
3. IDs are unique; ordered pairs are unique across all files; no self-loop,
   dangling endpoint, or duplicate tagged-union variant is counted twice;
4. no edge's artifact grants authority beyond the intersection of its source and
   target contracts, and no edge enters the `RS -> ... -> PA` mutation spine;
5. every `source_implementation_maturity` is one of `specified`,
   `implemented_dark`, `retired`, `unavailable` and every runtime
   `qualified`/`eligible`/`active` claim resolves to an external OA-owned overlay
   receipt, never a source field;
6. every referenced payload schema `galaxy.payload.<name>/v1` exists and is closed.

## 3. Name and lifecycle grammar

Names communicate authority rather than decorate it:

| Family | Meaning |
|---|---|
| Singularity | trusted authority, policy roots, and mutation kernel |
| Lensing | provider, capability, driver, and broker fabric |
| Flare | provider-neutral adversarial and resilience protocol |
| Nebula | bounded non-authoritative shared deliberation |
| Supernova | causal experiments, shadow trials, and promotion evidence |
| Gaia | temporal read-only projection; not counted as authority or capability |
| Orrery | dashboard visualization; not counted as authority |
| Gauntlet | benchmark and certification campaign |
| Magnetosphere | containment and integrity surfaces |
| Filament | evidence and causal-relation projections |
| Odyssey | selective typed broadcast |

Stable service names are permanent. A Team is a stable charter. A Cell is one
ephemeral charter execution. Provider identity is orthogonal: Claude, Codex,
Ollama, or a deterministic local algorithm may service an eligible role without
changing that role's node identity or authority.

The current Singularity-protected provider universe is exact: the user's existing
local Claude Code CLI and Codex CLI subscription surfaces, optional already-local
Ollama inference for reflex/draft work, and deterministic local algorithms. B
binds provider ID, driver/mode, executable and installation digests, credential
surface, billing class (`preowned_local_cli` or `local_compute`), and permitted
role into every sublease. No API provider, free trial, promotional credit, or
“currently zero price” route is eligible, and there is no fallback outside the
allowlist. Revoking Ollama or either CLI requires a new protected generation;
it does not change graph identity.

## 4. Capability overlay

This diagram shows the Flare/Nebula/Voyager overlay owned by this file. The
Pulsar and Quark edges are owned by their qualified annexes; this is not a
single rendering of all 134 target nodes.

Inherited node IDs used below are defined in the
[parent design](2026-07-14-galaxy-r3-design.md), not re-specified
here: `OA` Polaris Anchor, `K` Singularity controller, `R` Lensing router, `B` zero-cost
capacity leases, `G` mission DAG, `M` evidence-scoped memory, `E` evidence
graph, `V` value-of-information planner, `EG` external-effect gateway, `RA`
run-admission authority, `PA` protected purpose/outcome archive. New overlay IDs
(SCT, SIN, SVG, … PXB, PEA) are defined in §5–§6.

~~~mermaid
flowchart LR
    OA["Polaris Anchor and protected policy generation"] --> SCT["Flare Charter Registry"]
    OA --> CCR["Consumer Contract Registry"]
    OA --> AAG["Advisory Admission Gate"]
    R["Lensing Router"] --> CME["Capability Mesh Snapshot"]
    B["Zero-cost Capacity Leases"] --> CME

    G["Mission DAG"] --> SIN["Flare Intake"]
    M["Evidence-scoped Memory"] --> SIN
    E["Evidence Graph"] --> SIN
    SIN --> SVG["Flare Value Gate"]
    V["Value-of-information Planner"] --> SVG
    SCT --> SVG
    CME --> SVG
    SVG -->|"admitted initial round request"| SCG
    B -->|"bounded zero-cost round lease bundle"| SCA["Flare Cell Assembler"]

    SCA --> DIF["Disclosure Ingress Firewall"]
    DIF --> RED["Red Team"]
    DIF --> ORG["Orange Team"]
    DIF --> BLU["Blue Team"]
    DIF --> GRN["Green Team"]
    RED & ORG & BLU & GRN --> SOF["Structured Output Firewall"]
    SOF --> CXR["Contradiction Exchange"]
    CXR --> SCG["Flare Convergence Gate"]
    SCG -->|"atomic initial or next-round lease request"| B
    SCG --> SAB["Flare Advisory Bundle"]
    SAB --> AAG
    AAG --> K["GALAXY Controller"]
    SAB --> E
    E --> COR["Cell Outcome Resolver"]
    COR --> E

    G --> CQC["Nebula Query Compiler"]
    M --> CQC
    CQC --> ABG{"Automaticity hypothesis / deterministic bypass gate"}
    ABG -->|"deterministic or already resolved"| R
    ABG -->|"unknown or deliberate"| WEC["Workspace Epoch Controller"]
    ABG --> WRR["Workspace Receipt Recorder"]
    WEC --> CCL["Nebula Capacity Ledger"]
    WEC --> CQC
    CQC --> RFB["Relational Frame Binder"]
    SIN --> RFB
    CXR --> RFB
    RFB --> CIG["Context Integrity Gate"]
    CIG --> PBG["Phase Boundary Gate"]
    CIG --> WRR
    PBG --> CLE["Cognitive Load Estimator"]
    PBG --> WRR
    CLE --> WAO["Workspace Admission Optimizer"]
    CCL <--> WAO
    WAO --> BCW["Bounded Nebula Workspace"]
    BCW --> SBR["Selective Broadcast Router"]
    CCR --> SBR
    SBR --> BIF["Broadcast Independence Firewall"]
    BIF --> SCA

    CXR --> SSP["Structured Spillway"]
    SSP --> SRB["Spillway Recall Broker"]
    CQC --> SRB
    SRB --> SIN
    BCW --> WSM["Workspace Saturation Monitor"]
    WSM --> WEC

    BCW --> CSC["Nebula Synthesis Compiler"]
    CXR --> CSC
    CSC --> SCG
    SCG -->|"new evidence required"| WEC

    CSC --> WRR
    WRR --> E
    WRR --> WIP["Workspace Intervention Planner"]
    CR["Supernova"] --> WIP
    WIP --> CFR["Counterfactual Frame Runner"]
    BCW --> CFR
    CFR --> WOC["Workspace Outcome Comparator"]
    WOC --> CR
    WOC --> WRR

    EG["Brokered external-effect gateway"] --> PFG["Voyager Federation Gate - specified / disabled"]
    RA["Run Admission Authority"] --> PFG
    PFG --> PXB["Voyager Exchange Broker"]
    PXB --> PEA["Voyager Evidence Adapter"]
    PEA --> E
    PA["Protected purpose outcome archive"] -->|"post-terminal outcome only"| PFG
~~~

## 5. Flare and Magnetosphere admission: 16 purpose-distinct target nodes

Flare is advisory and provider-neutral. Agreement cannot create a verifier
pass, lease, promotion receipt, recovery authority, or canonical mutation.

| ID | Name | Distinct contract and lifecycle |
|---|---|---|
| SCT | Flare Charter Registry | Permanent protected charter generation. Exposes versioned Red, Orange, Blue, and Green contracts from an attenuated Singularity policy reference. |
| SIN | Flare Intake | Per-decision intake snapshot over mission, evidence, and memory references. Terminates admitted, bypassed, blocked, or unavailable. |
| SVG | Flare Value Gate | Deterministic VOI and eligibility gate. Emits an initial-round admission request binding exact charter, capability, evidence, and budget digests; SCG must consume a round credit and only base node B can reserve capacity. |
| CME | Capability Mesh Snapshot | Immutable recomputable intersection of Lensing eligibility and current zero-cost capacity. It never selects a provider or mints a lease. |
| SCA | Flare Cell Assembler | Per-round cell instantiation from one B-issued zero-cost bundle containing disjoint per-color subleases. It cannot bypass SVG, SCG, B, or create capacity. |
| DIF | Disclosure Ingress Firewall | Fail-closed Magnetosphere parser that converts exact mission/evidence references into provider-safe closed briefs; rejects secrets, prompt injection, hidden-reasoning requests, and unconstrained text. |
| RED | Red Team | Adversarial falsification, exploit search, assumption attack, and failure construction. |
| ORG | Orange Team | Converts challenges into minimized reproducers, kill tests, executable canaries, and discriminating counterexamples. |
| BLU | Blue Team | Audits containment, invariants, provenance, observability, context independence, and defensive gaps. |
| GRN | Green Team | Converts defensive findings into recovery, hardening, resilience, and operability proposals. |
| SOF | Structured Output Firewall | Fail-closed Magnetosphere parser, schema validator, provenance binder, and redactor immediately after every provider-team activation. Only sanitized typed claims and immutable evidence references leave it. |
| CXR | Contradiction Exchange | Protected bounded per-round fan-in and typed comparison of sanitized cell results. It binds the admitted-color/sublease set, closes exactly once after every member is terminal or the deadline expires, and never routes directly back to a cell. |
| SCG | Flare Convergence Gate | Sole owner of monotone round credits. Decides admit initial round, continue, converge, exhaust, abstain, unavailable, or cancel; each admitted round requests a fresh atomic B lease bundle. |
| SAB | Flare Advisory Bundle | Immutable terminal materialization of proposals, dissents, evidence, uncertainty, and unresolved obligations. |
| AAG | Advisory Admission Gate | Protected deterministic Magnetosphere gate. Accepts only closed, mission-bound advisory fields under Singularity policy and strips all controller, provider, lease, effect, acceptance, verifier, and mutation fields before K can read the reference. |
| COR | Cell Outcome Resolver | Post-terminal deterministic join of cell predictions to later outcome receipts for calibration and causal credit. It cannot reopen the current run. |

Each color emits typed claims, evidence references, uncertainty, abstention, and
falsifiers. Raw private reasoning and provider transcripts are not graph payloads.

## 6. Nebula: 21 purpose-distinct target nodes

Nebula is a bounded typed-artifact workspace. It is not a model, consciousness
claim, raw transcript bus, truth store, verifier, or authority tier.

| ID | Name | Distinct contract and lifecycle |
|---|---|---|
| CQC | Nebula Query Compiler | Compiles a decision-scoped query with acceptance obligations, stop conditions, and exact causal coordinates. |
| RFB | Relational Frame Binder | Represents subject, predicate, object, argument roles, evidence, contradictions, and unresolved bindings rather than a bag of concepts. |
| CIG | Context Integrity Gate | Rejects invalid provenance, injection, staleness, shared-lineage contamination, and correlation violations. |
| PBG | Phase Boundary Gate | Applies temporal, causal, scope, lifecycle, and disclosure masks. It cannot grant or revoke Singularity action authority. |
| CLE | Cognitive Load Estimator | Predicts marginal slot, context, provider-time, latency, and intervention load. It owns no capacity. |
| WAO | Workspace Admission Optimizer | Selects eligible frames under a fixed permit and records admit, defer, evict, or abstain decisions. |
| CCL | Nebula Capacity Ledger | Owns only workspace-local slot, byte/token, epoch, and intervention sub-reservations inside an existing run envelope. It cannot reserve provider time or mint a B lease. |
| WEC | Workspace Epoch Controller | Creates immutable epochs and exclusively controls bounded recurrence and termination. |
| BCW | Bounded Nebula Workspace | Owns run-scoped ephemeral versioned advisory slots with evidence and contradiction references. |
| CCR | Consumer Contract Registry | Permanent protected typed subscription and disclosure policy generation. |
| SBR | Selective Broadcast Router | Sends only the minimum contract-compatible workspace subset to each subscriber. |
| BIF | Broadcast Independence Firewall | Prevents shared-provider, shared-session, shared-evidence, or derivation-correlated outputs from masquerading as independent support. |
| ABG | Automaticity Hypothesis / Deterministic Bypass Gate | Lets only deterministic or already-resolved work bypass Nebula with an immutable receipt. Unknown classification fails toward bounded deliberation. It cannot infer model-internal automaticity or bypass acceptance and mutation gates. |
| SSP | Structured Spillway | Externalizes evicted, superseded, or currently irrelevant noncritical atoms as content-addressed TTL artifacts. |
| SRB | Spillway Recall Broker | Performs bounded policy-approved recall and readmission by immutable reference. |
| WSM | Workspace Saturation Monitor | Detects occupancy, stagnation, repeated digests, and backpressure; proposes spill, synthesis, or termination. |
| CSC | Nebula Synthesis Compiler | Produces a typed advisory synthesis while preserving dissent, hard constraints, uncertainty, and unresolved obligations. |
| WRR | Workspace Receipt Recorder | Appends mask, admission, broadcast, use, eviction, synthesis, bypass, and intervention lifecycle receipts. |
| WIP | Workspace Intervention Planner | Compiles a preregistered bounded intervention only from a Supernova-issued assignment warrant; it cannot assign treatment or self-authorize execution. |
| CFR | Counterfactual Frame Runner | Executes only Supernova-authorized read-only simulation or isolated counterfactual frames. |
| WOC | Workspace Outcome Comparator | Emits paired measurements and uncertainty; Supernova retains causal inference and promotion recommendation. |

Workspace priority is not truth, confidence, acceptance, or authority. Every
Nebula output remains an immutable advisory reference consumed through an
existing authoritative gate.

### 6.1 Voyager boundary: 3 purpose-distinct target nodes

| ID | Name | Distinct contract and lifecycle |
|---|---|---|
| PFG | Voyager Federation Gate | Specified and disabled fail-closed gate that consumes both a replay-only effect capability from EG and a normal-run federation warrant from RA. It cannot mint either authority. |
| PXB | Voyager Exchange Broker | Separate-process, operation-allowlisted, OS-authenticated replay broker. It owns one bounded exchange transaction and exposes no general Voyager package, shell, filesystem, network, training, or RSI surface. |
| PEA | Voyager Evidence Adapter | Receiver-side closed-schema validator and transitive-taint adapter. It can append a namespaced shadow observation only; it cannot resolve evidence, issue commands, or affect acceptance. |

### 6.2 Normative node-contract completion profile

The row above for each overlay node is normative, not descriptive shorthand. It
combines with this profile to instantiate every `QualifiedTopologyNode` field:

- `contract_version` is `galaxy.node.<lowercase-node-id>/v1`;
- `typed_input_schemas` and `typed_output_schemas` are exactly the incident
  versioned schemas in Section 7, each named
  `galaxy.payload.<lowercase-schema-name>/v1`;
- `observable_consumer_decision_effect` is the row's distinct contract plus its
  outgoing ledger schema; no unlisted effect is permitted;
- `ablation_key` is `node:<ID>:disabled` and the mandatory removal path is the
  matched G0 route, an explicit abstention, or unavailable -- never an implicit
  substitute node;
- `source_implementation_maturity` is `specified`; the external runtime overlay
  has no qualification, eligibility, or activation receipt for these nodes;
- default forbidden effects are repository or canonical mutation, provider or
  effect selection, lease creation, secret access, raw transcript or hidden
  reasoning transfer, acceptance, verification, promotion, recovery fencing,
  human acknowledgement, training, RSI, and authority change.

The only attenuated exceptions are explicit in Section 7: RED/ORG/BLU/GRN may
consume one B-issued per-cell provider sublease; PFG/PXB may consume one EG-issued
replay-only external-effect capability. Neither exception carries mutation,
acceptance, verifier, promotion, or authority capability.

`authority_class` is a closed enum with this exhaustive mapping:

| Authority class | Nodes | Maximum authority |
|---|---|---|
| `protected_policy_registry` | SCT, CCR | emit current protected policy references; no run action |
| `protected_reference_monitor` | DIF, SOF, AAG, CIG, PBG, BIF, PEA | accept/reject/attenuate typed references only; no positive action authority |
| `protected_admission_requester` | SVG, SCG | request B capacity under current policy; cannot reserve or launch |
| `attenuated_provider_dispatch` | SCA | fan out only the exact B-issued lease bundle; cannot select an unleased provider |
| `provider_advisory_executor` | RED, ORG, BLU, GRN | consume one named B sublease and emit advisory output through SOF |
| `advisory_state_owner` | CXR, CCL, WEC, BCW, SSP, SRB, WRR | mutate only the named run-local advisory state under CAS |
| `advisory_transform` | SIN, CME, SAB, COR, CQC, RFB, CLE, WAO, SBR, ABG, WSM, CSC, WIP, CFR, WOC | transform immutable references; no effect or policy authority |
| `replay_effect_gate` | PFG | conjoin and consume VG01/VG02; no effect creation |
| `replay_effect_executor` | PXB | execute only the one EG-authorized local replay operation |

DIF, SOF, AAG, SVG, SCG, SCT, CCR, CIG, PBG, BIF, CXR, WEC, CCL, SRB, PFG,
PEA, and Supernova's assignment/intervention-credit validator are reference
monitors or monotone state owners in the manifest-attested external controller TCB. Their full
executable, interpreter, native/library dependency, schema, and policy digests
bind to the active Singularity generation and an independently checked downstream
attestation receipt. Candidate repository code can neither implement nor
configure them. PXB runs in its separately restricted capsule described in
Section 11.

| Lifecycle profile | Nodes | Activation and terminal lifecycle | State owner | Ceiling and timeout | Failure terminal |
|---|---|---|---|---|---|
| protected registry | SCT, CCR | protected generation change; active until superseded by a newer valid Singularity generation | SCT owns charter versions; CCR owns consumer policies | 64 KiB generation, 2 s deterministic validation | retain LKG only when OA attests the same current unrevoked generation; any advance, revocation, or uncertainty is unavailable |
| decision transform | SIN, SVG, CME, SCA, DIF, SOF, SAB, AAG, COR, CQC, RFB, CIG, PBG, CLE, WAO, SBR, BIF, ABG, WSM, CSC, WIP, CFR, WOC, PEA | one exact run/decision/phase activation; terminates emitted, bypassed, rejected, abstained, unavailable, cancelled, or expired | explicitly stateless; outputs are immutable artifacts | one in-flight activation, 64 KiB input and output, 5 s local deterministic work; CFR additionally obeys its Supernova warrant | no output plus one bounded failure receipt |
| provider team | RED, ORG, BLU, GRN | one accepted round under one named single-use sublease in a B bundle; terminates emitted, abstained, unavailable, cancelled, or lease-expired | explicitly stateless; provider session is not graph state | one provider process, 128 KiB sanitized input, 64 KiB typed output, 900 s or earlier B deadline | sublease closes; no automatic retry |
| bounded run state | SCG, CXR, CCL, WEC, BCW, SSP, SRB, WRR | one run-scoped state machine; closes at its exact terminal, run deadline, cancellation, or credit exhaustion | SCG owns round credits; CXR per-round admitted-color join barriers; CCL local sub-reservations; WEC epochs; BCW slots; SSP TTL refs; SRB recall credits; WRR append-only receipts | 32 slots, 4 epochs, 4 rounds, 8 recalls, 3 interventions, 8 MiB total artifacts, never beyond run deadline | CAS to exhausted, cancelled, or unavailable |
| disabled federation | PFG, PXB | disabled until a GraphWarrant; then one purpose-bound replay transaction | PFG owns kill-switch/capability consumption; PXB owns nonce/dedupe transaction state | one in flight, one retry only before effect acknowledgement, 256 KiB cumulative transfer, 60 s | unavailable audit receipt and zero replay effect |

Any node-specific row is a stricter override. A future manifest compiler must
materialize these inherited values per node and fail on an omitted, widened, or
ambiguous field; inheritance is forbidden at runtime.

## 7. Exact unique edge ledger

Every row below has one ordered pair and one named closed payload. The manifest
contains no duplicate ordered pair.

The following inherited profile completes every architecture-time edge
contract. `contract_version` is `galaxy.edge.<lowercase-edge-id>/v1`; endpoint
versions are the Section 6 node versions; the payload version is
`galaxy.payload.<lowercase-schema-name>/v1`; and the ablation key is
`edge:<ID>:disabled`. Every payload uses a closed envelope containing only edge,
graph, source/target contract, run, mission, attempt, base revision, epoch,
phase, authority, provenance, causation, idempotency, expiry, artifact-kind,
artifact-digest, and one content-addressed typed artifact reference. A field-level
artifact schema is mandatory before runtime qualification; an unknown field or
schema version fails closed.

For every current SP/CT/PN ledger row,
`source_implementation_maturity = specified`; the external runtime overlay has
no qualification, eligibility, or activation receipt for any of these edges.

Default activation requires a freshly resolved GraphWarrant issued by the
external Polaris Anchor/admin authority, matching endpoint, schema, controller,
runtime-overlay, activation, and revocation digests, an unexpired same-run
upstream receipt, valid phase, and an unused idempotency key. The coordinator
and the deepest consumer authority gate re-resolve expiry and revocation; a
source `enabled` bit or cached receipt cannot substitute. Default authority is
`advisory_reference`; it cannot be amplified by a target. Provenance and taint
are transitive. Replay returns the same receipt without re-execution. Default
expiry is the earliest of 15 minutes, the warrant expiry, the source artifact
expiry, and run deadline. Default queue ceiling is one in-flight item per
edge/run/purpose and 64 KiB; timeout emits one unavailable receipt and no target
activation.

| Override profile | Edges | Additional rule |
|---|---|---|
| protected generation | FL01, FL27, NB01 | requires the exact current OA generation and carries policy reference only |
| provider capacity | FL11, FL12, FL24 | FL11 is admission into SCG; FL24 is the sole B CAS request; only FL12 carries a bounded bundle of disjoint single-use B subleases; stale snapshots never authorize execution |
| bounded color fan-in | FL22, FL23 | FL22 accepts exactly one terminal variant per admitted color/sublease; CXR closes once at complete set or deadline, records missing terminals, and only then emits FL23 |
| bounded recurrence | FL24, NB08, NB28 | must carry proof that the sole protected owner atomically consumed the applicable CyclePermit credit before delivery and advanced the round, epoch, or recall count |
| bounded epoch request | NB30, NB34 | consumes one separate epoch-request credit and changes no epoch-transition credit or index; WEC may reject, and NB08 is the sole epoch transition |
| local capacity CAS | NB07, NB18, NB19 | workspace-local only; commit/release is monotone and cannot trigger provider work |
| post-terminal resolution | FL30, FL31, VG06 | requires protected terminal state and cannot reopen or recursively re-enqueue a resolved claim |
| Supernova intervention | NB38 through NB43 | requires one Supernova assignment warrant, fixed treatment/control IDs, and one intervention credit |
| Voyager effect | VG01 through VG05 | disabled by default; VG01 is replay-only EG effect authority, VG02 normal-run admission, and VG03 their attenuated conjunction |

`causal_epoch_and_phase_rule` uses the following closed profiles. A payload from
another run, a future phase, a closed epoch, or an unlisted transition is invalid.

| Phase profile | Edges | Exact relation |
|---|---|---|
| `P0_PROTECTED_GENERATION` | FL01, FL27, NB01 | no run epoch; exact current OA generation only |
| `S0_INTAKE` | FL02-FL11 | same run, `epoch=0`, `round=0`; FL11 may request SCG admission but cannot advance round |
| `S1_ROUND_OPEN` | FL24, FL12 | SCG first CAS-advances `round r` to `r+1` and decrements one credit; FL24 requests and FL12 delivers the B bundle for exactly `r+1` |
| `S2_ROUND_BODY` | FL13-FL23 | same run and exact open round; FL23 closes collection for that round |
| `S3_TERMINAL_ADVISORY` | FL25-FL26, FL28-FL29 | same run after SCG terminal decision; no new round/epoch; FL27 remains protected-generation policy input |
| `S4_POST_TERMINAL_RESOLUTION` | FL30-FL31 | only after protected run terminal; same claim/outcome key; cannot reopen run |
| `C0_DECISION_CONTROL` | NB02-NB07, NB44 | same run and decision; NB06/NB07 target candidate epoch `e+1` without opening it |
| `C1_EPOCH_OPEN` | NB08 | WEC sole CAS from open/current `e` to `e+1`, consuming exactly one epoch credit after local budget succeeds |
| `C2_EPOCH_BODY` | NB09-NB27, NB29, NB31-NB33, NB35-NB36 | same run and exact immutable open epoch `e`; no index advance |
| `C2_RECALL_DELIVERY` | NB28 | same epoch `e`; SRB CAS-consumes exactly one recall credit before delivery |
| `C2_NEXT_EPOCH_REQUEST` | NB30, NB34 | same epoch `e`, targets `e+1`; protected dispatch/WEC tombstones a deterministic request key and consumes one request credit before acceptance, but only NB08 can consume an epoch-transition credit or advance the index |
| `C3_SHADOW_EXPERIMENT` | NB37-NB43 | separate Supernova experiment ID after eligible WRR receipt; fixed assignment and no current-run action authority |
| `F0_FEDERATION_REQUEST` | VG01-VG02 | same admitted purpose and Singularity generation; neither starts an exchange alone |
| `F1_FEDERATION_EXCHANGE` | VG03-VG05 | PFG CAS-opens one exchange ID; all messages bind that ID and close on VG05 or failure |
| `F2_OUTCOME_FEEDBACK` | VG06 | later PA terminal receipt only; cannot start replay and may condition only a fresh F0/F1 transaction |

### 7.1 Flare and Magnetosphere edges: 31

| ID | Source | Target | Closed payload schema |
|---|---|---|---|
| FL01 | OA | SCT | ProtectedCharterGenerationRef |
| FL02 | R | CME | ProviderEligibilitySnapshot |
| FL03 | B | CME | ZeroCostCapacitySnapshot |
| FL04 | G | SIN | MissionRef |
| FL05 | M | SIN | RetrievedEvidenceRefs |
| FL06 | E | SIN | TrustTieredEvidenceDelta |
| FL07 | SIN | SVG | SpectrumRequest |
| FL08 | V | SVG | ValueOfInformationBudget |
| FL09 | SCT | SVG | CharterConstraints |
| FL10 | CME | SVG | EligibleProviderCapacityMatrix |
| FL11 | SVG | SCG | SpectrumInitialRoundAdmissionRequest |
| FL12 | B | SCA | BoundedSpectrumRoundLeaseBundle |
| FL13 | SCA | DIF | CellBriefBundle |
| FL14 | DIF | RED | SanitizedFalsificationBrief |
| FL15 | DIF | ORG | SanitizedCounterexampleBrief |
| FL16 | DIF | BLU | SanitizedIntegrityBrief |
| FL17 | DIF | GRN | SanitizedResilienceBrief |
| FL18 | RED | SOF | FalsificationResult |
| FL19 | ORG | SOF | ReproducerCanaryResult |
| FL20 | BLU | SOF | IntegrityAuditResult |
| FL21 | GRN | SOF | ResilienceResult |
| FL22 | SOF | CXR | SanitizedCellResultUnion |
| FL23 | CXR | SCG | RoundStateAndContradictionSet |
| FL24 | SCG | B | SpectrumNextRoundLeaseCASRequest |
| FL25 | SCG | SAB | SpectrumTerminalDecision |
| FL26 | SAB | AAG | AdvisoryCandidateBundle |
| FL27 | OA | AAG | ProtectedAdvisoryAdmissionPolicy |
| FL28 | AAG | K | AttenuatedMissionAdvisoryRef |
| FL29 | SAB | E | TaintedAdvisoryObservationRef |
| FL30 | E | COR | TerminalClaimJoinRequest |
| FL31 | COR | E | CellResolutionReceipt |

SCT and CME do not connect directly to SCA. SVG asks SCG to admit the initial
round; SCG consumes a round credit and FL24 asks B to reserve atomically. Only
FL12 can instantiate a round. A continuation must pass CXR, SCG, FL24, and B
before SCA sees a fresh bundle. AAG accepts no free text and FL28 cannot alter
controller configuration, routing, leases, effects, acceptance, verification,
promotion, recovery, or mutation fields.
FL12 contains an explicit admitted-color set and one disjoint sublease per
admitted color, with aggregate capacity reserved atomically by B. SCA/DIF emit
FL14-FL17 only for tagged members of that set. Each emitted brief binds its own
unconsumed sublease ID and physically zero-cost provider allowlist, and that
color team atomically consumes only its sublease before launch. A stale CME
snapshot, absent branch tag, duplicate sublease, or sanitized brief has no
execution authority.

Each admitted sublease must terminate as `emitted`, `abstained`, `unavailable`,
`cancelled`, or `expired`. SOF validates normal results; for loss before provider
output, the protected dispatcher supplies only the signed B/sublease terminal
receipt, never synthetic claims. CXR opens one barrier keyed by
`(run, round, admitted_color_set_digest, lease_bundle_id)`, CAS-deduplicates one
FL22 terminal per member, and emits FL23 exactly once when the set is complete or
the round deadline closes it with explicit missing terminals. Arrival order can
change neither the bundle nor SCG's decision input.

### 7.2 Nebula edges: 44

| ID | Source | Target | Closed payload schema |
|---|---|---|---|
| NB01 | OA | CCR | ProtectedConsumerPolicyGenerationRef |
| NB02 | G | CQC | MissionNodeRef |
| NB03 | M | CQC | RetrievalSnapshotRef |
| NB04 | CQC | ABG | WorkspaceQuery |
| NB05 | ABG | R | FastPathRouteRecommendation |
| NB06 | ABG | WEC | DeliberateEpochRequest |
| NB07 | WEC | CCL | EpochBudgetReservation |
| NB08 | WEC | CQC | EpochOpenOrRefreshReceipt |
| NB09 | SIN | RFB | SpectrumCandidateBundle |
| NB10 | CXR | RFB | ContradictionRelationSet |
| NB11 | CQC | RFB | WorkspaceQuery |
| NB12 | RFB | CIG | RelationalFrame |
| NB13 | CIG | PBG | IntegrityEligibleFrame |
| NB14 | CIG | WRR | IntegrityQuarantineReceipt |
| NB15 | PBG | CLE | PhaseMaskedFrame |
| NB16 | PBG | WRR | PhaseRejectionReceipt |
| NB17 | CLE | WAO | CalibratedLoadForecast |
| NB18 | CCL | WAO | AvailableSlotReceipt |
| NB19 | WAO | CCL | CapacityCommitOrRelease |
| NB20 | WAO | BCW | WorkspaceAdmissionReceipt |
| NB21 | BCW | SBR | SealedWorkspaceFrame |
| NB22 | CCR | SBR | ConsumerContractSnapshot |
| NB23 | SBR | BIF | TargetedBroadcastEnvelope |
| NB24 | BIF | SCA | SanitizedCellInputEnvelope |
| NB25 | CXR | SSP | TypedUnbroadcastIntermediate |
| NB26 | SSP | SRB | TimeBoundSpillRef |
| NB27 | CQC | SRB | RecallQuery |
| NB28 | SRB | SIN | ReadmissionCandidate |
| NB29 | BCW | WSM | WorkspaceOccupancySnapshot |
| NB30 | WSM | WEC | SaturationOrStagnationSignal |
| NB31 | BCW | CSC | GroundedWorkspaceFrame |
| NB32 | CXR | CSC | BoundedContradictionBundle |
| NB33 | CSC | SCG | SynthesisCandidate |
| NB34 | SCG | WEC | MoreEvidenceEpochRequest |
| NB35 | CSC | WRR | SynthesisTraceReceipt |
| NB36 | WRR | E | TaintedWorkspaceObservationReceipt |
| NB37 | WRR | WIP | InterventionEligibleTrace |
| NB38 | CR | WIP | ExperimentPolicyAssignmentAndCreditWarrant |
| NB39 | WIP | CFR | PreregisteredInterventionPlan |
| NB40 | BCW | CFR | CleanControlFrame |
| NB41 | CFR | WOC | PairedShadowOutcomes |
| NB42 | WOC | CR | CausalEffectUncertaintyReceipt |
| NB43 | WOC | WRR | InterventionOutcomeReceipt |
| NB44 | ABG | WRR | BypassOrDeliberateDecisionReceipt |

SCG to SAB belongs to Flare edge FL25 and is intentionally absent here.
NB24 is non-activating supplemental input and must bind an already accepted
FL12 lease; FL12 remains the sole SCA activation edge. NB36 is observation-only
and inherits the evidence taint rules in Section 7.4.

### 7.3 Voyager federation edges: 6

The three boundary nodes are architecture-qualified but disabled by default. Voyager's
internal graph is separately governed and excluded from GALAXY's count.

| ID | Source | Target | Closed payload schema |
|---|---|---|---|
| VG01 | EG | PFG | ReplayOnlyPneumaEffectCapability |
| VG02 | RA | PFG | AttenuatedFederationWarrant |
| VG03 | PFG | PXB | PneumaFederationLease |
| VG04 | PXB | PEA | PneumaResponseEnvelope |
| VG05 | PEA | E | TaintedPneumaShadowObservation |
| VG06 | PA | PFG | ProtectedTerminalOutcomeFeedback |

### 7.4 Evidence trust and taint

E is one canonical graph with non-interchangeable partitions, not one flat trust
bucket. `authoritative_outcome` accepts only protected F/PA/verifier receipt
ancestry. `advisory_observation` accepts FL29, NB36, and VG05 while retaining the
full transitive source closure and can never satisfy acceptance, verification,
promotion, or a resolved claim. `resolution_receipt` records COR/Supernova joins
without upgrading their source material.

FL06 is a closed tagged union. Its `resolved` variant requires authoritative
outcome ancestry. Its `advisory_shadow` variant may create deliberation pressure
only, remains tainted through SIN/Nebula/Flare, and cannot contribute an
independent-support count. Content, agreement, repetition, or passage through a
workspace never changes trust tier. Supernova may promote a routing, memory, or
graph policy while preserving the complete source closure and taint; it can
never declassify an observation or create `authoritative_outcome`/`resolved`.
Only protected F/PA/verifier ancestry can create those separately named types.

## 8. Bounded cycles and termination proof

All feedback is artifact recurrence, never call-stack recursion or an authority
cycle. Every recurrent transition requires a CyclePermit containing:

~~~text
run_id
permit_id
owner_generation
cas_version
single_use = true
current_epoch
next_epoch
current_round
next_round
remaining_epoch_credits
remaining_epoch_request_credits
remaining_round_credits
remaining_intervention_credits
remaining_provider_and_context_budget
deadline
input_evidence_digest
challenge_digest
novelty_proof
transitive_origin_closure_digest
~~~

Credits cannot be replenished within a run. Every feedback transition consumes
at least one applicable credit by owner CAS before delivery while all other
ceilings remain non-increasing. SCG alone owns round credits, WEC epoch credits,
CCL workspace-local reservations, Supernova intervention assignment/credits, B
provider capacity, SRB recall credits, and PFG federation transaction nonces. No
consumer can mint or replenish its upstream permit.

SCG initializes `current_round=0` and `remaining_round_credits<=4`. Both initial
FL11 admission and a continuation require SCG to CAS
`current_round += 1; remaining_round_credits -= 1` before FL24, so the cap is four
total rounds, not one plus four. WEC analogously initializes `current_epoch=0`
and at most four epoch credits plus eight run-wide/two-per-epoch request credits.
Each NB30/NB34 request key is deterministically derived from `(run, epoch,
request_kind, evidence_or_challenge_digest)`; WEC persists an accept/reject
tombstone and CAS-consumes one request credit before accepting the edge. A key
cannot be retried and an epoch cannot accept more than two such requests. WEC
performs the sole epoch-transition CAS before NB08. SRB initializes at most eight
recall credits and CAS-consumes one before every NB28 delivery.

| Cycle | Distinct messages | Termination |
|---|---|---|
| SVG or CXR to SCG to B to SCA to cells to CXR | admission/contradiction set / round CAS request / disjoint B sublease bundle / sanitized result | SCG CAS consumes one credit before every FL24; default two total rounds, hard cap four total, same-digest stop; no direct CXR-to-cell edge |
| CCL and WAO | local CapacityGrant / AtomicReservationCommit | CCL CAS owns monotone reserve-commit-release state; no provider capacity and no recursive event trigger |
| WEC pipeline | EpochPermit / SaturationSignal / EvidenceRequest | WEC CAS consumes before NB08; default two epochs, hard cap four, new evidence or material contradiction required |
| E and COR | TerminalClaimJoinRequest / idempotent CellResolutionReceipt | E owns pending-to-resolved-or-unresolved CAS; one join per claim/outcome digest; FL31 receipts are origin-excluded from FL30 |
| SSP to SRB to SIN | SpillRef / RecallQuery / ReadmissionCandidate | one readmission per evidence digest and eight total per run; TTL and stale-source rejection |
| WRR to WIP to CFR to WOC to CR | assignment warrant / plan / paired outcome / causal receipt | Supernova fixes treatment/control before WIP; default one intervention, hard cap three; an outcome cannot trigger the same assignment ID |
| EG/RA to PFG to PXB to PEA to E, then later PA to PFG | effect capability / federation warrant / response / shadow observation / protected outcome | one nonce and purpose CAS, one pre-ack retry, no post-ack replay; VG06 accepts only a PA terminal receipt plus transitive origin closure |

VG06's closed union has two variants. `IndependentControlOutcome` proves no
Voyager ancestry. `TreatedOutcomeLabel` lists the exact Voyager exchange ancestry,
is label-only for preregistered shadow metrics, and is prohibited from returning
through VG04 as evidence. Neither variant can support the same or a descendant
claim, so feedback cannot manufacture independent confirmation.

Cancellation, deadline, provider loss, invalid provenance, exhausted credit,
unchanged digest, or missing novelty terminates as cancelled, unavailable,
exhausted, or abstained. None widens authority or budget.

No recurrent artifact contains a live mutation lease, repository-global slot,
promotion capability, recovery fence, or terminal acknowledgement.

## 9. Transformer transfer

The pinned source is
[Attention Is All You Need, arXiv:1706.03762v7](https://arxiv.org/abs/1706.03762v7).
Its mechanisms generate engineering hypotheses; they do not transfer neural
network guarantees to an autonomous system.

| Paper evidence and claim location | GALAXY engineering hypothesis |
|---|---|
| query/key/value weighted retrieval, Sections 3.2.1-3.2.2 | unresolved typed DecisionQuery over canonical scope/capability/provenance keys and immutable evidence/proposal references |
| parallel heads at similar total compute, Sections 3.2.2 and 6.2 Table 3(A) | independently chartered projections tested at 1, 4, and 8 roles under the same total Claude/Codex/context budget |
| decoder future-position mask only, Sections 3.1 and 3.2.3 | physically enforced phase, authority, contamination, lifecycle, and scope masks; their safety comes only from contracts and adversarial tests |
| additive residual connections, Section 3.1 | an independent hard-fact/constraint channel that attention priority cannot erase; immutability is an GALAXY invariant, not a paper result |
| positional encoding, Section 3.5 | explicit run revision, base SHA, transaction, epoch, round, journal position, and causal parents |
| position-wise feed-forward transform, Section 3.3 | narrow local specialist transform after relational retrieval |
| dense evaluated attention and restricted attention proposed only as future work, Section 4 | sparse typed neighborhoods are an GALAXY cost/security hypothesis, not a demonstrated Transformer result |

The paper establishes machine-translation and constituency-parsing results, not
autonomous-agent topology. Its fixed-compute head ablation is non-monotonic:
single-head quality is worse, but too many heads also hurt, so more graph roles
receive no presumption of benefit. Separately, GALAXY selects sparse routing as an
independent cost/security hypothesis that must beat a matched full-context
control; head-count evidence does not establish sparse connectivity.

## 10. Global Workspace and J-space transfer

The pinned web source is the July 6, 2026 publication
[Verbalizable Representations Form a Global Workspace in Language Models](https://transformer-circuits.pub/2026/workspace/index.html),
accessed 2026-07-13 with response SHA-256
`339843f5e8d29cb5276c6d57cce64cc005523261d98b9d0b01393876e77d8599`.

**Observed evidence in the paper:**

- a small privileged set of verbalizable representations supports report,
  directed modulation, internal reasoning, flexible generalization, and
  selective causal involvement;
- swap, suppression, and ablation interventions change some downstream behavior;
- coherent workspace-like content is concentrated in an intermediate layer band,
  has limited measured capacity, and shows unusually broad upstream/downstream
  connectivity consistent with a broadcast-like format;
- substantial routine language processing persists under J-space suppression,
  while tested complex reasoning is more impaired.

**Explicit limits and non-findings:**

- the authors do not find cleanly separable specialist processors;
- the documented broadcast occurs inside one feed-forward pass, not through a
  recurrent processor/workspace loop;
- observed competition may not be the sharp ignition proposed in biological
  global-workspace theories;
- J-lens is approximate and initially biased toward single-token concepts;
- the paper does not provide a classifier that predicts in advance whether an
  arbitrary new computation will use J-space.

**GALAXY hypotheses, not paper findings:** provider-neutral specialists working on
private briefs; typed competitive admission; targeted consumer subscriptions;
recurrent immutable epochs; relational frames; correlation-aware independence;
security and disclosure masks; explicit capacity accounting; and selective
broadcast outside a model. RFB, WEC, BIF, CIG, PBG, CCL, WSM, SBR, WRR, WIP,
CFR, and WOC exist to test those hypotheses rather than cite them into truth.
ABG bypasses only deterministic or already-resolved work; unknown classification
fails toward bounded deliberation, and “automaticity” remains an experimental
label.

The engineered Nebula is not Claude's or Codex's internal J-space, is not access
to hidden activations or chain of thought, and is not evidence of phenomenal
consciousness. The paper's approximate occupancy near 25 is not copied as a
constant. Capacity is tested at 8, 16, and 32 under fixed budgets.

The official
[Anthropic jacobian-lens repository at commit 581d398](https://github.com/anthropics/jacobian-lens/commit/581d398613e5602a5af361e1c34d3a92ea82ba8e)
is an Apache-2.0 reference implementation for compatible open-weight Hugging
Face decoder models. Fitting the averaged Jacobian requires activation access
and backward passes; applying a pre-fitted lens requires activation access, its
fitted map, and the model's unembedding. It cannot inspect subscription-backed
Claude or Codex internals. Downloaded model weights and corpora retain their own
licenses. Any reuse belongs in an optional digest-pinned
local research annex and enters Supernova only as fallible evidence, never as a
verifier, monitor, consciousness claim, or authority gate.

### 10.1 Research transfer records

All records expire on 2027-01-09 or earlier if the source, local model, license,
or relevant GALAXY contract changes. Expiry means re-review, not automatic renewal.

| ID | Pinned claim location | GALAXY hypothesis | Preregistered falsifier |
|---|---|---|---|
| TR01 | Transformer v7, Sections 3.2.1-3.2.2 and 6.2 Table 3(A) | typed Q/K/V retrieval and multiple independent charters can improve decisions | equal-budget 1/4/8-role trial shows no held-out gain or a sham charter matches the real mechanism |
| TR02 | Transformer v7, Sections 3.1, 3.2.3, 3.5, and 4 | explicit ordering, an independent constraint channel, and sparse hard masks reduce contamination without losing quality | one-mask removal has no signature, constraint can be erased, or sparse routing loses hidden quality at equal budget |
| GW01 | Global Workspace paper, “A global workspace in language models,” “The J-space acts as a Global Workspace,” and “The J-space's structure supports its function” | a bounded selective artifact workspace can improve flexible multi-step agent decisions | matched no-workspace/full-context controls win, causal frame swaps do not mediate output, or simple-task overhead regresses |
| GW02 | Global Workspace paper, “Limitations and open questions” and “Notable differences from human cognition” | GALAXY's typed specialists, targeted broadcast, relational binding, and immutable epochs repair useful limits in an external orchestration setting | flat claims, untargeted broadcast, or feed-forward-only controls match the real mechanism under equal resources |
| JL01 | jacobian-lens commit `581d398613e5602a5af361e1c34d3a92ea82ba8e`; README “Apply,” “Fit,” and “License and data”; `jlens.fitting.fit`, `jlens.fitting.jacobian_for_prompt`, and `jlens.lens.JacobianLens.apply` | an optional local replication may generate useful interpretability hypotheses | no license-compatible local model/corpus, replication instability, prohibitive local cost, or no downstream Supernova value |

Every transfer now binds revision, claim location, hypothesis, falsifier,
experiment family, and expiry. Inspiration without a falsifiable transfer record
is complexity theatre.

## 11. Voyager federation contract

Voyager receives an architectural port, not operational integration.

The live `C:\pneuma-lab\docs\project-status.json` manifest, as of 2026-07-10,
currently reports:

- standalone integration and no operational nervous system;
- only pneuma_trace_to_replay implemented among six required 9to5 edges;
- J-space and J-lens not implemented and neither sufficient nor currently
  authorized to support a phenomenal-consciousness claim;
- new training not authorized;
- runtime model integration none;
- RSI loop not operational;
- claim-of-record artifact absent.

Therefore PFG, PXB, and PEA remain specified and disabled. Voyager output is
`advisory_shadow`; invoking even a local replay is correctly classified as a
brokered external-computation effect, not hidden inside “advisory only.”

### 11.1 Semantic crosswalk

| Voyager required edge ID | GALAXY realization |
|---|---|
| nine_to_five_snapshot_to_pneuma_trace | existing K-to-EG request; VG01 replay-only effect capability, conjoined with VG02, then transmitted under VG03 |
| pneuma_trace_to_replay | purpose-bound, operation-allowlisted PXB transaction returning through VG04 |
| replay_outputs_to_shadow_log | VG04 then VG05 as a namespaced append-only shadow record |
| shadow_log_to_advisory_pressure | FL06 `advisory_shadow` variant into SIN; taint remains transitive and no new edge is counted |
| advisory_pressure_to_authority_gated_action | FL26 to AAG, then attenuated FL28 into K, followed by all normal GALAXY gates |
| realized_outcome_to_pneuma_feedback | PA-sourced VG06 may condition a fresh stateless `outcome_conditioned_replay_v1`; it never writes Voyager state and requires fresh VG01, VG02, and VG03 authority |

### 11.2 Mandatory federation envelope

Every request and response binds:

~~~text
protocol_id and version
schema digest
message, correlation, causation, and idempotency IDs
single-use nonce, capability ID, issuer generation, and channel binding
issuer repository ID, source commit, process-image digest, and executable digest
OS peer principal/SID, named-pipe identity, and ACL digest
canonical Voyager edge ID
direction and message kind
operation = replay_trace_v1 | outcome_conditioned_replay_v1
run, attempt, revision, base, goal, and acceptance digests
source commit, dirty state, manifest as-of, and manifest digest
authority_class = replay_only_external_effect | advisory_shadow
mutation_authority = false
external_computation_actuation = true
host_or_repository_mutation = false
data_mutation = false
training_authorization = not_authorized
automatic_training = false
rsi_eligible = false
supports_consciousness_claim = false
payload_class = closed_trace_request | closed_replay_summary | evidence_ref
reference_scheme = aura-evidence-sha256 | aura-shadow-sha256
raw_dataset_bytes = false
raw_hidden_reasoning = false
absolute_path_transfer = false
transitive provenance and taint closure digest
per-message and cumulative byte/query/item/runtime/in-flight/retry/deadline ceilings
receiver-enforced redaction policy and content digest
expiry and deduplication state
~~~

The endpoint is a pinned OS-authenticated local named pipe with an exact process
image and operation allowlist. PFG consumes anchor-bound single-use VG01 and VG02
capabilities; PXB never accepts a shell command, module name, arbitrary method,
path, URI, or caller-supplied executable. Only `aura-evidence-sha256` references
resolvable inside GALAXY's content-addressed evidence store are valid requests.
Only the closed replay-summary schema can return. Booleans in the sender envelope
are not trusted: both PXB and PEA enforce content type, reference scheme,
provenance, taint, cumulative bandwidth, and decode limits independently.

PXB is launched by the protected external controller under a dedicated restricted
OS principal/AppContainer. The OS policy denies `C:\pneuma-data`, network sockets,
filesystem writes outside its bounded output pipe, shell/tool lookup, dynamic
code loading, child processes, and every path except the read-only staged request
plus the digest-pinned Voyager replay code. The launcher attests the complete
Python/interpreter, module, native-library, configuration, and replay-operation
dependency closure -- never merely `python.exe`. An inability to prove any deny
or digest closes the boundary as unavailable.

`outcome_conditioned_replay_v1` is a closed VG03 variant that supplies one VG06
terminal-label reference and its prior exchange ID as ephemeral replay input. It
returns through VG04/VG05 and exits without a Voyager write. Durable feedback,
learning, model change, training, or RSI would be a different future effect and
is not represented by these six edges.

The boundary forbids:

- direct Python imports between repositories;
- shared databases, workspaces, long-lived credentials, worktrees, or mutation leases;
- reads or mounts of raw `C:\pneuma-data` by the 9to5 boundary process, or any
  raw data/path transfer across the boundary; Voyager's own separately authorized
  internal data handling remains outside GALAXY;
- raw transcripts, hidden chain of thought, or ungrounded self-report;
- training, fine-tuning, model promotion, or RSI entrypoints;
- shell passthrough, network widening, paid services, or provider credentials;
- arbitrary commands, verifier influence, host/repository mutation, or action authority.

Malformed, stale, oversized, unauthenticated, over-budget,
provenance-incomplete, policy-incompatible, or unknown-readiness traffic produces
one bounded unavailable audit receipt and no advisory artifact or replay. Disabled
or unavailable federation is observationally equivalent to absence for
repository bytes, canonical state, provider use, Voyager/data access, controller
decisions, and evidence; only that local audit receipt may differ.

Activation remains prohibited until all six Voyager edges are canonically
implemented, status validation passes, kill-switch and schema compatibility are
proven, and a Graph Admission Trial shows deterministic replay, no raw-data
access or transfer, no training/RSI/host-mutation path, correctly brokered replay
actuation, zero paid egress, and no regression.

Future Voyager internals use a separate PN namespace and never inherit GALAXY
authority or count toward the independent GALAXY-core quota.

## 12. Supernova Graph Admission Trial

Every graph delta is a candidate, not a permanent entitlement.

| Arm | Meaning |
|---|---|
| G0 | incumbent graph |
| Gcap | incumbent graph receiving the candidate's exact provider, context, tool, latency, and local-compute budget |
| Gsham | candidate topology with duplicated charters or shuffled evidence, preserving coordination overhead but destroying the mechanism |
| G1 | real candidate graph |
| G1-node | G1 with each proposed node removed in turn |
| G1-edge | G1 with each proposed edge removed in turn |

Tasks are paired by repository state and hidden acceptance suite. Claude and
Codex use a balanced provider-role crossover so provider identity cannot
masquerade as an architectural effect. Deterministic paths use replay and
simulation before provider-bearing trials.

Admission is lexicographic:

1. zero authority leakage, containment escape, false-success receipt, secret
   egress, acceptance omission, or artifact-loss regression;
2. verified quality non-inferior to G0;
3. material improvement over G0 and Gcap, or equal quality with reduced provider
   occupancy, context, latency, recovery time, or intervention;
4. node and edge knockouts establish marginal necessity;
5. gains reproduce on held-out task families and a temporal holdout;
6. coordination, context, latency, and local-compute ceilings hold.

Subgroup-only benefit earns a conditional route, not global activation. A
successful trial can request—but cannot emit—an expiring GraphWarrant. The
external Polaris Anchor/admin authority alone issues it, binding graph, contract,
controller/runtime-overlay and revocation digests, eligible workload families,
budgets, estimates, evidence, rollback, expiry, and renewal conditions. Every
use resolves the current protected generation; expiry/revocation closes the
route without falling back to source metadata.

The primary efficiency endpoint is paired verified wins per occupied
provider-minute, reported only after hard gates. No scalar score compensates for
an authority or correctness failure.

### 12.1 Required experiments

1. Base versus Flare versus Flare plus Nebula under equal total budget.
2. Nebula disabled versus enabled.
3. Workspace capacity 8, 16, and 32 under fixed provider and context budgets.
4. One, four, and eight active specialists under fixed total budget.
5. Real charters versus duplicated and shuffled-charter shams.
6. Selective broadcast versus full-context duplication.
7. Automaticity bypass versus mandatory workspace traversal.
8. Relational frames versus flat bags of claims.
9. One-mask-at-a-time removal in simulation only.
10. Poisoned, injected, stale-epoch, and correlated-evidence canaries.
11. Non-mandatory evidence dropout.
12. Flare off/on by Nebula off/on factorial evaluation.
13. Claude/Codex provider-role crossover.
14. Individual knockout of every one of the 60 new GALAXY-core nodes and 155 new
    GALAXY-core edges across this contract and its Pulsar/Quark annexes.
15. Malformed, replayed, stale, oversized, unavailable, and forbidden-payload
    Voyager exchanges while the boundary remains disabled.
16. Optional local J-lens replication on a compatible open-weight model,
    isolated from production admission.

Hard gates are zero paid calls, zero false success, zero authority or context
leakage, zero acceptance omission, verified-quality non-inferiority, and at least
one material hidden-outcome or resource-efficiency gain.

## 13. Existing-feature and brownfield disposition

- Elaborator remains the grounded intent and acceptance-contract compiler.
- Innovator remains a hypothesis emitter feeding Supernova.
- Adversary is a reusable Red Team implementation seam, not a permanent provider.
- Verifier remains deterministic receipt authority and is not the Blue Team.
- Council and Society become selective Flare/Nebula protocols rather than
  always-on provider casts.
- Human Nature Workspace remains an experimental compatibility adapter. Its
  current raw all-specialist broadcast, fixed salience, and silent callback
  failures cannot implement BCW, SBR, BIF, WEC, or WRR.
- AttentionSchema remains a self-observation projection and does not route work
  or count as Nebula.
- Gaia remains a read-only temporal projection.
- Orrery consumes canonical events and graph manifests but cannot write.

The capability topology projects, but does not redefine, the canonical
[brownfield/frontier registry](2026-07-14-galaxy-r3-brownfield-frontier-registry.md):

| Capability concern | Repository IDs | Paper IDs | Qualification use |
|---|---|---|---|
| inspectable harness and typed coordination | BR11, BR13-BR18 | FR22, FR24, FR32, FR34-FR35 | provider-neutral schemas, role ablations, process diagnosis, tool-graph scaling |
| execution isolation | BR19-BR23 | FR26-FR29 | sandbox lifecycle, capability boundary attacks, sealed adversarial execution |
| executable evaluation | BR38-BR39 | FR17-FR25 | stage-level labels, repository tasks, hidden functional/security oracles |
| provenance and non-authoritative telemetry | BR40-BR43 | FR18 | signed artifacts/steps, rotating roots, trace continuity, sanitization |
| planning and selective topology | BR15, BR17 | FR31-FR35 | fixed-compute modularity, hierarchy search, simulated futures, bounded communication |

No row imports a framework topology. A projected mechanism earns a target node or
edge only through Sections 2 and 12, with an incumbent, ablation, held-out result,
resource accounting, and falsifier.

No external provider seat survives in the zero-cost profile. Existing Gemini,
Groq, Cloudflare, Cerebras, or paid API paths must be physically ineligible, not
merely discouraged by prompt or hidden behind post-hoc cost accounting.

## 14. Orrery dashboard contract

The future dashboard renders the full-graph manifest and runtime event stream as
separate truth surfaces:

- structural target count; source-maturity counts for `specified`,
  `implemented_dark`, `retired`, and `unavailable`; and separately resolved
  runtime-overlay counts for `qualified`, `eligible`, and `active` plus any
  explicitly typed runtime availability state;
- current node, epoch, round, cell, provider, lease, causal parents, and
  evidence digest;
- advisory graph visually separated from mutation authority;
- active feedback credit and termination condition;
- every score linked to recomputable evidence;
- Voyager shown as a disabled external federation domain until activated;
- Gaia as a temporal projection over receipts;
- no dashboard-derived writes.

Orrery uses dedicated GET/SSE-only projection DTOs and endpoints. The
complete route, template, and client-script path imports no command, control,
scheduler-writer, execution, or effect surface; no POST handler or control
callback may accept or derive an action from a Orrery DTO.

A single 134-node canvas is not the default view. Orrery provides a
global navigator plus authority, execution, Flare, Nebula, Supernova,
federation, and evidence panels. Complexity remains inspectable rather than
chaotic.

## 15. Architecture-only boundary and implementation order

This document changes target architecture only. It does not claim that the new
nodes are implemented or active. Runtime code remains governed by the
transactional-kernel prerequisite in the parent design and implementation plan.

The companion implementation plans are separate from the kernel plan. Their
authority-safe order is:

1. transactional-kernel completion and exact external controller receipt;
2. machine-readable structural target manifest and static authority/count linter
   implementation (the architecture-time schema and ledgers are already frozen
   in these documents);
3. dark Pulsar transaction domain, trace-only ingestion, cutover schema, and
   rehearsal harness source; no authoritative rehearsal or switch yet;
4. all Quark solver, verifier, integration, activation-validator, and KHA
   adapter source is constructed dark, while only `qualification_only`
   Cepheid-0, shape certificates, independent verification, and bounded DOA may
   execute; no QK11/KHA path. After steps 1-2 this
   isolated work may run in parallel with step 3, but coordinator integration
   and `integration_shadow` wait for step 6's authoritative rehearsal bundle;
5. exact-final external controller activation in dark mode with run ingress
   closed and no scheduler authority switch;
6. an externally anchored `SchedulerCutoverRehearsalBundle` generated by that
   exact active dark controller over copied fixtures, followed by Quark
   `integration_shadow`; QK11 remains closed;
7. an externally issued Pulsar-only, dependency-closed scheduler GraphWarrant,
   followed by a separate scheduling-field TaskState cutover transaction with
   no source mutation;
8. Quark `live_eligible` only after the scheduler switch and an external P4
   transaction that joins one expiring workload-scoped GraphWarrant, protected
   catalog generation, and dependency-closed runtime overlay under a common
   activation binding; every invocation freshly resolves and matches them;
9. typed advisory artifacts and receipt-only shadow instrumentation;
10. Flare deterministic gates and ephemeral cells in shadow mode;
11. Nebula admission, bounded epochs, selective broadcast, and spill/recall;
12. Supernova graph-admission and node/edge knockout harness;
13. disabled Voyager envelope validator and no-op canaries;
14. dependency-closed GraphWarrant-controlled activation of the remaining
    admitted GALAXY subset or full graph; this is not the first scheduler or
    Quark live warrant;
15. dedicated read-only Orrery projection.

Kernel completion is not full GALAXY R3 completion. The world-class claim remains
unearned until the complete architecture passes its matched evidence program.

## 16. Final invariant

GALAXY may grow extremely complex in hypotheses, evidence, specialist transforms,
counterfactuals, recovery paths, and projections.

Only Singularity may grow authority, and only through reviewed typed contracts.

Every other component must remain replaceable, bounded, observable, causally
testable, and removable.
