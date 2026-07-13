# AURA Omega Revision 3: Target Capability Topology and Qualification Contract

> **Date:** 2026-07-13
>
> **Status:** preapproved architecture; runtime implementation remains deferred
>
> **Parent:** [AURA Omega Revision 3](2026-07-13-aura-omega-revision-3-design.md)
>
> **Hard constraints:** at least 105 purpose-distinct AURA-core target nodes and 160 unique typed
> edges; essentially zero incremental external operating cost; no paid API,
> metered hosted inference, or recurring SaaS dependency

## 1. Decision

The exact purpose-distinct target topology contains:

| Layer | Added nodes | Added edges | Cumulative nodes | Cumulative edges |
|---|---:|---:|---:|---:|
| Audited R3 base | - | - | 71 | 95 |
| Spectrum and Aegis admission | 16 | 31 | 87 | 126 |
| Cortex | 21 | 44 | **108** | **170** |
| Disabled Pneuma federation boundary | 3 | 6 | **111** | **176** |

The independent AURA core exceeds the 105-node / 160-edge quota without counting:

- Pneuma internals;
- retries, replicas, provider sessions, or ephemeral runtime instances;
- Chronicle, Constellation, or other presentation labels;
- aliases, placeholders, schema fields, or dormant compatibility wrappers;
- generic awareness, informs, shares, or all-to-all context relationships.

| Truth surface | Current status |
|---|---|
| exact structural target | AURA core 108 / 170; federation-ready 111 / 176 |
| new architecture-contract coverage | 37 / 75 AURA-core overlay plus 3 / 6 disabled Pneuma boundary |
| full graph manifest-qualified count | not reportable until the 71 / 95 base and overlay compile into one validated manifest |
| runtime-qualified and enabled new nodes | zero; every new node remains `specified` |

The graph is complex in capability and sparse in authority. No Spectrum, Aegis,
Cortex, or Pneuma edge enters the mutation-authority spine:

~~~text
RS -> RI? -> TP -> GS -> BI -> OF -> (MG | RC) -> TJ -> TO -> TA -> PA
~~~

## 2. What earns a counted node or edge

The numeric quota applies to purpose-distinct target topology, not boxes in a
diagram. The 71-node / 95-edge base is structurally audited in the parent design
but is not yet claimed as manifest-qualified. The normative rows, inherited
profiles, and exact ledger below provide architecture-contract coverage for the
40-node / 81-edge overlay. Full-graph qualification requires a future
machine-readable manifest and linter over base plus overlay; runtime qualification
then additionally requires implementation receipts and a GraphWarrant.

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
implementation_state
~~~

Implementation state is one of specified, implemented_shadow, eligible,
enabled, retired, or unavailable. Target-topology count and active-runtime count
are always reported separately.

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
~~~

Multiple payload variants between the same ordered pair form one closed tagged
union and count once. Duplicate pairs, dangling endpoints, self-loops, visual
grouping lines, generic context sharing, and unbounded feedback arrows do not
count. A conditional or disabled edge counts only when its eligibility,
terminal behavior, and knockout test are complete.

The topology generator must reject duplicate IDs, duplicate ordered pairs,
missing endpoints, incompatible schemas, authority amplification, and every new
ingress into the mutation spine.

## 3. Name and lifecycle grammar

Names communicate authority rather than decorate it:

| Family | Meaning |
|---|---|
| Omega | trusted authority, policy roots, and mutation kernel |
| Prism | provider, capability, driver, and broker fabric |
| Spectrum | provider-neutral adversarial and resilience protocol |
| Cortex | bounded non-authoritative shared deliberation |
| Crucible | causal experiments, shadow trials, and promotion evidence |
| Chronicle | temporal read-only projection; not counted as authority or capability |
| Constellation | dashboard visualization; not counted as authority |
| Gauntlet | benchmark and certification campaign |
| Aegis | containment and integrity surfaces |
| Lattice | evidence and causal-relation projections |
| Relay | selective typed broadcast |

Stable service names are permanent. A Team is a stable charter. A Cell is one
ephemeral charter execution. Provider identity is orthogonal: Claude, Codex,
Ollama, or a deterministic local algorithm may service an eligible role without
changing that role's node identity or authority.

The current Omega-protected provider universe is exact: the user's existing
local Claude Code CLI and Codex CLI subscription surfaces, optional already-local
Ollama inference for reflex/draft work, and deterministic local algorithms. B
binds provider ID, driver/mode, executable and installation digests, credential
surface, billing class (`preowned_local_cli` or `local_compute`), and permitted
role into every sublease. No API provider, free trial, promotional credit, or
“currently zero price” route is eligible, and there is no fallback outside the
allowlist. Revoking Ollama or either CLI requires a new protected generation;
it does not change graph identity.

## 4. Capability overlay

This diagram shows every overlay edge, not all 111 target nodes.

~~~mermaid
flowchart LR
    OA["Omega Anchor and protected policy generation"] --> SCT["Spectrum Charter Registry"]
    OA --> CCR["Consumer Contract Registry"]
    OA --> AAG["Advisory Admission Gate"]
    R["Prism Router"] --> CME["Capability Mesh Snapshot"]
    B["Zero-cost Capacity Leases"] --> CME

    G["Mission DAG"] --> SIN["Spectrum Intake"]
    M["Evidence-scoped Memory"] --> SIN
    E["Evidence Graph"] --> SIN
    SIN --> SVG["Spectrum Value Gate"]
    V["Value-of-information Planner"] --> SVG
    SCT --> SVG
    CME --> SVG
    SVG -->|"admitted initial round request"| SCG
    B -->|"bounded zero-cost round lease bundle"| SCA["Spectrum Cell Assembler"]

    SCA --> DIF["Disclosure Ingress Firewall"]
    DIF --> RED["Red Cell"]
    DIF --> ORG["Orange Cell"]
    DIF --> BLU["Blue Cell"]
    DIF --> GRN["Green Cell"]
    RED & ORG & BLU & GRN --> SOF["Structured Output Firewall"]
    SOF --> CXR["Contradiction Exchange"]
    CXR --> SCG["Spectrum Convergence Gate"]
    SCG -->|"atomic initial or next-round lease request"| B
    SCG --> SAB["Spectrum Advisory Bundle"]
    SAB --> AAG
    AAG --> K["AURA Controller"]
    SAB --> E
    E --> COR["Cell Outcome Resolver"]
    COR --> E

    G --> CQC["Cortex Query Compiler"]
    M --> CQC
    CQC --> ABG{"Automaticity hypothesis / deterministic bypass gate"}
    ABG -->|"deterministic or already resolved"| R
    ABG -->|"unknown or deliberate"| WEC["Workspace Epoch Controller"]
    ABG --> WRR["Workspace Receipt Recorder"]
    WEC --> CCL["Cortex Capacity Ledger"]
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
    WAO --> BCW["Bounded Cortex Workspace"]
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

    BCW --> CSC["Cortex Synthesis Compiler"]
    CXR --> CSC
    CSC --> SCG
    SCG -->|"new evidence required"| WEC

    CSC --> WRR
    WRR --> E
    WRR --> WIP["Workspace Intervention Planner"]
    CR["Crucible"] --> WIP
    WIP --> CFR["Counterfactual Frame Runner"]
    BCW --> CFR
    CFR --> WOC["Workspace Outcome Comparator"]
    WOC --> CR
    WOC --> WRR

    EG["Brokered external-effect gateway"] --> PFG["Pneuma Federation Gate - specified / disabled"]
    RA["Run Admission Authority"] --> PFG
    PFG --> PXB["Pneuma Exchange Broker"]
    PXB --> PEA["Pneuma Evidence Adapter"]
    PEA --> E
    PA["Protected purpose outcome archive"] -->|"post-terminal outcome only"| PFG
~~~

## 5. Spectrum and Aegis admission: 16 architecture-qualified nodes

Spectrum is advisory and provider-neutral. Agreement cannot create a verifier
pass, lease, promotion receipt, recovery authority, or canonical mutation.

| ID | Name | Distinct contract and lifecycle |
|---|---|---|
| SCT | Spectrum Charter Registry | Permanent protected charter generation. Exposes versioned Red, Orange, Blue, and Green contracts from an attenuated Omega policy reference. |
| SIN | Spectrum Intake | Per-decision intake snapshot over mission, evidence, and memory references. Terminates admitted, bypassed, blocked, or unavailable. |
| SVG | Spectrum Value Gate | Deterministic VOI and eligibility gate. Emits an initial-round admission request binding exact charter, capability, evidence, and budget digests; SCG must consume a round credit and only base node B can reserve capacity. |
| CME | Capability Mesh Snapshot | Immutable recomputable intersection of Prism eligibility and current zero-cost capacity. It never selects a provider or mints a lease. |
| SCA | Spectrum Cell Assembler | Per-round cell instantiation from one B-issued zero-cost bundle containing disjoint per-color subleases. It cannot bypass SVG, SCG, B, or create capacity. |
| DIF | Disclosure Ingress Firewall | Fail-closed Aegis parser that converts exact mission/evidence references into provider-safe closed briefs; rejects secrets, prompt injection, hidden-reasoning requests, and unconstrained text. |
| RED | Red Cell | Adversarial falsification, exploit search, assumption attack, and failure construction. |
| ORG | Orange Cell | Converts challenges into minimized reproducers, kill tests, executable canaries, and discriminating counterexamples. |
| BLU | Blue Cell | Audits containment, invariants, provenance, observability, context independence, and defensive gaps. |
| GRN | Green Cell | Converts defensive findings into recovery, hardening, resilience, and operability proposals. |
| SOF | Structured Output Firewall | Fail-closed Aegis parser, schema validator, provenance binder, and redactor immediately after every provider cell. Only sanitized typed claims and immutable evidence references leave it. |
| CXR | Contradiction Exchange | Protected bounded per-round fan-in and typed comparison of sanitized cell results. It binds the admitted-color/sublease set, closes exactly once after every member is terminal or the deadline expires, and never routes directly back to a cell. |
| SCG | Spectrum Convergence Gate | Sole owner of monotone round credits. Decides admit initial round, continue, converge, exhaust, abstain, unavailable, or cancel; each admitted round requests a fresh atomic B lease bundle. |
| SAB | Spectrum Advisory Bundle | Immutable terminal materialization of proposals, dissents, evidence, uncertainty, and unresolved obligations. |
| AAG | Advisory Admission Gate | Protected deterministic Aegis gate. Accepts only closed, mission-bound advisory fields under Omega policy and strips all controller, provider, lease, effect, acceptance, verifier, and mutation fields before K can read the reference. |
| COR | Cell Outcome Resolver | Post-terminal deterministic join of cell predictions to later outcome receipts for calibration and causal credit. It cannot reopen the current run. |

Each color emits typed claims, evidence references, uncertainty, abstention, and
falsifiers. Raw private reasoning and provider transcripts are not graph payloads.

## 6. Cortex: 21 architecture-qualified nodes

Cortex is a bounded typed-artifact workspace. It is not a model, consciousness
claim, raw transcript bus, truth store, verifier, or authority tier.

| ID | Name | Distinct contract and lifecycle |
|---|---|---|
| CQC | Cortex Query Compiler | Compiles a decision-scoped query with acceptance obligations, stop conditions, and exact causal coordinates. |
| RFB | Relational Frame Binder | Represents subject, predicate, object, argument roles, evidence, contradictions, and unresolved bindings rather than a bag of concepts. |
| CIG | Context Integrity Gate | Rejects invalid provenance, injection, staleness, shared-lineage contamination, and correlation violations. |
| PBG | Phase Boundary Gate | Applies temporal, causal, scope, lifecycle, and disclosure masks. It cannot grant or revoke Omega action authority. |
| CLE | Cognitive Load Estimator | Predicts marginal slot, context, provider-time, latency, and intervention load. It owns no capacity. |
| WAO | Workspace Admission Optimizer | Selects eligible frames under a fixed permit and records admit, defer, evict, or abstain decisions. |
| CCL | Cortex Capacity Ledger | Owns only workspace-local slot, byte/token, epoch, and intervention sub-reservations inside an existing run envelope. It cannot reserve provider time or mint a B lease. |
| WEC | Workspace Epoch Controller | Creates immutable epochs and exclusively controls bounded recurrence and termination. |
| BCW | Bounded Cortex Workspace | Owns run-scoped ephemeral versioned advisory slots with evidence and contradiction references. |
| CCR | Consumer Contract Registry | Permanent protected typed subscription and disclosure policy generation. |
| SBR | Selective Broadcast Router | Sends only the minimum contract-compatible workspace subset to each subscriber. |
| BIF | Broadcast Independence Firewall | Prevents shared-provider, shared-session, shared-evidence, or derivation-correlated outputs from masquerading as independent support. |
| ABG | Automaticity Hypothesis / Deterministic Bypass Gate | Lets only deterministic or already-resolved work bypass Cortex with an immutable receipt. Unknown classification fails toward bounded deliberation. It cannot infer model-internal automaticity or bypass acceptance and mutation gates. |
| SSP | Structured Spillway | Externalizes evicted, superseded, or currently irrelevant noncritical atoms as content-addressed TTL artifacts. |
| SRB | Spillway Recall Broker | Performs bounded policy-approved recall and readmission by immutable reference. |
| WSM | Workspace Saturation Monitor | Detects occupancy, stagnation, repeated digests, and backpressure; proposes spill, synthesis, or termination. |
| CSC | Cortex Synthesis Compiler | Produces a typed advisory synthesis while preserving dissent, hard constraints, uncertainty, and unresolved obligations. |
| WRR | Workspace Receipt Recorder | Appends mask, admission, broadcast, use, eviction, synthesis, bypass, and intervention lifecycle receipts. |
| WIP | Workspace Intervention Planner | Compiles a preregistered bounded intervention only from a Crucible-issued assignment warrant; it cannot assign treatment or self-authorize execution. |
| CFR | Counterfactual Frame Runner | Executes only Crucible-authorized read-only simulation or isolated counterfactual frames. |
| WOC | Workspace Outcome Comparator | Emits paired measurements and uncertainty; Crucible retains causal inference and promotion recommendation. |

Workspace priority is not truth, confidence, acceptance, or authority. Every
Cortex output remains an immutable advisory reference consumed through an
existing authoritative gate.

### 6.1 Pneuma boundary: 3 architecture-qualified nodes

| ID | Name | Distinct contract and lifecycle |
|---|---|---|
| PFG | Pneuma Federation Gate | Specified and disabled fail-closed gate that consumes both a replay-only effect capability from EG and a normal-run federation warrant from RA. It cannot mint either authority. |
| PXB | Pneuma Exchange Broker | Separate-process, operation-allowlisted, OS-authenticated replay broker. It owns one bounded exchange transaction and exposes no general Pneuma package, shell, filesystem, network, training, or RSI surface. |
| PEA | Pneuma Evidence Adapter | Receiver-side closed-schema validator and transitive-taint adapter. It can append a namespaced shadow observation only; it cannot resolve evidence, issue commands, or affect acceptance. |

### 6.2 Normative node-contract completion profile

The row above for each overlay node is normative, not descriptive shorthand. It
combines with this profile to instantiate every `QualifiedTopologyNode` field:

- `contract_version` is `aura.node.<lowercase-node-id>/v1`;
- `typed_input_schemas` and `typed_output_schemas` are exactly the incident
  versioned schemas in Section 7, each named
  `aura.payload.<lowercase-schema-name>/v1`;
- `observable_consumer_decision_effect` is the row's distinct contract plus its
  outgoing ledger schema; no unlisted effect is permitted;
- `ablation_key` is `node:<ID>:disabled` and the mandatory removal path is the
  matched G0 route, an explicit abstention, or unavailable -- never an implicit
  substitute node;
- `implementation_state` is `specified`; none is eligible or enabled;
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
| `replay_effect_gate` | PFG | conjoin and consume PN01/PN02; no effect creation |
| `replay_effect_executor` | PXB | execute only the one EG-authorized local replay operation |

DIF, SOF, AAG, SVG, SCG, SCT, CCR, CIG, PBG, BIF, CXR, WEC, CCL, SRB, PFG,
PEA, and Crucible's assignment/intervention-credit validator are reference
monitors or monotone state owners in the manifest-attested external controller TCB. Their full
executable, interpreter, native/library dependency, schema, and policy digests
bind to the active Omega generation and an independently checked downstream
attestation receipt. Candidate repository code can neither implement nor
configure them. PXB runs in its separately restricted capsule described in
Section 11.

| Lifecycle profile | Nodes | Activation and terminal lifecycle | State owner | Ceiling and timeout | Failure terminal |
|---|---|---|---|---|---|
| protected registry | SCT, CCR | protected generation change; active until superseded by a newer valid Omega generation | SCT owns charter versions; CCR owns consumer policies | 64 KiB generation, 2 s deterministic validation | retain LKG only when OA attests the same current unrevoked generation; any advance, revocation, or uncertainty is unavailable |
| decision transform | SIN, SVG, CME, SCA, DIF, SOF, SAB, AAG, COR, CQC, RFB, CIG, PBG, CLE, WAO, SBR, BIF, ABG, WSM, CSC, WIP, CFR, WOC, PEA | one exact run/decision/phase activation; terminates emitted, bypassed, rejected, abstained, unavailable, cancelled, or expired | explicitly stateless; outputs are immutable artifacts | one in-flight activation, 64 KiB input and output, 5 s local deterministic work; CFR additionally obeys its Crucible warrant | no output plus one bounded failure receipt |
| provider cell | RED, ORG, BLU, GRN | one accepted round under one named single-use sublease in a B bundle; terminates emitted, abstained, unavailable, cancelled, or lease-expired | explicitly stateless; provider session is not graph state | one provider process, 128 KiB sanitized input, 64 KiB typed output, 900 s or earlier B deadline | sublease closes; no automatic retry |
| bounded run state | SCG, CXR, CCL, WEC, BCW, SSP, SRB, WRR | one run-scoped state machine; closes at its exact terminal, run deadline, cancellation, or credit exhaustion | SCG owns round credits; CXR per-round admitted-color join barriers; CCL local sub-reservations; WEC epochs; BCW slots; SSP TTL refs; SRB recall credits; WRR append-only receipts | 32 slots, 4 epochs, 4 rounds, 8 recalls, 3 interventions, 8 MiB total artifacts, never beyond run deadline | CAS to exhausted, cancelled, or unavailable |
| disabled federation | PFG, PXB | disabled until a GraphWarrant; then one purpose-bound replay transaction | PFG owns kill-switch/capability consumption; PXB owns nonce/dedupe transaction state | one in flight, one retry only before effect acknowledgement, 256 KiB cumulative transfer, 60 s | unavailable audit receipt and zero replay effect |

Any node-specific row is a stricter override. A future manifest compiler must
materialize these inherited values per node and fail on an omitted, widened, or
ambiguous field; inheritance is forbidden at runtime.

## 7. Exact unique edge ledger

Every row below has one ordered pair and one named closed payload. The manifest
contains no duplicate ordered pair.

The following inherited profile completes every architecture-time edge
contract. `contract_version` is `aura.edge.<lowercase-edge-id>/v1`; endpoint
versions are the Section 6 node versions; the payload version is
`aura.payload.<lowercase-schema-name>/v1`; and the ablation key is
`edge:<ID>:disabled`. Every payload uses a closed envelope containing only edge,
graph, source/target contract, run, mission, attempt, base revision, epoch,
phase, authority, provenance, causation, idempotency, expiry, artifact-kind,
artifact-digest, and one content-addressed typed artifact reference. A field-level
artifact schema is mandatory before runtime qualification; an unknown field or
schema version fails closed.

Default activation requires an enabled GraphWarrant, matching endpoint and
schema digests, an unexpired same-run upstream receipt, valid phase, and an
unused idempotency key. Default authority is `advisory_reference`; it cannot be
amplified by a target. Provenance and taint are transitive. Replay returns the
same receipt without re-execution. Default expiry is the earliest of 15 minutes,
the source artifact expiry, and run deadline. Default queue ceiling is one
in-flight item per edge/run/purpose and 64 KiB; timeout emits one unavailable
receipt and no target activation.

| Override profile | Edges | Additional rule |
|---|---|---|
| protected generation | SP01, SP27, CT01 | requires the exact current OA generation and carries policy reference only |
| provider capacity | SP11, SP12, SP24 | SP11 is admission into SCG; SP24 is the sole B CAS request; only SP12 carries a bounded bundle of disjoint single-use B subleases; stale snapshots never authorize execution |
| bounded color fan-in | SP22, SP23 | SP22 accepts exactly one terminal variant per admitted color/sublease; CXR closes once at complete set or deadline, records missing terminals, and only then emits SP23 |
| bounded recurrence | SP24, CT08, CT28 | must carry proof that the sole protected owner atomically consumed the applicable CyclePermit credit before delivery and advanced the round, epoch, or recall count |
| bounded epoch request | CT30, CT34 | consumes one separate epoch-request credit and changes no epoch-transition credit or index; WEC may reject, and CT08 is the sole epoch transition |
| local capacity CAS | CT07, CT18, CT19 | workspace-local only; commit/release is monotone and cannot trigger provider work |
| post-terminal resolution | SP30, SP31, PN06 | requires protected terminal state and cannot reopen or recursively re-enqueue a resolved claim |
| Crucible intervention | CT38 through CT43 | requires one Crucible assignment warrant, fixed treatment/control IDs, and one intervention credit |
| Pneuma effect | PN01 through PN05 | disabled by default; PN01 is replay-only EG effect authority, PN02 normal-run admission, and PN03 their attenuated conjunction |

`causal_epoch_and_phase_rule` uses the following closed profiles. A payload from
another run, a future phase, a closed epoch, or an unlisted transition is invalid.

| Phase profile | Edges | Exact relation |
|---|---|---|
| `P0_PROTECTED_GENERATION` | SP01, SP27, CT01 | no run epoch; exact current OA generation only |
| `S0_INTAKE` | SP02-SP11 | same run, `epoch=0`, `round=0`; SP11 may request SCG admission but cannot advance round |
| `S1_ROUND_OPEN` | SP24, SP12 | SCG first CAS-advances `round r` to `r+1` and decrements one credit; SP24 requests and SP12 delivers the B bundle for exactly `r+1` |
| `S2_ROUND_BODY` | SP13-SP23 | same run and exact open round; SP23 closes collection for that round |
| `S3_TERMINAL_ADVISORY` | SP25-SP26, SP28-SP29 | same run after SCG terminal decision; no new round/epoch; SP27 remains protected-generation policy input |
| `S4_POST_TERMINAL_RESOLUTION` | SP30-SP31 | only after protected run terminal; same claim/outcome key; cannot reopen run |
| `C0_DECISION_CONTROL` | CT02-CT07, CT44 | same run and decision; CT06/CT07 target candidate epoch `e+1` without opening it |
| `C1_EPOCH_OPEN` | CT08 | WEC sole CAS from open/current `e` to `e+1`, consuming exactly one epoch credit after local budget succeeds |
| `C2_EPOCH_BODY` | CT09-CT27, CT29, CT31-CT33, CT35-CT36 | same run and exact immutable open epoch `e`; no index advance |
| `C2_RECALL_DELIVERY` | CT28 | same epoch `e`; SRB CAS-consumes exactly one recall credit before delivery |
| `C2_NEXT_EPOCH_REQUEST` | CT30, CT34 | same epoch `e`, targets `e+1`; protected dispatch/WEC tombstones a deterministic request key and consumes one request credit before acceptance, but only CT08 can consume an epoch-transition credit or advance the index |
| `C3_SHADOW_EXPERIMENT` | CT37-CT43 | separate Crucible experiment ID after eligible WRR receipt; fixed assignment and no current-run action authority |
| `F0_FEDERATION_REQUEST` | PN01-PN02 | same admitted purpose and Omega generation; neither starts an exchange alone |
| `F1_FEDERATION_EXCHANGE` | PN03-PN05 | PFG CAS-opens one exchange ID; all messages bind that ID and close on PN05 or failure |
| `F2_OUTCOME_FEEDBACK` | PN06 | later PA terminal receipt only; cannot start replay and may condition only a fresh F0/F1 transaction |

### 7.1 Spectrum and Aegis edges: 31

| ID | Source | Target | Closed payload schema |
|---|---|---|---|
| SP01 | OA | SCT | ProtectedCharterGenerationRef |
| SP02 | R | CME | ProviderEligibilitySnapshot |
| SP03 | B | CME | ZeroCostCapacitySnapshot |
| SP04 | G | SIN | MissionRef |
| SP05 | M | SIN | RetrievedEvidenceRefs |
| SP06 | E | SIN | TrustTieredEvidenceDelta |
| SP07 | SIN | SVG | SpectrumRequest |
| SP08 | V | SVG | ValueOfInformationBudget |
| SP09 | SCT | SVG | CharterConstraints |
| SP10 | CME | SVG | EligibleProviderCapacityMatrix |
| SP11 | SVG | SCG | SpectrumInitialRoundAdmissionRequest |
| SP12 | B | SCA | BoundedSpectrumRoundLeaseBundle |
| SP13 | SCA | DIF | CellBriefBundle |
| SP14 | DIF | RED | SanitizedFalsificationBrief |
| SP15 | DIF | ORG | SanitizedCounterexampleBrief |
| SP16 | DIF | BLU | SanitizedIntegrityBrief |
| SP17 | DIF | GRN | SanitizedResilienceBrief |
| SP18 | RED | SOF | FalsificationResult |
| SP19 | ORG | SOF | ReproducerCanaryResult |
| SP20 | BLU | SOF | IntegrityAuditResult |
| SP21 | GRN | SOF | ResilienceResult |
| SP22 | SOF | CXR | SanitizedCellResultUnion |
| SP23 | CXR | SCG | RoundStateAndContradictionSet |
| SP24 | SCG | B | SpectrumNextRoundLeaseCASRequest |
| SP25 | SCG | SAB | SpectrumTerminalDecision |
| SP26 | SAB | AAG | AdvisoryCandidateBundle |
| SP27 | OA | AAG | ProtectedAdvisoryAdmissionPolicy |
| SP28 | AAG | K | AttenuatedMissionAdvisoryRef |
| SP29 | SAB | E | TaintedAdvisoryObservationRef |
| SP30 | E | COR | TerminalClaimJoinRequest |
| SP31 | COR | E | CellResolutionReceipt |

SCT and CME do not connect directly to SCA. SVG asks SCG to admit the initial
round; SCG consumes a round credit and SP24 asks B to reserve atomically. Only
SP12 can instantiate a round. A continuation must pass CXR, SCG, SP24, and B
before SCA sees a fresh bundle. AAG accepts no free text and SP28 cannot alter
controller configuration, routing, leases, effects, acceptance, verification,
promotion, recovery, or mutation fields.
SP12 contains an explicit admitted-color set and one disjoint sublease per
admitted color, with aggregate capacity reserved atomically by B. SCA/DIF emit
SP14-SP17 only for tagged members of that set. Each emitted brief binds its own
unconsumed sublease ID and physically zero-cost provider allowlist, and that
color cell atomically consumes only its sublease before launch. A stale CME
snapshot, absent branch tag, duplicate sublease, or sanitized brief has no
execution authority.

Each admitted sublease must terminate as `emitted`, `abstained`, `unavailable`,
`cancelled`, or `expired`. SOF validates normal results; for loss before provider
output, the protected dispatcher supplies only the signed B/sublease terminal
receipt, never synthetic claims. CXR opens one barrier keyed by
`(run, round, admitted_color_set_digest, lease_bundle_id)`, CAS-deduplicates one
SP22 terminal per member, and emits SP23 exactly once when the set is complete or
the round deadline closes it with explicit missing terminals. Arrival order can
change neither the bundle nor SCG's decision input.

### 7.2 Cortex edges: 44

| ID | Source | Target | Closed payload schema |
|---|---|---|---|
| CT01 | OA | CCR | ProtectedConsumerPolicyGenerationRef |
| CT02 | G | CQC | MissionNodeRef |
| CT03 | M | CQC | RetrievalSnapshotRef |
| CT04 | CQC | ABG | WorkspaceQuery |
| CT05 | ABG | R | FastPathRouteRecommendation |
| CT06 | ABG | WEC | DeliberateEpochRequest |
| CT07 | WEC | CCL | EpochBudgetReservation |
| CT08 | WEC | CQC | EpochOpenOrRefreshReceipt |
| CT09 | SIN | RFB | SpectrumCandidateBundle |
| CT10 | CXR | RFB | ContradictionRelationSet |
| CT11 | CQC | RFB | WorkspaceQuery |
| CT12 | RFB | CIG | RelationalFrame |
| CT13 | CIG | PBG | IntegrityEligibleFrame |
| CT14 | CIG | WRR | IntegrityQuarantineReceipt |
| CT15 | PBG | CLE | PhaseMaskedFrame |
| CT16 | PBG | WRR | PhaseRejectionReceipt |
| CT17 | CLE | WAO | CalibratedLoadForecast |
| CT18 | CCL | WAO | AvailableSlotReceipt |
| CT19 | WAO | CCL | CapacityCommitOrRelease |
| CT20 | WAO | BCW | WorkspaceAdmissionReceipt |
| CT21 | BCW | SBR | SealedWorkspaceFrame |
| CT22 | CCR | SBR | ConsumerContractSnapshot |
| CT23 | SBR | BIF | TargetedBroadcastEnvelope |
| CT24 | BIF | SCA | SanitizedCellInputEnvelope |
| CT25 | CXR | SSP | TypedUnbroadcastIntermediate |
| CT26 | SSP | SRB | TimeBoundSpillRef |
| CT27 | CQC | SRB | RecallQuery |
| CT28 | SRB | SIN | ReadmissionCandidate |
| CT29 | BCW | WSM | WorkspaceOccupancySnapshot |
| CT30 | WSM | WEC | SaturationOrStagnationSignal |
| CT31 | BCW | CSC | GroundedWorkspaceFrame |
| CT32 | CXR | CSC | BoundedContradictionBundle |
| CT33 | CSC | SCG | SynthesisCandidate |
| CT34 | SCG | WEC | MoreEvidenceEpochRequest |
| CT35 | CSC | WRR | SynthesisTraceReceipt |
| CT36 | WRR | E | TaintedWorkspaceObservationReceipt |
| CT37 | WRR | WIP | InterventionEligibleTrace |
| CT38 | CR | WIP | ExperimentPolicyAssignmentAndCreditWarrant |
| CT39 | WIP | CFR | PreregisteredInterventionPlan |
| CT40 | BCW | CFR | CleanControlFrame |
| CT41 | CFR | WOC | PairedShadowOutcomes |
| CT42 | WOC | CR | CausalEffectUncertaintyReceipt |
| CT43 | WOC | WRR | InterventionOutcomeReceipt |
| CT44 | ABG | WRR | BypassOrDeliberateDecisionReceipt |

SCG to SAB belongs to Spectrum edge SP25 and is intentionally absent here.
CT24 is non-activating supplemental input and must bind an already accepted
SP12 lease; SP12 remains the sole SCA activation edge. CT36 is observation-only
and inherits the evidence taint rules in Section 7.4.

### 7.3 Pneuma federation edges: 6

The three boundary nodes are architecture-qualified but disabled by default. Pneuma's
internal graph is separately governed and excluded from AURA's count.

| ID | Source | Target | Closed payload schema |
|---|---|---|---|
| PN01 | EG | PFG | ReplayOnlyPneumaEffectCapability |
| PN02 | RA | PFG | AttenuatedFederationWarrant |
| PN03 | PFG | PXB | PneumaFederationLease |
| PN04 | PXB | PEA | PneumaResponseEnvelope |
| PN05 | PEA | E | TaintedPneumaShadowObservation |
| PN06 | PA | PFG | ProtectedTerminalOutcomeFeedback |

### 7.4 Evidence trust and taint

E is one canonical graph with non-interchangeable partitions, not one flat trust
bucket. `authoritative_outcome` accepts only protected F/PA/verifier receipt
ancestry. `advisory_observation` accepts SP29, CT36, and PN05 while retaining the
full transitive source closure and can never satisfy acceptance, verification,
promotion, or a resolved claim. `resolution_receipt` records COR/Crucible joins
without upgrading their source material.

SP06 is a closed tagged union. Its `resolved` variant requires authoritative
outcome ancestry. Its `advisory_shadow` variant may create deliberation pressure
only, remains tainted through SIN/Cortex/Spectrum, and cannot contribute an
independent-support count. Content, agreement, repetition, or passage through a
workspace never changes trust tier. Crucible may promote a routing, memory, or
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
CCL workspace-local reservations, Crucible intervention assignment/credits, B
provider capacity, SRB recall credits, and PFG federation transaction nonces. No
consumer can mint or replenish its upstream permit.

SCG initializes `current_round=0` and `remaining_round_credits<=4`. Both initial
SP11 admission and a continuation require SCG to CAS
`current_round += 1; remaining_round_credits -= 1` before SP24, so the cap is four
total rounds, not one plus four. WEC analogously initializes `current_epoch=0`
and at most four epoch credits plus eight run-wide/two-per-epoch request credits.
Each CT30/CT34 request key is deterministically derived from `(run, epoch,
request_kind, evidence_or_challenge_digest)`; WEC persists an accept/reject
tombstone and CAS-consumes one request credit before accepting the edge. A key
cannot be retried and an epoch cannot accept more than two such requests. WEC
performs the sole epoch-transition CAS before CT08. SRB initializes at most eight
recall credits and CAS-consumes one before every CT28 delivery.

| Cycle | Distinct messages | Termination |
|---|---|---|
| SVG or CXR to SCG to B to SCA to cells to CXR | admission/contradiction set / round CAS request / disjoint B sublease bundle / sanitized result | SCG CAS consumes one credit before every SP24; default two total rounds, hard cap four total, same-digest stop; no direct CXR-to-cell edge |
| CCL and WAO | local CapacityGrant / AtomicReservationCommit | CCL CAS owns monotone reserve-commit-release state; no provider capacity and no recursive event trigger |
| WEC pipeline | EpochPermit / SaturationSignal / EvidenceRequest | WEC CAS consumes before CT08; default two epochs, hard cap four, new evidence or material contradiction required |
| E and COR | TerminalClaimJoinRequest / idempotent CellResolutionReceipt | E owns pending-to-resolved-or-unresolved CAS; one join per claim/outcome digest; SP31 receipts are origin-excluded from SP30 |
| SSP to SRB to SIN | SpillRef / RecallQuery / ReadmissionCandidate | one readmission per evidence digest and eight total per run; TTL and stale-source rejection |
| WRR to WIP to CFR to WOC to CR | assignment warrant / plan / paired outcome / causal receipt | Crucible fixes treatment/control before WIP; default one intervention, hard cap three; an outcome cannot trigger the same assignment ID |
| EG/RA to PFG to PXB to PEA to E, then later PA to PFG | effect capability / federation warrant / response / shadow observation / protected outcome | one nonce and purpose CAS, one pre-ack retry, no post-ack replay; PN06 accepts only a PA terminal receipt plus transitive origin closure |

PN06's closed union has two variants. `IndependentControlOutcome` proves no
Pneuma ancestry. `TreatedOutcomeLabel` lists the exact Pneuma exchange ancestry,
is label-only for preregistered shadow metrics, and is prohibited from returning
through PN04 as evidence. Neither variant can support the same or a descendant
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

| Paper evidence and claim location | AURA engineering hypothesis |
|---|---|
| query/key/value weighted retrieval, Sections 3.2.1-3.2.2 | unresolved typed DecisionQuery over canonical scope/capability/provenance keys and immutable evidence/proposal references |
| parallel heads at similar total compute, Sections 3.2.2 and 6.2 Table 3(A) | independently chartered projections tested at 1, 4, and 8 roles under the same total Claude/Codex/context budget |
| decoder future-position mask only, Sections 3.1 and 3.2.3 | physically enforced phase, authority, contamination, lifecycle, and scope masks; their safety comes only from contracts and adversarial tests |
| additive residual connections, Section 3.1 | an independent hard-fact/constraint channel that attention priority cannot erase; immutability is an AURA invariant, not a paper result |
| positional encoding, Section 3.5 | explicit run revision, base SHA, transaction, epoch, round, journal position, and causal parents |
| position-wise feed-forward transform, Section 3.3 | narrow local specialist transform after relational retrieval |
| dense evaluated attention and restricted attention proposed only as future work, Section 4 | sparse typed neighborhoods are an AURA cost/security hypothesis, not a demonstrated Transformer result |

The paper establishes machine-translation and constituency-parsing results, not
autonomous-agent topology. Its fixed-compute head ablation is non-monotonic:
single-head quality is worse, but too many heads also hurt, so more graph roles
receive no presumption of benefit. Separately, AURA selects sparse routing as an
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

**AURA hypotheses, not paper findings:** provider-neutral specialists working on
private briefs; typed competitive admission; targeted consumer subscriptions;
recurrent immutable epochs; relational frames; correlation-aware independence;
security and disclosure masks; explicit capacity accounting; and selective
broadcast outside a model. RFB, WEC, BIF, CIG, PBG, CCL, WSM, SBR, WRR, WIP,
CFR, and WOC exist to test those hypotheses rather than cite them into truth.
ABG bypasses only deterministic or already-resolved work; unknown classification
fails toward bounded deliberation, and “automaticity” remains an experimental
label.

The engineered Cortex is not Claude's or Codex's internal J-space, is not access
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
local research annex and enters Crucible only as fallible evidence, never as a
verifier, monitor, consciousness claim, or authority gate.

### 10.1 Research transfer records

All records expire on 2027-01-09 or earlier if the source, local model, license,
or relevant AURA contract changes. Expiry means re-review, not automatic renewal.

| ID | Pinned claim location | AURA hypothesis | Preregistered falsifier |
|---|---|---|---|
| TR01 | Transformer v7, Sections 3.2.1-3.2.2 and 6.2 Table 3(A) | typed Q/K/V retrieval and multiple independent charters can improve decisions | equal-budget 1/4/8-role trial shows no held-out gain or a sham charter matches the real mechanism |
| TR02 | Transformer v7, Sections 3.1, 3.2.3, 3.5, and 4 | explicit ordering, an independent constraint channel, and sparse hard masks reduce contamination without losing quality | one-mask removal has no signature, constraint can be erased, or sparse routing loses hidden quality at equal budget |
| GW01 | Global Workspace paper, “A global workspace in language models,” “The J-space acts as a Global Workspace,” and “The J-space's structure supports its function” | a bounded selective artifact workspace can improve flexible multi-step agent decisions | matched no-workspace/full-context controls win, causal frame swaps do not mediate output, or simple-task overhead regresses |
| GW02 | Global Workspace paper, “Limitations and open questions” and “Notable differences from human cognition” | AURA's typed specialists, targeted broadcast, relational binding, and immutable epochs repair useful limits in an external orchestration setting | flat claims, untargeted broadcast, or feed-forward-only controls match the real mechanism under equal resources |
| JL01 | jacobian-lens commit `581d398613e5602a5af361e1c34d3a92ea82ba8e`; README “Apply,” “Fit,” and “License and data”; `jlens.fitting.fit`, `jlens.fitting.jacobian_for_prompt`, and `jlens.lens.JacobianLens.apply` | an optional local replication may generate useful interpretability hypotheses | no license-compatible local model/corpus, replication instability, prohibitive local cost, or no downstream Crucible value |

Every transfer now binds revision, claim location, hypothesis, falsifier,
experiment family, and expiry. Inspiration without a falsifiable transfer record
is complexity theatre.

## 11. Pneuma federation contract

Pneuma receives an architectural port, not operational integration.

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

Therefore PFG, PXB, and PEA remain specified and disabled. Pneuma output is
`advisory_shadow`; invoking even a local replay is correctly classified as a
brokered external-computation effect, not hidden inside “advisory only.”

### 11.1 Semantic crosswalk

| Pneuma required edge ID | AURA realization |
|---|---|
| nine_to_five_snapshot_to_pneuma_trace | existing K-to-EG request; PN01 replay-only effect capability, conjoined with PN02, then transmitted under PN03 |
| pneuma_trace_to_replay | purpose-bound, operation-allowlisted PXB transaction returning through PN04 |
| replay_outputs_to_shadow_log | PN04 then PN05 as a namespaced append-only shadow record |
| shadow_log_to_advisory_pressure | SP06 `advisory_shadow` variant into SIN; taint remains transitive and no new edge is counted |
| advisory_pressure_to_authority_gated_action | SP26 to AAG, then attenuated SP28 into K, followed by all normal AURA gates |
| realized_outcome_to_pneuma_feedback | PA-sourced PN06 may condition a fresh stateless `outcome_conditioned_replay_v1`; it never writes Pneuma state and requires fresh PN01, PN02, and PN03 authority |

### 11.2 Mandatory federation envelope

Every request and response binds:

~~~text
protocol_id and version
schema digest
message, correlation, causation, and idempotency IDs
single-use nonce, capability ID, issuer generation, and channel binding
issuer repository ID, source commit, process-image digest, and executable digest
OS peer principal/SID, named-pipe identity, and ACL digest
canonical Pneuma edge ID
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
image and operation allowlist. PFG consumes anchor-bound single-use PN01 and PN02
capabilities; PXB never accepts a shell command, module name, arbitrary method,
path, URI, or caller-supplied executable. Only `aura-evidence-sha256` references
resolvable inside AURA's content-addressed evidence store are valid requests.
Only the closed replay-summary schema can return. Booleans in the sender envelope
are not trusted: both PXB and PEA enforce content type, reference scheme,
provenance, taint, cumulative bandwidth, and decode limits independently.

PXB is launched by the protected external controller under a dedicated restricted
OS principal/AppContainer. The OS policy denies `C:\pneuma-data`, network sockets,
filesystem writes outside its bounded output pipe, shell/tool lookup, dynamic
code loading, child processes, and every path except the read-only staged request
plus the digest-pinned Pneuma replay code. The launcher attests the complete
Python/interpreter, module, native-library, configuration, and replay-operation
dependency closure -- never merely `python.exe`. An inability to prove any deny
or digest closes the boundary as unavailable.

`outcome_conditioned_replay_v1` is a closed PN03 variant that supplies one PN06
terminal-label reference and its prior exchange ID as ephemeral replay input. It
returns through PN04/PN05 and exits without a Pneuma write. Durable feedback,
learning, model change, training, or RSI would be a different future effect and
is not represented by these six edges.

The boundary forbids:

- direct Python imports between repositories;
- shared databases, workspaces, long-lived credentials, worktrees, or mutation leases;
- reads or mounts of raw `C:\pneuma-data` by the 9to5 boundary process, or any
  raw data/path transfer across the boundary; Pneuma's own separately authorized
  internal data handling remains outside AURA;
- raw transcripts, hidden chain of thought, or ungrounded self-report;
- training, fine-tuning, model promotion, or RSI entrypoints;
- shell passthrough, network widening, paid services, or provider credentials;
- arbitrary commands, verifier influence, host/repository mutation, or action authority.

Malformed, stale, oversized, unauthenticated, over-budget,
provenance-incomplete, policy-incompatible, or unknown-readiness traffic produces
one bounded unavailable audit receipt and no advisory artifact or replay. Disabled
or unavailable federation is observationally equivalent to absence for
repository bytes, canonical state, provider use, Pneuma/data access, controller
decisions, and evidence; only that local audit receipt may differ.

Activation remains prohibited until all six Pneuma edges are canonically
implemented, status validation passes, kill-switch and schema compatibility are
proven, and a Graph Admission Trial shows deterministic replay, no raw-data
access or transfer, no training/RSI/host-mutation path, correctly brokered replay
actuation, zero paid egress, and no regression.

Future Pneuma internals use a separate PN namespace and never inherit AURA
authority or count toward the independent AURA-core quota.

## 12. Crucible Graph Admission Trial

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
successful trial emits an expiring GraphWarrant binding graph and contract
digests, eligible workload families, budgets, estimates, evidence, rollback, and
renewal conditions.

The primary efficiency endpoint is paired verified wins per occupied
provider-minute, reported only after hard gates. No scalar score compensates for
an authority or correctness failure.

### 12.1 Required experiments

1. Base versus Spectrum versus Spectrum plus Cortex under equal total budget.
2. Cortex disabled versus enabled.
3. Workspace capacity 8, 16, and 32 under fixed provider and context budgets.
4. One, four, and eight active specialists under fixed total budget.
5. Real charters versus duplicated and shuffled-charter shams.
6. Selective broadcast versus full-context duplication.
7. Automaticity bypass versus mandatory workspace traversal.
8. Relational frames versus flat bags of claims.
9. One-mask-at-a-time removal in simulation only.
10. Poisoned, injected, stale-epoch, and correlated-evidence canaries.
11. Non-mandatory evidence dropout.
12. Spectrum off/on by Cortex off/on factorial evaluation.
13. Claude/Codex provider-role crossover.
14. Individual knockout of every one of the 37 new AURA-core nodes and 75 new
    AURA-core edges.
15. Malformed, replayed, stale, oversized, unavailable, and forbidden-payload
    Pneuma exchanges while the boundary remains disabled.
16. Optional local J-lens replication on a compatible open-weight model,
    isolated from production admission.

Hard gates are zero paid calls, zero false success, zero authority or context
leakage, zero acceptance omission, verified-quality non-inferiority, and at least
one material hidden-outcome or resource-efficiency gain.

## 13. Existing-feature and brownfield disposition

- Elaborator remains the grounded intent and acceptance-contract compiler.
- Innovator remains a hypothesis emitter feeding Crucible.
- Adversary is a reusable Red-cell implementation seam, not a permanent provider.
- Verifier remains deterministic receipt authority and is not a Blue cell.
- Council and Society become selective Spectrum/Cortex protocols rather than
  always-on provider casts.
- Human Nature Workspace remains an experimental compatibility adapter. Its
  current raw all-specialist broadcast, fixed salience, and silent callback
  failures cannot implement BCW, SBR, BIF, WEC, or WRR.
- AttentionSchema remains a self-observation projection and does not route work
  or count as Cortex.
- Chronicle remains a read-only temporal projection.
- Constellation consumes canonical events and graph manifests but cannot write.

No external provider seat survives in the zero-cost profile. Existing Gemini,
Groq, Cloudflare, Cerebras, or paid API paths must be physically ineligible, not
merely discouraged by prompt or hidden behind post-hoc cost accounting.

## 14. Constellation dashboard contract

The future dashboard renders the full-graph manifest and runtime event stream as
separate truth surfaces:

- target topology count versus implemented, eligible, active, unavailable, and
  retired counts;
- current node, epoch, round, cell, provider, lease, causal parents, and
  evidence digest;
- advisory graph visually separated from mutation authority;
- active feedback credit and termination condition;
- every score linked to recomputable evidence;
- Pneuma shown as a disabled external federation domain until activated;
- Chronicle as a temporal projection over receipts;
- no dashboard-derived writes.

A single 111-node canvas is not the default view. Constellation provides a
global navigator plus authority, execution, Spectrum, Cortex, Crucible,
federation, and evidence panels. Complexity remains inspectable rather than
chaotic.

## 15. Architecture-only boundary and next plan

This document changes target architecture only. It does not claim that the new
nodes are implemented or active. Runtime code remains governed by the
transactional-kernel prerequisite in the parent design and implementation plan.

The next implementation plan must be separate from the kernel plan and ordered:

1. machine-readable qualified manifest and static authority/count linter;
2. typed advisory artifacts and receipt-only shadow instrumentation;
3. Spectrum deterministic gates and ephemeral cells in shadow mode;
4. Cortex admission, bounded epochs, selective broadcast, and spill/recall;
5. Crucible graph-admission and node/edge knockout harness;
6. disabled Pneuma envelope validator and no-op canaries;
7. GraphWarrant-controlled activation;
8. Constellation projection.

Kernel completion is not full AURA R3 completion. The world-class claim remains
unearned until the complete architecture passes its matched evidence program.

## 16. Final invariant

AURA may grow extremely complex in hypotheses, evidence, specialist transforms,
counterfactuals, recovery paths, and projections.

Only Omega may grow authority, and only through reviewed typed contracts.

Every other component must remain replaceable, bounded, observable, causally
testable, and removable.
