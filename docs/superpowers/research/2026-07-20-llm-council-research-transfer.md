# LLM Council research-transfer intake

Status: captured public research; no trial authority; no runtime authority.

Captured at: `2026-07-20T03:00:25Z`

Upstream baseline revision: `karpathy/llm-council@92e1fccb1bdcf1bab7221aa9ed90f9dc72529131`

This artifact preserves paraphrased claims and exact credentialless HTTP-response
fingerprints. It does not copy source code, import an upstream implementation, or
authorize a council invocation. The broad last-30-days discovery corpus is retained
separately in
`docs/superpowers/research/karpathy-llm-council-and-advanced-multi-agent-deliberation-raw-2026-07-19.md`;
social results in that corpus are discovery leads, not qualification evidence.

## Captured claims

### C1 — Karpathy baseline

- Source: `https://raw.githubusercontent.com/karpathy/llm-council/92e1fccb1bdcf1bab7221aa9ed90f9dc72529131/README.md`
- Locator: `README.md`, three-stage workflow and final project-status paragraph.
- Source class: primary.
- Response SHA-256: `0f21b96fd783f74ed1599a7a831d75d9718a4876b42da5db2d931cb1442f4245`
- Claim: The pinned project fans one query out into independent first opinions,
  anonymizes model identities for peer ranking on accuracy and insight, and gives a
  designated chairman all responses for final synthesis. Its author describes it as
  an unsupported Saturday experiment supplied for inspiration, not as a
  qualified production authority system.

The GitHub commit response used to pin that revision had SHA-256
`b16d075860506fab17c77c6c6f6c6e8100047935c03516e55477e567bef3a416`.

### C2 — Selective deliberation

- Source: `https://aclanthology.org/2026.acl-industry.93/`
- Locator: abstract for *CascadeDebate: Multi-Agent Deliberation for Cost-Aware LLM Cascades*.
- Source class: primary peer-reviewed publication record.
- Response SHA-256: `fa0f1bd8ab8d22ae3ab987d80a74903aa43ef15cc1e0fe9d9c5ef687e45066b3`
- Claim: CascadeDebate inserts deliberation only at confidence-based escalation
  boundaries. Its abstract reports evaluation on five benchmarks, improvement up to
  26.75 percent over its named baselines, and 20.98–52.33 percent relative accuracy
  improvement from an online threshold optimizer over fixed policies. These reported
  effects motivate a preregistered value-of-information gate; they are not portable
  performance guarantees for GALAXY workloads.

### C3 — Diversity and calibrated confidence

- Source: `https://aclanthology.org/2026.findings-acl.1694/`
- Locator: abstract for *Demystifying Multi-Agent Debate: The Role of Confidence and Diversity*.
- Source class: primary peer-reviewed publication record.
- Response SHA-256: `6baa37e6327f785e7ebcdf9ba2bb764b0148533374c34540af6b75215fd47f77`
- Claim: The paper reports that vanilla debate can underperform majority vote despite
  greater compute, identifies diverse initial viewpoints and calibrated confidence
  exchange as missing mechanisms, and reports gains over both vanilla debate and
  majority vote across six reasoning-oriented QA benchmarks. GALAXY must therefore
  retain no-council, single-model, and majority-vote controls rather than assuming
  that more deliberation is better.

### C4 — Sparse trust-aware communication

- Source: `https://export.arxiv.org/api/query?id_list=2606.01828`
- Locator: Atom entry summary for *Dynamic Trust-Aware Sparse Communication Topology for LLM-Based Multi-Agent Consensus*.
- Source class: primary preprint record.
- Response SHA-256: `48fbb14ee893e7a4a8344ad43f5b569e280e5c80b53093bd49c5ec3f95adb363`
- Claim: DySCo scores candidate communication edges using agent reliability, answer
  divergence, and task relevance; selects a budgeted sparse subset; aggregates with
  dynamic trust weights; and stops early after stable consensus. These are candidate
  shadow mechanisms only, subject to independent reproduction and dissent-retention
  tests.

### C5 — Diverse paths and disagreement-triggered verification

- Source: `https://export.arxiv.org/api/query?id_list=2601.05746`
- Locator: Atom entry summary for *DynaDebate: Breaking Homogeneity in Multi-Agent Debate with Dynamic Path Generation*.
- Source class: primary preprint record.
- Response SHA-256: `3eace02e046d671f38447ab0a1c5f5d55408f985994aa70a7af0beac4419c808`
- Claim: DynaDebate allocates deliberately varied reasoning paths, critiques reasoning
  processes rather than only final answers, and activates an external tool-using
  verifier when disagreement persists. GALAXY may test these mechanisms only through
  credentialless verification and bounded advisory receipts.

### C6 — Judge qualification

- Source: `https://export.arxiv.org/api/query?id_list=2605.21748`
- Locator: Atom entry summary for *RankJudge: A Multi-Turn LLM-as-a-Judge Synthetic Benchmark Generator*.
- Source class: primary preprint record.
- Response SHA-256: `61058ef05b4a0094158e31a509791bf8276da6ac04fddeee0f27160ca15baae4`
- Claim: RankJudge constructs unambiguously labelled paired conversations with one
  localized injected flaw and uses them to evaluate judge reliability. This supports
  qualifying council reviewers on hidden, failure-localized fixtures instead of
  treating model rankings as ground truth.

## Local transfer hypothesis

The frozen GALAXY Flare/Nebula design can exceed the fixed three-stage baseline if,
and only if, it combines isolated first passes, blinded review, provider/session and
evidence-lineage correlation controls, selective value-of-information admission,
typed contradiction and uncertainty exchange, qualified external verification,
dissent-preserving advisory synthesis, immutable receipt chains, calibrated outcome
resolution, and bounded capacity. The legacy council cannot make that claim.

## Required falsification

Reject or retire the transfer if, under identical fixtures, provider subscriptions,
time, concurrency, and cost/capacity budgets, the candidate fails material benefit
against no-council, single-model, majority-vote, and pinned Karpathy-style baselines;
increases correlated error, calibration error, scope violations, false promotion, or
tail latency beyond the frozen gates; allows self-ranking, identity leakage, hidden
fallback, transcript contamination, chairman authority, or post-seal mutation; or
cannot preserve dissent and hard obligations through crash, replay, expiry,
revocation, and rollback campaigns.

## Admission state

- Canonical FR registry admission: absent.
- Experiment manifest: absent.
- Trial requested: no.
- Evidence state: `specified` research-transfer baseline only.
- Runtime authority: false.
- Shadow only: true.
- Required-control closure: isolated first passes; blinded review and self-exclusion;
  provider/session/evidence correlation firewall; selective VOI/capacity admission;
  sparse bounded exchange; disagreement-triggered qualified verification; judge
  qualification; dissent-preserving synthesis; calibration and baseline ablations;
  invocation idempotency and immutable receipts; and advisory-only output.
- Status recheck: `2027-01-08T00:00:00Z`, before the frozen all-transfer
  `2027-01-09T00:00:00Z` deadline.
- Next review: after Stage 7 dependencies and before Stage 8 trial preregistration.
