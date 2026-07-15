# GALAXY R3 — Brownfield and Frontier Evidence Registry R1

**Status:** APPROVED REGISTRY DESIGN; SOURCE QUARRIES ONLY; NO EXTERNAL AUTHORITY TRANSFER

This document is the sole package authority for brownfield repository membership
and frontier-paper membership. It contains exactly **50** repository records
(`BR01..BR50`) and **35** paper records (`FR01..FR35`). Other GALAXY documents
project these IDs; they do not redefine or recount them.

The registry is an engineering quarry, not a dependency lockfile. A listed source
may supply a mechanism, invariant, fixture, adversarial case, or clean-room design
hypothesis. It cannot supply GALAXY authority, correctness, or promotion evidence.

---

## 1. Admission and provenance contract

Every source-code adaptation requires a `SourcePassport` containing:

1. canonical repository URL and full 40-character commit SHA;
2. fetched-tree digest, fetch time, default branch, and license-file digest;
3. copied files/symbols or a declaration that the transfer is clean-room only;
4. transitive dependency and generated-code license review;
5. GALAXY consumer, closed input contract, invariant, and failure behavior;
6. independent semantic oracle and adversarial fixture provenance;
7. end-to-end benchmark including conversion, persistence, receipts, verification,
   fallback, cold start, memory, and crash behavior; and
8. expiry, upstream-drift review, rollback, and kill-switch owner.

The abbreviated discovery pins below were resolved on 2026-07-14. They make the
research pass reproducible but are not sufficient for a source port: the passport
must resolve and record the full SHA before code enters even a shadow backend.

License labels describe the pinned top-level repository. They do not waive
subdirectory, model-weight, dataset, generated-code, or dependency review.

---

## 2. Canonical brownfield repository registry — exactly 50

| ID | Source and discovery pin | License/posture | Transfer into GALAXY | Explicit non-transfer / qualification |
|---|---|---|---|---|
| BR01 | [agentscope-ai/ReMe](https://github.com/agentscope-ai/ReMe/tree/2e87b7a52eba) | Apache-2.0 | procedural-memory distillation, utility scoring, pruning fixtures | no duplicate memory authority or framework import; Accretion receipts remain canonical |
| BR02 | [alphastrata/DunMaoSSSP](https://github.com/alphastrata/DunMaoSSSP/tree/28bd63b4d13e) | MIT | directed non-negative SSSP research layout and differential fixtures | corrects the stale `alphastrata/fast_sssp` name; no dynamic-SSSP or production-speed claim |
| BR03 | [anthropics/jacobian-lens](https://github.com/anthropics/jacobian-lens/tree/581d398613e5) | Apache-2.0 | optional open-weight interpretability replication | never a production monitor, verifier, router, or proprietary-model claim |
| BR04 | [atcoder/ac-library](https://github.com/atcoder/ac-library/tree/864245a00b00) | CC0-1.0 | contest-hardened flow, SCC, convolution, and data-structure layouts | normalize contracts and independently test; no trust from contest provenance alone |
| BR05 | [cheran-senthil/PyRival](https://github.com/cheran-senthil/PyRival/tree/6a87b91b385a) | Apache-2.0 | Python algorithm implementations and cross-language fixtures | no direct trusted-kernel copy without bounded integer/error semantics |
| BR06 | [DiogoRibeiro7/bmssp](https://github.com/DiogoRibeiro7/bmssp/tree/181e380c4735) | MIT | BMSSP research implementation and counterexample generation | research backend only until exact equivalence and real crossover are proved |
| BR07 | [Kiz8-Team/pi-cwl](https://github.com/Kiz8-Team/pi-cwl/tree/cd2ea3f1a69c) | MIT | typed episode DAG and dependency-aware eviction | agent-authored boundaries cannot become unquestioned context truth |
| BR08 | [letta-ai/letta](https://github.com/letta-ai/letta/tree/b76da9092518) | Apache-2.0 | explicit core/archive memory operations and paging vocabulary | self-editing memory and overlapping orchestration authority are rejected |
| BR09 | [MemTensor/MemOS](https://github.com/MemTensor/MemOS/tree/13fbd43743b3) | Apache-2.0 | namespaced role/consumer memory views | no Neo4j/Qdrant/full-stack operational dependency in the R3 local baseline |
| BR10 | [networkx/networkx](https://github.com/networkx/networkx/tree/3b4c227fda1c) | BSD-family; GitHub detector `NOASSERTION` | simple graph oracle, fixture generator, and readable reference | never the authority fast path; verify the pinned license file in the passport |
| BR11 | [openai/codex-plugin-cc](https://github.com/openai/codex-plugin-cc/tree/db52e28f4d9d) | Apache-2.0 | inspectable delegation, health, background-job, and lifecycle contracts | no proprietary Claude Code source or nested-provider authority transfer |
| BR12 | [tigerbeetle/tigerbeetle](https://github.com/tigerbeetle/tigerbeetle/tree/97c7a8ef3852) | Apache-2.0 | deterministic simulation, time compression, seeded fault injection, production assertions | no VSR/replication import; GALAXY simulates a single-host fault domain |
| BR13 | [uw-syfi/TraceLab](https://github.com/uw-syfi/TraceLab/tree/b9d6cfa4da42) | Apache-2.0 | trajectory instrumentation, sanitization, and process diagnosis | telemetry never proves success or authority without verifier receipts |
| BR14 | [YennNing/Awesome-Code-as-Agent-Harness-Papers](https://github.com/YennNing/Awesome-Code-as-Agent-Harness-Papers/tree/06b0d447951a) | MIT research index | discovery index for harness-as-program mechanisms | index membership is not evidence; every downstream source is requalified |
| BR15 | [langchain-ai/langgraph](https://github.com/langchain-ai/langgraph/tree/b96f6170e7ed) | MIT | typed state graphs, reducers, checkpoints, interrupts, and resume fixtures | no competing state authority or framework dependency on the qualified path |
| BR16 | [OpenHands/OpenHands](https://github.com/OpenHands/OpenHands/tree/a55f1ded61ca) | MIT outside `enterprise/`; mixed-tree review required | sandbox event streams, artifact recovery, and agent/computer boundaries | enterprise subtree excluded; no wholesale runtime import |
| BR17 | [microsoft/agent-framework](https://github.com/microsoft/agent-framework/tree/b5300fe0c05e) | MIT | provider-neutral message/tool schemas, middleware, and multi-agent orchestration fixtures | no framework-owned routing, memory, or success authority |
| BR18 | [modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk/tree/2713b53b127a) | MIT | MCP capability negotiation, lifecycle, transports, cancellation, and schema fixtures | protocol compatibility does not grant tool trust or execution authority |
| BR19 | [e2b-dev/E2B](https://github.com/e2b-dev/E2B/tree/7474d904a2f6) | Apache-2.0 | disposable sandbox lifecycle and execution/artifact API patterns | hosted service is not a dependency; local implementation must preserve zero-cost rules |
| BR20 | [NVIDIA/OpenShell](https://github.com/NVIDIA/OpenShell/tree/e8c16eb168ca) | Apache-2.0 | policy-governed agent sandboxing and runtime isolation | no policy engine may override Singularity capabilities or receipts |
| BR21 | [kubernetes-sigs/agent-sandbox](https://github.com/kubernetes-sigs/agent-sandbox/tree/d32b35557917) | Apache-2.0 | sandbox resource/lifecycle separation and agent-oriented isolation fixtures | no Kubernetes control-plane dependency in the single-host baseline |
| BR22 | [google/gvisor](https://github.com/google/gvisor/tree/e84de63bce35) | Apache-2.0 | syscall interception, isolation tests, and reduced host-kernel exposure | Linux-only reference; not assumed available or equivalent on Windows |
| BR23 | [firecracker-microvm/firecracker](https://github.com/firecracker-microvm/firecracker/tree/1faca2f70e7a) | Apache-2.0 | jailer boundaries, resource controls, and disposable microVM lifecycle | Linux/KVM reference only; no claim that R3 can deploy it on every host |
| BR24 | [temporalio/temporal](https://github.com/temporalio/temporal/tree/4ca62848d3ce) | MIT | deterministic workflow replay, timers, retries, histories, and activity boundaries | no recurring service dependency and no exactly-once external-side-effect claim |
| BR25 | [cadence-workflow/cadence](https://github.com/cadence-workflow/cadence/tree/17ac08d064b5) | Apache-2.0 | durable histories, task queues, retry policies, and worker coordination | evidence/pattern source only; no service deployment in the local R3 baseline |
| BR26 | [dbos-inc/dbos-transact-py](https://github.com/dbos-inc/dbos-transact-py/tree/c60398175086) | MIT | transaction-backed durable Python workflow and recovery patterns | no Postgres dependency or external effect relabeling as exactly-once |
| BR27 | [ray-project/ray](https://github.com/ray-project/ray/tree/ce49e2f358b9) | Apache-2.0 | heterogeneous resources, placement groups, fair scheduling, and backpressure fixtures | no distributed cluster dependency; adapt only measured scheduler mechanisms |
| BR28 | [dask/distributed](https://github.com/dask/distributed/tree/40fcd99a8cd4) | BSD-3-Clause | dynamic DAG priorities, work stealing, spill, and worker-loss recovery | stealing cannot violate capability, affinity, reservation, or mission-fairness gates |
| BR29 | [kubernetes/kubernetes](https://github.com/kubernetes/kubernetes/tree/153eedf9b826) | Apache-2.0 | scheduling queues, plugin phases, feasibility, scoring, preemption, and resource fits | no Kubernetes deployment; framework phases are design and test quarries only |
| BR30 | [apache/kafka](https://github.com/apache/kafka/tree/da3b5e78ed2b) | Apache-2.0 | request purgatory/timers, partition backpressure, offsets, and replayable-log fixtures | no broker dependency; Kafka delivery semantics do not replace DIO receipts |
| BR31 | [apple/foundationdb](https://github.com/apple/foundationdb/tree/06ae2ea46860) | Apache-2.0 | deterministic simulation, transactional conflict handling, and failure recovery | no distributed database adoption; transfer testing discipline and bounded mechanisms |
| BR32 | [PrefectHQ/prefect](https://github.com/PrefectHQ/prefect/tree/4e685996b463) | Apache-2.0 | explicit states, concurrency limits, retries, schedules, and resumable-flow fixtures | no orchestration authority or hosted control-plane dependency |
| BR33 | [google/or-tools](https://github.com/google/or-tools/tree/98c165af62df) | Apache-2.0 | CP-SAT, assignment, matching, routing, min-cost flow, and exact small-cohort oracles | solver result requires an independent verifier; no opaque authority claim |
| BR34 | [scipopt/scip](https://github.com/scipopt/scip/tree/3dc4d050702f) | Apache-2.0 | exact/anytime MIP and constraint optimization for placement-oracle experiments | shadow/offline only until deterministic budgets, witnesses, and fallback qualify |
| BR35 | [apache/airflow](https://github.com/apache/airflow/tree/26c2c123a3cb) | Apache-2.0 | pools, priority weights, deferrable work, scheduler HA, and operational backpressure | no Airflow service or database dependency; do not copy its authority model |
| BR36 | [mem0ai/mem0](https://github.com/mem0ai/mem0/tree/ccbe5861a138) | Apache-2.0 | extraction/update/conflict pipelines and memory evaluation fixtures | model-generated memory mutations remain proposals until mechanically verified |
| BR37 | [getzep/graphiti](https://github.com/getzep/graphiti/tree/526dcad7a300) | Apache-2.0 | temporal graph ingestion, episode invalidation, and time-aware retrieval | no external graph database dependency or LLM-authored canonical edges |
| BR38 | [UKGovernmentBEIS/inspect_ai](https://github.com/UKGovernmentBEIS/inspect_ai/tree/326f9b5c9a66) | MIT | reproducible agent evaluations, sandboxes, scorers, logs, and approval hooks | evaluation framework output is evidence, not a promotion receipt by itself |
| BR39 | [SWE-bench/SWE-bench](https://github.com/SWE-bench/SWE-bench/tree/f7bbbb2ccdf4) | MIT | repository-task packaging, environment construction, and patch-verification fixtures | benchmark score is not production reliability and cannot hide security regressions |
| BR40 | [sigstore/cosign](https://github.com/sigstore/cosign/tree/8ca5b2002f5c) | Apache-2.0 | artifact signing/verification and identity-bound provenance fixtures | no hosted transparency-log dependency is required by the local baseline |
| BR41 | [theupdateframework/python-tuf](https://github.com/theupdateframework/python-tuf/tree/6889cfbffbb9) | Apache-2.0 | threshold roots, expiry, rollback/freeze protection, rotation, and revocation | metadata model informs Polaris; library cannot become root authority automatically |
| BR42 | [in-toto/in-toto](https://github.com/in-toto/in-toto/tree/a8ce9ee2125a) | Apache-2.0 license file; GitHub detector `NOASSERTION` | signed step/link attestations and supply-chain layout verification | predicate shapes do not prove the truth of unverified materials or products |
| BR43 | [open-telemetry/opentelemetry-python](https://github.com/open-telemetry/opentelemetry-python/tree/ae8feeb7af99) | Apache-2.0 | trace/span propagation, semantic conventions, and exporter-neutral telemetry | observability is non-authoritative and must fail independently of run state |
| BR44 | [yosupo06/library-checker-problems](https://github.com/yosupo06/library-checker-problems/tree/04c8de378bab) | Apache-2.0 | adversarial algorithm contracts, generators, validators, and reference outputs | tests supplement but never replace GALAXY shape certificates and oracles |
| BR45 | [online-judge-tools/verification-helper](https://github.com/online-judge-tools/verification-helper/tree/adbff121b1f9) | MIT | documentation-linked tests and automatic algorithm-library verification | helper output is CI evidence only; stale upstream activity triggers local ownership |
| BR46 | [MikeMirzayanov/testlib](https://github.com/MikeMirzayanov/testlib/tree/1e4e8a24c79c) | MIT | generators, validators, checkers, shrinkable adversarial cases | untrusted inputs execute only inside sealed test sandboxes |
| BR47 | [NyaanNyaan/library](https://github.com/NyaanNyaan/library/tree/b3981adc80a8) | CC0-1.0 | advanced graph, flow, convolution, dynamic-tree, and offline-query references | port only named mechanisms with proved consumers; no omnibus library import |
| BR48 | [ei1333/library](https://github.com/ei1333/library/tree/6313dbc29c40) | Unlicense | independent advanced graph/data-structure implementations and cross-oracles | normalize undefined behavior, integer bounds, and recursion before any port |
| BR49 | [ecnerwala/cp-book](https://github.com/ecnerwala/cp-book/tree/11b8e228b33f) | CC0-1.0 | compact flow, matching, geometry, strings, and dynamic-structure references | terse contest contracts require independent specification and property tests |
| BR50 | [bqi343/cp-notebook](https://github.com/bqi343/cp-notebook/tree/292c614b7b83) | CC0-1.0 | contest-hardened algorithms and notebook organization for narrow adapters | no prestige admission; every adapter needs bounds, invariant, oracle, and crossover |

### 2.1 Rejected or quarantined repositories

- `restatedev/restate` is useful durable-execution evidence, but its 2026-07-14
  tree is Business Source License 1.1, not a permissive open-source quarry. No
  Restate code enters GALAXY; the architecture may cite its public semantics.
- `kth-competitive-programming/kactl` is a high-value ICPC reference, but no
  repository license was detected. It is concepts/fixtures-only unless explicit
  permission is established.
- `cp-algorithms/cp-algorithms` is CC-BY-SA-4.0. Its explanations may guide
  research with attribution, but source is not copied into the trusted kernel.
- Official IOI and ICPC task statements/editorials are primary reduction and
  adversarial-fixture evidence, not source-code quarries.

---

## 3. Canonical frontier-paper registry — exactly 35

Each row separates the reported mechanism from GALAXY's engineering hypothesis.
Paper results never transfer across workloads without a preregistered experiment.

| ID | Primary source / status | GALAXY hypothesis and consumer | Required experiment and falsifier |
|---|---|---|---|
| FR01 | [Agentix: An Efficient Serving Engine for LLM Agents as General Programs](https://www.usenix.org/conference/nsdi26/presentation/luo), NSDI 2026 | program-level dependency/attained-service scheduling can reduce Pulsar end-to-end objective latency | replay identical workloads against FIFO and current lexicographic policy; reject if tails, fairness, or cancellation safety regress |
| FR02 | [FlexLLM](https://www.usenix.org/conference/nsdi26/presentation/oliaro), NSDI 2026 | dependency pruning and hybrid token scheduling may improve provider-lane SLO attainment | shadow only with real provider limits; reject if model quality, hard-deadline proof, or total cost worsens |
| FR03 | [AI Metropolis](https://proceedings.mlsys.org/paper_files/paper/2025/hash/4f31327e046913c7238d5b671f5d820e-Abstract-Conference.html), MLSys 2025 | true-dependency tracking can expose safe out-of-order multi-agent execution | compare global barriers with exact dependency cuts; any causal violation or insignificant end-to-end gain falsifies |
| FR04 | [ThunderServe](https://proceedings.mlsys.org/paper_files/paper/2025/hash/c2a0e26dd9ee7d57e92bb1c24b39659a-Abstract-Conference.html), MLSys 2025 | heterogeneous placement plus bounded rescheduling may improve local provider/worker utilization | test workload shifts and worker loss; reject if replan overhead or instability beats the incumbent |
| FR05 | [SOLA](https://proceedings.mlsys.org/paper_files/paper/2025/hash/bc82dbfbfa43232be85b8d9838f49c3e-Abstract-Conference.html), MLSys 2025 | request- and system-state-aware ordering may improve SLO attainment without mega-scores | preregister TTFT/TPOT analogues for GALAXY attempts; reject if cross-mission fairness or tail risk degrades |
| FR06 | [Real-Time Reasoning Agents in Evolving Environments](https://openreview.net/forum?id=n1AvXiU2lu), ICLR 2026 | parallel bounded-reactive and deep-planning lanes may improve deadline-sensitive decisions | equal-compute trial against either lane alone; reject if merge overhead or stale plans erase gains |
| FR07 | [Reinforcement Learning for Machine Learning Engineering Agents](https://openreview.net/forum?id=mfIbSouoaZ), ICLR 2026 | duration-aware credit and instrumented partial rewards may improve Supernova scheduler-policy trials | offline/shadow only; reject if partial rewards select fast low-value behavior or fail temporal holdout |
| FR08 | [On Training Large Language Models for Long-Horizon Tasks](https://openreview.net/forum?id=PnHfrCMKtp), ICML 2026 | higher-level actions and explicit subgoals can reduce effective execution horizon | matched tasks with/without macro actions; reject on hidden correctness loss or worse recovery localization |
| FR09 | [Scaling Long-Horizon Agent via Context Folding](https://openreview.net/forum?id=lNRgWoGfYg), ICML 2026 | branch/fold sub-trajectories can reduce active context while preserving continuation state | require exact hard-pin/causal coverage; any omitted acceptance fact or non-inferior-token failure rejects |
| FR10 | [AMemGym](https://openreview.net/forum?id=sfrVLzsmlf), ICLR 2026 | on-policy evolving-state tests reveal failures hidden by static memory benchmarks | add structured state evolution and abstention labels; reject benchmark transfer if simulated-user artifacts dominate |
| FR11 | [MemGAS](https://openreview.net/forum?id=i2yIvZARnG), ICLR 2026 | entropy-routed memory granularity may improve completeness/noise trade-offs | compare fixed chunk sizes under equal budgets; reject if hard-pin recall or latency regresses |
| FR12 | [MAGMA](https://aclanthology.org/2026.acl-long.1709/), ACL 2026 | separate semantic, temporal, causal, and entity graphs may reduce retrieval interference | ablate each graph on production-shaped queries; reject if one simple typed graph matches quality and cost |
| FR13 | [Grounding Agent Memory in Contextual Intent](https://aclanthology.org/2026.findings-acl.584/), ACL Findings 2026 | intent-compatible retrieval may suppress semantically similar but scope-wrong history | construct repeated-entity/different-goal traps; any authority omission or no gain over typed filters rejects |
| FR14 | [Agent Workflow Memory](https://proceedings.mlr.press/v267/wang25bx.html), ICML 2025 | induced reusable workflows may reduce steps on recurring tool tasks | temporal holdout with workflow provenance; reject on stale-workflow harm or no end-to-end benefit |
| FR15 | [MemoryAgentBench](https://openreview.net/forum?id=DT7JyQC3MR), ICLR 2026 | competency-separated evaluation better diagnoses Accretion than one aggregate score | map each competency to local fixtures; reject unmappable or model-judge-only dimensions |
| FR16 | [MemSyco-Bench](https://arxiv.org/abs/2607.01071), 2026 preprint | consistency/coordination tests may expose multi-memory synchronization failures | reproduce locally with deterministic labels; preprint remains hypothesis-only until replication succeeds |
| FR17 | [RigorBench](https://arxiv.org/abs/2606.22678), 2026 preprint | separate planning, verification, recovery, abstention, and atomic-transition metrics reveal false success | add independent gold labels and no composite hiding; reject any metric without reproducible local scoring |
| FR18 | [TraceLab](https://arxiv.org/abs/2606.30560), 2026 preprint | common sanitized traces can diagnose provider/harness capacity and process failure | validate schema coverage and secret stripping; reject if instrumentation changes outcomes or leaks data |
| FR19 | [SWE-Gym](https://proceedings.mlr.press/v267/pan25g.html), ICML 2025 | executable repository environments and trajectory verifiers can improve agent evaluation/training | local held-out repositories and contamination controls; reject if gains do not transfer temporally |
| FR20 | [Otter](https://proceedings.mlr.press/v267/ahmed25b.html), ICML 2025 | issue-derived tests plus rule repair can strengthen pre-patch acceptance contracts | compare against human tests and hidden regressions; reject tests that overfit candidate patches |
| FR21 | [ABC-Bench](https://aclanthology.org/2026.findings-acl.1142/), ACL Findings 2026 | full backend lifecycle and external API tests expose failures missed by unit-only tasks | reproduce representative multi-language services; reject if environment noise overwhelms agent signal |
| FR22 | [TDFlow](https://aclanthology.org/2026.eacl-long.70/), EACL 2026 | forced propose/debug/revise/test role separation may reduce context burden and confirmation bias | fixed-compute ablation against one agent; reject if role split adds cost without hidden-quality gain |
| FR23 | [REXBENCH](https://aclanthology.org/2026.acl-long.745/), ACL 2026 | research-extension tasks test implementation novelty beyond issue patching | temporal repository holdout with executable claims; reject if evaluation depends on subjective paper matching |
| FR24 | [Process-Level Trajectory Evaluation for Environment Configuration](https://openreview.net/forum?id=Q8qgloDKUO), ICLR 2026 | stage-level setup/diagnosis/repair labels improve failure localization | inject controlled environment faults; reject labels that cannot be independently reproduced |
| FR25 | [SecureVibeBench](https://aclanthology.org/2026.acl-long.1107/), ACL 2026 | combined functional and security oracles expose insecure-success patches | run static, dynamic, and regression oracles; any functionality-only promotion is forbidden |
| FR26 | [ToolSafe](https://aclanthology.org/2026.findings-acl.1850/), ACL Findings 2026 | proactive step-level tool-call checks may block unsafe actions while preserving benign completion | deterministic policy baseline plus attack suite; reject if model guard becomes sole authority or benign failure rises |
| FR27 | [SafeAgent](https://aclanthology.org/2026.acl-long.1501/), ACL 2026 | a structured instruction/context/action threat model can improve adversarial test generation | require human-reviewed taxonomy coverage and real terminal fixtures; reject synthetic-only gains |
| FR28 | [ShieldAgent](https://proceedings.mlr.press/v267/chen25ae.html), ICML 2025 | explicit policy extraction and executable checking may assist action-trajectory shielding | compare with hand-authored policies; reject probabilistic rule output as hard authorization |
| FR29 | [Make Agent Defeat Agent](https://www.usenix.org/conference/usenixsecurity25/presentation/liu-fengyu), USENIX Security 2025 | directed greybox fuzzing can discover taint-style agent vulnerabilities more efficiently | run only in sealed fixtures with semantic/distance feedback ablations; reject unverifiable findings |
| FR30 | [Unveiling Privacy Risks in LLM Agent Memory](https://aclanthology.org/2025.acl-long.1227/), ACL 2025 | black-box extraction tests can measure Accretion memory leakage | seed unique canaries across scopes and roles; any cross-scope recovery is a hard failure |
| FR31 | [A brain-inspired agentic architecture to improve planning with LLMs](https://www.nature.com/articles/s41467-025-63804-5), Nature Communications 2025 | separating conflict monitoring, prediction, evaluation, decomposition, and coordination may improve planning | equal-compute modular ablation; reject biological analogy as authority or if a monolith matches outcomes |
| FR32 | [BOAD](https://openreview.net/forum?id=O6stE173BD), ICLR 2026 | budgeted bandit selection may find effective software-agent hierarchies | nested holdout prevents topology overfit; reject unstable arms or no gain over fixed small portfolios |
| FR33 | [Dyna-Mind](https://openreview.net/forum?id=F848aPzCJy), ICLR 2026 | structured future simulation before action may improve long-horizon interactive planning | compare search depth under fixed compute; reject if imagined transitions contaminate hard facts |
| FR34 | [MOC](https://openreview.net/forum?id=wyynWicO5s), ICML 2026 | multi-hop evidence streams plus structural consolidation may reduce redundant agent communication | compare direct-neighbor/full-broadcast controls; reject on provenance loss or no token-adjusted gain |
| FR35 | [NaviAgent](https://openreview.net/forum?id=omRyEle4jZ), ICML 2026 | separating high-level planning from a tool-relation execution graph may scale tool orchestration | test unseen tools and dependency changes; reject if graph staleness or repair cost exceeds sequential planning |

---

## 4. Pulsar scheduler brownfield projection

This matrix is a research queue, not a change to the frozen live hierarchy. Every
candidate runs first in deterministic replay, then shadow, and can only become a
new protected policy generation through Quark and Supernova qualification.

| Scheduler mechanism | Repository evidence | Paper evidence | First experiment | Hard rejection |
|---|---|---|---|---|
| fair-share and dominant resources | BR27, BR29, BR35 | FR05 | compare mission DRF debt with framework-inspired fair queues on adversarial mixed resources | starvation, priority inversion, or authority trade-off |
| critical-path and attained-service ordering | BR28, BR33 | FR01, FR03 | program-DAG replay against current mission-major tuple | cross-mission starvation or no tail/makespan gain |
| bounded work stealing | BR27, BR28 | FR03 | steal only capability-compatible, unfenced, unreserved work | locality/capability/fence violation or oscillation |
| backpressure and admission | BR27, BR30, BR32, BR35 | FR02, FR05 | queue saturation, provider quota, slow consumer, and recovery bursts | dropped authority event, retry storm, or unbounded queue |
| durable timers and wakeups | BR24, BR25, BR30 | FR01 | compare exact scan, heap, and ORBIT wheel across sparse/dense timer shapes | early wake, lost wake, boot-time ambiguity, or no crossover |
| replay and crash recovery | BR12, BR24, BR25, BR26, BR31 | FR17, FR18 | seeded crash matrix around claim/reserve/issue/observe boundaries | duplicate effect, false success, or unreplayable history |
| heterogeneous placement | BR27, BR29, BR33, BR34 | FR04 | exact small-cohort oracle plus heuristic at production shapes | infeasible assignment, missing witness, or unstable replan |
| deterministic simulation | BR12, BR31, BR44, BR46 | FR17 | virtual clock/disk/RNG/provider/CLI faults with seed+commit replay | non-reproducible failure or incomplete liveness closure |

---

## 5. Competitive-systems admission queue

The phrase “ICPC/IOI-grade” describes technique sophistication, not correctness or
fitness. Official IOI/ICPC solutions and BR04/BR05/BR44..BR50 expand the quarry;
they do not bypass Quark.

| Candidate family | Likely GALAXY consumer | Mandatory invariant/oracle | Admission trigger | Reject when |
|---|---|---|---|---|
| min-cost flow, assignment, matching | Pulsar small-cohort placement; Quark exact oracle | witness recomputes feasibility and objective; brute-force oracle on tiny cases | measured placement/search bottleneck with closed integer bounds | interactions violate separability or simple enumeration wins |
| SCC, dominators, transitive bitsets | dependency impact, criticality, context causality | reachability equivalence against graph scan/NetworkX | repeated complete directed graph queries dominate | graph is incomplete, stale, or too small |
| rollback DSU and segment-tree time | sealed counterfactual timelines | rollback restores exact prior state; naive replay oracle | immutable offline batches with many interval updates | live directed causality or online mutation is required |
| link-cut/Euler-tour/dynamic trees | one-parent active lineage only | forest and path aggregate equal parent-chain oracle | telemetry proves high-churn forest queries dominate | joins/DAG truth or low query volume |
| persistent segment/wavelet/order-statistic structures | temporal history and bounded analytics | version immutability and scan-equivalent answers | repeated historical queries dominate storage/conversion | SQLite/index scan remains faster end to end |
| Li Chao/convex-hull optimization | affine packet/placement subproblem only | every candidate line and query domain is complete; enumeration oracle | a real affine envelope with many repeated queries exists | utility is non-affine or candidate portfolio incomplete |
| Aho-Corasick/string automata | evidence/log multi-pattern scans | every pattern compiled; direct hits never dropped | pattern count and corpus size beat repeated search | tiny pattern set or unstable normalization |
| adversarial generators/checkers | Quark qualification and DST | checker independence; known-bad corpus rejected; shrink preserves failure | every new algorithm backend | generator and implementation share the same bug ancestry |

Every admitted card records input bounds, latency target, correctness invariant,
simple oracle, benchmark distribution/seeds/hardware, crossover threshold, and
fallback. Advanced machinery without those fields remains dormant.

---

## 6. Package projection map

| Consumer document | Canonical projection |
|---|---|
| GALAXY design | registry authority, cross-system harness/sandbox/provenance posture, paper portfolio |
| Qualified capability topology | BR11, BR13..BR23, BR38..BR43; FR17..FR35 |
| Pulsar scheduler topology | BR12, BR24..BR35, BR44, BR46; FR01..FR08, FR17..FR18 |
| Quark solver topology | BR02, BR04..BR06, BR10, BR33..BR34, BR44..BR50 |
| Accretion context topology | BR01, BR07..BR09, BR36..BR37; FR09..FR16, FR30 |
| Readiness ledger | exact counts, provenance gates, validation commands, and unresolved implementation evidence |

No projection may add a repository or paper to the package count. Membership
changes require editing this registry, incrementing its revision, updating all
affected projections, and regenerating the package SHA-256 manifest.
