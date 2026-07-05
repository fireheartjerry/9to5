# Refactor Multi-File

Use when splitting a module, renaming an export, or making any multi-file edit that must land
atomically — all files change or none do. The `refactor/` package (stdlib leaf) provides
impact prediction and an all-or-nothing transaction with a crash journal.

## Read first

- `CLAUDE.md` (Modularity Rules — split patterns, size thresholds)
- `docs/ARCHITECTURE.md` (Any-project capabilities section)
- `.claude/rules/modularity.md`

## Likely files

- the module being split/renamed and its new sub-modules
- callers found by `findUsages` / flagged in `orphaned_usages`
- tests listed in `affected_tests`
- `AGENTS.md` headers — regenerate with `python tools/repo_map.py` afterwards

## Flow

1. **Model the root, predict impact before touching disk.**

```python
from introspect import extractProject
from refactor import predictImpact, RefactorTransaction, ReplaceInFile, WriteFile

model = extractProject(root)                 # any project root, not just 9to5
edits = [
    WriteFile("pkg/big_domain_a.py", DOMAIN_A_SRC),
    ReplaceInFile("pkg/big.py", old="def helperA(...): ...",
                  new="from pkg.big_domain_a import helperA"),
]
report = predictImpact(model, edits)         # pure, nothing written
if report.orphaned_usages:                   # callers that would break (file, line, kind)
    ...                                      # add re-exports or fix the callers first
if report.new_cycles:                        # import cycles the edits would CREATE
    ...                                      # restructure; pre-existing cycles never block
run_next = report.affected_tests             # tests importing the touched modules
```

2. **Apply atomically, gated on the project's own detected test command.**

```python
from introspect import KIND_TEST

test_cmds = [c for c in model.commands if c.kind == KIND_TEST]
gate = test_cmds[0].cmd.split() if test_cmds else None   # list form: no shell, no quoting bugs

tx = RefactorTransaction(root)
for edit in edits:
    tx.add(edit)                             # raises ValueError on invalid/forbidden paths
res = tx.apply(gate_cmd=gate)                # snapshot -> journal -> write -> gate -> commit
if not res.applied:
    print(res.reason)                        # why it rolled back (validation/compile/cycle/gate)
    print(res.gate_output)                   # stdout+stderr of the failed gate command
```

`apply()` is all-or-nothing versus validation and gate failures: every touched path is
byte-snapshotted and rolled back on any failure. Built-in gates: `py_compile` on every
touched `.py` (fail-closed even on pre-existing breakage) and only-NEW-import-cycles
(pre-existing cycles never block unrelated edits), then your `gate_cmd`.

3. **Crash recovery.** A hard process crash mid-apply leaves a `refactor-tx-*` journal dir
   in the system temp dir. Restore the pre-apply bytes with:

```python
from refactor import recoverJournal
res = recoverJournal(journal_dir)            # restores snapshots, deletes journal when clean
```

## Rules

- `RenameFile` never overwrites an existing target (fail-closed); `ReplaceInFile.old` must
  match exactly once.
- Edits that escape the root (`../`, absolute-outside) or touch a `FORBIDDEN_SEGMENTS`
  component (`.git`, `.env`, `venv`, `.venv`, `node_modules`, `__pycache__`) are rejected
  with an explicit reason — do not route around this guard.
- Prefer the list form for `gate_cmd`; a string is shlex-split (Windows-safely) as a fallback.
- When splitting a 9to5 module, keep the facade re-exporting all public names
  (`.claude/rules/modularity.md`), then run `python tools/repo_map.py`.

## Verification

- `python -m refactor check <root>` — import-cycle report, exit 1 on cycles.
- Run the tests from `report.affected_tests`, then `python tools/dev.py check <file>` on
  changed 9to5 files and `python tools/size_audit.py`.
