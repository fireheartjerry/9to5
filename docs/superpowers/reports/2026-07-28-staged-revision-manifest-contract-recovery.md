# Staged-revision suite recovered — admission-manifest contract drift

- Date: 2026-07-28 (America/Toronto)
- Author: Claude executor session, Stage 2, worktree `galaxy-r3-implementation`.
- **Impact: recovered 59 tests from 0 passing.** This suite is the entire
  staged-revision / promotion evidence surface; while it was red, the kernel's
  most important guarantees were unverified.
- No commit. No activation. Launch embargo unchanged.

## The problem

`CURRENT.md:194` records, as accepted evidence for the capsule-bootstrap packet:

> "staged revision 59 passed/1 POSIX-only skip on **each** Python 3.11 and 3.12 lane"

**That is no longer true.** Measured this session:

```
tests/execution/test_staged_revision.py  →  59 failed, 1 skipped, 0 passed
```

This is uncommitted live drift inside the shared dirty worktree: the recorded
evidence and the working tree disagree. The suite had silently gone from
fully-green to fully-red, so *no* staged-revision or promotion behaviour was
actually being verified.

## Root cause — a contract tightened, fixtures not migrated

`platform_core/runtime/attempt_journal.py:4441-4450` now requires an admission
manifest on every transition into `RUNNING`:

```python
if phase is AttemptPhase.RUNNING:
    admission_manifest = _runtime_resource_manifest_entries(...)
    if not admission_manifest:
        raise InvalidAttemptTransition("running requires an admission manifest")
```

The production-shaped crash-harness migration (AJ15a) made the manifest
mandatory and migrated the journal and clone fixtures, but **never migrated
`test_staged_revision.py`**:

| test file | `runtime_resource_manifest` references |
|---|---|
| `tests/execution/test_attempt_journal.py` | 13 |
| `tests/execution/test_execution_clone.py` | 2 |
| **`tests/execution/test_staged_revision.py`** | **0** |

All four files are untracked (`??`), so this drift exists only in the working
tree — which is exactly why it was invisible to any commit-based review.

## The full contract (discovered by fixing forward, error by error)

The fixture needed four separate corrections; each fix surfaced the next
requirement:

1. **Manifest must exist on the stored record.** `transition()` reads
   `current.runtime_resource_manifest_json` from the *persisted* record, so the
   manifest must be bound **before** `journal.create(record)`, not after.
2. **A local runner admits exactly a closed four-role closure**
   (`attempt_journal.py:448-485`) — not the single parser resource the fixture
   used:

   | role | required backend |
   |---|---|
   | `authority_watchdog` | `local` |
   | `model_driver` | `local` |
   | `candidate_parser` | `docker` |
   | `verifier` | `docker` |

   plus: exactly one watchdog and one driver, and the **model driver must declare
   `depends_on` the authority watchdog**. Anything else raises
   `"local runtime resource manifest differs from its closed required roles"`.
3. **Docker-backend resources require a real `image_digest`** — an empty string
   raises `"docker process registration requires image_digest"`.
4. **`resource_lease_ids` must equal the completed canonical set**
   (`attempt_journal.py:4456-4475`), compared by exact tuple identity and order.

## Fix

`tests/execution/test_staged_revision.py` only (production code untouched):

- Added a local `_with_runtime_manifest()` helper mirroring the canonical form in
  `test_attempt_journal.py:830-859` byte-for-byte (same schema string
  `galaxy.runtime-resource-manifest/v1`, same sorted-entry construction, same
  digest computation).
- Replaced the single `candidate_parser` lease with the full four-role closure via
  a small `_resource(...)` factory, with `image_digest` set for docker backends
  and the driver→watchdog dependency declared.
- Bound the manifest to the record **before** `create()`.
- **Derived `resource_lease_ids` from the tuple returned by
  `register_resources()`** rather than re-composing it locally.

That last point is deliberate and worth flagging: ledger item **AJ15** reads
*"Derive worktree `resource_lease_ids` from the returned canonical tuple"*. The
fixture now demonstrates exactly that contract — the canonical set comes back
from the journal and is used verbatim, so the test cannot drift out of order-sync
with the journal's own identity derivation again.

## Verification

| Lane | Result |
|---|---|
| Windows, Python 3.11.15 | **59 passed, 1 skipped, 0 failed** (was 59 failed / 0 passed), 295.96 s |
| Windows, Python 3.12.13 | **59 passed, 1 skipped, 0 failed**, 292.17 s |

Dual-lane green. This is now a *measured* figure and supersedes the stale
`CURRENT.md:194` claim.

`ruff check` → All checks passed. `git diff --check` → clean.

Note the runtime went from ~45 s (failing fast at the first transition) to ~296 s
— the suite is now actually executing its real git/clone/parse/promote work
rather than aborting early. The previous fast red was itself a signal.

## Why this matters beyond the test count

The recorded checkpoint evidence said this suite was green on both lanes. It was
not. Any reasoning that depended on "staged revision is proven" — including the
capsule-bootstrap packet's accepted evidence — was resting on a stale
observation. This is precisely the failure mode the repo's own
`corrected_implementation_audit` lesson warns about: **verify against the current
tree, never trust a recorded status line.** The suite should be re-run and the
checkpoint figure re-derived before the atomic Task 3+4 wave is claimed.

## Follow-ups

- Re-run on both lanes as part of AJ15e and record the *measured* figure in
  `CURRENT.md`, replacing the stale one.
- Consider whether `_with_runtime_manifest` should be promoted into a shared test
  helper module rather than duplicated between `test_attempt_journal.py` and
  `test_staged_revision.py` — duplication is what allowed the drift.
- Independent review of this fixture migration (not yet obtained).

## Worktree hygiene

No commit. Only `tests/execution/test_staged_revision.py` changed; production
code untouched. Nothing staged, reset, stashed, or cleaned.
