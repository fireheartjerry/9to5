# AJ15b partial FIX-FIRST evidence — prospective-debris directory-ceiling refusal

- Date: 2026-07-28 (America/Toronto)
- Author: Claude (Opus 4.8) executor session, resuming Codex's Stage 2 mid-flight
  worktree `galaxy-r3-implementation`.
- Stage: 2, Transactional Singularity Kernel. Sub-item: **AJ15b** (progress
  ledger `docs/superpowers/checkpoints/GALAXY-R3-PROGRESS.md`).
- Scope of this record: **one** concrete RED test closed inside the larger,
  still-open AJ15b boundary. This does **not** flip AJ15b `[ ]` → `[x]` and
  grants **no** runtime authority. Production launch embargo unchanged; no
  activation, no TOFU ceremony, no network/paid call occurred.

## What was failing (the exact resume point)

`git status` on entry showed the shared dirty worktree Codex left (≈317 entries).
`CURRENT.md` → "Exact next action" named two open Stage 2 FIX-FIRST boundaries
(AJ15b native filesystem semantics; AJ15c ceremonial-snapshot authority). Running
the two hot suites gave exactly one RED:

```
tests/execution/test_fsio.py::test_native_publication_refuses_partial_at_directory_ceiling_untouched
  → Failed: DID NOT RAISE NativeDirectoryQuotaExceeded
1 failed, 293 passed, 89 skipped   (Python 3.11.15, Windows; 89 skips are POSIX-only)
```

The credential suite (`tests/execution/test_credential_broker.py`, AJ15c surface)
was already fully green here — the single code gap was in AJ15b's **prospective
debris quota** at the directory ceiling.

## Root cause

`NativeDirectoryHandle._reconcileCreateOnlyFileAdmitted` in
`platform_core/core/fsio.py`.

When a create-only publication finds a retained same-payload temp
(`_nativePublishTempName(name, payload)` — note this name encodes the payload
digest + size and is otherwise randomized by pid / process-start-token /
thread-id / `os.urandom(8)`, so it never name-collides with a fresh temp), it
splits on whether the retained temp is **complete** (`debris.observed ==
payload`) or an **incomplete exact prefix** of an interrupted write of the same
payload (`payload.startswith(debris.observed)`):

- **Complete** debris took the correct order: reserve capacity (debris still
  present) → publish fresh temp → `_requirePublishedRegularFile` → `removeFile`
  the old debris. At the ceiling it either promotes the complete temp in place
  (net-zero slot) or refuses via `_requireNativePublicationDirectoryCapacity`.
- **Incomplete-prefix** debris took a different, wrong order: it called
  `removeFile(debris)` **first**, then fell through to reserve/publish. Removing
  the partial freed a slot, so at a full directory (ceiling = 4: 3 ordinary + 1
  partial) the sequence became remove→3 then publish→4 and **succeeded** instead
  of refusing, and it mutated (deleted) the retained partial. This also violated
  the fresh-publish-before-old-debris-cleanup ordering that
  `test_native_reconcile_replays_fresh_publish_before_old_debris_cleanup` pins
  for the complete case.

## Fix

Unified both same-payload cases onto the reserve-first / cleanup-after path,
keeping only the complete-**and**-at-ceiling promote shortcut. The incomplete
prefix now:

1. `listEntries` (debris still present),
2. `_boundedNativePublicationEntries(..., reserve_one=True)` +
   `_requireNativePublicationDirectoryCapacity` — **raises
   `NativeDirectoryQuotaExceeded` ("...directory ... capacity...") here, before
   any mutation, when at the ceiling**, leaving the partial untouched,
3. publish a fresh (uniquely named) temp, `_requirePublishedRegularFile`,
4. `removeFile` the retained partial **after** publication.

Diff is localized to the `if matching:` block of
`_reconcileCreateOnlyFileAdmitted` (~replacing the `if debris.observed ==
payload:` / trailing `self.removeFile(...)` early-remove with the unified
reserve→publish→cleanup block + a short ordering comment). No signature, export,
or other call site changed.

### Behaviour preserved (why the 293 stayed green)
- `test_native_reconcile_replaces_exact_payload_bound_partial_prefix` (partial,
  below ceiling): still publishes fresh + removes partial → final `immutable.bin`,
  temp gone.
- `test_native_publication_promotes_complete_retained_temp_at_ceiling` /
  `test_native_publication_max_minus_one_crash_is_recoverable_at_ceiling`
  (complete temp at ceiling): still hit the promote shortcut (net-zero slot),
  returning the retained temp identity.
- `test_native_reconcile_republishes_exact_payload_bound_full_temporary` and the
  lost-cleanup-response replay test: unchanged (complete-below-ceiling path is
  byte-for-byte the same sequence as before).

## Verification run (this session)

- `pytest tests/execution/test_fsio.py tests/execution/test_credential_broker.py`
  → **294 passed, 89 skipped, 0 failed** (was 293 passed / 1 failed).
- Target test alone: **1 passed**.
- `ruff check platform_core/core/fsio.py` → All checks passed.
- `mypy platform_core/core/fsio.py` → Success: no issues found.
- `py_compile` → OK. `git diff --check` → clean.
- Runtime: **Python 3.11.15 only, Windows host.**

## NOT done — what AJ15b still needs before `[x]`

The ledger acceptance for AJ15b is broader than this one RED. Still open:

1. **Python 3.12 lane** — unavailable on this host (`py -3.12` not installed);
   the second lane the discipline requires was not run.
2. **Real POSIX/WSL replay** — 89 POSIX-only tests skip on Windows, including the
   deletion fsync / parent-sync failure-prefix and native child-name vocabulary
   cases central to AJ15b. Not exercised here.
3. **Corrected independent specification + code-quality review** — not yet
   obtained for this change.
4. The remaining AJ15b semantics named in `CURRENT.md` (full child-name
   vocabulary, enumeration, process-birth identity, deletion-sync failure
   prefixes) are covered by currently-passing tests on 3.11/Windows but must be
   confirmed on 3.12 + WSL.

## Suggested next actions for Codex

- Re-run this matrix on **Python 3.12** and under **WSL/POSIX** (unskips the 89).
- Obtain the corrected independent review for the `_reconcileCreateOnlyFileAdmitted`
  change, then flip AJ15b `[ ]`→`[x]` in `GALAXY-R3-PROGRESS.md`.
- Proceed to **AJ15c** (still open): remove self-mintable clone snapshot
  admission; require fresh sealed credential absence before terminal
  broker/journal truth; reject a missing runtime manifest before provisioning
  mutation. (Its `test_credential_broker.py` suite is green on 3.11/Windows but
  the ledger item is unchecked pending its own review + snapshot-authority work.)
- Then run AJ15e (full AJ10–AJ15 dual-runtime affected matrix), retaining every
  deterministic failure as a fixture.

## Worktree hygiene

No commit was created. The change lives in the shared dirty `fsio.py` alongside
Codex's uncommitted Stage 2 expansion, per the CURRENT.md rule not to
discard/reset/overwrite the worktree and the requirement that kernel Task 3+4
land as one atomic wave. Nothing was staged, reset, or cleaned.
