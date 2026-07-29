# GALAXY R3 current recovery entrypoint

Last refreshed: 2026-07-20T14:14:01-04:00 (America/Toronto)

This is the stable entrypoint for resuming the long-running GALAXY R3
implementation after context compaction, agent replacement, or machine restart.
It is a navigation aid, not a new specification and not activation authority.

> **START HERE (2026-07-28):**
> `../reports/2026-07-28-session-close-findings-and-next-actions.md`
> is the single continuation entrypoint. It carries three findings that exist
> nowhere else: (1) **AJ10--AJ14 are already implemented and test-covered** — the
> `[ ]` marks are an evidence policy, not missing code, so do not rewrite them;
> (2) the activation ladder does not exist as documented — the embargo is
> unconditional, nothing ever writes `activation_state="active"`, and shadow
> evidence must come from a standalone harness rather than the run loop;
> (3) an unverified hypothesis for the controller-state failure. It also lists the
> exact next actions and the three AJ15c questions that need an operator decision
> rather than more code.

## Read these first

1. [Detailed session checkpoint](2026-07-19-galaxy-r3-session-checkpoint.md)
2. [Full progress and task ledger](GALAXY-R3-PROGRESS.md)
3. [Approved package README](../specs/2026-07-14-galaxy-r3-package-README.md)
4. [Artifact and plan hash registry](../../../config/galaxy/artifacts.v1.json)
5. [Transactional-kernel plan](../plans/2026-07-13-galaxy-r3-transactional-kernel.md)

Then re-read the repository and nearest nested AGENTS.md before touching a
package. The generated root navigation map is not an authority source for
security, qualification, or activation decisions.

## Resume anchor

- Worktree:
  C:\\Users\\fireh\\.config\\superpowers\\worktrees\\9to5\\galaxy-r3-implementation
- Branch: galaxy-r3-implementation
- Checkpoint HEAD: 5c8ca5cce409c4b41fde4c9c28ce5252ff53da43
- Pre-checkpoint-bundle status snapshot: 277 entries (184 modified and
  93 untracked). That snapshot predates this three-file checkpoint bundle and
  the later research-transfer files.
- Audit snapshot at 2026-07-19T18:23:38-04:00: 285 entries (184 modified and
  101 untracked). Counts are historical observations, not invariants. Recompute
  them with `git status --short --untracked-files=all` before work and preserve
  every current entry.
- Audit snapshot at 2026-07-20T03:33:03-04:00: 299 entries. This remains only
  a preservation aid for the shared dirty worktree, not a cleanliness target.
- Audit snapshot at 2026-07-20T07:45:09-04:00: 316 entries (205 modified-like
  and 111 added or untracked). This is another preservation aid, not permission
  to discard any earlier or later worktree entry.
- Active stage: Stage 2, Transactional Singularity Kernel.
- Immediate implementation wave: kernel Task 3 plus Task 4, which the approved
  child plan requires to land as one atomic source wave.
- Production authority: unchanged and inactive.
- Post-freeze Kimi K3 intake: the hosted Kimi/API service has been available
  since 2026-07-16, but the downloadable public-weight candidate remains
  unavailable and unregistered because no full weights, exact license,
  immutable revision/hashes, or reviewed offline runtime closure existed at
  capture. The paid hosted surfaces are prohibited by
  `external_spend_allowed=false`; the shadow-only `ResearchTransferRecord` has
  no provider, topology, trial, spend, or runtime authority. Its 12-claim
  provider-surface correction passed 23 tests on Python 3.11 and Python 3.12,
  ruff, direct mypy, artifact/digest validation, and independent review. A
  fresh last-30-days audit at the 2026-07-19 cutoff reconfirmed that K3 weights
  were only promised by 2026-07-27; the newest actually downloadable Moonshot
  artifact was Kimi-K2.7-Code, whose roughly 595 GB checkpoint and documented
  serving requirements do not make it a desktop Ollama reflex candidate. This
  audit changes no authority state.
- Pre-execution council intake: the legacy local council is not yet a heavily
  improved Karpathy-style council. The frozen Flare/Nebula design is intended
  to be materially stronger, but that hypothesis is unproven while its rows
  remain only `specified` and must pass the J1 matched qualification gates.
  The pinned Karpathy/recent-research transfer is
  record `98c2a17ab4c5890a0a1246179d7b48e95a955d8eff9941f0e4ccf282d829dd64`
  over artifact
  `00afba9ca9b3df93cbaa152fb734555afaae75edfc94ed85ba3a9f7f4bf098c9`.
  It carries six primary claims and 18 closed controls, has no registry row or
  experiment manifest, requests no trial, is `specified`, non-authoritative,
  and shadow-only, and passed 24 tests on both Python lanes plus ruff, mypy,
  digest loading, diff hygiene, and corrected independent re-review. Its
  granular qualification work is queued for Stages 8/9 without interrupting
  Stage 2. Independent re-review also passed the permanent-advisory wording,
  unproven-benefit wording, typed CXR task, and checkpoint consistency.
- Repository-map closure: 659 tracked modules; `research_transfer` is indexed,
  and all 24 focused map/header tests passed after regeneration.
- Task 3 durable acknowledgement seam: initial source now persists a detached
  pending receipt chain, acknowledges an exact promoted transaction, persists
  `done`, and then seals the terminal axis. Initial controller/watchdog
  generation, repository, journal-root, deadline, and transaction bindings are
  present, and the focused control/journal packet passed 40 tests on both
  Python 3.11 and Python 3.12.
- Persistence qualification: **fix-first**. Independent review found eight
  semantic blockers: unproved snapshot durability, absent state locking and
  stable-ID reacquisition, no monotone cross-attempt reducer, non-minimal
  replay, self-referential authority issuance, unfenced journal-head/generation
  validation, path-reopen root races, and a synthetic rather than production
  1,000-seed campaign. None is waived by the green focused count.
- Opaque persistence-authority slice: independently reviewed **PASS** under the
  trusted-controller / untrusted-spawned-child boundary. Caller-visible
  persistence handles now contain only an opaque ID and token; controller and
  attempt scope live in separate issuer-owned issuance records; copied,
  replaced, in-place-retargeted, parent-retargeted, and cross-transaction uses
  refuse. The affected authority packet passed 80 tests on both Python 3.11 and
  Python 3.12, plus ruff, mypy, and `git diff --check`. This does not close
  diagnostic minting, installed provenance, registry retirement, durable-write
  proof, CAS, locking, reducer, root identity, or crash qualification.
- Controller-path installation reservation: independently reviewed **PASS**.
  Publication now holds one path-to-environment lock order through commit or
  rollback, refuses settings/environment initialization races, binds lifecycle
  operations to the owning thread, and rejects foreign commit, same-object
  concurrent entry, and foreign exit without partial publication. The full
  config-bootstrap file passed 32 tests on Python 3.11 and 32 on Python 3.12;
  9 focused reservation tests passed on each runtime, the three deterministic
  adversarial races passed five repeated runs, and
  ruff, mypy, and diff hygiene passed. This is a source-dark prerequisite only:
  it installs no controller and grants no production authority.
- Diagnostic activation/store packet: independently reviewed **PASS**. One broader
  race exposed that `installControllerPaths()` released the path fence between
  candidate construction and reservation entry; installation now retains one
  uninterrupted path lock through build, enter, and commit. Diagnostic
  issuance, construction, and every store operation share the activation
  fence. Store operations now recheck expiry through lock wait and immediately
  around observations/effects; close serializes; nested same-thread operations
  abort the outer transaction; unlock failure poisons and releases the store;
  raw descriptors and every opened child handle are closed; valid JSON null
  backups and precommit-normalized update returns are covered. Committed
  move/replace/delete effects now win an expiry race during unwind. A terminal
  child-handle close failure is deferred until after OS-lock release, poisons
  and closes the store for later operations, and cannot rewrite the committed
  result; a backup-only cleanup failure remains a typed incomplete-prefix
  failure. Deterministic post-move, post-replace, post-remove, terminal-close,
  and backup-prefix fixtures are present. The controller file reports 43 passes
  in each Python lane and controller+config reports 82 passes in each; the
  standalone config file reports 39 passes in each lane. Ruff, source mypy,
  diff hygiene, and corrected independent re-review pass. No activation
  occurred.
- Installed-provenance packet: independently reviewed **PASS** without
  production-code churn. `installControllerRuntimeState()` validates live
  installed provenance before converting either caller path, publishing
  controller config/paths, importing the four mutable-state consumers, or
  constructing the external root/store. Its isolated regression supplies
  exploding `PathLike` values and now pins all four consumer modules absent
  before and after refusal. The focused fixture passes on Python 3.11 and
  Python 3.12; the controller+config closure remains 82 passes in each lane,
  with ruff and diff hygiene passing. Diagnostic authority produced zero
  runtime-install effects, and no activation occurred.
- Outer-capability opacity and handoff packet: independently reviewed **PASS**.
  `AuthorizedOuterCapabilities` is now an exact frozen/slotted two-field
  process-local handle backed by an issuer-owned immutable scope and
  recomputable domain-separated digest. Forged, copied, replaced, pickled,
  retargeted, cross-spliced, wrong-PID, malformed-type, noncanonical-frame,
  duplicate-handle, trailing-byte, and transfer-ID-collision paths refuse.
  Both PID-bound frames bind the currently available workload, launch, nonce,
  split-secret, raw-intent, schema/length, issuer-generation, and exact frame
  facts. The Win32 consumer waits boundedly for a complete frame, proves one
  frame plus writer closure, and parent descriptors/bindings retire on every
  exit. Invalid-PID or write-failure children either have terminal state proved
  or raise a typed containment failure carrying frozen cleanup evidence and
  the original refusal. Independent verification reports 186 scoped tests in
  each Python lane plus ruff, mypy, compile, diff hygiene, and a corrected
  adversarial PASS. Capsule-owned roots, controller/watchdog/revocation
  generations, expiry, one-use derivation, and installed composition remain
  pending. No activation occurred.
- Capsule-bootstrap atomic-bundle packet: independently reviewed **PASS**.
  Both PID-bound OS frames now carry the complete exact capsule scope, and the
  full outer digest binds workload, child PID, launch, approval nonce, split
  secrets, roots, receipt lineage, controller/watchdog/revocation generations,
  deadlines, and expiry. Installed and canonical repository identities remain
  deliberately distinct. A one-use exact transfer derives one memoized opaque
  `InstalledBootstrapAuthorities` bundle containing controller-state
  authority, a shared `AuthorityWatchdog`, a landing issuer, and the initial
  `RunAdmissionAuthority`; copied, stale, cross-process, cross-generation,
  post-activation, or revoked derivations refuse. Issuer-owned detached records
  reject every-field mutation and bind launch, task/spec, repository/base, and
  recovery scope. Bootstrap publication installs a pending tombstone before
  descendants, holds one epoch fence across both registry publications, and
  poisons every incomplete prefix. The child-spec file is create-once; pipe
  publication is bounded and nonblocking; descriptor cleanup is leak-free;
  and post-spawn expiry quiesces the child. Launch replay starts exactly once,
  probe truth must be exact, clock rollback/expiry is terminal, and the final
  landing guard runs after every blocking precommit read immediately before
  canonical `replaceFile`. Verification passed 354 integrated tests, 309
  affected tests, 20 candidate tests, 39 config tests, 24 repository-map tests,
  and staged revision 59 passed/1 POSIX-only skip on **each** Python 3.11 and
  3.12 lane; ruff, mypy, compile, repo-map drift, workflow validation, focused
  `dev.py check`, and diff hygiene passed. Corrected operator review and a fresh
  authority/CAS review both returned PASS. No network call, paid-provider call,
  production activation, or TOFU ceremony occurred.
- Fresh retry packet: backend policy resolves once; every retry receives fresh
  attempt/transaction/context identity; provider sessions do not cross the
  transaction; trusted-Local eligibility precedes installed clone landing;
  raw routing overrides are stripped; and five foreign lease axes fail closed
  without direct teardown. The combined packet passed 85 tests on both Python
  3.11 and Python 3.12.
- Limited state-store boundary: the standalone canonical authenticated protocol
  passed 65 tests on Python 3.11 and 65 on Python 3.12. The combined
  protocol/worker matrix passed 130 tests with 9 strict xfails on each lane;
  controller-state remained 71/71 on each lane. Independent reviews returned
  PASS for the protocol and PASS for the limited source-dark boundary only.
  `installStateStoreWorker`, `StateStoreWorkerClient.execute`, and the process
  entrypoint remain structurally unavailable with
  `BOOT_RESOURCE_LIFECYCLE_UNAVAILABLE`; direct process execution exits 78
  without calling `serve`. The shared-key HMAC proves canonical-frame integrity
  and request/response correlation, not worker-exclusive origin, because the
  controller also holds the key. The nine strict xfails remain open blockers.
  No activation occurred.
- AttemptJournal installed-binding packet: independently reviewed **PASS** after
  one specification-review FIX-FIRST cycle. One frozen, tamper-detecting journal
  binding now owns root, mode, and the exact installed bundle; the persistence
  issuer has an independently frozen binding. Installed caller generation inputs
  refuse before controller/watchdog validation, callbacks, runtime permits, root
  observation, registries, or storage. Exact generations come only from the
  retained accepted bundle/runtime. Every public journal operation enters one
  outer persistence fence, authority refusal precedes the file lock, and
  operation-first/revocation-first acknowledgement races are linearized. Fresh
  journal tests passed 73/73 on Python 3.11 and 73/73 on Python 3.12; the combined
  journal/transaction matrix retained 84 passes plus exactly three deliberate
  TaskState durable-receipt REDs on each lane. Ruff, scoped mypy, compile, and
  diff hygiene passed. The two races also passed five repeated runs per lane.
  No activation occurred.
- Production-shaped crash-harness migration: **PASS for the bounded harness
  change, not yet the complete AJ10--AJ15 gate**. The retired singleton local
  credential fixture now registers the exact canonical four-role runtime
  closure (`authority_watchdog`, `model_driver`, `candidate_parser`, and
  `verifier`) with role-correct local/Docker backends, dependencies,
  role-tagged identities, and manifest JSON/SHA-256 bound into the attempt.
  Recovery reconstructs that exact closure and quiesces every role. All 1,000
  preregistered seeds passed as 11 tests on Python 3.11 (355.07 s) and Python
  3.12 (377.56 s); the 100-seed smoke passed on both lanes, and ruff,
  dual-lane compilation, and scoped mypy passed. The broader AJ10--AJ15
  acceptance matrix, filesystem hardening, and credential/snapshot authority
  review remain open, so this evidence grants no runtime authority.
- Controller-state POSIX move retirement: independently reviewed **PASS**.
  Missing destinations now use exact create-only reconciliation; observed
  destinations retain temporary-file plus identity-bound replacement, and the
  controller has no dependency on generic POSIX `moveChild`. Normal POSIX
  directory link counts are accepted while Windows retains its single-link
  rule. A fresh real POSIX/WSL nested write-read-exact-replay case proves
  ordinary `st_nlink >= 2` directories. The complete controller-state file
  passed 77/77 tests on Python 3.11 and 77/77 on Python 3.12, with ruff,
  production mypy, dual-lane compilation, and diff hygiene clean. Both the
  corrected specification review and subsequent code-quality review returned
  PASS. This remains source-dark and changed no production authority.

- 2026-07-28 AJ15b prospective-debris ceiling RED closed (Claude executor,
  partial): `_reconcileCreateOnlyFileAdmitted` in `platform_core/core/fsio.py`
  routed retained-incomplete-prefix debris through a `removeFile`-first path that
  freed a slot and let publication succeed at the directory ceiling instead of
  refusing. Unified it onto the complete path's reserve-first / cleanup-after
  order; `test_native_publication_refuses_partial_at_directory_ceiling_untouched`
  now passes. fsio + credential_broker suites 294 passed / 89 skipped / 0 failed
  on Python 3.11.15/Windows; ruff, mypy, compile, diff-check clean. This did NOT
  close AJ15b: the Python 3.12 lane, POSIX/WSL replay (89 skips), and corrected
  independent review remain. No commit; change lives in the shared dirty `fsio.py`.
  Full evidence:
  `docs/superpowers/reports/2026-07-28-aj15b-prospective-debris-ceiling-fix.md`.

- 2026-07-28 AJ15c clause-(a) sub-slice landed (Claude executor, partial):
  `TransactionalCloneKernel.prepare()` re-proved artifact, parser, and coordinator
  IDENTITY but never re-proved run-admission LIVENESS, so a `RunAdmissionAuthority`
  revoked after construction still reached snapshot-admission issuance. Added
  `_requireLiveRunAdmission()` (verbatim reuse of the existing
  `__init__`/`productionReady` check) invoked from `_revalidateInstalledArtifacts`;
  uninstalled/diagnostic kernels are unaffected (early return on
  `_artifact_qualification is None`). RED-first test
  `test_installed_clone_prepare_refuses_revoked_run_admission`. Clone surface 129
  passed/1 skipped; ruff, compile, diff-check clean; mypy clean for clone.py.
  AJ15c remains OPEN: admission is still minted from kernel-owned `object()`
  sentinels; clause (b) residual and clause (c) target are AMBIGUOUS and were
  deliberately NOT guessed at; Python 3.12, POSIX/WSL, and independent review
  outstanding. Evidence:
  `docs/superpowers/reports/2026-07-28-aj15c-run-admission-use-time-revalidation.md`.
- 2026-07-28 PRE-EXISTING failure identified and attributed (NOT introduced this
  session, proved by temporary revert of the AJ15b edit + byte-compare restore):
  `tests/control/test_external_controller_state.py::test_runtime_install_constructor_cleanup_ambiguity_poison_is_permanent`
  fails deterministically. Its child process globally patches `threading.RLock` to
  raise; unrelated to publication or clone admission. Needs separate triage.
  Consolidated session verification: 720 passed, 91 skipped, this 1 failure.

- 2026-07-28 **POSIX/WSL and Python 3.12 lanes now exist** — the long-standing
  AJ15b blocker is gone. Python 3.12.13 installed via `uv` (Windows venv lives in
  the session scratchpad, deliberately OUTSIDE the worktree so the dirty-file
  inventory is unchanged); WSL Ubuntu venv at `/home/fireh/venv312` with
  `TMPDIR=/home/fireh/galaxy-tmp` on **ext4** (not the default tmpfs) so `tmp_path`
  exercises genuine POSIX semantics. Reproduce commands are in the report below.
- 2026-07-28 **Real POSIX-only defect found and fixed on first POSIX run**
  (pre-existing in Codex's code; proved by temporary revert + byte-compare
  restore). `_maybeStealStale`'s replacement-race softening compared only the
  stable object tuple via `_sameNativeFileObject`, but **POSIX reuses a just-freed
  inode**, so a fresh legitimately-held lock B could present the same
  (volume, file id) as the stale lock A it replaced. The benign-race branch was
  skipped and `OSError` escaped `tryAcquireLock` (a boolean API). `_removePosixFile`
  had already refused the unlink on full-identity comparison, so B was never
  deleted — the safety property held; the error contract did not. The two guards
  disagreed about identity and that disagreement was the bug. Fixed by comparing
  full identity in the softening (fail closed: decline to reclaim rather than risk
  deleting a live lock). Unreachable on Windows because NTFS does not aggressively
  reuse file IDs. Verified **WSL ext4 3.12: 298 passed/45 skipped/0 failed**
  (was 297/1 failed); **Windows 3.11: 254 passed**; **Windows 3.12: 254 passed**;
  ruff and mypy clean. Evidence:
  `docs/superpowers/reports/2026-07-28-aj15b-posix-inode-reuse-stale-lock-fix.md`.
- 2026-07-28 **Flaky test identified — blocks AJ15e evidence.**
  `test_concurrent_process_lock_acquisition_has_one_exact_winner` is
  non-deterministic (back-to-back isolated 3.11 runs: one pass 0.41s, one fail
  20.63s at the 20s barrier; also failed in a 3.12 consolidated run while passing
  3/3 isolated). Spawns two subprocesses importing `platform_core`, so it is
  process-start-latency sensitive. Pre-existing and in a different code path from
  this session's changes. A flaky test cannot serve as evidence — stabilise before
  claiming the AJ10--AJ15 matrix.

- 2026-07-28 **STALE EVIDENCE CORRECTED — staged revision was 59 FAILED, not 59
  passed.** The capsule-bootstrap packet note above records "staged revision 59
  passed/1 POSIX-only skip on each lane". Measured this session, that suite was
  **59 failed / 1 skipped / 0 passed** — uncommitted drift in the shared worktree,
  so the entire staged-revision and promotion evidence surface was unverified
  while being cited as proven. Cause: AJ15a made the admission manifest mandatory
  on every `RUNNING` transition (`attempt_journal.py:4441-4450`) and migrated the
  journal/clone fixtures but not `test_staged_revision.py` (0 manifest references
  vs 13 in the journal tests). Fixed in the test fixture only, production code
  untouched: manifest bound before `create()`; the closed four-role local closure
  (`authority_watchdog`/`model_driver` local, `candidate_parser`/`verifier` docker,
  driver depends_on watchdog); `image_digest` for docker backends; and
  `resource_lease_ids` now **derived from the tuple returned by
  `register_resources()`** — which is literally the AJ15 contract. Now **59 passed
  / 1 skipped on BOTH lanes** (Python 3.11.15: 295.96 s; Python 3.12.13: 292.17 s).
  That is a freshly measured figure and supersedes the stale line at ~172 above;
  do not cite the old number. Evidence:
  `docs/superpowers/reports/2026-07-28-staged-revision-manifest-contract-recovery.md`.

- 2026-07-28 **Branch consolidation and first native-Linux lane.** The two
  divergent Stage 2 tips are merged onto one truth: the branch now equals the
  GitHub transport commit `5c33df1` with an empty diff, and the VPS-side
  `b24a99a` "stuff" sibling — a strict subset that additionally tracked the
  runtime SQLite index — is retained only as tag `backup/vps-stuff-b24a99a`.
  `state/.ann_index.*/` is now ignored. Remote `github` added; the bundle remote
  `origin` is untouched. Nothing was pushed.
  Measured on Ubuntu 24.04 / Python 3.12.3 / **no Docker**: `test_fsio.py`
  **298 passed / 45 skipped / 0 failed**, independently replicating the WSL ext4
  AJ15b figure on a second POSIX filesystem; the AJ15e flake
  (`test_concurrent_process_lock_acquisition_has_one_exact_winner`) **passed 3/3
  in 0.41-0.50 s and does not reproduce here** — it remains unstabilised, and a
  non-reproduction is not a fix. `tests/control/` was **75 failed / 502 passed**
  and is now **4 failed / 502 passed / 140 skipped** after adding the POSIX skip
  guards that sibling suites already had (test-fixture seams only, production
  code untouched, no-ops on Windows). Consequently the single deterministic
  controller-state failure **cannot be triaged on POSIX at all**: the case now
  skips at Windows-root scope validation and never reaches the patched
  `threading.RLock`, so the test-versus-code ordering hypothesis needs Windows.
  Three blockers stay OPEN and are decisions, not code: (F2) Ubuntu git
  `2.43.0-1ubuntu7.3` prints no `SHA-1:` build option, so
  `object_parser_entrypoint.py:152` refuses the runtime and causes **54 of the 56**
  `test_staged_revision.py` failures on this host — widening that attestation
  would weaken a collision-detection gate and was refused; (F3) the operator's
  global `rerere.enabled=true` creates `.git/MERGE_RR`, which
  `canonical_repo.py:914` refuses as an unknown file surface; (F4)
  `state/task_io.py:483 saveDataSnapshot` returns a `Path` and never calls
  `_issueSnapshotReceipt` (**zero callers**), so four
  `test_attempt_state_transaction.py` contract tests fail on **every** platform —
  the same drift class as the staged-revision manifest, and the concrete face of
  the already-recorded unproved-snapshot-durability blocker. Also recorded so no
  later wave can claim it green: `tools/size_audit.py` reports **55 must_split
  files and 251 must_split functions** against a bar of zero. Evidence:
  `docs/superpowers/reports/2026-07-28-vps-posix-lane-consolidation.md`.

- 2026-07-28 **AJ15b: two of three open clauses closed.** The AJ15b surface
  (`test_fsio.py` + `test_credential_broker.py`, 383 cases) ran on native Linux
  ext4 on BOTH Python lanes — 3.11.15 **338 passed/45 skipped/0 failed** and
  3.12.3 **338 passed/45 skipped/0 failed** — so the missing Python 3.12 lane
  clause is closed and the POSIX replay is no longer WSL-only. The "replay the
  89 skips" clause is now proved arithmetically, not asserted: all 45 POSIX
  skips come from static `skipif(os.name != "nt")` decorators (15 sites, all in
  `test_fsio.py`), so each executes on Windows; solving against the Windows lane
  (294 passed/89 skipped) gives executed-on-both = 249 and POSIX-only-executed =
  **89**, exactly the Windows skip count. No case in this surface is dark on
  both lanes. AJ15b stays `[ ]`: the corrected independent review is still open,
  and the bounded-semantics clauses are only green, which is not reviewed.
  Evidence:
  `docs/superpowers/reports/2026-07-28-aj15b-posix-dual-lane-replay.md`.

- 2026-07-28 **AJ packet progress: reviews obtained, AJ10--AJ14 evidenced, the
  AJ15e flake blocker addressed, and all three AJ15c questions decided.**
  Independent review (no prior context, told to refute first) returned **PASS on
  both AJ15b changed functions** and **IMPLEMENTED with zero dark gates** for
  AJ10--AJ14, correcting three line references. AJ10--AJ14 dual-lane POSIX
  evidence: `test_attempt_journal.py` + `test_kernel_artifacts.py` **229
  passed/5 skipped/0 failed on 3.11.15 AND 3.12.3**, and the Windows-comparable
  scoped selection is **59 passed on both**, matching the Windows figure exactly
  — three lanes now agree. The 5 new skips are the same Windows-only capsule
  scope, guarded at one fixture seam (`test_attempt_journal.py:89`). The AJ15e
  flake is fixed at the harness level by splitting one 20 s budget into
  process-birth (120 s) versus invariant (20 s) versus release (4x invariant);
  the old child `release` wait was 20 s while the parent's worst case after `go`
  was 40 s, so a slow-but-correct election could fail the test on its own.
  Post-fix both lanes still 338 passed/45 skipped/0 failed. **Operator ruled on
  AJ15c:** (a) replace the `object()` sentinel with a sealed issuance record on
  the persistence-authority pattern; (b) yes to both absence re-proofs, fail
  closed; (c) audit first — completed, and the clause is **satisfied by existing
  code**, since only `PrivateCloneProvisioner.provision` mutates and its gate at
  `worktree.py:664` precedes `:673` and `:765`. Still open: AJ15c (a) and (b)
  implementations, AJ16, AJ17, the AJ15e matrix itself, and a new review finding
  — `OSError` escaping `tryAcquireLock`'s documented `-> bool` contract
  (pre-existing, needs its own packet). Evidence:
  `docs/superpowers/reports/2026-07-28-aj-packet-closure-progress.md`.

- 2026-07-28 **AJ15c (a) landed; (b) reverted and re-escalated.** (a): the
  kernel-owned `object()` snapshot capability is **deleted**. The admission
  handle is now a frozen dataclass carrying only an opaque `admission_id` and a
  `_token`; lease, quiescence, issuer, identity, and seal moved into an
  issuer-owned issuance record, and `_SNAPSHOT_ADMISSION_FACTORY` no longer
  exists. Forgery is defeated by exact-handle record binding instead of by
  guarding construction, so even a same-id/same-token reconstruction refuses.
  Dual-lane affected surface 361 passed/8 skipped on both 3.12 and 3.11, with
  one pre-existing environmental failure proved by stash-and-rerun.
  (b): **NOT implementable as ruled.** Requiring a fresh absence observation on
  the replay path contradicts `observeDeleted`, which refuses once terminal
  state exists (`credential_channel.py:1464-1468`); with the reordering, two
  legitimate crash-recovery paths break with "terminal credential destruction
  state already exists" — stuck rather than fail-closed. Reverted. **New
  operator question:** drop that terminal-state guard, add a replay-only
  re-observation entrypoint without it, or satisfy the clause only on the
  first-destruction path? `_markDestroyed`'s independent re-proof depends on
  that answer and was not started.

## Non-negotiable continuation rules

- Treat the seven 2026-07-14 specification files as immutable requirements.
- Verify their hashes and the migrated plan hashes before relying on them.
- Do not discard, reset, clean, or overwrite the dirty worktree.
- Continue with failing-test-first development and focused verification.
- A source maturity flag never grants runtime authority.
- Keep later overlays dark until their evidence, dependency closure,
  GraphWarrant, expiry, revocation, and rollback gates pass.
- Do not reuse old TOFU challenge responses or nonces. A fresh external
  ceremony must validate its own exact digest and fresh nonce.
- The user authorized one-time public Docker/package acquisition for the
  reviewed OCI closure, digest pinning, and final network-disabled builds.
  That authority does not permit bypassing the nine-role closure checks or
  activating a failed or incomplete generation.

## Exact next action

Close the two current Stage 2 FIX-FIRST boundaries before claiming the wider
AJ10--AJ15 packet. First, finish bounded native filesystem semantics: the full
child-name vocabulary, prospective publication/deletion debris quotas,
fail-closed process-birth identity, deletion fsync/parent-sync failure prefixes,
and real POSIX/WSL replay. (Progress 2026-07-28: the prospective-debris
directory-ceiling refusal RED is now closed on Python 3.11.15/Windows — see the
resume-anchor note and report above — but AJ15b stays open pending the Python
3.12 lane, POSIX/WSL replay of the 89 skipped cases, and corrected independent
review.) Second, remove ceremonial snapshot authority and make
credential terminal truth depend on fresh sealed absence proof before broker or
journal `DESTROYED`; provisioning must reject a missing runtime manifest before
any journal/repository mutation. (Progress 2026-07-28: AJ15c clause (a) now
refuses at use time under a revoked external run admission. The remaining AJ15c
decisions need operator/reviewer input rather than more code — specifically
whether the kernel-owned `object()` snapshot capability must be replaced
outright, whether the broker must independently re-prove credential absence on
top of the already-fenced journal path, and which provisioning entrypoint the
manifest clause targets, since the private-clone path already validates the
manifest before mutation at `worktree.py:664`. See the AJ15c report.)
Independently re-review and verify both Python lanes plus WSL. The controller-state POSIX move retirement is already accepted;
after both FIX-FIRST packets pass, run the complete AJ10--AJ15 dual-runtime
affected matrix and proceed to journal semantic quotas, remaining
generic POSIX move callers, AJ16 registry retirement, and AJ17 retained-root
TOCTOU closure. The state worker remains typed unavailable/source-dark; the
global launch embargo stays in force; no production activation or TOFU ceremony
is authorized by this checkpoint.

Treat `CURRENT.md`, the detailed session checkpoint, and
`GALAXY-R3-PROGRESS.md` as one checkpoint bundle. Update all three in the same
patch whenever a stage boundary, atomic kernel wave, protected-install state,
or activation state materially changes; never refresh only one copy of shared
HEAD, stage, authority, failure, or next-action information.
