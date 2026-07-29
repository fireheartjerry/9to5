# Session close — findings that post-date the transport commit, and exact next actions

- Date: 2026-07-28 (America/Toronto)
- Author: Claude executor session.
- Branch `galaxy-r3-implementation`; transport commit `5c33df19`.
- **Purpose: this file is the single continuation entrypoint.** It captures three
  findings that are NOT anywhere else in the repo — two landed after `5c33df19`
  was pushed, one was reasoned out and never written down. Read this together
  with `docs/superpowers/checkpoints/CURRENT.md`.
- No activation. No TOFU ceremony. Global launch embargo in force.

---

## Finding 1 — AJ10 through AJ14 are ALREADY IMPLEMENTED. Do not rewrite them.

This is the most schedule-relevant finding of the session and it arrived after
the push, so it appears in no other document.

The ledger marks AJ10–AJ14 `[ ]`. **That is an evidence policy, not missing
code.** A verification pass over `platform_core/runtime/attempt_journal.py`
(untracked, hence invisible to any git-based review) found all five fully
implemented and test-covered. Scoped run:

```
python -m pytest tests/execution/test_attempt_journal.py \
  -k "resource_set or empty_resource or resource_manifest or without_intent \
      or incomplete_resource or missing_resource or completed_resource or concurrent_resource"
→ 59 passed, 163 deselected (Python 3.11, Windows)
```

| Item | Status | Primary implementation |
|---|---|---|
| **AJ10** canonical closed-set intent, sorted role-tagged identities, full contract digests | IMPLEMENTED | `_resource_set_intent_bytes` `attempt_journal.py:2798`; `_resource_identity:2578`; `_resource_registration_contract_digest:2582`; canonical-sort enforced at write `:3935` and replay `:2925-2927` |
| **AJ11** deterministic completion event binding every sequence-zero registration, re-read before exposure | IMPLEMENTED | `_resource_set_completion_bytes:2865`; re-read from disk after append `:4105→:4110`; cross-check `:3752-3755` |
| **AJ12** typed missing vs incomplete; orphan dirs / membership mismatch = corruption | IMPLEMENTED | `MissingResourceSet:127`, `IncompleteResourceSet:131`; raises `:3095/:3109/:3137/:3189/:3738`; orphan→corruption `:3699-3702`, `:2982-2985`; consumers honour the split (`process_resources.py:550,865`, `worktree.py:775,1253`) |
| **AJ13** resume identical crash prefix, reject changed retry without append, exactly one set under concurrency | IMPLEMENTED | resume `:4010→:4085`; manifest-vs-reservation refusal *before* any write `:3022-3025`; create-only reservation dir `:3040`; multi-reservation refused `:3016` |
| **AJ14** explicit idempotent empty closure; cannot widen or enter RUNNING | IMPLEMENTED | `completion_resources` is `tuple \| None`, gates test `is None` (`:3729`, `:4054-4060`) so empty-but-complete ≠ absent; RUNNING gates `:4441-4476` |

Notable tests: `test_attempt_journal.py:3363, 3746, 3767, 3890, 4048, 4574, 4636,
4692, 4756, 4784, 5029, 5109`. Several use real `os._exit()` subprocess
failpoints and byte-compare the whole journal tree to prove *no* append occurred.

There is **no** TODO, xfail, `NotImplementedError`, feature flag, or dark gate in
any AJ10–AJ14 path. The boxes are gated on **AJ15e** per the ledger's own policy
(`GALAXY-R3-PROGRESS.md:23-28`, `:1054`).

> **Action:** what AJ10–AJ14 need is *verification evidence* — dual Python lane,
> POSIX replay, independent review — **not source**. Anyone who starts
> implementing them is duplicating finished work.

One precision caveat (not a gap): in the empty-set case RUNNING is actually
refused by the admission-manifest guard at `:4447`, because a record carrying an
admission manifest can never register an empty set (`:358`). The explicit
`not registered_resources` guard at `:4452` is defence-in-depth and unreachable
in the manifest-bound path. The test accepts either message
(`match="admission manifest|non-empty"`).

---

## Finding 2 — the activation ladder does not exist as documented. "Get to shadow" cannot go through the run loop.

A gate audit was run to answer "what can start emitting evidence now?". The
answer materially changes how the goal's *"nothing stays dark"* directive must be
executed, and it is recorded nowhere else.

**The embargo is unconditional.**
```python
# platform_core/execution/launch_guard.py:22-26
def requireTransactionalKernelActive(**_untrusted_context: object) -> None:
    raise TransactionalKernelInactive(
        "transactional Singularity kernel is inactive during implementation")
```
No branch, no flag, no env var, no receipt input. Empirically confirmed: setting
`GALAXY_R3_POLICY_ENFORCEMENT_ENABLED=1`, `FULL_STACK=1`, and `force=True` still
raises. `tests/execution/test_launch_guard.py:29-32` locks this by asserting the
module exposes no `activate`/`setActive`/`enable`/`installReceipt`. It fires at
seven production entrypoints: `main.py:343`, `orchestrator.py:178`,
`agents/execution/executor.py:317`, `executor_stream.py:240`,
`platform_core/execution/wiring.py:103` and `:196`, `learning/evolution/evolver.py:91`.
**The only lift is replacing the module source in the atomic Task 3/4 wave.**

**There is no dark → shadow → qualified → live ladder.** There is a binary
`activation_state ∈ {"inactive","active"}` on a protected anchor record
(`bootstrap/galaxy_launcher/anchor.py:678,707,835-837`). **Nothing in the repo
ever writes `"active"`.** Every writer hardcodes `"inactive"`
(`tofu_finalize.py:393,412,508,580`; `anchor.py:9109,9190`;
`tools/lock_galaxy_runtime.py:1619,1628,1667`; `capsule.py:22`) and every
validator *requires* `"inactive"` (`anchor.py:8170,8318,8500`;
`activation_harness.py:936,1052,1191`; `singularity_service.py:619,657`). The
cutover routine is literally `run_inactive_cutover` (`anchor.py:957`). The only
`"active"` in the tree is test fixtures.

**No activation overlay, no GraphWarrant.** `platform_core/singularity/activation_overlay.py`
(named in the Pulsar plan) **does not exist**; `find -iname "*overlay*"` and
`-iname "*warrant*"` return zero. `GraphWarrant` has exactly one non-doc
occurrence — a negative self-test in `tofu_bootstrap.ps1:872-886` that throws even
when handed a non-null warrant. Corroborated by
`reports/2026-07-14-galaxy-r3-stage-1-receipt.json:44-45`:
`"active_overlays": []`, `"graph_warrants": []`.

**Almost nothing emits evidence today.** `galaxy_evidence.py` writes nothing;
`EvidenceGate`, `BehaviorCapability`, and the receipt dataclasses have zero
production callers. `ShadowEvidenceJournal` (`galaxy_experiments.py`) has no
constructor outside tests. `_require_shadow` (`galaxy_evidence.py:148-150`) makes
a non-shadow receipt structurally unconstructible. The single genuinely wired
shadow writer is `run_phase_mixin.py:151-163` → `state.meta["galaxy_shadow"]`,
which sits *downstream of* `orchestrator.py:178` and therefore only fires under
`--sim-run` / `--dry-run`.

**Two hazards worth separate triage:**
1. `solution_space.py:231-246` hardcodes `impact_score=0.5`, `adoption_score=0.5`,
   `risk_inverse=0.6` and tags 7 of 8 metrics `unknown_metrics`, but
   `qd_archive.py:73-75` only rejects those when
   `GALAXY_R3_POLICY_ENFORCEMENT_ENABLED` is on — which it is **not** by default.
   So fabricated numbers currently feed fitness/Pareto ranking as if measured.
   This is the inverse of the stated intent and squarely on the design's own
   "complexity theatre kill list".
2. `FULL_STACK` defaults **ON** (`_env.py:270-274`), so the epic/HN/fabric flags
   are live-configured today. They are harmless only because the embargo blocks
   the paths that would use them — not because they are off.

> **Action:** shadow evidence must come from a **standalone harness driving
> modules directly**, not the run loop. `AttemptJournal`, `ReceiptStore`, and
> `controller_state` are all constructible in diagnostic mode from a temp dir
> alone (`AttemptJournal.__init__` defaults `diagnostic=True`,
> `attempt_journal.py:2015`; `ReceiptStore` has zero gating flags,
> `receipts.py:1042`) and already write durable, hash-chained, content-addressed
> receipts. That is the shortest real path to "evidence now".

Ranked shortest-path-to-evidence (no code changes needed for the first group):
AttemptJournal + ReceiptStore → `object_manifest`/`git_index` (pure computation) →
`canonical_repo.attestCanonicalRepository` (point it at a normal clone; it refuses
linked worktrees, `:1357`) → `loose_refs` → diagnostic `controller_state` →
`sha1dc` + `git_object_writer`. Then, one fix away: the staged-revision path
(now green), the 3 TaskState durable-receipt REDs, and the diagnostic clone
kernel (needs the reviewed offline object-parser image preloaded, which also
unskips `test_transactional_clone_canary.py:72`).

---

## Finding 3 — controller-state failure: hypothesis, NOT a verified conclusion

`tests/control/test_external_controller_state.py::test_runtime_install_constructor_cleanup_ambiguity_poison_is_permanent`
fails deterministically on both lanes. Proved **pre-existing** (temporary revert
of this session's fsio edit reproduced it identically, then byte-compare restore).

Mechanism, confirmed by traceback:
```
installControllerRuntimeState   controller_state.py:1783
  ControllerStateStore.__init__ controller_state.py:640
    _initialize                 controller_state.py:710
      openNativeDirectory       fsio.py:4525
        _openNativeDirectoryAnchor fsio.py:4482
          NativeDirectoryHandle.__init__ fsio.py:1836  <- threading.RLock() (patched) raises
RuntimeError: injected post-stream constructor failure
```
The poison branch (`controller_state.py:1818-1838`) fires only when
`publication_started`, `reservation_cleanup_ambiguous`, or
`store_cleanup_ambiguous` — the last being
`isinstance(primary, _ControllerStateStoreConstructionCleanupError)`. Here
`primary` is a raw `RuntimeError` and `store` is `None`, so control reaches the
bare `raise` at `:1858`. `_initialize`'s cleanup block (`:786-811`) only wraps
into `_ControllerStateStoreConstructionCleanupError` when a close actually failed
(`cleanup_errors` non-empty); since the failure happens before `self._handle` is
assigned, there is nothing to close and the list stays empty.

**HYPOTHESIS (unverified):** test-vs-code ordering drift — the same class of bug
as the staged-revision fixture drift fixed this session. The test is named
"**post-stream** constructor failure" and patches `os.fdopen` so `close()` raises,
which implies it was written when `threading.RLock()` was first called *after* the
lock stream existed. `fsio.py:1836` now constructs an `RLock` inside
`NativeDirectoryHandle.__init__`, intercepting the injection **earlier** than
intended — so no stream exists, no cleanup error is recorded, and no poison fires.

If that holds, the correct fix is in the **test** (move the injection to a genuine
post-stream point), not in the poison logic. The alternative — treating any
constructor failure as ambiguous and poisoning permanently — is a real design
decision about authority semantics and must not be taken by guess.

> **Action:** verify the hypothesis before touching anything. Deliberately NOT
> fixed this session under the "escalate ambiguous security semantics" rule.

---

## Exact next actions (priority order)

1. **Establish a true native baseline.** On Linux the ~89 Windows-skipped POSIX
   tests run for the first time on real hardware. Run `test_fsio.py`,
   `test_staged_revision.py`, `test_attempt_journal.py`, `test_kernel_artifacts.py`
   on **both** Python 3.11 and 3.12. Re-derive every checkpoint figure from the
   measured output — do not carry forward any recorded number.
2. **Stabilise the flaky test**
   `test_fsio.py::test_concurrent_process_lock_acquisition_has_one_exact_winner`
   (back-to-back isolated 3.11 runs gave one pass at 0.41 s and one failure at
   20.63 s against the 20 s barrier; spawns two subprocesses that each import
   `platform_core`). **AJ15e requires retaining every *deterministic* failure as a
   fixture, so a flaky test blocks the whole matrix.**
3. **Triage the controller-state failure** using Finding 3's hypothesis.
4. **AJ16** registry retirement and **AJ17** retained-root TOCTOU closure — both
   unblocked, no operator decision needed.
5. **AJ15e**: full AJ10–AJ15 matrix, both lanes + POSIX. This is what flips
   AJ10–AJ14 and AJ15b/c to `[x]`.
6. **Atomic Task 3 + Task 4 wave** — one commit, **no activation**.
7. **Task 5** close-out and installed-LKG activation — operator ceremony.

## Blocked on operator/reviewer decisions — do not guess

- **AJ15c (a) remainder:** must the kernel-owned `object()` snapshot capability
  (`candidate.py:5373`, granted `:5533-5539`, consumed `clone.py:368`) be replaced
  outright, and by which sealed authority? Use-time liveness is now enforced, but
  the sentinel itself remains.
- **AJ15c (b):** must `CredentialBroker._markDestroyed` (`credential_broker.py:1068-1118`)
  independently re-prove absence on top of the already-fenced journal path, and
  must the `_existing_terminal_receipt` replay short-circuit
  (`credential_channel.py:1098`) re-observe?
- **AJ15c (c):** which provisioning entrypoint does the runtime-manifest clause
  target? `PrivateCloneProvisioner.provision` already validates at
  `worktree.py:664` before `attestCanonicalRepository` (`:673`) and before the
  first mutation `journal.create` (`:765`).

## Standing rules

Never reset/clean/stash the worktree. Failing-test-first. Dual lane + POSIX.
Independent review per packet. Evidence before assertion — run it, read it, quote
it. Prove attribution by revert/reproduce/restore; never write "probably
pre-existing". **Checkpoint numbers can be stale — re-measure** (`CURRENT.md`
claimed "staged revision 59 passed" when it was 59 FAILED). `tools/affected_tests.py`
under-reports; grep real callers of the changed symbol. A source-maturity flag
never grants runtime authority.
