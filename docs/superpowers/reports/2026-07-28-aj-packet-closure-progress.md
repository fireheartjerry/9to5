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

## 6. AJ15c (a) implemented — sealed issuance record

Per the operator's ruling, the kernel-owned `object()` snapshot capability is
gone and the admission handle is now opaque, ported from the reviewed-PASS
persistence-authority pattern.

Before, `_CloneSnapshotAdmission` was a `__slots__` object carrying `_lease`,
`_quiescence`, `_issuer`, `_issuer_identity`, `_seal`, `_consumed`, `_lock`, and
its construction was fenced by a module-level `_SNAPSHOT_ADMISSION_FACTORY =
object()` sentinel. The scope a caller held *was* the authority.

After:

- `_CloneSnapshotAdmission` is a frozen, slotted, kw-only dataclass with exactly
  two fields: `admission_id: str` (a `secrets.token_hex(32)` opaque identifier)
  and `_token: object`.
- `_IssuedCloneSnapshotAdmission` holds the issuer-owned truth — the exact
  handle, token, issuer, issuer identity, seal, lease, and quiescence — in a
  module registry `_SNAPSHOT_ADMISSION_RECORDS` under its own lock.
- `_consumeCloneSnapshotAdmission()` validates the exact handle object identity,
  the token identity, the exact lease and quiescence objects, and the issuer's
  identity, seal, and registration, then retires the record.
- `_SNAPSHOT_ADMISSION_FACTORY` is **deleted**. There is no sentinel left to
  mint or bypass.

Forgery is now defeated by record binding rather than by guarding construction,
which is strictly stronger: a field-for-field reconstruction with the *same*
opaque id and the *same* token object is refused, because the record binds one
exact handle object. The RED-first test
`test_snapshot_admission_handle_is_opaque_and_scope_stays_with_the_issuer`
asserts the handle exposes no `_lease`/`_quiescence`/`_issuer`/`_issuer_identity`/
`_seal`, and that such a forgery refuses with "binding differs" while the genuine
handle succeeds. The pre-existing forgery test was extended to cover
`dataclasses.replace` as a fourth attack, which the old sentinel design could
not express because the handle was not a dataclass.

One correctness detail found by test: retiring the record on consume made a
replay indistinguishable from a forgery. Consumed identifiers are therefore
retained in `_SNAPSHOT_ADMISSION_CONSUMED`, so a genuine replay is still refused
as "already consumed" while the lease and quiescence references are dropped with
the record.

Verification (hermetic git config, since the host's `rerere.enabled=true` is a
known unrelated blocker — see §F3 of the consolidation report):

```txt
pytest test_execution_clone test_candidate test_kernel_artifacts test_worktree \
       test_attempt_journal test_credential_broker -q
  Python 3.12.3  ->  361 passed, 8 skipped, 1 failed
```

The single failure is
`test_worktree.py::test_legacy_retirement_checkpoints_dirty_and_moves_every_entry_outside`,
which is **pre-existing and environmental**: proved by stashing this change and
re-running the same suites at HEAD, where it is the *only* failure (1 failed / 65
passed). ruff ok; mypy unchanged at 14 pre-existing `ctypes.get_last_error`
errors with and without the patch.

## 7. AJ15c (b) — attempted, reverted, and escalated again

The operator ruled "yes to both, fail closed". The replay half was implemented
by hoisting the fresh absence observation above the replay short-circuit in
`_destroyGuarded` and `_select_terminal_receipt`, so returning an existing
terminal receipt would still cost a re-observation.

**It was reverted, because it is not implementable at that layer.**
`CredentialChannelAbsenceVerifier.observeDeleted` deliberately refuses once
terminal state exists:

```txt
credential_channel.py:1464  self._terminal_intent_absent(observed)
credential_channel.py:1465-1468  if self._broker_terminal_metadata_absent(observed) is not True:
                                     raise CredentialChannelEvidenceRefused(
                                         "credential broker terminal metadata already exists")
```

So "always re-observe" and "observation requires terminal state to be absent"
are contradictory as the code stands. With the reordering in place, two
legitimate recovery tests break —
`test_credential_broker.py::test_destroy_replay_adopts_receipt_persisted_before_broker_metadata`
and `test_worktree.py::test_recovery_reuses_broker_terminal_receipt_after_prejournal_crash`
— both failing with "terminal credential destruction state already exists". That
is not fail-closed; that is stuck, and it would strand any crash that died
between receipt persistence and broker metadata.

Measured attribution, not assumed: at HEAD those suites are 1 failed / 65 passed
(the environmental legacy-retirement failure); with the reordering they are
3 failed / 63 passed. The two extra failures are caused by the change.

The clause is therefore blocked on a narrower question than the one already
answered, and it is a question about authority semantics, so it was not guessed:

> **Open for the operator:** the terminal-state guard inside `observeDeleted`
> (`credential_channel.py:1464-1468`) is exactly what makes replay
> re-observation impossible. Should (i) that guard be dropped so absence can be
> re-observed after terminal state exists, (ii) a separate replay-only
> re-observation entrypoint be added that performs the filesystem absence check
> without the terminal guard, or (iii) the clause be satisfied only for the
> first-destruction path, leaving replay on the stored receipt?

`_markDestroyed`'s independent re-proof was not started, because it consumes
whatever the resolution above produces.

## 8. AJ16 — two real defects found and fixed

AJ16 asks for bounded authority-ID collision retry and retirement of expired
authority, issuer-binding, and journal-binding registry entries without
retargeting. `controller_state._registerControllerStateAuthority` already had
the reference implementation (`_MAX_AUTHORITY_ID_ATTEMPTS = 32`, `continue` on
collision, refusal on exhaustion). The persistence-authority issuer did not.

**Defect 1 — silent retarget on ID collision.**
`AttemptPersistenceAuthorityIssuer.issueAuthority` minted `secrets.token_hex(32)`
once and wrote `self._issued[authority_id] = issued` plus
`_PERSISTENCE_ISSUER_REGISTRY[authority_id] = self` with **no collision check at
all**. A repeated identifier silently overwrote the live issuance record,
rebinding an existing authority to a new scope — exactly what AJ16 forbids.
Demonstrated by RED-first test
`test_persistence_authority_id_collision_retries_without_retargeting`, which
forces one collision and observed the second authority reusing the first's
identifier. Fixed with a bounded retry loop that claims **both** registries
under their locks, so a collision in either rejects the whole attempt rather
than half-binding, and exhaustion refuses with "collision budget exhausted".

**Defect 2 — expired entries were never retired.** Expiry was enforced at use
time (fail closed, correct) but the expired record stayed in `self._issued` and
`_PERSISTENCE_ISSUER_REGISTRY` forever. Added `_retireExpiredAuthority`, called
at the expiry refusal, which re-reads both registries under their locks and
deletes the entry **only when it is still the exact record observed**, so a
concurrent reissue of the same identifier is never retired by mistake. RED-first
test `test_expired_persistence_authority_is_retired_without_retargeting_others`
asserts the expired entry leaves both registries while a second live authority
from the same issuer keeps its record and binding.

Both tests were verified genuinely RED: stashing only the source change makes
both fail, restoring makes both pass.

Verification (hermetic git config):

```txt
pytest test_attempt_journal test_kernel_artifacts test_worktree \
       test_execution_clone test_attempt_state_transaction -q
  Python 3.12.3  ->  285 passed, 6 skipped, 4 failed
```

The 4 failures are the §F4 `saveDataSnapshot` receipt tests and are
**pre-existing and unrelated**, proved twice over: the same combined run at HEAD
also gives 4 failed, and that file run alone gives 3 failed both with and
without this change (the fourth is a pre-existing test-order interaction).
ruff ok; mypy unchanged at 20 pre-existing errors with and without the patch.

**Defect 3 — `id()`-keyed journal bindings were never retired.**
`_ATTEMPT_JOURNAL_BINDINGS` is keyed by `id(journal)` and had no removal path at
all, so an entry outlived its object indefinitely. Because CPython reuses
addresses, an unrelated later object allocated at the same address inherits the
dead entry. That fails closed today — the stale record's `binding` is not the
new object's `__binding`, so validation refuses — but it is a false refusal plus
unbounded growth, and AJ16 names journal-binding retirement explicitly.
`AttemptJournal` was not even weak-referenceable (`__slots__` carried
`__binding` and `__dict__` but no `__weakref__`). Added `__weakref__`, and a
`weakref.finalize` that calls `_retireAttemptJournalBinding`, which deletes the
entry **only while it is still that exact record** — so a same-address successor
that has already registered is never retired out from under itself. RED-first
test `test_dead_journal_binding_is_retired_without_retargeting_a_live_one`
collects one journal and asserts its key leaves the registry while a sibling's
key and binding survive intact.

**Also aligned:** the `_SNAPSHOT_ADMISSION_RECORDS` mint added in §6 refused
outright on a repeated identifier; it now uses the same bounded retry
(`_MAX_SNAPSHOT_ADMISSION_ID_ATTEMPTS = 32`) and additionally retries against
already-consumed identifiers, so a consumed id can never be re-minted.

Verification after the remainder (hermetic git config):

```txt
pytest attempt_journal + kernel_artifacts + worktree + execution_clone +
       candidate + attempt_state_transaction + credential_broker -q
  Python 3.12.3  ->  374 passed, 9 skipped, 4 failed (the pre-existing §F4 set)
```

mypy unchanged: 20 pre-existing errors in `attempt_journal.py` and 14 in
`candidate.py`, with and without these patches. ruff ok on both.

### Correction — the journal-binding retirement is narrower than first stated

Measured after shipping it: `_IssuedCredentialVerifierBinding` holds
**strong references** to both the verifier and the journal
(`attempt_journal.py:2016-2017`). A live verifier binding therefore pins the
journal, the `weakref.finalize` never runs, and the entry is **not** retired.
Probe:

```txt
register journal              -> binding present
insert one verifier binding holding journal=j
del j; gc.collect()
journal binding retired?      -> False
```

So the shipped retirement is real but conditional: it fires only when no
credential-verifier binding references the journal. The commit message and the
first version of this section overstated it, and this paragraph is the
correction. The `_CREDENTIAL_VERIFIER_BINDINGS` registry is also self-pinning
for the same reason — the record strongly references the verifier it is keyed
by, so that registry can never shrink and `weakref.finalize` on the verifier
could never fire either.

Fixing this properly is a packet, not an increment, and it was deliberately not
attempted late in this session:

- `_IssuedCredentialVerifierBinding.verifier` and `.journal` must become
  weakrefs. The two identity checks that consume them
  (`attempt_journal.py:4301-4302`, `is not exact_verifier` / `is not self`)
  survive the change — a dead weakref dereferences to `None`, which still fails
  an `is` comparison — but they sit in a hot authority-validation path.
- `CredentialChannelAbsenceVerifier` (`credential_channel.py:1208`) declares
  `__slots__` without `__weakref__`, so it is not weak-referenceable either and
  a third file must change.
- `_CREDENTIAL_COORDINATORS` is the same shape again.

That is three files of authority-lifetime change and deserves its own
failing-test-first packet with independent review — particularly after this
session already produced one plausible-looking change in this area (AJ15c(b))
that tests proved would strand crash recovery.

### Update — the self-pinning packet was then done

RED-first test `test_verifier_binding_does_not_pin_its_journal_or_itself`
asserts that a collected journal loses its binding even while a verifier binding
exists, and that a collected verifier loses its own. It failed exactly as
predicted ("a verifier binding pinned its journal, defeating journal
retirement").

Implemented across the three files identified above:

- `_IssuedCredentialVerifierBinding` now stores `verifier_ref` and `journal_ref`
  and exposes `verifier` / `journal` as **dereferencing properties**. That keeps
  the two identity checks at `attempt_journal.py:4301-4302` written exactly as
  they were (`binding.verifier is not exact_verifier`,
  `binding.journal is not self`) — a dead weakref yields `None`, which still
  fails an `is` comparison, so the authority semantics are unchanged while the
  strong references are gone.
- `_retireCredentialVerifierBinding` plus a `weakref.finalize` on the verifier,
  deleting only while the entry is still that exact record.
- `CredentialChannelAbsenceVerifier` (`credential_channel.py:1208`) gained
  `__weakref__` so it can be referenced weakly at all.

One genuine regression surfaced and was fixed correctly rather than papered
over: `test_credential_verifier_copy_and_reflection_cannot_replay_terminal_truth[object-new]`
builds a reflected forgery by looping `verifier_type.__slots__` and
`object.__setattr__`-ing each slot, which now hit
`attribute '__weakref__' ... is not writable`. `__weakref__` is slot machinery,
not copyable state, so the loop skips it (and `__dict__`); the test's actual
property — a reflected copy cannot replay terminal truth — is untouched and
still passes on all three parametrisations.

Verification, by exact failure-list diff rather than by counts:

```txt
8 suites, hermetic git config
  at HEAD          -> 8 failed
  with the change  -> 8 failed, byte-identical FAILED list  (diff exit 0)
  3.12.3: 387 passed, 9 skipped, 1 xfailed
  3.11.15: 387 passed, 9 skipped, 1 xfailed
```

All 8 are the pre-existing sets already attributed above (§F4 `saveDataSnapshot`,
the `test_receipts` authorization group, and the environmental
legacy-retirement failure). mypy unchanged: 20 in `attempt_journal.py`, 9 in
`credential_channel.py`, with and without. ruff ok on both.

### `_CREDENTIAL_COORDINATORS` — the last registry, same treatment

`_IssuedCredentialCoordinator` had the identical shape: keyed by
`id(coordinator)` while holding `coordinator` and `journal` strongly. Converted
to `coordinator_ref`/`journal_ref` with dereferencing properties, so
`issued.coordinator is not self` and `issued.journal is not self._journal`
(`attempt_journal.py:5321-5330`) keep their exact wording; added
`_retireCredentialCoordinator` plus a `weakref.finalize` on the coordinator that
deletes only the exact record; and `_CredentialJournalCoordinator` gained
`__weakref__`. RED-first test
`test_coordinator_binding_does_not_pin_its_journal_or_itself`.

All three retirement paths — journal binding, verifier binding, coordinator —
now pass together, and journal retirement is unconditional in every case.

```txt
8 suites, hermetic git config, exact FAILED-list diff vs HEAD:
  3.12.3  -> 8 failed (byte-identical to HEAD), 388 passed, 9 skipped, 1 xfailed
```

ruff ok; mypy unchanged at 20 in `attempt_journal.py`.

**AJ16 clause status.** Bounded authority-ID collision retry: done, in both the
persistence issuer and the snapshot admission mint. Retirement of expired
authority entries: done. Retirement of issuer-binding and journal-binding
registry entries: done for `_ATTEMPT_JOURNAL_BINDINGS`,
`_CREDENTIAL_VERIFIER_BINDINGS`, and `_CREDENTIAL_COORDINATORS`, in every case
deleting only the exact record so nothing is retargeted. What the ledger text
asks for is now implemented.

### AJ16 independent review — VERIFIED on all four claims, no findings

Reviewer given no prior context, told not to trust commit messages or docs, and
instructed to refute first:

1. **Bounded collision retry, no retargeting — VERIFIED.** Lock order is always
   `self._issued_lock` -> `_PERSISTENCE_ISSUER_REGISTRY_LOCK`; the reviewer
   grepped every acquisition (lines 104, 1603, 1630, 2199) and confirmed the
   only other one is standalone, so there is **no deadlock path**. Both
   `continue` branches fire before either registry is mutated, and both writes
   happen while `_issued_lock` is held continuously, so **no thread can observe
   a half-bound state**. Exhaustion raises.
2. **Expired-authority retirement — VERIFIED.** `current` is re-read under the
   lock and compared by identity before any deletion, so a concurrent reissue of
   the same identifier is not retired by mistake.
3. **Weak records keep exact identity semantics — VERIFIED.** The reviewer
   checked every comparison site and found none that compares two dereferenced
   (possibly-`None`) values against each other: every identity check pins one
   side to a live, strongly-referenced object (`self`, `exact_verifier`, or
   `self._journal`, the last being a strong attribute, never a weakref). A dead
   weakref can therefore only make these checks **fail**, never spuriously pass.
4. **Finalizer `id()` capture — VERIFIED.** The captured id is only ever a dict
   key, never dereferenced, and each `_retire*` guard requires the slot to still
   hold the exact frozen record instance, so a finalizer for a dead object
   cannot delete a successor's entry that reused the address.

The reviewer explicitly attempted to construct races for each claim
(interleaved `issueAuthority`, concurrent retire + reissue, GC firing mid
comparison) and reported: "Concrete failure scenarios constructed: none."

With the clauses implemented, both lanes green, and an independent review
returning no findings, **AJ16's own bar is met.**

## 8b. AJ15c (b) — implemented on the operator's chosen shape

The operator chose a **replay-only re-observation entrypoint**: leave the live
first-destruction path and its terminal-state guard untouched, and give the
replay path its own way to re-prove absence.

`CredentialChannelAbsenceVerifier.reobserveDeletedForReplay` performs the same
filesystem absence proof as `observeDeleted` minus the two terminal-state guards
that made replay impossible (`_terminal_intent_absent`,
`_broker_terminal_metadata_absent`). It mints no observation and grants no
authority — it can only refuse.

The placement mattered more than the entrypoint. A first attempt called it after
`_remove_channel`, which made the proof trivially true: the replay deleted the
resurrected channel itself and then observed absence. `_destroyGuarded` now
decides replay-versus-first-destruction **before** removing anything:

```python
receipt = self._existing_terminal_receipt(observed)
if receipt is None:
    self._remove_channel(observed.secret_channel_id)      # first destruction
    ... observeDeleted -> _select_terminal_receipt ...
else:
    self._absence_verifier.reobserveDeletedForReplay(observed, intent)
```

The broker half was also implemented, per the same ruling. `_markDestroyed`
re-checks channel absence through its own `_channelPath` before writing terminal
metadata, independently of the journal fence that allowed the call, and refuses
with "credential channel remains present at terminal destruction".

Two RED-first tests, both demonstrating real gaps before the fix:
`test_destroy_replay_refuses_when_the_channel_reappeared` (replay adopted
terminal truth while the secret channel was present again — "DID NOT RAISE") and
`test_mark_destroyed_independently_reproves_absence`.

Crucially, the two legitimate recovery paths that the earlier reordering
stranded now pass: `test_destroy_replay_adopts_receipt_persisted_before_broker_metadata`
and `test_recovery_reuses_broker_terminal_receipt_after_prejournal_crash`. A
crash between receipt persistence and broker metadata still recovers; only a
channel that actually came back is refused.

```txt
8 suites, hermetic git config, exact FAILED-list diff vs HEAD:
  3.12.3  -> 8 failed (byte-identical to HEAD), 390 passed, 9 skipped, 1 xfailed
  3.11.15 -> 8 failed,                          390 passed, 9 skipped, 1 xfailed
```

ruff ok; mypy unchanged (9 in `credential_channel.py`, 1 in
`credential_broker.py`) with and without.

## 9. AJ17 — gap demonstrated and pinned, implementation not started

AJ17 was untouched. It still is, as an implementation — but its contract is no
longer a paragraph, it is an executable fixture.

`AttemptJournal.root` is a path, and `_root_identity` (`attempt_journal.py:581`)
re-stats that path at validation time, so journal work is bound to a **name**
rather than to the object that was validated. Demonstrated directly:

```txt
establish journal at <tmp>/journals        inode 3415324
os.rename(<tmp>/journals, <tmp>/moved)
mkdir <tmp>/journals                       inode 3415325
journal.create(second record)              -> DID NOT RAISE
```

The journal silently wrote into the impostor directory. New test
`test_journal_refuses_after_its_root_object_is_swapped` encodes the required
behaviour — refuse rather than write, and leave the impostor empty — and is
retained as `xfail(strict=True)`. Strict matters: if AJ17 lands and the test
starts passing while the marker is still present, the suite fails, so the
fixture cannot rot into a silent pass. This is the AJ15e rule ("retain every
deterministic failure as a fixture") applied to a failure that had no fixture.

Both lanes after adding it: 220 passed / 5 skipped / **1 xfailed**.

Implementation deliberately not started. Closing AJ17 means moving journal I/O
onto retained `NativeDirectoryHandle` children (`fsio.py:1827`,
`openNativeDirectory` at `:4521`) across 3 `_root_identity` call sites and 8
path-based operations, and it carries a Windows design question — holding a
directory handle open for the journal's lifetime changes deletion and rename
behaviour on exactly the platform this kernel targets. The POSIX case is pinned;
the Windows short-name/alias case still needs its own fixture.

## 9b. AJ17 implemented — open-validate-close, the operator's chosen shape

The operator chose **open-validate-close per operation** over retaining a handle
for the journal's lifetime, specifically to avoid changing Windows deletion and
rename semantics.

`AttemptJournal._requireBoundRootObject()` opens the journal root, reads
identity **from the opened handle**, and closes it immediately. The identity is
captured on first successful observation — the root may legitimately not exist
when the journal is constructed — and every later operation must match it, or
the journal refuses with "attempt journal root object changed beneath its path".
No directory handle is held across the journal's lifetime, so the Windows
semantics the operator was protecting are untouched.

It is called at two points:

- `_append_event`, the single seam every mutation funnels through (11 call
  sites), so all mutating entrypoints inherit the check.
- `create()`, immediately after `root.mkdir(...)` and **before `fileLock`**.
  Placement was load-bearing: with the guard only at `_append_event`, a swapped
  root still refused correctly but `fileLock` had already created a `.locks`
  directory inside the impostor. Validating before the lock means a swapped root
  leaves nothing behind at all.

`test_journal_refuses_after_its_root_object_is_swapped` — retained earlier as a
`xfail(strict=True)` fixture — now **passes**, and the marker has been removed
(strict xfail would otherwise fail the suite, which is exactly the ratchet it
was there to provide).

```txt
9 suites, hermetic git config:
  3.12.3  -> 391 passed, 13 skipped; non-staged-revision FAILED list identical to HEAD
  3.11.15 -> 391 passed,  9 skipped, 8 failed (the same pre-existing set)
```

ruff ok; mypy unchanged at 20. Scope stated plainly: this closes the POSIX
rename/replace race at operation granularity. The Windows short-name/alias case
still has no fixture, and per-operation validation is a narrower guarantee than
holding one handle across an operation's internal steps.

## 10. Ledger effect

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
