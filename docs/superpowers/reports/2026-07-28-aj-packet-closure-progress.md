# AJ packet closure progress (2026-07-28, VPS session)

Works the §O2c AJ packet toward "green and evidenced on both Python lanes plus
native POSIX". Environment: Ubuntu 24.04, native ext4, Python 3.12.3 and
Python 3.11.15 (the 3.11 venv lives outside the worktree). No Docker. No
activation, no TOFU ceremony, embargo in force.

## 1. Independent reviews obtained

Both reviews were run by a reviewer given **no prior context**, told not to
trust repo documentation, and instructed to attempt refutation first.

### AJ15b changed surface — PASS / PASS

| claim | verdict | strongest finding |
|---|---|---|
| `_maybeStealStale` (fsio.py:4883) compares full identity and fails closed | **PASS** | Confirmed at fsio.py:4925-4931: `_sameNativeFileObject(...)` *and* `successor != identity` (full dataclass `__eq__`), either divergence → `return` without re-raise. Reviewer could not construct an inode-reuse interleaving that removes a live lock, because `_removePosixFile` never blind-unlinks — it uses an open-retained fd plus rename-exchange and **restores** the original name (fsio.py:4315-4338) before raising. |
| `_reconcileCreateOnlyFileAdmitted` (fsio.py:2973) reserves before mutating | **PASS** | Confirmed at fsio.py:3068-3096: `listEntries` → `_boundedNativePublicationEntries(..., reserve_one=True)` → `_requireNativePublicationDirectoryCapacity` → only then `_publishNewFileUnlocked`, with debris cleanup after. Both quota helpers are pure read/raise. Structurally identical to the two other creation call sites. |

**New finding from the review, worth its own item:** `tryAcquireLock`
(fsio.py:5041) documents `-> bool`, but a generic `OSError` raised by
`_maybeStealStale` escapes through `_tryAcquireLockLease`'s
`except BaseException: ...; raise` (fsio.py:5032-5038) and out of
`tryAcquireLock` entirely. A caller relying on the documented boolean contract
gets an unhandled `OSError`. The reviewer was explicit that this is **not
introduced** by the AJ15b fix — both the old and new comparisons could reach
that `raise`. Recorded, not fixed here: changing it alters an error contract in
lock-acquisition code and deserves its own failing-test-first packet.

### AJ10–AJ14 implementation claims — IMPLEMENTED, no dark gates

The reviewer independently confirmed all five as implemented in
`platform_core/runtime/attempt_journal.py`, with **zero** TODO, xfail,
`NotImplementedError`, feature flag, or dark gate in any of the five paths, and
corrected three line references in the prior report:

- **AJ10** — `_resource_set_intent_bytes` (:2798-2819) serializes in the order
  given; it does **not** itself sort. The canonical sort is enforced one level
  up at the sole call site, `register_resources` :3935
  (`expected = tuple(sorted(resources, key=self._resource_identity))`), and on
  replay at `_decode_resource_set_members` :2925-2927. Duplicate identities
  cannot make the sort ambiguous — :3902-3903 and :3910-3914 raise first.
- **AJ11** — completion proofs are built from a **freshly loaded**
  `_load_resource_events_unfenced` (:4086-4089), not the write-time buffer, and
  the return value is a full disk re-read (:4110-4111) after the completion
  append. Replay cross-check begins at **:3748** (prior report said :3752-3755;
  same block).
- **AJ12** — `MissingResourceSet` :127, `IncompleteResourceSet` :131; raises at
  :3095, :3109, :3137, :3189, :3738; orphan→corruption at :2982-2985 and
  :3699-3702. MISSING and INCOMPLETE are structurally distinct (zero closure
  children vs reservation-only children) and cannot collapse.
- **AJ13** — multi-reservation refused :3016; manifest-vs-reservation refusal
  :3022-3025 fires inside `_reserve_resource_set_unfenced` (called :4010)
  before any append; create-only reservation dir :3040. Concurrency is held by
  `fileLock(..., timeout=30)` at :3904-3908 **plus** atomic `createDirectory`
  as an independent second barrier.
- **AJ14** — `completion_resources is None` gates at :3729 and :4054-4060; the
  RUNNING refusal for an empty set is at **:4452-4455**. Widening an
  already-closed empty set is rejected by the AJ13 refusal path before any
  write, because a different tuple yields a different `intent_digest` and thus a
  different reservation name.

## 2. AJ10–AJ14 evidence on both lanes, native POSIX

The ledger's own policy is that AJ10–AJ14 need *evidence*, not source.

```txt
pytest tests/execution/test_attempt_journal.py tests/execution/test_kernel_artifacts.py -q
  Python 3.12.3  ->  229 passed, 5 skipped, 0 failed
  Python 3.11.15 ->  229 passed, 5 skipped, 0 failed

pytest tests/execution/test_attempt_journal.py -k "<AJ10-14 scoped selection>" -q
  Python 3.12.3  ->  59 passed, 163 deselected
  Python 3.11.15 ->  59 passed, 163 deselected
```

The scoped figure matches the Windows 3.11 figure of 59 passed exactly, so the
AJ10–AJ14 surface is now measured on three lanes (Windows 3.11, POSIX 3.11,
POSIX 3.12) with identical results.

The 5 skips are new and deliberate. Those tests drive
`_run_installed_journal_case`, which spawns a child that builds a
`CapsuleBootstrapScope`; that scope requires exact local Windows absolute roots
(`bootstrap_scope._require_canonical_windows_root`), so on POSIX they were 5
hard failures reporting a Windows-path error rather than anything about the
journal. A `skipif`-equivalent guard was added at the single fixture seam
(`test_attempt_journal.py:89`), matching the treatment already applied to the
three control suites. They continue to execute on Windows.

## 3. AJ15e flake — fixed at the harness level

`test_fsio.py::test_concurrent_process_lock_acquisition_has_one_exact_winner`
was the blocker: AJ15e requires retaining every *deterministic* failure as a
fixture, so a flaky test stops the matrix.

It does not reproduce on Linux — 12/12 passes idle, then **15/15 passes under
2× CPU oversubscription** (12 busy loops on 6 cores). But reading the barrier
structure shows a real defect that explains the reported Windows signature
(one pass at 0.41 s, one failure at 20.63 s against a 20 s barrier):

1. The readiness barrier and the child's `go` wait were both 20 s, and they
   cover interpreter startup plus the `platform_core` import in each child.
   That is pure process-birth latency and measures nothing this test asserts,
   yet a slow birth was reported as a lock-semantics failure.
2. Worse, the child's `release` wait was **20 s while the parent's worst case
   after `go` is 40 s** (20 s electing a winner plus 20 s waiting for the
   loser's refusal). A slow-but-correct election could therefore make the
   winner exit 73 *before the parent ever wrote `release`* — a latent failure
   that has nothing to do with the invariant.

Fixed by splitting the budgets rather than by blanket-raising them:
`STARTUP_TIMEOUT_SECONDS = 120.0` for process birth, `ELECTION_TIMEOUT_SECONDS
= 20.0` kept tight for the actual invariant, and `RELEASE_TIMEOUT_SECONDS = 4 ×
ELECTION` so it strictly dominates the parent's worst case. The child now takes
both budgets as argv. The property under test — exactly one winner, loser
refuses with 83, no lock or debris left behind — is unchanged and still measured
on a 20 s window.

Honest limit: this removes the mechanism that produced the observed signature
and the reasoning is sound, but the flake itself was never reproduced on this
host, so confirmation requires a Windows re-run.

## 4. Post-fix regression, both lanes

```txt
pytest tests/execution/test_fsio.py tests/execution/test_credential_broker.py -q
  Python 3.12.3  ->  338 passed, 45 skipped, 0 failed
  Python 3.11.15 ->  338 passed, 45 skipped, 0 failed
```

Unchanged from the pre-fix figures, so the barrier split cost no coverage.

## 5. Operator decisions received (AJ15c)

Escalated rather than guessed, per the standing rule. The operator ruled:

- **(a)** Replace the kernel-owned `object()` snapshot capability with a
  **sealed issuance record**, mirroring the already-reviewed-PASS opaque
  persistence-authority pattern (`AttemptPersistenceAuthority` /
  `_AttemptPersistenceScope` / `_IssuedAttemptPersistenceAuthority`,
  attempt_journal.py:1058-1089): caller-visible handle carries only an opaque ID
  and token, scope lives in a separate issuer-owned record.
- **(b)** **Yes to both** — `CredentialBroker._markDestroyed` must independently
  re-prove absence on top of the fenced journal path, and the
  `_existing_terminal_receipt` replay short-circuit must re-observe. Fail closed.
- **(c)** **Audit every provisioning entrypoint first** rather than assuming the
  private-clone path was the intended target.

Implementation of (a) and (b) is the next work and is not in this report. The
(c) audit was run and is below.

### (c) provisioning-entrypoint audit — result

Ten provisioning entrypoints were traced. **Exactly one mutates journal or
repository state, and its manifest gate is correctly ordered.**

| entrypoint | mutates journal/repo? | manifest gate before mutation? |
|---|---|---|
| `wiring.py:84 provisionForAttempt` | no — delegates to `_env_router.provision` (:136) | n/a |
| `wiring.py:193 provisionForSubtask` | no — delegates (:206) | n/a |
| `router.py:377 provision` | no — dispatch wrapper (:381) plus telemetry | n/a |
| `environment.py:198 provision` | no — `@abstractmethod` stub | n/a |
| `backends/local.py:33` | no — returns an `EnvHandle` over the existing tree | n/a |
| `backends/docker.py:54` | no — `docker run` with a bind mount (:64) | n/a |
| `backends/remote.py:83` | no — remote `mkdir -p` (:94) | n/a |
| `backends/worktree.py:67` | no — pure delegation (:68) | n/a |
| `backends/clone.py:1286` | no — delegates to injected `clone_factory` (:1298) | n/a |
| `runtime/worktree.py:634 PrivateCloneProvisioner.provision` | **yes** — `attestCanonicalRepository` (:673) and `journal.create(record, require_new=True)` (:765) | **yes** — `validateRuntimeResourceManifest` at **:664**, wrapped to raise `PrivateCloneRefused` on `TypeError`/`ValueError` (:669-672); **:664 precedes both :673 and :765** |

So clause (c) is **satisfied by the existing code**, and the audit — not an
assumption — is what establishes it. The private-clone path was indeed the only
possible target, because it is the only mutator.

One caveat surfaced by the trace, outside the original question and worth its
own follow-up: `clone.py`'s `clone_factory` is assigned only via
`buildInstalledCloneEnvironment` (clone.py:1602), and **no production call site
outside tests wires a real factory**. That is consistent with the in-progress
transport commit, but it means the audited mutation path is not yet reachable in
production. Whoever lands the wiring must re-confirm the gate ordering survives
it.

## 6. Ledger effect

- AJ10–AJ14: implementation independently confirmed; dual-lane POSIX evidence
  obtained. Still gated on AJ15e per the ledger's own policy.
- AJ15b: all three clauses now closed for the changed surface; the unreviewed
  remainder is stated in `2026-07-28-aj15b-posix-dual-lane-replay.md`.
- AJ15e: the flake blocker is addressed; the matrix itself has not been run.
- AJ15c: unblocked by operator decision, not yet implemented.
- AJ16, AJ17: untouched.
- Not addressed here and still blocking a full POSIX matrix: `test_staged_revision.py`
  remains red on this host because Ubuntu git does not attest SHA1DC
  (see `2026-07-28-vps-posix-lane-consolidation.md` §F2).
