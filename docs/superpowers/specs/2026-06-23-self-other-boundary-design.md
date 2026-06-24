# Self/Other Boundary — Self-Identity Core (Spec 1 of 3) — Design

> **Status:** approved design (brainstorming output). Next: implementation plan
> (`docs/superpowers/plans/2026-06-23-self-other-boundary.md`).
> Branch: `feat/self-other-boundary`.
> This is **Spec 1 (foundation, comprehensive)** of a three-spec program. It builds
> the SELF manifest + two new primitives (provenance, epoch) and wires **every
> catastrophic and high-severity instance** through them. Spec 2 = remaining
> medium/low consumers + coverage gaps. Spec 3 = enforcement-layer hardening.

## Objective

Give 9to5 a working **immune system**: a positive, canonical notion of *self* so
that for every byte it ingests it can answer *"whose is this, and in what role?"* —
and never confuse a thing it **edits** with a thing it **obeys**, a thing it
**produced** with a thing it **believes**, or the code it **wrote to disk** with the
code it is **running**.

9to5 is a self-improving orchestrator: it edits its own files. Today it has an
**innate deny response** (a fixed antigen list: `.env`, `.git`, `venv`,
`state/tasks`, 4 core files) but **no notion of self** — nothing answers "is this
part of me, and in what capacity?" Every problem below flows from that one absence.

**Editing is never the danger; role-confusion and incoherent execution are.** Per
project philosophy ("surgical precision, not permission") 9to5 may edit *any* code,
including `orchestrator.py` itself. The foundation does not restrict editing. It
makes edits **role-aware** (you may edit `CLAUDE.md` but must never *obey* it) and
**execution-coherent** (you may edit `orchestrator.py` but the running process must
not re-run its own edits mid-life).

## The invariant (one sentence)

> **Provenance — not a file's location or format — decides its role.** Every byte
> 9to5 ingests carries an origin, and origin decides whether it is *obeyed*
> (instruction), *believed* (trusted fact), or *executed* (running identity), versus
> merely *edited* / *produced* / *stored*.

The bug class — **provenance collapse** — is any path where 9to5 ingests something it
(or a task it ran) produced or edits, and treats it as authoritative external
instruction / truth / identity.

## The problem, concretely (what exploration found)

A two-workflow sweep (13 subagents) enumerated **27 instances** of provenance
collapse, two **catastrophic**, plus 6 coverage gaps. They cluster on three types and
two axes.

**Type A — obey what you edit** (object-as-subject):
- **#2 (CATASTROPHIC)** — `prompt_variants` champion `body` *replaces* the orchestrator
  constitution at runtime (`orchestrator.py:734`, `learning/prompts.py:24-37`,
  `memory/experience.py:620-657`). A row in `state/experience.db` — which the guard
  does **not** protect (it blocks only `state/tasks`) — becomes the brain's governing
  system prompt. One SQL write reprograms the controller.
- **#3** — `state/sie_overrides.json` mutates `ALL_CAPS` config at import with **no
  value bounds** (`config.py:276-288`); can set `ADVERSARY_HEARTBEAT_EVERY=9999` +
  `PROMPT_PROMOTE_MIN_USES=1`, disabling review and enabling #2.
- **#4/#5/#6** — `knowledge/claude_code.md`, `knowledge/recommendations.md`,
  `.claude/agents/*`, `skills/*` — task-editable, injected into **every** Ollama
  prompt as authoritative truth (`knowledge.py:343-359,662-670`; `orchestrator.py:114-150`).

**Type B — believe what you produced** (output-as-truth) — *one laundering pipeline*:
> stub/repaired "pass" (`adversary.py:118-128`, `orchestrator.py:1299-1307`) →
> persisted as a **bare** `'approved'` string, **stub flag dropped** at
> `state/task.py:328-335` → `gold_examples` SQL cannot distinguish "never reviewed"
> from "genuinely approved" (`memory/experience.py:961-970`) → fans out to
> `solution_cache` (#11b), `reward` (#17), **LoRA fine-tuning that rewrites the
> brain's weights** (#9, `learning/distill.py`+`finetune.py`), and `reflection.trust`
> (#10, `learning/reflection.py:52-66`).

The entire chain is defeated by **one discarded bit** — the adversary's `stub=True`,
dropped before any consumer sees it.

**Type C — running self ≠ on-disk self** (split-brain / autoimmunity):
- **#1 (CATASTROPHIC, keystone, A+C)** — the PreToolUse guard re-reads
  `SELFMOD_ALLOW_CORE` + `CORE_PROTECTED_FILES` **live from disk every call** (fresh
  subprocess, `agents/hooks.py:286-292`). It obeys the *edited* config, not the
  launching run's. This is what literally turns "9to5 edited a file" into "9to5 now
  obeys the file."
- **#12–15, #24** — bytecode never hot-reloads; the post-run gate tests **new** code
  to bless a run that executed **old** code (`selfmod.py`, `orchestrator.py:1886-1905`);
  RAM `TaskState` clobbers disk (`state/task.py:114-129`); brain identity resolved
  live per call.

**The CLAUDE.md seed** (the user's original example) is one square in Type A:
`C:\9to5\CLAUDE.md` is read by the Claude CLI's memory-ancestry walk as executor
*instructions* (it opens *"You may have been spawned by 9TO5 as the Executor… Read
this"*), even though 9to5 only ever *edits* it. Overwrite is already prevented (the
`.sc-ctx` scratch cwd, `orchestrator.py:1762-1770`); **adoption is not.**

## The two axes (and why one fix is not enough)

- **Infection axis (Types A + B):** foreign / self-produced content ingested as
  trusted self. Defect: *content does not carry its origin.* ~17 instances.
- **Autoimmunity axis (Type C):** the running process diverges from the on-disk self.
  Defect: *no pin on what "the running self" is.* ~6 instances. Provenance tags do
  **not** fix this — the config in #1 is *correctly* self-authored; the defect is
  *when* it becomes authoritative.

The axes are coupled: the C-axis **enables** the A-axis. Because the guard (#1),
config (#3), and prompts (#2) are re-read live from disk rather than pinned to the
launching process, an edit becomes authoritative *mid-run* — that is precisely what
turns "9to5 edited X" into "9to5 obeys X." So the foundation needs **two** primitives
over **one** spine.

## Architecture — one spine, two primitives

```
                    ┌─────────────────────────────────┐
                    │   SELF MANIFEST  (identity.py)   │
                    │  canonical role per path;        │
                    │  "whose is this, in what role?"  │
                    └───────────────┬─────────────────┘
                 derives ↓                      ↓ derives
   ┌──────────────────────────────┐  ┌────────────────────────────────┐
   │ PRIMITIVE 1: PROVENANCE       │  │ PRIMITIVE 2: EPOCH PIN          │
   │ origin tag carried on every   │  │ freeze config/prompts/universe/ │
   │ ingested byte; checked at the │  │ guard-policy + bytecode FINGER- │
   │ single ingestion chokepoint   │  │ PRINT at process start; no mid- │
   │                               │  │ run live re-reads               │
   └──────────────┬───────────────┘  └───────────────┬────────────────┘
        kills INFECTION axis (A+B)         kills AUTOIMMUNITY axis (C)
```

### § 1. The SELF manifest (the spine) — `identity.py`

A new module `identity.py`, single source of truth, itself tagged `self.code`
(editable, fingerprinted). **The manifest is a classifier, not a guard** — roles
drive *handling*, not *prohibition*. Only `hard_boundary` forbids, and it stays
narrow.

Every path is **canonicalized at load** — `os.path.realpath` + `Path.resolve()` to
collapse symlinks/junctions/`..`/UNC/8.3 short-names — and classified by
**containment** under a resolved role root, never by string suffix. This kills the
symlink/`..`/relative-path evasion bugs (R5/#1) structurally rather than by
patching the matcher.

| Role | Semantics | Examples |
|------|-----------|----------|
| `self.code` | 9to5's own modules. **Freely editable.** Tagged for coherence fingerprinting; edits inert until restart. | `orchestrator.py`, `main.py`, `config.py`, `agents/*`, `learning/*`, `state/task.py`, `control.py`, `memory/*`, `identity.py` |
| `self.instructions` | Directives 9to5 **obeys**. Must never be sourced from a task-writable surface. | own constitution / role system prompts, `~/.claude/CLAUDE.md` |
| `self.object_meta` | Metadata 9to5 **edits but must never obey.** | `C:\9to5\CLAUDE.md`, `docs/*`, `README.md` |
| `self.learned` | Task-**produced** memory. Carries provenance; never trusted without attestation. | `state/experience.db`, `knowledge/*`, reflections, `solution_cache`, `sie_overrides.json` |
| `self.live_state` | Hot cross-process channel; provenance required on inbound commands. | `state/control/*` |
| `self.frozen_state` | Orchestrator owns it in RAM; disk is a lossy checkpoint. | `state/tasks/*` |
| `hard_boundary` | **The only prohibition.** Narrow. | `.env`, `.git`, `venv`, live task-state file mid-write |
| `other.content` | The work target — fair game within universe scope. | the `work_dir` codebase |

The decisive distinction: `self.instructions` (obey) vs `self.object_meta`
(edit-never-obey) are **different roles for structurally identical files**. That is
the whole point — and the structural fix for the CLAUDE.md adoption bug.

**API (illustrative):**
```python
roleOf(path: str) -> Role            # canonicalize, classify by containment
isObeyable(path) -> bool             # role in {self.instructions}
isEditable(path) -> bool             # role not in {hard_boundary}
isCodeSelf(path) -> bool             # role == self.code  (drives fingerprinting)
```

### § 2. Primitive 1 — Provenance (infection axis)

A `Provenance` value carried on **every** ingested byte:
```python
Provenance = {
  origin: "human" | "scrape" | "brain" | "executor" | "derived",
  attested_by: str | None,      # who independently vouched (e.g. real adversary)
  integrity: str | None,        # content hash / sidecar digest
  authoring_task_id: str | None # the task that produced it (for self-edit detection)
}
```

**Carrier per surface-type** (provenance must travel *with* the data, never be
recomputed at the consumer):
- **SQLite** (`experience.db`): a `provenance` column on every learnable table
  (`reflections`, `prompt_variants`, `solution_cache`, the gold/ledger rows). **The
  adversary's dropped `stub` flag becomes a carried provenance field** — this single
  change gives the entire B-laundering chain discrimination for free.
- **Files** (`knowledge/*`, docs): provenance front-matter (or a sidecar
  `.<name>.prov.json` digest); the read path verifies the digest before the content
  is allowed onto an obey/believe path.
- **In-memory** (verdicts, reflections, specs): a field on the dataclass, threaded
  end-to-end so it cannot be stripped at persistence.

**The ingestion chokepoint** — one function every consumer routes through:
```python
assertIngestible(surface, intended_role, provenance) -> Content | Quarantine
```
- Obey-paths (`self.instructions`, config knobs, the constitution) require
  `origin == human` *or* a trusted attestation; `origin in {executor, derived}` is
  refused.
- Believe-paths (gold examples, reward, distillation, reflection trust) require a
  **real** independent attestation; stub/abstain provenance maps to **neutral**, never
  positive.

**Comprehensive wiring (this spec, not deferred):** every **catastrophic + high**
infection instance routes through the chokepoint — #2 (prompt_variants body must be
human/gate-attested), #3 (sie_overrides values bounds-checked + provenance-gated),
#4/#5/#6 (knowledge docs verify provenance before injection), and the full B chain
#7→#8→#9/#10/#11/#11b (the stub flag now travels; `gold_examples` filters on real
attestation).

### § 3. Primitive 2 — Epoch pin (autoimmunity axis)

At process start, `Epoch.snapshot()` freezes an **immutable** object and writes a copy
into task meta (so out-of-process readers — chiefly the PreToolUse hook — read *it*,
not a fresh import):
- governing config (boundary set, `SELFMOD_*` flags, tunable knobs)
- active brain identity (champion id, adapter tag)
- the universe snapshot
- **bytecode fingerprint** — git SHA + per-module content hash of every `self.code`
  module from the manifest

**Rules:**
- **The hook reads the epoch from task meta, never a live `config` import** → closes
  the #1 keystone (the guard can no longer obey an edited config mid-run).
- The loop reads governing values from the epoch; it never re-imports mid-run.
- **Divergence detector** (policy ①, *observe-only / inert-until-restart*): if the
  on-disk `self.code` fingerprint ≠ the epoch fingerprint, set `code_diverged = True`,
  tag this run's outputs *"produced by pre-edit bytecode,"* and **forbid the post-run
  gate from blessing diverged-but-never-executed modules as verified** (closes
  #12/#14).
- **Safety invariant (the user's rule — "code must not re-run itself"):** no mid-run
  re-execution of edited code. No `importlib.reload`; `resilience.py`'s in-process
  restart keeps the epoch's bytecode and refuses to adopt edits (closes #13).
  Adoption of self-edits happens **only on a clean new process** — *"improve now,
  adopt next run."* Editing is unrestricted; executing is pinned.
- **State coherence:** out-of-process readers treat in-RAM `TaskState` as
  authoritative and the JSON as a lossy checkpoint; add an epoch/version stamp so a
  racing disk write is detectable rather than silently trusted (closes #15).

### § 4. Instance → fix mapping (Spec 1 coverage)

| # | Sev | Type | Closed by |
|---|-----|------|-----------|
| 1 | CATA | A+C | Epoch pin: hook reads epoch from task meta, not live config |
| 2 | CATA | A | Provenance: champion `body` requires human/gate attestation at `assertIngestible` |
| 3 | HIGH | A | Provenance + bounds: `sie_overrides` values validated, provenance-gated |
| 4,5,6 | HIGH | A | Provenance: knowledge/agents/skills verify provenance before prompt injection |
| 7 | HIGH | B | Provenance: stub flag becomes carried field; persists to consumers |
| 8 | HIGH | B | `gold_examples` filters on real attestation (stub/NULL ≠ gold) |
| 9 | HIGH | B | Distillation/LoRA dataset gated on real-attestation provenance |
| 10 | HIGH | B | `reflection.trust` rejects degraded (stub/repaired) anchors |
| 11,11b | HIGH | B | Reflections/solution_cache carry provenance; advisory-only on weak attestation |
| 12,14 | HIGH | C | Epoch fingerprint: post-run gate cannot bless unexecuted edited modules |
| 13 | HIGH | C | Epoch: in-process restart keeps pinned bytecode; no reload |
| 15 | HIGH | C | Epoch/version stamp on `TaskState`; disk is a checkpoint |

*Closed as a free consequence of the epoch snapshot (though medium-severity, so not
counted toward Spec 1's scope): #24 (brain identity — `champion_id`/adapter tag —
pinned once per run instead of resolved live per call). The epoch already carries it;
no extra work.*

Medium/low (#16–27, except #24 above) and the 6 coverage gaps are **Spec 2**;
enforcement mechanics (guard canonicalization beyond the manifest, bash write-hole,
headless-hook verification, true worktree isolation) are **Spec 3**.

### § 5. Data flow

```
process start
  └─ Epoch.snapshot()  ── freeze config/prompts/universe + self.code fingerprint
        └─ write epoch into task meta
              ├─ PreToolUse hook reads epoch (NOT live config)         [#1]
              └─ loop reads governing values from epoch                [#3]
per ingestion (knowledge, prompts, gold, reward, distill, overrides)
  └─ assertIngestible(surface, role, provenance) → Content | Quarantine [#2,#4-11]
per subtask boundary
  └─ divergence check: on-disk self.code fingerprint vs epoch          [#12-14]
post-run
  └─ gate honors epoch: refuses to verify diverged-but-unexecuted code [#12,#14]
```

### § 6. Error handling

- **Provenance fails CLOSED.** Missing/invalid provenance on an obey- or believe-path
  ⇒ quarantine (treated as untrusted `other.content`), never silently trusted. A
  brain offline / adversary stub yields *neutral*, never *positive*.
- **Epoch fails OBSERVABLE.** A fingerprint divergence ⇒ surface + tag + gate-refusal,
  never a crash. The system keeps running on its pinned bytecode and reports the
  split-brain honestly.
- **Manifest fails SAFE.** An unclassifiable / unresolvable path ⇒ treated as
  `hard_boundary`-adjacent (deny obey/believe; allow edit only if clearly under
  `work_dir`), and logged.

### § 7. Testing (the foundation must assert these — today *nothing* does)

- **Manifest resolution defeats evasion:** symlink → target's role; `..`/UNC/8.3 →
  correct containment classification; `C:/9to5/.env` and `.env` (from cwd) classify
  identically.
- **Provenance survives persistence:** an adversary stub verdict reaches
  `gold_examples` as non-gold; a brain-origin knowledge edit is refused on the obey
  path.
- **Epoch immutability:** a mid-run edit to `config.py` / `sie_overrides.json` does
  **not** change the live epoch; the hook enforces the pinned boundary set.
- **Divergence detection:** editing any `self.code` module mid-run flips
  `code_diverged` and the post-run gate refuses to bless it.
- **Coherence invariant:** in-process restart re-enters pinned bytecode; no
  `importlib.reload` anywhere in the loop.

## Non-goals (YAGNI / scope discipline)

- **No restriction on editing code.** 9to5 may edit any file outside `hard_boundary`,
  including its own loop. The foundation governs *role* and *execution coherence*, not
  the right to edit.
- **No deliberate safe-respawn (policy ②) in this spec.** Edits are inert until the
  next clean process. The epoch fingerprint leaves a clean seam for ② later, but
  re-entrant resume is out of scope.
- **No medium/low consumer rewrites, no coverage-gap surfaces** (Discord/ControlBus
  author provenance, Obsidian handoffs, git porcelain, eval-harness, adapter blob,
  `requirements.txt`) — those are Spec 2.
- **No enforcement-layer rewrite** (bash write-hole, headless-hook relocation,
  worktree isolation) — Spec 3.
- **No new external dependencies.** Stdlib hashing + the existing SQLite ledger +
  task-meta JSON only. Stays zero-marginal-cost and file-backed, per project
  philosophy.

## Open verification items (resolve in the plan's first phase)

1. **Does headless `claude --print --dangerously-skip-permissions` execute the
   `--settings` PreToolUse hook at all?** The codebase re-implements `block_destructive`
   in-process *because it believes headless skips hooks* (`executor.py:245-247`). The
   epoch-pinned hook (#1 fix) is only effective if the hook runs. If it does **not**,
   the epoch read must move into the executor plumbing — a Spec-3 relocation that the
   plan must branch on. **This is a 30-minute spike; run it before building the hook
   path.** (Cross-ref: Spec 3 owns the relocation; Spec 1 owns the epoch object the
   relocated check would read either way.)
2. **`experience.db` schema migration** for the `provenance` column — confirm the
   ledger has a migration path / version table, or add one.

## Summary

The foundation answers 9to5's missing question — *"whose is this, and in what
role?"* — with one **manifest** (positive self, role-classified, canonicalized) and
two primitives derived from it: **provenance** (kills the infection axis — foreign or
self-produced content ingested as trusted self) and the **epoch pin** (kills the
autoimmunity axis — the running self diverging from the on-disk self). Comprehensive
on severity: every catastrophic and high instance closes here. Editing stays
unrestricted; only *role* and *execution coherence* are governed.

## Spike result (Task 0.1)

**Hook fired: NO.**

Evidence: `python scripts/spike_headless_hook.py` printed `HOOK_FIRED: False`
— the sentinel file was never written, confirming that `claude --print
--dangerously-skip-permissions --settings <path>` does **not** execute
`PreToolUse` hooks even when a matching `settings.json` is supplied via
`--settings`. Claude version resolved via `shutil.which("claude")` →
`C:\Users\fireh\AppData\Roaming\npm\claude.cmd`.

Task 5.1's epoch read must ALSO live in `agents/executor.py`'s in-process
guard (where `block_destructive` already lives); the hook change still lands
but is not sole enforcement.

## Implementation review addendum (post-build)

After implementation, a holistic security review was run over the whole branch.
Outcome and honest scope notes:

- **#1 (keystone) — fully closed.** Initial wiring pinned only the universe
  `hard_boundaries`; a follow-up (`1fa947e`) also pins `SELFMOD_ALLOW_CORE` and
  `CORE_PROTECTED_FILES` into the epoch and routes the guard's core-lock through
  `hooks._coreLockFor(state)`. A mid-run edit to those constants is now ignored by the
  running guard (test: `test_core_lock_uses_pinned_epoch_not_live_config`). Legacy
  (no-epoch) tasks fall back to live config unchanged.

- **What the epoch ENFORCES vs only SNAPSHOTS.** Consumed at enforcement points:
  `universe.hard_boundaries` + `SELFMOD_ALLOW_CORE` + `core_protected_files` (the hook)
  and the `self.code` fingerprint (divergence detector + post-run gate). Also snapshotted
  but NOT yet consumed by a decision site: the remaining `config_knobs`
  (`MAX_SUBTASK_ATTEMPTS`, `RETRIEVAL_K`, …) and `brain_tag` — the loop still reads these
  live. This is not in-process-exploitable today because the only `set_override` caller
  runs **post-run** (`sie.run_maintenance`), so config doesn't mutate within a run.
  Pinning the loop's non-security knobs + brain identity to the epoch is deferred to a
  later spec.

- **#24 correction.** The earlier note that #24 (brain identity) "closes for free" was
  optimistic: `brain_tag` is snapshotted but no consumer reads it yet (the loop resolves
  the tag live via `finetune.active_brain_tag()`). #24 is therefore **deferred to Spec 2**,
  not closed here.

- **`reflection.trust` (advisory) — deliberate scope.** `trust()` still treats a
  verify-passing, never-adversary-reviewed subtask as trusted. This is acceptable because
  `trusted` reflections feed only **advisory lessons**, not the weight-rewriting sinks:
  distillation/LoRA (#9) and `solution_cache` (#11b) draw exclusively from
  `gold_examples`, which requires a real (non-stub) approval. Tightening the advisory
  path to require positive attestation is deferred to avoid starving the lessons pool;
  the catastrophic B-chain (gamed spec → weights) is already closed.

- **Bonus fix — R10.** `agents/hooks.py` previously hardcoded `sys.path.insert(0,
  r"C:\9to5")`; it now derives its root from `__file__` (`18470a2`), so a worktree imports
  its OWN tree. This is itself a self/other-identity fix (a constant standing in for
  "self") and is required for worktree-isolated self-improvement.

- **Forgery residual (the documented Spec-1 boundary).** All provenance attestations are
  unsigned JSON in task-writable stores (`experience.db`, `knowledge/*`). A task with
  write access can forge `{"origin":"human"}` / `attested_by` and defeat any gate. Every
  gate notes this consistently; no gate claims to be unforgeable. Closing it requires
  Spec 3: boundary enforcement covering `state/experience.db` + `knowledge/` and an
  unforgeable integrity signature (HMAC over the provenance field). The gates here are the
  chokepoint + the honest default (unattested ⇒ untrusted), not a cryptographic guarantee.
