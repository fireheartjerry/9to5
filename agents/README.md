# `agents/` — the replaceable intelligences (+ the guard hook)

Concrete implementations of the `protocols.py` seams: the things that *execute, review, and
draft* under the orchestrator's strict protocol. Module-by-module index: `agents/AGENTS.md`.

## What lives here
- **Executor** — `executor.py` (Claude Code CLI subprocess; `Executor` protocol).
- **Drivers** — `browser_executor.py`, `native_executor.py`, `chatgpt_driver.py`, `vlm_healer.py` (non-terminal surfaces).
- **Reviewers** — `adversary.py`, `second_brain.py` (`Reviewer` protocol; advisory verdicts).
- **Verifier** — `verifier.py` (`Verifier` protocol; `{cmd, expect}` → pass/fail).
- **Authoring** — `architect.py` (→ `architect.md`), `elaborator.py`, `clarifier.py`, `replanner.py`.
- **Guard** — `hooks.py` (the PreToolUse self-modification guard; with `identity.py`/`provenance.py`/`epoch.py` it is the only hard stop).

## Must NOT
- Own or mutate run state — that's `state/task.py`. Agents return results; the orchestrator decides.
- Verifier specifically: must not mutate state, replan, or call a dashboard (it is the deterministic proof gate).
- Weaken `hooks.py` boundaries — see `docs/DANGER_MAP.md`.

## Tests
`tests/test_executor.py`, `tests/test_verify_*.py`, `tests/test_adversary*.py`, `tests/test_apply_replan.py`, … (flat under `tests/`).
