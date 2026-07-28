# AJ15b — POSIX inode reuse defeats stale-lock replacement-race softening

- Date: 2026-07-28 (America/Toronto)
- Author: Claude executor session, Stage 2, worktree `galaxy-r3-implementation`.
- Ledger item: **AJ15b**, the "real POSIX/WSL replay" clause.
- **Severity: real correctness defect**, previously invisible. Found by actually
  running the POSIX lane for the first time.
- No commit. No activation. Launch embargo unchanged.

## Why this was never seen before

AJ15b requires "real POSIX/WSL replay". Until now the suite had only ever run on
Windows, where **89 POSIX-only tests skip**. This session stood up the missing
lanes:

- **Python 3.12 on Windows** — installed via `uv` (host had only 3.11.15 / 3.14).
- **Python 3.12 on WSL Ubuntu (ext4)** — venv at `/home/fireh/venv312`, with
  `TMPDIR=/home/fireh/galaxy-tmp` on **ext4** rather than the default tmpfs, so
  `tmp_path` exercises genuine ext4 semantics.

The first POSIX run immediately produced a failure that cannot occur on NTFS:

```
FAILED tests/execution/test_fsio.py::test_stale_reclaimer_c_cannot_unlink_b_after_observing_a
OSError: native deletion target identity differs   (fsio.py:4205, _removePosixFile)
```

Attribution was **proved, not assumed**: the session's earlier AJ15b publication
edit was temporarily reverted and the POSIX failure reproduced identically
without it, then the file was restored and byte-compared. **Pre-existing defect
in Codex's code, not introduced here.**

(Incidental finding from that same experiment: the earlier ceiling-quota RED
`test_native_publication_refuses_partial_at_directory_ceiling_untouched`
*already passed* on POSIX before that fix — its failure mode was
Windows-specific. The fix remains correct and makes the refusal explicit and
platform-independent, but its RED only ever manifested on Windows.)

## The defect

`_maybeStealStale` (`platform_core/core/fsio.py:~4890`) reclaims a lock proved
stale. It captures `identity` for the exact file it proved dead, then calls
`directory._removeFileAdmitted(name, expected=identity)`. If that raises, it
softens **only** what it believes is a benign disappearance/replacement race:

```python
except OSError:
    successor = directory._entry(name).identity   # (FileNotFoundError -> return)
    if not _sameNativeFileObject(successor, identity):
        return
    raise
```

`_sameNativeFileObject` compares only the **stable object tuple** —
`(volume_id, file_id, is_directory, is_reparse, mount_id, reparse_tag)`.

**On POSIX, `file_id` is the inode, and ext4 readily reuses a just-freed inode
for the next file created in the same directory.** So in the A/B/C race the test
models — stale lock A observed, then replaced by a fresh, legitimately-held lock
B before the unlink — B can land on **the very same inode** A just vacated. The
stable tuple is then identical, `_sameNativeFileObject` reports "same object",
the benign-race branch is skipped, and the `OSError` escapes out through
`_tryAcquireLockLease` → `tryAcquireLock`.

Two distinct guards disagreed about identity, and that disagreement *was* the bug:

| Guard | Comparison | Result in the race |
|---|---|---|
| `_removePosixFile` (fsio.py:4205) | **full** `NativeFileIdentity` equality | correctly detected the change and refused to unlink B |
| `_maybeStealStale` softening | **stable tuple** only | thought it was the same object, re-raised |

The safety property itself held — B was never deleted; `_removePosixFile` refused.
The failure was in the *error contract*: `tryAcquireLock` is a boolean API and
must return `False` when it cannot reclaim, not raise `OSError` at the caller.

On Windows this is unreachable because NTFS file IDs are not aggressively reused,
so the successor always looked different and the softening always fired.

## Fix

Compare the **full** identity in the softening, not just the stable tuple:

```python
if not _sameNativeFileObject(successor, identity) or successor != identity:
    return
```

Any observed difference — including the inode-reuse case where the stable tuple
matches but mtime/size/etc. do not — means the name no longer resolves to the
exact file we authorized reclaiming. Fail closed: leave the successor untouched
and report "did not reclaim". `raise` is now reserved for the case where the
successor is byte-identical in identity, i.e. the `OSError` had some other cause.

This is fail-closed in the correct direction: the worst outcome is declining to
steal a genuinely stale lock (caller retries), versus deleting a live lock held
by another process.

## Verification (three platforms, two lanes)

| Lane | Result |
|---|---|
| **WSL Ubuntu ext4, Python 3.12** (`tests/execution/test_fsio.py`) | **298 passed, 45 skipped, 0 failed** (was 297 passed / 1 failed) |
| **Windows, Python 3.11.15** | **254 passed, 89 skipped, 0 failed** |
| **Windows, Python 3.12.13** | **254 passed, 89 skipped, 0 failed** |

`ruff check` → All checks passed. `mypy` → Success, no issues. No regression on
either Windows lane; the previously-skipped POSIX cases now execute and pass.

## Other findings from standing up the lanes

1. **Flaky concurrency test (pre-existing, not mine):**
   `test_concurrent_process_lock_acquisition_has_one_exact_winner` is
   **non-deterministic**. Back-to-back isolated runs on Python 3.11 gave one pass
   (0.41 s) and one failure (20.63 s, barrier-deadline shaped, assertion at
   `tests/execution/test_fsio.py:2629`). It also failed in a 3.12 consolidated run
   while passing 3/3 isolated on 3.12. It spawns two subprocesses that each import
   `platform_core` and race for a lock behind a 20 s barrier, so it is sensitive
   to process-start latency under load. It exercises
   `tryAcquireLockLease`/`releaseLock` — a different code path from the changes in
   this session. **A flaky test cannot serve as evidence; this should be
   stabilised before the AJ15e matrix is claimed.**
2. **Pre-existing deterministic failure**, unchanged and still open:
   `tests/control/test_external_controller_state.py::test_runtime_install_constructor_cleanup_ambiguity_poison_is_permanent`
   (fails on both 3.11 and 3.12; proved not caused by this session).

## AJ15b status after this

Materially advanced but **still `[ ]`**. Now satisfied: dual Python lane
(3.11 + 3.12) and **real POSIX/WSL replay**, which was the long-standing blocker
and which found this defect. Still outstanding:
- **Corrected independent specification + code-quality review** of both this
  inode-reuse fix and the earlier ceiling-quota fix.
- Stabilise the flaky concurrency test above.
- Confirm the remaining AJ15b semantics (full child-name vocabulary, enumeration,
  process-birth identity, deletion fsync/parent-sync failure prefixes) are
  genuinely covered now that the POSIX cases execute — they pass, but coverage
  should be reviewed rather than assumed from a green count.

## Reproduce

```bash
# WSL Ubuntu, ext4 TMPDIR (NOT the default tmpfs)
wsl -d Ubuntu -- bash -lc "cd /mnt/c/Users/fireh/.config/superpowers/worktrees/9to5/galaxy-r3-implementation \
  && TMPDIR=/home/fireh/galaxy-tmp /home/fireh/venv312/bin/python -m pytest tests/execution/test_fsio.py -q"
```

Windows 3.12 venv (deps installed, outside the worktree so the dirty inventory is
untouched):
`C:\Users\fireh\AppData\Local\Temp\claude\C--9to5\2c2e8b0d-580b-45df-893a-40b25c4cd181\scratchpad\venv312\Scripts\python.exe`

## Worktree hygiene

No commit. The change is one softening condition plus its explanatory comment in
`platform_core/core/fsio.py`, living in the shared dirty worktree alongside
Codex's uncommitted Stage 2 work. Nothing staged, reset, stashed, or cleaned. The
3.12 venvs were created **outside** the worktree specifically so Codex's
dirty-file inventory is unchanged.
