# `tools/` — the AI-navigation layer (dev tooling)

The machinery that keeps the repo legible to LLM agents. Index: `tools/AGENTS.md`.

## What lives here
- **`repo_map.py`** — the single generator for three artifacts: the `@AI-MAP` header spliced into
  each module docstring, `.repo-map.json` (machine index), and `AGENTS.md` (root + per-package).
  Deterministic + drift-tested (`tests/test_repo_map.py`).
- **`dev.py`** — the fast inner loop: `check` (lint+type+affected tests+drift), `outline`, `where`,
  `watch`, `test`, `fast`, `map`, … (`python tools/dev.py <cmd>`).
- **`affected_tests.py`** — map changed files → covering tests.
- **`codemod.py`** — AST/libcst-based usages + rename.

## Must NOT
- Hand-edit the generated artifacts (`.repo-map.json`, `AGENTS.md`, the `@AI-MAP` blocks).
  Regenerate: `python tools/repo_map.py`. Only the `SIDE-EFFECTS` line in a header is human-authored
  (it is preserved across regeneration).
- Let the index go stale — the drift test (`tools/repo_map.py --check`) is the gate.

## Commands
`python tools/repo_map.py` (regen) · `python tools/repo_map.py --check` (drift) ·
`python tools/dev.py check <file>` · `python scripts/repo_health.py` (cold-start status).
