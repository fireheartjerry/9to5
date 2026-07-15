# GALAXY Singularity Revision 3: Transactional Attempt Kernel Implementation Plan

> **Execution mode:** implement directly on `main` at the user's explicit request. Use test-driven development for every behavior change. Each task gets an implementer, a specification reviewer, and a code-quality reviewer before the next task starts.

**Goal:** Make every mutating autonomous coding attempt transactional: each retry gets a fresh self-contained external clone, explicitly trusted Local or a credential-separated Docker plane executes only there, a native no-follow snapshot crosses into a pinned networkless object parser, and only its bounded canonical tree/blob manifest crosses back to a small memory-safe host object writer. The exact staged revision is verified in a fresh no-link clone inside the universal credentialless hardened verifier, and promotion uses a fenced Git ref/materialization protocol plus a crash-reconcilable journal. Preserve the execution-origin tier as receipt evidence, fail closed when isolation or credential separation cannot be honored, and leave durable linked recovery evidence on every rejection or crash.

**Design sources:** `docs/superpowers/specs/2026-07-13-galaxy-singularity-revision-3-design.md`,
`docs/superpowers/specs/2026-07-13-galaxy-r3-qualified-capability-topology.md`,
`docs/superpowers/specs/2026-07-13-galaxy-r3-pulsar-singularity-r1-qualified-topology.md`,
and `docs/superpowers/specs/2026-07-13-galaxy-r3-quark-portfolio-r2-qualified-topology.md`.
This plan implements only the transactional prerequisite. Kernel completion does
not mean the 131-node / 250-edge GALAXY core or disabled 134-node / 256-edge
federation-ready target is implemented, and it does not authorize Pulsar or
Quark runtime work.

**Non-negotiable cost boundary:** all implementation and verification use repository-local tools plus the user's existing local Claude, Codex, Git, and Ollama capability surfaces. No paid API, hosted metered inference, or recurring SaaS dependency is introduced.

---

## 1. Kernel invariant

Canonical `main` is never the staging area.

```text
fresh outer candidate checkout for this attempt
  -> self-contained external clone with no canonical/common-dir link
  -> execute through explicitly trusted Local, or a no-shell credential plane plus credentialless Docker command sandbox
  -> snapshot candidate bytes through native retained no-follow handles
  -> parse/diff only in a pinned credentialless networkless object-parser container
  -> validate its bounded canonical tree/blob manifest with memory-safe host code
  -> write deterministic loose blob/tree/commit objects and pin checkpoint ref
  -> replay the same immutable manifest against expected canonical SHA
  -> pin immutable proposed ref and build a fresh no-link verification clone
  -> verify the exact proposed SHA through a fresh universal credentialless hardened verifier
  -> acquire canonical merge lock and Git-standard index writer fence
  -> durably journal verified promotion intent and fence ownership
  -> atomically update canonical ref from expected SHA to verified SHA
  -> materialize the exact manifest with the native handle-relative writer, then same-directory install the verified deterministic index artifact
  -> durably journal promotion outcome
  -> persist pending receipt chain, acknowledge journal, then persist terminal state
```

If preparation, verification, compare-and-swap, promotion, or cleanup fails:

- canonical files and HEAD remain unchanged unless a verified promotion already completed;
- terminal task state cannot be `done` without a successful promotion receipt;
- candidate commits remain addressable for recovery;
- cleanup failure is recorded separately from landing truth;
- no later candidate may build on a rejected revision;
- nothing may mutate the promoted tree after its verified SHA is sealed.

### Pre-implementation documentation gate

This approved design, qualified-topology addenda, and implementation plans are versioned before production code changes. Stage exactly these seven known documentation files, inspect the staged diff, commit them, and require the tree to contain no other documentation change before Task 1:

```powershell
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) { throw 'Pre-existing staged paths; preserve them and stop' }
$stageAllowlist = @(
  'docs/superpowers/specs/2026-07-13-galaxy-singularity-revision-3-design.md',
  'docs/superpowers/specs/2026-07-13-galaxy-r3-qualified-capability-topology.md',
  'docs/superpowers/specs/2026-07-13-galaxy-r3-pulsar-singularity-r1-qualified-topology.md',
  'docs/superpowers/specs/2026-07-13-galaxy-r3-quark-portfolio-r2-qualified-topology.md',
  'docs/superpowers/plans/2026-07-13-galaxy-r3-transactional-kernel.md',
  'docs/superpowers/plans/2026-07-13-galaxy-r3-pulsar-r1-implementation-plan.md',
  'docs/superpowers/plans/2026-07-13-galaxy-r3-quark-r2-implementation-plan.md'
)
$oldHead = (git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or -not $oldHead) { throw 'Unable to resolve pre-documentation HEAD' }
$emptyHooks = Join-Path ([System.IO.Path]::GetTempPath()) ("galaxy-empty-hooks-" + [Guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $emptyHooks
$gitSafety = @('-c', "core.hooksPath=$emptyHooks", '-c', 'commit.gpgSign=false', '-c', 'core.fsmonitor=false', '-c', 'core.autocrlf=false', '-c', 'core.safecrlf=true')
try {
  foreach ($path in $stageAllowlist) {
    $blob = (git @gitSafety hash-object -w --no-filters -- $path).Trim()
    if ($LASTEXITCODE -ne 0 -or $blob -notmatch '^[0-9a-f]{40,64}$') { throw "Closed documentation hashing failed: $path" }
    git @gitSafety update-index --add --cacheinfo "100644,$blob,$path"
    if ($LASTEXITCODE -ne 0) { throw "Closed documentation index update failed: $path" }
  }
} finally {
  Remove-Item -LiteralPath $emptyHooks -Force -ErrorAction SilentlyContinue
}
$actualStaged = @(git diff --cached --name-only)
if ($LASTEXITCODE -ne 0) { throw 'Unable to enumerate staged documentation' }
$unexpectedStaged = @($actualStaged | Where-Object { $_ -notin $stageAllowlist })
if ($unexpectedStaged.Count) { throw "Unexpected staged paths: $($unexpectedStaged -join ', ')" }
$missingStaged = @($stageAllowlist | Where-Object { $_ -notin $actualStaged })
if ($missingStaged.Count) { throw "Documentation manifest paths were not staged: $($missingStaged -join ', ')" }
$unstagedTracked = @(git diff --name-only)
if ($LASTEXITCODE -ne 0) { throw 'Unable to enumerate unstaged paths at documentation gate' }
if ($unstagedTracked.Count) { throw "Unstaged tracked paths at documentation gate: $($unstagedTracked -join ', ')" }
$untracked = @(git ls-files --others --exclude-standard)
if ($LASTEXITCODE -ne 0) { throw 'Unable to enumerate untracked paths at documentation gate' }
if ($untracked.Count) { throw "Untracked paths at documentation gate: $($untracked -join ', ')" }
$actualStaged
git diff --cached --check
if ($LASTEXITCODE -ne 0) { throw 'Documentation staged diff check failed' }
$emptyHooks = Join-Path ([System.IO.Path]::GetTempPath()) ("galaxy-empty-hooks-" + [Guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $emptyHooks
try { git -c "core.hooksPath=$emptyHooks" -c commit.gpgSign=false -c core.fsmonitor=false commit --no-verify --no-gpg-sign -m "docs: plan GALAXY transactional kernel" }
finally { Remove-Item -LiteralPath $emptyHooks -Force -ErrorAction SilentlyContinue }
if ($LASTEXITCODE -ne 0) { throw 'Closed documentation commit failed' }
$baselineSha = (git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or -not $baselineSha) { throw 'Unable to resolve documentation commit' }
$committedPaths = @(git diff-tree --no-commit-id --name-only -r $oldHead $baselineSha)
if ($LASTEXITCODE -ne 0 -or @($committedPaths | Sort-Object).Count -ne $stageAllowlist.Count -or (Compare-Object ($stageAllowlist | Sort-Object) ($committedPaths | Sort-Object))) { throw 'Documentation commit tree differs from the exact seven-path manifest; stop for reconciliation' }
foreach ($path in $stageAllowlist) {
  $committedBlob = (git rev-parse "$baselineSha`:$path").Trim()
  if ($LASTEXITCODE -ne 0 -or -not $committedBlob) { throw "Unable to resolve committed documentation blob: $path" }
  $worktreeBlob = (git hash-object --no-filters -- $path).Trim()
  if ($LASTEXITCODE -ne 0 -or -not $worktreeBlob -or $committedBlob -ne $worktreeBlob) { throw "Documentation commit bytes differ from reviewed worktree bytes: $path" }
}
git show-ref --verify --quiet refs/9to5/baselines/galaxy-r3-qualified
if ($LASTEXITCODE -eq 0) { throw 'Baseline ref already exists; preserve it and stop for explicit reconciliation' }
if ($LASTEXITCODE -ne 1) { throw 'Unable to prove baseline ref absence' }
$zeroOid = "0" * $baselineSha.Length
git update-ref refs/9to5/baselines/galaxy-r3-qualified $baselineSha $zeroOid
if ($LASTEXITCODE -ne 0) { throw 'Create-only baseline ref installation failed' }
$resolvedBaseline = (git rev-parse refs/9to5/baselines/galaxy-r3-qualified).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Unable to resolve installed baseline ref' }
if ($resolvedBaseline -ne $baselineSha) { throw "Baseline mismatch: $resolvedBaseline != $baselineSha" }
$resolvedBaseline
git status --short --branch
if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect post-baseline status' }
```

The create-only baseline ref is the affected-test boundary for the entire implementation, independent of how many reviewer correction commits are required.

An outer candidate clone is mandatory for every attempt that may mutate repository state. “Mutating” is the conservative default; only an explicit, enforced read-only policy may bypass it. Local and Docker receive the same standalone Git representation; model-executed commands never run in a linked worktree that shares canonical refs or the attempt journal. Remote mutation fails before execution until a transactional collection adapter exists.

### Consistency and threat boundary

The kernel guarantees crash/retry/concurrency truth for its own paths and for cooperative Git porcelain writers that respect Git's standard index/ref locks. There is one unavoidable, explicit bootstrap assumption: before TOFU exists, the human operator and OS tools used to author/review/commit these design documents are out-of-band trusted; that documentation-only act is not claimed as protected self-modification. Task 1 production-source commit and every later controller activation use the external sterile anchor path instead of ordinary target `git add`/`git commit`. The main execution path consumes run-admission authority before startup knowledge refresh, work-directory grounding, TaskState creation/resume, elaboration, or orchestration; `runFull` revalidates it as its own first executable operation before constructing a control/dashboard surface. A no-follow canonical attestation then creates an immutable standalone source snapshot; elaboration, discovery, council, planning, replanning, path checks, and every repository-derived read/static-analysis operation consume only bounded receipts from a credentialless broker over that snapshot. Repository scripts/configuration never execute in pre-admission, snapshot-broker, kernel, canonical, verification, or hostile/unknown host paths. All model-executed Git commands target standalone clones. The sole host-code exception is the explicitly trusted-Local tier inside its private clone: it requires a live exact-scope process grant from fresh top-level operator authorization, and its immutable enforcement receipt records `os_enforced=False` and `eligibility=trusted_local`. Unknown or hostile repositories are ineligible for that tier. They use the split Docker execution plane described below, where the credential-bearing model driver cannot execute repository code and every shell/process action crosses a credentialless sandbox broker. If that plane cannot be proven ready, execution fails closed; it never falls back to Local. An operator using direct Git plumbing or a process writing canonical files without taking Git's index lock remains outside this wave's cooperative-writer claim. Such divergence is detected and quarantined, but the evidence must not claim impossible zero-transient mutation against an actor that bypasses the kernel.

That no-host-execution sentence is a **production autonomous-controller/model boundary**, not a claim that this human-directed implementation session is already sandboxed by software it is still building. Until final activation, the explicitly reviewed developer workflow—focused tests, linters, compilers, map generation, and implementation commits run by the operator/Codex on this trusted checkout—remains an out-of-band bootstrap activity. Its results are evidence only and cannot authorize activation. The installed LKG updater later rebuilds, verifies, reviews, and smokes the exact final SHA in pinned contained resources before it can become production authority. This distinction is recorded rather than pretending the system can retroactively sandbox its own construction.

Manifest/design truth corrections never ride inside or remain dirty across a source commit. If implementation or review discovers a required path/contract correction, stop the affected task, preserve source changes, stage only the exact design/plan documents, inspect and independently review that docs-only diff, commit it as a dedicated out-of-band trusted documentation checkpoint, and require cached/unstaged/untracked documentation state to be clean before resuming tests or source staging. Then regenerate that task's manifest-derived allowlist/commands from the committed plan. The create-only GALAXY baseline ref remains unchanged, so affected-test and final-review scope still includes every correction. Task 1's full-tree source proposal therefore cannot overwrite a dirty plan; Task 2 and the atomic Task 3+4 commit similarly reject dirty docs rather than sweeping them into implementation.

`tools/galaxy_plan_manifest.py` is the single deterministic mechanical reader for the `**Files**` blocks in Tasks 1-4. It accepts one or more exact task numbers and emits newline-delimited normalized repo-relative paths for `all`, `required-changes` (`Add`/`Create`/`Modify`), `red-tests` (`Add`/`Create` beneath `tests/`), `tests`, `python`, or `production-python`; it rejects duplicate/conflicting rows **inside one task block**, traversal/absolute paths, malformed headings/actions, empty selections, and paths outside the requested task blocks. Multi-task selection walks requested tasks in caller order and emits a stable unique path union, permitting an earlier `Add`/`Create`/`Test` path to be intentionally `Modify`/`Test` later. Action validation is deliberately separate from emission: it scans the documentation baseline and every plan task preceding the highest requested task, so a Task 3-only query recognizes files created by completed Tasks 1/2 without emitting or requiring them again. Parser tests pin Task 3-only, Tasks 3+4, every real overlap, and the Task 3/4 shared `run_loop.py`. `Test` rows are mandatory verification inputs but need not differ; every emitted `Add`/`Create`/`Modify` row must appear in the externally observed change set. `Add`/`Create` starts absent at the applicable prior-task state, while `Modify`/`Test` exists there. Every RED/green test gate, static gate, and staging allowlist below consumes this output instead of copying hundreds of paths; Task 1 uses the explicit complete `red-tests` list before the parser itself exists. This turns path/test parity into executable plan truth rather than reviewer arithmetic.

Path sets never ride wholesale on the Windows command line. The request-only Singularity client opens a transaction-bound external path-manifest upload and emits one canonical role record per normalized path: `allowed-only`, `test-only`, `required-change`, or `required-test`. These four roles are mutually exclusive encodings of the three logical sets, so the service reconstructs `Required ⊆ Allowed` and `Tests ⊆ Allowed` without accepting the same path twice. Raw JSON is never passed through the Windows PowerShell 5.1 native argv boundary, which strips embedded quotes. Instead, each canonical JSON chunk is strict-UTF-8 encoded and transported as canonical unpadded base64url. The request-only client and service reject padding, a non-base64url alphabet, alternate encodings, malformed UTF-8, or decode ambiguity; the service parses and canonical-reserializes the decoded JSON and requires exact byte equality. Every protected-pipe request contains at most 24 records **and** at most 8 KiB of the exact encoded request envelope. Scope and manifest IDs are service-issued bounded ASCII tokens; the helper holds each decoded records payload below 4 KiB, and the request-only client constructs and measures the full operation/scope/manifest/sequence/base64url envelope before sending with an explicit 8 KiB ceiling. The service independently measures both encoded envelope and decoded canonical bytes. It rejects blanks, duplicate paths or role records, invalid set relationships, reordering/replay, traversal, count/byte overflow, or paths outside the registered repository; it persists a create-only canonical content-addressed manifest outside the target, returns its SHA-256 plus total/required/test counts, and seals it before proposal preparation. Later calls carry only that opaque manifest ID and digest. The service re-reads and hashes it at every transition, while the target process can neither write nor substitute it. Tests cover the real Tasks 1-4 union, out-of-order/missing/duplicate chunks, role-confusion, multibyte paths whose character count fits but serialized byte count does not, maximum protocol overhead, client death, transaction replay, and the 32,767-character Windows limit. A real pinned-PowerShell client-boundary canary round-trips JSON quotes, backslashes and non-ASCII paths and proves byte equality after service decode/recanonicalization. The code blocks below spell this as `Register-SingularityPathManifest`; no implementation may expand a complete path set into one service argv.

This plan intentionally does **not** expand the whole GALAXY graph. It repairs the authority boundary beneath every Claude/Codex launch, normal execution, Society, parallel batches, and solution-space tournaments so later research mechanisms can rely on machine-checkable truth.

---

## 2. Durable contracts

### `SingularityAnchorReceipt`, `SingularityBootReceipt`, and `RunAdmissionAuthority`

The pre-Python Singularity Anchor is the small audited OS-native PowerShell source `bootstrap/galaxy_launcher/singularity_anchor.ps1`, provisioned by TOFU as external `galaxy-admin.ps1`. TOFU registers an OS service/task action that starts the exact OS-signed PowerShell executable as a **fresh** process with `-NoLogo -NoProfile -NonInteractive`, an empty external working directory, a closed environment/`PSModulePath`/`PATH`, no inherited stdin/console, and only its ACL-protected control pipe plus exclusive operator-approval surface. The anchor uses fully qualified .NET/native operations only—no aliases, functions, module autoload, command-name resolution, dot-sourcing, or ambient runspace. `singularity_admin_client.ps1` is a request-only pipe client launched in its own fresh `-NoProfile` host; it never holds anchor authority. The protected record binds the anchor digest, service/task action, host path/signature/digest, launch flags, pipe ACL, and environment policy. `anchor.py` is capsule-side manifest logic, not the pre-Python verifier. The anchor verifies the pinned Python executable/DLL/stdlib before launching it, so no unplanned native executable or toolchain artifact is assumed.

The root of trust is an OS-installed Singularity Anchor outside every target checkout. Its ACL-protected/OS-sealed record pins the expected capsule/controller/runtime digest and a monotone activation generation; only a live process-local `ControllerActivationAuthority` created by the previously trusted anchor plus fresh operator approval can compare-and-swap it. The anchor first verifies the pinned interpreter executable/DLL/stdlib digest, then starts a tiny standard-library-only zipapp installed under the per-user external kernel root. That capsule is never imported from or executed with a target checkout as cwd. It starts through the verified isolated interpreter (`-I -S`) with a closed environment, removes cwd/target/user site entries from import resolution, and verifies its own canonical manifest plus the content-addressed last-known-good controller and full runtime manifest against the anchor. The runtime manifest covers interpreter, stdlib, every Python/native dependency and DLL, dynamic module/entrypoint, schema, prompt/template, and asset byte; after verification the capsule adds only those external paths explicitly. Ambient host/venv/site packages are never visible. Replacing capsule, sidecar manifest, runtime directory, and writable generation together does not change the protected expected digest. Official CLI and Discord gateway services enter through the external anchor. The existing ignored machine-local `run.ps1` remains user-owned and untouched outside the trust boundary; tracked `bootstrap/galaxy_launcher/developer_redirect.ps1` can only call the installed request-only client or refuse, and neither path can confer production boot authority.

After verifying the last-known-good external controller bytes, the capsule may invoke only that bundle's minimal recovery entrypoint with a non-serializable `RecoveryAuthority`. This authority is bound to repository identity, anchor/controller generation, recovery deadline, watchdog, and the exact external journal/control roots. It permits no model/provider call, network, arbitrary or content-returning repository read, elaboration, planning, migration, or new attempt. It may only no-follow-read kernel metadata; quiesce already-registered resources; hash/type/identity-check the exact journal-bound expected-to-proposed changed-path set; and finish that existing ref/index/worktree/TaskState transaction under merge/index fences with the safe materializer. Content never leaves the recovery kernel. Attempts to inspect any non-journal path fail. The entrypoint emits an immutable `RecoveryReceipt` and exits.

Legacy target state migration is a separate optional one-time phase with a narrower `LegacyStateMigrationAuthority`, never an expansion of recovery. After recovery and before the post-recovery snapshot, the host kernel first opens every allowlisted legacy root and descendant component through native handle-relative no-follow APIs, retains and revalidates directory/file identities, enforces byte/file/depth/schema quotas, and rejects symlink, junction, reparse point, mount, unsupported type, identity race, or multi-link file. It copies only regular-file bytes through retained handles into an immutable external content-addressed snapshot. A credentialless network-disabled container receives that snapshot—not a target path or bind mount—and emits a normalized migration artifact/receipt; the external controller imports that artifact into the external state store. Outside-junction and outside-hardlink canaries must prove no external goldstone is read or changed. Target `.env`, secrets, provider/effect flags, logs, and arbitrary vault bytes never become live configuration. If safe migration cannot be proven, legacy resume is typed unavailable while a fresh run may continue. Only after migration closes does the capsule re-attest canonical metadata, perform source-acquisition registration when needed, create the immutable snapshot, run contained pre-spec analysis, prove complete quiescence, and obtain exact operator approval before starting the normal controller child. Direct `main.py`, `runFull`, candidate code, or persisted state cannot invoke recovery/migration or mint either authority.

The capsule passes non-serializable one-time `BootAdmissionCapability` and `OperatorSpecApprovalCapability` values through anonymous non-inheritable OS handles to a terminal-less controller child. The child consumes them once and derives `RunAdmissionAuthority`, bound to anchor/boot/controller/recovery receipt digests, activation generation, target attestation/base/snapshot, task/spec, child PID, watchdog, expiry, and revocation generation. Repository JSON, argv, environment, TaskState, copied handles, or direct `run.ps1`/`python main.py` invocation cannot mint it. Same-user malware or an operator deliberately bypassing the installed anchor is outside the target-repository isolation claim and is never mislabeled as prevented.

For self-referential 9to5 work, the target checkout is untrusted data and the controller is the previously activated external bundle. A successful repository promotion does not modify the running bundle. Building and activating a replacement controller is a separate verified restart transaction with an immutable activation receipt and rollback pointer; it never occurs from the candidate process or as teardown best effort.

`RunAdmissionAuthority` initially names immutable run revision `R0`, canonical base `B0`, and its exact source-snapshot receipt. It is never silently widened after a same-run promotion. Once a `PromotionReceipt` plus the complete `persistAttemptTransaction()` sequence prove `B0 -> B1`, TaskState acknowledgement, terminal-state persistence, and absence of mandatory reconciliation/cleanup work, the external kernel must first quiesce every old-revision driver, broker, sandbox, parser, verifier, reviewer, state worker, and clone lease; close new admission; attest `B1` through native no-follow handles; create and re-read a fresh immutable source snapshot; and append a content-addressed `RunRevisionAdvanceReceipt` linking `R0/B0`, the promotion/acknowledgement/terminal chain, `B1`, the new snapshot, resource-quiescence proof, watchdog, generation, and revocation counter. A crash after acknowledgement but before terminal persistence remains recovery-only and cannot admit `R1`. Only after the complete chain may the kernel derive a non-serializable `RunRevisionAuthority` for `R1/B1`. Drift to a commit not proven by that run's promotion chain requires a fresh operator-approved run and cannot be adopted. Because trusted-Local grants are exact-base capabilities, an `R0/B0` Local grant is invalid at `R1/B1`; without a fresh exact-base operator grant, rescheduled work uses the hostile split Docker plane or is typed unavailable. No descendant-chain wildcard or caller claim widens Local authority.

Every top-level `begin-cutover`, `begin-source-update`, and `begin-controller-update` consumes one service-owned repository-global transition slot across **all** generations and all three operation names. The slot is a monotone `reserved -> started_old -> advanced_recovery -> terminal_unacknowledged -> acknowledged` state machine; only acknowledged terminal state releases the live slot, and its protected tombstone remains discoverable afterward. A source/controller generation advance never changes the mutex key. Before any mutation, a pure lookup returns either no live slot or the exact bound prior-purpose receipt plus phase, operation, owner lease, owner fencing generation, and terminal observation. It can never settle work. A live or liveness-unknown owner yields `active_owned_elsewhere` and blocks. Settlement is legal only with an exact same-owner recovery capability or a durable dead/expired-owner-and-quiescence eligibility receipt; under the repository slot lock it revalidates that proof, advances the owner fencing generation, persists a replacement recovery fence, and only then may abort an untouched old-state begin or finish/reconcile/roll back already-advanced journal-bound work. The old owner cannot continue: every later manifest, normalization, proposal, verification, CAS, finish, reconciliation, release, terminal-observation, and acknowledgement mutation exact-matches the current owner fencing generation. Parent PID or lease expiry alone is insufficient without quiescence proof.

Transition purpose is a service-issued content-addressed `TransitionPurposeReceipt`, never a caller label. Purpose issuance itself is create-or-return, persisted before response, and independently recoverable read-only after response loss or parent death. It binds the protected reviewed-wave epoch, closed plan-DAG node, operation contract, requested fences, exact expected old source/controller state, and an external native no-follow batch snapshot plus canonicalization-policy digest. A mandated full restart after a frozen trust-leaf correction retires the old epoch only through a reviewed restart edge and creates a new epoch. The repeatable Task 5 correction node fingerprints the exact pre-normalization tracked/untracked batch; its `NormalizationReceipt` chains those immutable raw snapshot bytes and policy digest to the canonicalized change records, so normalization neither invalidates purpose identity nor erases its pre-fence identity. Intent acquisition, intent resolution, begin, begin resolution, every child mutation, settlement, terminal observation, acknowledgement, proposal verification, and CAS all exact-match the same purpose and current owner-fence receipts. Multiple matching purpose records or archives are an error. The protected purpose ledger survives slot acknowledgement: pure lookup returns `archived_achieved`, `archived_retryable`, `archived_rollback`, or `archived_failed` for that exact epoch/batch, while only an unattempted purpose returns `clear_never_started`.

Fresh-shell recovery always settles or refuses the repository-global slot and resolves the prior purpose result **before** inspecting current dirty paths, an untracked report, or a nonempty batch. The repeatable correction node has a separate service-issued `RepeatableInvocationReceipt`, persisted before response and bound to predecessor outcome, exact old state, native no-follow raw batch, reviewed universe, and canonicalization policy. Its pure result-state resolver distinguishes `achieved_clean`, `existing_invocation_only`, `existing_clear`, `existing_retryable`, `new_batch_after`, and `first_invocation`; ambiguity, an unmatched orphan invocation, or recovery-pending blocks. Same input re-resolves the same invocation and purpose after response loss, while a genuinely new post-achievement batch receives a new receipt. The nonrepeatable final-evidence node resolves exact current result state back to one purpose archive and returns `none` only when never issued; clear-never-started, achieved, retryable, rollback, failure, divergence, and ambiguity remain distinct. Local diff/report checks do not authorize anything: service-side invocation/purpose issuance recaptures and atomically revalidates the exact input, and begin rechecks the purpose-bound old state plus input under the repository slot lock before `started_old`. Concurrent drift is refused rather than incorporated or overwritten.

Terminal observation and purpose succession are separate closed decisions. The observer uses the operation recorded in the occupied slot, never the next requested operation; it emits a receipt only for the following exact live-state mappings. Anything else is `recovery_pending` and is not acknowledgeable.

| Recorded operation | `achieved` | `retryable_old` | `verified_rollback` | `safe_failed` |
|---|---|---|---|---|
| cutover | exact proposed source/index/tree active; inactive Singularity handoff verified; no legacy listener/controller; production and Discord disabled; developer source ingress open | exact old ref/index/tree/config and byte-identical legacy generation restored; no child/fence residue; old ingress explicitly open | monotone source rollback receipt; no legacy restart; every ingress held closed | exact pinned inactive/old generation plus failure receipt; every ingress held closed |
| source update | exact proposed source/index/tree and receipt active; developer ingress open; production inactive; Discord disabled | exact old source/index/tree restored; developer ingress open; production inactive; Discord disabled | exact prior source restored by monotone rollback; developer ingress held closed; production inactive; Discord disabled | exact old or committed generation named by failure receipt; developer ingress held closed; production inactive; Discord disabled |
| controller update | exact reviewed controller/anchor generation active; final activation receipt current; CLI/run ingress released; Discord disabled | exact prior controller generation active; CLI/run ingress restored to its proven prior state; Discord disabled | monotone verified LKG generation active; CLI/run ingress held closed; Discord disabled | exact named safe generation active with failure receipt; CLI/run ingress held closed; Discord disabled |

Acknowledgement atomically re-reads the latest journal, exact live generation, ingress, operation, wave epoch, purpose, and owner fencing generation under the slot lock; a stale observation remains `terminal_unacknowledged` or becomes `recovery_pending`. Cross-operation, cross-purpose, cross-epoch, and stale terminal-token replay are rejected. Only after the occupied purpose is acknowledged and archived does a separate resolver classify its relationship to the next desired purpose as `same`, `allowed_predecessor`, or `unrelated_or_new_epoch`. Same-purpose `archived_achieved` is `already_achieved`; same-purpose `archived_retryable` may retry; rollback/failure block. A different `archived_achieved` purpose may advance only across one explicit reviewed DAG edge (including an explicit wave-restart edge); every other relationship blocks. No predecessor outcome is ever mislabeled as the desired purpose's success.

Any transaction-level abort, finish, rollback, reconciliation, or ingress release that can change canonical/controller/ingress disposition has the symmetric rule: the mutating call's response is never treated as final truth. The client follows it with a read-only transaction-disposition lookup that re-reads the latest monotone journal sequence, persisted receipts, protected live fence bits, and exact ref/index/tree/controller generation; it rejects a stale receipt or any disagreement. The result reports separately whether the exact old/new generation is active and whether each ingress is open, held closed, or recovery-pending. Every source-update resolver also requires protected live proof that production-run ingress is inactive and the Discord listener is disabled; a developer-ingress label alone cannot authorize continuation. If that lookup fails, the result is `disposition_unknown`; diagnostics must say not to infer open **or** closed and must print the transaction ID. No error path may claim a fence merely because the request asked the service to keep one. Child-resource cleanup such as aborting an unsealed path-manifest cannot change ingress and remains covered by its enclosing transaction abort on uncertainty.

### `EnvHandle`

Extend `platform_core/execution/environment.py` with:

- `requires_canonical_landing: bool = False`
- `runtime_token: object | None = None`

`runtime_token` is process-local capability state. Exclude it from persistence and concise representation.

### `ExecutionContext`

Add a process-local composition contract rather than overloading one handle with two authorities:

- `landing_environment` and `landing_handle`: the mandatory per-attempt clone/snapshot-manifest bridge and sole owner of stage/verify/promote;
- `execution_environment` and `execution_handle`: trusted Local in the clone, or the hostile split-plane coordinator; the credentialed model driver never mounts or opens the clone and all hostile repository read/search/write/exec operations cross the credentialless broker;
- `runtime_resources`: an ordered collection of role-tagged `RuntimeResourceLease` records for credential lease, authority watchdog, model driver, broker, command sandbox, candidate/object parser, verifier, source fetch/parser, and state-store worker resources rather than one ambiguous inner handle;
- `verification_environment` and `verification_handle`: a fresh no-link checkout of the exact proposed SHA, always materialized and executed in a new credentialless/network-disabled hardened verification container; candidate origin is retained as evidence but never grants host acceptance-command execution;
- `work_dir`: the inner execution directory;
- `read_only`: true only when an explicit policy can enforce that no repository mutation is permitted.

Inner completion always happens before outer preparation. Every role-tagged Local process or Docker resource is quiesced in reverse dependency order before native candidate snapshot. Neither runner can promote or receives a linked canonical Git directory. Raw candidate patches, Git objects, packs, indexes, or repository metadata are never parsed by a host Git process. Verification never executes in the object-only staging surface, canonical, or host; it runs in a disposable clone inside the universal credentialless hardened verifier, with execution origin retained only as receipt evidence. A legacy requested-worktree preference maps to the safer clone candidate mode and records the effective backend truth. Remote is refused for mutating work until it can return a candidate artifact without touching canonical.

### Per-attempt scope

Backend policy is selected once per subtask, but `ExecutionContext` is created inside each retry iteration with a unique attempt/transaction ID. Rejection, failed verification, or execution failure checkpoints/quarantines and closes that context before retry. The next attempt starts from current canonical truth—unchanged after rejection—and receives prior diagnostics/receipts as context, never the rejected checkout as a filesystem base.

Every attempt also binds the current immutable run revision and snapshot. A successful promotion invalidates every still-live lease, candidate snapshot, parser output, staging receipt, review, and `LandingAuthority` based on the prior revision. Those resources are quiesced and quarantined; work is rescheduled only after the external run-revision advance above. Reusing an old-base candidate against a new expected parent, opportunistic host rebase, or manifest overlay across revisions is forbidden in this wave.

### `RuntimeResourceLease`

Add a frozen identity plus append-only journal state for every process/container boundary:

- resource ID, run/transaction/controller scope ID, role (`credential_lease`, `authority_watchdog`, `model_driver`, `broker`, `command_sandbox`, `candidate_parser`, `verifier`, `source_fetcher`, `source_parser`, `state_store_worker`), backend, ownership nonce;
- PID/process-group or container ID, image/entrypoint digest, mount/environment/security-profile digest;
- process/container state `planned -> registered -> created -> started -> quiesced -> collected`, or credential state `planned -> registered -> issued -> injected -> revoked_or_expired -> destroyed`, with timestamps and normalized error.

Credential-lease journal metadata is strictly non-secret: provider/auth mode, transaction, preallocated secret-channel identity/path, one-way fingerprint after issuance, TTL/expiry, issuer/revocation generation, and plan/register/issue/inject/revoke/destroy evidence. Before deriving credentials or materializing any channel bytes, the broker preallocates the lease/channel identity and durably registers its external owned cleanup target. Only then may materialization begin and transition to `issued`; a partial channel is discoverable and destroyable even if issuance crashes. The credential bytes, bearer token, profile, and recoverable derivative never enter the journal, receipt, argv, environment manifest, or log. Creation is gated: Docker and Local both use plan/register/create-stopped-or-suspended/persist-identity/start-release, while the broker uses plan/register/materialize/issue before injection. Recovery destroys registered-but-partial artifacts, immediately revokes an issued/injected lease, quiesces dependent drivers, destroys the secret-channel artifact, and only then marks it destroyed. It enumerates all resources, refuses unknown/unregistered live children, and quiesces in reverse dependency order. One “inner resource ID” is never treated as sufficient evidence for a split attempt.

Every process/container resource preallocates and durably registers a deterministic cleanup locator before OS creation: Docker name/labels plus transaction/role nonce, or a named no-breakaway Job Object/cgroup plus blocked-child handshake. Docker is created but not started, and a Local child is created suspended/blocked directly inside the registered boundary; actual container/PID identity is persisted before release. Recovery can therefore find and remove a partially created resource even if the creator dies during `create`. An unregistered live resource is never adopted.

Every repository-capable session also has a durably registered `authority_watchdog` before its driver starts. Its absolute deadline is the minimum of task, trust-grant, capability-receipt, and credential-lease expiry. It owns the OS process/job/cgroup boundary and a generation-bound admission gate shared by every resource start, broker operation, and provider pre-tool/process entrypoint. An action holds a read/start permit from the final authority check through durable resource identity registration and joining the watchdog-owned hierarchy; it cannot release a child/container outside that permit. Revocation/expiry takes the exclusive gate, marks admissions closed, freezes/terminates all registered Job Object/cgroup members and explicitly stops every registered Docker container ID, quiesces descendants, then commits the incremented revocation generation. If quiescence cannot be proven, the gate remains closed in `revocation_pending` containment failure. Thus a pre-check cannot race a post-revocation start, and no event timestamp after the durable revoked transition is accepted. No session may outlive the authority that admitted it; recovery treats an absent/dead watchdog around a live driver as a containment failure and kills the driver.

### `CapabilityEnforcementReceipt`

Add a frozen content-addressed readiness/eligibility receipt whose authority is narrower than its evidence:

- provider, actual CLI/driver/model version, and proven subscription auth/billing mode;
- exact `BackendLaunchPlan`, driver/sandbox image, entrypoint, immutable base, SBOM/package-manifest, broker-schema, environment, mount, network, seccomp, resource-limit, and security-profile digests;
- host Docker engine/runtime, kernel, architecture, isolation-mode, and required feature facts;
- authenticated no-op, broker operation, hostile-config, credential-absence, and cleanup evidence digests;
- issuer, issuance/expiry, monotone revocation generation, and normalized result.

The serialized receipt is evidence, not executable authority. The host enforcer issues a non-serializable process-local `CapabilityEnforcementGrant` only after every production launch fact exact-matches and it revalidates receipt provenance/content address, expiry, revocation generation, host/runtime facts, image digests, provider binary, auth mode, and launch-plan digest immediately before resource creation. A restart must revalidate and mint a new grant; a copied receipt cannot do so. Drift, missing facts, expiry, or a skipped/failed canary yields typed unavailability and requires a new real canary; a persisted `available` Boolean, provider self-report, mock, stale receipt, or receipt JSON alone is never authority.

### `PreparedFinalization`

Add a frozen dataclass that records preparation without claiming promotion:

- `backend`
- `work_dir`
- `accepted`
- `requires_revision_verification`
- `proposed_revision`
- `verification_dir`
- `verification_backend`
- `staged_ref`
- `candidate_snapshot_digest`
- `canonical_tree_manifest_digest`
- `staging_receipt_id`
- `error`
- `summary`
- `runtime_token`

Its `toDict()` output must be JSON-safe and must omit `runtime_token`.

### `ExecutionReceipt`

Add a frozen content-addressed record at runner quiescence:

- stable receipt, task, subtask, attempt, transaction, routing, and provider IDs;
- requested and evidence-backed actual driver/model/version/auth-billing mode;
- exact capability-enforcement receipt ID and resolved trust receipt/grant identity (without secret capability material);
- prompt/spec/schema/session/clone/base/head/candidate-snapshot/tree-manifest digests;
- every registered credential/watchdog/driver/broker/sandbox/candidate-parser/verifier/source-fetch/source-parser/state-store resource ID and normalized tool-event digest;
- timings, bounded usage/cost knowledge, result classification, and normalized error.

It records observation, not acceptance. Later staging or verification cannot rewrite it.

### `StagingReceipt`

Add a frozen immutable receipt, separate from the mutable recovery journal:

- stable receipt and transaction IDs;
- validated native source-snapshot and parser-output manifest/blob-set digests, including collision-resistant SHA-256 over every raw blob and canonical framed Git object byte sequence;
- pinned parser image/runtime/security-profile and memory-safe object-writer version digests;
- exact expected parent plus proposed commit/tree/diff Git OIDs and independent SHA-256 content digests;
- create-only staged ref and policy-manifest digest;
- deterministic commit-metadata digest, timestamp, and normalized error.

The receipt is content-addressed after creation. `PreparedFinalization` points to it; later journal transitions cannot rewrite it.

### `RevisionVerificationReceipt`

Add a frozen receipt that cannot be confused with an unbound Boolean:

- `passed`;
- `proposed_revision` and `verified_revision`;
- `scope="isolated_verification_clone"`;
- `runner_kind="credentialless_verifier"`, separate execution-origin tier, verification clone identity, container/resource identity, pinned image/SBOM digest, watchdog generation, and `VerificationCommandAuthority` receipt ID;
- command/evidence digest and stable evidence ID;
- tracked-tree integrity before and after verification;
- error and JSON-safe summary.

`passed=True` is invalid unless both revisions are the same non-empty SHA, the verification clone began at that SHA, the exact watchdog-bound universal verifier authority/container actually ran, execution origin is recorded separately, and tracked HEAD/index/worktree integrity still names that SHA afterward. Untracked test artifacts may be recorded and discarded inside the verification clone; they never become part of the sealed revision.

### `FinalizationReceipt`

Add a frozen dataclass that records terminal landing truth:

- `backend`
- `accepted`
- `requires_canonical_landing`
- `collected`
- `merged`
- `removed`
- `expected_revision`
- `observed_revision`
- `resulting_revision`
- `checkpoint_revision`
- `checkpoint_ref`
- `verification_revision`
- `promotion_transaction_id`
- `execution_receipt_id`
- `staging_receipt_id`
- `verification_receipt_id`
- `review_receipt_id`
- `selection_receipt_id`
- `promotion_receipt_id`
- `materialized`
- `journal_phase`
- `error`
- `cleanup_error`
- `summary`

For an accepted landing-required attempt, `succeeded` is true only when collection and promotion succeeded, canonical materialization is clean, the referenced durable journal is terminal-promoted, and `error` is empty. Accepted explicitly non-landing/read-only work succeeds when its own backend completion has no error. A cleanup warning after a successful landing must not falsify the landed commit; it belongs in `cleanup_error`.

### `PromotionReceipt`

Add a frozen immutable receipt whose bytes/digest are persisted and verified after exact materialization but before the journal transition. The receipt file alone is non-authoritative; it becomes promotion authority only when the atomic `promoted` journal transition references its ID:

- stable receipt/transaction IDs and linked staging/verification/review plus optional selection receipt IDs;
- expected, observed, proposed, resulting, canonical-index, and canonical-tree revisions;
- custom-lock and Git index-fence ownership digests;
- single-ref loose-lock CAS result, pre-CAS intent-ref/OID, materialization/postcondition result;
- canonical facts known at the durable `promoted` transition and normalized promotion error.

`MergeReceipt` may remain as a compatibility alias only. `FinalizationReceipt` links the immutable execution, staging, verification, review, and promotion nodes; `AttemptView` is a recomputable projection and never an authority.

### `ReviewReceipt`, `SelectionReceipt`, `ReconciliationReceipt`, and `CleanupReceipt`

Add append-only frozen chain nodes instead of mutating a prior receipt:

- `ReviewReceipt` records the immutable review target/evidence digest, reviewer identity/independence, findings, and gate decision. When policy legitimately skips semantic review, persist an explicit policy-skip ReviewReceipt with policy/version/risk inputs rather than omitting the node.
- `SelectionReceipt` binds batch ID, all candidate transaction and verification/review receipt IDs, eligible set, judge/evidence/policy digests, selected winner, and the intended `not_selected` disposition of every loser **before** winner promotion.
- `ReconciliationReceipt` links the original promotion/attempt receipt and records later ref/index/worktree observations, recovery action, subsequent canonical revision, and classification.
- `CleanupReceipt` links the attempt/finalization chain and records artifact/ref cleanup results and warnings.

`PromotionReceipt` contains only facts knowable at promotion and its hash never changes. `AttemptView` folds later reconciliation/cleanup nodes; tournament recovery consults the immutable selection receipt rather than guessing loser intent from canonical drift.

### `ReceiptStore` and `PromotionAuthorization`

All immutable chain nodes live in a host-owned `ReceiptStore` outside canonical, candidate clones, runtime projections, and provider mounts. It uses canonical JSON/schema versioning, content-addressed create-only filenames, no-follow path traversal, atomic durable write, directory fsync, hash verification on every read, and quarantine on collision/corruption. A receipt object or file is evidence only; the attempt journal determines which receipt IDs are authoritative for a transaction and phase.

`PromotionAuthorization` is a frozen typed reference bundle, never a Boolean. It binds transaction/task/subtask, prepared staging receipt and exact proposed revision/tree/diff/spec/policy digests, a passing `RevisionVerificationReceipt`, a passing semantic or explicit versioned policy-skip `ReviewReceipt`, and—when the journal declares tournament mode—the already-linked `SelectionReceipt`. The deepest clone-promotion boundary re-reads every node from `ReceiptStore`, verifies hashes/schema and complete same-transaction/target/policy linkage, verifies the review decision permits promotion, derives whether selection is required from the journal rather than caller input, and proves every tournament branch journal durably links the selection before acquiring merge/index/ref locks. Missing/null/forged/stale/cross-transaction receipts or direct legacy callers fail before canonical mutation. No overload accepting only `verification=True` remains on the promotion path.

A persisted `PromotionAuthorization` proves evidence linkage but never confers liveness. A separate non-serializable `LandingAuthority` is minted only from the still-live `RunAdmissionAuthority` for one transaction/task, prepared SHA/tree/receipt chain, watchdog, deadline, and controller generation. The promotion boundary validates it before any mutation and again under the held index/ref/materialization fences immediately before the loose-ref rename. Revocation, cancellation, admission expiry, watchdog loss, generation change, or task supersession before the durable ref move refuses and preserves canonical state. Once the journal and canonical ref prove that the authorized ref CAS already occurred, crash recovery may finish only the already-authorized consistency/materialization transaction without minting new landing power or selecting a new revision.

### Typed unavailability

Add `EnvironmentUnavailable`. Backend import, lookup, construction, health probing, and provisioning failures cross the router boundary only as this typed error. The error message preserves the backend name and causal detail.

### Environment lifecycle hooks

Extend `ExecutionEnvironment` with conservative defaults:

- `prepareChanges(handle, *, task_state, subtask) -> PreparedFinalization`
- `preparedChangesIntact(prepared) -> bool`
- `completeChanges(prepared, *, promote: bool, authorization: PromotionAuthorization | None=None, landing_authority: LandingAuthority | None=None) -> FinalizationReceipt`
- `checkpointRecovery(handle, *, task_state, subtask) -> dict`

Defaults fail closed. A backend may not claim staged landing support merely because it can execute commands.

---

## 3. Task 1 - Make environment selection and finalization typed and fail closed

**Files**

- Add: `bootstrap/galaxy_launcher/__main__.py`
- Add: `bootstrap/galaxy_launcher/singularity_anchor.ps1`
- Add: `bootstrap/galaxy_launcher/singularity_admin_client.ps1`
- Add: `bootstrap/galaxy_launcher/anchor.py`
- Add: `bootstrap/galaxy_launcher/capsule.py`
- Add: `bootstrap/galaxy_launcher/runtime_manifest.py`
- Add: `bootstrap/galaxy_launcher/manifest.json`
- Add: `bootstrap/galaxy_launcher/runtime.lock.json`
- Add: `bootstrap/galaxy_launcher/dev_tools.lock.json`
- Add: `bootstrap/galaxy_launcher/activation_verifier.py`
- Add: `bootstrap/galaxy_launcher/activation_reviewer.py`
- Add: `bootstrap/galaxy_launcher/activation_harness.py`
- Add: `bootstrap/galaxy_launcher/activation_acceptance.json`
- Add: `bootstrap/galaxy_launcher/activation_verifier.Dockerfile`
- Add: `bootstrap/galaxy_launcher/activation_reviewer.Dockerfile`
- Add: `bootstrap/galaxy_launcher/activation_images.lock.json`
- Add: `containers/galaxy/driver.Dockerfile`
- Add: `containers/galaxy/sandbox.Dockerfile`
- Add: `containers/galaxy/acquisition.Dockerfile`
- Add: `containers/galaxy/parser.Dockerfile`
- Add: `containers/galaxy/object_parser.Dockerfile`
- Add: `containers/galaxy/state_store.Dockerfile`
- Add: `bootstrap/galaxy_launcher/tofu_bootstrap.ps1`
- Add: `tools/build_galaxy_launcher.py`
- Add: `tools/lock_galaxy_runtime.py`
- Add: `tools/bootstrap_galaxy_dev_tools.py`
- Add: `tools/galaxy_plan_manifest.py`
- Modify: `tools/repo_map.py`
- Modify: `tools/repo_map_outputs.py`
- Modify: `requirements-dev.txt`
- Add: `bootstrap/galaxy_launcher/developer_redirect.ps1`
- Modify: `notifications/runtime/work_launcher.py`
- Modify: `platform_core/execution/environment.py`
- Modify: `platform_core/execution/router.py`
- Modify: `platform_core/execution/wiring.py`
- Modify: `platform_core/execution/__init__.py`
- Create: `platform_core/execution/launch_guard.py`
- Create: `platform_core/execution/trust.py`
- Create: `platform_core/runtime/execution_trust.py`
- Create: `platform_core/runtime/operator_launch.py`
- Modify: `platform_core/runtime/control_store.py`
- Modify: `platform_core/runtime/control.py`
- Modify: `platform_core/cli/main_cli.py`
- Modify: `main.py`
- Modify: `orchestrator.py`
- Modify: `agents/execution/executor.py`
- Modify: `agents/execution/executor_stream.py`
- Modify: `agents/execution/claude_sdk_bridge.py`
- Modify: `agents/review/verification.py`
- Modify: `agents/review/verifier_sanitize.py`
- Modify: `learning/evolution/evolver.py`
- Modify: `platform_core/ops/health.py`
- Create: `platform_core/execution/provider_probe.py`
- Modify: `platform_core/execution/backends/local.py`
- Modify: `platform_core/execution/backends/remote.py`
- Modify: `platform_core/execution/backends/docker.py`
- Modify: `platform_core/execution/backends/worktree.py`
- Test: `tests/execution/test_execution_environment.py`
- Test: `tests/execution/test_execution_router.py`
- Add: `tests/execution/test_execution_trust.py`
- Add: `tests/control/test_execution_trust_authority.py`
- Add: `tests/control/test_operator_launch.py`
- Test: `tests/control/test_control_store.py`
- Test: `tests/platform/test_main_cli.py`
- Test: `tests/execution/test_execution_local.py`
- Test: `tests/execution/test_execution_remote.py`
- Test: `tests/execution/test_execution_docker.py`
- Test: `tests/execution/test_execution_worktree.py`
- Add: `tests/execution/test_launch_guard.py`
- Test: `tests/execution/test_executor_stream.py`
- Test: `tests/execution/test_claude_sdk_bridge.py`
- Add: `tests/execution/test_provider_probe.py`
- Test: `tests/execution/test_verifier.py`
- Test: `tests/review/test_verification.py`
- Test: `tests/evolution/test_evolution_evolver.py`
- Test: `tests/platform/test_health_collect.py`
- Add: `tests/execution/test_external_launcher.py`
- Add: `tests/execution/test_controller_runtime_manifest.py`
- Add: `tests/execution/test_tofu_bootstrap.py`
- Add: `tests/execution/test_activation_harness.py`
- Add: `tests/execution/test_activation_images.py`
- Add: `tests/execution/test_cutover_normalization.py`
- Add: `tests/execution/test_anchor_host_isolation.py`
- Add: `tests/platform/test_galaxy_dev_tools.py`
- Add: `tests/platform/test_galaxy_plan_manifest.py`
- Add: `tests/platform/test_galaxy_repo_map_headers.py`
- Test: `tests/platform/test_repo_map.py`
- Test: `tests/execution/test_work_launcher.py`

### Step 0: Specify the explicit trust-on-first-install ceremony

The root of trust cannot be conjured by code already inside the untrusted target. Implement a small auditable OS-native `tofu_bootstrap.ps1` whose sole job is to copy a declared inactive capsule/interpreter manifest into a new external staging root, close ingress, supervise legacy-process drain, apply restrictive ACLs, persist the first protected expected digest/generation, and register the protected fresh-process Singularity service/task action plus request-only client. The registered action pins the OS-signed PowerShell path/signature/digest and exact `-NoLogo -NoProfile -NonInteractive` flags, empty external cwd, closed environment/module search, non-inherited stdio, and control-pipe ACL. It must not import Python from the target, evaluate target text, discover files, use the network, accept relative paths, reuse an ambient PowerShell runspace, or activate a normal controller. Deterministic tests compare its normalized source digest and fault-injected state machine; poisoned profile/function/alias/module/PATH/cwd/stdin canaries and an independent reviewer audit the exact bytes and launch record.

`runtime.lock.json` is a reviewed platform-specific content lock for the PowerShell host identity, Python executable/DLL/stdlib, every Python/native package/DLL, dynamic entrypoint, schema, prompt/template, and asset needed by the controller and activation verifier. `tools/lock_galaxy_runtime.py` may generate a developer proposal but has no install authority. During TOFU, the external copier obtains each declared byte from an explicit absolute operator-approved OS/package location through no-follow handles, verifies the lock digest, and seals it into a content-addressed offline runtime store. It never imports the package or uses the network. Missing/mismatched bytes block installation; there is no ambient site/venv fallback. Tests remove/poison ambient site-packages and prove the sealed runtime alone imports the inactive capsule and generic activation verifier from an empty cwd with `-I -S`.

The live development interpreter currently lacks `mypy`, so typecheck commands may not assume it. Before the first typecheck, `bootstrap/galaxy_launcher/dev_tools.lock.json` pins the exact zero-cost pure-wheel closure for mypy 2.3.0 and its transitive dependencies, including artifact URLs, filenames, sizes, SHA-256 hashes, Python/platform compatibility, and license metadata. `tools/bootstrap_galaxy_dev_tools.py` creates a dedicated external venv under the per-user GALAXY development cache, downloads only declared HTTPS wheels from the pinned hosts when absent, verifies every hash before install, uses `pip --only-binary=:all: --require-hashes` with no source build/plugin/config/index fallback, then re-runs offline and prints the exact interpreter path. An operator may instead preseed the same verified wheels. This is a one-time free development-tool bootstrap, not runtime/network authority. Network unavailability, lock drift, a missing wheel, or version mismatch is a hard pre-typecheck stop; no gate is skipped. `requirements-dev.txt` declares the exact mypy version, while the content lock is the installation authority. A live prerequisite canary proves the current missing-tool state is detected, the external toolchain exact-matches the lock, and `tools/dev.py typecheck` runs from that interpreter.

The inactive bundle contains generic, target-independent activation verification/review machinery, a closed executable acceptance manifest, and **all** production container bases: credentialed driver, credentialless command sandbox, networked source fetcher, networkless source/candidate/object parser, verifier, reviewer, and per-engine state-store worker. Before the Task 1 source proposal can receive exact-digest approval or TOFU installation, `activation_harness.py` and `activation_acceptance.json` encode the external black-box protocol, failpoint matrix, filesystem/process/network poison fixtures, receipt-schema checks, and every security/correctness invariant numbered in Tasks 1-4; future target code must expose the closed adapter protocol, but cannot change the assertions. Developer-authored target tests and later Dockerfile edits are diagnostics only. During TOFU, the OS-native copier imports explicit operator-approved offline OCI archives, verifies every manifest/config/layer/base/toolchain/package/SBOM/runtime/security-profile digest against `activation_images.lock.json`, and seals them in the external content-addressed runtime; it never builds or pulls an image from later target bytes. Generic images accept only an exact activation-manifest-bound controller entrypoint/runtime mounted read-only from the sealed external bundle. Real empty-cwd canaries prove every profile—including credential separation, network policy, parser bombs, verifier, reviewer, and cross-store state-worker isolation—runs from only those sealed assets before trust is installed. The inactive bundle can later materialize an exact source SHA only in that pinned credentialless verifier, run the closed harness, persist/re-read an exact-SHA/runtime/image-digest `RevisionVerificationReceipt`, and ask the separately contained local reviewer for a `ReviewReceipt` without exposing repository bytes to the anchor process. Task 2/3 reuse these images but cannot replace, extend, rebuild, or import their trust; no mutable target test, Dockerfile, `images.lock`, review claim, host build, Docker daemon result, or target execution can mint a capability or receipt.

This checkout's observed prerequisite state is deliberately not papered over: the Docker client is installed, but the daemon is not reachable and no reviewed OCI archives are present. Before TOFU, an out-of-band zero-cost artifact-provisioning gate must therefore do exactly one of two things: (a) accept operator-declared strict local absolute paths to already reviewed OCI archives, or (b) use an already-owned local engine/builder, with network and registry access disabled, to build the reviewed generic image sources entirely from hash-pinned locally cached inputs and export OCI archives. In either route, a pinned inspector independently validates archive structure, base/config/layer/toolchain/package/SBOM/security-profile closure, hashes every byte, and writes the proposed lock; the closed harness then imports and exercises only that closure. No target process, pull, unpinned cache entry, source distribution, paid API, hosted inference, registry login, or optimistic mock may fill a gap. If a compatible local engine/runtime or the complete verified archive set is absent, work may proceed through tests, source preparation, and independent review, but it **must stop before TOFU, Task 1 source commit, or cutover** with typed `OfflineActivationArtifactsUnavailable`. This prerequisite is an honest deployment block, not a reason to weaken containment.

Before Task 1 can commit, extract every exact reviewed bootstrap/anchor/client/capsule/closed-harness/acceptance/runtime-lock byte plus every offline OCI archive, image lock, manifest/config/layer/base/toolchain/package/SBOM/security-profile digest through no-follow handles into a new external staging root and verify them with OS-owned hashing. Eligible textual repository source leaves are transformed exactly once by the same versioned parent-BOM-preserving strict-UTF-8 CRLF-to-LF source policy used by the Task 1 proposal; their canonical bytes become installed bytes. Binary repository leaves remain exact. Raw target bytes, canonical bytes, policy digest, and mapping are bound so normalization cannot become substitution. The receipt has two closed submanifests: `source_leaves`, whose repo-relative canonical bytes must equal exact Task 1 proposal blobs, and `artifact_leaves`, whose OS/runtime/OCI archive/config/layer/SBOM bytes have no Git blob and must equal the exact hashes referenced by proposal-bound locks/manifests. Display one Merkle root over both subroots on a child-inaccessible operator surface and require the exact fresh response `TRUST SINGULARITY BOOTSTRAP <full-digest> NONCE <full-nonce>`. `TrustOnFirstInstallReceipt` binds both full submanifests and roots; substitution of any harness, lock, runtime, archive, layer, or policy byte changes the challenge. Only an outer OS-native copier holding that response may install the reviewed `singularity_anchor.ps1` as external `galaxy-admin.ps1`, service/client records, sealed runtimes/images, protected ACL/digest record, and first inactive generation. Before CAS, the source proposal must prove source-leaf blob equality **and** artifact-leaf closure equality to its lock/manifest references. The repository script cannot self-approve, copy itself after digest verification, or write the protected record. Generic advance approval—including the current unattended preapproval—does not satisfy this first-root ceremony. If the external verified admin is absent, implementation may prepare/review code but **must stop before the Task 1 commit and cutover**.

### Step 1: Add failing contract tests

Write tests proving:

1. Implicit or explicit Local execution is eligible only with a live operator-issued trust grant bound to the exact repository, canonical base SHA, task/spec digest, and trusted-Local capability; fabric-disabled selection without it is a typed refusal.
2. An explicit non-local backend fails closed when fabric is disabled.
3. Unknown backend, lazy import failure, registry lookup failure, constructor failure, false health check, and throwing health check all raise `EnvironmentUnavailable`.
4. Provision failure remains typed and never falls back to local.
5. Remote handles declare `requires_canonical_landing=True`.
6. Accepted legacy `finalize()` on a landing-required handle returns a staged-preparation-required failure and does not tear down or discard the artifact.
7. Rejection of a landing-required backend with no checkpoint support preserves its artifact and reports recovery unavailable.
8. Dataclass dictionaries are JSON-safe and omit runtime capability objects.
9. Accepted finalization success cannot be inferred from `removed=True`; it requires collection and merge truth.
10. An `ExecutionContext` distinguishes the inner command runner from the sole outer landing authority.
11. Model-authored `execution_backend`, `risk_tier`, task text, or repository files can tighten the resolved tier but cannot mint, widen, replay, or substitute a Local trust grant.
12. Wrong-repository, wrong-base, wrong-task/spec, expired, revoked, unknown-issuer, copied-JSON, post-issuance-mutated grants, forged/replaced/rolled-back control-store rows, restart without fresh launcher authorization, a bare/synthesized `--authorize-trusted-local` argv, and a launcher nested inside a registered model job/cgroup all resolve to unknown and cause zero launch/provision side effects.
13. The pre-spec model worker has pipe-only I/O, no controlling-terminal/console handle, input access, Local grant, or execution-child capability. After its bounded result arrives, every driver/broker/container/process/descendant and credential channel is proven quiescent and revoked before approval can begin. Only a newly spawned post-approval execution child may receive one-time launch/spec capabilities through anonymous non-inheritable OS handles; they are absent from argv, environment, files, task state, receipts, logs, and further child inheritance, consumed once, and non-replayable.
14. Raw launch-intent approval never authorizes a model-produced spec. After full elaborator quiescence, the outer launcher independently length-bounds and schema-validates strict UTF-8 input, rejects duplicate keys, ANSI escape/bidi/noncharacter and non-NFC hazards, reserializes canonical bytes, recomputes the digest, opens an exclusive operator channel inaccessible to every child, discards input predating a freshly generated outer nonce, renders every remaining C0/C1 character in a deterministic escaped control-neutral view, and requires the exact fixed-format digest-and-nonce challenge response. Concurrent stdout, console reopen/descendants, prequeued or synthesized input, stale nonce, child-supplied digests, terminal/bidi spoofing, oversized/invalid/ambiguous serialization, generic yes/EOF, `--auto-approve`, model-only acceptance, task state, copied approval evidence, and resume without fresh approval all produce zero execution-child/Local launch effects.
15. From the Task 1 commit through Task 2, the temporary pre-activation guard is the first executable operation of the main fresh/resume execution path—after argument parsing of operational subcommands but before startup knowledge refresh, work-directory resolution/grounding, TaskState creation/load, elaboration, approval, or orchestration—and is independently the first statement of `Orchestrator.runFull` before `ControlBus`, dashboard, heartbeat, self-referential setup, discovery, repository context, or backend selection. It also guards every direct repository-capable provider launch. It refuses the **entire autonomous run** plus all model inference with typed `TransactionalKernelInactive`, regardless of a valid Local grant, backend request, or caller-authored `read_only`, verifier, architect, clarification, health, or analysis label. Repository/config/task/env inputs cannot activate it. Direct true non-agent CLI version/auth-status probes remain separate and may bypass only their dedicated neutral diagnostic boundary.
16. A repository-wide provider-spawn inventory has no inference subprocess outside the guarded executor stream. The sole non-inference subprocess implementation is a shared neutral diagnostic helper used by health and the Claude SDK bridge: it permits only pinned `--version`/auth-status argv, runs from an empty temporary directory with a closed allowlisted environment and project discovery disabled, and never sends a prompt. Evolution escalation hits the embargo before invoking an injected spawn callback. During Task 1/2 the production brain-authored acceptance runner rejects **every** command before `Popen`, so `cmd`, PowerShell, batch files, Python, aliases, or nested interpreters cannot transitively launch a provider; lexical Claude/Codex rejection remains defense-in-depth only. The low-level `_launchClaude()` seam independently checks the embargo before `Popen`.
17. Official fresh/resume/Discord launch enters only through the OS-installed Singularity Anchor, whose protected record pins the expected external capsule/controller digest and monotone generation before isolated Python starts. Poisoned target `run.ps1`, `main.py`, package `__init__`, `sitecustomize.py`, `usercustomize.py`, `PYTHONPATH`, cwd, symlink/reparse paths, and simultaneous replacement of capsule, sidecar manifest, and writable generation cannot execute within or authorize the trusted path. Direct target-checkout invocation has no boot capability and cannot start a production run. During Task 1/2 the anchor points to an intentionally inactive generation that refuses before target import; no already-running pre-anchor bot/process may satisfy activation readiness. The canary distinguishes this target-repository guarantee from excluded same-user malware/operator bypass.
18. Initial cutover begins before the Task 1 commit with an external bootstrap supervisor: it closes Discord/CLI ingress, holds a create-only maintenance generation fence, enumerates and quiesces every recognized legacy controller/bot/launcher plus descendants, revokes their provider/tunnel/listener resources, proves no legacy listener/process remains, and continuously denies cooperative restart while the commit and inactive-anchor install occur. The anchor atomically assumes the fence before ingress can reopen. Failpoints and restart attempts on both sides of commit/install prove no legacy generation executes. If fresh exact-digest operator approval is unavailable before commit, the proposal remains uninstalled and the byte-identical old generation may be restored; after commit, ingress remains closed until verified inactive install or verified repository rollback. Generic advance approval never satisfies the digest ceremony.
19. The real current checkout can pass a one-time external normalization without trusting ambient Git configuration: its packed-only `refs/heads/main` is resolved no-follow, a same-OID loose ref is create-only installed under the cutover fence, and equality is re-read before attestation. A bounded Git-compatible config parser (not strict `configparser`) preserves inert duplicate branch metadata, removes an unused `extensions.worktreeConfig`, replaces the current absolute `core.hooksPath` only after proving there is no active hook, pins local `core.autocrlf=false`, `core.safecrlf=true`, and disables automatic maintenance/ref packing. The source proposal independently snapshots every allowlisted implementation path. Eligible UTF-8 text inputs—allowlisted or not—are canonicalized only by the pinned one-way CRLF-to-LF transform; NUL, lone CR, BOM ambiguity, malformed encoding, or any other conversion is rejected, and the displayed proposal digest binds the converted bytes. Every non-allowlisted tracked path must then be byte-exact to its parent blob after that transform; binary files are exact-only. After fresh exact proposal-digest approval and loose-ref CAS, the native safe materializer writes the **entire** proposed tree and deterministic index to exact blob bytes under the held fence, making index/worktree byte-clean despite system `core.autocrlf=true`. Later developer commits run the same external exact-change normalization plus same-OID loose-ref repair before staging, and final activation runs a full exact-index-byte normalization; manual ref packing or CRLF recreation therefore cannot silently strand activation. Any substantive non-allowlist change, active hook, untracked collision, ref drift, failed materialization, or post-write mismatch aborts/rolls back or keeps ingress fenced; no developer change is silently erased.
20. The live canonical DIRC v2 index's standard `TREE` cache-tree extension is strictly bounded and structurally validated but never authoritative. Initial fenced normalization deterministically rewrites ordinary entries from the attested tree and omits `TREE`; later attestation may validate then ignore/recompute a Git-created `TREE`. Malformed cache-tree bytes, unknown required extensions, split/sparse state, or entry drift fail closed. Live-index and corrupt-`TREE` fixtures prove the current checkout is admissible without trusting the extension.
21. Every bootstrap/update command is executed by the pinned Windows PowerShell 5.1 host and uses only .NET Framework APIs available there. The strict local-path helper accepts canonical drive-absolute paths such as `C:\9to5`, normalizes with `GetFullPath`, and rejects relative, drive-relative (`C:foo`), current-drive-rooted (`\foo`), UNC, and device namespace (`\\?\`, `\\.\`) forms; it never calls unavailable `Path.IsPathFullyQualified`. A real pinned-host parser/execution canary covers both cutover and final-activation snippets before TOFU.
22. The typecheck prerequisite is executable on this checkout: missing ambient `mypy` is detected, the external dev-tool bootstrap accepts only the reviewed hash-locked pure-wheel closure, an offline replay exact-matches mypy 2.3.0 plus dependencies, and every typecheck uses the printed external interpreter. A poisoned pip config/index/proxy, sdist, wrong wheel/hash/version, target path, or unavailable bootstrap refuses before a typecheck; it never converts missing tooling into a pass.
23. “BOM ambiguity” does not reject the five existing tracked UTF-8-BOM files. Exactly one leading `EF BB BF` is preserved only when the parent blob has that exact prefix and the remaining bytes are strict UTF-8; CRLF-to-LF applies to the payload, and every non-allowlisted result must rehash exactly to its parent. Adding, removing, doubling, relocating, or using a UTF-16/32 BOM is rejected. Live fixtures include `docs/simulated/README.md` and all four tracked BOM-bearing review/work-profile tests, so Task 1 cannot strand the checkout.
24. Bootstrap ref normalization is idempotent across the required documentation commit. Starting from the observed packed-only `main`, the ordinary docs commit may create an authoritative loose `refs/heads/main`; the external normalizer then either create-only installs the loose ref when absent or safely re-reads and accepts the existing ordinary no-follow loose ref only when symbolic HEAD, loose OID, and current docs commit agree. A matching stale packed shadow is tolerated; any mismatch, nonordinary path, or race refuses. The real `packed-only -> docs commit -> normalization` sequence is a mandatory canary.
25. The strict path helper accepts the live `git rev-parse --show-toplevel` form `C:/9to5` as drive-absolute input, canonicalizes it with PowerShell 5.1/.NET `GetFullPath`, and revalidates the normalized `C:\9to5` form. It still rejects drive-relative, UNC, `//?/`, `//./`, and backslash device forms. The exact live Git output is part of the pinned-host canary.
26. The ignored machine-local `run.ps1` is not adopted, overwritten, normalized, or added. Its pre/post bytes and metadata remain identical, while the separately tracked portable `developer_redirect.ps1` contains no hard-coded repository/log/profile path and can only reach the installed request-only client or refuse. No official service resolves either script from target cwd.
27. TOFU and the Task 1 source proposal share one canonical-byte policy. The receipt's repository `source_leaves` map textual raw bytes to exactly one parent-BOM-preserving strict-UTF-8 CRLF-to-LF blob and keep binary source exact; pre-CAS equality proves each installed anchor/client/capsule/harness/lock/image-input source leaf equals its proposal blob. Separate non-source `artifact_leaves` prove OS/runtime/OCI archive/config/layer/SBOM bytes equal the proposal-bound lock/manifest hashes rather than pretending those artifacts have Git blobs. Frozen source leaves already contain stable navigation headers, so later map regeneration changes none. Any source equality, artifact-root, newline/BOM/policy/header, or later frozen-leaf drift fails before source CAS/final activation and requires aborting/restarting the wave with a fresh reviewed Task 1 plus TOFU.
28. `tools/repo_map.py --headers-only --only <prefix>` and the narrow `repo_map_outputs` implementation deterministically splice/check headers without writing `.repo-map.json`, `.llm-map.json`, ignored AGENTS indexes, or any out-of-prefix source. Task 1 runs it for `bootstrap/galaxy_launcher` before TOFU and re-runs in `--check` mode; a later full Task 5 regeneration changes zero protected TOFU leaf. Dedicated failing header-mode tests cover no-index writes, prefix isolation, idempotence, and the real Task 1 trust-leaf set.
29. The repository-global transition protocol has deterministic failpoints before/after purpose persistence, intent persistence, begin persistence, old-to-new state advance, CAS, finish/reconciliation/release, terminal observation, atomic acknowledgement, and purpose-ledger archival. Each failpoint is tested with client-response loss and complete parent death. Recovery begins with a pure all-generation/all-operation slot lookup, not a volatile request ID or desired-purpose guess. Concurrency canaries race cutover/source/controller across old and new source/controller generations; a live or liveness-unknown owner is never settled, while a durably dead/expired-and-quiesced owner is taken over only after an atomic owner-fencing-generation bump. The expired old process is then resumed adversarially at manifest, normalization, proposal, verification, CAS, finish, reconciliation, release, observation, and acknowledgement calls, and every stale-owner mutation is rejected. Purpose issuance is create-or-return and independently resolvable after response loss; every intent/begin/proposal/CAS path rejects a different purpose. Canaries cover prior-purpose-to-next-purpose handoff, same-purpose retry, unrelated/cross-epoch refusal, explicit reviewed wave restart, cross-operation/cross-purpose/cross-epoch terminal-token replay, multiple-archive ambiguity, observation becoming stale before atomic acknowledgement, acknowledgement-response loss, parent death after acknowledgement, and end-of-operation slot release. Repeated Task 5 corrections with different immutable pre-normalization batches receive different purposes, while the same batch resolves the same purpose and its normalization receipt chains raw snapshot plus policy to canonical records. Every source disposition also proves production inactive and Discord disabled. No canary may fabricate ingress/fence truth, hijack a live owner, alias a batch, erase an archived result, or leave an undiscoverable transaction.
30. The exact Windows PowerShell 5.1 request-only client boundary transports path-manifest JSON only as strict-UTF-8 canonical unpadded base64url. A real native-process canary uses embedded quotes, repeated backslashes, combining/non-ASCII path characters, and values near both byte caps; the service rejects padding/noncanonical alphabet, malformed UTF-8, alternate encodings, decode/re-encode inequality, decoded payloads above 4 KiB, and encoded envelopes above 8 KiB. The accepted round trip reserializes to the exact original canonical bytes.
31. Every fresh-shell Task 5 entry settles or refuses the existing all-generation slot and resolves exact purpose/result state before any dirty-diff or report-presence gate. Failpoint canaries cover response loss after invocation persistence but before purpose issuance, after purpose persistence but before intent, and after intent but before begin. They prove that correction recovery after clean CAS/ack returns the unique achieved purpose without needing the vanished input batch; invocation-only, clear and retryable exact inputs return the same invocation/purpose chain; a new dirty batch after achievement creates a distinct invocation and purpose; orphaned or ambiguous result/archive matches block; and final-evidence recovery after its report becomes tracked returns before the sole-untracked-report check. An adversarial edit between invocation, purpose, intent, and begin is rejected by the under-slot-lock old-state/input revalidation and is never swept into or overwritten by the source proposal. All six settlement helpers cancel an untouched reservation only with authoritative no-begin proof, while any persisted begin makes that cancellation path fail closed.

Run:

```powershell
$redTests = @(
  'tests/execution/test_execution_trust.py', 'tests/control/test_execution_trust_authority.py',
  'tests/control/test_operator_launch.py', 'tests/execution/test_launch_guard.py',
  'tests/execution/test_provider_probe.py', 'tests/execution/test_external_launcher.py',
  'tests/execution/test_controller_runtime_manifest.py', 'tests/execution/test_tofu_bootstrap.py',
  'tests/execution/test_activation_harness.py', 'tests/execution/test_activation_images.py',
  'tests/execution/test_cutover_normalization.py', 'tests/execution/test_anchor_host_isolation.py',
  'tests/platform/test_galaxy_dev_tools.py', 'tests/platform/test_galaxy_plan_manifest.py',
  'tests/platform/test_galaxy_repo_map_headers.py'
)
$unexpectedGreen = @()
foreach ($test in $redTests) {
  if (-not (Test-Path -LiteralPath $test -PathType Leaf) -or (Get-Item -LiteralPath $test).Length -eq 0) { throw "Task 1 RED test was not written: $test" }
  python -m pytest $test --collect-only -q
  if ($LASTEXITCODE -ne 0) { throw "Task 1 RED test does not collect cleanly: $test" }
  python -m pytest $test -q
  if ($LASTEXITCODE -eq 0) { $unexpectedGreen += $test }
}
if ($unexpectedGreen.Count) { throw "Task 1 RED modules unexpectedly passed: $($unexpectedGreen -join ', ')" }
```

Expected: the new tests fail for missing contracts and fail-closed behavior.

### Step 2: Implement the dataclasses, trust authority, and typed error

Build `bootstrap/galaxy_launcher` as a standard-library-only zipapp plus OS-installed anchor. `tools/build_galaxy_launcher.py` is only an untrusted proposal/redirect client: it can canonicalize declared source for developer inspection but cannot touch installed staging, anchor records, generations, or activation without an anonymous one-use capability from the installed updater. The initial external bootstrap ceremony separately verifies the exact capsule plus pinned interpreter/stdlib digest, refuses symlink/reparse/hardlink inputs and dirty/unreviewed scope, writes the inactive bundle/manifest atomically under the per-user external kernel root, fsyncs, reopens and verifies every byte, and creates the first OS-protected expected digest/generation only after fresh exact-digest operator approval. Later, the previously trusted installed LKG updater treats the target commit only as inert bytes and constructs a reproducible offline controller runtime containing its own pinned interpreter, stdlib, full Python/native wheel/DLL dependency closure, dynamic entrypoints, schemas, prompts/templates, and assets; it runs no target code and uses no network. Every byte is in the activation manifest. Empty-cwd/closed-env import plus fresh/resume/recovery/config/broker smoke occurs before activation. Later updates require the previous external anchor's live `ControllerActivationAuthority`, exact old-generation compare-and-swap, and rollback pointer. The installed `galaxy` entrypoint and any future external Discord gateway invoke the verified runtime with isolated Python (`-I -S`), a closed environment, an empty external cwd, and anonymous non-inheritable handles. The new tracked `developer_redirect.ps1` can only invoke the installed request-only client or refuse with installation guidance; it never launches repository `main.py` with production authority. The existing ignored, machine-specific `run.ps1` is deliberately untouched user state, is never read or staged by GALAXY, and is outside every official production entrypoint.

Task 1 installs an **inactive** capsule generation whose only production run outcome is typed `TransactionalKernelInactive`. The activation record binds the last-known-good controller bundle digest, but Tasks 1/2 do not yet mint `RunAdmissionAuthority`. `main.py` and `operator_launch` require a live one-time boot capability for any non-simulation fresh/resume path, while health/doctor/version/build/test subcommands remain explicitly separate. A direct checkout invocation can therefore exercise developer diagnostics but cannot start autonomous mutation. Before any Task 1 commit, an external bootstrap supervisor closes ingress, obtains an OS-protected create-only maintenance generation lease, enumerates and quiesces every recognized legacy launcher/bot/controller and descendant, revokes listeners/tunnels/provider children, proves none remains, and watches for cooperative restart. It holds that fence across the commit and initial inactive install; after fresh exact-digest operator approval, the anchor atomically takes fence ownership before any ingress can reopen. A pre-capsule process is never grandfathered. A failure **before** the commit may restore the byte-identical old generation; after the commit succeeds, legacy code must never restart. Install/handoff failure keeps ingress fenced closed until inactive installation succeeds or a separately verified repository rollback completes while all legacy processes remain quiesced. Only a persisted/re-read inactive-readiness receipt may finish the cutover and reopen developer-only source-update ingress; production run admission and Discord listener ingress remain closed.

Keep compatibility imports through `platform_core/execution/__init__.py` if callers already import from the package facade. Do not place Git-specific logic in the abstract environment contract.

Add frozen `WorkloadTrustReceipt`, `WorkloadTrustGrant`, and `ResolvedWorkloadTrust` contracts. Only the top-level host launcher may issue a process-capability grant from explicit operator authorization received before any model call. Bind its content-addressed receipt to issuer ID, canonical repository-attestation digest, expected base SHA, canonical task ID and acceptance-spec digest, allowed capability profile, issuance/expiry, nonce, and monotone revocation generation. The serialized receipt and every durable control-store row are evidence, not executable authority: selection additionally requires the unforgeable process-local grant registered with the live issuer. A restart/resume is a new OS process and must receive a fresh top-level operator authorization; task JSON, environment, a copied receipt, or a forged/replaced/rolled-back SQLite row can never reissue a grant.

Resolve trust as a restrictive filament. Operator authority can make the exact bound scope eligible for trusted Local; deterministic probes, repository policy, and model-authored fields may only move it toward unknown/hostile or request a stronger backend. They can never move unknown/hostile toward trusted. Default is unknown.

`--authorize-trusted-local` is only a request, never authority by itself. The production issuer is `platform_core.runtime.operator_launch`: an outer host launcher invoked before any model call. It proves its process is outside every active/recovering registered model-driver Job Object/cgroup/process tree and retains exclusive ownership of operator interaction. It never gives a model-bearing child the operator's controlling terminal, console input buffer, stdin/stdout/stderr handles, or a Local/execution launch capability.

Raw launch intent is insufficient to authorize a model-produced acceptance spec. For a new goal, the outer launcher first starts a separate contained pre-spec analysis worker with pipe-only bounded I/O and `PreSpecAnalysisAuthority`; the worker has no console/TTY/ConPTY, operator input, or execution-child handle. The launcher receives a length-prefixed candidate serialization but trusts neither those bytes nor any child-supplied digest. It then revokes/destroys the credential channel and proves the entire pre-spec driver/broker/container/Job Object/cgroup process tree and every descendant quiescent. Failure to prove quiescence refuses approval and preserves recovery evidence. Only after that barrier does the outer process enforce a strict maximum byte/field/depth budget, decode strict UTF-8, reject duplicate object keys, ANSI escape sequences, bidi override/isolate/mark characters, Unicode noncharacters, and strings not already in NFC, validate the versioned acceptance-spec schema, deterministically reserialize the sole canonical byte form, and independently compute its digest.

After quiescence, the launcher opens a fresh OS-exclusive operator surface that was never inherited by a child—a private non-inherited ConPTY/app channel on Windows or an exclusive PTY (`TIOCEXCL`) on POSIX, with fail-closed equivalent handling on other platforms. It drains/discards all input queued before this phase, generates a cryptographically random approval nonce, and only then renders a fixed outer-owned frame containing an escaped ASCII-safe line-numbered representation plus the recomputed full digest and nonce. Every remaining C0/C1 character, including tabs and newlines inside values, is visibly escaped; untrusted content cannot emit prompt chrome. Approval requires the exact `APPROVE SPEC <full-digest> NONCE <full-nonce>` response on that exclusive channel. Generic yes, EOF, input predating the nonce, concurrent writers, console reopen attempts, truncated/mismatched digest, stale nonce, child framing, and automation flags refuse. Inability to prove exclusive input/output ownership refuses trusted Local.

Only after approval does the launcher create a **new** `main.py` execution child with no controlling terminal and closed pipe/`DEVNULL` stdio. It creates fresh one-time `OperatorLaunchCapability` and `OperatorSpecApprovalCapability` values bound to that new PID, repository attestation/base, raw intent/task ID, canonical byte length/schema, recomputed digest, approval nonce, and issuer generation, and passes them through anonymous non-inheritable OS handles. The child consumes both once before any model call, exact-matches the persisted canonical spec, and only then may derive the narrower task/spec-bound `WorkloadTrustReceipt`. On resume there is no pre-spec worker: the outer launcher loads the persisted canonical bytes, repeats validation/rendering with a fresh nonce on the exclusive channel, and spawns a fresh terminal-less execution child after approval. No unattended restart regains Local authority. Registered execution children/drivers run inside no-breakaway Job Objects/cgroups; nested launchers are refused. `main.py` appends only non-authoritative audit/revocation evidence and injects `OperatorTrustAuthority` after both live capabilities validate. No task field, environment variable, copied flag, repository config, prompt, web request, control-store row, or model output can mint either capability.

The elaboration needed to propose that spec cannot bootstrap the authority it is asking to receive. `PreSpecAnalysisAuthority` binds raw operator intent, repository attestation, base, an immutable read-only source snapshot, and a no-write/no-shell/no-Task/no-MCP broker policy; it has no canonical/clone write mount, promotion surface, operator terminal, or execution-child capability. Its output is an untrusted proposal. If that enforced tier or its full quiescence proof is unavailable, the system stops for an operator-supplied spec or a later contained run—it never uses trusted Local as an elaboration fallback. Task 1/2's total inference embargo means this handoff becomes executable only in the atomic Task 3 + Task 4 activation.

Every **execution child** start—including `--resume` after a crash—requires fresh post-approval outer-launch/spec capabilities and operator request; the separate pre-spec worker has only contained analysis authority. Without the execution capabilities, Local is unavailable and recovery may continue only through an eligible contained tier. While the execution process lives, the authority verifies that each current base is the authorized initial SHA or is connected by an unbroken chain of successful promotion receipts for the same run, then issues a fresh exact-base attempt grant. An unrelated canonical move, missing receipt link, expiry, revocation, database substitution/symlink, issuer-generation rollback, replayed handle, stale approval nonce, or nested-model ancestry fails closed and requires a new outer authorization.

### Step 3: Harden router selection

In `select()` or its equivalent, wrap all of these in one causal translation boundary:

- lazy module import;
- backend registry lookup;
- backend construction;
- `healthCheck()` invocation.

Rules:

- no explicit backend + fabric disabled + valid scope-bound trusted-Local grant -> local;
- explicit local + valid scope-bound trusted-Local grant -> local;
- any Local request without a valid grant -> typed refusal (or the hostile plane when policy explicitly selects it), never implicit trust;
- explicit Docker, remote, or worktree + fabric disabled -> typed refusal;
- unavailable requested backend -> typed refusal;
- never substitute a weaker backend silently.

### Step 4: Split preparation from completion

Add router functions with typed return values:

- `prepare(env, handle, task_state, subtask, *, accepted)`
- `complete(env, handle, prepared, *, authorization: PromotionAuthorization | None=None, landing_authority: LandingAuthority | None=None)`

For a landing-required accepted handle, `prepare()` calls the backend staged hook. It captures failures in a `PreparedFinalization` without mutating canonical state. `complete()` can request promotion only with both a non-null typed `PromotionAuthorization` evidence bundle and non-serializable live `LandingAuthority`; it forwards both to `completeChanges()` for deepest-boundary ReceiptStore/journal and liveness revalidation. Task 1's conservative backend defaults reject promotion because the store/kernel is not implemented until Task 2. A bare passing verification receipt, caller Boolean, persisted/copyable authorization, missing live landing authority, or missing review/selection link can never create a durable promotion record.

For local, rejected, or non-landing handles, preserve current teardown behavior behind typed receipts. Before teardown of a rejected landing-required handle, request a recovery checkpoint. If the backend cannot checkpoint, preserve the artifact.

Keep legacy `finalize()` as a compatibility boundary, but make accepted landing-required finalization fail closed with “staged prepare required.” This prevents unmigrated callers from merging before verification.

### Step 5: Install the fail-closed intermediate activation gate

Task 1 and Task 2 are separately committed on `main`, but neither has the composed outer clone authority required for safe execution. Create a temporary guard in `platform_core/execution/launch_guard.py` whose production activation state is structurally unavailable until the atomic Task 3 + Task 4 wave. `main.py` invokes it on fresh/resume execution immediately after operational-subcommand parsing and before startup knowledge refresh, work-directory resolution, TaskState creation/load, elaboration, or approval. `Orchestrator.runFull()` repeats it as its literal first executable statement before `ControlBus`, dashboard, heartbeat, self-referential detection/preparation, discovery, context collection, or any other run side effect. `provisionForSubtask()` calls it before selection/provision, `runClaude()` calls it before normalization, filesystem access, logging, session lookup, or subprocess construction, and the low-level `_launchClaude()` seam checks it again immediately before `Popen`. During this intermediate state every autonomous run and every repository-capable Local, Docker, Worktree, Remote, Claude, or Codex inference launch raises typed `TransactionalKernelInactive`, including calls labeled read-only, verifier, architect, clarification, health, or analysis; a valid Local trust grant changes selection eligibility in isolated contract tests but cannot pass the production launch boundary. No environment variable, config flag, task field, receipt JSON, control-store row, caller label, or model-authored input can enable the guard.

Create `platform_core.execution.provider_probe` as the only non-agent provider subprocess implementation. It accepts a closed enum of version/auth-status probes, resolves the executable outside repository influence, launches from a newly created empty temporary directory with a closed allowlisted environment and user/project discovery disabled, has no stdin/prompt or repository path, and returns typed bounded diagnostics. Move both `platform_core.ops.health._claudeCli` and `agents.execution.claude_sdk_bridge._claudeVersion` to it immediately; neither retains its own `subprocess` call. Evolution's optional injected Claude spawn calls the embargo before constructing/dispatching work. At the production acceptance boundary, `_runVector` calls the same embargo as its first executable statement and refuses every brain-authored command during Task 1/2 before path creation or `Popen`; it does not attempt to prove safety from `argv[0]`. Provider-shaped argv rejection in `verifier_sanitize` remains a later defense-in-depth rule, not an authority boundary. Add wrapper/interpreter/batch-file tests and a repository-wide static inventory assertion over provider command construction and subprocess calls; only the shared non-agent diagnostic implementation and guarded executor seam are allowlisted, and any new direct inference site fails the test.

`tests/execution/test_launch_guard.py` plus the main/orchestrator/provider-probe/SDK-bridge/health/evolution/verifier/executor-stream tests prove every discovered choke point is zero-side-effect and remains closed with a valid Local grant, explicit Docker/worktree request, every read-only/verifier/architect/clarification/analysis label, forged activation inputs, direct `runFull()`/`runClaude()`/`_launchClaude()` invocation, injected evolution spawn, and provider-shaped verification argv. The `runFull` canary poisons knowledge freshness, self-referential branch setup, repository scripts, dashboard/control constructors, and filesystem goldstones and proves none is observed before refusal. `tests/review/test_verification.py` additionally proves plain acceptance commands plus `cmd /c`, PowerShell `-Command`, batch/sh wrappers, Python launchers, aliases, and renamed executables all stop before directory creation or `Popen`. Neutral probes inherit no repository cwd/environment/config and cannot accept inference argv. Task 2 reruns this embargo suite unchanged. The only code allowed to replace the embargo is Task 4's atomic activation commit, where permanent first-statement run and execution authorities become live after all pre-execution, ordinary, Society, parallel, tournament, validation, and publication callers are migrated.

### Step 6: Verify the selection boundary

Re-run the tests with valid and poisoned Local grants, explicit/implicit Local, worktree, Docker, remote, unknown, unhealthy, and constructor/provision-failure cases. Confirm that Local selection succeeds in isolation only for the exact two-phase operator-authorized scope, model fields are tighten-only, and every absent/mismatched grant or unavailable stronger request produces typed refusal with zero provisioning. Then prove the production pre-activation guard still refuses all mutating launches before selection/provision. Task 1 lands contracts, router truth, and a zero-launch embargo; Task 2 supplies staged leases while preserving that embargo; Task 3 + Task 4 atomically replace it with the composed outer-lease authority. No intermediate commit may advertise or execute transactional mutation as complete.

### Step 7: Verify and commit

Run:

```powershell
python tools/repo_map.py --headers-only --only bootstrap/galaxy_launcher
if ($LASTEXITCODE -ne 0) { throw 'Task 1 protected trust-leaf header stabilization failed' }
python tools/repo_map.py --headers-only --only bootstrap/galaxy_launcher --check
if ($LASTEXITCODE -ne 0) { throw 'Task 1 protected trust-leaf headers are not idempotently stable' }
python -m pytest tests/execution/test_execution_environment.py tests/execution/test_execution_router.py tests/execution/test_execution_trust.py tests/execution/test_execution_local.py tests/execution/test_execution_remote.py tests/execution/test_execution_docker.py tests/execution/test_execution_worktree.py tests/execution/test_launch_guard.py tests/execution/test_external_launcher.py tests/execution/test_work_launcher.py tests/execution/test_executor_stream.py tests/execution/test_claude_sdk_bridge.py tests/execution/test_provider_probe.py tests/execution/test_verifier.py tests/review/test_verification.py tests/evolution/test_evolution_evolver.py tests/platform/test_health_collect.py tests/control/test_execution_trust_authority.py tests/control/test_operator_launch.py tests/control/test_control_store.py tests/platform/test_main_cli.py -q
if ($LASTEXITCODE -ne 0) { throw 'Task 1 focused tests failed' }
python tools/dev.py lint agents/execution/executor.py agents/execution/executor_stream.py agents/execution/claude_sdk_bridge.py agents/review/verification.py agents/review/verifier_sanitize.py learning/evolution/evolver.py platform_core/ops/health.py platform_core/execution/provider_probe.py platform_core/execution/router.py platform_core/execution/environment.py platform_core/execution/wiring.py platform_core/execution/trust.py platform_core/execution/launch_guard.py platform_core/runtime/execution_trust.py platform_core/runtime/operator_launch.py
if ($LASTEXITCODE -ne 0) { throw 'Task 1 lint failed' }
$devToolRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) '9to5\galaxy-dev-tools'
$devPython = (python tools/bootstrap_galaxy_dev_tools.py --lock bootstrap/galaxy_launcher/dev_tools.lock.json --root $devToolRoot --download-if-missing --only-binary --require-hashes --print-python-only).Trim()
if ($LASTEXITCODE -ne 0 -or -not $devPython -or -not (Test-Path -LiteralPath $devPython -PathType Leaf)) { throw 'Pinned GALAXY development typechecker bootstrap failed' }
$mypyVersion = (& $devPython -m mypy --version).Trim()
if ($LASTEXITCODE -ne 0 -or $mypyVersion -notmatch '^mypy 2\.3\.0(?: |$)') { throw "Unexpected pinned mypy version: $mypyVersion" }
& $devPython tools/dev.py typecheck agents/execution/executor.py agents/execution/executor_stream.py agents/execution/claude_sdk_bridge.py agents/review/verification.py agents/review/verifier_sanitize.py learning/evolution/evolver.py platform_core/ops/health.py platform_core/execution/provider_probe.py platform_core/execution/router.py platform_core/execution/environment.py platform_core/execution/wiring.py platform_core/execution/trust.py platform_core/execution/launch_guard.py platform_core/runtime/execution_trust.py platform_core/runtime/operator_launch.py
if ($LASTEXITCODE -ne 0) { throw 'Task 1 typecheck failed' }
$planPath = 'docs/superpowers/plans/2026-07-13-galaxy-r3-transactional-kernel.md'
$devToolRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) '9to5\galaxy-dev-tools'
$devPython = (python tools/bootstrap_galaxy_dev_tools.py --lock bootstrap/galaxy_launcher/dev_tools.lock.json --root $devToolRoot --offline --only-binary --require-hashes --print-python-only).Trim()
if ($LASTEXITCODE -ne 0 -or -not $devPython -or -not (Test-Path -LiteralPath $devPython -PathType Leaf)) { throw 'Pinned GALAXY development typechecker is unavailable' }
$mypyVersion = (& $devPython -m mypy --version).Trim()
if ($LASTEXITCODE -ne 0 -or $mypyVersion -notmatch '^mypy 2\.3\.0(?: |$)') { throw "Unexpected pinned mypy version: $mypyVersion" }
function Get-GalaxyManifest { param([int[]]$Tasks, [string]$Kind)
  $taskArgs = @(); foreach ($task in $Tasks) { $taskArgs += @('--task', [string]$task) }
  $paths = @(python tools/galaxy_plan_manifest.py --plan $planPath @taskArgs --kind $Kind)
  if ($LASTEXITCODE -ne 0 -or -not $paths.Count -or @($paths | Where-Object { -not $_ }).Count) { throw "GALAXY manifest extraction failed for $Kind" }
  if (@($paths | Sort-Object -Unique).Count -ne $paths.Count) { throw "GALAXY manifest emitted duplicate $Kind paths" }
  return $paths
}
$manifestTests = @(Get-GalaxyManifest @(1) tests)
$manifestPython = @(Get-GalaxyManifest @(1) python)
$manifestProduction = @(Get-GalaxyManifest @(1) production-python)
function Invoke-GalaxyChunks { param([string[]]$Paths, [string]$Mode, [string]$Label)
  for ($offset = 0; $offset -lt $Paths.Count; $offset += 40) {
    $last = [Math]::Min($offset + 39, $Paths.Count - 1); $chunk = @($Paths[$offset..$last])
    switch ($Mode) { 'pytest' { python -m pytest @chunk -q } 'compile' { python -m compileall @chunk } 'lint' { python tools/dev.py lint @chunk } 'typecheck' { & $devPython tools/dev.py typecheck @chunk } default { throw "Unknown GALAXY check mode: $Mode" } }
    if ($LASTEXITCODE -ne 0) { throw "$Label failed for manifest chunk $offset..$last" }
  }
}
Invoke-GalaxyChunks $manifestTests pytest 'Task 1 complete manifest tests'
Invoke-GalaxyChunks $manifestPython compile 'Task 1 complete manifest compile'
Invoke-GalaxyChunks $manifestPython lint 'Task 1 complete manifest lint'
Invoke-GalaxyChunks $manifestProduction typecheck 'Task 1 complete manifest typecheck'
git diff --check
if ($LASTEXITCODE -ne 0) { throw 'Task 1 diff check failed' }
```

Expected: focused tests pass; the explicit interim gates report no lint or type regression. Do not use `tools/dev.py check` in Tasks 1-4: it unconditionally runs `repo_map.py --check`, while mapped artifacts intentionally remain frozen until Task 5's clean-tree review and one-time regeneration.

Now—and not at the earlier contract-writing Step 0—perform the actual TOFU installation. The Task 1 production/test bytes must already be green, exact manifests/locks must be closed, two independent reviews must have no P0/P1, and the source tree may contain only the declared Task 1 implementation paths. Before invocation, the operator uses an OS-owned copy/launch tool outside this repository to create the independently reviewed `tofu_bootstrap.ps1` bytes in a new ACL-protected external staging directory, prove the directory and file are ordinary non-reparse single-link objects, record both stable identities plus the full SHA-256, and deny target/user write/delete. The parent process opens the file without write/delete sharing and retains that verified handle across the synchronous PowerShell launch, rehashes it afterward, and requires the child receipt to bind the same path, identity, digest, protected parent identity, and host process. This is the explicit out-of-band root: a same-user or privileged attacker that defeats the operator-owned staging ACL/tool remains outside the target-repository claim, but a repository race cannot swap bytes between review and parse. It is intentionally interactive: the external copier displays the full trust-closure digest and waits for the fresh exact nonce response. The current generic unattended approval cannot satisfy it, so an unattended implementation run stops here without committing or cutting over.

```powershell
$pinnedPowerShell = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
function Resolve-StrictLocalAbsolutePath { param([string]$RawPath)
  if ([string]::IsNullOrWhiteSpace($RawPath) -or $RawPath -notmatch '^[A-Za-z]:[\\/]' -or $RawPath.StartsWith('\\?\') -or $RawPath.StartsWith('\\.\') -or $RawPath.StartsWith('//?/') -or $RawPath.StartsWith('//./')) { throw "Not a strict local drive-absolute path: $RawPath" }
  $full = [System.IO.Path]::GetFullPath($RawPath); if ($full -notmatch '^[A-Za-z]:\\') { throw "Path normalization lost drive-absolute form: $RawPath" }; return $full
}
$repoRoot = Resolve-StrictLocalAbsolutePath (Get-Location).Path
$tofuBootstrap = 'C:\ProgramData\9to5\singularity-tofu-staging\tofu_bootstrap.ps1'
$reviewedTofuSha256 = '<FULL-SHA256-FROM-INDEPENDENT-OS-COPY-REVIEW>'
$bootstrapManifest = [System.IO.Path]::GetFullPath((Join-Path $repoRoot 'bootstrap\galaxy_launcher\manifest.json'))
$runtimeLock = [System.IO.Path]::GetFullPath((Join-Path $repoRoot 'bootstrap\galaxy_launcher\runtime.lock.json'))
$imageLock = [System.IO.Path]::GetFullPath((Join-Path $repoRoot 'bootstrap\galaxy_launcher\activation_images.lock.json'))
foreach ($path in @($pinnedPowerShell, $tofuBootstrap, $bootstrapManifest, $runtimeLock, $imageLock)) {
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing TOFU input: $path" }
}
$repoPrefix = $repoRoot.TrimEnd('\') + '\'
if ($tofuBootstrap.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'TOFU bootstrap must be the independently reviewed external copy, never the repository script path' }
$tofuIdentity = '<STABLE-FILE-IDENTITY-FROM-INDEPENDENT-OS-COPY-LAUNCH-TOOL>'
$tofuParentIdentity = '<STABLE-PARENT-IDENTITY-FROM-INDEPENDENT-OS-COPY-LAUNCH-TOOL>'
$tofuStream = [System.IO.File]::Open($tofuBootstrap, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read)
try {
  $sha256 = [System.Security.Cryptography.SHA256]::Create()
  try { $observedTofuSha256 = [System.BitConverter]::ToString($sha256.ComputeHash($tofuStream)).Replace('-', '') }
  finally { $sha256.Dispose() }
  if ($observedTofuSha256 -cne $reviewedTofuSha256) { throw 'External TOFU bootstrap digest differs from the independently reviewed OS-copy digest' }
  $tofuReceipt = (& $pinnedPowerShell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $tofuBootstrap --require-self-digest $reviewedTofuSha256 --require-open-parent-identity $tofuParentIdentity --require-open-file-identity $tofuIdentity --require-protected-nonreparse-single-link-staging --bind-child-opened-same-file --install-inactive --repo $repoRoot --bootstrap-manifest $bootstrapManifest --runtime-lock $runtimeLock --activation-image-lock $imageLock --canonicalize-text-leaves-with-source-policy strict-utf8-parent-bom-preserving-crlf-to-lf-or-exact --bind-raw-to-canonical-leaf-map --require-absolute-no-follow-inputs --require-two-independent-review-evidence --display-full-merkle-challenge --require-fresh-exact-nonce-response --register-fresh-anchor-service --install-request-only-client --persist-and-reread-tofu-receipt).Trim()
  if ($LASTEXITCODE -ne 0 -or -not $tofuReceipt) { throw 'TOFU installation was not approved and verified; stop before Task 1 commit/cutover' }
  $tofuStream.Position = 0; $sha256 = [System.Security.Cryptography.SHA256]::Create()
  try { $postLaunchTofuSha256 = [System.BitConverter]::ToString($sha256.ComputeHash($tofuStream)).Replace('-', '') } finally { $sha256.Dispose() }
  if ($postLaunchTofuSha256 -cne $reviewedTofuSha256) { throw 'Held TOFU bootstrap bytes changed across launch; installed state requires external reconciliation' }
} finally { $tofuStream.Dispose() }
$singularityClient = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) '9to5\singularity\bin\singularity-admin-client.ps1'
function Invoke-SingularityAdmin { & $pinnedPowerShell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $singularityClient --request-only --require-server-validated-client-digest @args }
Invoke-SingularityAdmin verify-tofu-receipt --receipt $tofuReceipt --require-full-leaf-manifest --require-protected-generation --require-sealed-runtime-and-images --require-inactive-service-readiness
if ($LASTEXITCODE -ne 0) { throw 'Installed TOFU root or inactive readiness could not be re-read; stop before source commit' }
```

Commit:

```powershell
$pinnedPowerShell = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
$bootstrapClient = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) '9to5\singularity\bin\singularity-admin-client.ps1'
if (-not (Test-Path -LiteralPath $pinnedPowerShell -PathType Leaf) -or -not (Test-Path -LiteralPath $bootstrapClient -PathType Leaf)) { throw 'Initial external Singularity service/client is unavailable; complete the fresh exact-digest root-of-trust ceremony before cutover' }
function Invoke-SingularityRecoveryAdmin { & $pinnedPowerShell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $bootstrapClient --request-only --require-server-validated-client-digest @args }
function Invoke-SingularityAdmin { Invoke-SingularityRecoveryAdmin @args }
Invoke-SingularityAdmin verify-self --require-fresh-service-host --require-os-pinned-digest --require-protected-acl --require-current-generation --require-closed-launch-record
if ($LASTEXITCODE -ne 0) { throw 'External Singularity Anchor failed root-of-trust verification' }
$tofuReceipt = (Invoke-SingularityAdmin current-tofu-receipt --require-protected-generation --persisted-and-reread).Trim()
if ($LASTEXITCODE -ne 0 -or -not $tofuReceipt) { throw 'Unable to resolve the installed TOFU receipt before cutover' }
function Resolve-StrictLocalAbsolutePath { param([string]$RawPath)
  if ([string]::IsNullOrWhiteSpace($RawPath) -or $RawPath -notmatch '^[A-Za-z]:[\\/]' -or $RawPath.StartsWith('\\?\') -or $RawPath.StartsWith('\\.\') -or $RawPath.StartsWith('//?/') -or $RawPath.StartsWith('//./')) { throw "Not a strict local drive-absolute path: $RawPath" }
  $full = [System.IO.Path]::GetFullPath($RawPath)
  if ($full -notmatch '^[A-Za-z]:\\') { throw "Path normalization lost drive-absolute form: $RawPath" }
  return $full
}
$repoRoot = Resolve-StrictLocalAbsolutePath (Get-Location).Path
function Complete-SingularityTopLevelSlot { param([string]$Repository)
  function Invoke-SingularityAdmin { Invoke-SingularityRecoveryAdmin @args }
  $currentPurpose = (Invoke-SingularityAdmin resolve-current-top-level-transition --repo $Repository --repository-global-all-generations --read-only --require-unique-live-slot --print-none-or-bound-purpose-receipt).Trim()
  if ($LASTEXITCODE -ne 0 -or -not $currentPurpose) { throw 'Pure repository-global transition lookup failed; no settlement is authorized' }
  if ($currentPurpose -eq 'none') { return 'none' }
  if ($currentPurpose -notmatch '^purpose_[0-9a-f]{64}$') { throw 'Occupied transition has an invalid or ambiguous purpose receipt' }
  $terminalKind = $null
  $recoveryOwnerFence = $null
  for ($pass = 0; $pass -lt 2; $pass += 1) {
    $observeArgs = @('observe-top-level-transition','--repo',$Repository,'--repository-global-all-generations','--bound-purpose-receipt',$currentPurpose,'--read-only','--include-owner-lease-and-fencing-generation','--require-latest-journal-live-state-and-ingress','--closed-terminal-map','singularity-top-level-terminal-v1','--print-owner-state-recovery-pending-or-terminal-observation')
    if ($recoveryOwnerFence) { $observeArgs += @('--transition-owner-fence-receipt',$recoveryOwnerFence,'--require-current-owner-fencing-generation') }
    $slotResult = (Invoke-SingularityAdmin @observeArgs).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $slotResult) { throw 'Occupied transition disposition is unknown; do not mutate or start another transition' }
    if ($slotResult -in @('active_owned_elsewhere','owner_liveness_unknown')) { throw "Occupied transition has a live or unproven owner: $currentPurpose" }
    if ($slotResult -eq 'recovery_pending') { throw "Occupied transition remains recovery-pending: $currentPurpose" }
    if ($slotResult -match '^recoverable_dead_owner_([0-9a-f]{64})$') {
      $eligibilityReceipt = $Matches[1]
      $recoveryOwnerFence = (Invoke-SingularityAdmin settle-top-level-transition --repo $Repository --repository-global-all-generations --bound-purpose-receipt $currentPurpose --dead-owner-eligibility-receipt $eligibilityReceipt --revalidate-owner-dead-expired-and-quiesced-under-slot-lock --advance-owner-fencing-generation-before-mutation --existing-slot-only --journal-bound-settlement --allow-cancel-only-with-no-begin-proof --no-new-candidate --no-new-selection --no-unbound-state-adoption --persist-before-response --print-recovery-owner-fence-receipt).Trim()
      if ($LASTEXITCODE -ne 0 -or $recoveryOwnerFence -notmatch '^ownerfence_[0-9a-f]{64}$') { throw "Dead-owner settlement failed safely for $currentPurpose" }
      continue
    }
    if ($slotResult -notmatch '^terminal_(cutover|source|controller)_(achieved|retryable_old|verified_rollback|safe_failed)_([0-9a-f]{64})$') { throw 'Occupied transition observation is malformed or outside the closed terminal map' }
    $terminalKind = $Matches[2]
    Invoke-SingularityAdmin acknowledge-terminal-disposition --repo $Repository --repository-global-all-generations --bound-purpose-receipt $currentPurpose --terminal-observation-token $slotResult --closed-terminal-map singularity-top-level-terminal-v1 --revalidate-observation-still-current-before-ack --require-current-owner-fencing-generation-bound-to-observation --atomic-under-slot-lock --reject-cross-operation-purpose-epoch-or-owner-token-replay --idempotent --persist-before-response | Out-Null
    $ackExit = $LASTEXITCODE
    break
  }
  if (-not $terminalKind) { throw "Settlement did not produce an acknowledgeable terminal observation for $currentPurpose" }
  $afterAck = (Invoke-SingularityAdmin resolve-transition-purpose-outcome --repo $Repository --purpose-receipt $currentPurpose --read-only --require-unique-exact-archive --require-observation-acknowledgement-chain --print-archived-outcome).Trim()
  $expectedArchive = @{ achieved='archived_achieved'; retryable_old='archived_retryable'; verified_rollback='archived_rollback'; safe_failed='archived_failed' }
  if ($LASTEXITCODE -ne 0 -or $afterAck -ne $expectedArchive[$terminalKind]) { throw "Terminal acknowledgement/archive disagreement after ack_exit=$ackExit" }
  $released = (Invoke-SingularityAdmin resolve-current-top-level-transition --repo $Repository --repository-global-all-generations --read-only --require-unique-live-slot --print-none-or-bound-purpose-receipt).Trim()
  if ($LASTEXITCODE -ne 0 -or $released -ne 'none') { throw 'Acknowledged transition did not release the repository-global live slot' }
  return "$afterAck|$currentPurpose"
}
function Resolve-SingularityPurposeStartDisposition { param([string]$Repository, [string]$DesiredPurpose, [string]$PriorTerminal)
  if ($DesiredPurpose -notmatch '^purpose_[0-9a-f]{64}$') { throw 'Invalid service-issued desired-purpose receipt' }
  if ($PriorTerminal -ne 'none') {
    $priorParts = @($PriorTerminal -split '\|', 2); if ($priorParts.Count -ne 2) { throw 'Malformed prior terminal result' }
    $relationship = (Invoke-SingularityAdmin classify-purpose-successor --repo $Repository --completed-purpose-receipt $priorParts[1] --desired-purpose-receipt $DesiredPurpose --read-only --require-closed-reviewed-purpose-dag --require-explicit-wave-restart-edge --reject-multiple-matching-archives --print-same-allowed-predecessor-or-unrelated).Trim()
    if ($LASTEXITCODE -ne 0 -or $relationship -notin @('same','allowed_predecessor','unrelated_or_new_epoch')) { throw 'Purpose relationship is unknown' }
    if ($relationship -eq 'unrelated_or_new_epoch') { throw 'Prior occupied purpose is unrelated to the desired purpose or lacks an explicit wave-restart edge' }
    if ($relationship -eq 'allowed_predecessor' -and $priorParts[0] -ne 'archived_achieved') { throw 'Only an achieved reviewed predecessor may advance the purpose DAG' }
  }
  $desiredOutcome = (Invoke-SingularityAdmin resolve-transition-purpose-outcome --repo $Repository --purpose-receipt $DesiredPurpose --read-only --require-unique-exact-archive --print-clear-never-started-or-archived-outcome).Trim()
  if ($LASTEXITCODE -ne 0 -or $desiredOutcome -notin @('clear_never_started','archived_achieved','archived_retryable','archived_rollback','archived_failed')) { throw 'Desired-purpose outcome is unknown or ambiguous' }
  if ($desiredOutcome -eq 'archived_achieved') { return 'already_achieved' }
  if ($desiredOutcome -in @('clear_never_started','archived_retryable')) { return 'proceed' }
  if ($desiredOutcome -eq 'archived_rollback') { throw "Desired purpose was previously rolled back: $DesiredPurpose" }
  throw "Desired purpose previously failed safely: $DesiredPurpose"
}
$priorTerminal = Complete-SingularityTopLevelSlot $repoRoot
$purposeIssueReply = (Invoke-SingularityAdmin acquire-transition-purpose --repo $repoRoot --reviewed-plan-node task1-cutover-v1 --operation cutover --contract cutover-drain-v1 --requested-fences close-ingress+quiesce-legacy-tree+hold-restart-fence --bind-active-reviewed-wave-epoch --require-wave-epoch-bound-to-current-tofu-receipt --require-satisfied-reviewed-predecessor-ledger --reject-unrelated-or-multiple-predecessor-archives --bind-exact-old-state --capture-native-no-follow-pre-normalization-batch --bind-canonicalization-policy strict-utf8-parent-bom-preserving-crlf-to-lf-or-exact --create-or-return-exact --persist-before-response --print-purpose-receipt).Trim()
$purposeIssueExit = $LASTEXITCODE
$transitionPurpose = (Invoke-SingularityAdmin resolve-transition-purpose --repo $repoRoot --reviewed-plan-node task1-cutover-v1 --operation cutover --contract cutover-drain-v1 --requested-fences close-ingress+quiesce-legacy-tree+hold-restart-fence --bind-active-reviewed-wave-epoch --require-wave-epoch-bound-to-current-tofu-receipt --require-satisfied-reviewed-predecessor-ledger --reject-unrelated-or-multiple-predecessor-archives --bind-exact-old-state --capture-native-no-follow-pre-normalization-batch --bind-canonicalization-policy strict-utf8-parent-bom-preserving-crlf-to-lf-or-exact --read-only --require-unique-exact --print-purpose-receipt-or-none).Trim()
if ($LASTEXITCODE -ne 0 -or $transitionPurpose -notmatch '^purpose_[0-9a-f]{64}$') { throw "Task 1 purpose is not recoverable after issue_exit=$purposeIssueExit" }
if ($purposeIssueExit -eq 0 -and $purposeIssueReply -and $purposeIssueReply -ne $transitionPurpose) { throw 'Task 1 purpose issue reply disagrees with authoritative resolution' }
$slotOutcome = Resolve-SingularityPurposeStartDisposition $repoRoot $transitionPurpose $priorTerminal
if ($slotOutcome -eq 'already_achieved') { Write-Output 'Task 1 cutover was already authoritatively completed and acknowledged'; return }
$cutoverIntentReply = (Invoke-SingularityAdmin acquire-begin-intent --repo $repoRoot --operation cutover --contract cutover-drain-v1 --transition-purpose-receipt $transitionPurpose --require-exact-purpose-binding --require-reviewed-purpose-dag --requested-fences close-ingress+quiesce-legacy-tree+hold-restart-fence --bind-exact-old-state --exclusive-top-level-mutation-per-registered-repo-all-generations --create-or-return-unique-slot --persist-before-response --print-request-id).Trim()
$cutoverIntentExit = $LASTEXITCODE
$cutoverRequestId = (Invoke-SingularityAdmin resolve-begin-intent --repo $repoRoot --operation cutover --contract cutover-drain-v1 --transition-purpose-receipt $transitionPurpose --require-exact-purpose-binding --requested-fences close-ingress+quiesce-legacy-tree+hold-restart-fence --bind-exact-old-state --exclusive-top-level-mutation-per-registered-repo-all-generations --read-only --require-unique-slot --require-persisted-intent --print-request-id-or-none).Trim()
if ($LASTEXITCODE -ne 0 -or -not $cutoverRequestId -or $cutoverRequestId -eq 'none') { throw "Cutover begin intent is not authoritatively discoverable after intent_exit=$cutoverIntentExit; recover by repository and operation contract without starting another transition" }
if ($cutoverIntentExit -eq 0 -and $cutoverIntentReply -and $cutoverIntentReply -ne $cutoverRequestId) { throw 'Cutover intent reply disagrees with authoritative intent discovery; do not start another transition' }
$ownerFenceReceipt = (Invoke-SingularityAdmin resolve-begin-intent-owner-fence --repo $repoRoot --request-id $cutoverRequestId --transition-purpose-receipt $transitionPurpose --read-only --require-current-owner-lease-and-fencing-generation --print-owner-fence-receipt).Trim()
if ($LASTEXITCODE -ne 0 -or $ownerFenceReceipt -notmatch '^ownerfence_[0-9a-f]{64}$') { throw 'Cutover owner-fence receipt is unavailable; do not begin' }
function Invoke-SingularityAdmin { $recoveryCommands=@('resolve-current-top-level-transition','observe-top-level-transition','settle-top-level-transition','acknowledge-terminal-disposition','resolve-transition-purpose-outcome');if($args.Count-and$args[0]-in$recoveryCommands){& $pinnedPowerShell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $bootstrapClient --request-only --require-server-validated-client-digest @args}else{& $pinnedPowerShell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $bootstrapClient --request-only --require-server-validated-client-digest --transition-purpose-receipt $transitionPurpose --transition-owner-fence-receipt $ownerFenceReceipt --require-current-owner-fencing-generation @args} }
$cutoverReplyTx = (Invoke-SingularityAdmin begin-cutover --request-id $cutoverRequestId --idempotent-create --repo $repoRoot --require-exact-purpose-binding --close-ingress --quiesce-legacy-tree --hold-restart-fence --persist-begin-receipt-before-response).Trim()
$cutoverReplyExit = $LASTEXITCODE
$cutoverTx = (Invoke-SingularityAdmin resolve-cutover-begin --request-id $cutoverRequestId --repo $repoRoot --read-only --require-exact-request-binding --require-exact-purpose-binding --require-persisted-begin-receipt-if-started --require-latest-monotone-journal-if-started --require-exact-old-state-if-started --require-live-requested-fences-held-if-started --classify-started-exact-requested-fences-held-or-not-started --print-transaction-or-not-started).Trim()
if ($LASTEXITCODE -ne 0 -or -not $cutoverTx) { throw "Cutover begin state is uncertain after begin_exit=$cutoverReplyExit; do not use or infer ingress state; recover by request ID $cutoverRequestId" }
if ($cutoverTx -eq 'not_started') { throw "External maintenance drain did not start; request ID $cutoverRequestId" }
if ($cutoverReplyExit -eq 0 -and $cutoverReplyTx -and $cutoverReplyTx -ne $cutoverTx) { throw "Cutover begin reply disagrees with authoritative resolution; do not infer ingress state; recover by request ID $cutoverRequestId" }
function Stop-SingularityCutoverBeforeCas { param([string]$Reason, [string]$Proposal)
  $abortArgs = @('abort-cutover', '--transaction', $cutoverTx, '--before-source-cas-only', '--abort-all-child-resources', '--reconcile-journaled-ref-config-normalization', '--restore-old-ingress-only-if-ref-index-tree-config-byte-identical', '--persist-and-reread-recovery-receipt', '--print-disposition')
  if ($Proposal) { $abortArgs += @('--source-proposal', $Proposal) }
  Invoke-SingularityAdmin @abortArgs | Out-Null
  $abortExit = $LASTEXITCODE
  $disposition = (Invoke-SingularityAdmin resolve-cutover-disposition --transaction $cutoverTx --read-only --require-persisted-receipt --classify-safe-old-ingress-open-or-held-closed-or-recovery-pending --print-disposition).Trim()
  if ($LASTEXITCODE -ne 0 -or $disposition -notin @('safe_old_ingress_open', 'safe_old_ingress_held_closed', 'fenced_recovery_pending')) { throw "$Reason; authoritative cutover disposition is unavailable after abort_exit=$abortExit; do not infer ingress state; recover transaction $cutoverTx" }
  if ($disposition -eq 'safe_old_ingress_open') { throw "$Reason; exact old state is restored and old ingress is authoritatively open" }
  if ($disposition -eq 'safe_old_ingress_held_closed') { throw "$Reason; exact old state is restored but ingress is authoritatively held closed" }
  throw "$Reason; a durable recovery receipt proves ingress held closed pending recovery"
}
Invoke-SingularityAdmin verify-drained --transaction $cutoverTx --require-no-listener --require-no-legacy-controller --watch-restarts
if ($LASTEXITCODE -ne 0) { Stop-SingularityCutoverBeforeCas 'Legacy process/listener drain is not proven' '' }
Invoke-SingularityAdmin normalize-bootstrap-ref --transaction $cutoverTx --repo $repoRoot --resolve-packed-symbolic-head --create-if-absent-or-verify-existing-same-oid --allow-matching-stale-packed-shadow --no-follow --reread-equality
if ($LASTEXITCODE -ne 0) { Stop-SingularityCutoverBeforeCas 'Packed-to-loose bootstrap ref normalization failed' '' }
Invoke-SingularityAdmin normalize-bootstrap-git-config --transaction $cutoverTx --repo $repoRoot --git-compatible-bounded-parser --preserve-inert-duplicate-branch-metadata --remove-unused-worktreeconfig --replace-hooks-path-only-if-no-active-hook --core-autocrlf false --core-safecrlf true --disable-auto-maintenance-and-ref-packing --no-follow --reread-policy
if ($LASTEXITCODE -ne 0) { Stop-SingularityCutoverBeforeCas 'Bootstrap Git-config normalization failed' '' }
Invoke-SingularityAdmin attest-target --repo $repoRoot --require-current-directory --no-follow --require-symbolic-loose-head --print-identity
if ($LASTEXITCODE -ne 0) { Stop-SingularityCutoverBeforeCas 'Canonical repository identity failed external post-normalization attestation' '' }
$planPath = 'docs/superpowers/plans/2026-07-13-galaxy-r3-transactional-kernel.md'
$stageAllowlist = @(python tools/galaxy_plan_manifest.py --plan $planPath --task 1 --kind all)
if ($LASTEXITCODE -ne 0 -or -not $stageAllowlist.Count) { Stop-SingularityCutoverBeforeCas 'Task 1 manifest extraction failed' '' }
$requiredChanges = @(python tools/galaxy_plan_manifest.py --plan $planPath --task 1 --kind required-changes)
if ($LASTEXITCODE -ne 0 -or -not $requiredChanges.Count) { Stop-SingularityCutoverBeforeCas 'Task 1 required-change manifest extraction failed' '' }
$testPaths = @(python tools/galaxy_plan_manifest.py --plan $planPath --task 1 --kind tests)
if ($LASTEXITCODE -ne 0 -or -not $testPaths.Count) { Stop-SingularityCutoverBeforeCas 'Task 1 test manifest extraction failed' '' }
function Register-SingularityPathManifest { param([string]$Scope, [string[]]$Allowed, [string[]]$Required, [string[]]$Tests)
  function ConvertTo-SingularityManifestBase64Url { param([string]$CanonicalJson) $bytes = ([System.Text.UTF8Encoding]::new($false, $true)).GetBytes($CanonicalJson); if ($bytes.Length -gt 4096) { throw 'Path-manifest decoded JSON exceeds 4096 bytes' }; return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_') }
  $allowedSet = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
  $requiredSet = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
  $testSet = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
  foreach ($entry in $Allowed) { if (-not $entry -or $entry.Length -gt 240 -or -not $allowedSet.Add($entry)) { throw "Invalid or duplicate allowed path: $entry" } }
  foreach ($entry in $Required) { if (-not $requiredSet.Add($entry) -or -not $allowedSet.Contains($entry)) { throw "Invalid required-change subset: $entry" } }
  foreach ($entry in $Tests) { if (-not $testSet.Add($entry) -or -not $allowedSet.Contains($entry)) { throw "Invalid test subset: $entry" } }
  $records = @($Allowed | ForEach-Object {
    $isRequired = $requiredSet.Contains($_); $isTest = $testSet.Contains($_)
    $role = if ($isRequired -and $isTest) { 'required-test' } elseif ($isRequired) { 'required-change' } elseif ($isTest) { 'test-only' } else { 'allowed-only' }
    [ordered]@{ role = $role; path = $_ }
  })
  $manifestId = (Invoke-SingularityAdmin begin-path-manifest --scope $Scope --expected-total-count $Allowed.Count --expected-required-count $Required.Count --expected-test-count $Tests.Count).Trim()
  if ($LASTEXITCODE -ne 0 -or -not $manifestId) { throw 'Unable to begin external path manifest' }
  try {
    $sequence = 0; $chunk = @()
    foreach ($record in $records) {
      $trial = @($chunk + $record); $trialJson = ([ordered]@{ sequence = $sequence; records = $trial } | ConvertTo-Json -Compress -Depth 4)
      if (($trial.Count -gt 24 -or [Text.Encoding]::UTF8.GetByteCount($trialJson) -gt 4096) -and $chunk.Count) {
        $chunkJson = ([ordered]@{ sequence = $sequence; records = $chunk } | ConvertTo-Json -Compress -Depth 4)
        $chunkPayload = ConvertTo-SingularityManifestBase64Url $chunkJson
        Invoke-SingularityAdmin append-path-manifest --scope $Scope --manifest $manifestId --sequence $sequence --canonical-records-json-base64url $chunkPayload --require-strict-unpadded-base64url --require-decoded-canonical-json-max-bytes 4096 --require-decode-recanonicalize-byte-equality --require-exact-envelope-max-bytes 8192
        if ($LASTEXITCODE -ne 0) { throw "External path-manifest upload failed at sequence $sequence" }; $sequence += 1; $chunk = @($record)
      } else { $chunk = $trial }
    }
    if ($chunk.Count) { $chunkJson = ([ordered]@{ sequence = $sequence; records = $chunk } | ConvertTo-Json -Compress -Depth 4); $chunkPayload = ConvertTo-SingularityManifestBase64Url $chunkJson; Invoke-SingularityAdmin append-path-manifest --scope $Scope --manifest $manifestId --sequence $sequence --canonical-records-json-base64url $chunkPayload --require-strict-unpadded-base64url --require-decoded-canonical-json-max-bytes 4096 --require-decode-recanonicalize-byte-equality --require-exact-envelope-max-bytes 8192; if ($LASTEXITCODE -ne 0) { throw "External path-manifest upload failed at sequence $sequence" } }
    $receipt = (Invoke-SingularityAdmin seal-path-manifest --scope $Scope --manifest $manifestId --canonical-order --sha256 --require-total-count $Allowed.Count --require-required-count $Required.Count --require-test-count $Tests.Count --persist-and-reread).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $receipt) { throw 'External path-manifest seal failed' }; return $receipt
  } catch {
    Invoke-SingularityAdmin abort-path-manifest --scope $Scope --manifest $manifestId --persist-cleanup-receipt --require-no-unsealed-resource
    if ($LASTEXITCODE -ne 0) { throw "Path-manifest failure and cleanup are uncertain; transaction must remain fenced: $($_.Exception.Message)" }; throw
  }
}
try { $pathManifestReceipt = Register-SingularityPathManifest $cutoverTx $stageAllowlist $requiredChanges $testPaths }
catch { Stop-SingularityCutoverBeforeCas "Path-manifest failure: $($_.Exception.Message)" '' }
$proposalTx = (Invoke-SingularityAdmin prepare-source-commit --repo $repoRoot --cutover $cutoverTx --path-manifest-receipt $pathManifestReceipt --require-purpose-pre-normalization-batch-and-policy --revalidate-purpose-batch-under-cutover-source-fences --native-no-follow-snapshot --parent-plus-allowlist-complete-tree --eligible-text-policy strict-utf8-parent-bom-preserving-crlf-to-lf-or-exact --nonallowlist-byte-policy parent-exact-after-policy --binary-policy exact --no-ambient-git-config --no-hooks --no-filters --no-signing --fixed-commit-metadata --message 'feat: add typed staged execution contracts').Trim()
if ($LASTEXITCODE -ne 0 -or -not $proposalTx) { Stop-SingularityCutoverBeforeCas 'External sterile source-commit preparation failed' '' }
Invoke-SingularityAdmin review-source-proposal --transaction $proposalTx --sealed-independent-reviewer --require-two-independent-review-passes --persist-and-reread-review-receipt --no-canonical-write
if ($LASTEXITCODE -ne 0) { Stop-SingularityCutoverBeforeCas 'Task 1 source proposal did not receive the required independent review receipt' $proposalTx }
Invoke-SingularityAdmin verify-source-proposal --transaction $proposalTx --require-purpose-pre-normalization-batch-and-policy --require-exact-manifest --require-every-required-path-changed --require-policy-canonicalized-allowlist-byte-match --require-nonallowlist-parent-exact-after-policy --require-review-receipt --require-no-canonical-ref-write
if ($LASTEXITCODE -ne 0) { Stop-SingularityCutoverBeforeCas 'Task 1 source proposal failed exact-byte review' $proposalTx }
$trustEqualityReceipt = (Invoke-SingularityAdmin verify-proposal-trust-closure --transaction $proposalTx --tofu-receipt $tofuReceipt --require-source-leaves-equal-policy-canonical-proposed-blobs --require-artifact-leaves-equal-proposal-bound-lock-and-manifest-hashes --require-image-and-harness-root-equality --persist-and-reread-equality-receipt --no-canonical-write).Trim()
if ($LASTEXITCODE -ne 0 -or -not $trustEqualityReceipt) { Stop-SingularityCutoverBeforeCas 'Task 1 proposal differs from the installed TOFU trust closure; re-review and repeat TOFU' $proposalTx }
Invoke-SingularityAdmin commit-source-proposal --transaction $proposalTx --cutover $cutoverTx --tofu-receipt $tofuReceipt --require-purpose-pre-normalization-batch-and-policy --require-trust-closure-equality-receipt $trustEqualityReceipt --require-fresh-exact-digest-approval --bind-inactive-runtime-digest --cas-loose-ref --native-full-tree-materialize --install-verified-index --require-final-byte-clean --durable
if ($LASTEXITCODE -ne 0) {
  Invoke-SingularityAdmin reconcile-source-commit --transaction $proposalTx --cutover $cutoverTx --classify-old-or-exact-new-ref-index-tree --finish-only-journal-bound-materialization --never-run-legacy-after-visible-cas --persist-and-reread-recovery-receipt | Out-Null
  $reconcileExit = $LASTEXITCODE
  $sourceDisposition = (Invoke-SingularityAdmin resolve-source-commit-disposition --transaction $proposalTx --cutover $cutoverTx --read-only --require-persisted-receipt --classify-not-committed-exact-old-or-committed-exact-new --require-ingress-held-closed --print-disposition).Trim()
  if ($LASTEXITCODE -ne 0 -or $sourceDisposition -notin @('not_committed_exact_old_ingress_held_closed', 'committed_exact_new_ingress_held_closed')) { throw "Task 1 source-commit disposition is unavailable after reconcile_exit=$reconcileExit; do not infer ingress state; recover cutover $cutoverTx" }
  if ($sourceDisposition -eq 'not_committed_exact_old_ingress_held_closed') {
    Invoke-SingularityAdmin abort-cutover --transaction $cutoverTx --before-source-cas-only --source-proposal $proposalTx --restore-old-ingress-only-if-byte-identical --persist-and-reread-recovery-receipt | Out-Null
    $abortExit = $LASTEXITCODE
    $abortDisposition = (Invoke-SingularityAdmin resolve-cutover-disposition --transaction $cutoverTx --read-only --require-persisted-receipt --classify-safe-old-ingress-open-or-held-closed-or-recovery-pending --print-disposition).Trim()
    if ($LASTEXITCODE -ne 0 -or $abortDisposition -notin @('safe_old_ingress_open', 'safe_old_ingress_held_closed', 'fenced_recovery_pending')) { throw "Task 1 did not commit and authoritative abort disposition is unavailable after abort_exit=$abortExit; do not infer ingress state; recover transaction $cutoverTx" }
    if ($abortDisposition -eq 'safe_old_ingress_open') { throw 'Task 1 source commit did not occur; exact old state is restored and old ingress is authoritatively open' }
    if ($abortDisposition -eq 'safe_old_ingress_held_closed') { throw 'Task 1 source commit did not occur; exact old state is restored but ingress is authoritatively held closed' }
    throw 'Task 1 source commit did not occur; a durable recovery receipt proves ingress held closed pending recovery'
  }
}
function Stop-SingularityCutoverAfterCommit { param([string]$Phase, [string]$Reason)
  Invoke-SingularityAdmin reconcile-cutover-failure --transaction $cutoverTx --phase $Phase --source-proposal $proposalTx --complete-inactive-or-create-verified-monotone-source-rollback --never-restart-legacy --keep-all-ingress-fenced --persist-and-reread-recovery-receipt --print-disposition | Out-Null
  $reconcileExit = $LASTEXITCODE
  $disposition = (Invoke-SingularityAdmin resolve-cutover-disposition --transaction $cutoverTx --read-only --require-persisted-receipt --classify-inactive-ready-or-verified-source-rollback-or-recovery-pending --require-ingress-held-closed --print-disposition).Trim()
  if ($LASTEXITCODE -ne 0 -or $disposition -notin @('inactive_ready_ingress_held_closed', 'verified_source_rollback_ingress_held_closed', 'fenced_recovery_pending')) { throw "$Reason; authoritative post-commit disposition is unavailable after reconcile_exit=$reconcileExit; do not infer ingress state; recover transaction $cutoverTx" }
  throw "$Reason; disposition=$disposition; the persisted receipt proves ingress held closed pending explicit verified resume"
}
Invoke-SingularityAdmin install-inactive --transaction $cutoverTx --source-proposal $proposalTx --consume-bound-cutover-authority --require-sealed-offline-runtime
if ($LASTEXITCODE -ne 0) { Stop-SingularityCutoverAfterCommit 'inactive-install' 'Inactive installation failed after source commit' }
Invoke-SingularityAdmin handoff-to-anchor --transaction $cutoverTx --expect-mode inactive --require-no-legacy-controller --atomic-fence-transfer
if ($LASTEXITCODE -ne 0) { Stop-SingularityCutoverAfterCommit 'anchor-handoff' 'Inactive anchor handoff failed' }
Invoke-SingularityAdmin verify-cutover --transaction $cutoverTx --expect-mode inactive --require-no-listener --require-no-legacy-controller
if ($LASTEXITCODE -ne 0) { Stop-SingularityCutoverAfterCommit 'post-handoff-verification' 'Inactive Singularity readiness is not proven; Task 2 is forbidden' }
Invoke-SingularityAdmin finish-cutover --transaction $cutoverTx --require-inactive-readiness-receipt --release-developer-only-source-update-ingress --keep-production-run-inactive --keep-discord-listener-disabled --persist-and-reread-finish-receipt --print-disposition | Out-Null
$finishExit = $LASTEXITCODE
$cutoverDisposition = (Invoke-SingularityAdmin resolve-cutover-disposition --transaction $cutoverTx --read-only --require-persisted-receipt --classify-inactive-ready-developer-ingress-open-or-held-closed-or-recovery-pending --require-production-run-inactive --require-discord-listener-disabled --print-disposition).Trim()
if ($LASTEXITCODE -ne 0 -or $cutoverDisposition -notin @('inactive_ready_developer_ingress_open', 'inactive_ready_ingress_held_closed', 'fenced_recovery_pending')) { throw "Task 1 finish disposition unavailable after finish_exit=$finishExit; do not infer ingress state; recover transaction $cutoverTx" }
if ($cutoverDisposition -ne 'inactive_ready_developer_ingress_open') { throw "Task 1 inactive cutover is authoritative but developer ingress did not reopen: $cutoverDisposition" }
$terminalOutcome = Complete-SingularityTopLevelSlot $repoRoot
if ($terminalOutcome -ne "archived_achieved|$transitionPurpose") { throw 'Task 1 terminal transition was not observed, acknowledged, archived, and released as achieved' }
```

---

## 4. Task 2 - Build sterile object-only staging with fenced promotion

**Files**

- Modify: `platform_core/runtime/worktree.py`
- Add: `platform_core/runtime/candidate.py`
- Add: `platform_core/runtime/attempt_journal.py`
- Add: `platform_core/runtime/receipts.py`
- Add: `platform_core/runtime/sterile_git.py`
- Add: `platform_core/runtime/object_manifest.py`
- Add: `platform_core/runtime/git_object_writer.py`
- Add: `platform_core/runtime/git_index.py`
- Add: `platform_core/runtime/canonical_repo.py`
- Add: `platform_core/runtime/loose_refs.py`
- Add: `platform_core/execution/object_parser.py`
- Add: `containers/galaxy/object_parser_entrypoint.py`
- Modify: `platform_core/core/fsio.py`
- Modify: `platform_core/execution/backends/worktree.py`
- Add: `platform_core/execution/backends/clone.py`
- Test: `tests/execution/test_worktree.py`
- Test: `tests/execution/test_execution_worktree.py`
- Test: `tests/execution/test_fsio.py`
- Add: `tests/execution/test_candidate.py`
- Add: `tests/execution/test_execution_clone.py`
- Add: `tests/execution/test_sterile_git.py`
- Add: `tests/execution/test_object_parser.py`
- Add: `tests/execution/test_git_object_writer.py`
- Add: `tests/execution/test_git_index.py`
- Add: `tests/execution/test_canonical_repo.py`
- Add: `tests/execution/test_loose_refs.py`
- Add: `tests/execution/test_staged_revision.py`
- Add: `tests/execution/test_attempt_journal.py`
- Add: `tests/execution/test_attempt_crash_matrix.py`
- Add: `tests/execution/test_receipts.py`
- Add: `tests/execution/test_promotion_authorization.py`

### Step 1: Add real-repository failing tests

Every critical test uses a temporary real Git repository, not a Git command mock.

Add tests proving:

1. Legacy production worktree provisioning refuses shared-checkout fallback and is never selected as a model command surface.
2. `stageCandidateSnapshotAgainst()` leaves canonical HEAD, index, and files unchanged while creating the exact proposed tree/commit from a pinned parser's canonical manifest through the memory-safe object writer.
3. No linked worktree or candidate-controlled filesystem is created for staging; the checkpoint/proposed refs are the only executable-code-independent inputs.
4. Rejection after failed verification leaves canonical unchanged and the checkpoint/proposed commits readable with `git show`.
5. Promotion succeeds only while the immutable proposed ref still names the exact sealed commit/tree.
6. Ref movement, native-snapshot/blob/manifest drift, object-writer drift, or proposed-ref drift causes integrity failure and rejection.
7. A stale expected canonical SHA fails compare-and-swap and does not change canonical.
8. Two disjoint changes can land in order only as separate revision-bound attempts: promote A, quiesce and invalidate every B0 resource, advance the run revision and snapshot to A's resulting SHA, provision a fresh B lease against that SHA, then promote B and retain both files. An old B0 candidate is never replayed against A.
9. Failed or rejected candidate checkout changes are checkpointed before removal.
10. Candidate, snapshot/blob-manifest, verification-clone, and staged-ref cleanup errors are separated from landing truth.
11. Branch commits stay recoverable even after checkout removal.
12. Ignored cache files do not invalidate integrity, while unignored files do.
13. A rejected proposed revision remains readable with `git show` through a quarantine ref after disposable-clone removal.
14. A dirty canonical worktree fails promotion before merge; its HEAD and files remain untouched.
15. Reusing the same subtask ID cannot erase an older checkpoint: every attempt has an immutable checkpoint ref that survives `git gc --prune=now`.
16. A concurrent ref move injected after preflight but before promotion causes atomic old-OID CAS refusal.
17. A crash after the ref CAS but before caller state persistence is reconciled from the durable journal.
18. A crash before the ref CAS leaves canonical at expected and reconciles as not promoted.
19. A crash during worktree materialization never produces `done`; restart either proves the old tree was untouched and completes materialization, or records a recovery conflict without destructive guessing.
20. Every executable outer clone lease is durably registered before candidate commands launch.
21. A simulated hard process death during dirty Local/Docker execution is recovered before same-SID branch/path reuse: the inner resource is quiesced, changes are checkpointed to a create-only ref, and `git gc --prune=now` cannot erase them.
22. An active or non-quiescent stale lease is preserved and blocks reuse with explicit recovery failure.
23. Repeating checkpoint recovery with the same ref/SHA is idempotent; attempting to move that ref to a different SHA is an integrity failure.
24. A terminal `promoted` journal record lacking TaskState acknowledgement remains explicitly discoverable and immutable for Task 3's acknowledgement helper; Task 2 never mutates TaskState.
25. Rejection creates the quarantine ref before proposed-ref/artifact removal; any ref-transaction failure preserves the original refs and evidence.
26. Moving or recreating the candidate branch after snapshot cannot change staging input; preparation consumes only the immutable native snapshot plus parser-output manifest/blob-set digests.
27. Journal/lock/control files and candidate/verification checkout roots resolve outside canonical; a proposed commit cannot overwrite them even after changing `.gitignore`.
28. Proposed trees containing a reserved configured runtime-data/control path are rejected before verification/promotion.
29. A legacy worktree found under the old in-repository `STATE_DIR/.sc-worktrees` root is checkpointed if dirty and never reused; clean legacy entries are safely retired.
30. A normal old-OID refusal durably closes as `cas_refused`, preserves recovery refs, and does not block later re-preparation.
31. A crash immediately before or after the single canonical loose-ref lockfile rename is classified from the canonical ref/index/worktree plus durable intent and fence: expected means not promoted, proposed means recover materialization, and any third state is explicit recovery conflict/divergence. No auxiliary ref is treated as atomic proof.
32. User Git status configuration cannot hide staged, unstaged, or untracked canonical changes from preflight.
33. Existing ignored/untracked paths that collide with proposed additions fail before ref movement; materialization never uses force/reset/clean.
34. After non-force two-tree materialization, canonical ref, durable promotion receipt, index tree, tracked diffs, and untracked collision state all match the exact proposed revision.
35. Every `CloneLease` kind used by later Local, Docker, parallel, Society, and solution-space wiring is self-contained: `.git` and its common directory resolve inside the clone, with no hardlinks, alternates, remote, or linked-worktree pointer into canonical.
36. A Local command that runs `git update-ref` inside its candidate changes only the clone; the canonical ref namespace and attempt-journal control root remain byte-for-byte unchanged.
37. After Local child-process or Docker-container quiescence, the host performs a quota-bounded full native handle-relative no-follow walk of the candidate tree against the expected-tree manifest, including deletions and every untracked entry, rejects reparse/mount/multi-link/unsupported/raced objects, and snapshots all regular bytes through retained handles. A pinned credentialless network-disabled parser container receives only that immutable snapshot plus the expected inert blob/tree manifest, reconstructs Git semantics internally, and emits a bounded canonical proposed-tree manifest and content-addressed inert blob set. The host never parses a candidate patch, pack, index, or Git object: a small memory-safe writer validates every path/mode/digest, deterministically writes only loose blob/tree/commit objects, and pins the checkpoint ref without touching canonical HEAD/index/worktree.
38. Docker launch mounts only the private clone and required non-repository runtime inputs; canonical, its Git common directory, and attempt-journal control root are absent from container mounts.
39. When a real Docker daemon is available, a backend canary proves private-clone `git rev-parse`, file edit/delete/untracked creation, quiescence, complete native snapshot, contained parse, and memory-safe object checkpoint construction; Task 3 owns real backend-native model launch and contained verification. When unavailable, Docker mutation is typed-unavailable rather than downgraded.
40. A hard-crash recovery record can identify and quiesce the Local child/session or Docker container before importing/checkpointing its clone; failure to stop it preserves the clone and blocks reuse.
41. Candidate tree walking, snapshot, parser input/output, and object writing enforce wall/idle time, byte/file/depth/path/object limits and reject unsafe, reserved, submodule, symlink, junction, mount, multi-link, unsupported, omitted, malformed, or duplicate manifest entries while preserving evidence.
42. Task 2's public candidate/backend contracts expose no linked `WorktreeLease`; Task 3 and Task 4 own the live-launcher and parallel-path assertions that no model receives one.
43. While promotion owns canonical `index.lock`, a concurrent normal Git checkout/reset/merge is refused without changing canonical files or refs.
44. An injected direct-plumbing ref move that deliberately ignores the index fence produces `post_promotion_divergence`, preserves evidence, and never produces `done`; the evidence report identifies it as outside the cooperative-writer guarantee rather than claiming impossible hostile-Local atomicity.
45. A same-OID branch switch or detach injected immediately before index-fence acquisition is detected by an exact symbolic-`HEAD` recheck under the fence; the stored branch is never moved beneath another checked-out identity.
46. Once the exact ref/index/worktree postconditions and durable `promoted` transition exist, that historical success is monotonic: a crash before TaskState acknowledgement followed by a later cooperative commit still attaches the promotion receipt exactly once, while recording the subsequent canonical revision separately.
47. A poisoned repository/global Git configuration plus candidate `.gitattributes`, tracked hook path, fsmonitor, diff/textconv, filter, merge driver, signing helper, symlink, or submodule cannot execute a host command during snapshot, contained parse, object construction, integrity checks, or materialization; unsupported external-driver attributes fail before ref movement.
48. Raw candidate/acquisition/canonical patch, pack, index, and Git-object parsing or decompression occurs only in a pinned credentialless network-disabled parser container. Host Git is limited to controller-generated, schema-validated minimal loose objects in a sterile shadow store; no candidate-authored bytes become Git syntax, and no candidate-authored command, checkout hook, merge driver, or working-tree filter runs on the host.
49. A crash after deterministic commit-object creation but before create-only ref installation replays with the journaled author/committer/timestamp/message metadata and reproduces the identical commit OID rather than creating an unreachable sibling.
50. Repository-private `$GIT_DIR/info/attributes`, including macros and filter-process rules, is absent from the sterile shadow Git directory used for every attribute-sensitive operation; a goldstone filter there cannot execute during staging or materialization.
51. Every kernel Git command sets `GIT_NO_LAZY_FETCH=1`; shallow, partial, promisor, or locally incomplete **canonical/acquired source** stores fail typed before lease creation, and a missing-promisor-blob canary invokes no transport or credential helper. Kernel-created disposable clones may use only an attested intentional shallow boundary at their exact expected/proposed root with no remote or lazy provider.
52. The quota-bounded exact commit/tree/blob closure required for expected/proposed operation is proven complete by the contained parser and independently revalidated from the canonical manifest before loose-object construction, clone provisioning, staging, integrity inspection, or promotion; any omitted commit parent is represented only by the explicit kernel-owned shallow-root record and never treated as available history.
53. `StagingReceipt` and `PromotionReceipt` are frozen, content-addressed chain nodes; journal replay is idempotent and cannot rewrite a previously issued receipt.
54. A later canonical advance, reconciliation classification, or cleanup warning creates a linked `ReconciliationReceipt`/`CleanupReceipt`; the original `PromotionReceipt` bytes and hash remain unchanged.
55. `terminal_state_persisted=False` keeps an otherwise promoted, acknowledged, and cleanup-complete transaction discoverable until the final `done` snapshot is durable.
56. The kernel never launches Git with canonical `GIT_DIR`: a trusted metadata attestation rejects local config includes, active hooks/helpers, non-`files` ref storage, a packed-only target ref, a packed target OID that disagrees with its authoritative loose same-name ref, alternates, symlink/junction/reparse indirection, and unsafe object/ref/index paths before staging. A matching shadowed packed entry plus the no-follow authoritative loose ref created at cutover is allowed and bound into attestation.
57. A canonical `.git/config` include goldstone and ref/object reparse-point canary cause typed refusal without opening the include target, touching the goldstone, or writing outside the attested common directory.
58. Failpoints on both sides of the single loose-ref lockfile rename prove exact recovery; the plan makes no false multi-ref atomicity claim on Git's `files` backend.
59. A deterministic 1,000-seed state-machine crash matrix covers every attempt/promotion/resource/receipt/state transition and asserts zero false `done`, lost promotion truth, or duplicate canonical promotion; each transition also has at least one real-temp-repository failpoint case.
60. ReceiptStore create/read/replay is content-addressed, no-follow, immutable, durably atomic, and detects missing/corrupt/collision/schema-invalid nodes without trusting a caller object.
61. Null authorization, a bare verification receipt/Boolean, direct legacy promotion, missing/corrupt/cross-transaction/wrong-target review evidence, a non-permitting review decision, or a tournament journal without a fully linked SelectionReceipt all fail before merge/index/ref lock creation and leave canonical ref/index/worktree byte-identical.
62. A valid ordinary policy-skip or semantic review chain and a valid fully linked tournament selection chain authorize only their exact prepared revision; replay against another transaction/revision/spec/policy is refused.
63. Before ref CAS and again under the held index fence immediately before materialization, the kernel opens/attests canonical root plus every changed path and ancestor component with no-follow primitives and stable file/directory identities. A pre-existing or raced symlink, NTFS junction/reparse point, mount escape, unexpected hardlink, ancestor replacement, or path-type change refuses before any write; a canary whose apparently clean tracked path traverses an outside junction leaves the outside goldstone byte-identical. On Windows, and on every platform where directory-handle/identity continuity cannot be proven through Git, a kernel-owned handle-relative no-follow materializer is mandatory; `git read-tree -u`, checkout, and any path-string reopen are forbidden.
64. The complete proposed tree is injective and losslessly representable on the actual canonical filesystem before ref CAS and again under the materialization fence. Reject case-fold aliases, Unicode-normalization aliases, trailing-dot/space aliases, reserved device names, alternate-data-stream or invalid-colon components, invalid/control components, unsupported path/file lengths, and **colliding or drifting** 8.3 mappings. The kernel records and revalidates the complete short-name map through retained handles. A pre-existing one-to-one short alias for the same stable long-name identity is permitted; a proposed or untracked name that resolves through another entry's short alias, two logical names sharing a long/short identity, or any map/identity race is refused. A collision corpus including a benign existing alias and adversarial short-name collisions leaves ref/index/worktree byte-identical except that the benign identity is accepted.
65. Canonical metadata attestation parses and rejects sparse checkout, sparse index, `skip-worktree`, `assume-unchanged`, split index, unmerged stages, intent-to-add, and unknown/unsupported index extensions before lease creation and again before promotion. This wave never normalizes or expands those modes; real-Git canaries prove typed refusal with zero ref/index/worktree change.
66. A `LandingAuthority` revoked or expired before the under-fence loose-ref CAS cannot land even if every persisted receipt passes. Cancellation during lock wait and generation/watchdog races refuse byte-identically; only recovery of a durably proven already-moved exact ref may finish that same consistency transaction without fresh authority.
67. Canonical raw-object capture, contained exact-object closure traversal, snapshot/candidate/verifier manifest construction, contained pack parsing/indexing/extraction, and memory-safe loose-object writing share authority-bound wall/idle time, object-count, pack/disk, per-object and aggregate inflated-byte, tree-entry/depth/path/file-count, and output quotas. They copy only the minimal exact commit/tree/blob closure needed for the pinned revision, not arbitrary reachable history, and install the expected/proposed commit as an explicit intentional shallow root in disposable repositories. Local decompression/object-graph/tree-depth/history bombs fail typed with process-tree kill and receipted external cleanup before model or canonical mutation.
68. After candidate quiescence and before parser start, a quota-bounded full native handle-relative walk rejects every symlink, junction, reparse point, mount, unsupported type, identity race, and multi-link file; it derives changes itself against the immutable expected-tree manifest, including deletion and untracked discovery, then copies only through retained handles into an immutable external blob manifest. Parser containers mount that snapshot, never the live candidate. Omitted-change, deletion, untracked, quota, raced outside-junction, and outside-hardlink canaries prove completeness and that no external goldstone byte is read or changed.
69. Corrupt/malicious canonical loose objects or packs are raw-snapshotted through handles and parsed/decompressed only in the same pinned networkless parser tier. Its canonical blob/tree manifest is the sole source for the external source object store; host Git never receives raw canonical or acquisition packs. A malformed-pack/parser-exploit canary kills the parser resource, preserves the target byte-for-byte, and cannot create a host process, object, ref, or network event.
70. Canonical index input supports only DIRC v2 ordinary entries plus the standard `TREE` cache-tree extension. The strict codec bounds and validates `TREE` syntax, treats it as derived non-authority, and recomputes or omits it in the deterministic proposed index. The current live DIRC v2 plus `TREE` fixture passes; v3/v4 input, truncation, count/path/OID inconsistency, extension duplication, unknown required extensions, split/sparse state, or entry-tree mismatch refuses with zero ref/index/worktree mutation.
71. Standard `objects/info/packs`, `multi-pack-index`, commit-graph, `.rev`, and `.mtimes` files in the live canonical store are bounded, type-checked derived accelerators, never object authority. The retained-handle walker records their identities/digests for drift detection but derives closure only from paired raw `.idx`/`.pack` and loose-object bytes inside the networkless parser. Missing accelerators are harmless; malformed, raced, path-escaping, or inconsistently paired sidecars are ignored only after safe bounded capture or cause typed refusal according to the closed policy, and are never passed to host Git. Current-store plus corrupt-sidecar canaries prove identical canonical closure and zero host process/network/write effects.
72. The live repository's SHA-1 object format is never treated as collision-resistant identity. Parser and writer bind every raw payload and canonical `type length\0payload` frame to SHA-256, maintain an injective map from each Git SHA-1 OID to exactly one strong digest and exact byte sequence, and derive the Git OID through a pinned collision-detecting SHA1DC implementation sealed in the runtime. Before reusing an existing loose OID, the native writer safely decompresses it only in the parser tier and requires exact framed-byte plus SHA-256 equality. A duplicate OID with different bytes/strong digest, any SHA1DC alarm, or Git-OID/strong-digest drift fails closed. SHAttered/precomputed collision fixtures and a synthetic duplicate-OID manifest cannot alter a ref, index, or existing object.
73. The normal canonical `.git` may retain registered linked worktrees owned by the user. The live `.git/worktrees/test-suite-reduction` registration is captured as bounded opaque regular-file metadata without following its external `gitdir`; its `HEAD` proves it is detached and not a second checkout of the target branch. Registry bytes/identities are double-read under the fence and bound into attestation, while any same-target-branch registration, mutation, prune/GC/ref race, reparse, malformed entry, or unknown live child causes retry/refusal. The kernel never deletes, moves, repairs, enters, snapshots, or projects the registered checkout.
74. Live inert Git-adjacent metadata is explicit rather than mistaken for authority: quota-bounded ordinary `cursor/**`, `gk/config`, `sg-hook-once-*`, and `sg-reviewed-shas` bytes are hashed as opaque drift evidence and never parsed, copied, projected, or executed; `info/refs` is a derived advertisement and `info/exclude` cannot hide native untracked discovery; regular no-follow `objects/<fanout>/tmp_obj_*` files are unreachable temporary garbage and are left untouched. An unknown authority-like top-level path, type/size/quota violation, alias/reparse/hardlink, or identity race refuses. Real-current-metadata, external-`gitdir` goldstone, wrong-branch registry, oversized tool metadata, raced `tmp_obj`, and poisoned `info/exclude` canaries prove no scope escape, deletion, hidden candidate change, or authority substitution.

Run:

```powershell
$planPath = 'docs/superpowers/plans/2026-07-13-galaxy-r3-transactional-kernel.md'
$redTests = @(python tools/galaxy_plan_manifest.py --plan $planPath --task 2 --kind red-tests)
if ($LASTEXITCODE -ne 0 -or -not $redTests.Count -or @($redTests | Sort-Object -Unique).Count -ne $redTests.Count) { throw 'Task 2 RED manifest extraction failed' }
$unexpectedGreen = @()
foreach ($test in $redTests) {
  if (-not (Test-Path -LiteralPath $test -PathType Leaf) -or (Get-Item -LiteralPath $test).Length -eq 0) { throw "Task 2 RED test was not written: $test" }
  python -m pytest $test --collect-only -q
  if ($LASTEXITCODE -ne 0) { throw "Task 2 RED test does not collect cleanly: $test" }
  python -m pytest $test -q
  if ($LASTEXITCODE -eq 0) { $unexpectedGreen += $test }
}
if ($unexpectedGreen.Count) { throw "Task 2 RED modules unexpectedly passed: $($unexpectedGreen -join ', ')" }
```

Expected: new sterile-staging and fenced-promotion tests fail before production changes.

### Step 2: Define lease and receipt types

Add generic transactional types in `platform_core/runtime/candidate.py`; retain legacy worktree APIs/results in `platform_core/runtime/worktree.py` only as compatibility adapters:

**`StagedRevisionLease`**

- transaction/task/subtask/unique attempt IDs;
- candidate runner kind and process-local cleanup token;
- immutable native candidate-snapshot and parser-output manifest/blob-set digests;
- immutable checkpoint ref/revision;
- expected target revision;
- private staged ref and proposed revision/tree/diff digest;
- immutable `StagingReceipt` ID and object-closure digest;
- JSON-safe `toDict()` that omits the process-local cleanup token.

**Candidate lease contract** in `platform_core/runtime/candidate.py`

Use one frozen `CloneLease` as the only candidate shape: task/subtask/unique attempt IDs, checkout path, expected base revision, runner kind (`local` or `docker`), private candidate branch, canonical repository identity, ownership nonce, and no hardlink/alternate/link to canonical Git metadata. Do not add a new linked-worktree lease to the transactional API. The reusable subtask ID is never a recovery identity. Generic staging consumes only the immutable native snapshot and canonical parser-output manifest/blob set plus exact controller-generated revisions, so it does not care whether the clone bytes originated under the trusted Local or contained Docker runner.

Add generic `CandidateResult` with exact Git truth and keep `WorktreeResult` as a compatibility alias/adapter for legacy callers:

- `entered`, `staged`, `promoted`, `removed`, `error`, `cleanup_error`;
- expected, observed, resulting, and checkpoint revisions;
- candidate-snapshot/parser-manifest/staged-tree digests and recovery refs;
- JSON-safe `toDict()`.

**`AttemptTransactionRecord`** in `platform_core/runtime/attempt_journal.py`

- transaction ID and phase;
- task, subtask, and unique attempt IDs;
- canonical repository identity/root;
- canonical metadata-attestation digest, object format/OID length, and supported ref-backend identity;
- candidate kind, outer clone-lease path, branch, base revision, and ownership nonce;
- deterministic checkpoint/proposal commit identity, message digest, and timestamp seed fixed at lease registration;
- durable role-tagged `RuntimeResourceLease` collection needed to revoke/destroy every credential lease and quiesce every authority watchdog, driver, broker, command sandbox, candidate parser, verifier, source fetch/parser, and state-store worker independently;
- canonical ref name;
- expected, proposed, and verified revisions plus proposed tree/diff digests;
- native snapshot/parser manifest/blob-set paths and digests plus disposable verification-clone identity;
- immutable execution, staging, verification, review/selection, promotion, reconciliation, cleanup, and finalization receipt IDs/digests;
- tournament batch/selection receipt ID, selected winner transaction, and planned per-candidate disposition when applicable;
- observed/resulting revision;
- materialization state, deterministic memory-safe proposed-index artifact/digest, canonical index path, and Git index-fence ownership nonce;
- immutable checkpoint/staged/quarantine/promotion-intent refs; an intent ref preserves evidence but is never treated as proof that the canonical CAS committed;
- independent `task_state_acknowledged`, `terminal_state_persisted`, and `cleanup_complete` booleans; `terminal_state_persisted` starts false for promoted work and flips only after the post-ack `done` snapshot is durable;
- error/reconciliation outcome;
- timestamps and JSON-safe serialization.

Store one record per attempt transaction under the anchor-attested external per-repository controller-state root, never under the checked-out tree, Git common directory, or target `STATE_DIR`. Journal, custom kernel locks, ownership manifests, snapshots, parser outputs, generated object closures, index artifacts, and failpoints all use the external no-follow durable store and are bound into `RecoveryAuthority`. Only unavoidable content-addressed loose objects/private refs and Git's ephemeral standard index/ref lockfiles enter canonical `.git`. Every transition uses the deepest external durable-store primitive. The journal is the crash authority from outer-lease provisioning through exact-revision promotion, TaskState acknowledgement, and artifact cleanup.

The monotonic phase set is `lease_registered -> running -> candidate_checkpointed -> staged_prepared -> verified -> promotion_prepared -> index_fenced -> ref_moved -> materialized -> promoted`, with terminal `rejected`, `cas_refused`, `not_promoted`, `post_promotion_divergence`, and `recovery_conflict` branches. Phase transitions validate required fields and cannot move backward; acknowledgement and cleanup remain independent idempotent axes.

### Step 3: Move transactional control and checkout roots outside the promoted tree

Derive roots from the canonical repository identity:

- external controller root: the anchor-attested per-repository state directory for durable journals, candidate snapshots, parser/blob/tree manifests, deterministic generated-object/index artifacts, custom locks, ownership manifests, receipts, and failpoints;
- external checkout root: a child of that protected root for private candidate and verification clones plus per-attempt runtime projections;
- `<repo-id>` is a stable digest of the normalized Git common directory, preventing cross-repository collisions.

Open roots component-by-component through the anchor-provided external state authority and fail closed unless every controller/checkout/artifact path is outside canonical and its Git common directory. Make roots injectable only for tests. Proposed-tree validation rejects entries under configured repository-relative legacy runtime/control namespaces such as `state/tasks`; changing `.gitignore` cannot authorize overwriting live state. Discover legacy registered worktrees under the old `STATE_DIR/.sc-worktrees`/`.sc-integrations` locations only through the bounded native legacy-snapshot path: safely retire clean ones after identity proof, create immutable recovery checkpoints for dirty ones, and never reuse an in-repository checkout.

Before invoking any external Git process, create a frozen `CanonicalRepositoryAttestation` with a non-Git, native no-follow metadata walker. This first wave supports only a normal canonical `.git` directory (which may contain the explicitly inert linked-worktree registry below), the `files` ref backend, a symbolic `HEAD` naming an existing **loose** branch ref, and an ordinary loose/pack object store. Reject a linked canonical checkout, reftable, a packed-only target ref after the explicit TOFU normalization, shallow/partial/promisor state, alternates, grafts/replacements, local config `include`/`includeIf`, unsafe hooks/helpers/transports/filters, and any symlink, junction, mount escape, or Windows reparse point in `.git`, the common/index/ref/object/pack paths, or existing object fan-out directories. Resolve every path beneath the attested common directory component-by-component with platform no-follow primitives and bind the attestation digest to the transaction. Raw canonical loose-object/pack/index files are quota-bound and copied through retained handles into an immutable external snapshot, then parsed, decompressed, and closure-checked only in the pinned networkless object-parser container. Its canonical relative-path/mode/blob/tree/commit manifest becomes the external source object store. No kernel Git subprocess ever receives canonical `GIT_DIR`, canonical raw objects/packs/index, or canonical local config.

The canonical checkout may coexist with user-owned registrations under `.git/worktrees`. The native walker reads only a bounded closed set of ordinary registry files through retained handles, treats external path strings as inert bytes, and never resolves or follows the registered `gitdir`. It double-reads the registry identity and content under the maintenance fence, binds them to the attestation, and requires every registration's recorded `HEAD` not to name the target branch; detached registrations such as the live `test-suite-reduction` checkout are preserved. Registry drift, a cooperative worktree/ref/GC race, malformed metadata, same-target-branch registration, or an external-target access attempt retries or refuses without pruning or touching the user's worktree.

A closed inert-metadata policy also admits the live bounded regular `cursor/**`, `gk/config`, `sg-hook-once-*`, and `sg-reviewed-shas` surfaces as opaque digest-only drift evidence. They are never parsed, executed, copied into a clone, or accepted as ref/object/config/index authority. `info/refs` is a derived advertisement; `info/exclude` is not consulted because tracked and untracked truth comes from the native full walk; standard loose-object names must be exact hex, while bounded ordinary `objects/<fanout>/tmp_obj_*` files are recorded as unreachable temporary garbage and left untouched. The only kernel-created extra surface is `.git/9to5-tombstones/<transaction-id>` while its exact owner/operation manifest and maintenance fence are live; recovery accepts only journal-bound identities and otherwise refuses it as unknown. Per-surface byte/file/depth quotas, no-follow type/link checks, closed names, and before/after identity equality are mandatory; unknown authority-like metadata or any race refuses instead of deleting user data.

The live object store may contain standard derived accelerators: `objects/info/packs`, `objects/info/multi-pack-index`, commit-graph chain files, `.rev`, and `.mtimes`. They are not closure authority. The native retained-handle walker safely bounds and snapshots their identities/digests only for drift/corruption evidence; the networkless parser derives truth solely from paired raw `.idx`/`.pack` plus loose-object bytes. Missing sidecars do not matter. Malformed, duplicate, raced, escaping, or inconsistent sidecars are handled by the closed safe policy without ever reaching host Git, and corrupt-sidecar canaries must produce the same authoritative closure or a typed refusal with no mutation.

Add one argv-only `SterileGit` runner for the narrow host operations that consume only controller-generated, schema-validated external loose-object stores and private clones. It uses a transaction-owned shadow Git directory, a minimal environment (`GIT_CONFIG_NOSYSTEM=1`, an empty global/local config and attributes file, `GIT_NO_REPLACE_OBJECTS=1`, `GIT_NO_LAZY_FETCH=1`, no prompt/askpass/external diff), explicit safe `-c` overrides (empty hooks path, signing/fsmonitor disabled, no pager), an allowlist of commands/flags, bounded output/time, and never `shell=True`. It never receives canonical or candidate raw Git syntax. `ObjectManifest`, `GitObjectWriter`, and the strict bounded DIRC v2 `GitIndex` codec independently validate duplicate-free canonical paths/modes/OIDs, object format, tree ordering, supported extensions, checksums, and complete closure before any generated bytes enter a Git-readable directory. For the current SHA-1 repository, every object also carries SHA-256 over its raw payload and canonical framed bytes; the pinned runtime's collision-detecting SHA1DC implementation derives the Git OID, and no OID may map to two strong digests or byte strings. Existing same-OID objects are reusable only after contained decompression and exact strong-digest/byte equality.

Attribute and complete-tree policy is computed by memory-safe code over the parser's canonical manifest; repository `.gitattributes` is inert data and cannot configure host behavior. The sole supported transform declaration is the exact safe subset `text eol=lf` with no macro: the affected blob must already contain LF-only canonical bytes, and candidate checkout, verifier checkout, manifest, and final native materialization must all hash identically. This admits the live checkout's `.repo-map.json`/`AGENTS.md` rules. Reject bare/auto/negative `text`, `eol=crlf` or any other `eol`, `ident`, `working-tree-encoding`, `filter`, attribute macros, and every external behavior attribute (`diff`, `merge`). Every private candidate/verifier Git invocation pins `core.autocrlf=false`, `core.safecrlf=true`, an independently generated safe-attribute file containing only validated `text eol=lf` rules, and no ambient transforms; real-current-attributes plus `text`/`eol=crlf`/`ident` attack canaries prove byte parity. `GitObjectWriter` deterministically creates bounded loose blob/tree/commit objects from inert blobs under the external source store, then no-follow create-only copies only already-hashed proposed loose objects into canonical object fan-out before refs make them reachable. `GitIndex` deterministically creates and validates the complete proposed index without invoking Git. `LooseRefStore` performs create-only checkpoint/staged/quarantine refs and the one canonical branch CAS directly with no-follow, exclusive Git-compatible loose lockfiles, fsync, expected-OID comparison, and atomic same-directory replace; it never asks Git to load canonical metadata. Before any working-tree materialization, fail closed on submodules, symlinks, reserved paths, or other entries the native materializer cannot prove safe. Canaries poison system/global/repository config and canonical `info/attributes`, including a long-running filter process, and assert no include target, transport, helper, parser, transform, or host goldstone is touched.

Extend `fsio` with strict durable primitives needed by the kernel: exclusive-create-with-content that never steals an existing owner, and durable atomic file replacement with Windows retry plus directory fsync where supported. Unit-test ownership refusal and injected replace failures before using them for Git's canonical index fence/install.

### Step 4: Add candidate collection and checkpointing

Implement:

- `snapshotCloneTree(lease)`: after its Local child/session or Docker container is quiesced, perform the full bounded native no-follow candidate walk and persist an immutable content-addressed snapshot;
- `parseCandidateSnapshot(snapshot, expected)`: run the pinned networkless parser over only immutable inert inputs and return a canonical proposed-tree/blob manifest plus receipt;
- `stageCandidateSnapshotAgainst(parsed, expected, *, target_ref)`: validate the manifest, use the memory-safe writer to create deterministic loose blob/tree/commit objects, and create the target ref with zero-old-OID semantics;
- `checkpointCandidate(lease) -> CandidateResult`: run snapshot, contained parse, and object-only staging against the lease base and preserve crash/rejection work before checkout removal;
- validation that clone/snapshot/parser/blob/object/index paths, branches, ownership nonces, digests, and repository identities belong to their expected namespaces.

Checkpointing creates the tree/commit from the validated parser manifest with the deterministic object writer and create-only installs the unique ref through `LooseRefStore` before checkout removal. An existing ref at the same SHA is an idempotent retry; an existing ref at any other SHA is an integrity failure and all artifacts remain untouched. Never report recovery success without the native snapshot, parser receipt, manifest/blob-set digests, addressable SHA, and immutable ref. A reusable compatibility branch may move, but it cannot invalidate a prior recovery receipt because later preparation consumes only those immutable artifacts.

`CloneLease` provisioning is uniform for Local, Docker, Society, parallel, and solution-space execution. Before provisioning, require the parser-proven minimal expected commit/tree/blob closure from the external source store and its explicit intentional shallow-root record. `GitObjectWriter` creates a fresh private repository's bounded loose objects and deterministic index from that canonical manifest; no pack import, alternate, hardlink, remote, lazy provider, or absolute canonical path exists. The sterile runner may check out only those controller-generated validated objects on a private candidate branch inside the selected runner tier. The result has a locally complete operational tree; history beyond the attested boundary is explicitly unavailable rather than silently missing. Verify that both `.git` and `git rev-parse --git-common-dir` resolve inside the clone. Local sets this clone as its working directory; Docker mounts this clone only. The legacy Worktree preference selects the Local runner inside this safer clone representation and records the effective landing backend as `clone`.

After either a Docker container or trusted-Local child/session is fully quiesced, the host first creates an immutable **candidate file snapshot** with the native handle-relative no-follow copier. It performs a quota-bounded full walk against the immutable expected-tree manifest, derives every modification/deletion/untracked path itself, retains/revalidates every ancestor/file identity, rejects symlink/junction/reparse/mount/unsupported types and every multi-link file, reads bytes only through retained handles, and writes a content-addressed sterile blob tree/manifest outside the clone. Candidate Git/status/index/config is not an input. Omitted-change, deletion, untracked, quota, raced-junction, and outside-hardlink goldstones prove completeness and remain unread/byte-identical. The live candidate tree is never bind-mounted into a parser.

The parser then runs inside a fresh pinned credentialless, network-disabled hardened container with only that immutable sterile snapshot and the expected canonical inert blob/tree manifest. It never sees live candidate/canonical paths or invokes Git against candidate repository metadata. Inside its disposable namespace it reconstructs the expected tree, overlays the complete snapshot, applies bounded Git semantics, and emits only a strict canonical relative-path/mode/content-digest proposed-tree manifest, content-addressed inert blob set, normalized diff digest, and receipt. Candidate `.git`, local config, `info/attributes`, hooks, filters, fsmonitor, objects, refs, live paths, and control roots are absent. Host captures bounded framed output to the external durable store, independently validates every byte/path/mode/digest/quota, and uses the memory-safe writer to create deterministic loose objects; it never feeds parser/model bytes to host Git as patch/pack/index/object syntax. Pre-parse canaries poison local config, filter-process, fsmonitor, attributes, object paths, hooks, malformed pack/patch payloads, junctions, and hardlinks and assert no host goldstone, process, network, object, or external path is touched. Any snapshot/parse/write failure preserves clone and immutable evidence; canonical HEAD/index/worktree never move.

Before candidate commands launch, persist the ready outer clone lease in the attempt journal. Before provisioning any same-SID lease, scan older unacknowledged lease records: acquire recovery ownership, quiesce any registered Local/Docker child resource, checkpoint its dirty tree with the create-only rule, and only then clean/reuse paths. If ownership or quiescence cannot be proven, preserve the checkout/ref, record recovery failure, and refuse reuse. A hard process death is not allowed to turn an uncommitted candidate clone into an invisible orphan.

### Step 5: Prepare an immutable staged revision without touching canonical files

`prepareStagedRevision(candidate, expected_target_revision=None)` must:

1. validate candidate/snapshot/parser/blob-manifest identity and checkpoint truth;
2. select the explicit expected SHA or candidate base SHA;
3. require the parser receipt to bind that exact expected tree and independently revalidate the immutable proposed manifest/blob set;
4. reject stale expected, missing/deleted/duplicate/unsafe paths, digest drift, unsupported modes, or incomplete closure before object creation;
5. use `GitObjectWriter` to policy-validate the complete tree and deterministically write the exact loose blob/tree objects plus direct-child commit with sanitized author/committer identity, exact timestamp/timezone, and message digest durably fixed in the journal before staging, so replay produces the same SHA;
7. pin it under a unique create-only `refs/9to5/staged/<transaction-id>` ref;
8. compute proposed commit/tree/diff/object-closure/parser/index/policy digests, atomically persist a frozen content-addressed `StagingReceipt`, and return a `StagedRevisionLease` linked to that receipt;
9. leave canonical HEAD, index, and files untouched.

On snapshot/manifest conflict or setup failure, preserve the candidate checkpoint, clone, snapshot, parser receipt, and blob/tree manifest and return precise failure truth. No merge driver, rebase, checkout hook, filter, or candidate branch executes on the host. A test deliberately moves/reuses the candidate branch and changes its Git config after snapshot; staged output must remain identical because only the immutable snapshot/parser artifacts are inputs.

The private staged ref makes the proposed commit genuinely addressable. After successful promotion it can be deleted only after the durable promoted record exists because canonical points at the commit. Rejection first create-only installs a unique `refs/9to5/quarantine/...` ref through `LooseRefStore` and durably verifies it, then independently deletes the private staged ref; a crash may leave both safe refs but never neither. If either operation fails, retain the original ref/artifacts. A receipt must never claim a recoverable proposed SHA that only survives in a reflog.

### Step 6: Seal staged-revision integrity

`stagedRevisionIntact(lease)` returns true only when:

- the staged ref equals `proposed_revision`;
- the proposed commit has exactly one parent equal to `expected_target_revision`;
- `proposed^{tree}` equals the recorded tree digest;
- the memory-safe canonical manifest comparison of expected and proposed equals the recorded proposal diff digest;
- the durable source snapshot, parser receipt, and canonical manifest/blob set still equal their recorded digests;
- complete-tree reserved-path/external-driver/submodule/symlink policy still passes.

Check integrity immediately before and immediately after contained verification, and again before promotion. Verification receives only a copied no-link clone of this revision; it never receives the sterile index, staged ref namespace, canonical common directory, or control root.

### Step 7: Promote with a durable journal, Git index writer fence, and one attested loose-ref compare-and-swap

`promoteStagedRevision(lease, authorization, landing_authority)` first calls `validatePromotionAuthorization()` and `validateLandingAuthority()` and re-reads the complete bound receipt chain plus transaction journal from the external store. The live authority must exact-match transaction/task, prepared SHA/tree/receipts, watchdog, deadline, controller generation, and active run admission. These validations occur before integrity checks, custom/index/ref lock acquisition, intent-ref creation, or any canonical write; failure returns typed refusal with canonical byte-identical. The legacy two-argument signature is removed or a fail-closed compatibility shim. Recovery of a durably proven already-moved ref uses a separate `recoverPromotionConsistency(recovery_authority, journal_record)` API that cannot choose or CAS a ref. Promotion must then:

1. reject if staged-revision integrity is lost;
2. acquire the external no-follow custom merge lock from the anchor-attested controller root;
3. revalidate the frozen canonical-metadata attestation, parse no-follow `HEAD`, and require the exact symbolic loose branch ref captured at preparation; detached/packed-only/reftable state fails closed;
4. take the canonical index path directly from the attestation, construct the complete proposed index with the strict memory-safe `GitIndex` codec under the external controller root, and record its digest; this external artifact is the durable source, not something assumed atomically renameable across volumes;
5. require canonical ref to equal `expected_target_revision`, parse the real canonical index with the bounded memory-safe codec, require its complete manifest/tree digest to equal expected, and establish byte-level cleanliness with a full native no-follow worktree walk against the expected manifest plus complete untracked enumeration; no user-configured Git status/diff/attribute behavior participates;
6. compare expected/proposed canonical manifests; reject every existing untracked path or ancestor/descendant collision and every reserved runtime/control namespace; then run complete-tree policy and actual-filesystem injectivity/round-trip scans for case, Unicode, trailing-dot/space, device, ADS/colon, invalid/control component, path-length, and 8.3 long/short-name identity collisions or drift. Revalidate and permit only stable one-to-one aliases of their own existing long-name entry. Open and retain no-follow handles/identities for canonical root plus every changed ancestor. Create-only install the already-validated proposed loose objects into canonical fan-out through retained handles and re-hash them; they remain unreachable if later admission fails. Every other failure occurs before intent or canonical ref mutation;
7. prove from the parser/object-writer manifest that proposed is the deterministic direct child of expected;
8. create a unique immutable `refs/9to5/promotion-intents/<transaction-id>` ref through `LooseRefStore`, then durably write a `promotion_prepared` record containing expected, proposed, verified and review/selection receipt IDs, the intent ref, canonical branch/index paths, proposed-index digest, attestation digest, and a fresh index-fence ownership nonce. The intent preserves evidence and is explicitly **not** proof that the canonical ref moved;
9. atomically create the canonical Git `<index-path>.lock` with exclusive-create semantics, write and fsync a small ownership goldstone containing transaction ID plus nonce, then durably transition to `index_fenced`; an existing or unverifiable lock fails closed and is never stolen;
10. while the standard Git index lock blocks cooperative checkout/reset/merge/commit writers, revalidate the attestation, every retained directory handle/identity, complete-tree policy and actual-filesystem representability, and the live `LandingAuthority`; parse no-follow `HEAD`, require the exact canonical ref name captured in step 3, then re-read that loose ref's OID, parse the real index with `GitIndex`, and rerun the full native expected-manifest/untracked checks. A branch switch, detach, metadata/path drift, authority revocation/expiry, watchdog/generation change, or other pre-CAS change closes as `cas_refused`/`not_promoted` and releases only provably owned locks;
11. acquire the canonical loose branch `<ref>.lock` by exclusive no-follow create, re-read the ref under that lock and require `expected`, revalidate `LandingAuthority` once more immediately before the commit point, write only `proposed\n` to the lockfile while ownership metadata remains separately durable in the journal, fsync the lockfile, then atomically replace the one branch ref and fsync its directory. This single-ref lockfile rename is the CAS; no multi-ref atomicity or auxiliary-witness claim is made;
12. if lock acquisition or the under-lock expected-OID check refuses, durably close as `cas_refused`, preserve checkpoint/staged/intent refs and snapshot/parser evidence, and remove only owned proposed-index/fence artifacts;
13. after the branch lockfile rename, durably transition the journal to `ref_moved`. A crash between steps 11 and 13 is reconciled from the canonical ref plus the still-owned index fence and proposed-index artifact;
14. recheck the already-proven complete-tree policy and actual-filesystem mapping under the retained handles and revalidate the proposed manifest/index digest. Compute one deterministic expected-to-proposed operation manifest: validate every deletion subtree contains no untracked/ignored descendant; identify maximal wholly deleted subtrees; journal exact old identities/blob digests and owned quarantine destinations; and rename each exact deleted file or maximal subtree, through retained handles, into a transaction-owned no-follow quarantine below canonical `.git/9to5-tombstones/<transaction-id>` on the same repository volume. Tombstones are therefore never visible to working-tree untracked enumeration. Create missing directories parents-first through the closest retained ancestor with exact identities/modes, and write replacements/additions through bounded exclusive same-directory temporary siblings. Fsync each file plus every affected worktree/quarantine parent, re-open/re-hash through retained handles, then remove only the exact journal-owned quarantine after durable exact-proposed truth. A crash resumes idempotently from the operation manifest: an exact owned temp/tombstone/new-directory identity may be completed or restored, while a nonempty deletion subtree, unknown child, directory↔file replacement race, or identity/type drift becomes a fenced conflict and never triggers recursive discovery or cleanup. Expected blobs remain in the sealed object store, so verified rollback can rematerialize a deleted tracked path without guessing. On Windows this handle-relative materializer is mandatory and explicitly rejects junction/reparse races, case/Unicode/trailing-dot-or-space/device/ADS aliases, 8.3 collisions/map drift, and path-length surprises while permitting only stable one-to-one aliases of their own existing long-name identity. File deletion, whole-directory deletion, directory↔file replacement, nested-directory creation, nonempty-directory/untracked-descendant refusal, tombstone invisibility, replacement race, and crash-before/after-quarantine canaries must leave every outside goldstone unchanged. Never use `read-tree -u`, `reset --hard`, checkout, forced checkout, `git clean`, unowned recursive delete, a merge driver, a candidate hook, path-string reopen, or an unsanitized Git environment;
15. before installing the index, require canonical ref still equals proposed, the proposed-index codec/manifest/tree digest equals the proposed tree, the full native worktree comparison is exact, and all untracked collision checks remain clear;
16. while the ownership goldstone still fences cooperative writers, create a distinct exclusive transaction-nonce sibling in the canonical index directory (never the occupied standard `index.lock`), durably journal its exact name/identity, copy the external proposed-index bytes through retained handles, fsync, reopen, hash, and codec/manifest-verify it, then atomically replace canonical `index` from that same-directory sibling and fsync the directory before transitioning to `materialized`. Recovery removes or resumes only an exact journal-owned sibling and works when the external controller root is on another volume; crashes before sibling creation, after partial/full copy, and on either side of replace are canaries;
17. require canonical ref to equal proposed, parse/re-hash the newly installed canonical index as the proposed manifest/tree, require the native tracked comparison to be exact, and require full untracked collision checks to remain clear;
18. construct, persist, and re-read the frozen content-addressed `PromotionReceipt` linked to exact staging/verification/review evidence while the journal is still `materialized`; then atomically transition the journal to `promoted` with that receipt ID. A receipt file alone is non-authoritative, while a `promoted` journal transition is invalid without the already-verified receipt. Failpoints on both sides prove idempotent reconstruction without a receiptless promotion;
19. remove the provably owned goldstone, release the lock, then idempotently remove or policy-retain candidate/verification clones, external snapshot/parser/object/runtime artifacts, and the now-redundant private staged ref;
20. persist and re-read an immutable `CleanupReceipt` listing every removed/retained/failed artifact and warning, then set journal `cleanup_complete=True` only when that receipt proves every artifact reached an allowed terminal disposition. A receipt alone is non-authoritative; a transient failure leaves the flag false for recovery. Cleanup warnings never rewrite promotion truth.

The custom repository lock serializes kernel writers. Git's standard index and loose-ref lock names fence cooperative porcelain, while the no-follow under-lock expected-OID check plus one atomic same-directory loose-ref rename arbitrate the exact expected-to-proposed move. The kernel never loads canonical Git config and deliberately supports only an attested loose `files` ref in this wave. Direct plumbing/filesystem writes that intentionally ignore the custom/index/ref locks remain outside the stated cooperative-writer boundary; postconditions detect and quarantine divergence. The intent ref proves only prepared intent. Landing truth comes from the canonical ref/index/worktree, durable phase, and immutable promotion/reconciliation receipts. A stale SHA never rebases implicitly.

The ref CAS, worktree materialization, and canonical-index installation are explicit recoverable phases, not a fictitious single filesystem transaction. If ref movement succeeds but materialization, index install, or caller persistence fails, the durable journal plus owned index goldstone/proposed-index metadata provide enough information to reconcile or fail closed without a destructive reset. Terminal `done` still waits for a durable `promoted` record and exact clean materialization.

### Step 8: Reconcile interrupted promotion

`reconcileAttempts(repo)` scans every durable record whose promotion is unresolved **or** whose `task_state_acknowledged`, `terminal_state_persisted`, or `cleanup_complete` flag is false before new candidate provisioning and during runtime startup. Terminal `promoted` records are therefore acknowledged/finalized/cleaned too, not skipped and never downgraded. A promoted record with ack true but terminal-state false is still mandatory recovery work even when cleanup is already complete. Lease recovery acquires a per-attempt recovery-ownership lock; every unresolved canonical-ref classification or materialization acquires the same `_mergeLockPath` used by live promotion and refuses a record still owned by a live promoter. It inspects `<index-path>.lock` without removing it unless its transaction ID and nonce exactly match the durable record; unknown locks always block:

- a registered stale outer clone lease is recovery-owned, its inner process/container is quiesced, and its dirty tree is exported/checkpointed before any same-SID reuse; inability to prove quiescence preserves it and records conflict;
- a record already durably `promoted` remains immutable historical success: attach its exact receipt to TaskState once even if canonical later advanced, record `subsequent_canonical_revision` as separate observation, and retry only pending-state persistence, acknowledgement, final-`done` persistence, and cleanup; never reclassify it as `post_promotion_divergence`, launch another model attempt, or revoke `done`;
- for a pre-`ref_moved` record, current canonical ref equals expected and canonical index/worktree are exactly expected -> the loose-ref CAS did not remain visible; remove only provably owned ref/index lock artifacts, mark `not_promoted`, and retain checkpoint/staged/intent refs plus snapshot/parser evidence. Never promote implicitly from intent;
- current canonical ref equals proposed and canonical index/worktree already exactly proposed -> validate or reconstruct the immutable promotion receipt, mark `promoted_recovered`, and remove only provably owned stale lock/temp artifacts;
- current canonical ref equals proposed, canonical index/worktree are exactly expected, and the recorded proposed-index artifact/codec/manifest digest is intact -> retain/reacquire the owned index fence, retry only the same native expected-to-proposed manifest materialization, atomically install that index, validate, persist receipt, then mark `promoted_recovered`;
- current canonical ref equals proposed, worktree is exactly proposed, and the intact proposed-index artifact is valid while canonical index is expected -> install that index under the owned fence, validate, persist receipt, and mark `promoted_recovered`;
- any journal-owned same-parent materialization temp, deletion tombstone, created-directory identity, or canonical-index sibling is reconciled against the immutable operation manifest before classifying the tree: exact partial state is completed idempotently, exact expected state is safely retried, and an unknown/nonempty/replaced identity remains fenced conflict. Recovery never recursively removes a directory or follows a path to discover ownership;
- for a pre-`promoted` record, current canonical ref is neither expected nor proposed, or ref equals expected while index/worktree show proposed/partial state -> mark `recovery_conflict`/`post_promotion_divergence`, never overwrite the later writer, preserve evidence and the safety fence, and refuse `done`;
- an unknown ref/index lock owner, changed attestation, wrong proposed-index artifact/codec/manifest digest, missing required receipt, or unprovable partial materialization -> preserve all refs/artifacts and locks, emit an immutable `ReconciliationReceipt`, notify, and refuse destructive reset or new promotion.

Fault-injection seams cover death after durable intent, before and after loose-ref lockfile creation, immediately before and after its atomic rename, before the `ref_moved` journal write, during native manifest materialization, after materialization but before proposed-index install, after index install, before/after PromotionReceipt persistence and promoted-phase transition, before/after CleanupReceipt persistence and `cleanup_complete`, before the pending TaskState save, before journal acknowledgement, and after acknowledgement but before the final `done` save/terminal flag. Concurrency tests (a) switch to a same-OID branch immediately before fence acquisition and prove the exact under-fence no-follow `HEAD` check refuses it, (b) hold the fence while normal Git porcelain attempts checkout/reset/merge and prove those writers fail without mutation, (c) inject a deliberately noncooperative direct-ref move before durable promotion and prove divergence is detected and never acknowledged as `done`, and (d) advance canonical cooperatively after durable `promoted` but before simulated restart and prove historical promotion acknowledgement remains monotonic. Reconciliation emits append-only receipts; absence of a process-local return value never erases landing truth.

Every record carries stable task/subtask/attempt identifiers. The orchestration reconciliation seam attaches a recovered receipt to TaskState idempotently by transaction ID and persists `promotion_persistence_pending`; only then does it durably flip `task_state_acknowledged`, after which a second atomic state save may set `done`. A crash between those writes simply replays the missing acknowledgement/final-state transition without a model launch. Cleanup is likewise retried until durable `cleanup_complete`. A recovered clean promotion dominates later attempt outcomes; `not_promoted` or `recovery_conflict` can never become `done`. Records whose TaskState is not currently loaded remain visible in the journal/health surface rather than being deleted.

### Step 9: Reject without canonical mutation

`rejectStagedRevision(lease)` first creates and verifies the unique quarantine ref with create-only `LooseRefStore` semantics, durably records that safe copy, and only then independently retires the staged ref; a crash-safe replay tolerates both refs. It removes disposable candidate/verification clones afterward. It retains the native snapshot, parser receipt, canonical blob/tree manifest, candidate checkpoint, and quarantine ref as addressable recovery evidence and verifies objects by OID with the memory-safe writer/manifest reader before reporting success. It never checks out, resets, merges, or edits canonical state. A later retention policy may garbage-collect acknowledged quarantine refs/artifacts; this kernel does not silently discard them.

### Step 10: Make clone landing uniform across Local, Worktree preference, and Docker

Add `CloneEnvironment.handleFromLease(lease, base_dir, expected_target_revision=None)` so normal, parallel, and tournament paths construct the same truthful handle.

Implement hooks:

- `provision()` uses fail-closed `enterCloneLease(runner_kind=...)` for every model-executed attempt;
- `prepareChanges()` delegates to `prepareStagedRevision()`, then creates a private no-checkout verification repository from the validated proposed loose-object manifest with an explicit proposed shallow root; it has no remotes/absolute paths and returns that path, runner kind, proposed revision, staged ref, snapshot/manifest digests, and process-local lease token;
- `preparedChangesIntact()` delegates to staged-revision integrity;
- `completeChanges(promote=True, authorization=..., landing_authority=...)` forwards both persisted evidence and the live non-serializable authority to deepest-boundary ReceiptStore/journal/liveness validation and promotes only after both pass;
- `completeChanges(promote=False, authorization=None)` rejects without requiring acceptance evidence;
- `checkpointRecovery()` checkpoints before teardown.

New `CloneEnvironment` provisions `CloneLease` for trusted Local and contained Docker landing, exports the quiesced clone into sterile object-only staging, prepares the staged revision/verification clone, and owns clone recovery/cleanup. `WorktreeEnvironment` becomes a compatibility facade for the user's historical backend preference: it delegates to `CloneEnvironment(runner_kind="local")`, reports requested-versus-effective backend truth, and never exposes or provisions a linked worktree for command execution. No new linked-worktree type participates in the transactional kernel. Factor shared staged hooks into a narrow helper/mixin only if it avoids duplicated authority logic; there remains one router preparation/completion path.

Verification-clone construction never checks out proposed files on the host for **any** candidate origin. `GitObjectWriter` creates a bounded private loose-object store and deterministic index from the validated proposed commit/tree/blob manifest plus explicit proposed shallow-root record; it has no pack import, hardlinks, alternates, remotes, or source paths, and the worktree remains empty. A fresh credentialless hardened verification container performs the first checkout and every acceptance command. Re-hash the copied object graph/ref/shallow boundary and prove the clone's Git/common directory is private before the container starts.

`LocalEnvironment` and the split-plane `DockerEnvironment` coordinator are inner execution surfaces only. Completion proves every registered role-tagged resource quiescent and flushes the private clone, but no inner surface receives a linked worktree, creates canonical refs, imports host objects, stages proposed revisions, or promotes. `CloneEnvironment` performs sterile host-side export/staging actions only after complete resource quiescence.

As a legacy low-level backstop, a Remote handle remains landing-required and its staged-prepare hook returns typed unsupported without teardown or a false collection claim. Production mutating wiring never reaches that state: it refuses Remote immediately after selection, before provisioning either an outer lease or a remote runtime.

### Step 11: Verify and commit

Run:

```powershell
python -m pytest tests/execution/test_worktree.py tests/execution/test_execution_worktree.py tests/execution/test_launch_guard.py tests/execution/test_fsio.py tests/execution/test_candidate.py tests/execution/test_execution_clone.py tests/execution/test_sterile_git.py tests/execution/test_canonical_repo.py tests/execution/test_loose_refs.py tests/execution/test_staged_revision.py tests/execution/test_attempt_journal.py tests/execution/test_attempt_crash_matrix.py tests/execution/test_receipts.py tests/execution/test_promotion_authorization.py -q
if ($LASTEXITCODE -ne 0) { throw 'Task 2 focused tests failed' }
python -m pytest tests/execution/test_launch_guard.py tests/execution/test_executor_stream.py tests/execution/test_claude_sdk_bridge.py tests/execution/test_provider_probe.py tests/execution/test_verifier.py tests/review/test_verification.py tests/evolution/test_evolution_evolver.py tests/platform/test_health_collect.py -q
if ($LASTEXITCODE -ne 0) { throw 'Task 2 intermediate launch-embargo regression suite failed' }
python tools/dev.py lint platform_core/runtime/worktree.py platform_core/runtime/candidate.py platform_core/runtime/sterile_git.py platform_core/runtime/canonical_repo.py platform_core/runtime/loose_refs.py platform_core/runtime/receipts.py platform_core/execution/backends/worktree.py platform_core/execution/backends/clone.py
if ($LASTEXITCODE -ne 0) { throw 'Task 2 lint failed' }
$devToolRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) '9to5\galaxy-dev-tools'
$devPython = (python tools/bootstrap_galaxy_dev_tools.py --lock bootstrap/galaxy_launcher/dev_tools.lock.json --root $devToolRoot --offline --only-binary --require-hashes --print-python-only).Trim()
if ($LASTEXITCODE -ne 0 -or -not $devPython -or -not (Test-Path -LiteralPath $devPython -PathType Leaf)) { throw 'Pinned GALAXY development typechecker is unavailable' }
$mypyVersion = (& $devPython -m mypy --version).Trim()
if ($LASTEXITCODE -ne 0 -or $mypyVersion -notmatch '^mypy 2\.3\.0(?: |$)') { throw "Unexpected pinned mypy version: $mypyVersion" }
& $devPython tools/dev.py typecheck platform_core/runtime/worktree.py platform_core/runtime/candidate.py platform_core/runtime/sterile_git.py platform_core/runtime/canonical_repo.py platform_core/runtime/loose_refs.py platform_core/runtime/receipts.py platform_core/execution/backends/worktree.py platform_core/execution/backends/clone.py
if ($LASTEXITCODE -ne 0) { throw 'Task 2 typecheck failed' }
$planPath = 'docs/superpowers/plans/2026-07-13-galaxy-r3-transactional-kernel.md'
function Get-GalaxyManifest { param([int[]]$Tasks, [string]$Kind)
  $taskArgs = @(); foreach ($task in $Tasks) { $taskArgs += @('--task', [string]$task) }
  $paths = @(python tools/galaxy_plan_manifest.py --plan $planPath @taskArgs --kind $Kind)
  if ($LASTEXITCODE -ne 0 -or -not $paths.Count -or @($paths | Where-Object { -not $_ }).Count) { throw "GALAXY manifest extraction failed for $Kind" }
  if (@($paths | Sort-Object -Unique).Count -ne $paths.Count) { throw "GALAXY manifest emitted duplicate $Kind paths" }
  return $paths
}
$manifestTests = @(Get-GalaxyManifest @(1,2) tests)
$manifestPython = @(Get-GalaxyManifest @(1,2) python)
$manifestProduction = @(Get-GalaxyManifest @(1,2) production-python)
function Invoke-GalaxyChunks { param([string[]]$Paths, [string]$Mode, [string]$Label)
  for ($offset = 0; $offset -lt $Paths.Count; $offset += 40) {
    $last = [Math]::Min($offset + 39, $Paths.Count - 1); $chunk = @($Paths[$offset..$last])
    switch ($Mode) { 'pytest' { python -m pytest @chunk -q } 'compile' { python -m compileall @chunk } 'lint' { python tools/dev.py lint @chunk } 'typecheck' { & $devPython tools/dev.py typecheck @chunk } default { throw "Unknown GALAXY check mode: $Mode" } }
    if ($LASTEXITCODE -ne 0) { throw "$Label failed for manifest chunk $offset..$last" }
  }
}
Invoke-GalaxyChunks $manifestTests pytest 'Task 1 + Task 2 complete manifest tests'
Invoke-GalaxyChunks $manifestPython compile 'Task 1 + Task 2 complete manifest compile'
Invoke-GalaxyChunks $manifestPython lint 'Task 1 + Task 2 complete manifest lint'
Invoke-GalaxyChunks $manifestProduction typecheck 'Task 1 + Task 2 complete manifest typecheck'
git diff --check
if ($LASTEXITCODE -ne 0) { throw 'Task 2 diff check failed' }
```

Commit:

```powershell
$cachedPaths = @(git diff --cached --name-only)
if ($LASTEXITCODE -ne 0 -or $cachedPaths.Count) { throw "Pre-existing staged paths; preserve them and stop: $($cachedPaths -join ', ')" }
$planPath = 'docs/superpowers/plans/2026-07-13-galaxy-r3-transactional-kernel.md'
$stageAllowlist = @(python tools/galaxy_plan_manifest.py --plan $planPath --task 2 --kind all)
if ($LASTEXITCODE -ne 0 -or -not $stageAllowlist.Count) { throw 'Task 2 manifest extraction failed' }
$requiredChanges = @(python tools/galaxy_plan_manifest.py --plan $planPath --task 2 --kind required-changes)
if ($LASTEXITCODE -ne 0 -or -not $requiredChanges.Count) { throw 'Task 2 required-change manifest extraction failed' }
$testPaths = @(python tools/galaxy_plan_manifest.py --plan $planPath --task 2 --kind tests)
if ($LASTEXITCODE -ne 0 -or -not $testPaths.Count) { throw 'Task 2 test manifest extraction failed' }
$pinnedPowerShell = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
$singularityClient = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) '9to5\singularity\bin\singularity-admin-client.ps1'
if (-not (Test-Path -LiteralPath $pinnedPowerShell -PathType Leaf) -or -not (Test-Path -LiteralPath $singularityClient -PathType Leaf)) { throw 'Installed inactive Singularity service/client is unavailable' }
function Invoke-SingularityRecoveryAdmin { & $pinnedPowerShell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $singularityClient --request-only --require-server-validated-client-digest @args }
function Invoke-SingularityAdmin { Invoke-SingularityRecoveryAdmin @args }
Invoke-SingularityAdmin verify-self --require-fresh-service-host --require-os-pinned-digest --require-protected-acl --require-inactive-generation --require-closed-launch-record
if ($LASTEXITCODE -ne 0) { throw 'Installed inactive Singularity service failed self-verification' }
function Resolve-StrictLocalAbsolutePath { param([string]$RawPath)
  if ([string]::IsNullOrWhiteSpace($RawPath) -or $RawPath -notmatch '^[A-Za-z]:[\\/]' -or $RawPath.StartsWith('\\?\') -or $RawPath.StartsWith('\\.\') -or $RawPath.StartsWith('//?/') -or $RawPath.StartsWith('//./')) { throw "Not a strict local drive-absolute path: $RawPath" }
  $full = [System.IO.Path]::GetFullPath($RawPath); if ($full -notmatch '^[A-Za-z]:\\') { throw "Path normalization lost drive-absolute form: $RawPath" }; return $full
}
$repoRoot = Resolve-StrictLocalAbsolutePath (Get-Location).Path
function Complete-SingularityTopLevelSlot { param([string]$Repository)
  function Invoke-SingularityAdmin { Invoke-SingularityRecoveryAdmin @args }
  $currentPurpose=(Invoke-SingularityAdmin resolve-current-top-level-transition --repo $Repository --repository-global-all-generations --read-only --require-unique-live-slot --print-none-or-bound-purpose-receipt).Trim();if($LASTEXITCODE-ne 0-or-not$currentPurpose){throw 'Pure slot lookup failed; settlement is forbidden'};if($currentPurpose-eq'none'){return 'none'};if($currentPurpose-notmatch'^purpose_[0-9a-f]{64}$'){throw 'Invalid occupied purpose receipt'}
  $slotResult=(Invoke-SingularityAdmin observe-top-level-transition --repo $Repository --repository-global-all-generations --bound-purpose-receipt $currentPurpose --read-only --include-owner-lease-and-fencing-generation --require-latest-journal-live-state-and-ingress --closed-terminal-map singularity-top-level-terminal-v1 --print-owner-state-recovery-pending-or-terminal-observation).Trim();if($LASTEXITCODE-ne 0-or-not$slotResult){throw 'Occupied slot state is unknown'};if($slotResult-in@('active_owned_elsewhere','owner_liveness_unknown')){throw "Live or unproven slot owner blocks takeover: $currentPurpose"};if($slotResult-eq'recovery_pending'){throw "Slot recovery remains pending: $currentPurpose"}
  if($slotResult-match'^recoverable_dead_owner_([0-9a-f]{64})$'){$eligibilityReceipt=$Matches[1];$recoveryOwnerFence=(Invoke-SingularityAdmin settle-top-level-transition --repo $Repository --repository-global-all-generations --bound-purpose-receipt $currentPurpose --dead-owner-eligibility-receipt $eligibilityReceipt --revalidate-owner-dead-expired-and-quiesced-under-slot-lock --advance-owner-fencing-generation-before-mutation --existing-slot-only --journal-bound-settlement --allow-cancel-only-with-no-begin-proof --no-new-candidate --no-new-selection --no-unbound-state-adoption --persist-before-response --print-recovery-owner-fence-receipt).Trim();if($LASTEXITCODE-ne 0-or$recoveryOwnerFence-notmatch'^ownerfence_[0-9a-f]{64}$'){throw 'Dead-owner settlement failed safely'};$slotResult=(Invoke-SingularityAdmin observe-top-level-transition --repo $Repository --repository-global-all-generations --bound-purpose-receipt $currentPurpose --transition-owner-fence-receipt $recoveryOwnerFence --require-current-owner-fencing-generation --read-only --require-latest-journal-live-state-and-ingress --closed-terminal-map singularity-top-level-terminal-v1 --print-terminal-observation-or-recovery-pending).Trim()}
  if($slotResult-notmatch'^terminal_(cutover|source|controller)_(achieved|retryable_old|verified_rollback|safe_failed)_([0-9a-f]{64})$'){throw 'Occupied slot is not in an acknowledgeable closed terminal state'};$terminalKind=$Matches[2];Invoke-SingularityAdmin acknowledge-terminal-disposition --repo $Repository --repository-global-all-generations --bound-purpose-receipt $currentPurpose --terminal-observation-token $slotResult --closed-terminal-map singularity-top-level-terminal-v1 --revalidate-observation-still-current-before-ack --require-current-owner-fencing-generation-bound-to-observation --atomic-under-slot-lock --reject-cross-operation-purpose-epoch-or-owner-token-replay --idempotent --persist-before-response|Out-Null;$ackExit=$LASTEXITCODE
  $afterAck=(Invoke-SingularityAdmin resolve-transition-purpose-outcome --repo $Repository --purpose-receipt $currentPurpose --read-only --require-unique-exact-archive --require-observation-acknowledgement-chain --print-archived-outcome).Trim();$expected=@{achieved='archived_achieved';retryable_old='archived_retryable';verified_rollback='archived_rollback';safe_failed='archived_failed'};if($LASTEXITCODE-ne 0-or$afterAck-ne$expected[$terminalKind]){throw "Terminal archive disagreement after ack_exit=$ackExit"};$released=(Invoke-SingularityAdmin resolve-current-top-level-transition --repo $Repository --repository-global-all-generations --read-only --require-unique-live-slot --print-none-or-bound-purpose-receipt).Trim();if($LASTEXITCODE-ne 0-or$released-ne'none'){throw 'Acknowledged slot did not release'};return "$afterAck|$currentPurpose"
}
function Resolve-SingularityPurposeStartDisposition{param([string]$Repository,[string]$DesiredPurpose,[string]$PriorTerminal);if($DesiredPurpose-notmatch'^purpose_[0-9a-f]{64}$'){throw 'Invalid desired-purpose receipt'};if($PriorTerminal-ne'none'){$parts=@($PriorTerminal-split'\|',2);if($parts.Count-ne 2){throw 'Malformed prior terminal result'};$relationship=(Invoke-SingularityAdmin classify-purpose-successor --repo $Repository --completed-purpose-receipt $parts[1] --desired-purpose-receipt $DesiredPurpose --read-only --require-closed-reviewed-purpose-dag --require-explicit-wave-restart-edge --reject-multiple-matching-archives --print-same-allowed-predecessor-or-unrelated).Trim();if($LASTEXITCODE-ne 0-or$relationship-eq'unrelated_or_new_epoch'){throw 'Prior and desired purposes lack an allowed relationship'};if($relationship-eq'allowed_predecessor'-and$parts[0]-ne'archived_achieved'){throw 'Only an achieved predecessor may advance'}};$outcome=(Invoke-SingularityAdmin resolve-transition-purpose-outcome --repo $Repository --purpose-receipt $DesiredPurpose --read-only --require-unique-exact-archive --print-clear-never-started-or-archived-outcome).Trim();if($outcome-eq'archived_achieved'){return 'already_achieved'};if($outcome-in@('clear_never_started','archived_retryable')){return 'proceed'};throw "Desired purpose is not runnable: $outcome"}
$priorTerminal=Complete-SingularityTopLevelSlot $repoRoot
$purposeIssueReply=(Invoke-SingularityAdmin acquire-transition-purpose --repo $repoRoot --reviewed-plan-node task2-source-v1 --operation source-update --contract source-update-maintenance-v1 --requested-fences cli-run-closed+discord-disabled+maintenance-index-ref --bind-active-reviewed-wave-epoch --require-wave-epoch-bound-to-current-tofu-receipt --require-satisfied-reviewed-predecessor-ledger --reject-unrelated-or-multiple-predecessor-archives --bind-exact-old-state --capture-native-no-follow-pre-normalization-batch --bind-canonicalization-policy strict-utf8-parent-bom-preserving-crlf-to-lf-or-exact --create-or-return-exact --persist-before-response --print-purpose-receipt).Trim();$purposeIssueExit=$LASTEXITCODE
$transitionPurpose=(Invoke-SingularityAdmin resolve-transition-purpose --repo $repoRoot --reviewed-plan-node task2-source-v1 --operation source-update --contract source-update-maintenance-v1 --requested-fences cli-run-closed+discord-disabled+maintenance-index-ref --bind-active-reviewed-wave-epoch --require-wave-epoch-bound-to-current-tofu-receipt --require-satisfied-reviewed-predecessor-ledger --reject-unrelated-or-multiple-predecessor-archives --bind-exact-old-state --capture-native-no-follow-pre-normalization-batch --bind-canonicalization-policy strict-utf8-parent-bom-preserving-crlf-to-lf-or-exact --read-only --require-unique-exact --print-purpose-receipt-or-none).Trim();if($LASTEXITCODE-ne 0-or$transitionPurpose-notmatch'^purpose_[0-9a-f]{64}$'){throw "Task 2 purpose is not recoverable after issue_exit=$purposeIssueExit"};if($purposeIssueExit-eq 0-and$purposeIssueReply-and$purposeIssueReply-ne$transitionPurpose){throw 'Task 2 purpose issue reply disagrees with resolution'}
$slotOutcome = Resolve-SingularityPurposeStartDisposition $repoRoot $transitionPurpose $priorTerminal
if ($slotOutcome -eq 'already_achieved') { Write-Output 'Task 2 source update was already authoritatively completed and acknowledged'; return }
$sourceIntentReply = (Invoke-SingularityAdmin acquire-begin-intent --repo $repoRoot --operation source-update --contract source-update-maintenance-v1 --transition-purpose-receipt $transitionPurpose --require-exact-purpose-binding --require-reviewed-purpose-dag --requested-fences cli-run-closed+discord-disabled+maintenance-index-ref --bind-exact-old-state --exclusive-top-level-mutation-per-registered-repo-all-generations --create-or-return-unique-slot --persist-before-response --print-request-id).Trim()
$sourceIntentExit = $LASTEXITCODE
$sourceUpdateRequestId = (Invoke-SingularityAdmin resolve-begin-intent --repo $repoRoot --operation source-update --contract source-update-maintenance-v1 --transition-purpose-receipt $transitionPurpose --require-exact-purpose-binding --requested-fences cli-run-closed+discord-disabled+maintenance-index-ref --bind-exact-old-state --exclusive-top-level-mutation-per-registered-repo-all-generations --read-only --require-unique-slot --require-persisted-intent --print-request-id-or-none).Trim()
if ($LASTEXITCODE -ne 0 -or -not $sourceUpdateRequestId -or $sourceUpdateRequestId -eq 'none') { throw "Task 2 source-update intent is not authoritatively discoverable after intent_exit=$sourceIntentExit; recover by repository and operation contract without starting another transition" }
if ($sourceIntentExit -eq 0 -and $sourceIntentReply -and $sourceIntentReply -ne $sourceUpdateRequestId) { throw 'Task 2 intent reply disagrees with authoritative intent discovery; do not start another transition' }
$ownerFenceReceipt = (Invoke-SingularityAdmin resolve-begin-intent-owner-fence --repo $repoRoot --request-id $sourceUpdateRequestId --transition-purpose-receipt $transitionPurpose --read-only --require-current-owner-lease-and-fencing-generation --print-owner-fence-receipt).Trim()
if ($LASTEXITCODE -ne 0 -or $ownerFenceReceipt -notmatch '^ownerfence_[0-9a-f]{64}$') { throw 'Task 2 owner-fence receipt is unavailable; do not begin' }
function Invoke-SingularityAdmin { $recoveryCommands=@('resolve-current-top-level-transition','observe-top-level-transition','settle-top-level-transition','acknowledge-terminal-disposition','resolve-transition-purpose-outcome');if($args.Count-and$args[0]-in$recoveryCommands){& $pinnedPowerShell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $singularityClient --request-only --require-server-validated-client-digest @args}else{& $pinnedPowerShell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $singularityClient --request-only --require-server-validated-client-digest --transition-purpose-receipt $transitionPurpose --transition-owner-fence-receipt $ownerFenceReceipt --require-current-owner-fencing-generation @args} }
$sourceReplyTx = (Invoke-SingularityAdmin begin-source-update --request-id $sourceUpdateRequestId --idempotent-create --repo $repoRoot --require-exact-purpose-binding --close-cli-run-ingress --keep-discord-listener-disabled --hold-maintenance-index-and-ref-fences --persist-begin-receipt-before-response).Trim()
$sourceReplyExit = $LASTEXITCODE
$sourceTx = (Invoke-SingularityAdmin resolve-source-update-begin --request-id $sourceUpdateRequestId --repo $repoRoot --read-only --require-exact-request-binding --require-exact-purpose-binding --require-persisted-begin-receipt-if-started --require-latest-monotone-journal-if-started --require-exact-old-state-if-started --require-live-requested-fences-held-if-started --classify-started-exact-requested-fences-held-or-not-started --print-transaction-or-not-started).Trim()
if ($LASTEXITCODE -ne 0 -or -not $sourceTx) { throw "Task 2 source-update begin state is uncertain after begin_exit=$sourceReplyExit; do not use or infer ingress state; recover by request ID $sourceUpdateRequestId" }
if ($sourceTx -eq 'not_started') { throw "Task 2 source update did not start; request ID $sourceUpdateRequestId" }
if ($sourceReplyExit -eq 0 -and $sourceReplyTx -and $sourceReplyTx -ne $sourceTx) { throw "Task 2 begin reply disagrees with authoritative resolution; do not infer ingress state; recover by request ID $sourceUpdateRequestId" }
function Stop-SingularitySourceUpdateBeforeCas { param([string]$Reason, [string]$Proposal)
  $abortArgs = @('abort-source-update', '--transaction', $sourceTx, '--before-cas-only', '--abort-all-child-resources', '--reconcile-journaled-normalization', '--restore-developer-ingress-only-if-old-ref-index-tree-exact', '--keep-production-run-inactive', '--keep-discord-listener-disabled', '--persist-and-reread-recovery-receipt', '--print-disposition'); if ($Proposal) { $abortArgs += @('--proposal', $Proposal) }
  Invoke-SingularityAdmin @abortArgs | Out-Null; $abortExit = $LASTEXITCODE
  $disposition = (Invoke-SingularityAdmin resolve-source-update-disposition --transaction $sourceTx --read-only --require-persisted-receipt --require-production-run-inactive --require-discord-listener-disabled --classify-safe-old-developer-ingress-open-or-held-closed-or-recovery-pending --print-disposition).Trim()
  if ($LASTEXITCODE -ne 0 -or $disposition -notin @('safe_old_developer_ingress_open', 'safe_old_developer_ingress_held_closed', 'fenced_recovery_pending')) { throw "$Reason; authoritative source-update disposition is unavailable after abort_exit=$abortExit; do not infer ingress state; recover transaction $sourceTx" }
  if ($disposition -eq 'safe_old_developer_ingress_open') { throw "$Reason; exact old state is restored and developer ingress is authoritatively open" }
  if ($disposition -eq 'safe_old_developer_ingress_held_closed') { throw "$Reason; exact old state is restored but developer ingress is authoritatively held closed" }
  throw "$Reason; a durable recovery receipt proves developer ingress held closed pending recovery"
}
function Stop-SingularitySourceUpdateAfterCas { param([string]$Reason, [string]$Proposal)
  Invoke-SingularityAdmin reconcile-source-update --transaction $sourceTx --proposal $Proposal --classify-old-or-exact-new-ref-index-tree --finish-only-journal-bound-materialization-attestation-and-ingress --keep-production-run-inactive --keep-discord-listener-disabled --persist-and-reread-recovery-receipt --print-disposition | Out-Null
  $reconcileExit = $LASTEXITCODE
  $disposition = (Invoke-SingularityAdmin resolve-source-update-disposition --transaction $sourceTx --read-only --require-persisted-receipt --require-production-run-inactive --require-discord-listener-disabled --classify-safe-old-or-committed-exact-new-with-ingress-or-recovery-pending --print-disposition).Trim()
  if ($LASTEXITCODE -ne 0 -or $disposition -notin @('safe_old_developer_ingress_open', 'safe_old_developer_ingress_held_closed', 'committed_exact_new_developer_ingress_open', 'committed_exact_new_developer_ingress_held_closed', 'fenced_recovery_pending')) { throw "$Reason; authoritative source-update disposition is unavailable after reconcile_exit=$reconcileExit; do not infer ingress state; recover transaction $sourceTx" }
  throw "$Reason; authoritative disposition=$disposition; re-enter through verified recovery before continuing"
}
function Register-SingularityPathManifest { param([string]$Scope, [string[]]$Allowed, [string[]]$Required, [string[]]$Tests)
  function ConvertTo-SingularityManifestBase64Url { param([string]$CanonicalJson) $bytes = ([System.Text.UTF8Encoding]::new($false, $true)).GetBytes($CanonicalJson); if ($bytes.Length -gt 4096) { throw 'Path-manifest decoded JSON exceeds 4096 bytes' }; return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_') }
  $allowedSet = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal); $requiredSet = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal); $testSet = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
  foreach ($entry in $Allowed) { if (-not $entry -or $entry.Length -gt 240 -or -not $allowedSet.Add($entry)) { throw "Invalid or duplicate allowed path: $entry" } }; foreach ($entry in $Required) { if (-not $requiredSet.Add($entry) -or -not $allowedSet.Contains($entry)) { throw "Invalid required-change subset: $entry" } }; foreach ($entry in $Tests) { if (-not $testSet.Add($entry) -or -not $allowedSet.Contains($entry)) { throw "Invalid test subset: $entry" } }
  $records = @($Allowed | ForEach-Object { $isRequired = $requiredSet.Contains($_); $isTest = $testSet.Contains($_); $role = if ($isRequired -and $isTest) { 'required-test' } elseif ($isRequired) { 'required-change' } elseif ($isTest) { 'test-only' } else { 'allowed-only' }; [ordered]@{ role = $role; path = $_ } })
  $manifestId = (Invoke-SingularityAdmin begin-path-manifest --scope $Scope --expected-total-count $Allowed.Count --expected-required-count $Required.Count --expected-test-count $Tests.Count).Trim()
  if ($LASTEXITCODE -ne 0 -or -not $manifestId) { throw 'Unable to begin external path manifest' }
  $sequence = 0; $chunk = @(); foreach ($record in $records) { $trial = @($chunk + $record); $trialJson = ([ordered]@{ sequence = $sequence; records = $trial } | ConvertTo-Json -Compress -Depth 4); if (($trial.Count -gt 24 -or [Text.Encoding]::UTF8.GetByteCount($trialJson) -gt 4096) -and $chunk.Count) { $chunkJson = ([ordered]@{ sequence = $sequence; records = $chunk } | ConvertTo-Json -Compress -Depth 4); $chunkPayload = ConvertTo-SingularityManifestBase64Url $chunkJson; Invoke-SingularityAdmin append-path-manifest --scope $Scope --manifest $manifestId --sequence $sequence --canonical-records-json-base64url $chunkPayload --require-strict-unpadded-base64url --require-decoded-canonical-json-max-bytes 4096 --require-decode-recanonicalize-byte-equality --require-exact-envelope-max-bytes 8192; if ($LASTEXITCODE -ne 0) { throw "External path-manifest upload failed at sequence $sequence" }; $sequence += 1; $chunk = @($record) } else { $chunk = $trial } }
  if ($chunk.Count) { $chunkJson = ([ordered]@{ sequence = $sequence; records = $chunk } | ConvertTo-Json -Compress -Depth 4); $chunkPayload = ConvertTo-SingularityManifestBase64Url $chunkJson; Invoke-SingularityAdmin append-path-manifest --scope $Scope --manifest $manifestId --sequence $sequence --canonical-records-json-base64url $chunkPayload --require-strict-unpadded-base64url --require-decoded-canonical-json-max-bytes 4096 --require-decode-recanonicalize-byte-equality --require-exact-envelope-max-bytes 8192; if ($LASTEXITCODE -ne 0) { throw "External path-manifest upload failed at sequence $sequence" } }
  $receipt = (Invoke-SingularityAdmin seal-path-manifest --scope $Scope --manifest $manifestId --canonical-order --sha256 --require-total-count $Allowed.Count --require-required-count $Required.Count --require-test-count $Tests.Count --persist-and-reread).Trim(); if ($LASTEXITCODE -ne 0 -or -not $receipt) { throw 'External path-manifest seal failed' }; return $receipt
}
try { $pathManifestReceipt = Register-SingularityPathManifest $sourceTx $stageAllowlist $requiredChanges $testPaths }
catch { Stop-SingularitySourceUpdateBeforeCas "Task 2 path-manifest failure: $($_.Exception.Message)" '' }
$normalizationReceipt = (Invoke-SingularityAdmin normalize-developer-source --transaction $sourceTx --repo $repoRoot --path-manifest-receipt $pathManifestReceipt --chain-purpose-pre-normalization-batch-and-policy --require-exact-purpose-batch-membership --strict-utf8-parent-bom-preserving-crlf-to-lf-only --binary-exact --ensure-symbolic-loose-head-same-oid --create-if-absent-or-verify-existing-loose-head --disable-auto-ref-packing --native-full-tree-exact-index-bytes --no-ambient-git-config --no-hooks --no-filters --require-no-unexpected-change --persist-before-response --print-normalization-receipt).Trim()
if ($LASTEXITCODE -ne 0 -or $normalizationReceipt -notmatch '^normalization_[0-9a-f]{64}$') { Stop-SingularitySourceUpdateBeforeCas 'Task 2 exact-change normalization did not chain the immutable purpose batch' '' }
$proposalTx = (Invoke-SingularityAdmin prepare-source-commit --transaction $sourceTx --repo $repoRoot --path-manifest-receipt $pathManifestReceipt --normalization-receipt $normalizationReceipt --require-pre-normalization-purpose-chain --native-no-follow-snapshot --parent-plus-allowlist-complete-tree --fixed-commit-metadata --message 'feat: stage and fence candidate promotion').Trim()
if ($LASTEXITCODE -ne 0 -or -not $proposalTx) { Stop-SingularitySourceUpdateBeforeCas 'Task 2 source proposal failed' '' }
Invoke-SingularityAdmin review-source-proposal --transaction $proposalTx --sealed-independent-reviewer --persist-and-reread-review-receipt --no-canonical-write
if ($LASTEXITCODE -ne 0) { Stop-SingularitySourceUpdateBeforeCas 'Task 2 independent proposal review failed' $proposalTx }
Invoke-SingularityAdmin verify-source-proposal --transaction $proposalTx --normalization-receipt $normalizationReceipt --require-pre-normalization-purpose-chain --require-exact-manifest --require-every-required-path-changed --require-no-unexpected-change --require-review-receipt --require-no-canonical-ref-write
if ($LASTEXITCODE -ne 0) { Stop-SingularitySourceUpdateBeforeCas 'Task 2 exact proposal verification failed' $proposalTx }
Invoke-SingularityAdmin commit-source-proposal --transaction $proposalTx --source-update $sourceTx --normalization-receipt $normalizationReceipt --require-pre-normalization-purpose-chain --require-fresh-exact-digest-approval --cas-loose-ref --native-full-tree-materialize --install-verified-index --require-final-byte-clean --durable --keep-production-run-inactive
if ($LASTEXITCODE -ne 0) { Stop-SingularitySourceUpdateAfterCas 'Task 2 external source commit reported failure' $proposalTx }
Invoke-SingularityAdmin attest-committed-source --transaction $sourceTx --proposal $proposalTx --require-loose-head --require-exact-index-worktree-bytes --require-source-receipt --keep-production-run-inactive
if ($LASTEXITCODE -ne 0) { Stop-SingularitySourceUpdateAfterCas 'Task 2 committed source attestation failed' $proposalTx }
Invoke-SingularityAdmin finish-source-update --transaction $sourceTx --release-developer-only-ingress --keep-production-run-inactive --keep-discord-listener-disabled --persist-and-reread-finish-receipt --print-disposition | Out-Null
$finishExit = $LASTEXITCODE
$finishDisposition = (Invoke-SingularityAdmin resolve-source-update-disposition --transaction $sourceTx --read-only --require-persisted-receipt --require-production-run-inactive --require-discord-listener-disabled --classify-safe-old-or-committed-exact-new-with-ingress-or-recovery-pending --print-disposition).Trim()
if ($LASTEXITCODE -ne 0 -or -not $finishDisposition) { throw "Task 2 finish disposition unavailable after finish_exit=$finishExit; do not infer ingress state; recover transaction $sourceTx" }
if ($finishDisposition -ne 'committed_exact_new_developer_ingress_open') { Stop-SingularitySourceUpdateAfterCas "Task 2 finish resolved as $finishDisposition" $proposalTx }
$terminalOutcome = Complete-SingularityTopLevelSlot $repoRoot
if ($terminalOutcome -ne "archived_achieved|$transitionPurpose") { throw 'Task 2 terminal transition was not observed, acknowledged, archived, and released as achieved' }
```

---

## 5. Task 3 - Make every retry its own prepare, verify, promote transaction

**Files**

- Modify: `main.py`
- Modify: `orchestrator.py`
- Modify: `selfmod.py`
- Modify: `config.py`
- Modify: `llm_io.py`
- Modify: `notifications/bot/core.py`
- Modify: `notifications/psyche_cog.py`
- Modify: `notifications/slash.py`
- Modify: `notifications/bot/cogs/admin.py`
- Modify: `notifications/bot/cogs/ask_cog.py`
- Modify: `notifications/bot/cogs/context_cog.py`
- Modify: `notifications/bot/cogs/control_cog.py`
- Modify: `notifications/bot/cogs/engagement_cog.py`
- Modify: `notifications/bot/cogs/log_cog.py`
- Modify: `notifications/bot/cogs/observe_cog.py`
- Modify: `notifications/bot/cogs/plan_cog.py`
- Modify: `notifications/bot/cogs/ops_cog.py`
- Modify: `notifications/bot/ui/dynamic.py`
- Modify: `notifications/bot/cogs/runs_cog.py`
- Modify: `notifications/ask.py`
- Modify: `notifications/brain_dialogue.py`
- Modify: `notifications/briefing.py`
- Modify: `notifications/instinct.py`
- Modify: `notifications/jerry_client.py`
- Modify: `notifications/council_transcript.py`
- Modify: `notifications/runtime/work_launcher.py`
- Modify: `notifications/runtime/work_launcher_readiness.py`
- Modify: `notifications/runtime/tunnel.py`
- Modify: `notifications/runtime/tunnel_providers.py`
- Modify: `notifications/runtime/reflection_post.py`
- Modify: `notifications/runtime/subprocess_feed.py`
- Modify: `notifications/audit.py`
- Modify: `notifications/discord/channels.py`
- Modify: `notifications/discord/client.py`
- Modify: `notifications/cast.py`
- Modify: `notifications/commands.py`
- Modify: `notifications/surfaces/dashboard.py`
- Modify: `notifications/surfaces/webdash.py`
- Modify: `notifications/surfaces/terminal_ipc.py`
- Modify: `notifications/surfaces/terminal_surface.py`
- Modify: `notifications/presentation/views_control.py`
- Modify: `notifications/presentation/views_feedback.py`
- Modify: `notifications/presentation/views_run.py`
- Modify: `notifications/presentation/views_subtask.py`
- Modify: `notifications/presentation/views_terminal.py`
- Modify: `notifications/presentation/icons.py`
- Modify: `memory/stores/obsidian.py`
- Modify: `memory/stores/user_prefs.py`
- Modify: `memory/retrievals/core.py`
- Modify: `memory/conviction_ledger.py`
- Modify: `memory/ledger/index.py`
- Modify: `memory/ledger/schema.py`
- Modify: `memory/novelty/store.py`
- Modify: `human_nature/faculties/runtime/consolidation.py`
- Modify: `human_nature/faculties/signals/instinct.py`
- Modify: `human_nature/faculties/signals/momentary.py`
- Modify: `human_nature/faculties/signals/opinions.py`
- Modify: `human_nature/faculties/runtime/psyche_store.py`
- Modify: `human_nature/faculties/runtime/ab_harness.py`
- Modify: `human_nature/faculties/identity/continuity.py`
- Modify: `agents/discovery/__init__.py`
- Modify: `agents/discovery/digest.py`
- Modify: `agents/discovery/ledger_bridge.py`
- Modify: `agents/planning/council_context.py`
- Modify: `agents/planning/council_seam.py`
- Modify: `agents/planning/council_logging.py`
- Modify: `agents/planning/pre_execution_council.py`
- Modify: `agents/planning/elaborator/core.py`
- Modify: `agents/planning/elaborator/grounding.py`
- Modify: `agents/planning/elaborator/path_verify.py`
- Modify: `agents/planning/replanner.py`
- Modify: `agents/planning/playbook.py`
- Modify: `platform_core/execution/environment.py`
- Modify: `platform_core/execution/security.py`
- Modify: `platform_core/execution/backends/local.py`
- Modify: `platform_core/execution/backends/docker.py`
- Modify: `platform_core/execution/backends/remote.py`
- Add: `platform_core/execution/launch_plan.py`
- Add: `platform_core/execution/sandbox_broker.py`
- Add: `platform_core/execution/credential_broker.py`
- Add: `platform_core/execution/local_model_broker.py`
- Add: `platform_core/execution/source_acquisition.py`
- Add: `platform_core/execution/neutral_host_probe.py`
- Add: `platform_core/execution/provider_boot.py`
- Add: `platform_core/execution/image_manifest.py`
- Modify: `platform_core/runtime/attempt_journal.py`
- Modify: `platform_core/runtime/candidate.py`
- Modify: `platform_core/runtime/receipts.py`
- Modify: `platform_core/runtime/operator_launch.py`
- Modify: `platform_core/runtime/control_store.py`
- Modify: `platform_core/runtime/control.py`
- Add: `platform_core/runtime/controller_state.py`
- Add: `platform_core/runtime/state_store_worker.py`
- Add: `platform_core/runtime/effect_guard.py`
- Add: `platform_core/runtime/recovery.py`
- Add: `platform_core/runtime/legacy_state_migration.py`
- Add: `agents/execution/claude_driver.py`
- Add: `agents/execution/codex_driver.py`
- Add: `containers/galaxy/driver_entrypoint.py`
- Add: `containers/galaxy/state_store_entrypoint.py`
- Modify: `agents/execution/executor.py`
- Modify: `agents/execution/executor_env.py`
- Modify: `agents/execution/executor_stream.py`
- Modify: `agents/execution/executor_stream_results.py`
- Modify: `agents/execution/executor_session.py`
- Modify: `agents/execution/browser_executor.py`
- Modify: `agents/execution/chatgpt_browser_driver.py`
- Modify: `agents/execution/native_executor.py`
- Modify: `agents/execution/gemini_driver.py`
- Modify: `agents/review/verification.py`
- Modify: `agents/review/verifier_runner.py`
- Modify: `agents/review/verification_diff.py`
- Modify: `agents/review/architect.py`
- Modify: `agents/review/independent_verifier.py`
- Modify: `platform_core/ops/health.py`
- Modify: `platform_core/ops/external_project.py`
- Modify: `platform_core/ops/doctor.py`
- Modify: `platform_core/ops/retention.py`
- Modify: `platform_core/ops/wipe.py`
- Modify: `platform_core/core/epoch.py`
- Modify: `platform_core/core/git_io.py`
- Modify: `platform_core/core/jsonl_io.py`
- Modify: `platform_core/core/tracing.py`
- Modify: `platform_core/cli/main_cli.py`
- Modify: `platform_core/app_config/__init__.py`
- Modify: `platform_core/app_config/_env.py`
- Modify: `platform_core/app_config/paths.py`
- Modify: `platform_core/app_config/llm.py`
- Modify: `platform_core/app_config/settings.py`
- Modify: `platform_core/knowledge_base/compress.py`
- Modify: `platform_core/knowledge_base/scraper.py`
- Modify: `learning/evolution/evolver.py`
- Modify: `learning/evolution/bootstrap.py`
- Modify: `learning/evolution/sie.py`
- Modify: `learning/evolution/sie_steps.py`
- Modify: `learning/evolution/sie_curriculum.py`
- Modify: `learning/evolution/selfplay.py`
- Modify: `learning/evolution/validate.py`
- Modify: `learning/evolution/compute.py`
- Modify: `learning/evolution/curator.py`
- Modify: `learning/evolution/curriculum.py`
- Modify: `learning/evolution/promote.py`
- Modify: `learning/evolution/release.py`
- Modify: `learning/feedback/lessons.py`
- Modify: `learning/feedback/preferences.py`
- Modify: `learning/model/finetune.py`
- Modify: `learning/model/distill.py`
- Modify: `learning/model/eval_harness.py`
- Modify: `learning/model/dataset.py`
- Modify: `learning/eval_harness.py`
- Modify: `learning/selfplay.py`
- Modify: `platform_core/execution/launch_guard.py`
- Add: `platform_core/execution/authority_watchdog.py`
- Add: `platform_core/execution/runtime_projection.py`
- Add: `platform_core/execution/pre_execution.py`
- Modify: `platform_core/execution/wiring.py`
- Modify: `platform_core/execution/backends/clone.py`
- Modify: `platform_core/orchestration/execute_mixin.py`
- Modify: `platform_core/orchestration/execute_attempt_mixin.py`
- Modify: `platform_core/orchestration/run_phase_mixin.py`
- Modify: `platform_core/orchestration/run_loop.py`
- Modify: `platform_core/orchestration/plan_context.py`
- Modify: `platform_core/orchestration/plan_mixin.py`
- Modify: `platform_core/orchestration/plan_prompts.py`
- Modify: `platform_core/orchestration/subtask.py`
- Modify: `platform_core/orchestration/fork_policy.py`
- Modify: `platform_core/orchestration/knowledge_refresh.py`
- Modify: `platform_core/orchestration/validation_cache.py`
- Modify: `platform_core/orchestration/self_ref_gate.py`
- Modify: `platform_core/orchestration/github.py`
- Modify: `platform_core/orchestration/pr_feedback.py`
- Modify: `platform_core/orchestration/run_phase_outcome.py`
- Modify: `platform_core/orchestration/review_mixin.py`
- Modify: `platform_core/orchestration/control_mixin.py`
- Modify: `platform_core/orchestration/execute_delegates_mixin.py`
- Modify: `platform_core/orchestration/llm_mixin.py`
- Modify: `platform_core/orchestration/compaction.py`
- Modify: `platform_core/orchestration/brain_io.py`
- Modify: `platform_core/orchestration/adversary_loop.py`
- Modify: `platform_core/orchestration/evidence_gate.py`
- Modify: `platform_core/orchestration/invention_seeding.py`
- Modify: `platform_core/orchestration/code_graph.py`
- Modify: `platform_core/orchestration/society/blackboard.py`
- Modify: `platform_core/orchestration/human_nature_bridge/lifecycle.py`
- Modify: `learning/model/eval_runner.py`
- Modify: `learning/outcome_evaluation.py`
- Modify: `platform_core/simulator/testing/outcome_runner.py`
- Modify: `state/task_schema.py`
- Modify: `state/task_io.py`
- Modify: `platform_core/runtime/heartbeat.py`
- Modify: `platform_core/runtime/perf.py`
- Modify: `platform_core/runtime/trajectory.py`
- Modify: `tools/claude_metrics.py`
- Modify: `tools/size_audit.py`
- Modify: `agents/hook_handlers/core.py`
- Modify: `agents/hook_handlers/destructive.py`
- Modify: `agents/hook_handlers/selfmod.py`
- Modify: `agents/hook_handlers/obsidian.py`
- Test: `tests/execution/test_executor.py`
- Test: `tests/execution/test_executor_stream.py`
- Add: `tests/execution/test_executor_env.py`
- Test: `tests/execution/test_executor_session_lock.py`
- Test: `tests/execution/test_execution_security.py`
- Test: `tests/execution/test_execution_docker.py`
- Add: `tests/execution/test_sandbox_broker.py`
- Add: `tests/execution/test_credential_broker.py`
- Add: `tests/execution/test_local_model_broker.py`
- Add: `tests/execution/test_source_acquisition.py`
- Add: `tests/execution/test_effect_guard.py`
- Add: `tests/execution/test_provider_safe_boot.py`
- Add: `tests/execution/test_runtime_resource_recovery.py`
- Add: `tests/execution/test_external_recovery.py`
- Add: `tests/execution/test_legacy_state_migration.py`
- Add: `tests/execution/test_galaxy_images.py`
- Test: `tests/execution/test_attempt_journal.py`
- Test: `tests/execution/test_attempt_crash_matrix.py`
- Test: `tests/execution/test_promotion_authorization.py`
- Test: `tests/execution/test_receipts.py`
- Test: `tests/execution/test_execution_trust.py`
- Test: `tests/control/test_execution_trust_authority.py`
- Test: `tests/control/test_operator_launch.py`
- Test: `tests/control/test_control_store.py`
- Add: `tests/control/test_external_controller_state.py`
- Test: `tests/control/test_task_io_single_writer.py`
- Test: `tests/control/test_webdash_control.py`
- Test: `tests/review/test_verification.py`
- Test: `tests/execution/test_verifier_runner.py`
- Test: `tests/execution/test_verification_diff.py`
- Add: `tests/review/test_analysis_isolation.py`
- Test: `tests/platform/test_health_collect.py`
- Test: `tests/platform/test_config_logging_lock.py`
- Test: `tests/evolution/test_evolution_evolver.py`
- Test: `tests/execution/test_launch_guard.py`
- Add: `tests/execution/test_authority_watchdog.py`
- Add: `tests/execution/test_runtime_projection.py`
- Add: `tests/execution/test_pre_execution_isolation.py`
- Add: `tests/execution/test_verification_isolation.py`
- Test: `tests/orchestration/test_execute_mixin_env.py`
- Test: `tests/execution/test_execute_mixin_teardown.py`
- Add: `tests/orchestration/test_staged_finalization.py`
- Add: `tests/control/test_attempt_state_transaction.py`
- Test: `tests/platform/test_main_cli.py`
- Test: `tests/execution/test_dry_run.py`
- Test: `tests/test_main_elaboration.py`
- Test: `tests/test_validation_cache.py`
- Test: `tests/evolution/test_knowledge.py`
- Test: `tests/execution/test_github_pr_gate.py`
- Test: `tests/execution/test_pr_feedback_async.py`
- Test: `tests/execution/test_external_project.py`
- Test: `tests/execution/test_work_launcher.py`
- Test: `tests/execution/test_external_launcher.py`
- Test: `tests/execution/test_browser_executor.py`
- Test: `tests/execution/test_chatgpt_browser_driver.py`
- Test: `tests/orchestration/test_native_executor_cleanup.py`
- Test: `tests/orchestration/test_gemini_driver.py`
- Test: `tests/notifications/test_runs_cog.py`
- Test: `tests/notifications/test_discord_channels.py`
- Test: `tests/notifications/test_discord_rest.py`
- Test: `tests/notifications/test_cast.py`
- Test: `tests/notifications/test_commands.py`
- Test: `tests/notifications/test_engagement.py`
- Test: `tests/notifications/test_obsidian_write.py`
- Test: `tests/notifications/test_obsidian_atomic_claude_md.py`
- Test: `tests/control/test_hooks_obsidian.py`
- Test: `tests/notifications/test_tunnel.py`
- Test: `tests/notifications/test_jerry_client.py`
- Test: `tests/notifications/test_bloomberg_webdash.py`
- Test: `tests/notifications/test_ask.py`
- Test: `tests/notifications/test_briefing.py`
- Test: `tests/notifications/test_instinct.py`
- Test: `tests/orchestration/test_brain_dialogue.py`
- Test: `tests/evolution/test_selfmod.py`
- Test: `tests/evolution/test_selfmod_runner.py`
- Test: `tests/evolution/test_user_prefs.py`
- Add: `tests/evolution/test_selfplay_boundary.py`
- Test: `tests/slow/test_full_autonomy.py`
- Test: `tests/control/test_hooks_selfmod.py`
- Test: `tests/control/test_safety_gate_divergence.py`
- Test: `tests/evolution/test_sie.py`
- Test: `tests/evolution/test_finetune.py`
- Test: `tests/evolution/test_eval_harness.py`
- Test: `tests/evolution/test_evolution_validate.py`
- Test: `tests/evolution/test_dataset_gate.py`
- Test: `tests/evolution/test_curriculum.py`
- Test: `tests/evolution/test_retrieval.py`
- Test: `tests/human_nature/test_consolidation.py`
- Test: `tests/human_nature/test_momentary.py`
- Test: `tests/human_nature/test_opinions.py`
- Test: `tests/orchestration/test_llm_io_pydantic.py`
- Test: `tests/orchestration/test_ollama_num_ctx_stable.py`
- Test: `tests/orchestration/test_discovery_digest.py`
- Test: `tests/orchestration/test_discovery_facade.py`
- Test: `tests/orchestration/test_invention_seeding.py`
- Test: `tests/orchestration/test_code_graph.py`
- Test: `tests/orchestration/test_plan_project_context.py`
- Add: `tests/orchestration/test_planning_projection.py`
- Test: `tests/orchestration/test_pre_execution_council_seam.py`
- Test: `tests/planning/test_pre_execution_council.py`
- Test: `tests/planning/test_pre_execution_council_seam.py`
- Test: `tests/orchestration/test_elaborator.py`
- Test: `tests/orchestration/test_elaborator_grounding.py`
- Test: `tests/orchestration/test_run_loop_replan_mixin.py`
- Test: `tests/orchestration/test_execute_quality_gate.py`
- Test: `tests/orchestration/test_horizon_fill.py`
- Test: `tests/orchestration/test_orch_core_bugs.py`
- Test: `tests/orchestration/test_execcwd_fabric.py`
- Test: `tests/orchestration/test_control_review_mixin.py`
- Test: `tests/orchestration/test_subtask_files_touched.py`
- Test: `tests/evolution/test_playbook.py`
- Test: `tests/orchestration/test_fork_policy.py`
- Test: `tests/execution/test_eval_runner.py`
- Test: `tests/evolution/test_outcome_evaluation.py`
- Test: `tests/slow/test_outcome_lifecycle.py`
- Test: `tests/orchestration/test_outcome_evaluation_verify.py`
- Test: `tests/platform/test_doctor.py`
- Test: `tests/platform/test_config_bootstrap.py`
- Test: `tests/execution/test_evidence_gate.py`
- Add: `tests/execution/test_deep_boundary_inventory.py`
- Add: `tests/execution/test_external_state_writers.py`
- Test: `tests/platform/test_jsonl_io.py`
- Test: `tests/platform/test_iteration_telemetry.py`
- Test: `tests/platform/test_retention.py`
- Test: `tests/control/test_heartbeat.py`
- Test: `tests/control/test_terminal_ipc.py`
- Test: `tests/control/test_wipe.py`
- Test: `tests/control/test_hooks.py`
- Test: `tests/control/test_views.py`
- Test: `tests/control/test_views_terminal.py`
- Test: `tests/orchestration/test_trajectory.py`
- Test: `tests/orchestration/test_compaction.py`
- Test: `tests/orchestration/test_society_blackboard.py`
- Test: `tests/orchestration/test_human_nature_bridge.py`
- Test: `tests/orchestration/test_adversary_trust.py`
- Test: `tests/notifications/test_audit.py`
- Test: `tests/notifications/test_reflection_post.py`
- Test: `tests/notifications/test_terminal_surface.py`
- Test: `tests/notifications/test_slash.py`
- Test: `tests/notifications/test_admin.py`
- Test: `tests/notifications/test_context_cog.py`
- Test: `tests/notifications/test_dynamic.py`
- Test: `tests/notifications/test_icons.py`
- Test: `tests/notifications/test_log_cog.py`
- Test: `tests/notifications/test_observe_cog.py`
- Test: `tests/notifications/test_ops.py`
- Test: `tests/notifications/test_plan_cog.py`
- Test: `tests/notifications/test_psyche_cog.py`
- Test: `tests/evolution/test_conviction_ledger.py`
- Test: `tests/evolution/test_experience_schema.py`
- Test: `tests/evolution/test_exp_index.py`
- Test: `tests/evolution/test_novelty_index.py`
- Test: `tests/evolution/test_evolution_curator.py`
- Test: `tests/evolution/test_evolution_promote.py`
- Test: `tests/evolution/test_lessons.py`
- Test: `tests/evolution/test_preferences.py`
- Test: `tests/execution/test_compute.py`
- Test: `tests/human_nature/test_psyche_store.py`
- Test: `tests/human_nature/test_ab_harness.py`
- Test: `tests/human_nature/test_continuity.py`
- Test: `tests/test_perf_telemetry.py`
- Add: `tests/platform/test_runtime_tool_isolation.py`
- Add: `tests/evolution/test_maintenance_deep_boundaries.py`

### Step 1: Add ordering and state-truth tests

Write failing tests proving:

1. The successful order is `provision attempt -> execute -> inner complete/quiesce -> object-only prepare -> provision verification clone/runner -> exact verify -> review-or-policy-skip receipt -> promote/complete -> copy-on-write pending+receipt save -> journal acknowledge -> copy-on-write done save -> terminal_state_persisted -> terminal return`.
2. Verification receives a fresh private clone of the exact proposed SHA, not canonical, the candidate clone, a host-parsed index, or a linked worktree.
3. Failed staged verification never changes canonical, persists a failed attempt outcome, and can produce terminal `failed` only when retry policy is exhausted.
4. A promotion or compare-and-swap failure prevents `done` even when execution and verification passed.
5. Preparation, universal-verifier authority-bound verification, and finalization receipts are persisted on task/subtask state.
6. Verification is bound to `prepared.proposed_revision`.
7. Staged-ref/tree/snapshot/parser-manifest drift before or after the verifier, or verification-clone HEAD/index/tracked drift, causes rejection.
8. `defer_completion=True` still finalizes the composed inner environment before returning control to the outer owner.
9. A valid operator-granted fabric-off Local attempt writes only inside its self-contained private clone; `git rev-parse --git-common-dir` and an attempted candidate `git update-ref` prove canonical Git metadata is unreachable through Git, and failed verification leaves canonical HEAD and files byte-for-byte unchanged.
10. A hostile/unknown Docker-selected attempt mounts the same self-contained private-clone representation rather than canonical metadata. Its credential-bearing model driver and credentialless command sandbox are distinct hardened resources; candidate edits plus failed verification leave canonical unchanged.
11. Mutating remote execution fails immediately after selection and before either outer-lease or remote provisioning because remote collection is not implemented.
12. A requested Worktree backend records `requested=worktree`, `effective_landing=clone`, and `runner=local`; no linked worktree reaches the command runner and the clone landing lease remains authoritative.
13. Every Claude/Codex CLI launch requires a registered typed launch authority unless an explicit enforced read-only authority denies shell, Task/subagents, MCP, Notebook, network, and all write tools; every current repository-capable call site instead uses a candidate or disposable analysis clone.
14. An exception after candidate execution triggers rejected preparation/completion and an immutable checkpoint receipt.
15. A caller-supplied, validated outer `CloneLease` is adopted exactly once; an isolated path without its typed lease is refused rather than guessed or nested.
16. Restart reconciliation attaches a recovered promotion receipt to TaskState exactly once by transaction ID; unresolved or not-promoted records cannot produce `done`.
17. In a two-attempt real-Git run, attempt 1 fails exact-revision verification and is quarantined; attempt 2 starts from unchanged canonical with none of attempt 1's files, then promotes independently.
18. Each retry has a distinct transaction ID, candidate checkout, checkpoint ref, journal record, and complete inner/outer lifecycle.
19. Normal completion atomically persists transaction ID, receipts, and `promotion_persistence_pending`, then flips journal acknowledgement, then atomically persists `done`; it never exposes `done` before acknowledgement.
20. Failpoints before the pending save, after pending save/before journal acknowledgement, during acknowledgement, after acknowledgement/before the done save, and after done save/before `terminal_state_persisted` replay idempotently without duplicate receipts, a second model invocation, or premature `done`.
21. A failed TaskState save leaves the live in-memory object byte-for-byte unchanged; a later unrelated save cannot leak an unpersisted receipt or `done` status.
22. Docker-origin verification starts a new credentialless, network-disabled, capability-dropped container, checks out only the proposed ref in its private clone, and cannot touch host goldstone, canonical/common-dir refs, journal, or candidate-execution container.
23. Every origin, including trusted Local, verifies in a fresh private clone inside a credentialless, network-disabled, pinned hardened container; no acceptance command executes on the host or from the object-only staging surface. Candidate-origin trust remains evidence, never verifier process authority.
24. The pure `validateLaunchAuthority()`/guarded-entry helper is proven zero-side-effect in Task 3—before `_prepareEnv`, directory creation, context/settings generation, logging, session lookup, or launcher resolution—and derives `work_dir` only from authority. Task 4's activation test then proves this helper is literally `runClaude`'s first executable operation after every legacy caller is migrated.
25. Generated `CLAUDE.md`, task snapshots, settings, hooks, session state, and telemetry live only in the external runtime projection; none is created inside the candidate clone or can appear in the canonical candidate snapshot/manifest.
26. A Docker-classified writer uses a typed split launch plan: the authenticated model-driver capsule has **no clone mount and no built-in filesystem, shell, Task/subagent, Notebook, plugin, project-config, or arbitrary MCP tool**. All repository read/list/search/patch/write/exec operations cross a closed typed broker into a separate non-root, cap-dropped, no-new-privileges, read-only-root, network-disabled credentialless container with the clone and bounded scratch. If safe boot and bounded credential handoff cannot be proven, Docker mutation is typed-unavailable.
27. Candidate-parser, command-sandbox, verifier, source-fetch/parser, and state-store containers all use an explicitly pinned hardened resource/mount/network profile; an authenticated readiness canary proves an actual no-op model exchange plus a brokered command without exposing credential material. `--version` alone is never eligibility evidence.
28. Backend launch environments are built from a closed allowlist rather than `os.environ.copy()`. Poisoned `GIT_*`, `HOME`/`USERPROFILE`, `PWD`, `PYTHONPATH`, `VIRTUAL_ENV`, PATH entries, credentials, and canonical/common-dir/control/host paths cannot cross into a container; container HOME/PATH/TMP and projection paths are backend-native.
29. Cross-transaction `--resume` is disabled. A same-transaction resume may use only a sanitized per-attempt session directory in the runtime projection and only when transaction, clone, capability, provider, and spec digests match. No host profile/session store is mounted; a retry starts a new session.
30. Architect, evaluation, evidence-review, and adversary call sites use disposable or transactional clone contexts. Hostile/unknown analysis uses the same Docker trust tier; trusted read-only Local analysis has an enforced closed tool list with no shell/write/Task/MCP and cannot execute repository code. Missing analysis containment fails closed.
31. Health uses non-agent version/auth-status probes outside any repository and never invokes `--print --dangerously-skip-permissions`. Evolution uses registered disposable analysis/output authority outside canonical and never grants `state/evolution/candidates` as a raw add-dir.
32. Task 1's static provider-spawn inventory and launch embargo remain green. Task 3 extends that inventory for the new Claude/Codex drivers and unit-tests the permanent zero-side-effect authority helper while explicitly recording the still-unmigrated Society/parallel/tournament callers. The repository-wide **transactional zero-bypass assertion and activation of permanent `runClaude` first-statement authority run only in Task 4** after those callers migrate; no Task 3 checkpoint claims that final assertion is already green.
33. In-place state commit preserves surviving nested object identities, all post-boundary callers reacquire by stable ID, and winner/loser or recovery/failure ordering cannot downgrade durable promotion truth.
34. Every promotion persistence/ack failpoint returns typed recovery-only control; no fresh lease, model session, or retry is created.
35. Hostile tracked `.claude/settings*.json`, `.mcp.json`, plugins, hooks, LSP configuration, Codex project configuration/commands, and a clone symlink targeting a credential/runtime path cannot start a process or read a credential-plane goldstone; the driver starts in an empty projected cwd with project/local/user discovery disabled and the broker rejects symlink traversal component-by-component.
36. Crash tests before/after `planned -> registered`, during OS/container creation, after create before PID/container-ID persistence, and before/after start release for watchdog, driver, broker, command sandbox, candidate parser, verifier, source fetch/parser, and the boot-scoped state-store worker leave all resources durably discoverable and quiesceable; no single-handle shortcut can report completion. The state-store worker binds controller generation/watchdog, has a deterministic cleanup locator before create, and must be recovered or quiesced before another generation can open its stores.
37. Every ordinary verified candidate receives an immutable `ReviewReceipt`—semantic review or explicit versioned policy skip—before promotion; no missing/null review link can authorize landing.
38. Trusted-Local authority is revalidated against freshly observed canonical repository/base/task/spec truth before every attempt provision and again as the zero-side-effect first launch operation. Drift/expiry/revocation between selection and provision yields typed unavailability with no clone or runtime side effect. If it occurs after clone provisioning but before launch, no driver/process/model log/session is created; the already-registered clone is durably rejected/checkpointed/quarantined and cleaned or retained by policy, never reused. A kernel-promoted descendant requires a freshly issued exact-base attempt grant.
39. Capability eligibility exact-matches a live `CapabilityEnforcementReceipt`; changing provider binary/auth mode, any launch-plan/image/SBOM/broker/env/mount/security digest, host Docker/kernel fact, expiry, or revocation generation after canary causes typed unavailability until a real canary reissues the receipt.
40. Failpoints before/after credential planning/registration, during secret derivation or channel materialization, before/after issuance and injection, during revocation/expiry, after driver death, and before/after secret-channel destruction leave only non-secret durable metadata; restart removes registered partial artifacts, revokes or expires issued credentials, quiesces the dependent driver, destroys the channel artifact idempotently, and never records credential bytes.
41. A session deadline is clamped to the earliest task/trust/capability/credential expiry. A deterministic race barrier pauses an action after its final authority check but before OS/container start while revocation takes the exclusive admission gate: the action never releases, all Job Object/cgroup members and Docker IDs quiesce, no event appears after the durable revoked generation, and a missing/dead watchdog with a live driver is recovered as containment failure.
42. Pre-spec Claude/Codex elaboration accepts only contained `PreSpecAnalysisAuthority` over the raw-intent-bound immutable read-only snapshot; it cannot receive trusted Local, clone/canonical write, shell, Task, MCP, or promotion authority. Its digest remains untrusted until the outer operator explicitly approves the exact canonical spec bytes, and unavailable containment stops rather than falling back.
43. Post-activation `_runVector` never host-`Popen`s brain-authored acceptance argv. It requires a watchdog-bound `VerificationCommandAuthority` and sends a typed argv request to the credentialless verification container. Plain tests and nested test workers run inside its no-breakaway resource set, but `cmd`/PowerShell/sh/Python/pytest/batch wrappers cannot find provider binaries, credentials, provider config, clone-external paths, or network; attempts to invoke Claude/Codex or a copied API client fail and are receipted. A provider-mediated semantic check is routed through the guarded model driver as a separate review receipt, never disguised as acceptance execution.
44. Pre-spec worker stdout/ANSI flooding, inherited/reopened console attempts, stdin prequeue/races, a surviving descendant, stale approval responses, and same-process capability reuse cannot authorize. Approval begins only after complete worker/resource/credential quiescence, uses a nonce generated afterward on an exclusive child-inaccessible operator channel, and spawns a different terminal-less execution PID whose two one-time capabilities bind that nonce and digest.
45. Before any repository-derived elaboration, discovery, council, planning, replanning, path probe, or static analysis, a no-follow canonical attestation and `PreExecutionSnapshotAuthority` pin the exact base/tree and a standalone immutable snapshot. A credentialless, network-disabled `PreExecutionReadBroker` is the only consumer of snapshot bytes. Poisoned `tools/size_audit.py`, `validate_workflows.py`, `AGENTS.md`, `.repo-map.json`, local/global Git config includes, hooks, filters/textconv/fsmonitor, symlinks/junctions/reparse points, huge/deep paths, and host goldstones cannot execute or escape; missing containment returns typed unavailable rather than reading canonical.
46. Discovery digest, repository grounding, `projectContextBlock`, council context, and path verification accept a bounded `PreExecutionContextReceipt` instead of `work_dir`. Repository scripts are inert data; trusted built-in scanners compute size/workflow facts over brokered bytes, and sterile Git metadata is supplied by receipt. Outputs are canonical, size/depth/path bounded, content-addressed, bound to snapshot/base/spec, and contain only stable repo-relative logical paths—never canonical, disposable-clone, container, credential, control, or runtime-projection absolute paths.
47. Both startup and preamble knowledge refreshes converge on one content-addressed external runtime cache under the attested per-user kernel root. A stale tracked `knowledge/claude_code.md` remains byte-for-byte and mtime identical, canonical stays clean, refresh failures preserve the last complete immutable generation, and generated knowledge enters prompts only through a bounded read-only projection that candidate snapshots cannot stage.
48. Legacy self-referential setup never runs `checkout -B`, creates `.sc-ctx`, or mutates canonical on fresh or resumed runs. On restart, the external anchor invokes only the previously trusted controller's minimal `RecoveryAuthority` entrypoint before snapshot creation; it quiesces registered resources and reconciles journaled ref/index/worktree/TaskState transitions, emits `RecoveryReceipt`, exits, and forces fresh canonical attestation. Crashes at resource registration/start and on both sides of ref/index/worktree commit points prove restart recovery precedes every snapshot/model call. Incremental, self-mod, and pre-PR suites consume an exact proposed/promoted revision plus `VerificationCommandAuthority` and reuse or append universal-verifier receipts; `validation_cache` has no host command runner, and post-seal failure can request a new transaction but cannot revert the promoted tree.
49. Automatic PR publication is typed deferred in this slice: `github.createPullRequest`, its review facade, and phase 4 consume the immutable PromotionReceipt/resulting SHA and return an in-memory `PublicationDeferred` result without host checkout/add/commit/push/`gh`, working-tree diff/snapshot/restore, or daemon publication. Only after that deepest boundary has returned may the already-authorized external `ControllerStateStore` best-effort append an internal deferral receipt; append failure preserves the in-memory result and never reaches the effect. A later claim/apply/ack effect authority may publish that exact SHA without becoming another repository writer.
50. Planner and replanner prompts/specs use backend-neutral repo-relative verify targets. Any absolute host path, `PROJECT_ROOT`, raw `work_dir`, snapshot path, or provider-visible mismatch is rejected or translated through the runtime projection before persistence; the universal verifier resolves typed paths inside its clone.
51. A repository-wide pre/post-transaction host-I/O inventory proves that production orchestration has no raw `Path.read*`, glob/walk, repository-cwd `subprocess`, Git porcelain, validation runner, snapshot/restore, or canonical mutation reachable outside canonical attestation, sterile object plumbing, the snapshot broker, the universal verifier, fenced promotion, or an explicitly separate effect authority. Task 4 activates this assertion together with the first-statement `RunAdmissionAuthority`; there is no legacy, self-ref, council, resume, review, or publication waiver.
52. The Discord `/create-pr` path cannot authorize from TaskState `done|partial`, instantiate a fresh Orchestrator, or reach publication through a second facade. The deepest publisher requires the future non-serializable effect authority; automatic, manual, replayed, copied-state, and direct-call variants all return the same typed deferred result with zero process/network/repository effect.
53. `--repo-url` and Discord external-project ingestion cannot clone or checkout under `PROJECT_ROOT/state` before admission. Only normalized public HTTPS is implemented in this slice; local-path/file-scheme, private, credentialed, or otherwise unprovable sources are typed unavailable before process/directory creation. HTTPS requires a top-level process-local `SourceAcquisitionAuthority`, preregistered fetch/output resources, a closed config-free environment, external quarantine, no checkout/filter/helper, complete local object closure, and the kernel safe materializer before normal attestation/snapshot. It disables proxy/system/user Git config, helpers, redirects by default, LFS, and submodule recursion; its pinned transport resolves and binds a public IP for every explicitly bounded redirect/connection and rejects loopback, private, link-local, multicast, unspecified, metadata-service, and IPv4-mapped/IPv6 equivalents plus DNS rebinding. Authority-bound wall/idle time, wire-byte, disk, pack, object-count, per-object inflated-size, aggregate-inflated-size, tree-entry/depth/path/file-count, and materialization quotas fail before exhaustion; pack/index/fsck and complete closure run inside those bounds. Failure kills the whole process tree, revokes resources, and emits a cleanup receipt for the external quarantine.
54. Post-run SIE maintenance does not auto-start from teardown in this slice. Bootstrap, package installation, model pulls, self-play, and spawned curriculum runs require a future explicit maintenance/effect authority; disabling the automatic call emits a durable deferred maintenance fact and never weakens the separate operator-invoked maintenance command.
55. Browser/native/Gemini-second-brain/live-council execution is typed `ExternalEffectAuthorityUnavailable` at the deepest public driver boundary in this slice. Brain-authored browser/native specs, absolute/relative uploads, omitted or false irreversible flags, arbitrary/localhost/metadata origins, direct ChatGPT/native driver calls, profile/Git inspection, startup `probe`/`startConversation`, `sessionAsk`/`askGemini`, adversary review, and flag/API-key-enabled GPT/Gemini/Groq/Cloudflare/Cerebras paths perform zero import, path stat/read, client/process, UIA, browser, screenshot, profile, network, download, artifact, or external action.
56. Evaluation and outcome runners never create linked worktrees or call the legacy host verifier. Every fixture/evolution candidate gets a standalone disposable clone, exact analysis/verification authority, and universal-verifier receipt; post-run maintenance remains deferred and cannot silently invoke an unguarded evaluation path.
57. The OS-installed anchor compares its protected expected digest/generation before capsule execution. Simultaneously replacing capsule bytes, sidecar manifest, external writable generation, target wrapper/main, cwd, and Python import customization still refuses before target import; direct repository launch and a pre-anchor gateway cannot mint boot authority.
58. The recovery entrypoint is callable only by the external capsule with a live exact-generation `RecoveryAuthority`; direct controller/main/runFull calls, copied handles, persisted receipts, and candidate code fail before journal or repository access. It can finish only an existing journaled transaction, inspect only no-follow hash/type/identity facts for that journal's exact changed-path set, and cannot return content or create a task, lease, snapshot, model call, network request, migration, or new promotion. Any non-journal path read is denied.
59. Every Ollama call crosses one anchor-controlled `LocalModelBroker`. Its endpoint is a pinned loopback address or protected local IPC channel with proxies, redirects, environment routing, and non-loopback resolution disabled; its `LocalModelCapabilityReceipt` binds exact model content digest, manifest/tag, Ollama runtime/binary digest and version, broker policy, run/analysis authority, expiry, and controller generation. A remote/private/metadata host, proxy variable, redirect, DNS retarget, mutable-tag replacement, runtime change, missing authority, or digest mismatch is typed unavailable before snapshot context leaves the controller. Direct `ollama.Client`, raw `/api/*`, and unguarded CLI calls are rejected by the static inventory.
60. Until the durable effect-command wave, every run-originated outbound or host-external mutation is denied at its deepest repository-owned boundary and returned first as a typed in-memory deferred fact. This includes Discord REST/webhook/Cast messages and attachment reads, every bot/cog/view response, Obsidian REST and vault writes/appends, public-tunnel download/spawn/stop, Jerry/remote helpers, browser/native uploads/downloads/screenshots, publication, wipe/restart/retention, and every lower post-run maintenance entrypoint. Direct boundary calls, copied TaskState, flags, and call-site bypasses produce zero effect-facing path read/write, socket, DNS, process, browser/UI, or external effect. Only a subsequent authority-bound append to the pre-attested external `ControllerStateStore` may durably record the deferral; failure to append cannot invoke the effect. The loopback dashboard may expose authority-bound GET/SSE projection only; every POST/control/button handler returns typed unavailable before ControlBus/TaskState mutation, and its token/log state lives exclusively under external controller state.
61. Every mutable controller artifact—TaskState, control/command rows, heartbeats, IPC, receipts, JSONL/telemetry/audit/trajectory/perf records, SQLite/Chroma databases, caches, vault projection, generated knowledge, sessions, Society blackboards, Human Nature stores, and learning/evolution outputs—lives under an anchor-attested external per-repository state root. `jsonl_io`, heartbeat/IPC, retention, compaction, hook telemetry, reflection, ledger/novelty/conviction, psyche/continuity, and maintenance writers accept a live `ControllerStateAuthority` and use component-by-component no-follow create/open, retained directory identities, restrictive ACLs, quotas, durable atomic writes, and hardlink/reparse rejection at the deepest store; they have no target/cwd fallback. Each path-only native engine (SQLite, Chroma, and similar) runs in its own pinned networkless state-store worker with one dedicated pre-created non-authoritative per-engine data subtree writable; journal, receipt, control, authority, credential, runtime, anchor, other-engine, and parent roots are absent, not merely read-only. RPC accepts closed operation and logical-database IDs, never caller paths, and returns normalized signed results for controller-side promotion. Sibling-journal/receipt/runtime and cross-database goldstones prove compromise cannot alter authoritative truth. Target `state/`, logs, vault, `.env`, and overrides are never runtime destinations. After recovery, `LegacyStateMigrationAuthority` first drives a full native handle-relative snapshot of the explicit quota-bound legacy allowlist, rejecting reparse/symlink/mount/multi-link/raced input; the networkless migration container receives only that immutable blob snapshot and emits a content-addressed normalized artifact. Target config/secrets never become live config. Unsafe migration makes legacy resume unavailable. Poisoned target junctions/reparse points/hardlinks cannot cause a read or write, and fenced promotion is the sole target-worktree writer.
62. Production bootstrap/configuration comes only from the anchor-owned protected typed configuration bound into `SingularityBootReceipt`; importing config/settings cannot load target `.env`, repository `sie_overrides.json`, cwd/user environment routing, or target-controlled path/provider/effect flags before admission. Target configuration is brokered inert snapshot context only. Symlinked, oversized, malformed-encoding, duplicate-key, or hostile target config causes no host read/env/path/process/network effect; direct configuration bootstrap and reload paths are covered by the activation inventory.
63. Remote/SSH execution and helpers are wholly typed `ExternalEffectAuthorityUnavailable` in this slice, including requests labeled read-only. Direct backend calls and fabric routing create no socket, DNS lookup, process, credential read, remote command, or output artifact until a future bounded remote-effect authority exists.
64. A successful same-run promotion revokes every old-revision lease and cannot silently widen the initial snapshot authority. Only after complete quiescence, native no-follow attestation of the promoted SHA, a new immutable snapshot, and a persisted/re-read `RunRevisionAdvanceReceipt` may the external kernel derive the next `RunRevisionAuthority`. Unrelated canonical drift requires a fresh operator-approved run. An exact-base trusted-Local grant never follows the revision; without fresh approval, rescheduled work uses the hostile Docker plane or is typed unavailable.
65. The source fetcher's egress is enforced below the application. The host controller has no general network or DNS capability; it resolves each normalized HTTPS hop through the trusted acquisition authority, registers one public numeric IP and port, and installs an engine/firewall rule that permits only that tuple for the one fetch resource. Every redirect closes the old socket/resource, removes the old rule, resolves and validates the next hop on the host, then registers a new tuple before connection. The fetcher connects to that numeric tuple while preserving the normalized URL hostname as TLS SNI/certificate-hostname input and the same normalized hostname plus effective port as HTTP/1.1 `Host` or HTTP/2 `:authority`; numeric-IP, userinfo, duplicate/conflicting Host, and target overrides cannot alter virtual-host selection. It requires a valid OS-trusted chain, validity time, server-auth EKU, and hostname match, and forbids `-k`, custom target CA/client certificates, target TLS config, and plaintext downgrade. The receipt binds URL/HTTP authority, hostname, tuple, TLS version, chain/SPKI evidence, and redirect authority for every hop. Arbitrary socket/RCE canaries inside the fetch container cannot reach loopback, RFC1918/ULA/link-local, multicast, unspecified, metadata endpoints, the Docker host/control plane, DNS, a second public address, or the prior redirect address; shared-IP wrong-Host, wrong-host/self-signed/expired/client-cert/downgrade canaries fail before any source bytes are admitted.
66. `memory.stores.user_prefs` accepts only a closed logical store ID plus live `ControllerStateAuthority`; arbitrary `Path`, `STATE_DIR/..`, env, and cwd fallbacks refuse before construction. `learning.selfplay` and `learning.evolution.selfplay` require both logical state authority and explicit `MaintenanceAuthority` before state lookup or injected launch. `learning.evolution.sie_curriculum` likewise returns `MaintenanceDeferred` before queue construction or `work_launcher.spawn`; its enabled, injected-launch, direct-import, and swallowed-exception paths cannot create work without authority. Disabled, teardown, direct-import, and missing-authority calls perform zero path/process work. `agents.hook_handlers.selfmod` consumes only the sealed immutable hook-boundary projection; `NINE_TO_FIVE_TASK_FILE`, `PROJECT_ROOT`, TaskState/latest fallback, and caller paths cannot influence a read or boundary set. `agents.hook_handlers.obsidian` checks `EffectGuard` before TaskState resolution, note/path/payload construction, or client creation. `notifications.commands` and `notifications.bot.cogs.engagement_cog` refuse at their first boundary while command claim/apply/ack and Discord ingress are disabled; direct calls cannot load TaskState, mutate ControlBus/preferences, respond, or construct effect payloads.

Run:

```powershell
$planPath = 'docs/superpowers/plans/2026-07-13-galaxy-r3-transactional-kernel.md'
$redTests = @(python tools/galaxy_plan_manifest.py --plan $planPath --task 3 --kind red-tests)
if ($LASTEXITCODE -ne 0 -or -not $redTests.Count -or @($redTests | Sort-Object -Unique).Count -ne $redTests.Count) { throw 'Task 3 RED manifest extraction failed' }
$unexpectedGreen = @()
foreach ($test in $redTests) {
  if (-not (Test-Path -LiteralPath $test -PathType Leaf) -or (Get-Item -LiteralPath $test).Length -eq 0) { throw "Task 3 RED test was not written: $test" }
  python -m pytest $test --collect-only -q
  if ($LASTEXITCODE -ne 0) { throw "Task 3 RED test does not collect cleanly: $test" }
  python -m pytest $test -q
  if ($LASTEXITCODE -eq 0) { $unexpectedGreen += $test }
}
if ($unexpectedGreen.Count) { throw "Task 3 RED modules unexpectedly passed: $($unexpectedGreen -join ', ')" }
```

Expected: ordering and receipt tests fail before wiring changes.

### Step 2: Resolve once, provision inside every attempt

Close the executor boundary before rewiring orchestration:

- `ExecutionLaunchAuthority` is an unforgeable process-local token tied to transaction ID, `CloneLease` ownership nonce, real clone root, runner kind, exact capability-enforcement receipt and process-grant nonce, resolved trust receipt ID and grant nonce, issuer/revocation generations, absolute not-after deadline, expected canonical base, registered authority-watchdog resource, and journal phase. The permanent `runClaude` check is its **first executable statement**, before normalization, `_prepareEnv`, filesystem access, logging, session lookup, launcher resolution, or subprocess construction. It revalidates current canonical attestation/base, trust scope/expiry/revocation, capability receipt/grant, watchdog state, and registered resource state; derives the only valid work directory from the token; clamps process timeout to the earliest authority deadline; and rejects a conflicting caller argument. Every brokered or provider pre-tool/process action revalidates the same live generation/deadline. A mutation-capable repository launch without live exact authority raises a typed error; identity/canonical fallback is deleted. Build and test this guard in Task 3, then activate it atomically in Task 4 after the final legacy caller is migrated.
- Delete `writeClaudioMd(..., work)` and any candidate-local generated settings/context. Remove unconditional `--add-dir config.PROJECT_ROOT`; omit it at clone root or map it only to the backend-visible clone. Never pass canonical, its common directory, control root, host settings, host task file, host session store, or host-only launcher path through isolated argv/environment/mounts.
- `RuntimeProjection` creates a minimal per-attempt, hash-manifested bundle outside canonical: allowlisted settings, generated context, a sanitized read-only task/boundary snapshot, a self-contained immutable guard runner, a transaction-scoped session directory, and a separate bounded writable telemetry directory. Generated context is supplied through prompt/system input or a projection path, never a tracked candidate path. Exporters do not mount the projection, so it cannot enter `git add -A` output.
- Replace inherited environments with `buildLaunchEnvironment(plan)`: start empty, add only backend-approved locale/runtime/provider variables, and synthesize backend-native HOME/PATH/TMP/projection paths. Reject inherited `GIT_*`, `PWD`, `PYTHON*`, virtualenv, profile, credential, canonical/common/control, and host-only path values. Settings composition accepts explicit backend-visible project/hook/interpreter/output paths and never derives them from module globals.
- Add a typed `BackendLaunchPlan` to `execution/environment.py`: driver argv/environment, empty driver cwd, backend-visible projection/session paths, closed broker operation schema, resource leases, mounts, egress/resource/security profile, and exact `CapabilityEnforcementReceipt` requirements. Local plans may resolve the host CLI only for an explicitly trusted workload; their receipt cannot satisfy hostile eligibility.
- For Docker-classified mutation, implement a split plane whose credentialed side never sees repository bytes as a filesystem. `CredentialBroker` creates a bounded, redacted, transaction-owned credential lease from the user's existing zero-marginal-cost local CLI authentication; it never mounts the live host profile and destroys the lease after the driver quiesces. `ProviderSafeBoot` launches a pinned Claude/Codex adapter in an empty projected cwd with isolated HOME/CODEX_HOME, project/local/user discovery disabled, safe/bare mode chosen according to the proven auth method, strict explicit broker configuration, slash/skill/plugin/hook/LSP/background-agent discovery disabled, and all built-in tools disabled. The only callable surface is a closed projected broker API: `repo_read`, `repo_list`, `repo_search`, `repo_apply_patch`, and `repo_exec`.
- `SandboxCommandBroker` validates transaction/resource capability, relative path, realpath ownership, no-symlink traversal (`openat`/`O_NOFOLLOW` or platform equivalent), cwd, argv, limits, and operation schema. It executes read/search/write/patch/command operations only in a separate credentialless network-disabled hardened container and records input/output/container digests. The model driver receives bounded results, never a clone mount or raw Docker/socket capability. Candidate `.claude`, `.mcp`, `.codex`, hook/plugin/LSP files therefore remain inert data in the command sandbox.
- Reuse only the TOFU-sealed generic driver/sandbox/fetch/parser/verifier/state-store images and their immutable manifest/config/layer/base/toolchain/package/SBOM/security-profile digests. Exact-final controller entrypoints are read-only mounted from the separately sealed runtime and bound into the launch plan; repo-owned Dockerfiles are reproducibility evidence, never build/install authority. A local readiness gate for each enabled provider proves credential issue/expiry/redaction, safe startup with hostile tracked configuration, one brokered read/write/command, credential absence in the code sandbox, and cleanup. If Claude or Codex cannot pass with the user's existing subscription auth, mark that provider's hostile mutation capability unavailable; do not claim it or inject the live profile/token into a repository-bearing container.
- Use the same hardened non-root, cap-drop, no-new-privileges, read-only-root, seccomp/resource-limited base profile for command, candidate-parser, verifier, source-parser, and state-store containers, with the networked source fetcher isolated by its separate egress policy. Candidate-parser containers see only immutable blob manifests; verifier containers receive only the exact verification clone; the state worker receives only its pre-attested external store mount. None sees canonical/common/control credentials. Readiness performs one authenticated no-op driver exchange and one credential-absence broker canary; a binary `--version` probe is diagnostic only.
- Disable cross-transaction Claude/Codex session resume. Resume is legal only within the same transaction when session, clone, provider, capability, and spec digests match, using the projection's sanitized session directory. A retry/new transaction starts fresh and receives prior receipts as text, never host session storage or stale clone paths.
- Audit every direct CLI call. `platform_core/ops/health.py` becomes a non-agent version/auth-status diagnostic in a neutral external cwd. `learning/evolution/evolver.py` uses registered disposable analysis/output authority outside canonical. Architect/evidence review use either same-tier contained analysis or an enforced no-shell/no-write/no-Task/no-MCP read-only profile; evaluation uses an isolated candidate plus verification clone but never promotes; adversary remediation becomes a new transactional attempt rather than post-seal mutation. No hostile analysis path may fall back to Local.

#### Run admission and the immutable source plane

`main.py` and `Orchestrator.runFull` consume the one-time `RunAdmissionAuthority` issued by the external anchor/capsule before any product startup or repository-derived operation. The authority owns a `PreExecutionSnapshotLease`: exact canonical attestation/base/tree, external standalone object source, credentialless snapshot-container resource, immutable content manifest, deadline/revocation generation, and receipts. Creation uses only the Task 2 no-follow attestation and sterile object plumbing; the first worktree checkout happens inside the pinned credentialless container. A missing/dead watchdog, attestation drift, snapshot mismatch, or unavailable container refuses the run with no canonical fallback.

Before normal controller import, the capsule supplies an anchor-owned immutable typed configuration and a `ControllerStateAuthority` for one no-follow-attested external per-repository root. `platform_core.app_config` never discovers target `.env`, `sie_overrides.json`, cwd files, or user/system proxy/provider routing in production. `app_config.paths` maps TaskState, control/commands, heartbeat, IPC, receipts, logs, databases, cache, vault projection, generated knowledge, sessions, and learning/evolution outputs only beneath the external root; no target environment variable may override it. `ControllerStateStore` is the only file-store primitive. Its native handle-relative API serves authoritative JSON/JSONL/atomic files. Each separately registered pinned networkless `state_store_worker` receives exactly one dedicated non-authoritative per-engine subtree mount; it cannot see the external root parent, journals, receipts, controls, runtime/anchor data, or another engine, and its closed RPC accepts logical IDs rather than paths. Every deepest caller—including hooks, telemetry, audit, terminal IPC, retention, reflection, compaction, Society, Human Nature, memory, and all maintenance modules—must present authority or return typed unavailable before path construction. Existing target `state/`, logs, and vault data are inert legacy input: the host native snapshot plus separate `LegacyStateMigrationAuthority` container may import only a bounded schema-validated artifact before the post-recovery snapshot, then never writes those target paths. Target `.env` and overrides are never migrated as live config. Poisoned target directories and config must be unobserved before snapshot and can never redirect a controller read or write.

Add a closed `PreExecutionReadBroker` in `platform_core.execution.pre_execution`. Its typed operations are bounded repo-relative `read`, `list`, `search`, sterile Git-history/status facts, and trusted built-in static scanners over data. It cannot run repository scripts, arbitrary argv, hooks, filters, helpers, or network. Replace `agents.discovery.digest` calls to `tools/size_audit.py`, `validate_workflows.py`, grep, Git, GitHub CLI, and raw files with broker calls; size/workflow checks are controller-owned algorithms, not imports from the target. `ledger_bridge`, invention seeding, and code-graph construction consume the same snapshot receipt instead of defaulting to `config.PROJECT_ROOT`.

Elaborator grounding/path verification, discovery, council context/logging, project context, planner/critic/horizon-fill prompts, verify strengthening/repair, replanner, playbook, fork policy, architect, and every fallback accept `PreExecutionContextReceipt` or typed runtime-projection paths. They persist only normalized repo-relative logical paths. Any raw `work_dir`, `PROJECT_ROOT`, canonical/snapshot/container absolute path, target `.claude`/`.codex` config, or missing receipt is rejected or produces an explicit bounded unavailable context—never a host read. Council artifacts live under the external kernel root and bind the snapshot/spec receipt; no default logger mkdir/write occurs under `PROJECT_ROOT/state`.

`platform_core.ops.doctor` splits neutral product diagnostics from repository facts. The former run from an empty external cwd with anchor configuration; the latter are supplied by canonical-attestation/snapshot receipts and never invoke raw Git in the target. Startup calls doctor only after admission/snapshot. `work_launcher_readiness` likewise consumes a signed readiness receipt from the capsule instead of resolving an arbitrary `work_dir` and running inherited-environment Git. Remote/SSH backends and Jerry/remote helpers are deepest-boundary typed unavailable in this slice even for caller-labeled read-only work; they cannot resolve a host, read a credential, or start a process/socket.

External `--repo-url`/Discord acquisition uses a top-level operator-bound `SourceAcquisitionAuthority` before any model call. It registers all resources/output before start and accepts only normalized public HTTPS in this slice; local paths/file URLs and private or credentialed sources are typed unavailable before resource creation. A pinned credentialless **networked acquisition container** has only bounded quarantine scratch—no host profile, repository, Docker/control socket, credentials, controller state, or other host mount. Its transport ignores proxy/system/user Git configuration and credential helpers, performs no checkout/filter/LFS/submodule action, resolves and pins a public address for every explicitly capped redirect and connection, and rejects loopback/private/link-local/multicast/unspecified/metadata and IPv4-mapped or IPv6 equivalents on both DNS and connect observations. DNS rebinding, URL userinfo, alternate schemes, ambiguous ports, and cross-origin redirects fail closed. Raw bounded pack artifacts then cross a digest/size manifest into a **different network-disabled parser container**; attacker-controlled pack indexing, decompression, `fsck`, and closure proof never execute as the host user. The parser emits only a bounded canonical relative-path/mode/content-digest manifest plus content-addressed inert blob set and receipt—never a host bind-mounted checkout. Authority-bound wall/idle time, wire bytes, disk bytes, pack count/size, object count, per-object and aggregate inflated bytes, tree entries/depth/path length/file count, and output quotas cover both stages. The host validates that manifest, creates a new no-follow-attested external integration target, and writes inert blobs through the same native handle-relative safe materializer and filesystem-alias policy as Task 2; on Windows only the host kernel holds NTFS directory handles and evaluates reparse/ADS/8.3/case/Unicode truth. No acquisition container can materialize canonical. `SourceAcquisitionReceipt` binds both pinned image/runtime/security digests, resource IDs, raw/verified/blob/manifest digests, quotas, address/redirect observations, native materialization receipt, and cleanup state. Timeout, decompression/graph bombs, malformed packs, quota breach, or cancellation kills both registered resource trees, revokes handles, and durably receipts external-quarantine cleanup. No source byte or checkout enters `PROJECT_ROOT/state`.

Application-level URL checks are not the egress boundary. The host controller itself receives no general network/DNS authority. For each hop, the trusted acquisition authority resolves and validates one public address, registers the exact numeric IP:port plus resource identity, and asks the container engine/OS firewall to install default-deny egress with only that tuple reachable; the container has no DNS route. A redirect first closes and unregisters the old connection/rule, then repeats host-side resolution, policy validation, resource registration, and firewall installation before the next connect. The rule is removed on every terminal path. A compromised fetch binary or arbitrary-socket canary must fail against loopback, private/ULA, link-local, multicast, unspecified, metadata, Docker host/control sockets, DNS, an unregistered public address, and the previous redirect tuple. `SourceAcquisitionReceipt` binds the resolver observation, firewall-rule digest, engine enforcement evidence, tuple lifecycle, and teardown proof for every hop; absent enforcement is typed unavailable.

TLS remains authenticated even though transport connects to a pinned numeric tuple. The fetcher sends the normalized URL hostname as SNI and verifies that hostname against an OS-trusted certificate chain with valid time and server-auth EKU. The HTTP/1.1 `Host` or HTTP/2 `:authority` is independently fixed to that same normalized URL authority and effective port; numeric-IP rewriting is connect-only, while userinfo, target overrides, duplicate/conflicting Host values, and cross-authority reuse are forbidden. It forbids insecure mode, custom target-controlled CA/client certificate/configuration, certificate-name bypass, plaintext downgrade, and TLS renegotiation outside the closed policy. Each redirect receives a fresh hostname/HTTP-authority check and tuple fence. The receipt binds URL authority, HTTP authority, hostname, numeric tuple, negotiated TLS version/cipher policy, chain and leaf/SPKI evidence, validation result, and redirect relationship; shared-IP wrong-virtual-host, wrong-host, self-signed, expired, private-CA, and downgrade canaries admit zero source bytes.

The living-knowledge path becomes `RuntimeKnowledgeCache`: immutable content-addressed generations under the external kernel root plus an atomically advanced current pointer. Both startup and preamble call one idempotent receipt-aware refresh; tracked `knowledge/claude_code.md` is a read-only seed obtained through the snapshot broker, never a write target. `knowledge_base.compress` and `scraper` cannot cold-cache fall back to project/install-root scans; product capability roots and recommendations are explicit bounded controller inputs, and generated knowledge is projected read-only. `app_config.paths` names source and runtime-cache paths separately. Refresh failure retains the last complete generation and records unknown/stale truth.

#### Close every non-CLI and post-seal bypass

Disable legacy browser/native/live-council routes at their deepest public boundaries for this kernel slice. Brain-authored `surface=browser`, Playwright/Chrome profile drivers, GPT-browser seats, Gemini, Groq, Cloudflare, Cerebras, and any external live seat return typed unavailable before browser/session/process/network/artifact creation unless a future implementation supplies the same registered contained analysis/attempt authority and, for irreversible UI actions, effect authority. Contained Claude/Codex and a pinned local Ollama broker remain the zero-marginal-cost intelligence plane. `LocalModelBroker` is created only by the external controller from anchor-owned configuration, accepts only a protected local IPC channel or numerically pinned loopback endpoint, ignores proxy/env/system routing, refuses redirects, and checks the exact model content digest plus Ollama runtime/binary version/digest before issuing a short-lived `LocalModelCapabilityReceipt`. Every orchestration, human-nature, memory, notification, doctor/health, council, and direct `llm_io` Ollama call must present a live run or bounded analysis authority to that broker; raw `ollama.Client`, HTTP `/api/*`, and CLI constructors are denied by the activation inventory. Tag retargeting, remote host/proxy injection, redirect/rebinding, runtime drift, and digest mismatch are typed unavailable before prompt transmission. Extend the static inventory from CLI argv to browser/session/provider/local-model constructors and subprocesses.

`verifier_runner` performs no host `Path.exists`, normalization, glob, or declared-target probe before `VerificationCommandAuthority`; `verification_diff` receives changed-file/staged-diff facts from the immutable revision receipt rather than host Git. `validation_cache` becomes a cache over exact revision, command-policy, image, and verifier-receipt digests—not a host runner. Incremental self-ref, self-mod, pre-PR, evaluation, outcome-runner, and SIE evaluation checks all provision standalone clones and use the universal verifier. Delete linked eval worktrees, canonical test execution, stash/checkout/revert, mutable `git diff HEAD`, and the production `_selfmodGate`/`.sc-ctx` cleanup paths. A failed post-seal observation may schedule a new attempt; it cannot mutate or downgrade the promoted revision.

Adversary and semantic review consume the immutable staged diff/receipt. Remediation is a fresh pre-seal transactional attempt. `github.createPullRequest` is the deepest publication fail-closed boundary: until the next command/effect wave it returns an in-memory `PublicationDeferred` for automatic phase 4, review facades, Discord `/create-pr`, copied TaskState, and direct calls without starting Git, `gh`, network, or a daemon. The deny-by-default `EffectGuard` sits at every deepest repository-owned outbound boundary: Discord REST/webhooks/Cast/attachment loading; every registered slash/cog/view/dynamic interaction response; Obsidian REST/vault mutation; tunnel download/process lifecycle; Jerry/remote helpers; browser/native artifact actions; and wipe/restart/retention delete-move paths. It accepts no commit authority in this slice. The boundary returns a typed in-memory deferral before constructing or reading an effect-facing path, DNS/socket/process/UI object, or external payload. Only afterward may the controller append the internal deferral receipt through the already-authorized external `ControllerStateStore`; that one pre-attested internal append is the sole permitted write and failure degrades to the in-memory result, never to the effect. The external Discord gateway remains listener/ingress-disabled until a later effect-command implementation can claim/apply/ack safely. The loopback web dashboard exposes authority-bound GET/SSE projection only; its deepest POST/control dispatch refuses before `ControlBus` or TaskState mutation and stores token/logs only in the external state root. Every lower SIE/curator/curriculum/promote/release/distill/preferences/lessons path performs the same maintenance guard before database/path/process construction, so direct calls cannot bypass teardown's `MaintenanceDeferred`. `NeutralHostProbe` is the only optional GPU diagnostic: it resolves a pinned trusted `nvidia-smi`, runs from a newly created empty cwd with closed environment/stdin and bounded output/time, and otherwise returns unknown; inherited PATH/cwd execution is forbidden.

Finally, a repository-wide AST/call-graph inventory enumerates production-reachable repo-cwd subprocess/Git/browser/native launch, raw Ollama clients/API/CLI, HTTP/socket/DNS, Discord/bot/webhook sends, Obsidian and tunnel mutations, `Path.read*`, open/glob/walk/stat, worktree/checkout/stash, recursive delete, and network sites from entrypoints through teardown. Each site must resolve to the external anchor/acquisition plane, no-follow attestation/sterile object plumbing, snapshot broker, pinned LocalModelBroker, guarded driver, universal verifier, fenced promotion, or a typed deferred effect. The inventory is deny-by-default and has poison fixtures for scripts, Git config/attributes, symlinks/reparse points, host goldstones, absolute paths, remote/proxied/retargeted Ollama, attachment and vault paths, tunnel downloads, browser flags, resume, council, evaluation, self-ref, Discord publication, and maintenance.

#### Docker provider feasibility gate

Before any Docker-classified production path is enabled, the external controller re-hashes the TOFU-sealed image archive/config/layer/SBOM/runtime/security digests, imports only those exact archives into the local engine under a registered resource, binds the exact-final sealed controller entrypoint digest, and runs provider-specific canaries through the exact `BackendLaunchPlan`; it never asks the target or host Docker daemon to build trust. For Claude and Codex independently, prove: safe boot ignores hostile project/user configuration; no clone/profile mount exists in the driver; the credential lease is bounded, absent from argv and persisted env manifests/logs/receipts, injected only through the adapter's audited secret channel, and deleted; only the explicit broker surface is callable; one real subscription-authenticated no-op plus brokered repository edit/test completes; the command container cannot observe the credential goldstone. Persist the full content-addressed `CapabilityEnforcementReceipt` only for providers that pass. Production exact-matches and revalidates it immediately before launch. A skipped/failed/stale canary produces typed unavailability and keeps the route disabled—never an `available` Boolean or optimistic mock-backed capability claim.

Replace subtask-scoped provisioning with two seams:

- `resolveExecutionPolicy(...)`: pure selection/classification performed once; it translates the legacy Worktree preference to `requested=worktree, runner=local, landing=clone` **before** raw fabric routing, refuses mutating Remote before resources exist, selects a Local or Docker runner, and always requires clone landing for mutating attempts without weakening the request. Mandatory clone landing is kernel safety, not an optional fabric feature, so this legacy mapping remains safe when the fabric feature flag is off;
- `provisionForAttempt(policy, attempt_id, ...) -> ExecutionContext`: called inside each retry and never reused by another attempt.

For every attempt, provisioning follows this order:

1. reconcile unresolved/unacknowledged attempt-journal records under recovery/merge locks;
2. allocate a unique attempt/transaction ID;
3. reobserve canonical truth and revalidate/reissue the exact-base operator grant, then provision a fail-closed external `CloneEnvironment` landing lease for every mutating attempt, with Local runner kind only for a live trusted-Local grant (including an authorized legacy Worktree preference) and split-plane Docker runner kind for hostile/unknown work;
4. expose the **execution** clone directly only to explicitly trusted Local. For Docker, mount it only into credentialless command/export sandboxes; the credentialed driver receives an empty projected cwd and broker capabilities, never the clone. For every origin, the separate verification clone mounts only into the universal credentialless verifier;
5. adopt a caller-supplied `CloneLease` only after typed ownership/isolation validation and only for that single attempt; an arbitrary checkout path is refused;
6. durably register the ready clone lease before commands launch and journal a separate `RuntimeResourceLease` before each resource can act: every Docker resource first persists deterministic name/labels and every Local resource first persists its no-breakaway Job Object/cgroup cleanup handle, then creation occurs stopped/suspended, actual container/PID identity is persisted, and only then may start release; credential handoff similarly persists non-secret lease/channel cleanup identity before derivation/materialization, then records `issued -> injected`; and an authority watchdog owns the registered OS boundary before driver release. Credential lease, watchdog, driver, broker, command sandbox, candidate parser, and verifier transition independently. Source fetch/parser use the same registration under `SourceAcquisitionAuthority`; the generation-scoped state-store worker is registered before controller import. Recovery destroys partial channels/resources, revokes credentials, and quiesces/destroys resources in dependency-safe order;
7. on partial provisioning failure, quiesce/finalize inner resources, export/stage/checkpoint candidate content with a create-only ref, and persist recovery truth;
8. expose only the inner clone execution directory while retaining `CloneEnvironment` and its handle as sole landing authority.

Inner completion/teardown must run before candidate preparation. Neither Local nor Docker has a linked-worktree `.git` pointer; Docker additionally cannot see canonical/common-dir/control mounts. Only host-side `CloneEnvironment` kernel code may export/stage/checkpoint, create a staged revision, or promote canonical.

### Step 3: Add quiet typed lifecycle helpers

In `platform_core/execution/wiring.py`, replace fire-and-forget teardown helpers with:

- `prepareQuietly(...) -> PreparedFinalization`
- `completeQuietly(...) -> FinalizationReceipt`

They log causal detail but never erase failure truth. Keep a compatibility helper only if unmigrated callers require it.

### Step 4: Use one idempotent TaskState acknowledgement helper

Add `persistAttemptTransaction(...)` and use it from both normal completion and recovery:

1. validate the journal phase, exact transaction ID, receipts, and requested attempt/subtask outcome;
2. derive status through one monotone receipt reducer: any durable successful `PromotionReceipt` dominates retry, `not_selected`, rejection, and later-attempt failure records; `failed` is legal only when no promoted or unresolved-promotion truth exists; loser/retry outcomes remain attempt history and cannot downgrade the subtask;
3. while holding the orchestrator state lock, reacquire task/subtask exclusively by stable ID, deep-copy the complete `state.data`, idempotently insert the linked immutable receipt chain, and validate it without mutating the live object;
4. for a durable promotion, place `promotion_persistence_pending`—not `done`—plus the exact receipt chain in the candidate snapshot; for non-promoted attempts, place only the receipt-derived attempt/terminal outcome allowed by the reducer;
5. persist the candidate snapshot through `task_io.saveDataSnapshot(...)`. Then apply that same validated delta to the live graph **in place** while the lock remains held, preserving the identity of surviving task/subtask dicts and lists; never replace `state.data`. Audit retained nested references and convert worker/batch ownership to stable IDs plus reacquisition after every persistence boundary;
6. only after the first snapshot save succeeds, durably set journal `task_state_acknowledged=True`;
7. for a promoted transaction, build and atomically persist a second validated snapshot that changes only `promotion_persistence_pending -> done`, then apply that delta in place. A crash after acknowledgement but before this final state save is recovery-only and reconciliation completes it without another model launch;
8. after the final `done` snapshot is durable and applied in place, durably set journal `terminal_state_persisted=True`. If the flag write fails, recovery observes the already-done transaction ID/status and idempotently flips only the flag;
9. if the first save or acknowledgement fails after durable promotion, return typed `PromotionPersistencePending`; stop retry/batch scheduling and permit only receipt attachment/ack/final-state reconciliation. If the first save fails, discard the copy and leave live memory/disk unchanged. If acknowledgement fails, disk/live remain pending and replay retries only acknowledgement. Never report terminal success from either path;
10. if the final `done` save or terminal-flag transition fails, retain recovery-only truth and reconcile it; do not launch, provision, or classify generic failure. A later unrelated save cannot leak an uncommitted state mutation.

Attempt failures that will retry are persisted as attempt outcomes without terminal subtask failure. Exhaustion may persist terminal `failed` only through the monotone reducer. Add tests for a successful save with a formerly retained subtask reference, two parallel persistence calls, winner-then-loser ordering, recovered promotion after a stale failure record, and every persistence/ack/final-flag failpoint—including `done` durable but flag false. Exactly one model invocation, transaction, and clone may exist when promotion is already durable.

### Step 5: Add exact-revision verification

Add a helper such as `verifyPreparedRevision(...)` that:

1. fails if verification path or proposed revision is absent;
2. calls `env.preparedChangesIntact()` before verification;
3. validates that the no-checkout verification clone's `.git` and common directory are private, its bounded generated loose-object manifest and explicit shallow boundary contain the proposed SHA/tree/blob closure, and no remote/alternate/canonical/control path remains;
4. provisions a **new** pinned credentialless/network-disabled/capability-dropped/no-new-privileges verification container for every candidate origin, with read-only root and only the verification clone plus bounded scratch mounted; it issues a process-local `VerificationCommandAuthority` bound to transaction, proposed SHA, container/resource IDs, mount/env/image digests, watchdog generation, command policy, and deadline;
5. checks out `prepared.proposed_revision` inside that container, proves HEAD/index/tracked worktree start at the exact SHA, and records runner/container identity;
6. calls the refactored verifier with an injected typed broker runner and clone-confined path resolver. `_runVector` validates `VerificationCommandAuthority` before any path/process action and submits argv to the container; it never host-`Popen`s acceptance code. Delete `_normalizeWorkDir`-style fallback to `INSTALL_ROOT`/canonical: an acceptance target absent from the verification clone fails. Changed-file/declared-target evidence comes from the immutable staged diff/tree via `SterileGit`, while clone integrity/tool execution uses absolute trusted container tools rather than candidate PATH/config;
7. catches checkout, verifier, timeout, containment, or teardown exceptions as a failed `RevisionVerificationReceipt`, never as a fallback;
8. quiesces the verification runner, then proves verification-clone HEAD/index/tracked files still name the proposed SHA, records any untracked test artifacts, and calls staged-revision integrity again;
9. records `verified_revision=prepared.proposed_revision`, `scope=isolated_verification_clone`, runner kind, and evidence digest only when all checks pass.

Do not accept a Boolean detached from an exact revision or execution tier. Escape canaries for both Local- and Docker-origin candidates add acceptance code that attempts to touch a host goldstone, canonical ref/common-dir, journal, the prior execution container, or invoke Claude/Codex through direct argv, `cmd`/PowerShell/sh/Python/pytest/batch wrappers, renamed binaries, or a copied network client. Every host/provider/credential/network path is absent or denied while an ordinary test and nested test worker still run. If the pinned credentialless verification container is unavailable, **every** origin is typed-unavailable rather than verified on the host. Provider-mediated semantic verification is a separate guarded review-driver call that emits a `ReviewReceipt`; it is never an acceptance command.

### Step 6: Put the full lifecycle inside the retry loop

Refactor `_runAttemptLoop` so the lifecycle surrounds **one** attempt, not the whole subtask:

1. create a unique attempt ID and provision its standalone candidate clone plus selected inner runner;
2. execute exactly one candidate attempt;
3. complete and tear down/quiesce the inner runner into that candidate checkout;
4. export accepted changes, prepare the object-only staged revision, and build its fresh no-link verification clone;
5. verify the exact proposed revision through the fresh universal credentialless verification container while preserving the candidate's original trust tier only as receipt evidence;
6. resolve the review policy over immutable staged/verification evidence and persist either a trust-tiered `ReviewReceipt` or explicit versioned policy-skip receipt; material findings reject or request a fresh repair attempt rather than mutating the sealed candidate;
7. complete with promotion only when verification and review policy passed, otherwise quarantine/reject;
8. persist the attempt transaction through the idempotent TaskState-then-journal acknowledgement helper;
9. on successful durable promotion, stop retrying and materialize terminal `done`;
10. on `PromotionPersistencePending`, stop immediately and enter reconciliation-only control flow; before any later provisioning, reconciliation short-circuits when the subtask already has durable promoted truth;
11. on retryable failure with no promoted/unresolved-promotion truth, prove candidate/verification clone and staged-artifact cleanup or durable preservation, discard the context, and start a **fresh** context from current canonical truth;
12. after retry exhaustion, persist terminal failure without reusing a rejected checkout.

Exception paths use a mandatory nested `finally`: first enumerate and quiesce every role-tagged runtime resource in dependency-safe order, then snapshot/checkpoint/reject the outer clone lease. If any credential revocation/destruction or watchdog/driver/broker/sandbox/candidate-parser/verifier/source-parser/state-worker quiescence/collection cannot be proven, preserve all resource/clone artifacts, record recovery failure, and do not remove or reuse the lease. Only after the complete resource set is quiescent may outer rejected preparation/completion checkpoint useful work. A failed cleanup cannot overwrite a more important execution or verification error, but is retained in an append-only receipt.

Carry retry feedback as immutable diagnostics and receipt references. Never use attempt N's rejected filesystem tree as attempt N+1's base. If canonical moved because another verified transaction promoted between attempts, the next attempt records that new expected SHA explicitly.

### Step 7: Enforce post-seal immutability

Once `resulting_revision == verified_revision`, no callback in the attempt path—including adversary remediation, evidence review, runner-up graft, or evaluation—may mutate canonical files. Follow-on improvement ideas become proposals for a new clone-staged-verification attempt with a new receipt. Analysis-only callbacks run in disposable clones under the resolved trust tier: hostile/unknown uses the contained driver/broker plane, while trusted Local is permitted only with a mechanically enforced no-shell/no-write/no-Task/no-MCP tool set. They return text/evidence, never filesystem effects, and missing containment never falls back.

### Step 8: Verify and commit

Run:

```powershell
python -m pytest tests/execution/test_executor.py tests/execution/test_executor_stream.py tests/execution/test_executor_env.py tests/execution/test_executor_session_lock.py tests/execution/test_execution_security.py tests/execution/test_execution_docker.py tests/execution/test_sandbox_broker.py tests/execution/test_credential_broker.py tests/execution/test_provider_safe_boot.py tests/execution/test_runtime_resource_recovery.py tests/execution/test_galaxy_images.py tests/execution/test_attempt_journal.py tests/execution/test_attempt_crash_matrix.py tests/execution/test_promotion_authorization.py tests/execution/test_receipts.py tests/execution/test_execution_trust.py tests/control/test_execution_trust_authority.py tests/control/test_operator_launch.py tests/review/test_verification.py tests/execution/test_verifier_runner.py tests/execution/test_verification_diff.py tests/review/test_analysis_isolation.py tests/platform/test_health_collect.py tests/evolution/test_evolution_evolver.py tests/execution/test_launch_guard.py tests/execution/test_authority_watchdog.py tests/execution/test_runtime_projection.py tests/execution/test_pre_execution_isolation.py tests/execution/test_verification_isolation.py tests/orchestration/test_execute_mixin_env.py tests/execution/test_execute_mixin_teardown.py tests/orchestration/test_staged_finalization.py tests/control/test_attempt_state_transaction.py tests/platform/test_main_cli.py tests/execution/test_dry_run.py tests/test_main_elaboration.py tests/test_validation_cache.py tests/evolution/test_knowledge.py tests/execution/test_github_pr_gate.py tests/execution/test_pr_feedback_async.py tests/execution/test_external_project.py tests/execution/test_work_launcher.py tests/execution/test_browser_executor.py tests/execution/test_chatgpt_browser_driver.py tests/notifications/test_runs_cog.py tests/evolution/test_selfmod.py tests/evolution/test_selfmod_runner.py tests/control/test_safety_gate_divergence.py tests/evolution/test_sie.py tests/orchestration/test_discovery_digest.py tests/orchestration/test_discovery_facade.py tests/orchestration/test_invention_seeding.py tests/orchestration/test_code_graph.py tests/orchestration/test_plan_project_context.py tests/orchestration/test_planning_projection.py tests/orchestration/test_pre_execution_council_seam.py tests/planning/test_pre_execution_council.py tests/planning/test_pre_execution_council_seam.py tests/orchestration/test_elaborator.py tests/orchestration/test_elaborator_grounding.py tests/orchestration/test_run_loop_replan_mixin.py tests/orchestration/test_execute_quality_gate.py tests/orchestration/test_horizon_fill.py tests/orchestration/test_orch_core_bugs.py tests/orchestration/test_execcwd_fabric.py tests/orchestration/test_control_review_mixin.py tests/orchestration/test_subtask_files_touched.py tests/evolution/test_playbook.py tests/orchestration/test_fork_policy.py tests/execution/test_eval_runner.py tests/evolution/test_outcome_evaluation.py tests/slow/test_outcome_lifecycle.py tests/orchestration/test_outcome_evaluation_verify.py tests/platform/test_doctor.py tests/platform/test_config_bootstrap.py tests/execution/test_evidence_gate.py -q
if ($LASTEXITCODE -ne 0) { throw 'Task 3 focused tests failed' }
python tools/dev.py lint platform_core/orchestration/execute_mixin.py platform_core/execution/wiring.py agents/execution/executor.py agents/review/verification.py state/task_schema.py
if ($LASTEXITCODE -ne 0) { throw 'Task 3 lint failed' }
$devToolRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) '9to5\galaxy-dev-tools'
$devPython = (python tools/bootstrap_galaxy_dev_tools.py --lock bootstrap/galaxy_launcher/dev_tools.lock.json --root $devToolRoot --offline --only-binary --require-hashes --print-python-only).Trim()
if ($LASTEXITCODE -ne 0 -or -not $devPython -or -not (Test-Path -LiteralPath $devPython -PathType Leaf)) { throw 'Pinned GALAXY development typechecker is unavailable' }
$mypyVersion = (& $devPython -m mypy --version).Trim()
if ($LASTEXITCODE -ne 0 -or $mypyVersion -notmatch '^mypy 2\.3\.0(?: |$)') { throw "Unexpected pinned mypy version: $mypyVersion" }
& $devPython tools/dev.py typecheck platform_core/orchestration/execute_mixin.py platform_core/execution/wiring.py agents/execution/executor.py agents/review/verification.py state/task_schema.py
if ($LASTEXITCODE -ne 0) { throw 'Task 3 typecheck failed' }
$planPath = 'docs/superpowers/plans/2026-07-13-galaxy-r3-transactional-kernel.md'
function Get-GalaxyManifest { param([int[]]$Tasks, [string]$Kind)
  $taskArgs = @(); foreach ($task in $Tasks) { $taskArgs += @('--task', [string]$task) }
  $paths = @(python tools/galaxy_plan_manifest.py --plan $planPath @taskArgs --kind $Kind)
  if ($LASTEXITCODE -ne 0 -or -not $paths.Count -or @($paths | Where-Object { -not $_ }).Count) { throw "GALAXY manifest extraction failed for $Kind" }
  if (@($paths | Sort-Object -Unique).Count -ne $paths.Count) { throw "GALAXY manifest emitted duplicate $Kind paths" }
  return $paths
}
$manifestTests = @(Get-GalaxyManifest @(3) tests)
$manifestPython = @(Get-GalaxyManifest @(3) python)
$manifestProduction = @(Get-GalaxyManifest @(3) production-python)
function Invoke-GalaxyChunks { param([string[]]$Paths, [string]$Mode, [string]$Label)
  for ($offset = 0; $offset -lt $Paths.Count; $offset += 40) {
    $last = [Math]::Min($offset + 39, $Paths.Count - 1); $chunk = @($Paths[$offset..$last])
    switch ($Mode) { 'pytest' { python -m pytest @chunk -q } 'compile' { python -m compileall @chunk } 'lint' { python tools/dev.py lint @chunk } 'typecheck' { & $devPython tools/dev.py typecheck @chunk } default { throw "Unknown GALAXY check mode: $Mode" } }
    if ($LASTEXITCODE -ne 0) { throw "$Label failed for manifest chunk $offset..$last" }
  }
}
Invoke-GalaxyChunks $manifestTests pytest 'Task 3 complete manifest tests'
Invoke-GalaxyChunks $manifestPython compile 'Task 3 complete manifest compile'
Invoke-GalaxyChunks $manifestPython lint 'Task 3 complete manifest lint'
Invoke-GalaxyChunks $manifestProduction typecheck 'Task 3 complete manifest typecheck'
git diff --check
if ($LASTEXITCODE -ne 0) { throw 'Task 3 diff check failed' }
```

Do **not** commit or activate the permanent `runClaude` guard yet. Task 3 and Task 4 form one atomic activation wave: Task 3 may be verified in the working tree, but the global first-statement guard and repository-wide no-bypass assertion land only after every Society/parallel/tournament caller is migrated in Task 4. This avoids both a broken intermediate `main` and a temporary legacy-authority bypass.

```powershell
git diff --check
if ($LASTEXITCODE -ne 0) { throw 'Task 3 pre-activation diff check failed' }
git status --short
if ($LASTEXITCODE -ne 0) { throw 'Task 3 pre-activation status failed' }
```

Keep retry policy in `execute_mixin.py`, but route the one-attempt execution/finalization seam through the existing `execute_attempt_mixin.py`; do not create a second hidden retry loop.

---

## 6. Task 4 - Put Society, parallel batches, and tournaments under one promotion authority

**Files**

- Modify: `platform_core/orchestration/solution_space.py`
- Modify: `platform_core/orchestration/branch_runner.py`
- Modify: `platform_core/orchestration/winner_merge.py`
- Modify: `platform_core/orchestration/judge_panel.py`
- Modify: `platform_core/orchestration/run_loop.py`
- Modify: `platform_core/orchestration/run_loop_mixin.py`
- Modify: `platform_core/orchestration/fork_seams.py`
- Modify: `platform_core/orchestration/society/society_batch.py`
- Modify: `platform_core/orchestration/society/coordinator.py`
- Modify: `platform_core/orchestration/society/worker.py`
- Modify: `platform_core/execution/backends/worktree.py`
- Modify: `platform_core/runtime/worktree.py`
- Test: `tests/orchestration/test_solution_space.py`
- Test: `tests/orchestration/test_solution_space_generational.py`
- Test: `tests/orchestration/test_branch_runner.py`
- Test: `tests/orchestration/test_winner_merge.py`
- Test: `tests/orchestration/test_judge_panel.py`
- Test: `tests/orchestration/test_society_batch.py`
- Test: `tests/orchestration/test_society_coordinator.py`
- Test: `tests/orchestration/test_society_worker.py`
- Test: `tests/orchestration/test_society_off_invariance.py`
- Test: `tests/orchestration/test_fork_seams.py`
- Test: `tests/execution/test_worktree_batch.py`
- Test: `tests/orchestration/test_execute_mixin_fork_wiring.py`
- Add: `tests/orchestration/test_transactional_parallel.py`
- Add: `tests/orchestration/test_selection_recovery.py`
- Add: `tests/execution/test_launch_guard_activation.py`

### Step 1: Add parallel-chain failing tests

Prove:

1. All outer parallel clone leases share one canonical base before launch, or the batch falls back safely.
2. The first candidate failing staged verification is rejected without moving canonical.
3. A second disjoint candidate can prepare against the unchanged expected SHA and promote successfully only when every earlier processed candidate was rejected and canonical therefore remains at the shared base.
4. After the first successful promotion, `expected_target_revision` advances only to that receipt's `resulting_revision`; every unprocessed or returned lease/artifact bound to the old shared base is immediately invalidated, quiesced, quarantined, and rescheduled only after a run-revision advance.
5. A preparation or merge failure replaces any earlier isolated `passed=True` truth with a precise failed verification/finalization result.
6. Parallel crash recovery persists the checkpoint receipt; it is not discarded after cleanup.
7. No later candidate depends on a rejected revision.
8. Parallel and solution-space branch runners execute one attempt per lease; any retry or old-base survivor is rescheduled with a fresh lease/transaction from current canonical truth only after the external kernel issues the next `RunRevisionAuthority`.
9. The run loop's earlier Society gate cannot bypass transactional wiring: every worker receives one registered private clone/launch authority and never the shared `_work_dir`.
10. Society workers return candidate/inner-runner receipts to the batch owner; they do not host-verify, promote, or persist terminal subtask status themselves.
11. If Society clone/authority wiring is unavailable, the Society path fails closed or is disabled before workers launch; it never silently executes against canonical.
12. Global guard activation occurs only after all ordinary, Society, parallel, solution-space, health, evolution, architect, reviewer, evaluation, and adversary paths carry typed authority; a repository-wide inventory has no temporary waiver.
13. A durable promotion followed by TaskState save/ack failure stops the batch in recovery-only mode. No remaining worker, retry, or new lease launches; loser dispositions are preserved for reconciliation.
14. Every promotable parallel, Society, and tournament candidate has a durable semantic or explicit versioned policy-skip `ReviewReceipt`; a missing/null review link is ineligible for selection or promotion.

Run the complete Task 4 RED set one module at a time before changing production code; a collection error is not an acceptable red result:

```powershell
$planPath = 'docs/superpowers/plans/2026-07-13-galaxy-r3-transactional-kernel.md'
$redTests = @(python tools/galaxy_plan_manifest.py --plan $planPath --task 4 --kind red-tests)
if ($LASTEXITCODE -ne 0 -or -not $redTests.Count -or @($redTests | Sort-Object -Unique).Count -ne $redTests.Count) { throw 'Task 4 RED manifest extraction failed' }
$unexpectedGreen = @()
foreach ($test in $redTests) {
  if (-not (Test-Path -LiteralPath $test -PathType Leaf) -or (Get-Item -LiteralPath $test).Length -eq 0) { throw "Task 4 RED test was not written: $test" }
  python -m pytest $test --collect-only -q
  if ($LASTEXITCODE -ne 0) { throw "Task 4 RED test does not collect cleanly: $test" }
  python -m pytest $test -q
  if ($LASTEXITCODE -eq 0) { $unexpectedGreen += $test }
}
if ($unexpectedGreen.Count) { throw "Task 4 RED modules unexpectedly passed: $($unexpectedGreen -join ', ')" }
```

### Step 2: Migrate outer parallel finalization

For every parallel candidate attempt:

1. allocate a unique transaction and fresh lease at the shared batch base; branch-local retry loops are disabled;
2. construct and pass a validated attempt context through `CloneEnvironment.handleFromLease()`, with candidate completion explicitly deferred to the batch owner;
3. require the one-attempt path to finalize its inner runner but leave its candidate lease untouched;
4. prove the candidate lease, native snapshot, parser manifest, and current `expected_target_revision` all still name the unchanged shared batch base, then prepare the object-only staged revision against that base;
5. verify the exact proposed SHA in its fresh universal credentialless verification container, retaining branch origin only as receipt evidence;
6. generate, persist, and re-read the required semantic or explicit versioned policy-skip `ReviewReceipt`; a material finding rejects the candidate and a missing/null link fails closed;
7. complete promotion or rejection without acknowledging yet, linking the exact review receipt;
8. advance expected SHA only after successful promotion, then atomically close batch admission and invalidate/quiesce/quarantine every remaining lease, snapshot, parser output, staged ref, verification, and review bound to the old base;
9. invoke and successfully finish the shared `persistAttemptTransaction()` helper, which copy-on-write saves all receipts/status, acknowledges the journal, persists terminal state, and proves no mandatory reconciliation or cleanup flag remains; a crash after acknowledgement but before terminal persistence stays recovery-only;
10. only then require the external kernel's complete old-base quiescence, no-follow re-attestation, new immutable source snapshot, and persisted/re-read `RunRevisionAdvanceReceipt`; reschedule retryable failures and old-base survivors as new transactions/leases only after that receipt, never by reusing or rebasing the prior checkout.

If promotion is durable but persistence/acknowledgement is pending, return `PromotionPersistencePending`, stop the entire batch, and reconcile only. Do not provision a replacement or continue to a model-bearing branch. Receipt reduction is monotone: later rejected or `not_selected` attempts append history but cannot change a promoted subtask from `done`.

If preparation or verification fails, canonical remains at the prior shared base and the next candidate from that same base may still be attempted. The first successful promotion ends the old-base batch; there is no disjoint-candidate chaining, host rebase, or three-way manifest replay in this wave. If the canonical compare-and-swap fails, stop the chain because the authority boundary changed externally.

### Step 3: Migrate the earlier-selected Society path

`run_loop_mixin.py` owns `_societyGate`/`_handleSocietyBatch` and evaluates the Society path before the ordinary parallel path; `run_loop.py` composes it. Migrate both explicitly rather than relying on worktree-symbol discovery:

1. the coordinator asks the same pure policy resolver for each ready subtask and provisions one fresh `ExecutionContext`/transaction through `provisionForAttempt()`;
2. the worker receives only the private clone work directory plus valid launch authority, executes exactly one candidate attempt, quiesces its inner runner, and returns `CandidateResult`/execution diagnostics to the batch owner;
3. the worker never receives shared canonical `_work_dir`, calls the host verifier, promotes, or writes terminal `done`/`failed`; progress updates cannot imply landing truth;
4. while canonical remains at the shared base, the batch owner serially snapshots/parses/stages a returned candidate only when every lease/snapshot/parser receipt exact-matches that base, verifies in a fresh universal credentialless verification container, records execution origin separately, generates and durably re-reads its semantic or explicit versioned policy-skip `ReviewReceipt`, then completes promotion/rejection with that exact link and invokes `persistAttemptTransaction()`;
5. the first promotion ends the old-base batch: remaining workers/resources are quiesced, their leases/artifacts/receipts are quarantined as stale, and only after a `RunRevisionAdvanceReceipt` may the work be rescheduled with fresh clones from the new canonical SHA; disjoint old-base candidates never chain;
6. journal records keep the canonical task ID independent of any worker/scratch ID so startup recovery always finds the real TaskState;
7. any missing authority, unsupported backend, active worker at recovery, or ownership mismatch preserves artifacts and fails closed. There is no shared-tree fallback.

Add tests at both the `run_loop` gate and worker/coordinator layers so flag combinations cannot reorder around this authority boundary.

### Step 4: Add solution-space environment-preservation tests

Prove:

1. Backend policy is resolved before provisioning a normal outer context.
2. Only an eligible Local-runner policy at canonical root may choose solution-space as the outer candidate producer; a legacy Worktree preference is eligible only through its explicit Local-runner/private-clone mapping.
3. When solution-space is chosen, it provisions the private clone leases itself; the normal outer lease is not also created.
4. Docker and already-isolated execution bypass solution-space and use the ordinary fresh-per-attempt context factory; mutating Remote is typed-refused before either path provisions resources.
5. Forking is disabled when `exec_cwd` is already an outer isolated clone.
6. A failed solution-space clone lease does not fall back to shared canonical execution.
7. There is exactly one candidate clone layer, no linked worktree command surface, and one promotion authority on every path.

This slice deliberately gives every model-executed branch the same standalone-clone Git boundary while retaining explicitly classified Local as a trusted runner and the split credential-plane/credentialless-Docker sandbox as the hostile-workload tier. A later capability wave may add provider-independent OS isolation to trusted Local; until then it cannot inherit hostile eligibility.

Reorder the fork decision ahead of normal `provisionForAttempt()` only for this eligible Local-runner case. Solution-space then owns multiple one-attempt `CloneLease` candidates and uses Local merely as the command runner inside each clone. Every other case uses the Task 3 fresh context factory and remains linear. This preserves tournaments without letting an already-provisioned lease be discarded, nested, or reused by a retry.

### Step 5: Migrate solution-space branch contracts

Update the branch-isolation protocol and null backend to use typed clone leases and results. Keep compatibility names only at old import boundaries. `BranchResult` carries:

- its lease when provisioned;
- checkpoint/recovery receipt on crash;
- preparation, exact universal-verifier authority-bound verification, and semantic or explicit versioned policy-skip review receipts for every completed branch, plus finalization receipt after winner/loser disposition. A branch with a missing/null review link is never eligible.

`_makeRunOneBranch` fails if the isolation lease is unavailable. On crash it checkpoints and attaches recovery truth rather than constructing an empty recovery path.

Each branch lease executes exactly one attempt. A branch-level retry becomes a new `BranchResult` with a new lease/transaction and may consume prior diagnostics, but never reopens the prior checkout. Every journal record stores the canonical task ID separately from the throwaway fork-state ID.

### Step 6: Stage and verify every branch, then promote one winner

Candidate judging cannot consume an ungrounded clone-side success headline. Before `judge_panel.factsGate`:

1. quiesce every branch's inner runner;
2. object-stage every surviving branch at the shared expected SHA and build its no-link verification clone;
3. exact-verify every staged SHA through its own universal credentialless verification container, retain branch origin as receipt evidence, and attach the `RevisionVerificationReceipt` to `BranchResult`;
4. generate, persist, and re-read a semantic or explicit versioned policy-skip `ReviewReceipt` for every verification-passing branch; reject/quarantine material findings and treat a missing/null receipt as ineligible;
5. reject, quarantine, persist, acknowledge, and clean every crash/preparation/verification/review failure before judging;
6. pass only exact verified and non-null reviewed receipt chains into `factsGate`, then choose among eligible evidence-bound candidates;
7. before any promotion, persist and re-read a content-addressed `SelectionReceipt` binding batch ID, complete candidate/eligible sets, every verification/review receipt ID, evidence and judge-policy digests, winner transaction, and every loser's `not_selected` disposition; durably link that receipt and planned disposition into every branch journal. The receipt alone is non-authoritative until all journal links are durable;
8. recheck the winning staged ref/integrity and promote only that already-verified and reviewed SHA, linking the exact ReviewReceipt and SelectionReceipt from its PromotionReceipt;
9. copy-on-write persist the winner receipt/status, acknowledge its journal, and finish the pending-to-done/terminal-flag transition;
10. reject/quarantine every non-winning eligible branch according to the precommitted selection receipt and persist/acknowledge its explicit `not_selected` attempt history before cleanup. The monotone reducer preserves winner `done`; if winner persistence is pending, retain already-durable loser dispositions and enter reconciliation-only mode before any additional state mutation.

If canonical changes externally after branch verification, do not reuse the evidence against a restaged SHA: reject or restage the winner against the new expected revision and run a fresh universal credentialless verification before any CAS.

Crash tests stop after SelectionReceipt persistence, after each branch-journal link, after winner ref CAS, and between loser dispositions. Recovery first completes/validates selection linkage, then recognizes the winner and replays each loser as `not_selected`; it never guesses `cas_refused` merely because canonical moved to the selected winner.

There is no linear fallback on a contaminated canonical tree because verification failure never mutates canonical. A linear fallback is permissible only after a clean rejection and only if policy still allows it.

### Step 7: Remove post-seal mutation

Add a `_sealedRevision`-style guard and tests proving:

- adversary remediation is not invoked after the verified revision has been promoted;
- runner-up grafting does not mutate canonical after seal;
- both mechanisms may emit a deferred proposal/new-attempt request instead.

If runner-up grafting is valuable, it must become a fresh transactional candidate with its own preparation, verification, and promotion receipts in a later wave.

### Step 8: Activate the global launch boundary

Only after every call path above passes its focused migration test, replace the inactive embargo with the permanent `RunAdmissionAuthority` at the external-controller entrypoint, its independent first-operation revalidation in `runFull`, the `ExecutionLaunchAuthority` first statement in `runClaude`, and the repository-wide static host-I/O/provider/browser/native inventory. There is no legacy waiver: pre-spec, elaboration, discovery, council, planning, ordinary execution, Society, solution-space, parallel, evaluation, review, verification, self-ref, resume, teardown, Discord publication, browser/native, and external acquisition are typed authority-bound or typed unavailable/deferred. Re-run all Task 3 tests plus the Task 4 graph migration tests before commit; an enabled path that lacks authority prevents activation.

### Step 9: Verify and commit the atomic Task 3 + Task 4 wave

Run:

```powershell
python -m pytest tests/orchestration/test_solution_space.py tests/orchestration/test_solution_space_generational.py tests/orchestration/test_branch_runner.py tests/orchestration/test_winner_merge.py tests/orchestration/test_judge_panel.py tests/orchestration/test_society_batch.py tests/orchestration/test_society_coordinator.py tests/orchestration/test_society_worker.py tests/orchestration/test_society_off_invariance.py tests/orchestration/test_fork_seams.py tests/execution/test_worktree_batch.py tests/orchestration/test_execute_mixin_fork_wiring.py tests/orchestration/test_transactional_parallel.py tests/orchestration/test_selection_recovery.py tests/execution/test_launch_guard.py tests/execution/test_launch_guard_activation.py tests/execution/test_credential_broker.py tests/execution/test_provider_safe_boot.py tests/execution/test_runtime_resource_recovery.py tests/execution/test_galaxy_images.py tests/review/test_analysis_isolation.py tests/platform/test_health_collect.py tests/evolution/test_evolution_evolver.py -q
if ($LASTEXITCODE -ne 0) { throw 'Task 4 orchestration migration tests failed' }
python -m pytest tests/execution/test_attempt_journal.py tests/execution/test_executor.py tests/execution/test_executor_stream.py tests/execution/test_executor_env.py tests/execution/test_executor_session_lock.py tests/execution/test_execution_security.py tests/execution/test_execution_docker.py tests/execution/test_sandbox_broker.py tests/execution/test_credential_broker.py tests/execution/test_provider_safe_boot.py tests/execution/test_runtime_resource_recovery.py tests/execution/test_galaxy_images.py tests/execution/test_launch_guard.py tests/execution/test_runtime_projection.py tests/execution/test_verification_isolation.py tests/review/test_verification.py tests/review/test_analysis_isolation.py tests/platform/test_health_collect.py tests/evolution/test_evolution_evolver.py tests/orchestration/test_execute_mixin_env.py tests/execution/test_execute_mixin_teardown.py tests/orchestration/test_staged_finalization.py tests/control/test_attempt_state_transaction.py -q
if ($LASTEXITCODE -ne 0) { throw 'Task 3 regression suite failed after activation' }
python -m pytest tests/execution/test_execution_trust.py tests/control/test_execution_trust_authority.py tests/control/test_operator_launch.py tests/control/test_control_store.py tests/platform/test_main_cli.py -q
if ($LASTEXITCODE -ne 0) { throw 'Activation trust/control tests failed' }
python -m pytest tests/execution/test_attempt_crash_matrix.py -q
if ($LASTEXITCODE -ne 0) { throw 'Activation crash-matrix tests failed' }
python -m pytest tests/execution/test_authority_watchdog.py -q
if ($LASTEXITCODE -ne 0) { throw 'Activation watchdog tests failed' }
python -m pytest tests/execution/test_receipts.py tests/execution/test_promotion_authorization.py -q
if ($LASTEXITCODE -ne 0) { throw 'Activation receipt authorization tests failed' }
python tools/dev.py lint platform_core/orchestration/solution_space.py platform_core/orchestration/winner_merge.py platform_core/orchestration/society/worker.py
if ($LASTEXITCODE -ne 0) { throw 'Task 3 + Task 4 lint failed' }
$devToolRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) '9to5\galaxy-dev-tools'
$devPython = (python tools/bootstrap_galaxy_dev_tools.py --lock bootstrap/galaxy_launcher/dev_tools.lock.json --root $devToolRoot --offline --only-binary --require-hashes --print-python-only).Trim()
if ($LASTEXITCODE -ne 0 -or -not $devPython -or -not (Test-Path -LiteralPath $devPython -PathType Leaf)) { throw 'Pinned GALAXY development typechecker is unavailable' }
$mypyVersion = (& $devPython -m mypy --version).Trim()
if ($LASTEXITCODE -ne 0 -or $mypyVersion -notmatch '^mypy 2\.3\.0(?: |$)') { throw "Unexpected pinned mypy version: $mypyVersion" }
& $devPython tools/dev.py typecheck platform_core/orchestration/solution_space.py platform_core/orchestration/winner_merge.py platform_core/orchestration/society/worker.py
if ($LASTEXITCODE -ne 0) { throw 'Task 3 + Task 4 typecheck failed' }
$planPath = 'docs/superpowers/plans/2026-07-13-galaxy-r3-transactional-kernel.md'
function Get-GalaxyManifest { param([int[]]$Tasks, [string]$Kind)
  $taskArgs = @(); foreach ($task in $Tasks) { $taskArgs += @('--task', [string]$task) }
  $paths = @(python tools/galaxy_plan_manifest.py --plan $planPath @taskArgs --kind $Kind)
  if ($LASTEXITCODE -ne 0 -or -not $paths.Count -or @($paths | Where-Object { -not $_ }).Count) { throw "GALAXY manifest extraction failed for $Kind" }
  if (@($paths | Sort-Object -Unique).Count -ne $paths.Count) { throw "GALAXY manifest emitted duplicate $Kind paths" }
  return $paths
}
$manifestTests = @(Get-GalaxyManifest @(1,2,3,4) tests)
$manifestPython = @(Get-GalaxyManifest @(1,2,3,4) python)
$manifestProduction = @(Get-GalaxyManifest @(1,2,3,4) production-python)
function Invoke-GalaxyChunks { param([string[]]$Paths, [string]$Mode, [string]$Label)
  for ($offset = 0; $offset -lt $Paths.Count; $offset += 40) {
    $last = [Math]::Min($offset + 39, $Paths.Count - 1); $chunk = @($Paths[$offset..$last])
    switch ($Mode) { 'pytest' { python -m pytest @chunk -q } 'compile' { python -m compileall @chunk } 'lint' { python tools/dev.py lint @chunk } 'typecheck' { & $devPython tools/dev.py typecheck @chunk } default { throw "Unknown GALAXY check mode: $Mode" } }
    if ($LASTEXITCODE -ne 0) { throw "$Label failed for manifest chunk $offset..$last" }
  }
}
Invoke-GalaxyChunks $manifestTests pytest 'Task 1-4 complete manifest tests'
Invoke-GalaxyChunks $manifestPython compile 'Task 1-4 complete manifest compile'
Invoke-GalaxyChunks $manifestPython lint 'Task 1-4 complete manifest lint'
Invoke-GalaxyChunks $manifestProduction typecheck 'Task 1-4 complete manifest typecheck'
git diff --check
if ($LASTEXITCODE -ne 0) { throw 'Task 3 + Task 4 diff check failed' }
```

Commit:

```powershell
$cachedPaths = @(git diff --cached --name-only)
if ($LASTEXITCODE -ne 0 -or $cachedPaths.Count) { throw "Pre-existing staged paths; preserve them and stop: $($cachedPaths -join ', ')" }
$planPath = 'docs/superpowers/plans/2026-07-13-galaxy-r3-transactional-kernel.md'
$stageAllowlist = @(python tools/galaxy_plan_manifest.py --plan $planPath --task 3 --task 4 --kind all)
if ($LASTEXITCODE -ne 0 -or -not $stageAllowlist.Count) { throw 'Task 3 + Task 4 manifest extraction failed' }
$requiredChanges = @(python tools/galaxy_plan_manifest.py --plan $planPath --task 3 --task 4 --kind required-changes)
if ($LASTEXITCODE -ne 0 -or -not $requiredChanges.Count) { throw 'Task 3 + Task 4 required-change manifest extraction failed' }
$testPaths = @(python tools/galaxy_plan_manifest.py --plan $planPath --task 3 --task 4 --kind tests)
if ($LASTEXITCODE -ne 0 -or -not $testPaths.Count) { throw 'Task 3 + Task 4 test manifest extraction failed' }
$pinnedPowerShell = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
$singularityClient = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) '9to5\singularity\bin\singularity-admin-client.ps1'
if (-not (Test-Path -LiteralPath $pinnedPowerShell -PathType Leaf) -or -not (Test-Path -LiteralPath $singularityClient -PathType Leaf)) { throw 'Installed inactive Singularity service/client is unavailable' }
function Invoke-SingularityRecoveryAdmin { & $pinnedPowerShell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $singularityClient --request-only --require-server-validated-client-digest @args }
function Invoke-SingularityAdmin { Invoke-SingularityRecoveryAdmin @args }
Invoke-SingularityAdmin verify-self --require-fresh-service-host --require-os-pinned-digest --require-protected-acl --require-inactive-generation --require-closed-launch-record
if ($LASTEXITCODE -ne 0) { throw 'Installed inactive Singularity service failed self-verification' }
function Resolve-StrictLocalAbsolutePath { param([string]$RawPath)
  if ([string]::IsNullOrWhiteSpace($RawPath) -or $RawPath -notmatch '^[A-Za-z]:[\\/]' -or $RawPath.StartsWith('\\?\') -or $RawPath.StartsWith('\\.\') -or $RawPath.StartsWith('//?/') -or $RawPath.StartsWith('//./')) { throw "Not a strict local drive-absolute path: $RawPath" }
  $full = [System.IO.Path]::GetFullPath($RawPath); if ($full -notmatch '^[A-Za-z]:\\') { throw "Path normalization lost drive-absolute form: $RawPath" }; return $full
}
$repoRoot = Resolve-StrictLocalAbsolutePath (Get-Location).Path
function Complete-SingularityTopLevelSlot { param([string]$Repository)
  function Invoke-SingularityAdmin { Invoke-SingularityRecoveryAdmin @args }
  $currentPurpose=(Invoke-SingularityAdmin resolve-current-top-level-transition --repo $Repository --repository-global-all-generations --read-only --require-unique-live-slot --print-none-or-bound-purpose-receipt).Trim();if($LASTEXITCODE-ne 0-or-not$currentPurpose){throw 'Pure slot lookup failed; settlement is forbidden'};if($currentPurpose-eq'none'){return 'none'};if($currentPurpose-notmatch'^purpose_[0-9a-f]{64}$'){throw 'Invalid occupied purpose receipt'}
  $slotResult=(Invoke-SingularityAdmin observe-top-level-transition --repo $Repository --repository-global-all-generations --bound-purpose-receipt $currentPurpose --read-only --include-owner-lease-and-fencing-generation --require-latest-journal-live-state-and-ingress --closed-terminal-map singularity-top-level-terminal-v1 --print-owner-state-recovery-pending-or-terminal-observation).Trim();if($LASTEXITCODE-ne 0-or-not$slotResult){throw 'Occupied slot state is unknown'};if($slotResult-in@('active_owned_elsewhere','owner_liveness_unknown')){throw "Live or unproven slot owner blocks takeover: $currentPurpose"};if($slotResult-eq'recovery_pending'){throw "Slot recovery remains pending: $currentPurpose"}
  if($slotResult-match'^recoverable_dead_owner_([0-9a-f]{64})$'){$eligibilityReceipt=$Matches[1];$recoveryOwnerFence=(Invoke-SingularityAdmin settle-top-level-transition --repo $Repository --repository-global-all-generations --bound-purpose-receipt $currentPurpose --dead-owner-eligibility-receipt $eligibilityReceipt --revalidate-owner-dead-expired-and-quiesced-under-slot-lock --advance-owner-fencing-generation-before-mutation --existing-slot-only --journal-bound-settlement --allow-cancel-only-with-no-begin-proof --no-new-candidate --no-new-selection --no-unbound-state-adoption --persist-before-response --print-recovery-owner-fence-receipt).Trim();if($LASTEXITCODE-ne 0-or$recoveryOwnerFence-notmatch'^ownerfence_[0-9a-f]{64}$'){throw 'Dead-owner settlement failed safely'};$slotResult=(Invoke-SingularityAdmin observe-top-level-transition --repo $Repository --repository-global-all-generations --bound-purpose-receipt $currentPurpose --transition-owner-fence-receipt $recoveryOwnerFence --require-current-owner-fencing-generation --read-only --require-latest-journal-live-state-and-ingress --closed-terminal-map singularity-top-level-terminal-v1 --print-terminal-observation-or-recovery-pending).Trim()}
  if($slotResult-notmatch'^terminal_(cutover|source|controller)_(achieved|retryable_old|verified_rollback|safe_failed)_([0-9a-f]{64})$'){throw 'Occupied slot is not in an acknowledgeable closed terminal state'};$terminalKind=$Matches[2];Invoke-SingularityAdmin acknowledge-terminal-disposition --repo $Repository --repository-global-all-generations --bound-purpose-receipt $currentPurpose --terminal-observation-token $slotResult --closed-terminal-map singularity-top-level-terminal-v1 --revalidate-observation-still-current-before-ack --require-current-owner-fencing-generation-bound-to-observation --atomic-under-slot-lock --reject-cross-operation-purpose-epoch-or-owner-token-replay --idempotent --persist-before-response|Out-Null;$ackExit=$LASTEXITCODE
  $afterAck=(Invoke-SingularityAdmin resolve-transition-purpose-outcome --repo $Repository --purpose-receipt $currentPurpose --read-only --require-unique-exact-archive --require-observation-acknowledgement-chain --print-archived-outcome).Trim();$expected=@{achieved='archived_achieved';retryable_old='archived_retryable';verified_rollback='archived_rollback';safe_failed='archived_failed'};if($LASTEXITCODE-ne 0-or$afterAck-ne$expected[$terminalKind]){throw "Terminal archive disagreement after ack_exit=$ackExit"};$released=(Invoke-SingularityAdmin resolve-current-top-level-transition --repo $Repository --repository-global-all-generations --read-only --require-unique-live-slot --print-none-or-bound-purpose-receipt).Trim();if($LASTEXITCODE-ne 0-or$released-ne'none'){throw 'Acknowledged slot did not release'};return "$afterAck|$currentPurpose"
}
function Resolve-SingularityPurposeStartDisposition{param([string]$Repository,[string]$DesiredPurpose,[string]$PriorTerminal);if($DesiredPurpose-notmatch'^purpose_[0-9a-f]{64}$'){throw 'Invalid desired-purpose receipt'};if($PriorTerminal-ne'none'){$parts=@($PriorTerminal-split'\|',2);if($parts.Count-ne 2){throw 'Malformed prior terminal result'};$relationship=(Invoke-SingularityAdmin classify-purpose-successor --repo $Repository --completed-purpose-receipt $parts[1] --desired-purpose-receipt $DesiredPurpose --read-only --require-closed-reviewed-purpose-dag --require-explicit-wave-restart-edge --reject-multiple-matching-archives --print-same-allowed-predecessor-or-unrelated).Trim();if($LASTEXITCODE-ne 0-or$relationship-eq'unrelated_or_new_epoch'){throw 'Prior and desired purposes lack an allowed relationship'};if($relationship-eq'allowed_predecessor'-and$parts[0]-ne'archived_achieved'){throw 'Only an achieved predecessor may advance'}};$outcome=(Invoke-SingularityAdmin resolve-transition-purpose-outcome --repo $Repository --purpose-receipt $DesiredPurpose --read-only --require-unique-exact-archive --print-clear-never-started-or-archived-outcome).Trim();if($outcome-eq'archived_achieved'){return 'already_achieved'};if($outcome-in@('clear_never_started','archived_retryable')){return 'proceed'};throw "Desired purpose is not runnable: $outcome"}
$priorTerminal=Complete-SingularityTopLevelSlot $repoRoot
$purposeIssueReply=(Invoke-SingularityAdmin acquire-transition-purpose --repo $repoRoot --reviewed-plan-node task34-source-v1 --operation source-update --contract source-update-maintenance-v1 --requested-fences cli-run-closed+discord-disabled+maintenance-index-ref --bind-active-reviewed-wave-epoch --require-wave-epoch-bound-to-current-tofu-receipt --require-satisfied-reviewed-predecessor-ledger --reject-unrelated-or-multiple-predecessor-archives --bind-exact-old-state --capture-native-no-follow-pre-normalization-batch --bind-canonicalization-policy strict-utf8-parent-bom-preserving-crlf-to-lf-or-exact --create-or-return-exact --persist-before-response --print-purpose-receipt).Trim();$purposeIssueExit=$LASTEXITCODE
$transitionPurpose=(Invoke-SingularityAdmin resolve-transition-purpose --repo $repoRoot --reviewed-plan-node task34-source-v1 --operation source-update --contract source-update-maintenance-v1 --requested-fences cli-run-closed+discord-disabled+maintenance-index-ref --bind-active-reviewed-wave-epoch --require-wave-epoch-bound-to-current-tofu-receipt --require-satisfied-reviewed-predecessor-ledger --reject-unrelated-or-multiple-predecessor-archives --bind-exact-old-state --capture-native-no-follow-pre-normalization-batch --bind-canonicalization-policy strict-utf8-parent-bom-preserving-crlf-to-lf-or-exact --read-only --require-unique-exact --print-purpose-receipt-or-none).Trim();if($LASTEXITCODE-ne 0-or$transitionPurpose-notmatch'^purpose_[0-9a-f]{64}$'){throw "Task 3 + Task 4 purpose is not recoverable after issue_exit=$purposeIssueExit"};if($purposeIssueExit-eq 0-and$purposeIssueReply-and$purposeIssueReply-ne$transitionPurpose){throw 'Task 3 + Task 4 purpose issue reply disagrees with resolution'}
$slotOutcome = Resolve-SingularityPurposeStartDisposition $repoRoot $transitionPurpose $priorTerminal
if ($slotOutcome -eq 'already_achieved') { Write-Output 'Task 3 + Task 4 source update was already authoritatively completed and acknowledged'; return }
$sourceIntentReply = (Invoke-SingularityAdmin acquire-begin-intent --repo $repoRoot --operation source-update --contract source-update-maintenance-v1 --transition-purpose-receipt $transitionPurpose --require-exact-purpose-binding --require-reviewed-purpose-dag --requested-fences cli-run-closed+discord-disabled+maintenance-index-ref --bind-exact-old-state --exclusive-top-level-mutation-per-registered-repo-all-generations --create-or-return-unique-slot --persist-before-response --print-request-id).Trim()
$sourceIntentExit = $LASTEXITCODE
$sourceUpdateRequestId = (Invoke-SingularityAdmin resolve-begin-intent --repo $repoRoot --operation source-update --contract source-update-maintenance-v1 --transition-purpose-receipt $transitionPurpose --require-exact-purpose-binding --requested-fences cli-run-closed+discord-disabled+maintenance-index-ref --bind-exact-old-state --exclusive-top-level-mutation-per-registered-repo-all-generations --read-only --require-unique-slot --require-persisted-intent --print-request-id-or-none).Trim()
if ($LASTEXITCODE -ne 0 -or -not $sourceUpdateRequestId -or $sourceUpdateRequestId -eq 'none') { throw "Task 3 + Task 4 source-update intent is not authoritatively discoverable after intent_exit=$sourceIntentExit; recover by repository and operation contract without starting another transition" }
if ($sourceIntentExit -eq 0 -and $sourceIntentReply -and $sourceIntentReply -ne $sourceUpdateRequestId) { throw 'Task 3 + Task 4 intent reply disagrees with authoritative intent discovery; do not start another transition' }
$ownerFenceReceipt = (Invoke-SingularityAdmin resolve-begin-intent-owner-fence --repo $repoRoot --request-id $sourceUpdateRequestId --transition-purpose-receipt $transitionPurpose --read-only --require-current-owner-lease-and-fencing-generation --print-owner-fence-receipt).Trim()
if ($LASTEXITCODE -ne 0 -or $ownerFenceReceipt -notmatch '^ownerfence_[0-9a-f]{64}$') { throw 'Task 3 + Task 4 owner-fence receipt is unavailable; do not begin' }
function Invoke-SingularityAdmin { $recoveryCommands=@('resolve-current-top-level-transition','observe-top-level-transition','settle-top-level-transition','acknowledge-terminal-disposition','resolve-transition-purpose-outcome');if($args.Count-and$args[0]-in$recoveryCommands){& $pinnedPowerShell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $singularityClient --request-only --require-server-validated-client-digest @args}else{& $pinnedPowerShell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $singularityClient --request-only --require-server-validated-client-digest --transition-purpose-receipt $transitionPurpose --transition-owner-fence-receipt $ownerFenceReceipt --require-current-owner-fencing-generation @args} }
$sourceReplyTx = (Invoke-SingularityAdmin begin-source-update --request-id $sourceUpdateRequestId --idempotent-create --repo $repoRoot --require-exact-purpose-binding --close-cli-run-ingress --keep-discord-listener-disabled --hold-maintenance-index-and-ref-fences --persist-begin-receipt-before-response).Trim()
$sourceReplyExit = $LASTEXITCODE
$sourceTx = (Invoke-SingularityAdmin resolve-source-update-begin --request-id $sourceUpdateRequestId --repo $repoRoot --read-only --require-exact-request-binding --require-exact-purpose-binding --require-persisted-begin-receipt-if-started --require-latest-monotone-journal-if-started --require-exact-old-state-if-started --require-live-requested-fences-held-if-started --classify-started-exact-requested-fences-held-or-not-started --print-transaction-or-not-started).Trim()
if ($LASTEXITCODE -ne 0 -or -not $sourceTx) { throw "Task 3 + Task 4 source-update begin state is uncertain after begin_exit=$sourceReplyExit; do not use or infer ingress state; recover by request ID $sourceUpdateRequestId" }
if ($sourceTx -eq 'not_started') { throw "Task 3 + Task 4 source update did not start; request ID $sourceUpdateRequestId" }
if ($sourceReplyExit -eq 0 -and $sourceReplyTx -and $sourceReplyTx -ne $sourceTx) { throw "Task 3 + Task 4 begin reply disagrees with authoritative resolution; do not infer ingress state; recover by request ID $sourceUpdateRequestId" }
function Stop-SingularitySourceUpdateBeforeCas { param([string]$Reason, [string]$Proposal)
  $abortArgs = @('abort-source-update', '--transaction', $sourceTx, '--before-cas-only', '--abort-all-child-resources', '--reconcile-journaled-normalization', '--restore-developer-ingress-only-if-old-ref-index-tree-exact', '--keep-production-run-inactive', '--keep-discord-listener-disabled', '--persist-and-reread-recovery-receipt', '--print-disposition'); if ($Proposal) { $abortArgs += @('--proposal', $Proposal) }
  Invoke-SingularityAdmin @abortArgs | Out-Null; $abortExit = $LASTEXITCODE
  $disposition = (Invoke-SingularityAdmin resolve-source-update-disposition --transaction $sourceTx --read-only --require-persisted-receipt --require-production-run-inactive --require-discord-listener-disabled --classify-safe-old-developer-ingress-open-or-held-closed-or-recovery-pending --print-disposition).Trim()
  if ($LASTEXITCODE -ne 0 -or $disposition -notin @('safe_old_developer_ingress_open', 'safe_old_developer_ingress_held_closed', 'fenced_recovery_pending')) { throw "$Reason; authoritative source-update disposition is unavailable after abort_exit=$abortExit; do not infer ingress state; recover transaction $sourceTx" }
  if ($disposition -eq 'safe_old_developer_ingress_open') { throw "$Reason; exact old state is restored and developer ingress is authoritatively open" }
  if ($disposition -eq 'safe_old_developer_ingress_held_closed') { throw "$Reason; exact old state is restored but developer ingress is authoritatively held closed" }
  throw "$Reason; a durable recovery receipt proves developer ingress held closed pending recovery"
}
function Stop-SingularitySourceUpdateAfterCas { param([string]$Reason, [string]$Proposal)
  Invoke-SingularityAdmin reconcile-source-update --transaction $sourceTx --proposal $Proposal --classify-old-or-exact-new-ref-index-tree --finish-only-journal-bound-materialization-attestation-and-ingress --keep-production-run-inactive --keep-discord-listener-disabled --persist-and-reread-recovery-receipt --print-disposition | Out-Null
  $reconcileExit = $LASTEXITCODE
  $disposition = (Invoke-SingularityAdmin resolve-source-update-disposition --transaction $sourceTx --read-only --require-persisted-receipt --require-production-run-inactive --require-discord-listener-disabled --classify-safe-old-or-committed-exact-new-with-ingress-or-recovery-pending --print-disposition).Trim()
  if ($LASTEXITCODE -ne 0 -or $disposition -notin @('safe_old_developer_ingress_open', 'safe_old_developer_ingress_held_closed', 'committed_exact_new_developer_ingress_open', 'committed_exact_new_developer_ingress_held_closed', 'fenced_recovery_pending')) { throw "$Reason; authoritative source-update disposition is unavailable after reconcile_exit=$reconcileExit; do not infer ingress state; recover transaction $sourceTx" }
  throw "$Reason; authoritative disposition=$disposition; re-enter through verified recovery before continuing"
}
function Register-SingularityPathManifest { param([string]$Scope, [string[]]$Allowed, [string[]]$Required, [string[]]$Tests)
  function ConvertTo-SingularityManifestBase64Url { param([string]$CanonicalJson) $bytes = ([System.Text.UTF8Encoding]::new($false, $true)).GetBytes($CanonicalJson); if ($bytes.Length -gt 4096) { throw 'Path-manifest decoded JSON exceeds 4096 bytes' }; return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_') }
  $allowedSet = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal); $requiredSet = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal); $testSet = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
  foreach ($entry in $Allowed) { if (-not $entry -or $entry.Length -gt 240 -or -not $allowedSet.Add($entry)) { throw "Invalid or duplicate allowed path: $entry" } }; foreach ($entry in $Required) { if (-not $requiredSet.Add($entry) -or -not $allowedSet.Contains($entry)) { throw "Invalid required-change subset: $entry" } }; foreach ($entry in $Tests) { if (-not $testSet.Add($entry) -or -not $allowedSet.Contains($entry)) { throw "Invalid test subset: $entry" } }
  $records = @($Allowed | ForEach-Object { $isRequired = $requiredSet.Contains($_); $isTest = $testSet.Contains($_); $role = if ($isRequired -and $isTest) { 'required-test' } elseif ($isRequired) { 'required-change' } elseif ($isTest) { 'test-only' } else { 'allowed-only' }; [ordered]@{ role = $role; path = $_ } })
  $manifestId = (Invoke-SingularityAdmin begin-path-manifest --scope $Scope --expected-total-count $Allowed.Count --expected-required-count $Required.Count --expected-test-count $Tests.Count).Trim(); if ($LASTEXITCODE -ne 0 -or -not $manifestId) { throw 'Unable to begin external path manifest' }
  $sequence = 0; $chunk = @(); foreach ($record in $records) { $trial = @($chunk + $record); $trialJson = ([ordered]@{ sequence = $sequence; records = $trial } | ConvertTo-Json -Compress -Depth 4); if (($trial.Count -gt 24 -or [Text.Encoding]::UTF8.GetByteCount($trialJson) -gt 4096) -and $chunk.Count) { $chunkJson = ([ordered]@{ sequence = $sequence; records = $chunk } | ConvertTo-Json -Compress -Depth 4); $chunkPayload = ConvertTo-SingularityManifestBase64Url $chunkJson; Invoke-SingularityAdmin append-path-manifest --scope $Scope --manifest $manifestId --sequence $sequence --canonical-records-json-base64url $chunkPayload --require-strict-unpadded-base64url --require-decoded-canonical-json-max-bytes 4096 --require-decode-recanonicalize-byte-equality --require-exact-envelope-max-bytes 8192; if ($LASTEXITCODE -ne 0) { throw "External path-manifest upload failed at sequence $sequence" }; $sequence += 1; $chunk = @($record) } else { $chunk = $trial } }
  if ($chunk.Count) { $chunkJson = ([ordered]@{ sequence = $sequence; records = $chunk } | ConvertTo-Json -Compress -Depth 4); $chunkPayload = ConvertTo-SingularityManifestBase64Url $chunkJson; Invoke-SingularityAdmin append-path-manifest --scope $Scope --manifest $manifestId --sequence $sequence --canonical-records-json-base64url $chunkPayload --require-strict-unpadded-base64url --require-decoded-canonical-json-max-bytes 4096 --require-decode-recanonicalize-byte-equality --require-exact-envelope-max-bytes 8192; if ($LASTEXITCODE -ne 0) { throw "External path-manifest upload failed at sequence $sequence" } }
  $receipt = (Invoke-SingularityAdmin seal-path-manifest --scope $Scope --manifest $manifestId --canonical-order --sha256 --require-total-count $Allowed.Count --require-required-count $Required.Count --require-test-count $Tests.Count --persist-and-reread).Trim(); if ($LASTEXITCODE -ne 0 -or -not $receipt) { throw 'External path-manifest seal failed' }; return $receipt
}
try { $pathManifestReceipt = Register-SingularityPathManifest $sourceTx $stageAllowlist $requiredChanges $testPaths }
catch { Stop-SingularitySourceUpdateBeforeCas "Task 3 + Task 4 path-manifest failure: $($_.Exception.Message)" '' }
$normalizationReceipt = (Invoke-SingularityAdmin normalize-developer-source --transaction $sourceTx --repo $repoRoot --path-manifest-receipt $pathManifestReceipt --chain-purpose-pre-normalization-batch-and-policy --require-exact-purpose-batch-membership --strict-utf8-parent-bom-preserving-crlf-to-lf-only --binary-exact --ensure-symbolic-loose-head-same-oid --create-if-absent-or-verify-existing-loose-head --disable-auto-ref-packing --native-full-tree-exact-index-bytes --no-ambient-git-config --no-hooks --no-filters --require-no-unexpected-change --persist-before-response --print-normalization-receipt).Trim()
if ($LASTEXITCODE -ne 0 -or $normalizationReceipt -notmatch '^normalization_[0-9a-f]{64}$') { Stop-SingularitySourceUpdateBeforeCas 'Task 3 + Task 4 exact-change normalization did not chain the immutable purpose batch' '' }
$proposalTx = (Invoke-SingularityAdmin prepare-source-commit --transaction $sourceTx --repo $repoRoot --path-manifest-receipt $pathManifestReceipt --normalization-receipt $normalizationReceipt --require-pre-normalization-purpose-chain --native-no-follow-snapshot --parent-plus-allowlist-complete-tree --fixed-commit-metadata --message 'feat: enforce transactional model execution').Trim()
if ($LASTEXITCODE -ne 0 -or -not $proposalTx) { Stop-SingularitySourceUpdateBeforeCas 'Task 3 + Task 4 source proposal failed' '' }
Invoke-SingularityAdmin review-source-proposal --transaction $proposalTx --sealed-independent-reviewer --persist-and-reread-review-receipt --no-canonical-write
if ($LASTEXITCODE -ne 0) { Stop-SingularitySourceUpdateBeforeCas 'Task 3 + Task 4 independent proposal review failed' $proposalTx }
Invoke-SingularityAdmin verify-source-proposal --transaction $proposalTx --normalization-receipt $normalizationReceipt --require-pre-normalization-purpose-chain --require-exact-manifest --require-every-required-path-changed --require-no-unexpected-change --require-review-receipt --require-no-canonical-ref-write
if ($LASTEXITCODE -ne 0) { Stop-SingularitySourceUpdateBeforeCas 'Task 3 + Task 4 exact proposal verification failed' $proposalTx }
Invoke-SingularityAdmin commit-source-proposal --transaction $proposalTx --source-update $sourceTx --normalization-receipt $normalizationReceipt --require-pre-normalization-purpose-chain --require-fresh-exact-digest-approval --cas-loose-ref --native-full-tree-materialize --install-verified-index --require-final-byte-clean --durable --keep-production-run-inactive
if ($LASTEXITCODE -ne 0) { Stop-SingularitySourceUpdateAfterCas 'Task 3 + Task 4 external source commit reported failure' $proposalTx }
Invoke-SingularityAdmin attest-committed-source --transaction $sourceTx --proposal $proposalTx --require-loose-head --require-exact-index-worktree-bytes --require-source-receipt --keep-production-run-inactive
if ($LASTEXITCODE -ne 0) { Stop-SingularitySourceUpdateAfterCas 'Task 3 + Task 4 committed source attestation failed' $proposalTx }
Invoke-SingularityAdmin finish-source-update --transaction $sourceTx --release-developer-only-ingress --keep-production-run-inactive --keep-discord-listener-disabled --persist-and-reread-finish-receipt --print-disposition | Out-Null
$finishExit = $LASTEXITCODE
$finishDisposition = (Invoke-SingularityAdmin resolve-source-update-disposition --transaction $sourceTx --read-only --require-persisted-receipt --require-production-run-inactive --require-discord-listener-disabled --classify-safe-old-or-committed-exact-new-with-ingress-or-recovery-pending --print-disposition).Trim()
if ($LASTEXITCODE -ne 0 -or -not $finishDisposition) { throw "Task 3 + Task 4 finish disposition unavailable after finish_exit=$finishExit; do not infer ingress state; recover transaction $sourceTx" }
if ($finishDisposition -ne 'committed_exact_new_developer_ingress_open') { Stop-SingularitySourceUpdateAfterCas "Task 3 + Task 4 finish resolved as $finishDisposition" $proposalTx }
$terminalOutcome = Complete-SingularityTopLevelSlot $repoRoot
if ($terminalOutcome -ne "archived_achieved|$transitionPurpose") { throw 'Task 3 + Task 4 terminal transition was not observed, acknowledged, archived, and released as achieved' }
$committedKernelSha = (git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Unable to resolve committed kernel SHA' }
$committedKernelSha
# Do not activate here. Task 5 independent review may require implementation corrections, and
# map/evidence commits must reach a clean final SHA first. The inactive external anchor remains
# authoritative until Task 5's installed-LKG-updater transaction succeeds.
```

The path list is an allowlist, not a convenience glob. Before `git add`, compare `git diff --name-only` and untracked implementation files to this reviewed manifest; stop on any unexpected path, and add a newly required path to the plan explicitly before staging. Never stage an entire directory in this working tree.

---

## 7. Task 5 - Close the truth surface, maps, and evidence

**Files**

- Modify: `docs/superpowers/specs/2026-07-13-galaxy-singularity-revision-3-design.md` only if implementation truth requires a correction
- Modify: `docs/superpowers/plans/2026-07-13-galaxy-r3-transactional-kernel.md` only for reviewed implementation-time manifest/truth corrections
- Add: `docs/superpowers/reports/2026-07-13-galaxy-r3-kernel-evidence.md`
- Regenerate: `.repo-map.json`
- Regenerate: `.llm-map.json`
- Regenerate applicable ignored `AGENTS.md` indexes locally through `python tools/repo_map.py` (do not stage ignored derived files)
- Inspect and stage each exact tracked source path whose adopted `@AI-MAP` header is changed by regeneration
- Modify tests only for genuine compatibility corrections, never to weaken assertions

### Step 1: Define the evidence schema; materialize it only at the review fixed point

Define the report fields now, but do **not** create the report file yet. Materialize it only after all source/test corrections and the post-map gate have reached a fixed point, so an untracked out-of-scope report can neither block nor be swept into a correction transaction. The final report records:

- before/after lifecycle;
- exact promoted invariants;
- all focused commands and results;
- real-Git concurrency/CAS evidence;
- known limitations;
- deferred GALAXY R3 waves;
- external operating-cost delta (`$0` expected);
- links to the architecture design and this plan.

Do not claim world-class superiority from architecture alone. Claim only the capabilities directly proven by tests and receipts.

### Step 2: Establish a clean implementation baseline

Do not regenerate maps or create the evidence report yet: independent review may still change code. Require every implementation commit to be complete and the tracked implementation tree clean; only separately reviewed/committed specification or plan truth corrections may have occurred:

```powershell
git status --short --branch
if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect pre-review status' }
git diff --check
if ($LASTEXITCODE -ne 0) { throw 'Pre-review diff check failed' }
$cachedPaths = @(git diff --cached --name-only)
if ($LASTEXITCODE -ne 0) { throw 'Unable to enumerate pre-review staged paths' }
if ($cachedPaths.Count) { throw "Pre-staged paths before final review: $($cachedPaths -join ', ')" }
$unexpectedTracked = @(git diff --name-only)
if ($LASTEXITCODE -ne 0) { throw 'Unable to enumerate pre-review tracked paths' }
if ($unexpectedTracked.Count) { throw "Uncommitted implementation paths: $($unexpectedTracked -join ', ')" }
$unexpectedUntracked = @(git ls-files --others --exclude-standard)
if ($LASTEXITCODE -ne 0) { throw 'Unable to enumerate pre-review untracked paths' }
if ($unexpectedUntracked.Count) { throw "Unexpected untracked paths: $($unexpectedUntracked -join ', ')" }
```

Expected: no uncommitted implementation path can be swept into a later documentation/map commit.

### Step 3: Run the transactional-kernel suite

Run:

```powershell
python -m pytest tests/execution/test_execution_environment.py tests/execution/test_execution_local.py tests/execution/test_execution_router.py tests/execution/test_execution_remote.py tests/execution/test_execution_worktree.py tests/execution/test_execution_security.py tests/execution/test_execution_docker.py tests/execution/test_worktree.py tests/execution/test_fsio.py tests/execution/test_candidate.py tests/execution/test_execution_clone.py tests/execution/test_sterile_git.py tests/execution/test_canonical_repo.py tests/execution/test_loose_refs.py tests/execution/test_staged_revision.py tests/execution/test_attempt_journal.py tests/execution/test_executor.py tests/execution/test_executor_env.py tests/execution/test_executor_session_lock.py tests/execution/test_sandbox_broker.py tests/execution/test_credential_broker.py tests/execution/test_provider_safe_boot.py tests/execution/test_runtime_resource_recovery.py tests/execution/test_galaxy_images.py tests/execution/test_launch_guard.py tests/execution/test_launch_guard_activation.py tests/execution/test_runtime_projection.py tests/execution/test_verification_isolation.py tests/review/test_verification.py tests/review/test_analysis_isolation.py tests/platform/test_health_collect.py tests/evolution/test_evolution_evolver.py tests/execution/test_worktree_batch.py tests/execution/test_execute_mixin_teardown.py tests/control/test_attempt_state_transaction.py tests/orchestration/test_execute_mixin_env.py tests/orchestration/test_staged_finalization.py tests/orchestration/test_execute_mixin_fork_wiring.py tests/orchestration/test_branch_runner.py tests/orchestration/test_fork_seams.py tests/orchestration/test_solution_space.py tests/orchestration/test_solution_space_generational.py tests/orchestration/test_judge_panel.py tests/orchestration/test_winner_merge.py tests/orchestration/test_society_batch.py tests/orchestration/test_society_coordinator.py tests/orchestration/test_society_worker.py tests/orchestration/test_society_off_invariance.py tests/orchestration/test_transactional_parallel.py tests/orchestration/test_selection_recovery.py -q
if ($LASTEXITCODE -ne 0) { throw 'Complete focused kernel suite failed' }
python -m pytest tests/execution/test_executor_stream.py tests/execution/test_claude_sdk_bridge.py tests/execution/test_provider_probe.py tests/execution/test_verifier.py -q
if ($LASTEXITCODE -ne 0) { throw 'Complete direct-launch and verifier-sanitization suite failed' }
python -m pytest tests/execution/test_execution_trust.py tests/control/test_execution_trust_authority.py tests/control/test_operator_launch.py tests/control/test_control_store.py tests/platform/test_main_cli.py -q
if ($LASTEXITCODE -ne 0) { throw 'Complete trust/control suite failed' }
python -m pytest tests/execution/test_attempt_crash_matrix.py -q
if ($LASTEXITCODE -ne 0) { throw 'Complete crash-matrix suite failed' }
python -m pytest tests/execution/test_authority_watchdog.py -q
if ($LASTEXITCODE -ne 0) { throw 'Complete watchdog suite failed' }
python -m pytest tests/execution/test_receipts.py tests/execution/test_promotion_authorization.py -q
if ($LASTEXITCODE -ne 0) { throw 'Complete receipt authorization suite failed' }
$planPath = 'docs/superpowers/plans/2026-07-13-galaxy-r3-transactional-kernel.md'
$devToolRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) '9to5\galaxy-dev-tools'
$devPython = (python tools/bootstrap_galaxy_dev_tools.py --lock bootstrap/galaxy_launcher/dev_tools.lock.json --root $devToolRoot --offline --only-binary --require-hashes --print-python-only).Trim()
if ($LASTEXITCODE -ne 0 -or -not $devPython -or -not (Test-Path -LiteralPath $devPython -PathType Leaf)) { throw 'Pinned GALAXY development typechecker is unavailable' }
$mypyVersion = (& $devPython -m mypy --version).Trim()
if ($LASTEXITCODE -ne 0 -or $mypyVersion -notmatch '^mypy 2\.3\.0(?: |$)') { throw "Unexpected pinned mypy version: $mypyVersion" }
function Get-GalaxyManifest { param([int[]]$Tasks, [string]$Kind)
  $taskArgs = @(); foreach ($task in $Tasks) { $taskArgs += @('--task', [string]$task) }
  $paths = @(python tools/galaxy_plan_manifest.py --plan $planPath @taskArgs --kind $Kind)
  if ($LASTEXITCODE -ne 0 -or -not $paths.Count -or @($paths | Where-Object { -not $_ }).Count) { throw "GALAXY manifest extraction failed for $Kind" }
  if (@($paths | Sort-Object -Unique).Count -ne $paths.Count) { throw "GALAXY manifest emitted duplicate $Kind paths" }
  return $paths
}
function Invoke-GalaxyChunks { param([string[]]$Paths, [string]$Mode, [string]$Label)
  for ($offset = 0; $offset -lt $Paths.Count; $offset += 40) {
    $last = [Math]::Min($offset + 39, $Paths.Count - 1); $chunk = @($Paths[$offset..$last])
    switch ($Mode) { 'pytest' { python -m pytest @chunk -q } 'compile' { python -m compileall @chunk } 'lint' { python tools/dev.py lint @chunk } 'typecheck' { & $devPython tools/dev.py typecheck @chunk } default { throw "Unknown GALAXY check mode: $Mode" } }
    if ($LASTEXITCODE -ne 0) { throw "$Label failed for manifest chunk $offset..$last" }
  }
}
$manifestTests = @(Get-GalaxyManifest @(1,2,3,4) tests)
$manifestPython = @(Get-GalaxyManifest @(1,2,3,4) python)
$manifestProduction = @(Get-GalaxyManifest @(1,2,3,4) production-python)
Invoke-GalaxyChunks $manifestTests pytest 'Task 5 complete Tasks 1-4 manifest tests'
Invoke-GalaxyChunks $manifestPython compile 'Task 5 complete Tasks 1-4 manifest compile'
Invoke-GalaxyChunks $manifestPython lint 'Task 5 complete Tasks 1-4 manifest lint'
Invoke-GalaxyChunks $manifestProduction typecheck 'Task 5 complete Tasks 1-4 manifest typecheck'
```

### Step 4: Run affected tests and static validation

Run:

```powershell
$galaxyBaseline = (git rev-parse refs/9to5/baselines/galaxy-r3-qualified).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Unable to resolve GALAXY baseline ref' }
$galaxyChanged = @(git diff --name-only $galaxyBaseline)
if ($LASTEXITCODE -ne 0) { throw 'Unable to enumerate GALAXY baseline diff' }
$galaxyTestsRaw = ((python tools/affected_tests.py @galaxyChanged) -join ' ').Trim()
if ($LASTEXITCODE -ne 0) { throw 'Affected-test selection failed' }
$galaxyTests = @($galaxyTestsRaw -split '\s+' | Where-Object { $_ })
if (-not $galaxyTests.Count) { throw 'Affected-test selection returned no targets for the GALAXY implementation diff' }
$galaxyTests
python -m pytest @galaxyTests -q
if ($LASTEXITCODE -ne 0) { throw 'Affected-test execution failed' }
$galaxyPython = @($galaxyChanged | Where-Object { $_.EndsWith('.py', [System.StringComparison]::OrdinalIgnoreCase) })
if (-not $galaxyPython.Count) { throw 'GALAXY baseline diff unexpectedly contains no Python paths' }
$galaxyProductionPython = @($galaxyPython | Where-Object { -not $_.StartsWith('tests/', [System.StringComparison]::OrdinalIgnoreCase) })
if (-not $galaxyProductionPython.Count) { throw 'GALAXY baseline diff unexpectedly contains no production Python paths' }
$devToolRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) '9to5\galaxy-dev-tools'
$devPython = (python tools/bootstrap_galaxy_dev_tools.py --lock bootstrap/galaxy_launcher/dev_tools.lock.json --root $devToolRoot --offline --only-binary --require-hashes --print-python-only).Trim()
if ($LASTEXITCODE -ne 0 -or -not $devPython -or -not (Test-Path -LiteralPath $devPython -PathType Leaf)) { throw 'Pinned GALAXY development typechecker is unavailable' }
$mypyVersion = (& $devPython -m mypy --version).Trim()
if ($LASTEXITCODE -ne 0 -or $mypyVersion -notmatch '^mypy 2\.3\.0(?: |$)') { throw "Unexpected pinned mypy version: $mypyVersion" }
for ($offset = 0; $offset -lt $galaxyPython.Count; $offset += 40) {
  $last = [Math]::Min($offset + 39, $galaxyPython.Count - 1); $chunk = @($galaxyPython[$offset..$last])
  python -m compileall @chunk
  if ($LASTEXITCODE -ne 0) { throw "GALAXY compile validation failed for changed-source chunk $offset..$last" }
  python tools/dev.py lint @chunk
  if ($LASTEXITCODE -ne 0) { throw "GALAXY lint validation failed for changed-source chunk $offset..$last" }
}
for ($offset = 0; $offset -lt $galaxyProductionPython.Count; $offset += 40) {
  $last = [Math]::Min($offset + 39, $galaxyProductionPython.Count - 1); $chunk = @($galaxyProductionPython[$offset..$last])
  & $devPython tools/dev.py typecheck @chunk
  if ($LASTEXITCODE -ne 0) { throw "GALAXY typecheck failed for changed production-source chunk $offset..$last" }
}
python tools/dev.py fast --ignore=tests/platform/test_repo_map.py
if ($LASTEXITCODE -ne 0) { throw 'Pre-map fast lane failed outside the intentionally deferred repo-map module' }
git diff --check
if ($LASTEXITCODE -ne 0) { throw 'Post-verification diff check failed' }
git status --short --branch
if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect post-verification status' }
```

`affected_tests.py` is a selector, not a runner. The gate above captures its space-joined output, normalizes it to a PowerShell argument array, refuses the unexpectedly empty mapping, and executes the resulting targets. `dev.py fast` is run here with only the repo-map test module excluded because mapped artifacts are deliberately still frozen during review; no other fast test is skipped. Do not replace either gate with a print-only invocation or silently skip execution. The complete fast lane, including repo-map drift, runs after regeneration below.

### Step 5: Failure injection review

Before completion, inspect evidence for each boundary:

| Boundary | Required proof |
|---|---|
| Backend unavailable | typed failure, no local downgrade |
| Authorized Local mutation | exact live operator grant plus mandatory standalone clone; candidate refs/common-dir are private; failed verify leaves canonical unchanged |
| Forged/stale Local trust | copied task/receipt/control DB, restart without fresh top-level authorization, expiry/revocation, or base/spec mismatch yields unknown and zero launch/provision effects |
| Stale capability receipt | any provider/plan/image/SBOM/broker/env/mount/host-runtime/expiry drift yields typed unavailable until a real canary reissues evidence |
| Docker mutation | bind mount is the private standalone clone, never canonical/common-dir/control root |
| Model launch closure | first-statement transaction authority required; invalid authority has zero filesystem/log/session side effects |
| Docker credential separation | authenticated driver cannot execute repo code; command sandbox has no provider secret/profile/session and all process events have broker receipts |
| Credential issuance crash | pre-registered cleanup identity makes partial channel discoverable; recovery revokes/expires/destroys it without persisting recoverable secret bytes |
| Runtime projection | no generated context enters the candidate snapshot/manifest; no canonical/host-only argv, inherited env, settings, task, session, or launcher path |
| Remote mutation without collection | refusal before launch |
| Candidate crash | checkpoint SHA and recovery receipt |
| Hard process death during candidate execution | registered lease is quiesced and checkpointed before reuse |
| Candidate restaging conflict | exact snapshot/base/manifest binding refuses; canonical unchanged |
| Verifier failure | canonical unchanged |
| Docker verifier escape attempt | new credentialless contained runner cannot reach host/canonical/common-dir/journal |
| Verifier mutates tracked verification clone | integrity failure, no promotion |
| Poisoned Git extensions/attributes | sterile host Git canary executes no hook/filter/fsmonitor/diff/merge/signing helper |
| Canonical `info/attributes` filter | sterile shadow Git directory prevents the highest-precedence filter/process from executing |
| Partial/promisor object | no-lazy-fetch typed refusal; no transport/credential helper or network activity |
| Cooperative canonical Git writer during promotion | standard `index.lock` refusal; no ref/index/worktree overwrite |
| Canonical ref moves before CAS | atomic old-OID CAS refusal, no overwrite |
| Direct plumbing ignores the fence | scoped `post_promotion_divergence`, preserved evidence, never `done` |
| CAS commits then canonical moves again | immutable promotion/reconciliation receipts preserve historical landing without an auxiliary-ref atomicity claim |
| Crash after index fence or ref CAS | owned goldstone/proposed-index journal reconciliation, no missing landing truth |
| Crash after durable promoted phase | TaskState acknowledgement and cleanup still reconcile idempotently |
| Crash during materialization/index install | no terminal done; exact safe reconciliation or explicit fenced conflict |
| Same-SID retry plus Git GC | immutable checkpoint ref remains readable |
| Candidate changes `.gitignore`/runtime path | external control roots and reserved-path rejection prevent overwrite |
| Ignored/untracked materialization collision | pre-CAS refusal; no forced cleanup or overwrite |
| Promotion succeeds, cleanup fails | landed SHA true plus cleanup warning |
| TaskState save/ack fails after promotion | typed recovery-only pending; no retry/model/clone; live identity preserved and `done` waits for acknowledgement |
| Parallel candidate rejected | expected chain does not advance |
| Society path selected first | every worker still has clone/transaction authority; no shared-work-dir launch or terminal write |
| Stronger backend selected | Society/solution forks do not bypass it |
| Revision sealed | no adversary or runner-up mutation |

### Step 6: Independent review and final commit

Request a final specification review and code-quality review. Resolve every P0/P1 issue and rerun the command affected by each correction. After **every** source or test correction, rerun all of Step 3's manifest-derived Tasks 1-4 pytest/compile/lint/typecheck closure, then all of Step 4's changed-source compile/lint/typecheck, affected-test execution, pre-map fast lane, and diff/status gates; a narrower “affected command” is additional evidence, never a substitute.

Correction admission uses the **current observed diff**, not the historical Tasks 1-4 `required-changes` union: every currently modified/untracked source or test path must belong to the Tasks 1-4 `all` union; that exact current set is both Allowed and Required, while its intersection with the Tasks 1-4 test union is Tests. This prevents an impossible requirement that all previously committed paths change again. The installed source-leaf closure (`bootstrap/galaxy_launcher/**` except the developer-only redirect/dev-tool lock, plus production `containers/galaxy/*.Dockerfile` image inputs) is frozen after Task 1; later exact-final `containers/galaxy/*.py` entrypoints are controller-runtime leaves, not TOFU source leaves. Frozen source leaves are created with their final stable navigation headers, and Task 5 map generation must produce no such diff. If review discovers a frozen-leaf correction, or map generation changes one, abort this implementation wave: keep the inactive old root authoritative, invalidate the uncommitted later-wave assumption, make the correction in a new reviewed Task 1 proposal, and repeat the entire canonicalization, closed-harness review, and fresh exact TOFU ceremony before any source CAS. This wave deliberately does not invent an unimplemented in-place root-rotation API during final review. Generic unattended approval is insufficient.

For each non-root correction batch, run this exact external source-update transaction; the compact uploader is the same four-role/8-KiB protocol tested in Tasks 1/2:

```powershell
$pinnedPowerShell = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'; $singularityClient = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) '9to5\singularity\bin\singularity-admin-client.ps1'
function Invoke-SingularityAdmin { & $pinnedPowerShell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $singularityClient --request-only --require-server-validated-client-digest @args }
$repoRoot = [System.IO.Path]::GetFullPath((git rev-parse --show-toplevel).Trim()); if ($LASTEXITCODE -ne 0 -or $repoRoot -notmatch '^[A-Za-z]:\\') { throw 'Invalid correction repository root' }
function Complete-SingularityTopLevelSlot{param([string]$Repository);$currentPurpose=(Invoke-SingularityAdmin resolve-current-top-level-transition --repo $Repository --repository-global-all-generations --read-only --require-unique-live-slot --print-none-or-bound-purpose-receipt).Trim();if($LASTEXITCODE-ne 0-or-not$currentPurpose){throw 'Pure slot lookup failed; settlement is forbidden'};if($currentPurpose-eq'none'){return 'none'};if($currentPurpose-notmatch'^purpose_[0-9a-f]{64}$'){throw 'Invalid occupied purpose receipt'};$slotResult=(Invoke-SingularityAdmin observe-top-level-transition --repo $Repository --repository-global-all-generations --bound-purpose-receipt $currentPurpose --read-only --include-owner-lease-and-fencing-generation --require-latest-journal-live-state-and-ingress --closed-terminal-map singularity-top-level-terminal-v1 --print-owner-state-recovery-pending-or-terminal-observation).Trim();if($LASTEXITCODE-ne 0-or-not$slotResult){throw 'Occupied slot state is unknown'};if($slotResult-in@('active_owned_elsewhere','owner_liveness_unknown')){throw "Live or unproven slot owner blocks takeover: $currentPurpose"};if($slotResult-eq'recovery_pending'){throw "Slot recovery remains pending: $currentPurpose"};if($slotResult-match'^recoverable_dead_owner_([0-9a-f]{64})$'){$eligibilityReceipt=$Matches[1];$recoveryOwnerFence=(Invoke-SingularityAdmin settle-top-level-transition --repo $Repository --repository-global-all-generations --bound-purpose-receipt $currentPurpose --dead-owner-eligibility-receipt $eligibilityReceipt --revalidate-owner-dead-expired-and-quiesced-under-slot-lock --advance-owner-fencing-generation-before-mutation --existing-slot-only --journal-bound-settlement --allow-cancel-only-with-no-begin-proof --no-new-candidate --no-new-selection --no-unbound-state-adoption --persist-before-response --print-recovery-owner-fence-receipt).Trim();if($LASTEXITCODE-ne 0-or$recoveryOwnerFence-notmatch'^ownerfence_[0-9a-f]{64}$'){throw 'Dead-owner settlement failed safely'};$slotResult=(Invoke-SingularityAdmin observe-top-level-transition --repo $Repository --repository-global-all-generations --bound-purpose-receipt $currentPurpose --transition-owner-fence-receipt $recoveryOwnerFence --require-current-owner-fencing-generation --read-only --require-latest-journal-live-state-and-ingress --closed-terminal-map singularity-top-level-terminal-v1 --print-terminal-observation-or-recovery-pending).Trim()};if($slotResult-notmatch'^terminal_(cutover|source|controller)_(achieved|retryable_old|verified_rollback|safe_failed)_([0-9a-f]{64})$'){throw 'Occupied slot is not in an acknowledgeable closed terminal state'};$terminalKind=$Matches[2];Invoke-SingularityAdmin acknowledge-terminal-disposition --repo $Repository --repository-global-all-generations --bound-purpose-receipt $currentPurpose --terminal-observation-token $slotResult --closed-terminal-map singularity-top-level-terminal-v1 --revalidate-observation-still-current-before-ack --require-current-owner-fencing-generation-bound-to-observation --atomic-under-slot-lock --reject-cross-operation-purpose-epoch-or-owner-token-replay --idempotent --persist-before-response|Out-Null;$ackExit=$LASTEXITCODE;$afterAck=(Invoke-SingularityAdmin resolve-transition-purpose-outcome --repo $Repository --purpose-receipt $currentPurpose --read-only --require-unique-exact-archive --require-observation-acknowledgement-chain --print-archived-outcome).Trim();$expected=@{achieved='archived_achieved';retryable_old='archived_retryable';verified_rollback='archived_rollback';safe_failed='archived_failed'};if($LASTEXITCODE-ne 0-or$afterAck-ne$expected[$terminalKind]){throw "Terminal archive disagreement after ack_exit=$ackExit"};$released=(Invoke-SingularityAdmin resolve-current-top-level-transition --repo $Repository --repository-global-all-generations --read-only --require-unique-live-slot --print-none-or-bound-purpose-receipt).Trim();if($LASTEXITCODE-ne 0-or$released-ne'none'){throw 'Acknowledged slot did not release'};return "$afterAck|$currentPurpose"}
function Resolve-SingularityPurposeStartDisposition{param([string]$Repository,[string]$DesiredPurpose,[string]$PriorTerminal);if($DesiredPurpose-notmatch'^purpose_[0-9a-f]{64}$'){throw 'Invalid desired-purpose receipt'};if($PriorTerminal-ne'none'){$parts=@($PriorTerminal-split'\|',2);if($parts.Count-ne 2){throw 'Malformed prior terminal result'};$relationship=(Invoke-SingularityAdmin classify-purpose-successor --repo $Repository --completed-purpose-receipt $parts[1] --desired-purpose-receipt $DesiredPurpose --read-only --require-closed-reviewed-purpose-dag --require-explicit-wave-restart-edge --reject-multiple-matching-archives --print-same-allowed-predecessor-or-unrelated).Trim();if($LASTEXITCODE-ne 0-or$relationship-eq'unrelated_or_new_epoch'){throw 'Prior and desired purposes lack an allowed relationship'};if($relationship-eq'allowed_predecessor'-and$parts[0]-ne'archived_achieved'){throw 'Only an achieved predecessor may advance'}};$outcome=(Invoke-SingularityAdmin resolve-transition-purpose-outcome --repo $Repository --purpose-receipt $DesiredPurpose --read-only --require-unique-exact-archive --print-clear-never-started-or-archived-outcome).Trim();if($outcome-eq'archived_achieved'){return 'already_achieved'};if($outcome-in@('clear_never_started','archived_retryable')){return 'proceed'};throw "Desired purpose is not runnable: $outcome"}
$priorTerminal=Complete-SingularityTopLevelSlot $repoRoot
$correctionInvocationState=(Invoke-SingularityAdmin resolve-repeatable-purpose-invocation-state --repo $repoRoot --reviewed-plan-node task5-correction-v1 --bind-active-reviewed-wave-epoch --read-only --caller-result-is-non-authorizing --native-no-follow-current-canonical-index-worktree --require-unique-result-state-and-predecessor --require-achieved-clean-to-match-exact-committed-result-with-no-new-dirty-batch --reject-ambiguous-or-recovery-pending --print-first-new-existing-invocation-only-clear-retryable-or-achieved-clean).Trim()
if($LASTEXITCODE-ne 0-or-not$correctionInvocationState){throw 'Repeatable correction invocation state is not uniquely recoverable before live-diff inspection'}
$correctionInvocationReceipt=$null;$correctionExpectedPurpose=$null;$correctionInvocationPredecessor=$null
if($correctionInvocationState-match'^achieved_clean\|(purpose_[0-9a-f]{64})$'){$alreadyPurpose=$Matches[1];$alreadyOutcome=(Invoke-SingularityAdmin resolve-transition-purpose-outcome --repo $repoRoot --purpose-receipt $alreadyPurpose --read-only --require-unique-exact-archive --require-current-canonical-index-worktree-exact-committed-result-and-no-new-dirty-batch --print-archived-outcome).Trim();if($LASTEXITCODE-ne 0-or$alreadyOutcome-ne'archived_achieved'){throw 'Achieved correction result-state proof is stale or contradictory'};Write-Output 'The latest exact correction invocation was already authoritatively completed and acknowledged';return}
if($correctionInvocationState-eq'first_invocation'){$correctionInvocationPredecessor='first_invocation'}elseif($correctionInvocationState-match'^new_batch_after\|(purpose_[0-9a-f]{64})$'){$correctionInvocationPredecessor=$correctionInvocationState}elseif($correctionInvocationState-match'^existing_invocation_only\|(invocation_[0-9a-f]{64})$'){$correctionInvocationReceipt=$Matches[1]}elseif($correctionInvocationState-match'^existing_clear\|(invocation_[0-9a-f]{64})\|(purpose_[0-9a-f]{64})$'){$correctionInvocationReceipt=$Matches[1];$correctionExpectedPurpose=$Matches[2]}elseif($correctionInvocationState-match'^existing_retryable\|(invocation_[0-9a-f]{64})\|(purpose_[0-9a-f]{64})$'){$correctionInvocationReceipt=$Matches[1];$correctionExpectedPurpose=$Matches[2]}else{throw "Unsupported or unsafe correction invocation state: $correctionInvocationState"}
$planPath = 'docs/superpowers/plans/2026-07-13-galaxy-r3-transactional-kernel.md'
function Get-GalaxyManifest { param([string]$Kind) $paths = @(python tools/galaxy_plan_manifest.py --plan $planPath --task 1 --task 2 --task 3 --task 4 --kind $Kind); if ($LASTEXITCODE -ne 0 -or -not $paths.Count -or @($paths | Sort-Object -Unique).Count -ne $paths.Count) { throw "GALAXY correction manifest extraction failed: $Kind" }; return $paths }
$allowedUniverse = @(Get-GalaxyManifest all); $testUniverse = @(Get-GalaxyManifest tests)
$cachedCorrection = @(git diff --cached --name-only); if ($LASTEXITCODE -ne 0) { throw 'Unable to enumerate staged correction paths' }; if ($cachedCorrection.Count) { throw "Pre-staged correction paths are forbidden: $($cachedCorrection -join ', ')" }
$currentTracked = @(git diff HEAD --name-only); if ($LASTEXITCODE -ne 0) { throw 'Unable to enumerate tracked correction paths' }
$currentUntracked = @(git ls-files --others --exclude-standard); if ($LASTEXITCODE -ne 0) { throw 'Unable to enumerate untracked correction paths' }
$correctionPaths = @($currentTracked + $currentUntracked | Sort-Object -Unique)
if (-not $correctionPaths.Count) { throw 'No correction paths are present; do not create an empty source update' }
foreach ($path in $correctionPaths) { if ([string]::IsNullOrWhiteSpace($path) -or $path.Length -gt 240) { throw "Invalid correction path: $path" } }
$outside = @($correctionPaths | Where-Object { $_ -notin $allowedUniverse }); if ($outside.Count) { throw "Correction paths outside Tasks 1-4: $($outside -join ', ')" }
$correctionTests = @($correctionPaths | Where-Object { $_ -in $testUniverse })
$rootLeaves = @($correctionPaths | Where-Object { (($_ -like 'bootstrap/galaxy_launcher/*') -and $_ -notin @('bootstrap/galaxy_launcher/developer_redirect.ps1','bootstrap/galaxy_launcher/dev_tools.lock.json')) -or $_ -like 'containers/galaxy/*.Dockerfile' })
if ($rootLeaves.Count) { throw "Trust-root correction requires aborting and restarting the wave from reviewed Task 1 plus fresh TOFU: $($rootLeaves -join ', ')" }
if($correctionInvocationReceipt){$resolvedInvocation=(Invoke-SingularityAdmin resolve-repeatable-purpose-invocation --repo $repoRoot --reviewed-plan-node task5-correction-v1 --bind-active-reviewed-wave-epoch --invocation-receipt $correctionInvocationReceipt --capture-native-no-follow-current-dirty-batch --bind-canonicalization-policy strict-utf8-parent-bom-preserving-crlf-to-lf-or-exact --require-current-old-state-batch-policy-and-reviewed-universe-exact --read-only --require-unique-exact --print-invocation-receipt-or-none).Trim();if($LASTEXITCODE-ne 0-or$resolvedInvocation-ne$correctionInvocationReceipt){throw 'Retryable correction invocation no longer matches the exact current batch'}}else{$invocationIssueReply=(Invoke-SingularityAdmin acquire-repeatable-purpose-invocation --repo $repoRoot --reviewed-plan-node task5-correction-v1 --bind-active-reviewed-wave-epoch --predecessor-disposition $correctionInvocationPredecessor --rederive-and-revalidate-predecessor-under-protected-ledger-lock --reject-caller-asserted-predecessor-authority --capture-native-no-follow-current-dirty-batch --bind-canonicalization-policy strict-utf8-parent-bom-preserving-crlf-to-lf-or-exact --require-batch-within-reviewed-task1-through-task4-universe --create-or-return-exact --persist-before-response --print-invocation-receipt).Trim();$invocationIssueExit=$LASTEXITCODE;$correctionInvocationReceipt=(Invoke-SingularityAdmin resolve-repeatable-purpose-invocation --repo $repoRoot --reviewed-plan-node task5-correction-v1 --bind-active-reviewed-wave-epoch --predecessor-disposition $correctionInvocationPredecessor --rederive-predecessor-from-protected-ledger-read-snapshot --reject-caller-asserted-predecessor-authority --capture-native-no-follow-current-dirty-batch --bind-canonicalization-policy strict-utf8-parent-bom-preserving-crlf-to-lf-or-exact --require-batch-within-reviewed-task1-through-task4-universe --read-only --require-unique-exact --print-invocation-receipt-or-none).Trim();if($LASTEXITCODE-ne 0-or$correctionInvocationReceipt-notmatch'^invocation_[0-9a-f]{64}$'){throw "Correction invocation is not recoverable after issue_exit=$invocationIssueExit"};if($invocationIssueExit-eq 0-and$invocationIssueReply-and$invocationIssueReply-ne$correctionInvocationReceipt){throw 'Correction invocation issue reply disagrees with authoritative resolution'}}
$purposeIssueReply=(Invoke-SingularityAdmin acquire-transition-purpose --repo $repoRoot --reviewed-plan-node task5-correction-v1 --operation source-update --contract source-update-maintenance-v1 --requested-fences cli-run-closed+discord-disabled+maintenance-index-ref --bind-active-reviewed-wave-epoch --require-wave-epoch-bound-to-current-tofu-receipt --require-satisfied-reviewed-predecessor-ledger --reject-unrelated-or-multiple-predecessor-archives --repeatable-invocation-receipt $correctionInvocationReceipt --require-invocation-bound-exact-old-state-pre-normalization-batch-policy-and-reviewed-universe --recapture-native-no-follow-current-batch-and-require-invocation-exact-before-purpose-use --create-or-return-exact --persist-before-response --print-purpose-receipt).Trim();$purposeIssueExit=$LASTEXITCODE
$transitionPurpose=(Invoke-SingularityAdmin resolve-transition-purpose --repo $repoRoot --reviewed-plan-node task5-correction-v1 --operation source-update --contract source-update-maintenance-v1 --requested-fences cli-run-closed+discord-disabled+maintenance-index-ref --bind-active-reviewed-wave-epoch --require-wave-epoch-bound-to-current-tofu-receipt --require-satisfied-reviewed-predecessor-ledger --reject-unrelated-or-multiple-predecessor-archives --repeatable-invocation-receipt $correctionInvocationReceipt --require-invocation-bound-exact-old-state-pre-normalization-batch-policy-and-reviewed-universe --recapture-native-no-follow-current-batch-and-require-invocation-exact-before-purpose-use --read-only --require-unique-exact --print-purpose-receipt-or-none).Trim();if($LASTEXITCODE-ne 0-or$transitionPurpose-notmatch'^purpose_[0-9a-f]{64}$'){throw "Correction purpose is not recoverable after issue_exit=$purposeIssueExit"};if($purposeIssueExit-eq 0-and$purposeIssueReply-and$purposeIssueReply-ne$transitionPurpose){throw 'Correction purpose issue reply disagrees with resolution'}
if($correctionExpectedPurpose-and$transitionPurpose-ne$correctionExpectedPurpose){throw 'Existing correction invocation resolved to a different purpose'}
$slotOutcome=Resolve-SingularityPurposeStartDisposition $repoRoot $transitionPurpose $priorTerminal;if($slotOutcome-eq'already_achieved'){Write-Output 'This exact correction batch was already authoritatively completed and acknowledged';return}
$sourceIntentReply=(Invoke-SingularityAdmin acquire-begin-intent --repo $repoRoot --operation source-update --contract source-update-maintenance-v1 --transition-purpose-receipt $transitionPurpose --require-exact-purpose-binding --require-reviewed-purpose-dag --requested-fences cli-run-closed+discord-disabled+maintenance-index-ref --bind-exact-old-state --require-purpose-bound-pre-normalization-input-still-current-no-follow --exclusive-top-level-mutation-per-registered-repo-all-generations --create-or-return-unique-slot --persist-before-response --print-request-id).Trim();$sourceIntentExit=$LASTEXITCODE
$sourceUpdateRequestId=(Invoke-SingularityAdmin resolve-begin-intent --repo $repoRoot --operation source-update --contract source-update-maintenance-v1 --transition-purpose-receipt $transitionPurpose --require-exact-purpose-binding --requested-fences cli-run-closed+discord-disabled+maintenance-index-ref --bind-exact-old-state --require-purpose-bound-pre-normalization-input-still-current-no-follow --exclusive-top-level-mutation-per-registered-repo-all-generations --read-only --require-unique-slot --require-persisted-intent --print-request-id-or-none).Trim()
if($LASTEXITCODE-ne 0-or-not$sourceUpdateRequestId-or$sourceUpdateRequestId-eq'none'){throw "Correction source-update intent is not authoritatively discoverable after intent_exit=$sourceIntentExit; recover by repository and operation contract without starting another transition"};if($sourceIntentExit-eq 0-and$sourceIntentReply-and$sourceIntentReply-ne$sourceUpdateRequestId){throw 'Correction intent reply disagrees with authoritative intent discovery; do not start another transition'}
$ownerFenceReceipt=(Invoke-SingularityAdmin resolve-begin-intent-owner-fence --repo $repoRoot --request-id $sourceUpdateRequestId --transition-purpose-receipt $transitionPurpose --read-only --require-current-owner-lease-and-fencing-generation --print-owner-fence-receipt).Trim();if($LASTEXITCODE-ne 0-or$ownerFenceReceipt-notmatch'^ownerfence_[0-9a-f]{64}$'){throw 'Correction owner-fence receipt is unavailable; do not begin'}
function Invoke-SingularityAdmin { $recoveryCommands=@('resolve-current-top-level-transition','observe-top-level-transition','settle-top-level-transition','acknowledge-terminal-disposition','resolve-transition-purpose-outcome');if($args.Count-and$args[0]-in$recoveryCommands){& $pinnedPowerShell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $singularityClient --request-only --require-server-validated-client-digest @args}else{& $pinnedPowerShell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $singularityClient --request-only --require-server-validated-client-digest --transition-purpose-receipt $transitionPurpose --transition-owner-fence-receipt $ownerFenceReceipt --require-current-owner-fencing-generation @args} }
$sourceReplyTx=(Invoke-SingularityAdmin begin-source-update --request-id $sourceUpdateRequestId --idempotent-create --repo $repoRoot --require-exact-purpose-binding --revalidate-purpose-bound-input-under-slot-lock-before-started-old --close-cli-run-ingress --keep-discord-listener-disabled --hold-maintenance-index-and-ref-fences --persist-begin-receipt-before-response).Trim();$sourceReplyExit=$LASTEXITCODE
$sourceTx=(Invoke-SingularityAdmin resolve-source-update-begin --request-id $sourceUpdateRequestId --repo $repoRoot --read-only --require-exact-request-binding --require-exact-purpose-binding --require-purpose-bound-input-attested-if-started --require-persisted-begin-receipt-if-started --require-latest-monotone-journal-if-started --require-exact-old-state-if-started --require-live-requested-fences-held-if-started --classify-started-exact-requested-fences-held-or-not-started --print-transaction-or-not-started).Trim()
if($LASTEXITCODE-ne 0-or-not$sourceTx){throw "Correction source-update begin state uncertain after begin_exit=$sourceReplyExit; do not use or infer ingress state; recover by repository and operation contract"};if($sourceTx-eq'not_started'){throw "Correction source update did not start; durable request ID $sourceUpdateRequestId"};if($sourceReplyExit-eq 0-and$sourceReplyTx-and$sourceReplyTx-ne$sourceTx){throw 'Correction begin reply disagrees with authoritative resolution; do not infer ingress state'}
function Stop-BeforeCorrectionCas { param([string]$Reason, [string]$Proposal)
  $a=@('abort-source-update','--transaction',$sourceTx,'--before-cas-only','--abort-all-child-resources','--reconcile-journaled-normalization','--restore-developer-ingress-only-if-old-ref-index-tree-exact','--keep-production-run-inactive','--keep-discord-listener-disabled','--persist-and-reread-recovery-receipt','--print-disposition'); if($Proposal){$a+=@('--proposal',$Proposal)}
  Invoke-SingularityAdmin @a | Out-Null; $abortExit=$LASTEXITCODE
  $d=(Invoke-SingularityAdmin resolve-source-update-disposition --transaction $sourceTx --read-only --require-persisted-receipt --require-production-run-inactive --require-discord-listener-disabled --classify-safe-old-developer-ingress-open-or-held-closed-or-recovery-pending --print-disposition).Trim()
  if($LASTEXITCODE-ne 0-or$d-notin@('safe_old_developer_ingress_open','safe_old_developer_ingress_held_closed','fenced_recovery_pending')){throw "$Reason; authoritative disposition unavailable after abort_exit=$abortExit; do not infer ingress state; recover transaction $sourceTx"}
  throw "$Reason; authoritative disposition=$d"
}
function Stop-AfterCorrectionCas { param([string]$Reason, [string]$Proposal)
  Invoke-SingularityAdmin reconcile-source-update --transaction $sourceTx --proposal $Proposal --classify-old-or-exact-new-ref-index-tree --finish-only-journal-bound-materialization-attestation-and-ingress --keep-production-run-inactive --keep-discord-listener-disabled --persist-and-reread-recovery-receipt --print-disposition | Out-Null; $reconcileExit=$LASTEXITCODE
  $d=(Invoke-SingularityAdmin resolve-source-update-disposition --transaction $sourceTx --read-only --require-persisted-receipt --require-production-run-inactive --require-discord-listener-disabled --classify-safe-old-or-committed-exact-new-with-ingress-or-recovery-pending --print-disposition).Trim()
  if($LASTEXITCODE-ne 0-or$d-notin@('safe_old_developer_ingress_open','safe_old_developer_ingress_held_closed','committed_exact_new_developer_ingress_open','committed_exact_new_developer_ingress_held_closed','fenced_recovery_pending')){throw "$Reason; authoritative disposition unavailable after reconcile_exit=$reconcileExit; do not infer ingress state; recover transaction $sourceTx"}
  throw "$Reason; authoritative disposition=$d; re-enter through recovery"
}
function Register-ExactChangeManifest { param([string]$Scope,[string[]]$Paths,[string[]]$Tests)
  function ConvertTo-SingularityManifestBase64Url { param([string]$CanonicalJson) $bytes=([System.Text.UTF8Encoding]::new($false,$true)).GetBytes($CanonicalJson);if($bytes.Length-gt 4096){throw 'Path-manifest decoded JSON exceeds 4096 bytes'};return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_') }
  $testSet=New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal);foreach($t in $Tests){if(-not$testSet.Add($t)-or$t-notin$Paths){throw "Invalid correction test subset: $t"}}
  $records=@($Paths|ForEach-Object{[ordered]@{role=$(if($testSet.Contains($_)){'required-test'}else{'required-change'});path=$_}})
  $id=(Invoke-SingularityAdmin begin-path-manifest --scope $Scope --expected-total-count $Paths.Count --expected-required-count $Paths.Count --expected-test-count $Tests.Count).Trim();if($LASTEXITCODE-ne 0-or-not$id){throw 'Unable to begin correction path manifest'}
  $seq=0;$chunk=@();foreach($r in $records){$trial=@($chunk+$r);$j=([ordered]@{sequence=$seq;records=$trial}|ConvertTo-Json -Compress -Depth 4);if(($trial.Count-gt 24-or[Text.Encoding]::UTF8.GetByteCount($j)-gt 4096)-and$chunk.Count){$j=([ordered]@{sequence=$seq;records=$chunk}|ConvertTo-Json -Compress -Depth 4);$payload=ConvertTo-SingularityManifestBase64Url $j;Invoke-SingularityAdmin append-path-manifest --scope $Scope --manifest $id --sequence $seq --canonical-records-json-base64url $payload --require-strict-unpadded-base64url --require-decoded-canonical-json-max-bytes 4096 --require-decode-recanonicalize-byte-equality --require-exact-envelope-max-bytes 8192;if($LASTEXITCODE-ne 0){throw 'Correction path chunk failed'};$seq+=1;$chunk=@($r)}else{$chunk=$trial}}
  if($chunk.Count){$j=([ordered]@{sequence=$seq;records=$chunk}|ConvertTo-Json -Compress -Depth 4);$payload=ConvertTo-SingularityManifestBase64Url $j;Invoke-SingularityAdmin append-path-manifest --scope $Scope --manifest $id --sequence $seq --canonical-records-json-base64url $payload --require-strict-unpadded-base64url --require-decoded-canonical-json-max-bytes 4096 --require-decode-recanonicalize-byte-equality --require-exact-envelope-max-bytes 8192;if($LASTEXITCODE-ne 0){throw 'Final correction path chunk failed'}}
  $receipt=(Invoke-SingularityAdmin seal-path-manifest --scope $Scope --manifest $id --canonical-order --sha256 --require-total-count $Paths.Count --require-required-count $Paths.Count --require-test-count $Tests.Count --persist-and-reread).Trim();if($LASTEXITCODE-ne 0-or-not$receipt){throw 'Correction path-manifest seal failed'};return $receipt
}
try { $pathReceipt=Register-ExactChangeManifest $sourceTx $correctionPaths $correctionTests } catch { Stop-BeforeCorrectionCas "Correction manifest failure: $($_.Exception.Message)" '' }
$normalizationReceipt=(Invoke-SingularityAdmin normalize-developer-source --transaction $sourceTx --repo $repoRoot --path-manifest-receipt $pathReceipt --chain-purpose-pre-normalization-batch-and-policy --require-exact-purpose-batch-membership --strict-utf8-parent-bom-preserving-crlf-to-lf-only --binary-exact --ensure-symbolic-loose-head-same-oid --create-if-absent-or-verify-existing-loose-head --native-full-tree-exact-index-bytes --no-ambient-git-config --no-hooks --no-filters --require-no-unexpected-change --persist-before-response --print-normalization-receipt).Trim();if($LASTEXITCODE-ne 0-or$normalizationReceipt-notmatch'^normalization_[0-9a-f]{64}$'){Stop-BeforeCorrectionCas 'Correction normalization failed or did not chain the immutable purpose batch' ''}
$proposalTx=(Invoke-SingularityAdmin prepare-source-commit --transaction $sourceTx --repo $repoRoot --path-manifest-receipt $pathReceipt --normalization-receipt $normalizationReceipt --require-pre-normalization-purpose-chain --native-no-follow-snapshot --parent-plus-allowlist-complete-tree --fixed-commit-metadata --message 'fix: address GALAXY final review').Trim();if($LASTEXITCODE-ne 0-or-not $proposalTx){Stop-BeforeCorrectionCas 'Correction proposal failed' ''}
Invoke-SingularityAdmin review-source-proposal --transaction $proposalTx --sealed-independent-reviewer --require-two-independent-review-passes --persist-and-reread-review-receipt --no-canonical-write;if($LASTEXITCODE-ne 0){Stop-BeforeCorrectionCas 'Correction review failed' $proposalTx}
Invoke-SingularityAdmin verify-source-proposal --transaction $proposalTx --normalization-receipt $normalizationReceipt --require-pre-normalization-purpose-chain --require-exact-manifest --require-every-required-path-changed --require-no-unexpected-change --require-review-receipt --require-no-canonical-ref-write;if($LASTEXITCODE-ne 0){Stop-BeforeCorrectionCas 'Correction exact verification failed' $proposalTx}
Invoke-SingularityAdmin commit-source-proposal --transaction $proposalTx --source-update $sourceTx --normalization-receipt $normalizationReceipt --require-pre-normalization-purpose-chain --require-fresh-exact-digest-approval --cas-loose-ref --native-full-tree-materialize --install-verified-index --require-final-byte-clean --durable --keep-production-run-inactive;if($LASTEXITCODE-ne 0){Stop-AfterCorrectionCas 'Correction source commit reported failure' $proposalTx}
Invoke-SingularityAdmin attest-committed-source --transaction $sourceTx --proposal $proposalTx --require-loose-head --require-exact-index-worktree-bytes --require-source-receipt --keep-production-run-inactive;if($LASTEXITCODE-ne 0){Stop-AfterCorrectionCas 'Correction source attestation failed' $proposalTx}
Invoke-SingularityAdmin finish-source-update --transaction $sourceTx --release-developer-only-ingress --keep-production-run-inactive --keep-discord-listener-disabled --persist-and-reread-finish-receipt --print-disposition|Out-Null;$finishExit=$LASTEXITCODE;$finishDisposition=(Invoke-SingularityAdmin resolve-source-update-disposition --transaction $sourceTx --read-only --require-persisted-receipt --require-production-run-inactive --require-discord-listener-disabled --classify-safe-old-or-committed-exact-new-with-ingress-or-recovery-pending --print-disposition).Trim();if($LASTEXITCODE-ne 0-or-not$finishDisposition){throw "Correction finish disposition unavailable after finish_exit=$finishExit; do not infer ingress state; recover transaction $sourceTx"};if($finishDisposition-ne'committed_exact_new_developer_ingress_open'){Stop-AfterCorrectionCas "Correction finish resolved as $finishDisposition" $proposalTx}
$terminalOutcome=Complete-SingularityTopLevelSlot $repoRoot;if($terminalOutcome-ne"archived_achieved|$transitionPurpose"){throw 'Correction terminal transition was not observed, acknowledged, archived, and released as achieved'}
```

Repeat independent review and the **entire** Step 3 plus Step 4 closure after this commit. Repeat correction admission until no P0/P1 remains and the tracked/untracked implementation tree is clean. Reviewer fixes never enter the later documentation/map/evidence commit.

Only after that fixed point, regenerate navigation artifacts and derive map scope from **all** new tracked diffs rather than a handpicked directory list:

```powershell
$cachedPaths = @(git diff --cached --name-only)
if ($LASTEXITCODE -ne 0) { throw 'Unable to enumerate pre-map staged paths' }
if ($cachedPaths.Count) { throw "Pre-staged paths before map generation: $($cachedPaths -join ', ')" }
$preMapTracked = @(git diff --name-only)
if ($LASTEXITCODE -ne 0) { throw 'Unable to enumerate pre-map tracked paths' }
$unexpectedPreMap = @($preMapTracked)
if ($unexpectedPreMap.Count) { throw "Dirty tree before map generation: $($unexpectedPreMap -join ', ')" }
$unexpectedUntracked = @(git ls-files --others --exclude-standard)
if ($LASTEXITCODE -ne 0) { throw 'Unable to enumerate pre-map untracked paths' }
if ($unexpectedUntracked.Count) { throw "Unexpected untracked paths before map generation: $($unexpectedUntracked -join ', ')" }
python tools/repo_map.py
if ($LASTEXITCODE -ne 0) { throw 'Repository map generation failed' }
python tools/repo_map.py --check
if ($LASTEXITCODE -ne 0) { throw 'Repository map check failed immediately after generation' }
git check-ignore -v AGENTS.md platform_core/AGENTS.md tests/AGENTS.md
if ($LASTEXITCODE -ne 0) { throw 'Generated AGENTS ignore-boundary check failed' }
$postMapTracked = @(git diff --name-only)
if ($LASTEXITCODE -ne 0) { throw 'Unable to enumerate post-map tracked paths' }
$mapPaths = @($postMapTracked | Where-Object { $_ -notin $preMapTracked })
$mapPaths
foreach ($path in $mapPaths) {
  git diff -- $path
  if ($LASTEXITCODE -ne 0) { throw "Unable to inspect generated map path: $path" }
}
python tools/dev.py fast
if ($LASTEXITCODE -ne 0) { throw 'Post-map complete fast lane failed' }
```

Inspect every `$mapPaths` diff, regardless of package. The set may contain only `.repo-map.json`, `.llm-map.json`, or files whose changes are exclusively generated `@AI-MAP` headers. Any functional/source-body diff fails the gate. Ignored `AGENTS.md` files remain local derived navigation. Only after this post-map gate is green, materialize `docs/superpowers/reports/2026-07-13-galaxy-r3-kernel-evidence.md` from the Step 1 schema with the final command/receipt results, review its exact bytes, and require it to be the sole untracked file.

Commit:

```powershell
$pinnedPowerShell = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'; $singularityClient = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) '9to5\singularity\bin\singularity-admin-client.ps1'
function Invoke-SingularityAdmin { & $pinnedPowerShell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $singularityClient --request-only --require-server-validated-client-digest @args }
$repoRoot = [System.IO.Path]::GetFullPath((git rev-parse --show-toplevel).Trim()); if ($LASTEXITCODE -ne 0 -or $repoRoot -notmatch '^[A-Za-z]:\\') { throw 'Invalid final repository root' }
function Complete-SingularityTopLevelSlot{param([string]$Repository);$currentPurpose=(Invoke-SingularityAdmin resolve-current-top-level-transition --repo $Repository --repository-global-all-generations --read-only --require-unique-live-slot --print-none-or-bound-purpose-receipt).Trim();if($LASTEXITCODE-ne 0-or-not$currentPurpose){throw 'Pure slot lookup failed; settlement is forbidden'};if($currentPurpose-eq'none'){return 'none'};if($currentPurpose-notmatch'^purpose_[0-9a-f]{64}$'){throw 'Invalid occupied purpose receipt'};$slotResult=(Invoke-SingularityAdmin observe-top-level-transition --repo $Repository --repository-global-all-generations --bound-purpose-receipt $currentPurpose --read-only --include-owner-lease-and-fencing-generation --require-latest-journal-live-state-and-ingress --closed-terminal-map singularity-top-level-terminal-v1 --print-owner-state-recovery-pending-or-terminal-observation).Trim();if($LASTEXITCODE-ne 0-or-not$slotResult){throw 'Occupied slot state is unknown'};if($slotResult-in@('active_owned_elsewhere','owner_liveness_unknown')){throw "Live or unproven slot owner blocks takeover: $currentPurpose"};if($slotResult-eq'recovery_pending'){throw "Slot recovery remains pending: $currentPurpose"};if($slotResult-match'^recoverable_dead_owner_([0-9a-f]{64})$'){$eligibilityReceipt=$Matches[1];$recoveryOwnerFence=(Invoke-SingularityAdmin settle-top-level-transition --repo $Repository --repository-global-all-generations --bound-purpose-receipt $currentPurpose --dead-owner-eligibility-receipt $eligibilityReceipt --revalidate-owner-dead-expired-and-quiesced-under-slot-lock --advance-owner-fencing-generation-before-mutation --existing-slot-only --journal-bound-settlement --allow-cancel-only-with-no-begin-proof --no-new-candidate --no-new-selection --no-unbound-state-adoption --persist-before-response --print-recovery-owner-fence-receipt).Trim();if($LASTEXITCODE-ne 0-or$recoveryOwnerFence-notmatch'^ownerfence_[0-9a-f]{64}$'){throw 'Dead-owner settlement failed safely'};$slotResult=(Invoke-SingularityAdmin observe-top-level-transition --repo $Repository --repository-global-all-generations --bound-purpose-receipt $currentPurpose --transition-owner-fence-receipt $recoveryOwnerFence --require-current-owner-fencing-generation --read-only --require-latest-journal-live-state-and-ingress --closed-terminal-map singularity-top-level-terminal-v1 --print-terminal-observation-or-recovery-pending).Trim()};if($slotResult-notmatch'^terminal_(cutover|source|controller)_(achieved|retryable_old|verified_rollback|safe_failed)_([0-9a-f]{64})$'){throw 'Occupied slot is not in an acknowledgeable closed terminal state'};$terminalKind=$Matches[2];Invoke-SingularityAdmin acknowledge-terminal-disposition --repo $Repository --repository-global-all-generations --bound-purpose-receipt $currentPurpose --terminal-observation-token $slotResult --closed-terminal-map singularity-top-level-terminal-v1 --revalidate-observation-still-current-before-ack --require-current-owner-fencing-generation-bound-to-observation --atomic-under-slot-lock --reject-cross-operation-purpose-epoch-or-owner-token-replay --idempotent --persist-before-response|Out-Null;$ackExit=$LASTEXITCODE;$afterAck=(Invoke-SingularityAdmin resolve-transition-purpose-outcome --repo $Repository --purpose-receipt $currentPurpose --read-only --require-unique-exact-archive --require-observation-acknowledgement-chain --print-archived-outcome).Trim();$expected=@{achieved='archived_achieved';retryable_old='archived_retryable';verified_rollback='archived_rollback';safe_failed='archived_failed'};if($LASTEXITCODE-ne 0-or$afterAck-ne$expected[$terminalKind]){throw "Terminal archive disagreement after ack_exit=$ackExit"};$released=(Invoke-SingularityAdmin resolve-current-top-level-transition --repo $Repository --repository-global-all-generations --read-only --require-unique-live-slot --print-none-or-bound-purpose-receipt).Trim();if($LASTEXITCODE-ne 0-or$released-ne'none'){throw 'Acknowledged slot did not release'};return "$afterAck|$currentPurpose"}
function Resolve-SingularityPurposeStartDisposition{param([string]$Repository,[string]$DesiredPurpose,[string]$PriorTerminal);if($DesiredPurpose-notmatch'^purpose_[0-9a-f]{64}$'){throw 'Invalid desired-purpose receipt'};if($PriorTerminal-ne'none'){$parts=@($PriorTerminal-split'\|',2);if($parts.Count-ne 2){throw 'Malformed prior terminal result'};$relationship=(Invoke-SingularityAdmin classify-purpose-successor --repo $Repository --completed-purpose-receipt $parts[1] --desired-purpose-receipt $DesiredPurpose --read-only --require-closed-reviewed-purpose-dag --require-explicit-wave-restart-edge --reject-multiple-matching-archives --print-same-allowed-predecessor-or-unrelated).Trim();if($LASTEXITCODE-ne 0-or$relationship-eq'unrelated_or_new_epoch'){throw 'Prior and desired purposes lack an allowed relationship'};if($relationship-eq'allowed_predecessor'-and$parts[0]-ne'archived_achieved'){throw 'Only an achieved predecessor may advance'}};$outcome=(Invoke-SingularityAdmin resolve-transition-purpose-outcome --repo $Repository --purpose-receipt $DesiredPurpose --read-only --require-unique-exact-archive --print-clear-never-started-or-archived-outcome).Trim();if($outcome-eq'archived_achieved'){return 'already_achieved'};if($outcome-in@('clear_never_started','archived_retryable')){return 'proceed'};throw "Desired purpose is not runnable: $outcome"}
$priorTerminal=Complete-SingularityTopLevelSlot $repoRoot
$finalRecoveredPurpose=$null
$finalResultState=(Invoke-SingularityAdmin resolve-plan-node-purpose-result-state --repo $repoRoot --reviewed-plan-node task5-final-evidence-v1 --bind-active-reviewed-wave-epoch --read-only --native-no-follow-current-canonical-index-worktree --require-unique-exact-purpose-archive --print-none-only-if-never-issued-else-outcome-purpose-and-current-state-relation).Trim()
if($LASTEXITCODE-ne 0-or-not$finalResultState){throw 'Final-evidence result state is not uniquely recoverable before live-diff inspection'}
if($finalResultState-match'^archived_achieved_exact_current\|(purpose_[0-9a-f]{64})$'){$finalRecoveredPurpose=$Matches[1];$finalRecoveredOutcome=(Invoke-SingularityAdmin resolve-transition-purpose-outcome --repo $repoRoot --purpose-receipt $finalRecoveredPurpose --read-only --require-unique-exact-archive --require-current-canonical-index-worktree-exact-committed-result --print-archived-outcome).Trim();if($LASTEXITCODE-ne 0-or$finalRecoveredOutcome-ne'archived_achieved'){throw 'Final-evidence achieved result proof is stale or contradictory'};Write-Output 'Final evidence update was already authoritatively completed and acknowledged';return}elseif($finalResultState-match'^clear_never_started_exact_input\|(purpose_[0-9a-f]{64})$'){$finalRecoveredPurpose=$Matches[1]}elseif($finalResultState-match'^archived_retryable_exact_input\|(purpose_[0-9a-f]{64})$'){$finalRecoveredPurpose=$Matches[1]}elseif($finalResultState-ne'none_never_issued'){throw "Final-evidence node has a non-runnable or divergent archived result: $finalResultState"}
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) { throw 'Pre-existing staged paths; preserve them and stop' }
$reportPath = 'docs/superpowers/reports/2026-07-13-galaxy-r3-kernel-evidence.md'
$finalTracked = @(git diff --name-only); if ($LASTEXITCODE -ne 0) { throw 'Unable to enumerate final tracked paths' }
$finalUntracked = @(git ls-files --others --exclude-standard); if ($LASTEXITCODE -ne 0) { throw 'Unable to enumerate final untracked paths' }
if (@($finalUntracked | Where-Object { $_ -ne $reportPath }).Count -or $reportPath -notin $finalUntracked) { throw "Evidence report must be the sole untracked path: $($finalUntracked -join ', ')" }
$finalPaths = @($finalTracked + $reportPath | Sort-Object -Unique); if (-not $finalPaths.Count) { throw 'Final exact-change set is empty' }
foreach ($path in $finalPaths) { if ([string]::IsNullOrWhiteSpace($path) -or $path.Length -gt 240) { throw "Invalid final path: $path" } }
$finalTests = @($finalPaths | Where-Object { $_.StartsWith('tests/', [StringComparison]::Ordinal) })
$allowedFinalFixed = @('.repo-map.json','.llm-map.json',$reportPath)
$unexpectedFinal = @($finalPaths | Where-Object { $_ -notin $allowedFinalFixed -and -not $_.EndsWith('.py',[StringComparison]::OrdinalIgnoreCase) })
if ($unexpectedFinal.Count) { throw "Final map/evidence set contains an unreviewed path: $($unexpectedFinal -join ', ')" }
git diff --check; if ($LASTEXITCODE -ne 0) { throw 'Final unstaged diff check failed' }
if($finalRecoveredPurpose){$purposeIssueReply=$finalRecoveredPurpose;$purposeIssueExit=0}else{$purposeIssueReply=(Invoke-SingularityAdmin acquire-transition-purpose --repo $repoRoot --reviewed-plan-node task5-final-evidence-v1 --operation source-update --contract source-update-maintenance-v1 --requested-fences cli-run-closed+discord-disabled+maintenance-index-ref --bind-active-reviewed-wave-epoch --require-wave-epoch-bound-to-current-tofu-receipt --require-satisfied-reviewed-predecessor-ledger --reject-unrelated-or-multiple-predecessor-archives --bind-exact-old-state --capture-native-no-follow-pre-normalization-batch --bind-canonicalization-policy strict-utf8-parent-bom-preserving-crlf-to-lf-or-exact --create-or-return-exact --persist-before-response --print-purpose-receipt).Trim();$purposeIssueExit=$LASTEXITCODE}
$transitionPurpose=(Invoke-SingularityAdmin resolve-transition-purpose --repo $repoRoot --reviewed-plan-node task5-final-evidence-v1 --operation source-update --contract source-update-maintenance-v1 --requested-fences cli-run-closed+discord-disabled+maintenance-index-ref --bind-active-reviewed-wave-epoch --require-wave-epoch-bound-to-current-tofu-receipt --require-satisfied-reviewed-predecessor-ledger --reject-unrelated-or-multiple-predecessor-archives --bind-exact-old-state --capture-native-no-follow-pre-normalization-batch --bind-canonicalization-policy strict-utf8-parent-bom-preserving-crlf-to-lf-or-exact --read-only --require-unique-exact --print-purpose-receipt-or-none).Trim();if($LASTEXITCODE-ne 0-or$transitionPurpose-notmatch'^purpose_[0-9a-f]{64}$'){throw "Final evidence purpose is not recoverable after issue_exit=$purposeIssueExit"};if($purposeIssueExit-eq 0-and$purposeIssueReply-and$purposeIssueReply-ne$transitionPurpose){throw 'Final evidence purpose issue reply disagrees with resolution'}
if($finalRecoveredPurpose-and$transitionPurpose-ne$finalRecoveredPurpose){throw 'Existing final-evidence result resolved to a different purpose'}
$slotOutcome=Resolve-SingularityPurposeStartDisposition $repoRoot $transitionPurpose $priorTerminal;if($slotOutcome-eq'already_achieved'){Write-Output 'Final evidence update was already authoritatively completed and acknowledged';return}
$sourceIntentReply=(Invoke-SingularityAdmin acquire-begin-intent --repo $repoRoot --operation source-update --contract source-update-maintenance-v1 --transition-purpose-receipt $transitionPurpose --require-exact-purpose-binding --require-reviewed-purpose-dag --requested-fences cli-run-closed+discord-disabled+maintenance-index-ref --bind-exact-old-state --require-purpose-bound-pre-normalization-input-still-current-no-follow --exclusive-top-level-mutation-per-registered-repo-all-generations --create-or-return-unique-slot --persist-before-response --print-request-id).Trim();$sourceIntentExit=$LASTEXITCODE
$sourceUpdateRequestId=(Invoke-SingularityAdmin resolve-begin-intent --repo $repoRoot --operation source-update --contract source-update-maintenance-v1 --transition-purpose-receipt $transitionPurpose --require-exact-purpose-binding --requested-fences cli-run-closed+discord-disabled+maintenance-index-ref --bind-exact-old-state --require-purpose-bound-pre-normalization-input-still-current-no-follow --exclusive-top-level-mutation-per-registered-repo-all-generations --read-only --require-unique-slot --require-persisted-intent --print-request-id-or-none).Trim()
if($LASTEXITCODE-ne 0-or-not$sourceUpdateRequestId-or$sourceUpdateRequestId-eq'none'){throw "Final source-update intent is not authoritatively discoverable after intent_exit=$sourceIntentExit; recover by repository and operation contract without starting another transition"};if($sourceIntentExit-eq 0-and$sourceIntentReply-and$sourceIntentReply-ne$sourceUpdateRequestId){throw 'Final intent reply disagrees with authoritative intent discovery; do not start another transition'}
$ownerFenceReceipt=(Invoke-SingularityAdmin resolve-begin-intent-owner-fence --repo $repoRoot --request-id $sourceUpdateRequestId --transition-purpose-receipt $transitionPurpose --read-only --require-current-owner-lease-and-fencing-generation --print-owner-fence-receipt).Trim();if($LASTEXITCODE-ne 0-or$ownerFenceReceipt-notmatch'^ownerfence_[0-9a-f]{64}$'){throw 'Final evidence owner-fence receipt is unavailable; do not begin'}
function Invoke-SingularityAdmin { $recoveryCommands=@('resolve-current-top-level-transition','observe-top-level-transition','settle-top-level-transition','acknowledge-terminal-disposition','resolve-transition-purpose-outcome');if($args.Count-and$args[0]-in$recoveryCommands){& $pinnedPowerShell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $singularityClient --request-only --require-server-validated-client-digest @args}else{& $pinnedPowerShell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $singularityClient --request-only --require-server-validated-client-digest --transition-purpose-receipt $transitionPurpose --transition-owner-fence-receipt $ownerFenceReceipt --require-current-owner-fencing-generation @args} }
$sourceReplyTx=(Invoke-SingularityAdmin begin-source-update --request-id $sourceUpdateRequestId --idempotent-create --repo $repoRoot --require-exact-purpose-binding --revalidate-purpose-bound-input-under-slot-lock-before-started-old --close-cli-run-ingress --keep-discord-listener-disabled --hold-maintenance-index-and-ref-fences --persist-begin-receipt-before-response).Trim();$sourceReplyExit=$LASTEXITCODE
$sourceTx=(Invoke-SingularityAdmin resolve-source-update-begin --request-id $sourceUpdateRequestId --repo $repoRoot --read-only --require-exact-request-binding --require-exact-purpose-binding --require-purpose-bound-input-attested-if-started --require-persisted-begin-receipt-if-started --require-latest-monotone-journal-if-started --require-exact-old-state-if-started --require-live-requested-fences-held-if-started --classify-started-exact-requested-fences-held-or-not-started --print-transaction-or-not-started).Trim()
if($LASTEXITCODE-ne 0-or-not$sourceTx){throw "Final source-update begin state uncertain after begin_exit=$sourceReplyExit; do not use or infer ingress state; recover by repository and operation contract"};if($sourceTx-eq'not_started'){throw "Final source update did not start; durable request ID $sourceUpdateRequestId"};if($sourceReplyExit-eq 0-and$sourceReplyTx-and$sourceReplyTx-ne$sourceTx){throw 'Final begin reply disagrees with authoritative resolution; do not infer ingress state'}
function Stop-BeforeFinalCas { param([string]$Reason,[string]$Proposal)
  $a=@('abort-source-update','--transaction',$sourceTx,'--before-cas-only','--abort-all-child-resources','--reconcile-journaled-normalization','--restore-developer-ingress-only-if-old-ref-index-tree-exact','--keep-production-run-inactive','--keep-discord-listener-disabled','--persist-and-reread-recovery-receipt','--print-disposition');if($Proposal){$a+=@('--proposal',$Proposal)}
  Invoke-SingularityAdmin @a | Out-Null;$abortExit=$LASTEXITCODE
  $d=(Invoke-SingularityAdmin resolve-source-update-disposition --transaction $sourceTx --read-only --require-persisted-receipt --require-production-run-inactive --require-discord-listener-disabled --classify-safe-old-developer-ingress-open-or-held-closed-or-recovery-pending --print-disposition).Trim()
  if($LASTEXITCODE-ne 0-or$d-notin@('safe_old_developer_ingress_open','safe_old_developer_ingress_held_closed','fenced_recovery_pending')){throw "$Reason; authoritative disposition unavailable after abort_exit=$abortExit; do not infer ingress state; recover transaction $sourceTx"}
  throw "$Reason; authoritative disposition=$d"
}
function Stop-AfterFinalCas { param([string]$Reason,[string]$Proposal)
  Invoke-SingularityAdmin reconcile-source-update --transaction $sourceTx --proposal $Proposal --classify-old-or-exact-new-ref-index-tree --finish-only-journal-bound-materialization-attestation-and-ingress --keep-production-run-inactive --keep-discord-listener-disabled --persist-and-reread-recovery-receipt --print-disposition | Out-Null;$reconcileExit=$LASTEXITCODE
  $d=(Invoke-SingularityAdmin resolve-source-update-disposition --transaction $sourceTx --read-only --require-persisted-receipt --require-production-run-inactive --require-discord-listener-disabled --classify-safe-old-or-committed-exact-new-with-ingress-or-recovery-pending --print-disposition).Trim()
  if($LASTEXITCODE-ne 0-or$d-notin@('safe_old_developer_ingress_open','safe_old_developer_ingress_held_closed','committed_exact_new_developer_ingress_open','committed_exact_new_developer_ingress_held_closed','fenced_recovery_pending')){throw "$Reason; authoritative disposition unavailable after reconcile_exit=$reconcileExit; do not infer ingress state; recover transaction $sourceTx"}
  throw "$Reason; authoritative disposition=$d; re-enter through recovery"
}
function Register-FinalManifest { param([string]$Scope,[string[]]$Paths,[string[]]$Tests)
  function ConvertTo-SingularityManifestBase64Url { param([string]$CanonicalJson) $bytes=([System.Text.UTF8Encoding]::new($false,$true)).GetBytes($CanonicalJson);if($bytes.Length-gt 4096){throw 'Path-manifest decoded JSON exceeds 4096 bytes'};return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_') }
  $ts=New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal);foreach($t in $Tests){if(-not$ts.Add($t)-or$t-notin$Paths){throw "Invalid final test subset: $t"}}
  $records=@($Paths|ForEach-Object{[ordered]@{role=$(if($ts.Contains($_)){'required-test'}else{'required-change'});path=$_}})
  $id=(Invoke-SingularityAdmin begin-path-manifest --scope $Scope --expected-total-count $Paths.Count --expected-required-count $Paths.Count --expected-test-count $Tests.Count).Trim();if($LASTEXITCODE-ne 0-or-not$id){throw 'Unable to begin final manifest'}
  $seq=0;$chunk=@();foreach($r in $records){$trial=@($chunk+$r);$j=([ordered]@{sequence=$seq;records=$trial}|ConvertTo-Json -Compress -Depth 4);if(($trial.Count-gt 24-or[Text.Encoding]::UTF8.GetByteCount($j)-gt 4096)-and$chunk.Count){$j=([ordered]@{sequence=$seq;records=$chunk}|ConvertTo-Json -Compress -Depth 4);$payload=ConvertTo-SingularityManifestBase64Url $j;Invoke-SingularityAdmin append-path-manifest --scope $Scope --manifest $id --sequence $seq --canonical-records-json-base64url $payload --require-strict-unpadded-base64url --require-decoded-canonical-json-max-bytes 4096 --require-decode-recanonicalize-byte-equality --require-exact-envelope-max-bytes 8192;if($LASTEXITCODE-ne 0){throw 'Final manifest chunk failed'};$seq+=1;$chunk=@($r)}else{$chunk=$trial}}
  if($chunk.Count){$j=([ordered]@{sequence=$seq;records=$chunk}|ConvertTo-Json -Compress -Depth 4);$payload=ConvertTo-SingularityManifestBase64Url $j;Invoke-SingularityAdmin append-path-manifest --scope $Scope --manifest $id --sequence $seq --canonical-records-json-base64url $payload --require-strict-unpadded-base64url --require-decoded-canonical-json-max-bytes 4096 --require-decode-recanonicalize-byte-equality --require-exact-envelope-max-bytes 8192;if($LASTEXITCODE-ne 0){throw 'Final manifest tail failed'}}
  $receipt=(Invoke-SingularityAdmin seal-path-manifest --scope $Scope --manifest $id --canonical-order --sha256 --require-total-count $Paths.Count --require-required-count $Paths.Count --require-test-count $Tests.Count --persist-and-reread).Trim();if($LASTEXITCODE-ne 0-or-not$receipt){throw 'Final path-manifest seal failed'};return $receipt
}
try{$pathReceipt=Register-FinalManifest $sourceTx $finalPaths $finalTests}catch{Stop-BeforeFinalCas "Final manifest failure: $($_.Exception.Message)" ''}
$rootTouched=@($finalPaths|Where-Object{(($_ -like 'bootstrap/galaxy_launcher/*')-and$_-notin@('bootstrap/galaxy_launcher/developer_redirect.ps1','bootstrap/galaxy_launcher/dev_tools.lock.json'))-or$_-like'containers/galaxy/*.Dockerfile'});if($rootTouched.Count){Stop-BeforeFinalCas "Final generated headers touched frozen trust-root leaves; abort and restart the wave from Task 1 plus fresh TOFU: $($rootTouched -join ', ')" ''}
$normalizationReceipt=(Invoke-SingularityAdmin normalize-developer-source --transaction $sourceTx --repo $repoRoot --path-manifest-receipt $pathReceipt --chain-purpose-pre-normalization-batch-and-policy --require-exact-purpose-batch-membership --strict-utf8-parent-bom-preserving-crlf-to-lf-only --binary-exact --ensure-symbolic-loose-head-same-oid --create-if-absent-or-verify-existing-loose-head --native-full-tree-exact-index-bytes --no-ambient-git-config --no-hooks --no-filters --require-no-unexpected-change --persist-before-response --print-normalization-receipt).Trim();if($LASTEXITCODE-ne 0-or$normalizationReceipt-notmatch'^normalization_[0-9a-f]{64}$'){Stop-BeforeFinalCas 'Final normalization did not chain the immutable purpose batch' ''}
$proposalTx=(Invoke-SingularityAdmin prepare-source-commit --transaction $sourceTx --repo $repoRoot --path-manifest-receipt $pathReceipt --normalization-receipt $normalizationReceipt --require-pre-normalization-purpose-chain --native-no-follow-snapshot --parent-plus-allowlist-complete-tree --fixed-commit-metadata --message 'docs: record GALAXY transactional kernel evidence').Trim();if($LASTEXITCODE-ne 0-or-not$proposalTx){Stop-BeforeFinalCas 'Final source proposal failed' ''}
Invoke-SingularityAdmin review-source-proposal --transaction $proposalTx --sealed-independent-reviewer --require-two-independent-review-passes --persist-and-reread-review-receipt --no-canonical-write;if($LASTEXITCODE-ne 0){Stop-BeforeFinalCas 'Final source review failed' $proposalTx}
Invoke-SingularityAdmin verify-source-proposal --transaction $proposalTx --normalization-receipt $normalizationReceipt --require-pre-normalization-purpose-chain --require-exact-manifest --require-every-required-path-changed --require-generated-map-body-policy --require-evidence-schema --require-review-receipt --require-no-canonical-ref-write;if($LASTEXITCODE-ne 0){Stop-BeforeFinalCas 'Final proposal verification failed' $proposalTx}
Invoke-SingularityAdmin commit-source-proposal --transaction $proposalTx --source-update $sourceTx --normalization-receipt $normalizationReceipt --require-pre-normalization-purpose-chain --require-fresh-exact-digest-approval --cas-loose-ref --native-full-tree-materialize --install-verified-index --require-final-byte-clean --durable --keep-production-run-inactive;if($LASTEXITCODE-ne 0){Stop-AfterFinalCas 'Final evidence source commit reported failure' $proposalTx}
Invoke-SingularityAdmin attest-committed-source --transaction $sourceTx --proposal $proposalTx --require-loose-head --require-exact-index-worktree-bytes --require-source-receipt --keep-production-run-inactive;if($LASTEXITCODE-ne 0){Stop-AfterFinalCas 'Final evidence source attestation failed' $proposalTx}
Invoke-SingularityAdmin finish-source-update --transaction $sourceTx --release-developer-only-ingress --keep-production-run-inactive --keep-discord-listener-disabled --persist-and-reread-finish-receipt --print-disposition|Out-Null;$finishExit=$LASTEXITCODE;$finishDisposition=(Invoke-SingularityAdmin resolve-source-update-disposition --transaction $sourceTx --read-only --require-persisted-receipt --require-production-run-inactive --require-discord-listener-disabled --classify-safe-old-or-committed-exact-new-with-ingress-or-recovery-pending --print-disposition).Trim();if($LASTEXITCODE-ne 0-or-not$finishDisposition){throw "Final finish disposition unavailable after finish_exit=$finishExit; do not infer ingress state; recover transaction $sourceTx"};if($finishDisposition-ne'committed_exact_new_developer_ingress_open'){Stop-AfterFinalCas "Final finish resolved as $finishDisposition" $proposalTx}
$terminalOutcome=Complete-SingularityTopLevelSlot $repoRoot;if($terminalOutcome-ne"archived_achieved|$transitionPurpose"){throw 'Final evidence terminal transition was not observed, acknowledged, archived, and released as achieved'}
python tools/repo_map.py --check
if ($LASTEXITCODE -ne 0) { throw 'Post-commit repository map check failed' }
$remainingCached = @(git diff --cached --name-only)
if ($LASTEXITCODE -ne 0) { throw 'Unable to enumerate remaining staged paths' }
$remainingTracked = @(git diff --name-only)
if ($LASTEXITCODE -ne 0) { throw 'Unable to enumerate remaining tracked paths' }
$remainingUntracked = @(git ls-files --others --exclude-standard)
if ($LASTEXITCODE -ne 0) { throw 'Unable to enumerate remaining untracked paths' }
if ($remainingCached.Count -or $remainingTracked.Count -or $remainingUntracked.Count) {
  throw "Final tree not clean: cached=$($remainingCached -join ', ') tracked=$($remainingTracked -join ', ') untracked=$($remainingUntracked -join ', ')"
}
git status --short --branch
if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect final repository status' }
```

### Step 7: Activate the exact final controller through the installed LKG updater

Activation is last. The target checkout and `tools/build_galaxy_launcher.py` are inert input only; neither may execute, stage external bytes, obtain a capability, activate, or roll back. The already-installed, digest/ACL-verified last-known-good updater independently reads the exact final commit through no-follow object access, constructs the complete offline interpreter/stdlib/Python/native/DLL/dynamic-entrypoint/schema/prompt/asset runtime, mounts exact-final entrypoints only into the TOFU-sealed generic image set, and verifies every manifest/image byte. Before controller staging it compares every final trust leaf to the protected `TrustOnFirstInstallReceipt`; any later anchor/service/client/harness/image-input difference blocks activation and requires restarting the wave from Task 1 plus fresh TOFU. Its sealed credentialless harness **creates and re-reads** a new exact-final-SHA/runtime/image `RevisionVerificationReceipt`; its separately contained local reviewer creates and re-reads the bound `ReviewReceipt`. Mutable target tests, prior developer dossiers, target Dockerfiles/locks, and host build results are evidence only and cannot authorize activation. Empty-cwd recovery/fresh/resume/config/local-broker smokes run before any generation CAS.

The updater holds the external maintenance fence and separate surface-specific ingress fences across staging, operator approval, CAS, installed verification, post-CAS smokes, independent active-generation postconditions, and either explicit release or rollback. Fresh approval is for the exact staged runtime/manifest/image/final-source digest on the exclusive operator surface; the user's earlier generic unattended preapproval cannot satisfy it. The one-use `ControllerActivationAuthority` exists only inside the installed updater service process. A direct target-script, client argv/environment, copied receipt, or file cannot mint it. The CASed generation is not launchable while the fence is held. Any post-CAS fault causes the updater to advance the monotone generation again to the recorded LKG digest, prove LKG/inactive refusal, and only then decide whether CLI/run-admission ingress may reopen; it never decrements/restores a generation record. Discord gateway/listener ingress remains disabled throughout this wave. If rollback cannot be proven, every ingress stays fenced closed.

```powershell
$pinnedPowerShell = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
$singularityClient = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) '9to5\singularity\bin\singularity-admin-client.ps1'
if (-not (Test-Path -LiteralPath $pinnedPowerShell -PathType Leaf) -or -not (Test-Path -LiteralPath $singularityClient -PathType Leaf)) { throw 'Installed LKG service/client is unavailable; final controller remains inactive' }
function Invoke-SingularityAdmin { & $pinnedPowerShell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $singularityClient --request-only --require-server-validated-client-digest @args }
Invoke-SingularityAdmin verify-self --require-fresh-service-host --require-os-pinned-digest --require-protected-acl --require-current-generation --require-closed-launch-record
if ($LASTEXITCODE -ne 0) { throw 'Installed LKG updater failed root-of-trust verification' }
$repoRootRaw = (git rev-parse --show-toplevel).Trim()
if ($LASTEXITCODE -ne 0 -or -not $repoRootRaw) { throw 'Unable to resolve final repository root' }
function Resolve-StrictLocalAbsolutePath { param([string]$RawPath)
  if ([string]::IsNullOrWhiteSpace($RawPath) -or $RawPath -notmatch '^[A-Za-z]:[\\/]' -or $RawPath.StartsWith('\\?\') -or $RawPath.StartsWith('\\.\') -or $RawPath.StartsWith('//?/') -or $RawPath.StartsWith('//./')) { throw "Not a strict local drive-absolute path: $RawPath" }
  $full = [System.IO.Path]::GetFullPath($RawPath)
  if ($full -notmatch '^[A-Za-z]:\\') { throw "Path normalization lost drive-absolute form: $RawPath" }
  return $full
}
$repoRoot = Resolve-StrictLocalAbsolutePath $repoRootRaw
$finalActivationSha = (git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or -not $finalActivationSha) { throw 'Unable to resolve final activation SHA' }
function Complete-SingularityTopLevelSlot { param([string]$Repository)
  $currentPurpose=(Invoke-SingularityAdmin resolve-current-top-level-transition --repo $Repository --repository-global-all-generations --read-only --require-unique-live-slot --print-none-or-bound-purpose-receipt).Trim();if($LASTEXITCODE-ne 0-or-not$currentPurpose){throw 'Pure slot lookup failed; settlement is forbidden'};if($currentPurpose-eq'none'){return 'none'};if($currentPurpose-notmatch'^purpose_[0-9a-f]{64}$'){throw 'Invalid occupied purpose receipt'}
  $slotResult=(Invoke-SingularityAdmin observe-top-level-transition --repo $Repository --repository-global-all-generations --bound-purpose-receipt $currentPurpose --read-only --include-owner-lease-and-fencing-generation --require-latest-journal-live-state-and-ingress --closed-terminal-map singularity-top-level-terminal-v1 --print-owner-state-recovery-pending-or-terminal-observation).Trim();if($LASTEXITCODE-ne 0-or-not$slotResult){throw 'Occupied slot state is unknown'};if($slotResult-in@('active_owned_elsewhere','owner_liveness_unknown')){throw "Live or unproven slot owner blocks takeover: $currentPurpose"};if($slotResult-eq'recovery_pending'){throw "Slot recovery remains pending: $currentPurpose"}
  if($slotResult-match'^recoverable_dead_owner_([0-9a-f]{64})$'){$eligibilityReceipt=$Matches[1];$recoveryOwnerFence=(Invoke-SingularityAdmin settle-top-level-transition --repo $Repository --repository-global-all-generations --bound-purpose-receipt $currentPurpose --dead-owner-eligibility-receipt $eligibilityReceipt --revalidate-owner-dead-expired-and-quiesced-under-slot-lock --advance-owner-fencing-generation-before-mutation --existing-slot-only --journal-bound-settlement --allow-cancel-only-with-no-begin-proof --no-new-candidate --no-new-selection --no-unbound-state-adoption --persist-before-response --print-recovery-owner-fence-receipt).Trim();if($LASTEXITCODE-ne 0-or$recoveryOwnerFence-notmatch'^ownerfence_[0-9a-f]{64}$'){throw 'Dead-owner settlement failed safely'};$slotResult=(Invoke-SingularityAdmin observe-top-level-transition --repo $Repository --repository-global-all-generations --bound-purpose-receipt $currentPurpose --transition-owner-fence-receipt $recoveryOwnerFence --require-current-owner-fencing-generation --read-only --require-latest-journal-live-state-and-ingress --closed-terminal-map singularity-top-level-terminal-v1 --print-terminal-observation-or-recovery-pending).Trim()}
  if($slotResult-notmatch'^terminal_(cutover|source|controller)_(achieved|retryable_old|verified_rollback|safe_failed)_([0-9a-f]{64})$'){throw 'Occupied slot is not in an acknowledgeable closed terminal state'};$terminalKind=$Matches[2];Invoke-SingularityAdmin acknowledge-terminal-disposition --repo $Repository --repository-global-all-generations --bound-purpose-receipt $currentPurpose --terminal-observation-token $slotResult --closed-terminal-map singularity-top-level-terminal-v1 --revalidate-observation-still-current-before-ack --require-current-owner-fencing-generation-bound-to-observation --atomic-under-slot-lock --reject-cross-operation-purpose-epoch-or-owner-token-replay --idempotent --persist-before-response|Out-Null;$ackExit=$LASTEXITCODE
  $afterAck=(Invoke-SingularityAdmin resolve-transition-purpose-outcome --repo $Repository --purpose-receipt $currentPurpose --read-only --require-unique-exact-archive --require-observation-acknowledgement-chain --print-archived-outcome).Trim();$expected=@{achieved='archived_achieved';retryable_old='archived_retryable';verified_rollback='archived_rollback';safe_failed='archived_failed'};if($LASTEXITCODE-ne 0-or$afterAck-ne$expected[$terminalKind]){throw "Terminal archive disagreement after ack_exit=$ackExit"};$released=(Invoke-SingularityAdmin resolve-current-top-level-transition --repo $Repository --repository-global-all-generations --read-only --require-unique-live-slot --print-none-or-bound-purpose-receipt).Trim();if($LASTEXITCODE-ne 0-or$released-ne'none'){throw 'Acknowledged slot did not release'};return "$afterAck|$currentPurpose"
}
function Resolve-SingularityPurposeStartDisposition{param([string]$Repository,[string]$DesiredPurpose,[string]$PriorTerminal);if($DesiredPurpose-notmatch'^purpose_[0-9a-f]{64}$'){throw 'Invalid desired-purpose receipt'};if($PriorTerminal-ne'none'){$parts=@($PriorTerminal-split'\|',2);if($parts.Count-ne 2){throw 'Malformed prior terminal result'};$relationship=(Invoke-SingularityAdmin classify-purpose-successor --repo $Repository --completed-purpose-receipt $parts[1] --desired-purpose-receipt $DesiredPurpose --read-only --require-closed-reviewed-purpose-dag --require-explicit-wave-restart-edge --reject-multiple-matching-archives --print-same-allowed-predecessor-or-unrelated).Trim();if($LASTEXITCODE-ne 0-or$relationship-eq'unrelated_or_new_epoch'){throw 'Prior and desired purposes lack an allowed relationship'};if($relationship-eq'allowed_predecessor'-and$parts[0]-ne'archived_achieved'){throw 'Only an achieved predecessor may advance'}};$outcome=(Invoke-SingularityAdmin resolve-transition-purpose-outcome --repo $Repository --purpose-receipt $DesiredPurpose --read-only --require-unique-exact-archive --print-clear-never-started-or-archived-outcome).Trim();if($outcome-eq'archived_achieved'){return 'already_achieved'};if($outcome-in@('clear_never_started','archived_retryable')){return 'proceed'};throw "Desired purpose is not runnable: $outcome"}
$priorTerminal=Complete-SingularityTopLevelSlot $repoRoot
$purposeIssueReply=(Invoke-SingularityAdmin acquire-transition-purpose --registered-repo $repoRoot --reviewed-plan-node controller-activation-v1 --operation controller-update --contract controller-update-v1 --expected-source-sha $finalActivationSha --requested-fences cli-run-closed+discord-disabled+maintenance-index-ref --bind-active-reviewed-wave-epoch --require-wave-epoch-bound-to-current-tofu-receipt --require-satisfied-reviewed-predecessor-ledger --reject-unrelated-or-multiple-predecessor-archives --bind-exact-old-controller-state --bind-native-no-follow-final-source-and-trust-closure-fingerprint --create-or-return-exact --persist-before-response --print-purpose-receipt).Trim();$purposeIssueExit=$LASTEXITCODE
$transitionPurpose=(Invoke-SingularityAdmin resolve-transition-purpose --registered-repo $repoRoot --reviewed-plan-node controller-activation-v1 --operation controller-update --contract controller-update-v1 --expected-source-sha $finalActivationSha --requested-fences cli-run-closed+discord-disabled+maintenance-index-ref --bind-active-reviewed-wave-epoch --require-wave-epoch-bound-to-current-tofu-receipt --require-satisfied-reviewed-predecessor-ledger --reject-unrelated-or-multiple-predecessor-archives --bind-exact-old-controller-state --bind-native-no-follow-final-source-and-trust-closure-fingerprint --read-only --require-unique-exact --print-purpose-receipt-or-none).Trim();if($LASTEXITCODE-ne 0-or$transitionPurpose-notmatch'^purpose_[0-9a-f]{64}$'){throw "Controller purpose is not recoverable after issue_exit=$purposeIssueExit"};if($purposeIssueExit-eq 0-and$purposeIssueReply-and$purposeIssueReply-ne$transitionPurpose){throw 'Controller purpose issue reply disagrees with resolution'}
$slotOutcome = Resolve-SingularityPurposeStartDisposition $repoRoot $transitionPurpose $priorTerminal
if ($slotOutcome -eq 'already_achieved') { Write-Output 'Controller activation was already authoritatively completed and acknowledged'; return }
$activationIntentReply = (Invoke-SingularityAdmin acquire-begin-intent --registered-repo $repoRoot --operation controller-update --contract controller-update-v1 --transition-purpose-receipt $transitionPurpose --require-exact-purpose-binding --require-reviewed-purpose-dag --expected-source-sha $finalActivationSha --requested-fences cli-run-closed+discord-disabled+maintenance-index-ref --bind-exact-old-state --exclusive-top-level-mutation-per-registered-repo-all-generations --create-or-return-unique-slot --persist-before-response --print-request-id).Trim()
$activationIntentExit = $LASTEXITCODE
$activationRequestId = (Invoke-SingularityAdmin resolve-begin-intent --registered-repo $repoRoot --operation controller-update --contract controller-update-v1 --transition-purpose-receipt $transitionPurpose --require-exact-purpose-binding --expected-source-sha $finalActivationSha --requested-fences cli-run-closed+discord-disabled+maintenance-index-ref --bind-exact-old-state --exclusive-top-level-mutation-per-registered-repo-all-generations --read-only --require-unique-slot --require-persisted-intent --print-request-id-or-none).Trim()
if ($LASTEXITCODE -ne 0 -or -not $activationRequestId -or $activationRequestId -eq 'none') { throw "Controller-update intent is not authoritatively discoverable after intent_exit=$activationIntentExit; recover by repository and operation contract without starting another transition" }
if ($activationIntentExit -eq 0 -and $activationIntentReply -and $activationIntentReply -ne $activationRequestId) { throw 'Controller-update intent reply disagrees with authoritative intent discovery; do not start another transition' }
$ownerFenceReceipt = (Invoke-SingularityAdmin resolve-begin-intent-owner-fence --registered-repo $repoRoot --request-id $activationRequestId --transition-purpose-receipt $transitionPurpose --read-only --require-current-owner-lease-and-fencing-generation --print-owner-fence-receipt).Trim()
if ($LASTEXITCODE -ne 0 -or $ownerFenceReceipt -notmatch '^ownerfence_[0-9a-f]{64}$') { throw 'Controller owner-fence receipt is unavailable; do not begin' }
function Invoke-SingularityAdmin { $recoveryCommands=@('resolve-current-top-level-transition','observe-top-level-transition','settle-top-level-transition','acknowledge-terminal-disposition','resolve-transition-purpose-outcome');if($args.Count-and$args[0]-in$recoveryCommands){& $pinnedPowerShell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $singularityClient --request-only --require-server-validated-client-digest @args}else{& $pinnedPowerShell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $singularityClient --request-only --require-server-validated-client-digest --transition-purpose-receipt $transitionPurpose --transition-owner-fence-receipt $ownerFenceReceipt --require-current-owner-fencing-generation @args} }
$activationReplyTx = (Invoke-SingularityAdmin begin-controller-update --request-id $activationRequestId --idempotent-create --registered-repo $repoRoot --require-exact-purpose-binding --expected-source-sha $finalActivationSha --close-cli-run-ingress --keep-discord-listener-disabled --hold-maintenance-index-and-ref-fences --persist-begin-receipt-before-response).Trim()
$activationReplyExit = $LASTEXITCODE
$activationTx = (Invoke-SingularityAdmin resolve-controller-update-begin --request-id $activationRequestId --registered-repo $repoRoot --expected-source-sha $finalActivationSha --read-only --require-exact-request-binding --require-exact-purpose-binding --require-persisted-begin-receipt-if-started --require-latest-monotone-journal-if-started --require-exact-old-state-if-started --require-live-requested-fences-held-if-started --classify-started-exact-requested-fences-held-or-not-started --print-transaction-or-not-started).Trim()
if ($LASTEXITCODE -ne 0 -or -not $activationTx) { throw "Controller-update begin state is uncertain after begin_exit=$activationReplyExit; do not use or infer any ingress state; recover by repository and operation contract" }
if ($activationTx -eq 'not_started') { throw "Installed LKG updater did not start the controller update; durable request ID $activationRequestId" }
if ($activationReplyExit -eq 0 -and $activationReplyTx -and $activationReplyTx -ne $activationTx) { throw 'Controller-update begin reply disagrees with authoritative resolution; do not infer ingress state' }
function Stop-ControllerUpdateBeforeCas { param([string]$Reason)
  Invoke-SingularityAdmin abort-controller-update --transaction $activationTx --before-cas-only --abort-all-child-resources --reconcile-journaled-normalization --restore-prior-cli-run-ingress-if-proven-safe --keep-discord-listener-disabled --persist-and-reread-safe-failure-receipt --print-disposition | Out-Null
  $abortExit = $LASTEXITCODE
  $disposition = (Invoke-SingularityAdmin resolve-controller-update-disposition --transaction $activationTx --read-only --require-persisted-receipt --classify-prior-generation-cli-run-open-or-held-closed-or-recovery-pending --require-discord-listener-disabled --print-disposition).Trim()
  if ($LASTEXITCODE -ne 0 -or $disposition -notin @('prior_generation_cli_run_open_discord_disabled', 'prior_generation_ingress_held_closed', 'fenced_recovery_pending')) { throw "$Reason; authoritative controller-update disposition is unavailable after abort_exit=$abortExit; do not infer ingress state; recover transaction $activationTx" }
  throw "$Reason; authoritative disposition=$disposition"
}
Invoke-SingularityAdmin normalize-developer-checkout --transaction $activationTx --repo $repoRoot --source-sha $finalActivationSha --full-tree-exact-index-bytes --strict-utf8-parent-bom-preserving-crlf-to-lf-only --binary-exact --ensure-symbolic-loose-head-same-oid --disable-auto-ref-packing --require-no-substantive-change --bind-normalization-receipt
if ($LASTEXITCODE -ne 0) {
  Stop-ControllerUpdateBeforeCas 'Final exact-byte/loose-ref normalization failed under the activation fence'
}
Invoke-SingularityAdmin attest-target --transaction $activationTx --repo $repoRoot --source-sha $finalActivationSha --no-follow --require-clean --require-exact-index-worktree-bytes --require-symbolic-loose-head --bind-normalization-receipt
if ($LASTEXITCODE -ne 0) {
  Stop-ControllerUpdateBeforeCas 'Final source attestation failed under the activation fence'
}
Invoke-SingularityAdmin verify-final-trust-closure --transaction $activationTx --source-sha $finalActivationSha --require-protected-tofu-source-leaf-blob-equality --require-protected-tofu-artifact-root-equality --forbid-post-tofu-source-leaf-change --persist-and-reread-equality-receipt --keep-all-fences-held
if ($LASTEXITCODE -ne 0) { Stop-ControllerUpdateBeforeCas 'Final source trust leaves differ from the protected TOFU root; abort and restart the wave from reviewed Task 1 plus fresh TOFU' }
Invoke-SingularityAdmin prepare-controller-update --transaction $activationTx --require-final-trust-closure-equality-receipt --treat-source-as-inert-data --offline-runtime-closure --use-only-tofu-sealed-generic-images --keep-all-fences-held
if ($LASTEXITCODE -ne 0) {
  Stop-ControllerUpdateBeforeCas 'Installed LKG updater could not prepare the controller; old/inactive generation remains authoritative'
}
Invoke-SingularityAdmin verify-staged-controller --transaction $activationTx --run-sealed-closed-acceptance-manifest --pinned-credentialless-verifier --persist-and-reread-verification-receipt --run-separately-contained-local-review --persist-and-reread-review-receipt --bind-receipts-to-source-runtime-and-image-digests --require-empty-cwd-import --smoke-recovery --smoke-fresh --smoke-resume --smoke-config --smoke-local-broker --keep-all-fences-held
if ($LASTEXITCODE -ne 0) {
  Stop-ControllerUpdateBeforeCas 'Staged controller verification failed; no generation CAS occurred'
}
Invoke-SingularityAdmin commit-controller-update --transaction $activationTx --require-final-trust-closure-equality-receipt --require-fresh-exact-digest-approval --mint-process-local-authority --post-cas-verify --post-cas-smoke-recovery --post-cas-smoke-fresh --post-cas-smoke-resume --post-cas-smoke-config --post-cas-smoke-local-broker --independent-active-verification-before-return --monotone-lkg-rollback-on-any-failure --hold-all-fences-after-success --keep-discord-listener-disabled
if ($LASTEXITCODE -ne 0) {
  Invoke-SingularityAdmin reconcile-controller-update --transaction $activationTx --classify-exact-final-active-fenced-or-verified-lkg-rollback-fenced --finish-only-journal-bound-update --require-no-failed-generation-launch --keep-discord-listener-disabled --persist-and-reread-recovery-receipt --print-disposition | Out-Null
  $reconcileExit = $LASTEXITCODE
  $commitDisposition = (Invoke-SingularityAdmin resolve-controller-update-disposition --transaction $activationTx --read-only --require-persisted-receipt --classify-exact-final-active-or-verified-lkg-rollback-or-recovery-pending --require-ingress-held-closed --require-discord-listener-disabled --print-disposition).Trim()
  if ($LASTEXITCODE -ne 0 -or $commitDisposition -notin @('exact_final_active_ingress_held_closed', 'verified_lkg_rollback_ingress_held_closed', 'fenced_recovery_pending')) { throw "Activation disposition is unavailable after reconcile_exit=$reconcileExit; do not infer ingress state; recover transaction $activationTx" }
  if ($commitDisposition -eq 'verified_lkg_rollback_ingress_held_closed') { throw 'Final controller was not activated; a persisted receipt proves verified LKG rollback with ingress held closed' }
  if ($commitDisposition -eq 'fenced_recovery_pending') { throw 'Final controller update remains recovery-pending; a persisted receipt proves ingress held closed' }
}
Invoke-SingularityAdmin verify-active-controller --transaction $activationTx --source-sha $finalActivationSha --require-monotone-generation --require-no-legacy-controller --require-maintenance-fence-held --require-cli-run-ingress-closed --require-discord-listener-disabled --reread-activation-receipt
if ($LASTEXITCODE -ne 0) {
  Invoke-SingularityAdmin rollback-controller-update --transaction $activationTx --require-or-reacquire-all-fences --advance-monotone-lkg-generation --require-no-failed-generation-launch --keep-discord-listener-disabled | Out-Null
  Invoke-SingularityAdmin reconcile-controller-update --transaction $activationTx --classify-exact-final-active-fenced-or-verified-lkg-rollback-fenced --finish-only-journal-bound-rollback --require-no-failed-generation-launch --keep-discord-listener-disabled --persist-and-reread-recovery-receipt --print-disposition | Out-Null
  $reconcileExit = $LASTEXITCODE
  $rollbackDisposition = (Invoke-SingularityAdmin resolve-controller-update-disposition --transaction $activationTx --read-only --require-persisted-receipt --classify-exact-final-active-or-verified-lkg-rollback-or-recovery-pending --require-ingress-held-closed --require-discord-listener-disabled --print-disposition).Trim()
  if ($LASTEXITCODE -ne 0 -or $rollbackDisposition -notin @('exact_final_active_ingress_held_closed', 'verified_lkg_rollback_ingress_held_closed', 'fenced_recovery_pending')) { throw "Active verification failed and authoritative rollback disposition is unavailable after reconcile_exit=$reconcileExit; do not infer ingress state; recover transaction $activationTx" }
  if ($rollbackDisposition -eq 'exact_final_active_ingress_held_closed') { throw 'Active verification failed; rollback did not complete and the exact final generation remains active with ingress authoritatively held closed' }
  if ($rollbackDisposition -eq 'fenced_recovery_pending') { throw 'Active verification failed; a persisted receipt proves ingress held closed while rollback remains recovery-pending' }
  throw 'Active generation postcondition failed; a persisted receipt proves monotone LKG rollback with ingress held closed'
}
Invoke-SingularityAdmin release-ingress --transaction $activationTx --surface cli-run-admission --require-active-receipt --persist-and-reread-final-activation-receipt-before-release --atomic-fence-transition --failure-keeps-fence --keep-discord-listener-disabled
Invoke-SingularityAdmin reconcile-ingress-release --transaction $activationTx --surface cli-run-admission --classify-release-complete-or-held-closed --require-active-receipt --require-discord-listener-disabled --persist-and-reread-release-receipt --print-disposition | Out-Null
$reconcileExit = $LASTEXITCODE
$releaseDisposition = (Invoke-SingularityAdmin resolve-ingress-release-disposition --transaction $activationTx --surface cli-run-admission --read-only --require-persisted-receipt --classify-release-complete-or-held-closed-or-recovery-pending --require-active-receipt --require-discord-listener-disabled --print-disposition).Trim()
if ($LASTEXITCODE -ne 0 -or $releaseDisposition -notin @('cli_run_release_complete_discord_disabled', 'release_held_closed', 'fenced_recovery_pending')) { throw "CLI/run release disposition is unavailable after reconcile_exit=$reconcileExit; do not infer open or closed; recover transaction $activationTx" }
if ($releaseDisposition -eq 'release_held_closed') { throw 'Active controller is verified but CLI/run ingress remains durably fenced closed' }
if ($releaseDisposition -eq 'fenced_recovery_pending') { throw 'CLI/run release remains recovery-pending; do not infer open or closed from the client response' }
$terminalOutcome = Complete-SingularityTopLevelSlot $repoRoot
if ($terminalOutcome -ne "archived_achieved|$transitionPurpose") { throw 'Controller terminal transition was not observed, acknowledged, archived, and released as achieved' }
git status --short --branch
if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect repository after external activation' }
```

---

## 8. Explicitly deferred R3 waves

These are important but do not belong in the same high-risk kernel change:

1. Capability registry replacing `FULL_STACK` with evidence-backed activation states.
2. Provider-independent OS sandboxing for the explicitly trusted-Local tier, so it can later qualify for hostile workloads; this wave already requires OS/container enforcement for every hostile/unknown launch.
3. Exactly-once command-intent handling with stable control-store IDs plus idempotent sidecar/field-mask-CAS TaskState convergence; never claim cross-store exactly-once mutation.
4. Cross-provider independent review packets with contamination measurement.
5. Pre-execution clarification as an acceptance-contract prerequisite.
6. Risk-tiered, power-calculated outcome promotion rather than fixed sample counts.
7. Dashboard visualization of the live GALAXY graph and current execution node.
8. Transactional runner-up graft as a new independently verified candidate.
9. Structural target topology manifest and static node/edge/count/authority
   linter; runtime qualification remains solely in the external OA-owned
   overlay.
10. Flare charter registry, admission, ephemeral cells, contradiction exchange, convergence, advisory bundle, and post-terminal outcome resolution.
11. Nebula query framing, integrity and phase gates, bounded epochs, selective broadcast, spill/recall, synthesis receipts, and Supernova counterfactual trials.
12. Per-node and per-edge Graph Admission Trials with expiring workload-scoped warrants.
13. Disabled Voyager federation envelope validator, status-digest gate, shadow record, terminal feedback, kill switch, and forbidden-payload canaries.

They are deferred because the staged attempt kernel is their prerequisite, not because they are lower ambition.

---

## 9. Completion definition

This wave is complete only when all statements below are machine-supported:

The statements below certify the transactional-kernel wave only. Full GALAXY
Revision 3 completion additionally requires the qualified topology, graph
admission, Flare, Nebula, Voyager-boundary, and Orrery gates in the
capability-topology design.

- no accepted landing-required attempt can bypass staged preparation;
- every current mutating Local/Docker/Society/parallel/solution-space attempt executes inside a fail-closed standalone `CloneLease`; the transactional kernel stages objects without linked worktrees;
- every Claude/Codex repository launch has first-statement typed transaction/analysis authority; invalid authority causes no side effect, generated context never enters a candidate snapshot/manifest, and isolated launches receive only backend-visible allowlisted clone/runtime-projection paths;
- every hostile/unknown mutation or analysis launch has an OS/container enforcement receipt; credential-bearing model driving and credentialless repository-code execution are separate resources, while trusted Local is explicitly labeled and ineligible for hostile work;
- every retry has a fresh transaction/checkout; a rejected filesystem tree is never the next attempt's base;
- mutating Remote execution fails before launch until transactional collection exists;
- verification runs against an exact proposed SHA in a fresh no-link clone inside a universal credentialless/network-disabled hardened container; no origin's acceptance code executes on the host, and provider-mediated review uses the separately guarded model driver;
- failed verification leaves canonical HEAD and files unchanged;
- promotion requires an immutable object-staged revision, exact universal-verifier authority-bound verification, durable intent, the custom merge lock, a Git-standard canonical index writer fence, and atomic expected-old-OID Git ref compare-and-swap;
- canonical ref movement uses one attested Git-compatible loose-ref lockfile CAS/rename with crash classification on both sides; canonical materialization replays the immutable operation manifest through the native handle-relative writer, then installs a copied/re-read deterministic index from a journal-owned same-directory sibling with exact postconditions;
- terminal `done` requires clean canonical materialization plus a durable promoted journal record and successful finalization receipt;
- interrupted promotion is reconciled from expected/proposed/current Git truth rather than guessed from task status;
- rejected/crashed work has a durable native snapshot, parser receipt, canonical blob/tree manifest, and immutable addressable checkpoint ref, or an explicit recovery failure;
- journals/locks/manifests and all candidate/verification checkout roots are outside the promoted tree and protected from candidate path collisions;
- Society, parallel, and solution-space paths use the same stage/verify/persist/promotion authority and only the owner writes terminal task state;
- selected Local and Docker semantics run inside self-contained private clones with native no-follow snapshot, contained parse, and memory-safe object staging; legacy Worktree preference maps truthfully to clone landing, while unsupported mutating Remote is explicitly refused rather than silently replaced;
- TaskState promotion attachment is copy-on-write on disk and identity-preserving in live memory: pending receipt state is saved before journal acknowledgement, `done` is saved only afterward, persistence failure is recovery-only, and durable `promoted` truth dominates every later attempt outcome even if canonical advances;
- the evidence distinguishes the cooperative-writer guarantee from deliberately lock-bypassing direct plumbing/host filesystem writes and does not overclaim hostile Local containment;
- no post-verification mutation changes the sealed canonical revision;
- generated repository maps are current;
- focused, affected, compile, and fast-lane verification results are recorded;
- incremental external operating cost remains essentially zero.
