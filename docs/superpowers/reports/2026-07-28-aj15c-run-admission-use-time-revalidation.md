# AJ15c sub-slice evidence — snapshot preparation reproves run admission at use time

- Date: 2026-07-28 (America/Toronto)
- Author: Claude executor session, continuing Codex's Stage 2 worktree
  `galaxy-r3-implementation`.
- Stage 2, Transactional Singularity Kernel. Ledger item: **AJ15c**, item (a)
  "remove self-mintable clone snapshot admission".
- Scope: **one sub-slice only.** AJ15c stays `[ ]`. No runtime authority granted,
  no activation, no TOFU ceremony, no network/paid call. Launch embargo unchanged.
- Companion: `2026-07-28-aj15b-prospective-debris-ceiling-fix.md`.

## Why this sub-slice was chosen

A full read of the AJ15c surface found its three clauses are in very different states:

| AJ15c clause | Finding |
|---|---|
| (a) self-mintable clone snapshot admission | **Genuine, un-fenced.** Kernel self-issues admission from `object()` sentinels; external authority checked only at build time. |
| (b) fresh sealed credential absence before terminal DESTROYED | **Largely implemented.** Journal DESTROYED already requires the sealed verifier + fresh observation (`attempt_journal.py:4215-4271`, `credential_channel.py:1519-1596`). Residual (broker `_markDestroyed` trusting the receipt; `_existing_terminal_receipt` replay short-circuit) is **ambiguous** — whether AJ15c wants independent broker-side re-proof is not deducible from the plan. |
| (c) reject missing runtime manifest before provisioning mutation | **Already satisfied** on the private-clone path: `worktree.py:664` validates before `attestCanonicalRepository` (673) and before the first mutation `journal.create(...)` (765). Which other entrypoint AJ15c targets is not deducible. |

(b) and (c) both require guessing at security semantics, so they were deliberately
left alone. Within (a), the **unambiguous** defect was chosen: the fix reuses the
*already-held, already-validated* authority pair and only moves the check to a
fresher point. No new authority, no design invention.

## The defect (use-time vs build-time authority)

`platform_core/execution/backends/clone.py`.

`TransactionalCloneKernel.__init__` validates controller-owned run admission
liveness (`typed_issuer._validateAdmission(typed_admission)`, ~line 331) and
`productionReady()` repeats the same full check (~line 448).

But `prepare()` — the snapshot-admission path — calls
`self._revalidateInstalledArtifacts()` as its **first** statement (line 814), and
that method revalidated only:
- `qualification.revalidate()` (artifact bytes),
- `_requireWriterSource(...)`,
- parser qualification identity,
- coordinator **identity** (`coordinator._run_admission is not self._run_admission`).

It never re-proved that the run admission is still **live**. Identity is not
liveness: a `RunAdmissionAuthority` that was live at construction and has since
been revoked still satisfied every check, so `prepare()` proceeded to
`_snapshot_admission_issuer.issue(...)` (line 847) and minted snapshot admission
under a dead external authority. Classic time-of-check/time-of-use gap on the
exact boundary AJ15c names.

## Failing test written first (TDD)

`tests/execution/test_kernel_artifacts.py::test_installed_clone_prepare_refuses_revoked_run_admission`

Builds a real installed kernel via `buildInstalledTransactionalCloneKernel`
(modelled on the existing
`test_installed_clone_kernel_factory_is_the_only_production_ready_path` fixture),
asserts `productionReady()` is True, then calls the public
`issuer.revokeRunAdmission(admission)` and asserts:

1. `productionReady()` is now False (proves the revocation actually took), and
2. `kernel.prepare(...)` refuses matching `run admission|not live`.

The manifest / quiescence / coordinator providers are `pytest.fail(...)` traps, so
the test also proves refusal happens **before** any composition work.

**RED (pre-fix), for exactly the right reason:**

```
E  AssertionError: Regex pattern did not match.
E    Expected regex: 'run admission|not live'
E    Actual message: 'lease must be CloneLease'
```

i.e. `productionReady()` correctly reported False, yet `prepare()` sailed past
revalidation and only tripped later on lease typing — demonstrating the gap.

## Fix

Added `TransactionalCloneKernel._requireLiveRunAdmission()` and called it from
`_revalidateInstalledArtifacts()` (right after `_requireWriterSource`). The helper
is a verbatim reuse of the `__init__` check: exact-type check on
`LandingAuthorityIssuer` / `RunAdmissionAuthority`, `isInstalledAuthority()`, then
`_validateAdmission(...)`, raising
`EnvironmentUnavailable("clone", "installed clone kernel run admission is not live", cause=exc)`.

Notes:
- `_revalidateInstalledArtifacts` still returns early when
  `self._artifact_qualification is None`, so **uninstalled/diagnostic kernels are
  unaffected** — no behavior change outside installed mode.
- `EnvironmentUnavailable` is a distinct `RuntimeError`, so it is not swallowed by
  the method's existing `except (KernelArtifactsUnavailable, OSError, ValueError)`
  re-wrap; the precise reason reaches the caller.
- Because `prepare()` revalidates twice (line 814, and again at 839 with the
  coordinator), admission liveness is now reproved both before and after
  coordinator construction.

## Verification (this session)

- New test: **PASS**. `tests/execution/test_kernel_artifacts.py`: **12 passed**.
- Clone surface (`test_execution_clone.py`, `test_transactional_clone_canary.py`,
  `test_kernel_artifacts.py`, `test_candidate.py`, `test_execution_router.py`,
  `test_execution_environment.py`): **129 passed, 1 skipped**.
- Consolidated across every surface touched this session (adds `test_fsio.py`,
  `test_credential_broker.py`, `test_attempt_journal.py`,
  `test_external_controller_state.py`): **720 passed, 91 skipped, 1 failed** —
  the single failure is the pre-existing one documented below.
- `ruff` clean; `py_compile` clean; `git diff --check` clean.
- `mypy platform_core/execution/backends/clone.py` → clean for this file; it
  reports one **pre-existing, unrelated** error in `tools/galaxy_plan_manifest.py:192`
  (an untouched file, reached by import-following).
- Runtime: **Python 3.11.15, Windows only** (no 3.12, no WSL on this host).

## Pre-existing failure — explicitly NOT caused by this session

`tests/control/test_external_controller_state.py::test_runtime_install_constructor_cleanup_ambiguity_poison_is_permanent`
fails deterministically. Attribution was **proved, not assumed**: the AJ15b
`fsio.py` edit was temporarily reverted (after a scratchpad backup) and the
controller test failed identically without it, while the revert simultaneously
reproduced the original AJ15b RED. The file was then restored and byte-compared
to the verified version. The failure is in a child process that globally patches
`threading.RLock` to raise; it is unrelated to publication or clone admission.
**Codex should triage this separately** — it is pre-existing in the dirty worktree.

## NOT done — what AJ15c still needs before `[x]`

1. **Clause (a) remainder:** snapshot admission is still *minted* from
   kernel-owned `object()` sentinels (`clone.py:350-371`,
   `candidate.py:5373-5487`). This slice makes issuance impossible under a dead
   external authority, but does not replace the sentinel-based capability itself.
   Deciding whether the sentinel must be replaced outright (and by which sealed
   authority) is a design decision left to the operator/Codex.
2. **Clause (b):** broker `_markDestroyed` independent fresh-absence re-proof and
   the `_existing_terminal_receipt` replay short-circuit — pending a decision on
   whether independent broker-side proof is required.
3. **Clause (c):** confirm whether a provisioning entrypoint other than
   `PrivateCloneProvisioner.provision` is the intended target.
4. **Python 3.12 lane + POSIX/WSL replay** — not available on this host.
5. **Corrected independent specification + code-quality review** — not obtained.

## Suggested next actions for Codex

- Decide ambiguities (a-remainder), (b), (c) above — each needs the "corrected
  independent review" wording AJ15c references, which is not in-repo.
- Re-run on Python 3.12 + WSL, then obtain independent review for this slice.
- Triage the pre-existing controller-state failure.
- Then AJ15e: full AJ10–AJ15 dual-runtime affected matrix, retaining every
  deterministic failure as a fixture.

## Worktree hygiene

No commit created. Changes live in the shared dirty worktree
(`platform_core/execution/backends/clone.py` modified;
`tests/execution/test_kernel_artifacts.py` modified) alongside Codex's
uncommitted Stage 2 work, per the CURRENT.md rule and the atomic Task 3+4 wave
requirement. Nothing was staged, reset, stashed, or cleaned. Pre-existing
size-audit debt (31 must_split files / 130 functions) was left untouched; the
added helper is 30 lines, well under the 70-line function threshold.
