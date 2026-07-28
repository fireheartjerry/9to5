# GALAXY R3 implementation recovery checkpoint

Recorded: 2026-07-20T14:14:01-04:00, America/Toronto

Purpose: preserve the complete objective, authority boundaries, documentary
chain, implementation state, evidence, and next actions for a very long
multi-stage implementation. This document is intentionally detailed. It is a
checkpoint, not a replacement for an approved specification, child plan,
receipt, GraphWarrant, or installed-controller record.

> Addendum 2026-07-28 (Claude executor session): resumed the AJ15b FIX-FIRST
> boundary and closed its one open RED
> (`test_native_publication_refuses_partial_at_directory_ceiling_untouched`) via
> a reserve-first/cleanup-after unification in
> `platform_core/core/fsio.py::_reconcileCreateOnlyFileAdmitted`. fsio +
> credential_broker suites: 294 passed / 89 skipped / 0 failed on Python
> 3.11.15/Windows; ruff, mypy, compile, diff-check clean. AJ15b remains OPEN
> (`[ ]`) pending the Python 3.12 lane, POSIX/WSL replay, and corrected
> independent review; AJ15c is untouched. No commit; the shared dirty worktree
> was preserved. Full evidence:
> `docs/superpowers/reports/2026-07-28-aj15b-prospective-debris-ceiling-fix.md`.
>
> Same session, second slice — **AJ15c clause (a)**: `prepare()` re-proved
> artifact/parser/coordinator identity but never re-proved run-admission
> *liveness*, so an authority revoked after construction still reached
> snapshot-admission issuance. Added `_requireLiveRunAdmission()` to
> `_revalidateInstalledArtifacts` (verbatim reuse of the existing
> `__init__`/`productionReady` check); RED-first test
> `test_installed_clone_prepare_refuses_revoked_run_admission`. AJ15c remains
> OPEN — its clause (b)/(c) residuals are ambiguous and were deliberately not
> guessed at. Evidence:
> `docs/superpowers/reports/2026-07-28-aj15c-run-admission-use-time-revalidation.md`.
>
> Consolidated session verification: **720 passed, 91 skipped, 1 failed**, where
> the single failure
> (`test_external_controller_state.py::test_runtime_install_constructor_cleanup_ambiguity_poison_is_permanent`)
> was **proved pre-existing** by temporarily reverting the AJ15b edit and
> byte-compare-restoring it. It needs separate triage. No commit; the shared
> dirty worktree was preserved throughout.

## 1. Overall goal

Fully implement and verify the approved GALAXY R3 package in the isolated
implementation worktree. The scope includes the transactional kernel, Windows
controller boundary, durable commands and effects, provider-neutral drivers,
Pulsar scheduler, Quark solver portfolio, Accretion context plane, Supernova
experiments and adaptive intelligence, qualified topology overlays, Orrery
read-only projections, and final matched qualification.

All specified overlays may be implemented, but production influence is granted
only to dependency-closed subsets whose exact evidence and GraphWarrant gates
pass. Failed, expired, revoked, unavailable, or not-yet-qualified candidates
must remain non-authoritative. Voyager must remain disabled until it receives
its own workload-scoped warrant.

The completion standard is not merely “code exists.” Completion requires:

- every approved child-plan task implemented and verified;
- the structural topology counts and contracts remaining exact;
- all active capabilities covered by current external authority;
- deterministic crash, replay, expiry, revocation, rollback, and recovery
  campaigns passing;
- matched outcome evidence against the pinned incumbent;
- a reproducible final evidence dossier; and
- safe non-activation of every candidate that did not pass.

## 2. Authoritative hierarchy

When sources disagree, do not improvise a weaker interpretation. Stop the
affected implementation path and reconcile against this hierarchy:

1. The seven immutable 2026-07-14 specification documents.
2. Their frozen authority ordering, closed enums, receipt schemas, numerical
   gates, non-goals, and threat boundaries.
3. The migrated implementation plans whose hashes are registered in
   config/galaxy/artifacts.v1.json.
4. Machine-readable manifests and external receipts that satisfy those
   requirements.
5. This checkpoint and ordinary source comments only as navigation evidence.

Neither generated repository maps nor this checkpoint can activate runtime
authority.

### 2.1 Approved package, exact read order

Start with
[the package README](../specs/2026-07-14-galaxy-r3-package-README.md) and verify
[SHA256SUMS](../specs/2026-07-14-galaxy-r3-SHA256SUMS). Then read:

1. [System design](../specs/2026-07-14-galaxy-r3-design.md)
   - System thesis, security and authority model, appendix A rename map,
     deterministic simulation, and final qualification gates.
2. [Brownfield/frontier registry](../specs/2026-07-14-galaxy-r3-brownfield-frontier-registry.md)
   - Canonical BR01..BR50 and FR01..FR35 evidence records, source passports,
     research-transfer constraints, and admission queues.
3. [Qualified capability topology](../specs/2026-07-14-galaxy-r3-qualified-capability-topology.md)
   - Node/edge contract and manifest definition of done.
4. [Pulsar R1 topology](../specs/2026-07-14-galaxy-r3-pulsar-r1-qualified-topology.md)
   - Scheduler contracts, progress obligation, mission-major trade-off, and
     research laboratory.
5. [Quark R2 topology](../specs/2026-07-14-galaxy-r3-quark-portfolio-r2-qualified-topology.md)
   - Advisory solver substrate, qualified quarries, and P0–P4 admission.
6. [Accretion R1 context virtualization](../specs/2026-07-14-galaxy-r3-accretion-context-virtualization-r1.md)
   - Context contracts, exact hard obligations, lineage, packet compilation,
     paging, retention, and provider-session freshness.
7. [Preimplementation readiness ledger](../specs/2026-07-14-galaxy-r3-preimplementation-readiness-ledger.md)
   - Frozen audit record; read its banner before relying on any row.

At this checkpoint, every specification, migrated implementation plan, and
registered research artifact re-hashed exactly against
[config/galaxy/artifacts.v1.json](../../../config/galaxy/artifacts.v1.json).

### 2.2 Child implementation plans

- [Transactional kernel](../plans/2026-07-13-galaxy-r3-transactional-kernel.md)
  - Five tasks. Tasks 3 and 4 form the immediate atomic source wave; Task 5
    closes maps, failure injection, independent review, evidence, and exact
    installed-LKG activation.
- [Pulsar R1 implementation](../plans/2026-07-13-galaxy-r3-pulsar-r1-implementation-plan.md)
  - Seventeen sequential scheduler tasks.
- [Quark R2 implementation](../plans/2026-07-13-galaxy-r3-quark-r2-implementation-plan.md)
  - Fourteen sequential advisory-solver tasks.
- [Accretion R1 implementation](../plans/2026-07-13-galaxy-r3-accretion-r1-implementation-plan.md)
  - Twenty-two sequential context-plane tasks and AC-R01..AC-R34 coverage.

The exact hashes live in
[the artifact registry](../../../config/galaxy/artifacts.v1.json); do not copy
hashes from prose when the registry can be checked directly.

### 2.3 Stage receipts and machine records

- [Stage 0 receipt](../reports/2026-07-14-galaxy-r3-stage-0-receipt.json)
- [Stage 1 receipt](../reports/2026-07-14-galaxy-r3-stage-1-receipt.json)
- [Stage 2 prerequisite audit](../reports/2026-07-14-galaxy-r3-stage-2-prerequisite-audit.json)
- [Artifact/hash registry](../../../config/galaxy/artifacts.v1.json)
- [Research-transfer registry](../../../config/galaxy/research-transfers.v1.json)
- [Topology manifest](../../../config/galaxy/topology.v1.json)
- [Truth-gap registry](../../../config/galaxy/truth-gaps.v1.json)
- [Pinned incumbent baseline](../../../config/galaxy/incumbent-baseline.v1.json)
- [Activation image lock](../../../bootstrap/galaxy_launcher/activation_images.lock.json)
- [Closed activation acceptance matrix](../../../bootstrap/galaxy_launcher/activation_acceptance.json)
- [Controller runtime lock](../../../bootstrap/galaxy_launcher/runtime.lock.json)
- [Launcher bundle manifest](../../../bootstrap/galaxy_launcher/manifest.json)
- [SHA-1 collision-detection source passport](../../../bootstrap/galaxy_launcher/sha1dc_source_passport.json)
- [Kimi K3 retained raw artifact](../research/kimi-k3-last30days/kimi-k3-open-weight-model-architecture-benchmarks-integration-raw-v3.md)
- [Kimi K3 hosted-wire erratum](../research/2026-07-20-kimi-k3-hosted-wire-erratum.md)
- [Council research-transfer artifact](../research/2026-07-20-llm-council-research-transfer.md)

Research records registered by the artifact ledger:

- state/research/last30days/ai-agent-scheduling-long-horizon-autonomous-systems-local-first-ai-operating-systems-task-orchestration-raw-pulsar-r1-2026-07-13.md
- state/research/last30days/scheduling-compact.md

Research may influence preregistered trials only through a
ResearchTransferRecord; it is never runtime authority by itself.

## 3. Execution contract to preserve

- Work sequentially by approved stage and child-plan task.
- Use a dedicated worktree and preserve unrelated or pre-existing changes.
- Use failing-test-first implementation: observe RED, make the smallest safe
  implementation, obtain focused GREEN, run affected tests, then commit.
- Keep one coherent child-plan task per commit, except where the approved plan
  explicitly requires an atomic multi-task wave.
- Run python tools/dev.py check for focused source changes, affected tests
  before commits, and the full suite at stage boundaries.
- Keep external_spend_allowed false. Unknown price, quota, or capacity remains
  unknown and fails closed; it is not silently treated as zero.
- Brownfield source enters only with a complete SourcePassport.
- Provider papers and frontier research never acquire execution authority.
- Target-repository .env, provider configuration, state, logs, caches,
  knowledge, and vault paths remain inert to the installed controller.
- A committed terminal result wins a cancellation race. Otherwise accepted
  cancellation terminates the attempt and late output is ignored evidence.
- Replayed invocation or resume requests return the existing durable outcome.
- Production activation is external, exact-generation, expiring, revocable,
  dependency-closed, and rollback-bound.

## 4. Worktree continuation anchor

- Worktree:
  C:\Users\fireh\.config\superpowers\worktrees\9to5\galaxy-r3-implementation
- Branch: galaxy-r3-implementation
- Checkpoint HEAD: 5c8ca5cce409c4b41fde4c9c28ce5252ff53da43
- Pre-checkpoint-bundle status snapshot: 277 entries, comprising 184 modified
  and 93 untracked.
- Audit snapshot at 2026-07-19T18:23:38-04:00, after checkpoint and
  research-transfer additions: 285 entries, comprising 184 modified and
  101 untracked.
- Audit snapshot at 2026-07-20T07:45:09-04:00: 316 entries, comprising 205
  modified-like and 111 added or untracked entries.
- Both counts are historical observations. Recompute live status with
  `git status --short --untracked-files=all`; never interpret count drift as
  permission to discard an entry.
- This dirty state is expected. It includes the current transactional-kernel
  wave, generated maps, tests, manifests, and new implementation modules.
- Never run git reset --hard, git clean, checkout-based mass restoration, or
  any equivalent destructive operation against this worktree.

Recent commits that materially explain the branch:

- 5c8ca5cc — close Task 1 bootstrap manifest.
- 133192f9 — correct Task 2 implementation manifest.
- 029617a6 — add exact partial TOFU recovery.
- 5e9e303c — isolate main.py launch lifecycle seams.
- ca6fb1f3 — harden llm_io retries and structured extraction.
- 4d1a2e6b — resolve repository-map imports against tracked modules.
- ff4db68f — seal the transactional-kernel foundation.
- d209acf9 — record Stage 1 evidence.
- 3bea8f78 and 48842037 — Stage 0 migration/topology work, referenced by the
  Stage 0 receipt.

Do not commit the current kernel Task 3/4 changes separately: the child plan
requires the final Task 3 plus Task 4 source wave to be atomic.

## 5. Current stage state

### Stage 0 — artifact migration and immutable baseline

Status: completed with a stage receipt.

Evidence includes exact migrated artifact hashes, base 71-node/95-edge topology,
core 131/250, disabled federation-ready 134/256, incumbent baseline pinning,
workflow validation, and a recorded baseline failure set.

The current topology file contains 134 nodes and 256 edges:

- base: 71 nodes;
- Flare/Magnetosphere: 16;
- Nebula: 21;
- Pulsar: 19;
- Quark: 4;
- Voyager: 3.

All 134 node source maturities remain specified in the checked manifest. That is
not a defect and must not be “fixed” merely to imply runtime progress.

### Stage 1 — truth freeze and shadow evidence

Status: completed with a stage receipt.

The receipt records zero paid/network provider calls, external spend disabled,
truth-gap evidence freshness, immutable shadow experiment receipts, unknown
synthetic metrics, and no active overlays or GraphWarrants.

### Stage 2 — transactional Singularity kernel

Status: in progress; production authority remains unchanged and inactive.

Task 1 and Task 2 foundation source and manifests are substantially landed.
Current uncommitted work extends their protected object protocol and closes
brownfield regressions. The next approved implementation wave is:

1. Task 3 — every retry receives a fresh prepare/execute/verify/promote
   transaction, exact-revision verification, and one idempotent TaskState
   acknowledgement seam.
2. Task 4 — linear, Society, parallel, and tournament paths use one promotion
   authority; every branch is staged and verified, only one selected branch may
   promote, and no post-seal mutation is permitted.
3. Task 5 — truth-surface closure, repository maps, deterministic failure
   injection, independent review, final evidence, and only then exact installed
   LKG activation.

Do not activate at the end of Task 4. The child plan explicitly postpones
activation until Task 5 independent review reaches the exact fixed point.

### Stages 3–11

Status: no stage completion receipt and no production authority.

Some source scaffolding exists for later capabilities (including Claude/Codex
drivers and runtime boundaries), but source presence is not stage completion.
Use [the progress ledger](GALAXY-R3-PROGRESS.md) for the full task inventory.

## 6. Latest implemented and verified corrections

These corrections were made after the last committed Task 1/2 checkpoint and
must remain in the dirty wave unless deliberately reorganized under the plan.

### 6.1 Trajectory concurrency

Internal trajectory imports now use canonical
notifications.runtime.event_bus and
notifications.runtime.subprocess_feed modules. This avoids half-initialized
self-replacing compatibility facades during concurrent first import.

Evidence: 10 trajectory tests passed.

### 6.2 Exact verifier authority

Verifier tests and diagnostic helpers now issue exact
DiagnosticVerificationCommandAuthority. Bare or legacy production execution is
not restored. The production guard test proves refusal before process creation.

Evidence: 104 verifier tests and 6 subtests passed.

### 6.3 Native control-store corruption handling

The native ControllerStateStore validates durable flag types and the
pending_gate closed enum. Wrong-typed durable values fail to the supplied
default and are omitted from snapshots rather than becoming truthy policy.

Evidence: 38 focused control-store/error-hardening tests passed.

### 6.4 Standalone Claude metrics import

tools/claude_metrics.py establishes the repository root before platform imports,
so the status-line helper works from an unrelated current directory.

Evidence: 3 iteration-telemetry tests passed.

### 6.5 Packed Git object selection protocol

The admin-contained parent snapshot no longer supplies whole pack files to the
credentialless parser. It:

- catalogs loose names and pack indexes in external content-addressed state;
- asks the contained source-object-locate role for an exact loose object or pack
  offset/range;
- copies only the selected loose leaf or pack index, 12-byte header, and exact
  object range;
- runs source-object-frontier repeatedly to dependency closure;
- revalidates repository inventory, HEAD/ref/common-dir authority throughout;
  and
- binds the final selection transcript digest into the parser receipt.

Evidence:

- 4 loose/packed × primary/linked exact cases passed;
- 41 anchor host-isolation tests passed;
- 35 object-parser tests passed;
- 6 object-parser cases skipped only because the reviewed runtime images were
  not preloaded.

### 6.6 Repository map, llm_io, and main.py review work

The user supplied detailed review feedback for each file with explicit
instructions to apply only technically sound portions. The resulting commits
are already on this branch:

- Repository map: relative imports, tracked-inventory roots, known-module
  resolution, consistent test exclusion, annotated __all__, robust docstring
  encoding, indexed tests, and linear caller inversion.
- llm_io: pure response extraction, one accepted-response telemetry emission,
  normalized attempts, injected sleep/jitter, safer retry taxonomy, arrays and
  objects in loose JSON extraction, option validation, and a client reset seam.
- main.py: extracted terminal control, run lifecycle, and work-directory
  management; consolidated fresh/resume execution; tightened approval; and
  managed temporary directories.

Evidence:

- 66 combined focused feedback tests passed before map regeneration; the only
  failure was expected generated-map drift.
- Repository maps were regenerated after formatting.
- 21 repository-map tests then passed.
- git diff --check passed at this checkpoint.

### 6.7 Kimi K3 post-freeze research transfer

Kimi K3 became available as a hosted Kimi/API service on 2026-07-16. That
release and its future-weight announcement were researched with the
`last30days` workflow plus primary and independent web sources. The broad claim
that it beats every other model was rejected: independent evidence supports a
category-specific first place in Frontend Code Arena, not universal
superiority. At capture, the downloadable full weights, exact license,
immutable checkpoint revision/hashes, technical report, reproducible runtime
closure, and local 64-accelerator-class capacity were unavailable. The hosted
API is paid and prohibited by the zero-cost policy. Moonshot promised only the
full weights by 2026-07-27; it described the technical report as forthcoming
without assigning that report the same date.

Evidence and code:

- `docs/superpowers/research/2026-07-19-kimi-k3-last30days-plan.json`;
- `docs/superpowers/research/kimi-k3-last30days/` raw evidence, including
  exact HTTP-response fingerprints;
- `docs/superpowers/research/2026-07-20-kimi-k3-hosted-wire-erratum.md`, which
  fingerprints and distinguishes the general Kimi Open Platform from Kimi
  Code endpoints, model IDs, reasoning modes, entitlements, and fallbacks;
- `config/galaxy/research-transfers.v1.json`;
- `platform_core/core/research_transfer.py`; and
- `tests/platform/test_research_transfer.py`.

The record is content-addressed, binds each claim to its source-response digest
and retained research artifact, and rehashes both ledger and artifact through
bounded no-reparse/no-follow reads. Consumer/control/blocker enums are closed.
Even registered research requires an externally supplied exact qualification
context covering binding authentication, revocation, current/minimum
generation, registry row, record, claims, controls, falsifier, and manifest
before a shadow trial. K3 has no FR registry membership and requests no trial.
Its public-artifact evidence remains `unavailable`; its hosted service is
externally available but neither spend-authorized nor registered as a GALAXY
provider. The `ResearchTransferRecord` can never carry runtime authority.

Focused evidence: all 23 tests passed under Python 3.11 and Python 3.12, plus
ruff, direct mypy, exact artifact/digest validation, and targeted diff hygiene.
Independent re-review returned PASS for the 12-claim hosted-release,
provider-wire, entitlement, fallback, and no-authority closure.

Repository-map closure was then regenerated after adding the new source and
test to Git's intent-to-add inventory. The generated map reports 659 modules,
includes `platform_core.core.research_transfer`, and all 24 focused
repository-map/header tests passed.

### 6.7a Karpathy baseline and pre-execution council qualification transfer

The user requested a current comparison between Karpathy's `llm-council` and
GALAXY's pre-execution council. The `last30days` workflow retained a broad
social/GitHub/Hacker News discovery corpus, then the research pipeline captured
credentialless primary records for the pinned Karpathy README, CascadeDebate,
Demystifying Multi-Agent Debate, DySCo, DynaDebate, and RankJudge. Social
material remains discovery-only and was not used as qualification truth.

The pinned Karpathy revision is
`92e1fccb1bdcf1bab7221aa9ed90f9dc72529131`. It provides a useful fixed
baseline: independent first opinions, anonymized peer ranking, and chairman
synthesis. Its own README describes an unsupported Saturday experiment rather
than a production authority system.

The local source audit found that the current legacy 9to5 implementation is
not yet a heavily improved version. Its sequential default leaks earlier seat
outputs into nominally independent memos; it has no randomized opaque ballot,
self-review exclusion, or positional/self-preference audit; its synthesis is
deterministic application code with fixed confidence rather than a qualified
fresh role; and its target-tree logs are mutable files rather than an external
receipt chain. It remains default-off/non-authoritative. In contrast, the
frozen Flare/Nebula design specifies selective VOI admission, clean-room
independence, typed contradiction exchange, capacity accounting, immutable
advisory bundles, and calibration, but those topology rows are still only
`specified`.

Evidence and machine intake:

- `docs/superpowers/research/2026-07-19-llm-council-query-plan.json`;
- `docs/superpowers/research/karpathy-llm-council-and-advanced-multi-agent-deliberation-raw-2026-07-19.md`;
- `docs/superpowers/research/2026-07-20-llm-council-research-transfer.md`,
  SHA-256
  `00afba9ca9b3df93cbaa152fb734555afaae75edfc94ed85ba3a9f7f4bf098c9`;
- `config/galaxy/research-transfers.v1.json`, record
  `98c2a17ab4c5890a0a1246179d7b48e95a955d8eff9941f0e4ccf282d829dd64`;
- `platform_core/core/research_transfer.py`; and
- `tests/platform/test_research_transfer.py`.

The corrected record binds six sorted claims and 18 sorted closed controls:
isolated first passes, blinded review/self-exclusion, correlation firewall,
selective VOI/capacity admission, sparse bounded exchange,
disagreement-triggered verification, judge qualification,
dissent-preserving synthesis, calibration/ablations, idempotent immutable
receipts, exact provider/session bindings, and advisory-only output. Its
registry ID and experiment manifest are absent, it requests no trial, its
evidence state is `specified`, `runtime_authority` is false, and `shadow_only`
is true. The status recheck is 2027-01-08, before the frozen 2027-01-09
all-transfer deadline.

The first independent review returned FIX-FIRST for an overlong recheck,
misnamed DynaDebate/RankJudge locators, an unsupported commit-count phrase,
missing machine-bound council controls, and insufficiently granular Stage 8/9
tasks. All were corrected, every claim/artifact/record digest was regenerated,
and the source/ledger/test re-review returned PASS. All 24 research-transfer
tests passed on Python 3.11 and Python 3.12; ruff, direct mypy, loader rehashing,
and targeted `git diff --check` passed. This transfers research hypotheses and
falsifiers only; it does not import Karpathy code or grant council authority.
Independent checkpoint/task re-review also returned PASS after making
advisory status permanent, describing benefit as an unproven J1 hypothesis,
and adding typed CXR contradiction-loss ablations.

### 6.8 Task 3 durable acknowledgement seam

The first Task 3 persistence seam now uses the real `TaskState`
shape (`plan.subtasks` and `subtask_id`) and the canonical `AttemptJournal`
methods and phases. A promoted transaction derives one exact ordered receipt
chain from the durable journal, writes a detached
`promotion_persistence_pending` TaskState snapshot, acknowledges that exact
transaction in the journal, writes the terminal `done` snapshot, and only then
marks terminal-state persistence. The detached save path validates the task ID
and uses the already installed external controller store/authority when that
boundary is active; it never mutates live `TaskState.data` before durable save.

Focused crash-prefix tests now cover failure before the pending snapshot,
before journal acknowledgement, before the done snapshot, and after the done
snapshot but before the terminal flag. Replay preserves one recoverable receipt
chain. Unbound task/receipt chains and a different promoted transaction are
refused before save. The focused Python 3.11 packet reports 32 passed; focused
ruff and mypy checks passed.

Initial source subsequently added process-local persistence authority bound to
controller/watchdog generation, repository, journal root, deadline, and exact
transaction. The first focused control/journal packet passed 40 tests on Python
3.11 and 40 on Python 3.12. That count was implementation feedback, not
acceptance.

An independent fix-first review found eight blockers that supersede the earlier
optimistic assessment:

1. a public injectable snapshot callback can acknowledge a no-op write;
2. no orchestrator state lock or stable-ID reacquisition fences concurrent
   copy/save/apply;
3. no all-attempt monotone reducer makes a durable winner dominate stale
   failure/loser requests;
4. replay repeats writes instead of performing only missing transitions;
5. authority issuance originally stored self-referential capability state,
   while diagnostic provenance can still be minted or derived after activation;
6. journal-head, receipt-chain, and generation checks are observational rather
   than CAS-fenced through acknowledgement;
7. journal operations validate a path identity and then reopen paths instead
   of retaining a full native directory identity; and
8. the 1,000-seed campaign uses diagnostic/raw axes and fake persistence labels
   rather than the production-shaped TaskState coordinator.

The seam also has no production completion/recovery caller yet. Production
authority therefore remains inactive. The accepted repair order is immutable
issuance provenance, durable snapshot proof, state locking/stable-ID merge,
journal-head/generation fencing, monotone reduction/minimal replay, retained
native root identity, production integration, and only then a real crash
campaign.

The self-referential half of item 5 is now closed. `ControllerStateAuthority`
and `AttemptPersistenceAuthority` are exact process-local opaque handles backed
by separate issuer-owned issuance records and scope digests. Handles expose no
persistence issuer or process capability; copied, replaced, in-place-retargeted,
parent-retargeted, and cross-transaction uses refuse. Independent re-review
marked this narrow slice **PASS** under the declared trusted-controller /
untrusted-spawned-child boundary. The affected controller/journal/config packet
passed 80 tests under Python 3.11 and 80 under Python 3.12; ruff, mypy, and
`git diff --check` were clean. Evaluated code may never run in the controller
interpreter or through fork-without-exec, because that would invalidate the
process-local capability boundary.

The diagnostic half of item 5 remains open: diagnostic controller authority can
still be minted and used to construct a store after path activation, no honest
installed production provenance exists, and issuance registries still require
bounded retirement. No production authority follows from the opaque-handle
PASS.

The atomic path-publication prerequisite is now independently reviewed
**PASS**. `reserveControllerPathsInstallation()` validates an exact candidate,
serializes the controller-path and environment domains through commit or
rollback, refuses settings/environment initialization races, and binds commit
and exit to the owning thread. Deterministic RED tests reproduced a foreign
commit publishing after owner rollback, two threads entering the same
reservation, and a foreign exit poisoning lifecycle state; the owner-bound
fix closes all three without sleeps. The full config-bootstrap file passed 32
tests on Python 3.11 and 32 on Python 3.12, 9 focused reservation tests passed
on each runtime, the three adversarial tests passed five repeated runs, and
ruff, mypy, and `git diff --check` passed. Both the
specification reviewer and concurrency/security reviewer returned PASS. The
factory token is accidental-misuse hardening, not same-process secrecy; the
frozen threat invariant remains that evaluated or hostile target code never
imports into the installed controller process. No paths were activated and no
production authority changed.

### 6.9 Task 3 fresh retry and Local/clone authority packet

The attempt loop now resolves non-authoritative runner policy once, allocates a
fresh attempt ID and transaction ID inside every retry, provisions a distinct
`ExecutionContext`, delivers that exact context/work directory to execution,
and enters a per-attempt finally boundary. Persisted or returned provider
session IDs do not cross a fresh transaction; bounded textual diagnostics may.

The subsequent authority packet closes three independently reviewed defects:

- trusted-Local eligibility is revalidated before any landing resolution;
- mandatory clone landing resolves only from installed controller composition,
  independently of the optional legacy fabric flag; and
- the frozen scope and returned lease must agree on attempt, transaction, task,
  subtask, and runner identity. Foreign/malformed leases are refused without
  directly tearing down ownership that may belong to another transaction.

The raw `execution_backend` field is removed from the copied subtask passed to
both trust validation and clone provisioning, so it cannot regain routing
authority in a downstream factory. Focused evidence is 85 passed on Python
3.11 and 85 passed on Python 3.12.

This packet remains source-dark. The ordinary production loop does not yet own
installed registry/trust composition; unresolved prior journal records are not
yet reconciled before allocation; and compatibility finalization does not
quiesce a landing-required clone. Those are explicit later Task 3 blockers, not
implicit claims hidden by the green packet.

### 6.10 Diagnostic activation and retained store hardening

The controller-path activation fence now linearizes diagnostic authority
issuance, diagnostic store construction, every retained-store transaction, and
controller-path publication. A broader deterministic activation-first race
revealed a build-to-entry window in `installControllerPaths()`: candidate path
conversion completed under one lock hold, then the lock was released before
reservation entry. Installation now retains one uninterrupted path lock from
the first caller-controlled conversion through reservation entry and commit.
The two activation-first operation/constructor cases changed from RED to two
passes, and the full config-bootstrap file passes 39 tests on each Python lane.

`ControllerStateStore` now:

- serializes close with in-flight operations and rejects same-thread close;
- rejects nested same-thread operations immediately and invalidates the outer
  transaction even if the callback catches the refusal;
- rechecks immutable authority expiry before, during, and after OS-lock
  acquisition and immediately around read/list/update/delete/backup effects;
- poisons and closes the store after an unlock failure;
- closes raw descriptors after constructor failures;
- closes every already-opened child handle after traversal or close failure;
- distinguishes a valid JSON `null` primary from a missing primary during
  backup; and
- JSON-normalizes update results before commit, preventing a post-commit
  deepcopy failure from fabricating failure after success;
- preserves committed move/replace/delete truth if authority expiry advances
  only after the native effect; and
- defers terminal child-handle cleanup poison until after OS-lock release,
  closes retained resources, and refuses every later operation without
  converting the committed result into failure. A backup-only cleanup failure
  remains a typed incomplete-prefix failure.

Deterministic regressions cover lock contention, after-acquire expiry,
observation expiry, deepest write/delete/backup effects, close serialization,
reentrancy, Windows unlock poisoning and OS-lock release, descriptor leakage,
null backup, normalized return, mid-traversal cleanup, close-all behavior,
post-move/post-replace/post-remove expiry, terminal replace/delete cleanup
failure, and backup-only cleanup failure. The controller file passes 43 tests
under Python 3.11 and 43 under Python 3.12; controller+config passes 82 under
each lane. Ruff, source mypy, and diff hygiene pass. Corrected independent
re-review returned PASS on both formerly open post-effect boundaries. No
controller paths or runtime authority were activated.

### 6.11 Installed-provenance first-effect boundary

`installControllerRuntimeState()` already validates the exact live installed
controller authority before it converts `source_root` or `installed_root`,
publishes controller configuration or paths, imports mutable-state consumers,
or constructs the retained store and external root. No production refactor was
needed for this narrow packet.

The permanent isolated regression supplies exploding `PathLike` objects,
requires the typed installed-authority refusal, proves controller config and
paths remain inactive, proves the external root remains absent, and now asserts
that `control_store`, `task_io`, `heartbeat`, and `terminal_ipc` remain absent
from `sys.modules` both before and after the refused call. The focused test
passes on Python 3.11 and Python 3.12; controller+config remains 82 passes under
each lane, ruff and diff hygiene pass, and corrected independent review returns
PASS. Diagnostic authority caused zero runtime-install effects. No activation
occurred.

### 6.12 Outer-capability opacity, exact handoff, and containment

The caller-visible `AuthorizedOuterCapabilities` record is now an exact
`frozen=True`, `slots=True`, `eq=False` two-field handle containing only a
random transfer ID and an identity token. All workload and process truth lives
in a separate issuer-owned frozen scope. Registry resolution requires the
exact handle object, exact token identity, current child PID, and a fresh
domain/version-separated SHA-256 over every issuer field, including exact
process-capability identity; it returns a detached internal scope only after
the registry lock is released. There are no compatibility scope properties.

Both capability frames now use duplicate-key-rejecting canonical JSON and an
exact two-kind multiset. They bind the currently available repository/base,
task/raw-intent, schema/byte length/spec, child PID, launch ID, approval nonce,
issuer generation, independently split secret cross-digests, closed argv, and
exact frame digests. Transfer-ID allocation has a 32-attempt collision ceiling.
Duplicate handles refuse before any pipe observation. Win32 consumption waits
boundedly through empty and partial publication, revalidates PID before and
after consumption, rejects trailing bytes or a second frame, and requires
writer closure. Parent descriptor copies and binding rows retire after handoff
and on every failure path.

Invalid child PID or payload publication failure now attempts a finite
`poll -> terminate -> wait -> kill -> wait -> poll` cleanup sequence. Exact
integer terminal status is required; a resistant child raises typed
`OperatorChildContainmentFailure` with frozen attempts/failure-types/return-code
evidence and preserves the original launch refusal as `__cause__`. It cannot
silently claim quiescence.

The final independently rerun closure reports 186 tests passing under Python
3.11 and 186 under Python 3.12 across operator launch, controller state,
configuration bootstrap, candidate, and promotion authority. Ruff, source
mypy, compileall, and scoped `git diff --check` pass. Corrected adversarial
re-review reports PASS, including immediate-child partial-frame startup,
one-frame/EOF proof, descriptor-map cleanup, all 18 issuer-field mutations,
bounded collision, exact process identity, and resistant-child containment.
No activation occurred. This packet deliberately does not claim the complete
capsule bootstrap scope: external roots, anchor/boot/controller/watchdog and
revocation generations, receipt lineage, deadlines/expiry, one-use derivation,
and installed composition remain open.

### 6.13 Capsule-bootstrap atomic bundle and hardened transfer

The complete capsule-owned scope now crosses the operator boundary in both
PID-bound OS capability frames. Canonical encoding and the domain-separated
outer digest cover the installed repository identity, distinct canonical
repository identity, repository attestation and base, run and workload facts,
source/installed/controller-state roots, immutable receipt lineage, activation,
boot, controller, watchdog, issuer, and revocation generations, absolute
capability expiry and run deadline, child PID, launch ID, approval nonce,
split-secret cross-digests, spec bytes/digest, and exact frame digests. No scope
fact is accepted from argv, environment, child reconstruction, or a later
caller argument.

The first exact transfer resolves once into one memoized opaque
`InstalledBootstrapAuthorities` bundle. It contains the controller-state
authority, the shared `AuthorityWatchdog`, a landing issuer, and the initial
`RunAdmissionAuthority`. Exact replay returns that identical bundle; copied,
stale, cross-process, cross-generation, first-use-after-activation, or revoked
handles refuse. Installed identity remains the TOFU path identity while the
canonical repository ID remains the attested native/Git identity; neither is
silently substituted for the other. Diagnostic minting and installed
derivation refuse after activation.

All caller-visible launch, admission, landing, and recovery objects are checked
against detached issuer-owned records and exact private identity. Every public
field mutation, copied-object revocation, issuer clock/probe retarget, task/spec
cross-use, repository/base mismatch, and recovery cross-repository use refuses.
`releaseStart` is a retained pending/starting/started-or-indeterminate state
machine: concurrent or sequential replay returns one stored outcome, and a
failed starter is never invoked again. Probes must return exact typed truth;
exceptions are normalized; liveness is rechecked after probes. Observed
bootstrap expiry, authority expiry, or backward clock movement terminally
retires the relevant issuer so wall-clock rollback cannot resurrect authority.

Bootstrap derivation publishes a pending transfer tombstone before creating
descendants and holds the shared epoch permit through controller, landing,
bundle, and terminal registry publication. Any partial prefix retires the
controller, removes bundle publication, poisons the transfer, and refuses
remint. Revocation propagates through the shared watchdog to every descendant.
The controller-init/revoke and activation/derivation races have deterministic
lock-order fixtures, including an activation-first cold subprocess proof.

The operator boundary mints and validates launch entropy before allocating
pipes. Pipe pairs enter cleanup ownership before inheritability configuration.
Writers use bounded nonblocking publication on Windows and POSIX, and scope is
rechecked after spawn, before parent binding, and immediately before and after
each frame. A non-reading child times out, a post-spawn expiry quiesces the
child, and each writer is removed from the outer live collection before local
close so descriptor reuse cannot close an unrelated handle. The child spec is
canonical create-once data: byte-identical replay is idempotent and any
different rewrite refuses. The real Win32 child consumes the complete frames
without fallback.

Canonical landing now requires an exact issuer/admission pair bound to the
coordinator's repository attestation and base. That admission is revalidated
under the retained issuer/bootstrap permit. `LooseRefStore` requires a callable
commit guard and invokes it after every blocking HEAD/ref/lock observation,
immediately before the native `replaceFile` effect. Thus expiry or revocation
cannot slip through the former post-probe/pre-replace interval.

Fresh retained evidence for this accepted source-dark packet:

- integrated capsule/operator/controller/promotion/watchdog matrix: 354 passed
  on Python 3.11 and 354 passed on Python 3.12;
- exact affected-test mapping: 309 passed on each lane;
- authority/promotion/candidate/loose-ref matrix: 150 passed on each lane;
- full staged-revision file: 59 passed and 1 POSIX-only skip on each lane
  (216.80 seconds / 216.62 seconds);
- candidate file: 20 passed on each lane; config bootstrap: 39 passed on each
  lane; repository-map/header closure: 24 passed on each lane;
- ruff passed both lanes, mypy found no issues in seven source files on both
  lanes, both lanes compiled all seven files, `dev.py check` passed all seven
  source files and 309 mapped tests, repository-map drift was clean, all three
  workflows validated, and `git diff --check` exited zero;
- corrected operator-boundary review returned PASS after reproducing all five
  former cleanup/deadline defects, and a fresh independent authority/CAS review
  returned PASS on rollback permanence, exact admission pairing, lock order,
  commit-guard placement, and call-site closure.

This evidence grants no activation. Retained blockers are: the operator
channel is not yet proven exclusive authority; prespec quiescence/operator
exchange lack a capsule-deadline timeout; canonical spec contracts still carry
string paths instead of retained no-follow native roots; the child does not yet
independently exact-match persisted spec bytes; a real installed
`SingularityBootReceipt` producer and persistent external revocation channel do
not exist; retained native-root/manifest identity and trusted recovery
quiescence remain open; installed execution probes remain intentionally absent;
and full installed-runtime composition acceptance, including CB26–CB33, remains
open. The global launch embargo remains unchanged.

### 6.14 Authenticated state-store protocol and typed source-dark boundary

The state-store channel now has a standalone canonical protocol with strict
JSON framing, an exact 32-byte channel key, a 4 MiB whole-frame quota, closed
request and response schemas, exact runtime generations and controller PID,
thread-safe monotonic cursors, detached snapshots, domain-separated HMACs, and
exact resource, request, sequence, result, and digest correlation. Replay,
substitution, bad signatures, missing or unknown members, duplicate JSON
members, noncanonical frames, and mutable double-projection races refuse.

This checkpoint does not mistake symmetric authentication for process origin.
The shared-key HMAC proves canonical-frame integrity and correlation only;
because the controller holds the same key, it cannot prove that a response was
created exclusively inside the worker. Production origin remains blocked on a
worker-generated Ed25519 key bound into the sealed readiness handshake and each
response.

Installed worker authority is deliberately fail-closed. `installStateStoreWorker`
and direct `StateStoreWorkerClient.execute` raise the exact typed
`BOOT_RESOURCE_LIFECYCLE_UNAVAILABLE` reason before callbacks, request-value
projection, path observation, RPC, or storage effects. The process entrypoint
returns exit code 78 without entering `serve`. Diagnostic helpers remain
available only as fenced brownfield scaffolding and do not grant installed or
production authority.

Fresh retained evidence for this limited source-dark packet:

- the protocol file passed 65 tests on Python 3.11 and 65 on Python 3.12;
- the combined protocol/worker matrix passed 130 tests with 9 strict xfails on
  each lane;
- the controller-state matrix passed 71 tests on each lane;
- targeted ruff, direct mypy for the three source files, and `git diff --check`
  exited cleanly; and
- independent protocol review returned PASS, while the separate worker review
  returned PASS for this limited source-dark checkpoint only.

The nine strict xfails are retained blockers, not accepted functionality. They
cover installed success, generation tampering, revoked admission, cross-thread
revocation, runtime poisoning, three reentrant transition cases, and registered
channel snapshot integration. Closing them requires a separate pre-controller
boot-resource journal, sealed digest-pinned Docker create/inspect/start and
registration lifecycle, worker-exclusive origin identity, exact `/data` mount
and fixed-database identity, retained storage handles, durable recovery and lost
response replay, cancellation and indeterminate-outcome semantics, and bounded
cleanup. Stage 2, D3.1, CB26–CB33, every OCI role, and production authority
remain open; no activation occurred.

### 6.15 AttemptJournal immutable binding and one-fence persistence boundary

The installed AttemptJournal boundary now has one private frozen binding for
the exact root, diagnostic/installed mode, and accepted bootstrap bundle. The
persistence issuer has a separate frozen binding for controller authority,
repository and root identity, generations, process capability, provenance,
bundle, and clock. Independent issuer-owned fingerprints detect ordinary
retargeting, in-place frozen-dataclass mutation, and whole-binding replacement
before path or journal effects.

Installed callers cannot inject controller or watchdog generation inputs. The
constructor refuses those inputs before controller validation/classification,
authority-registry or watchdog observation, runtime/bundle permits, generation
callbacks, root resolution, persistence registries, or storage. The exact
controller generation is derived from the retained runtime authority and must
equal the accepted bundle admission generation; the watchdog generation comes
only from that admission. Diagnostic probes remain available only under the
preactivation diagnostic fence and are immediately followed by held-fence
revalidation.

Public journal methods now enter exactly one outer persistence fence and call
only private unfenced helpers internally. Authority lookup, scope validation,
and refusal occur before the transaction file lock. Once locked, recovery-axis
mutation uses already-derived immutable scope and never reacquires a higher
runtime fence. In the installed race matrix, an acknowledgement that linearizes
first retains the runtime epoch through its durable append while revocation
waits; revocation that linearizes first refuses before lock, replay, append, or
axis mutation. The obsolete raw-path fixture was replaced with one installed
negative/positive boundary proving both zero-effect refusal and exact-authority
commit plus replay.

Fresh retained evidence:

- `tests/execution/test_attempt_journal.py` passed 73 tests on Python 3.11 and
  73 on Python 3.12;
- the combined journal/transaction matrix produced 84 passes plus exactly the
  three preregistered TaskState durable-receipt REDs on each lane;
- operation-first and revocation-first tests passed five repeated runs on each
  Python lane;
- ruff, scoped mypy, Python compilation, affected-test mapping, and
  `git diff --check` passed;
- `tools/dev.py check platform_core/runtime/attempt_journal.py` passed ruff,
  typecheck, and all 73 tests, but its aggregate exit remained nonzero because
  13 broader dirty-worktree repository-map artifacts were already stale; and
- specification review returned FIX-FIRST for the original constructor order,
  the adversarial RED reproduced that flaw, the minimal fix went green, and
  specification re-review plus independent code-quality/security review both
  returned PASS.

This is not acceptance of the current resource registry as a crash-closed set.
Registration still lacks a durable immutable intent and completion marker, so a
crash prefix can be exposed or redefined. The next packet must add exact
role-tagged contract closure, typed missing/incomplete states, identical-manifest
resume, different-manifest refusal, explicit empty closure, completed-set gates
for transition/RUNNING, and concurrent-winner proof. Authority-ID collision
retry, binding/authority registry retirement, and retained native-root handles
also remain explicit follow-ups. The three TaskState receipt REDs stay visible.
No Stage 2 completion, production authority, worker activation, or TOFU action
occurred.

## 7. Protected install and OCI state

The user explicitly authorized:

- one-time public Docker image/package downloads;
- digest pinning of every input;
- construction of the reviewed offline OCI closure; and
- final build and verification with networking disabled.

The user also explicitly required that nothing activate unless all nine roles
and every closure check pass.

The repository activation-image lock currently declares:

- schema galaxy.activation-images/v1;
- two digest-pinned base images;
- nine logical roles across eight unique OCI archives;
- network_acquisition_closed set to true.

The nine roles are:

1. candidate_parser
2. command_sandbox
3. credentialed_driver
4. object_parser
5. reviewer
6. source_fetcher
7. source_parser
8. state_store
9. verifier

The closed acceptance matrix contains 192 numbered invariant records. Those
source artifacts do not prove that the current Docker engine has the images
loaded or that an installed runtime passed the closed harness.

Live machine state at this checkpoint:

- Docker client 29.5.2 exists with context desktop-linux.
- Docker server is unreachable at the Desktop Linux named pipe; Docker Desktop
  being open has not yet made the daemon reachable.
- C:\Users\fireh\AppData\Local\9to5\singularity\activation-runtime.json
  is missing.
- C:\Users\fireh\AppData\Local\9to5\singularity\bin\singularity-admin-client.ps1
  is missing.
- C:\Users\fireh\.galaxy-r3\review exists and contains test/evidence
  material, but the protected runtime is not installed.

The archived Python 3.12 full-suite diagnostic
`C:\Users\fireh\.galaxy-r3\review\full-suite-cp312-20260716-v4.log`
(SHA-256
`1cae2d6d71dca575a02972cea9698f6ca86123ace4845b3e383a68565aee85a8`)
and its exit sidecar `full-suite-cp312-20260716-v4.exit` (content `1`, SHA-256
`f1b2f662800122bed0ff255693df89c4487fbdcf453d3524a42d4ec20c3d9c04`)
recorded 5 setup errors, 4 failures, 5,674 passes, and 8 skips.

Within that archived run, six outcomes specifically identified protected-install
prerequisites:

- five activation-harness setup errors because `activation-runtime.json` was
  absent; and
- one cutover-normalization failure because no installed protected anchor
  record existed for this checkout.

This is a scoped protected-install inventory, not a claim that only six tests
remain globally. The same archive also contained two truth-gap freshness
failures and repository-map drift. Later focused passes do not replace a fresh
full-suite artifact. The mutable `.pytest_cache/v/cache/lastfailed` set contains
historical node IDs and is not qualification evidence.

The next global count must come from a newly archived invocation of:

    C:\Users\fireh\.galaxy-r3\review\pytest-cp312\Scripts\python.exe -m pytest -n auto -q

Retain both its complete log and exact exit-code sidecar before updating this
section.

Do not rewrite those tests to accept a repository-local substitute. Resolve
them through the reviewed offline closure, fresh exact-digest TOFU install,
external admin client, and installed LKG evidence.

Old TRUST SINGULARITY BOOTSTRAP lines and nonces from chat are historical and
must not be replayed. A valid ceremony must issue and verify a fresh challenge
for the exact current source/artifact digest. The user’s general authorization
cannot substitute for cryptographic freshness.

## 8. Exact next sequence

1. **Completed narrow slice:** replace persistence authorities with opaque
   tokens backed by separate, immutable issuer-owned scope records; copied,
   forged, and in-place-retargeted objects now fail before mutation.
2. **Completed prerequisite:** make controller-path publication an atomic,
   owner-thread-bound reservation that serializes settings/environment races
   and cannot publish through foreign commit or poisoned exit.
3. **Completed packet:** committed effects win post-effect expiry and terminal
   child-close races; deterministic dual-runtime fixtures and independent
   corrected re-review pass.
4. **Completed packet:** qualify the already-present installed controller
   provenance boundary before runtime installation observes
   caller paths or creates the external root; diagnostic authority must have
   zero runtime-install effects.
5. **Completed packet:** replace mutable outer-capability truth with an opaque
   two-field handle and issuer-owned immutable scope; bind every currently
   available workload/launch/frame fact, close Win32 partial/trailing-frame and
   parent-descriptor races, and fail typed when child quiescence is unproved.
6. **Completed packet:** carry the complete capsule-owned scope through both OS
   frames, derive one exact opaque installed-authority bundle, enforce one-use
   first derivation plus exact replay, propagate revocation/expiry, harden
   bounded child transfer and immutable spec publication, and close the actual
   final-read-to-ref-replace authority interval. Dual-runtime verification and
   two independent reviews pass; no activation occurred.
7. **Source implemented; broader CB26–CB33 acceptance pending:** make
   `installControllerRuntimeState()` accept only that exact
   bundle, derive every root and generation from it, retain bundle/watchdog and
   path-reservation permits through precommit, roll back consumer/store state
   before path commit, and poison every postcommit failure. Prove all prefixes,
   races, and real operator-child composition with zero caller-controlled
   authority facts.
8. **Accepted limited packet:** retain the canonical authenticated state-store
   protocol and typed source-dark worker refusal. Do not promote shared-key HMAC
   integrity into worker-origin evidence or treat nine strict xfails as green.
9. **Completed bounded packet:** freeze one private installed AttemptJournal
   binding, derive generations only from the installed bundle/runtime, reject
   installed generation inputs before observation, remove nested fence re-entry,
   replace the obsolete fixture, and pass dual-runtime specification plus
   security-quality review.
10. **Completed bounded harness migration:** replace the retired singleton
    credential crash fixture with the exact four-role runtime closure and bind
    its canonical manifest JSON/SHA-256 into every attempt. The 100-seed smoke
    and all 1,000 preregistered seeds pass on Python 3.11 and Python 3.12; this
    does not by itself close the broader AJ10--AJ15 gate.
10a. **Current FIX-FIRST boundary:** close bounded native enumeration/name,
     prospective debris-quota, owner-identity, deletion-sync, and POSIX/WSL
     replay semantics; independently re-review the corrected packet.
10b. **Current FIX-FIRST boundary:** remove caller-self-mintable snapshot
     admission, require fresh sealed credential absence before any terminal
     timestamp/broker/journal truth, and reject manifestless provisioning before
     mutation; independently re-review the corrected packet.
10c. **Completed accepted packet:** controller-state missing-destination writes
     use exact create-only reconciliation without generic POSIX move; ordinary
     POSIX directory link counts work in a real WSL/native runtime case, while
     identity-bound replacement remains intact. The file passed 77 tests on
     each Python lane, static checks, corrected specification review, and
     independent code-quality review. No activation occurred.
10d. After both current FIX-FIRST packets pass, run the complete AJ10--AJ15
     dual-runtime affected matrix and retain every deterministic failure as a
     permanent fixture.
11. Close persistence-authority collision retry and process-lifetime registry
    retirement without weakening exact object/token/scope identity.
12. Build the separate pre-controller boot-resource journal, sealed worker
    launcher/registration lifecycle, worker-generated origin identity, exact
    mount/storage identity, and durable channel recovery required to turn all
    nine state-worker xfails green.
13. Make `saveDataSnapshot` return a typed durable receipt for exact bytes and
    destination; remove the public authority-bearing writer callback.
14. Require that exact durable proof for journal acknowledgement and terminal
    persistence; patch storage below the coordinator for crash tests.
15. Hold the orchestrator state lock across copy/save/apply/ack/done, reacquire
    task/subtask by stable ID, and replace positional application with monotone
    stable-ID merging.
16. Bind acknowledgement to the validated journal head and receipt-chain digest
    with CAS, sharing the controller generation mutation gate.
17. Derive terminal truth across all durable attempts, make promoted winner
    dominate, and implement only-missing replay transitions.
18. Retain a native directory identity/handle across journal mutations and add
    rebind, alias, short-name, mount, and reparse-race fixtures.
19. Integrate the coordinator into normal completion and recovery, then rerun
    the 1,000-seed campaign through the real production-shaped seam.
20. Continue the typed ExecutionReceipt, exact verifier, finalization, cleanup,
     persistence, and single-promotion-authority sequence captured in the full
     progress ledger.
21. Implement each smallest contract-preserving change after its focused RED;
     run focused Python 3.11 tests, then Python 3.12 for each completed packet.
22. Run affected tests, static checks, `git diff --check`, and map validation.
23. Finish Task 3 and Task 4 as one atomic source commit only after their joint
     gate passes.
24. Execute Task 5 failure injection, independent review, map/evidence closure,
     and exact final SHA work.
25. In parallel only where dependency-safe, restore Docker daemon reachability,
     verify every digest-pinned archive/image and all nine roles, then run the
     final closed harness with networking disabled.
26. Perform a fresh protected TOFU/install/LKG transaction only after the exact
     Task 5 fixed point. Never fabricate activation-runtime.json.
27. At Stages 8/9, qualify the selective Flare/Nebula council against matched
     no-council, single-model, majority-vote, and pinned Karpathy baselines using
    the granular advisory-only task in the progress ledger.
28. Continue sequentially with Stages 3–11 using the full progress ledger.

## 9. Useful commands and runtimes

Work from the isolated worktree, not C:\9to5.

Python 3.11 compatibility lane:

    C:\Users\fireh\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe

Python 3.12 production/test lane:

    C:\Users\fireh\.galaxy-r3\review\pytest-cp312\Scripts\python.exe

Mypy/dev-tools environment:

    C:\Users\fireh\AppData\Local\9to5\galaxy-dev-tools\Scripts\python.exe

Core checks:

    python tools/dev.py check <file>
    python tools/affected_tests.py <changed files>
    python tools/repo_map.py --check
    python validate_workflows.py
    python -m platform_core.core.galaxy_topology
    python -m pytest -n auto -q
    git diff --check

Do not use a broad full-suite result as evidence for installed activation unless
the exact protected runtime, image closure, no-network harness, generation,
authority, and rollback records all co-resolve.

## 10. Checkpoint maintenance rule

Treat `CURRENT.md`, this detailed checkpoint, and
`GALAXY-R3-PROGRESS.md` as one atomic navigation artifact. Update all three in
the same patch, then re-read their links and ensure their HEAD, stage,
authority, failure scope, and next action agree. Never update one file merely
to chase a volatile live count while leaving the other two stale.

Refresh the bundle at:

- every independently accepted source-dark packet or retained evidence
  boundary;
- each stage receipt;
- completion of the atomic kernel Task 3/4 wave;
- Task 5 review fixed point;
- any OCI closure digest change;
- protected TOFU/install success or rollback;
- any activation, expiry, revocation, or GraphWarrant change; and
- before knowingly ending a long implementation session.

Record evidence with commands, exit codes, exact commits, fixtures, environment,
authority state, known failures, and rollback point. Never rewrite historical
receipts to make the present look greener.
