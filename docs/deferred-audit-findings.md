# Deferred audit findings (blocked on concurrent edits)

Two HIGH-severity bugs surfaced by the overnight deep audit (2026-06-24) could **not** be fixed in
that session because the files had **uncommitted changes from a concurrent session** (an in-flight
`orchestrator.py` / `adversary.py` / `llm_io.py` refactor). Editing/committing them would have
swept up that unrelated WIP. Fix these once those files are clean (`git status` shows them
unmodified), each with a reproduction + regression test.

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

_Source: deep-audit-pass2 workflow, adversarially verified. Findings cached at run time; re-derive
exact line numbers against the current file before fixing (the concurrent refactor will have moved them)._
