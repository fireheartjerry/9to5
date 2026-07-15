# GALAXY R3 — Pre-Implementation Readiness Ledger

**Status:** evidence-backed candidate readiness; implementation remains prohibited pending explicit Accretion R1 approval  
**Date:** 2026-07-14 (revision pass; supersedes the 2026-07-13 freeze)  
**Branch:** `main`  
**Purpose:** prove that architecture, authority, research, algorithms, implementation sequencing, gates, rollback, and verification are specified before runtime implementation begins

> **Post-review-pass note (added during spec review):** the original six R3 architecture
> documents received (a) an additive clarity/consistency review pass and (b) a
> full **astro naming migration** — every subsystem renamed to an astrophysical
> object convention, with the `aura.*` contract namespace becoming `galaxy.*`,
> six identifier families re-prefixed, and all six files renamed. The complete
> old→new map, the deliberately preserved identifiers, and the required
> out-of-package follow-up are normative in
> [design appendix A](2026-07-14-galaxy-r3-design.md#appendix-a-astro-naming-migration-r3-rename).
>
> The rename is **nomenclature-only**: it changes no count, gate, threshold,
> authority rule, or behaviour. Re-audited post-rename and still valid: `131/250`
> core and `134/256` federation-ready counts, `PU01`–`PU68` / `QK01`–`QK12` /
> `AC-R01`–`AC-R34` contiguity, and the `93/529` Cepheid-0 maxima.
>
> Two integrity consequences: the Accretion specification hash is recomputed in
> §7.2, and **all implementation-plan hashes (§7.1, §7.2) are invalidated**
> because those files live outside this package and have not yet been migrated.
> Before the readiness claim below is *re*-asserted for sign-off: migrate the
> §A.4 files, recompute their hashes, and re-run the §10 reproducible commands to
> refresh the git-state audit (commits-ahead, `git diff --check`,
> task/requirement contiguity).
>
> **Brownfield/frontier expansion (approved 2026-07-14):** a seventh
> specification now owns exactly `BR01..BR50` repository records and
> `FR01..FR35` frontier-paper records. Existing specifications contain only
> non-counting projections of those IDs. This expands evidence and experiments;
> it changes no qualified node/edge count, authority class, live scheduler policy,
> promotion threshold, or activation permission.

---

## 1. Readiness claim

The GALAXY R3 pre-implementation package is structurally complete enough for
an approval decision. It contains:

1. the world-model and transactional-kernel design;
2. the canonical qualified capability topology;
3. Pulsar R1 scheduling architecture and implementation plan;
4. Quark Portfolio R2 algorithm-qualification architecture and plan;
5. Accretion Context Virtualization Plane R1 architecture and plan;
6. current scheduling/context research artifacts and primary-source transfers;
7. exact authority, lifecycle, failure, rollback, and qualification contracts;
8. file-exact, test-first implementation tasks; and
9. commands and evidence needed before any live activation.
10. a canonical, pinned-discovery brownfield/frontier registry with subsystem projections.

This is not a claim that the runtime has been implemented or that GALAXY is already
world-class. It is a claim that implementation can begin without another
speculative architecture cycle once the candidate freeze is approved.

---

## 2. Authoritative artifact inventory

| Layer | Artifact | Evidence provided |
|---|---|---|
| System thesis | `docs/superpowers/specs/2026-07-14-galaxy-r3-design.md` | goals, zero-cost boundary, Claude/Codex roles, research synthesis, capability thesis |
| Brownfield/frontier registry | `docs/superpowers/specs/2026-07-14-galaxy-r3-brownfield-frontier-registry.md` | exactly 50 repository quarries and 35 frontier papers; discovery pins, license posture, transfers, rejections, experiments, and falsifiers |
| Authority kernel | `docs/superpowers/plans/2026-07-13-galaxy-r3-transactional-kernel.md` | mutation/effect/verification transactions, failure states, staging, activation |
| Main graph | `docs/superpowers/specs/2026-07-14-galaxy-r3-qualified-capability-topology.md` | 131-node/250-edge core topology, authority classes, Nebula/Flare, disabled Voyager boundary |
| Scheduler spec | `docs/superpowers/specs/2026-07-14-galaxy-r3-pulsar-r1-qualified-topology.md` | scheduler ownership, queueing, leases, recovery, graph contracts, algorithm seams |
| Scheduler plan | `docs/superpowers/plans/2026-07-13-galaxy-r3-pulsar-r1-implementation-plan.md` | 17 executable tasks and exact 132-file staging closure |
| Algorithm portfolio spec | `docs/superpowers/specs/2026-07-14-galaxy-r3-quark-portfolio-r2-qualified-topology.md` | candidate qualification lifecycle, exact oracles, P0–P4 evidence, shadow/canary rules |
| Algorithm portfolio plan | `docs/superpowers/plans/2026-07-13-galaxy-r3-quark-r2-implementation-plan.md` | 14 executable tasks and terminal-live requalification lifecycle |
| Context spec | `docs/superpowers/specs/2026-07-14-galaxy-r3-accretion-context-virtualization-r1.md` | 34 closed requirements, schemas, data structures, provider/session rules, paging and compaction |
| Context plan | `docs/superpowers/plans/2026-07-13-galaxy-r3-accretion-r1-implementation-plan.md` | 22 test-first tasks, exact files/APIs/gates, shadow implementations, rollback |
| Research plan | `state/last30days-scheduling-plan.json` | frozen subqueries and source weights |
| Recent evidence | `state/research/last30days/scheduling-compact.md` | last30days v3.8.3 output, 72 evidence items across GitHub/HN/Reddit/YouTube |
| Raw research | `state/research/last30days/ai-agent-scheduling-long-horizon-autonomous-systems-local-first-ai-operating-systems-task-orchestration-raw-pulsar-r1-2026-07-13.md` | untrusted raw evidence preserved separately from synthesis |

The last30days evidence is supplementary discovery material, not architecture
authority. Primary papers, official documentation, repository code, local
brownfield facts, and exact tests dominate when sources conflict.

---

## 3. User requirement coverage

| User requirement | Evidence | Status |
|---|---|---|
| Transformative, not incremental | transactional kernel, Pulsar, Quark, Flare/Nebula, Accretion | covered architecturally |
| Essentially zero incremental external operating cost | explicit local-only constraints in all four freezes; no paid/network fallback in qualification | covered |
| Claude and Codex as real differentiated capabilities | GALAXY design and Accretion provider specialization | covered |
| Preserve old elaborator/innovator capabilities | main topology migration/compatibility sections | covered |
| Capability complexity with ordered authority | 131/250 core graph and closed authority classes | covered |
| Professional named systems and colored teams | GALAXY/Nebula/Pulsar/Quark/Accretion names; Red/Orange/Blue/Green roles | covered |
| Dashboard should later show live graph position | immutable dashboard receipt contracts in Pulsar and Accretion; UI deferred intentionally | designed, implementation deferred |
| Deep attention/global-workspace transfer | GALAXY global-workspace/Nebula research section | covered as falsifiable hypothesis |
| Relevant GitHub brownfielding | canonical `BR01..BR50`; 14 retained sources plus 36 qualified additions | specified; every actual port still requires a full `SourcePassport` |
| Current frontier research | canonical `FR01..FR35`, restricted to 2025-2026 and separated into scheduling, memory, reliability, security, and planning | specified as falsifiable hypotheses; preprints labeled |
| Scheduler spans entire system and queues work | Pulsar schedule journal, eligibility, priority, backpressure, timers, DIO, recovery | covered |
| Advanced CP techniques | BR02, BR04-BR06, BR10, BR33-BR34, BR44-BR50 plus Quark P2; official IOI/ICPC material is editorial evidence only | expanded without prestige coupling; no backend auto-promoted |
| Directed SSSP paper considered | Quark shape certification and negative-use gates; no forced use where workload invariants are absent | covered |
| Segment/lazy context virtualization | Accretion temporal hierarchy and restricted composable metadata tags | covered |
| Li Chao context selection | affine complete-packet shadow candidate plus exact counterexample and Pareto fallback | covered conditionally |
| Link-cut active context lineage | derived one-parent shadow accelerator plus DAG/parent-chain oracle | covered conditionally |
| Voyager-Lab integration space | disabled, tainted, read-only hypothesis boundary | reserved safely |
| Obsidian decision | retained as human-readable projection, never canonical runtime state | covered |
| No runtime code during architecture phase | current diff contains documentation/research state only | proven at audit time |
| Main branch | `git branch --show-current` returns `main` | proven |
| Keep xhigh and never request downgrade | working preference recorded in thread; no lower-model gate appears in plans | covered operationally |

### 3.1 Competitive-programming brain-dump disposition

Both user-provided CP brain dumps and the new ICPC/IOI-grade brownfield search
were audited as an additive candidate catalog. Canonical repository membership is
BR02, BR04-BR06, BR10, BR33-BR34, and BR44-BR50; the seven new contest and
verification quarries are BR44-BR50. KACTL is quarantined for missing detected
license, and `cp-algorithms` is explanation-only under CC-BY-SA-4.0.
They are not an instruction to put every technique on the authority path. The
frozen Quark ledger supplies the common admission law: a technique needs a
real consumer, a machine-checkable shape certificate, a permanent independent
oracle, complete end-to-end P2 crossover evidence, and immediate fallback.

| Candidate family from the two dumps | Frozen disposition | Concrete pre-implementation decision |
|---|---|---|
| Cache-oblivious layouts, SIMD/SWAR, branchless loops, prefetching, allocation control, recurrence unrolling, PyPy/NumPy/Numba, flat arrays, big-int bitsets, `deque`/`heapq`/`bisect`, buffer reuse, and Python lookup/IO tuning | `DOA_ACCELERATOR_ONLY` | Apply only to a measured hot bounded kernel. Include warmup, serialization, persistence, verifier, memory, and fallback costs; language- or hardware-inapplicable techniques stay dormant. |
| Persistent segment/DSU/trie/treap, segment-tree beats/merging, wavelet/merge-sort matrices, fractional cascading, order-statistic/implicit treaps, sqrt trees, vEB/X-fast/Y-fast/fusion structures | `DORMANT_ANALYTICS` or `DORMANT_SHAPE_CANDIDATE` | Accretion separately admits a persistent segment hierarchy only in shadow. All others require a repeated query/update algebra that beats SQLite/bisect/scan end to end. |
| Link-cut, heavy-light, top/directed-topology trees, Euler-tour trees, centroid decomposition, DSU-on-tree, virtual trees, long-path/ladder decomposition, O(1) LCA, Cartesian trees | `CAPABILITY_RESERVE_OUTSIDE_KHRONOS` | Accretion separately admits link-cut only for a proved one-parent churned forest. DAG truth, joins, and materialized output retain exact baselines. |
| Rollback DSU over segment-tree time, offline dynamic connectivity, Mo/Hilbert with modifications/on trees, CDQ, parallel binary search, small-to-large and rebuild batching | `TARGET_EXACT_OFFLINE_LAB` or dormant analytics | Legal only for sealed timelines or immutable query batches; never reused as live directed causality or scheduler authority. |
| SCC/condensation, dominators, transitive bitsets, bridges/BCC/block-cut/SPQR, cactus transforms, directed MST, de Bruijn/Hierholzer, k-shortest/disjoint paths, Johnson/APSP, contraction hierarchies | exact conditional rows or capability reserve | Tarjan/SCC and bitset closure have proved scheduler consumers. The rest require a new exact predicate and passport; no graph prestige creates a topology node. |
| Dinic/scaling, push-relabel/ISAP/MPM, lower-bound flow/circulation, min-cost flow, cost scaling/network simplex, closure/min-cut, Gomory-Hu/Stoer-Wagner, Hopcroft-Karp, Hungarian, Blossom, matroid methods | exact gated solver, shape specialization, or reserve | Quark keeps Cepheid-0 and independently verified MCF/matching certificates. Coupled constraints or unsupported objectives fall back; general matching/flow variants remain dormant without a workload crossover. |
| 0-1 BFS, Dial, radix heap, indexed Dijkstra, 2025 BMSSP and later directed SSSP research | exact internal dispatch plus `RESEARCH_EXACT_NOT_ELIGIBLE` | Numeric-domain certificates choose simple backends. Indexed Dijkstra is permanent. Sorting-barrier research is rebuilt per residual augmentation and cannot activate without equality and large-sparse crossover evidence. |
| Z/KMP, Manacher/eertree, Aho-Corasick, suffix automaton/tree/SA-IS/DC3/Kasai, Lyndon/runs, Bitap/Myers, BWT/FM-index, multidimensional hashing | `CAPABILITY_RESERVE_OUTSIDE_KHRONOS` | Existing Aho-Corasick may be brownfield quarry only. No present scheduler or context authority predicate needs the remaining string machinery. |
| NTT/FWHT/FFT/chirp-z/Bluestein, online FFT, FPS/Newton, interpolation/evaluation, Berlekamp-Massey/Kitamasa/Bostan-Mori, polynomial GCD/factorization, subset/GCD/LCM convolution, tropical/min-plus algebra | `CAPABILITY_RESERVE_OUTSIDE_KHRONOS` | Retained as versioned research rows, not imports or opcodes. A future finite algebraic consumer must prove exact arithmetic, overflow behavior, oracle equality, and P2 crossover. |
| Divide-and-conquer/Knuth/LARSCH/SMAWK DP, Aliens/WQS, CHT/Li Chao/slope trick, SOS/subset/bitset/MITM, rerooting, digit/profile/Steiner/TSP DP, matrix recurrences | exact gated solver or dormant shape candidate | Li Chao is admitted separately only for certified affine complete packets. Lagrangian methods do not prove hard-budget feasibility; every other optimization needs its mathematical preconditions as a certificate. |
| Miller-Rabin/Pollard-Rho, CRT/Garner, modular roots/logs, sieves, linear bases/GF(2), matrix-tree/LGV/BEST/Tutte/FKT/Ryser, Burnside/Polya, inclusion-exclusion and enumerative families | `CAPABILITY_RESERVE_OUTSIDE_KHRONOS` | Preserve as a discoverable research family. Probabilistic identities cannot become protected truth without an explicit error model and deterministic/independent verification path. |
| Convex hull/Minkowski, half-plane intersection, sweeps/calipers, Delaunay/Voronoi, KD trees, planar duality, randomized enclosing geometry, persistent planar point location | `CAPABILITY_RESERVE_OUTSIDE_KHRONOS` | No current coordinate geometry consumer exists. Exact integer predicates and numerical error contracts would be prerequisites. |
| Retrograde/safety games, Sprague-Grundy and partizan games, Freivalds/Schwartz-Zippel/Karger, annealing/hill-climbing/beam search, simplex/fractional programming | exact relative-to-abstraction, advisory-only, or reserve | Finite safety games need an abstraction proof and concrete replay. Randomized/heuristic results may propose candidates only; verified hard predicates and authority gates remain deterministic. |
| Q-analog/holonomic/LLL/transfinite/Borel/pushdown-game and other speculative frontier ideas | research reserve only | These remain hypotheses until a finite system invariant, bounded representation, falsifiable benchmark, and independent verifier exist. They receive no runtime node, edge, passport, or authority. |

This disposition incorporates the entire brainstorm without converting novelty into
complexity theatre. A favorable isolated microbenchmark, asymptotic result, or
competitive-programming reputation may prioritize an experiment; none can
qualify or activate a backend.

---

## 4. Real capability gains versus complexity theatre

| Mechanism | Real gain sought | Exact baseline | Theatre rejection |
|---|---|---|---|
| Transactional kernel | no false success, split-brain authority, or partial promotion | current deterministic authority/evidence checks | graph size or names without ownership/lifecycle proof |
| Pulsar | globally ordered, durable, fair, backpressured work under local resource constraints | FIFO/priority and exact scheduling predicates | advanced scheduler with no measured queue/runtime workload |
| Quark | admit specialized algorithms only at proven workload crossovers | simplest correct algorithm and exact oracle | asymptotics or microbenchmarks detached from end-to-end gains |
| Nebula | bounded selective deliberation and provider specialization | no-workspace/full-context controls | generic all-to-all agent chat |
| Accretion ledger | exact obligations and provenance survive arbitrary horizon/reset | immutable flat replay | summaries or transcripts treated as truth |
| MMR/history | authenticated append-only prefixes and proofs | flat ordered scan | segment tree for pure append-only history |
| Persistent segment | efficient repeated historical/versioned ranges | MMR/chunk coverage and flat range fold | adding it before a measured range workload |
| Parent chain | exact active execution inheritance | explicit path walk | pretending `O(log N)` removes output-size cost |
| Link-cut | dynamic cut/relink path aggregates | parent chain/persistent stack | use on shallow/static/append-only lineages |
| Pareto selector | exact fixed-packet budget query | exhaustive enumeration | learned/heuristic selector in hard path |
| Li Chao | affine scalar packet-envelope queries | exhaustive/Pareto | use for ordinary budgeted knapsack or complementarity |
| Paging | bounded recall and clean-context reconstruction | full packet rebuild | claiming in-session tool calls reclaim provider tokens |

### 4.1 Accretion requirement-by-requirement implementation mapping

| Requirement | Plan tasks | Direct evidence class |
|---|---|---|
| `AC-R01` | 3, 14, 21 | frozen contracts, ingress classification, authority noninterference |
| `AC-R02` | 14, 21 | kernel-qualified ingress and independent live revalidation tests |
| `AC-R03` | 6, 14 | reducer and `ExecutionStateCutRef` adapter tests |
| `AC-R04` | 6, 14 | closed deterministic reducer and observation/advisory rejection |
| `AC-R05` | 5, 6, 20 | source-cursor uniqueness, causal closure/cycle tests, flat replay |
| `AC-R06` | 6, 9, 10 | exact pins, provider envelope, packet completeness |
| `AC-R07` | 9, 10, 13, 21 | `ContextUnsatisfiable` and no-truncation routing tests |
| `AC-R08` | 12 | summary invariants and exact-handle fallback |
| `AC-R09` | 3, 10, 12, 14 | monotone taint/origin contracts and transformation tests |
| `AC-R10` | 3, 10, 14 | transitive origin closure and false-independence tests |
| `AC-R11` | 3, 4, 7 | canonical serialization, blob digest, Merkle domain/shape tests |
| `AC-R12` | 5, 12 | protected root-publication receipt and CAS tests |
| `AC-R13` | 12 | closed Evaporation transaction-stage tests |
| `AC-R14` | 12 | every-stage crash matrix and raw reachability |
| `AC-R15` | 16 | mark-and-sweep roots and leases |
| `AC-R16` | 5 | immutable SQLite triggers and isolated current-root CAS |
| `AC-R17` | 5, 12, 20 | transaction crash injection and replay recovery |
| `AC-R18` | 13 | additive recall versus replacement classification |
| `AC-R19` | 13, 15 | fresh-epoch and session-binding tests |
| `AC-R20` | 15 | retry/rejection/rollback/revision freshness matrix |
| `AC-R21` | 15 | exact same-session binding predicate |
| `AC-R22` | 13, 21 | bounded recall admission and router tests |
| `AC-R23` | 13 | consumer/purpose/snapshot-bound opaque handle tests |
| `AC-R24` | 2, 13 | incumbent observations, faults, refaults, and thrash containment |
| `AC-R25` | 7, 17 | per-stream history and separate DAG tests |
| `AC-R26` | 7, 17 | independent range fold and monoid property tests |
| `AC-R27` | 17 | lazy composition/action law and field-closure tests |
| `AC-R28` | 8, 18 | parent-chain semantics and link-cut cycle/API tests |
| `AC-R29` | 8, 10, 18 | exact union of pins, DAG closure, and lineage |
| `AC-R30` | 11 | exhaustive selector and Pareto equivalence |
| `AC-R31` | 19 | affine certificate, counterexample, and zero-regret tests |
| `AC-R32` | 17–21 | flags, exact fallbacks, replay, P2 crossover, rollback receipts |
| `AC-R33` | 4, 14, 16 | secret non-persistence, protected handles/redaction, retention tests |
| `AC-R34` | 5, 6, 7, 20 | bounded delta validation, streamed recovery, offline flat replay |

---

## 5. Frozen authority order

```text
protected mission/policy/repository/evidence receipts
  -> deterministic context/scheduler cuts
  -> advisory planning, retrieval, scheduling, and packet proposals
  -> eligibility, integrity, capability, and freshness gates
  -> atomic reservation/dispatch/mutation transaction
  -> independent verification and protected terminal outcome
  -> promotion only through the existing kernel
```

Neither Pulsar, Quark, Nebula, Accretion, provider models, Obsidian, the
dashboard, nor Voyager can bypass this order.

---

## 6. Implementation sequencing proof

The plans establish dependencies in this order:

1. observe and measure incumbents;
2. define canonical contracts and exact oracles;
3. build immutable storage and deterministic state;
4. add the simplest correct production baselines;
5. integrate behind disabled/dark flags;
6. create shadow optimized candidates;
7. differentially compare candidates with exact baselines;
8. qualify only at measured end-to-end crossover;
9. run A/A, hidden replay, temporal holdout, shadow, canary, and rollback; and
10. activate through one atomic authority-bound transaction.

This prevents an advanced backend from becoming indispensable before its
correctness and usefulness are independently established.

---

## 7. Verification evidence already obtained

### 7.1 Pulsar and Quark freeze audit

- stable Pulsar implementation-plan SHA-256:
  `a4b5e94adc525bf79882fe6544f6d383d919ed408faa1ff090e1622fe06ff42f`;
- Pulsar tasks are contiguous `1..17`;
- Quark tasks are contiguous `1..14`;
- Task 14 staging closure is exactly 132 declared and 132 staged paths;
- zero executable target-code/test/build/staging/commit commands occur after the
  dark seal or authority switch;
- terminal-live Quark renewal requires fresh Q, Q-bound P0–P3 and integration
  shadow evidence, current Q resolution, then fresh P4;
- direct terminal-live to live renewal is rejected;
- topology parses as Base `71/95`, Flare `16/31`, Nebula `21/44`, Pulsar
  `19/68`, Quark `4/12`, core `131/250`, disabled Voyager `134/256`
  (sums: `71+16+21+19+4 = 131` nodes, `95+31+44+68+12 = 250` edges, `+3/+6`
  federation);
- zero duplicate node IDs, edge IDs, ordered pairs, self-loops, or dangling
  endpoints were found;
- all 19 local links across the ten authoritative architecture artifacts
  resolved; and
- `git diff --check` passed.

### 7.2 Accretion document audit

- specification requirements are contiguous `AC-R01..AC-R34`;
- implementation tasks are contiguous `1..22`;
- all 34 requirements are covered both by the plan's range map and the ledger's
  individual requirement rows;
- code-fence counts are even;
- prohibited planning placeholders are absent;
- every task has an explicit file surface;
- all seven independent architecture-review findings are closed in the spec or
  plan: BIF independence, secret non-persistence, telemetry writer isolation,
  config layering, bounded parent walks, path confinement, and bounded live-delta
  validation;
- both CP brain dumps are explicitly dispositioned by candidate family rather
  than promoted by prestige;
- Last30Days raw and compact artifacts are present with 72 evidence items across
  four active source classes;
- permanent exact oracles precede optimized candidates; and
- persistent segment, link-cut, and Li Chao remain shadow-only until Quark P2.

Frozen Accretion content hashes at this audit point:

- specification SHA-256:
  `86851eff4ba7526f423eccdbf89c77e144b8566ca159aeb27e3c57b6cde34bfc`
  (recomputed 2026-07-14 after the astro rename migration, the R3 evidence pass
  that added §1.1 prior art, and the 2026-07-14 re-dating; supersedes
  `2349e7fa…`, `b01479a8…`, `a8386034…`, and the original freeze value);
- implementation-plan SHA-256: **invalidated, recomputation required**. The
  previously asserted `1d12e19b101a8f7442b95e797a0f5574f4d4f3748a7780920aaf7729db0bc813`
  describes the pre-rename plan file. That file is outside this package, still
  carries retired names, and must be renamed and transformed per design
  appendix §A.4 before a new hash is recorded here. The same applies to the
  Pulsar implementation-plan hash asserted in §7.1
  (`a4b5e94a…`). No plan-hash assertion in this ledger may be treated as
  current until those files are migrated and re-hashed.

### 7.3 Worktree scope

At readiness-audit time:

- branch is `main`;
- `main` is three commits ahead of `origin/main`;
- no runtime-source/config/test file has a working-tree diff;
- modified/untracked scope is documentation and research state only;
- no files are staged; and
- no commit or push is authorized by this readiness ledger.

---

## 8. Evidence still required during implementation

| Evidence | Required before |
|---|---|
| Incumbent operation-shape telemetry | choosing any optimized data structure |
| Flat replay equivalence and crash-prefix matrix | context ledger shadow activation |
| 100% hard-pin recall and zero stale admission | any qualified context packet path |
| Parent-chain/Pareto exact results | link-cut/Li Chao comparison |
| P2 need floor and lower-confidence crossover | any optimized backend qualification |
| Fixed-budget verified-success noninferiority | efficiency claim |
| A/A and hidden replay | shadow influence |
| Temporal holdout and adjacent scale buckets | canary |
| Current rollback and source-tree bindings | live activation |
| Full 40-character repository SHA, fetched-tree/license digests, copied-symbol inventory, independent oracle, and expiry owner in a `SourcePassport` | any BR source entering a shadow implementation |
| Claim-location capture, local hypothesis, preregistered experiment, falsifier, and status recheck | any FR mechanism influencing a policy trial |

| Validated single manifest + count/authority linter (base `71/95` materialized; core `131/250`; no spine ingress) | any "manifest-qualified" claim or GraphWarrant issuance |

| Deterministic simulation testing campaign (design §15.1): preregistered seed budget green, every discovered seed retained as a regression fixture with its `(seed, source_revision_digest, harness_digest)` triple | any wave landing; necessary but never sufficient — does not substitute for E3 preflight or live qualification |

No document can substitute for these runtime measurements.

---

## 9. Remaining approval boundary

The sole pre-implementation decision remaining is explicit acceptance of the
Accretion R1 candidate freeze. Acceptance authorizes implementation behind
disabled/dark flags. It does not authorize:

- live traffic influence;
- mutation/effect authority;
- paid or network services;
- automatic promotion of any advanced backend;
- Voyager activation;
- a dashboard control plane; or
- bypassing tests, Quark qualification, canary, or rollback.

After approval, Task 1 of the Accretion plan may begin immediately. No additional
architecture phase is required.

---

## 10. Reproducible readiness commands

```powershell
git branch --show-current
git status --short
git diff --check

$plan = 'docs/superpowers/plans/2026-07-13-galaxy-r3-accretion-r1-implementation-plan.md'
$spec = 'docs/superpowers/specs/2026-07-14-galaxy-r3-accretion-context-virtualization-r1.md'
$registry = 'docs/superpowers/specs/2026-07-14-galaxy-r3-brownfield-frontier-registry.md'

Select-String -Path $plan -Pattern '^### Task ([0-9]+):'
Select-String -Path $spec -Pattern '`MN-R([0-9]+)`'
Select-String -Path $plan,$spec -Pattern ('T' + 'BD|T' + 'ODO|F' + 'IXME|X' + 'XX')

$br = Select-String -Path $registry -Pattern '^\| BR([0-9]{2}) \|' | ForEach-Object { [int]$_.Matches[0].Groups[1].Value }
$fr = Select-String -Path $registry -Pattern '^\| FR([0-9]{2}) \|' | ForEach-Object { [int]$_.Matches[0].Groups[1].Value }
if (($br -join ',') -ne ((1..50) -join ',')) { throw "BR registry is not exactly contiguous BR01..BR50" }
if (($fr -join ',') -ne ((1..35) -join ',')) { throw "FR registry is not exactly contiguous FR01..FR35" }

$allSpecs = Get-ChildItem 'docs/superpowers/specs/2026-07-14-galaxy-r3-*.md'
$known = @(1..50 | ForEach-Object { 'BR{0:D2}' -f $_ }) +
  @(1..35 | ForEach-Object { 'FR{0:D2}' -f $_ })
$refs = Select-String -Path $allSpecs.FullName -Pattern '\b(?:BR|FR)[0-9]{2}\b' -AllMatches |
  ForEach-Object Matches | ForEach-Object Value | Sort-Object -Unique
$unknown = $refs | Where-Object { $_ -notin $known }
if ($unknown) { throw "Unknown registry IDs: $($unknown -join ', ')" }

Get-FileHash -Algorithm SHA256 `
  'docs/superpowers/plans/2026-07-13-galaxy-r3-pulsar-r1-implementation-plan.md', `
  'docs/superpowers/plans/2026-07-13-galaxy-r3-quark-r2-implementation-plan.md', `
  $spec, $plan
```

Expected readiness result:

- branch `main`;
- tasks `1..22` without gaps;
- requirements `AC-R01..AC-R34` without gaps;
- repositories `BR01..BR50` and papers `FR01..FR35` without gaps or unknown projected IDs;
- placeholder scan empty;
- `git diff --check` exit zero; and
- runtime-source diff empty.

---

## 11. Final pre-implementation disposition

**Disposition:** `READY_FOR_ARCHITECTURE_APPROVAL`  
**Implementation:** prohibited until approval  
**Live activation:** prohibited until implementation, exact verification,
Quark qualification, shadow/canary evidence, and atomic authority switch  
**Fallbacks:** immutable flat replay, MMR, parent chain, exact enumeration, and
Pareto remain permanent
