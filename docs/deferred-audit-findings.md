# Deferred audit findings — ✅ ALL RESOLVED

These bugs were deferred during the overnight audit (2026-06-24) because the files had uncommitted
changes from a concurrent `orchestrator.py`/`adversary.py`/`llm_io.py` refactor. Once that refactor
landed, all three were fixed against the current code, each with a regression test:

- **#1 remediation git-clobber** → fixed in `7faab24` (`_remediationTreeShared` guard)
- **#2 malformed-verdict→approved** → fixed in `54d0b72` (`_normalizeVerdict` fails closed)
- **#3 knowledge-doc fixed-temp** → fixed in `7faab24` (unique per-writer temp)

The original analysis is kept below for reference.

---

---

## 1. Adversary remediation's whole-tree `git checkout -- .` clobbers concurrent parallel workers

- **File:** `orchestrator.py` — `_remediate` / `_gitSnapshot` / `_gitRestore` (~1248-1256, 1286-1294) and `_execCwd` (~2005-2014)
- **Severity:** HIGH (silent data loss). **Trigger:** `--parallel >=2` on a **non**-self-referential goal.
- **Root cause:** For non-self-ref runs every parallel subtask shares the repo-root cwd (`_execCwd`
  returns `work_dir`; only self-ref runs get an isolated `.sc-ctx/<sid>`). On a challenged verdict,
  `_remediate` snapshots with `git stash create` and, if a remediation edit fails re-verification,
  reverts with `git checkout <sha> -- .` — a **whole-repo** pathspec — while peer pool workers are
  actively editing other files. The snapshot/restore are not under `_state_lock` or any file lock,
  so a peer's just-written file is reverted and silently lost, yet that peer already recorded its
  subtask `done` with a passing verify captured before the revert.
- **Fix:** Make snapshot/restore tree-isolated and parallel-safe: (a) scope the restore to ONLY the
  files this subtask touched (`git stash show --name-only` → explicit pathspec) instead of `-- .`;
  (b) serialize all `_gitSnapshot`/`_gitRestore` under a dedicated repo-mutation lock; or best, give
  every non-self-ref parallel worker its own `git worktree` (as self-ref effectively gets via
  `.sc-ctx`). Simplest safe stopgap: disable adversary remediation when `parallelism>1` and the
  exec cwd is shared.

---

## 2. Malformed/typo'd adversary verdict silently becomes `approved`, neutering the PR hold

- **File:** `agents/adversary.py` — verdict parsing (~166-171) and both call sites (~211, 305)
- **Severity:** HIGH (safety gate defeated). 
- **Root cause:** Verdict parsing treats anything that isn't an explicit non-approval as `approved`.
  A malformed/off-contract verdict (missing `verdict` key, typo, prose-wrapped) collapses to
  `approved`, so a high-severity challenge is silently dropped and the PR hold never fires.
- **Fix:** Fail **closed** when the model clearly produced an off-contract shape: if `data` has no
  `verdict` key (or it isn't one of the known values), do NOT coerce to `approved` — raise in
  `_parseVerdict` / treat as junk so the caller degrades to the conservative **stub** review (which
  is at least labelled a stub and counts toward disabling a dead session), rather than a real
  `approved`.

---

---

## 3. Knowledge-doc atomic write uses a FIXED temp name (cross-process clobber)

- **File:** `orchestrator.py` — `refreshClaudeKnowledge` (~155-163)
- **Severity:** MEDIUM. 
- **Root cause:** Writes the ~1MB unified reference via a FIXED temp `kpath.with_suffix(".md.tmp")`
  (always `knowledge/claude_code.md.tmp`), guarded only by `_KNOWLEDGE_LOCK` (a **process-local**
  threading.Lock). `refreshClaudeKnowledge` runs at the start of *every* process (each run, the
  gateway bot, etc.), so two processes refreshing concurrently write the same temp and the second
  `os.replace` hits `FileNotFoundError` after the first moved it — exactly the bug already fixed in
  `ControlBus._write` and `TaskState.save`.
- **Fix:** Unique temp per writer — `kpath.with_suffix(f".{os.getpid()}-{threading.get_ident()}-{os.urandom(4).hex()}.md.tmp")`
  — with `try/except` cleanup of the temp on failure. (Same one-line pattern as the task.py fix in
  commit `3eca882`.)

---

_Source: deep-audit passes 2 & 3, adversarially verified. Findings cached at run time; re-derive
exact line numbers against the current file before fixing (the concurrent refactor will have moved them)._
