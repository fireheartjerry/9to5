# AJ15b POSIX dual-lane replay (2026-07-28)

Closes two of AJ15b's three open clauses — the Python 3.12 lane and the POSIX
replay of the 89 Windows-lane skips — on native Linux ext4. No production code
changed in this report's work; the measurements are of the code already on the
branch. No activation, no TOFU ceremony, embargo intact.

## Environment

- Ubuntu 24.04, kernel 6.8.0, **native ext4** (not WSL, not tmpfs).
- Python 3.12.3 (`/home/ubuntu/code/9to5-galaxy-r3/.venv`).
- Python 3.11.15 via `uv`, venv deliberately created **outside the worktree** at
  the session scratchpad so the dirty-file inventory is unchanged.
- No Docker.

## Commands

```txt
.venv/bin/python -m pytest \
  tests/execution/test_fsio.py tests/execution/test_credential_broker.py -q

PYTHONPATH=<repo> <scratchpad>/venv311/bin/python -m pytest \
  tests/execution/test_fsio.py tests/execution/test_credential_broker.py -q
```

## Result

| lane | passed | skipped | failed |
|---|---|---|---|
| Python 3.11.15, Linux ext4 | 338 | 45 | **0** |
| Python 3.12.3, Linux ext4 | 338 | 45 | **0** |
| Python 3.11, Windows (prior report) | 294 | 89 | 0 |

Both POSIX lanes agree exactly, so the AJ15b surface is now measured on both
Python versions on POSIX, not only on 3.12/WSL.

## The 89-skip replay clause is satisfied

The suite has 383 cases on every lane (338 + 45 = 294 + 89 = 383).

Every one of the 45 POSIX skips comes from a **static**
`@pytest.mark.skipif(os.name != "nt", ...)` decorator — 15 decorator sites in
`tests/execution/test_fsio.py`, several parametrized, none in
`test_credential_broker.py`:

```txt
 30  Windows native component vocabulary   (fsio.py:832, parametrized)
  5  Windows retained-handle cleanup       (fsio.py:60,100,137,183)
  3  Windows native name equivalence       (fsio.py:854,869,884)
  2  Windows retained-handle boundary      (fsio.py:3561,3581)
  1  Windows retained replace boundary     (fsio.py:4779)
  1  Windows retained publication ordering (fsio.py:1767)
  1  Windows retained-handle move boundary (fsio.py:3628)
  1  Windows publication mutex boundary    (fsio.py:3186)
  1  Windows 8.3 alias identity            (fsio.py:912)
```

Because the guard is `os.name`, each of those 45 necessarily **executes** on the
Windows lane. Therefore the set executed on both lanes is
`383 - 45 = 338` minus the POSIX-only cases; solving against the Windows lane:

```txt
executed_on_both      = 294 - 45  = 249
posix_only_executed   = 338 - 249 =  89
windows_skipped                    =  89   <- equal
```

The 89 cases skipped on Windows are exactly the 89 executed only on POSIX, and
they all passed. Combined with the 45 Windows-only cases passing on Windows,
**no case in this surface is dark on both lanes.** That is the property AJ15b's
replay clause asks for, and it is now arithmetic rather than assertion.

Caveat kept explicit: this proves *execution* coverage of the union, not that
the Windows lane numbers are current. The Windows figures are quoted from
`2026-07-28-aj15b-prospective-debris-ceiling-fix.md` and were measured on
Python 3.11 only.

## Clause status after this report

- [x] Python 3.12 lane — done here, and additionally 3.11 on POSIX.
- [x] POSIX/WSL replay of the 89 skips — done here on native ext4, 0 failures.
- [x] Corrected independent review — **PASS on both changed functions**, by a
  reviewer given no prior context and instructed to refute first. See
  `2026-07-28-aj-packet-closure-progress.md` §1 for the full verdicts, including
  one real error-contract leak it found (`OSError` escaping `tryAcquireLock`'s
  documented `-> bool`), which is pre-existing and independent of the AJ15b fix.

Residual, stated plainly: the review covered the two functions AJ15b changed
(`_maybeStealStale`, `_reconcileCreateOnlyFileAdmitted`). The rest of AJ15b's
bounded-semantics list — child-name vocabulary, deletion debris quotas,
fail-closed process-birth identity, deletion fsync/parent-sync failure prefixes
— is *green on both lanes* but was not separately re-reviewed, and green is not
reviewed.
