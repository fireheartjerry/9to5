# PR Feedback — Post-PR Learning Loop

Captures CI status and review feedback after every PR creation and writes the
result to the experience ledger so the learning loop can treat failed CI /
change-request reviews as negative signal and block auto-promotion.

---

## Architecture overview

```
orchestrator finalization phase
        │
        ▼
 capturePRFeedback(pr_url, run_id, subtask_id)  ← platform_core/orchestration/pr_feedback.py
        │
        ├── gh pr view  →  head commit SHA
        ├── gh api check-runs  →  poll until complete (up to poll_attempts × poll_interval)
        ├── gh api reviews  →  latest review state per reviewer
        │
        ├── record_feedback(kind="pr_ci", ...)   ← memory/experience.py
        ├── record_reflection(role="executor", teacher="github_ci", ...)
        └── record_pr_outcome(...)               ← memory/experience_pr.py
                                                      (pr_outcomes table)
```

`promote_safe` is `True` only when CI passed **and** no reviewer requested
changes.  Callers must check this flag before auto-promoting a change.

---

## Modules

| Module | Role |
|---|---|
| `platform_core/orchestration/pr_feedback.py` | Public API — `capturePRFeedback` |
| `memory/experience_pr.py` | `record_pr_outcome` / `fetch_pr_outcomes` (SQLite `pr_outcomes` table) |
| `memory/experience_schema.py` | Shared schema — `pr_outcomes` table DDL, connection pool |
| `memory/experience.py` | `record_feedback` / `record_reflection` (existing SIE ledger) |

---

## Public API

### `capturePRFeedback`

```python
from platform_core.orchestration.pr_feedback import capturePRFeedback

result = capturePRFeedback(
    pr_url="https://github.com/owner/repo/pull/42",
    run_id="run-abc123",
    subtask_id="st-010",          # optional; enables record_reflection
    poll_attempts=6,              # default 6
    poll_interval=30,             # seconds between polls; default 30
)
```

**Returns:**

```python
{
    "ok": True,
    "pr_url": "...",
    "ci_status": "passed" | "failed" | "pending" | "unknown",
    "ci_summary": "All 4 CI check(s) passed",
    "review_state": "approved" | "changes_requested" | "pending" | "none",
    "review_feedback": ["reviewer comment body", ...],   # max 3, truncated at 300 chars
    "promote_safe": True,          # False when CI failed OR review requested changes
    "provenance": {
        "origin": "pr_feedback",
        "owner": "...", "repo": "...", "pr_number": "42",
        "head_sha": "...", "run_id": "...", "subtask_id": "...",
    },
    "ledger_pr_outcome_ok": True,  # whether record_pr_outcome succeeded
}
```

Never raises — errors degrade to `{"ok": False, "skipped": True, "reason": "..."}`.

### `fetch_pr_outcomes`

```python
from memory.experience_pr import fetch_pr_outcomes

# All outcomes for a run
rows = fetch_pr_outcomes(run_id="run-abc123")

# Only outcomes that block promotion
blocked = fetch_pr_outcomes(promote_safe=False, limit=20)
```

---

## Deployment Instructions

### Prerequisites

- `gh` CLI installed and authenticated (`gh auth status`).
- `EXPERIENCE_LEDGER_ENABLED=true` in `.env` (controls whether writes go through).
- Python dependencies unchanged — no new packages required.

### Step 1 — Verify the new modules are importable

```bash
python -c "from platform_core.orchestration.pr_feedback import capturePRFeedback; print('ok')"
python -c "from memory.experience_pr import record_pr_outcome, fetch_pr_outcomes; print('ok')"
```

Both should print `ok` with no errors.

### Step 2 — Confirm the `pr_outcomes` schema is applied

The `pr_outcomes` table is created automatically on first connection via
`memory/experience_schema.py`.  To verify:

```bash
python - <<'EOF'
from memory.experience_schema import init, _connect
init()
with _connect() as c:
    rows = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='pr_outcomes'").fetchall()
    print("table present:", bool(rows))
EOF
```

### Step 3 — Wire the call into the orchestrator finalization phase

In the finalization block that runs after `createPullRequest` succeeds, add:

```python
from platform_core.orchestration.pr_feedback import capturePRFeedback

pr_result = capturePRFeedback(
    pr_url=created_pr_url,
    run_id=current_run_id,
    subtask_id=current_subtask_id,   # pass None if not available
)
if not pr_result.get("promote_safe"):
    LOG.warning("Auto-promotion blocked: %s", pr_result.get("ci_summary"))
    # Surface the reason to the user / dashboard and halt promotion
```

> **Self-modification boundary:** `orchestrator.py` is a protected core file.
> Record this wiring step as a human-review item in the run output instead of
> editing the file directly.

### Step 4 — Run the focused test suite

```bash
python -m pytest tests/test_pr_feedback.py tests/test_experience_pr.py -v
```

All tests must pass before any branch is promoted.

### Step 5 — Smoke-test with a real PR URL (optional, manual)

```bash
python - <<'EOF'
from platform_core.orchestration.pr_feedback import capturePRFeedback
import json
r = capturePRFeedback(
    pr_url="https://github.com/<owner>/<repo>/pull/<N>",
    run_id="smoke-test",
)
print(json.dumps(r, indent=2))
EOF
```

Replace `<owner>/<repo>/pull/<N>` with an actual PR.  Confirm `ok=True` and a
meaningful `ci_status`.

---

## Promotion Gate

`promote_safe` is `False` when **either** of:

- `ci_status` is `failed`, `cancelled`, `timed_out`, `action_required`, or `stale`
- `review_state` is `changes_requested`

A caller that ignores `promote_safe` and auto-promotes on a failed result will
produce a ledger entry with `trusted=False` and `confidence=0.3`, which the SIE
learning loop counts as negative signal.

---

## Learning Loop Integration

`record_reflection` stores each PR outcome keyed to the subtask:

| Field | Value |
|---|---|
| `role` | `"executor"` |
| `teacher` | `"github_ci"` |
| `trusted` | `promote_safe` |
| `confidence` | `0.9` if `promote_safe`, else `0.3` |
| `approach` | PR URL + ci_status + review_state |
| `reusable_recipe` | Standard CI polling recipe |
| `spec_feedback` | Review comment bodies (joined, truncated) |
| `verify_critique` | `"ci_status=..., review=..."` |

The SIE picks these up via `memory/retrieval.py` during the next `run_maintenance`
pass.  Failed PR outcomes lower the adapter confidence and may trigger a policy
rebuild.

---

## Observability

All writes are logged at INFO/WARNING/ERROR under the `orchestrator.pr_feedback`
logger:

```
INFO  orchestrator.pr_feedback: capturing feedback for owner/repo#42
WARN  orchestrator.pr_feedback: promote_safe=False for ... (ci=failed, review=none)
ERROR orchestrator.pr_feedback: record_pr_outcome failed — PR outcome data may be lost: ...
```

---

## Tests

| File | What it covers |
|---|---|
| `tests/test_pr_feedback.py` | `capturePRFeedback` end-to-end with mocked `gh` |
| `tests/test_experience_pr.py` | `record_pr_outcome` / `fetch_pr_outcomes` SQLite writes |
| `tests/slow/test_learning_loop.py` | SIE integration with PR feedback signal |

Run all three:

```bash
python -m pytest tests/test_pr_feedback.py tests/test_experience_pr.py tests/slow/test_learning_loop.py -v
```
