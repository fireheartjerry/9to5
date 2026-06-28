# Memory

Persistent memory and note-writing behavior for 9TO5.

## Obsidian role

Obsidian stores long context and human-readable run notes.

Task JSON should stay lean. Long executor output, architecture notes, replans, reviews, and handoffs belong in Obsidian or trace logs.

## Obsidian REST API

Notes are written via Local REST API:

```txt
https://127.0.0.1:27124
verify=False
Authorization: Bearer <OBSIDIAN_API_KEY>
```

The API serves whichever vault is currently open in Obsidian.

If a different vault is open, the key may be rejected with 401. In that case, 9TO5 should fall back to disk writes.

## Disk fallback

Fallback path:

```txt
C:\9to5\vault\9to5\
```

Preserve fallback behavior. Memory writes must be resilient because autonomous runs should not lose context just because a desktop app decided to be dramatic, as desktop apps are legally required to do.

## Vault structure

```txt
vault/9to5/tasks/<task_id>_<date>/
  index.md
  architect.md
  replan-log.md
  subtasks/
    st-001.md
    st-001-rv.md
  handoffs/
    ho-001.md

vault/9to5/sessions/
```

## What belongs in memory

Use memory for:

- architect design docs
- subtask outputs
- adversary reviews
- replanning logs
- context handoffs
- final reports
- lessons learned
- failure analysis
- durable playbooks if promoted

Do not use memory as canonical run state.

## Experience DB

If a SQLite experience DB exists, it should store structured lessons/traces.

It should not bypass:

- verifier
- adversary
- control gates
- hard boundaries
- source-of-truth state ownership

### PR outcomes table (`pr_outcomes`)

Added alongside the existing `reflections` and `human_feedback` tables. Stores one
row per `(run_id, pr_url)` keyed pair, upserted on each `capturePRFeedback` call:

| Column | Type | Notes |
|---|---|---|
| `run_id` | TEXT | 9TO5 run ID |
| `subtask_id` | TEXT | optional; enables `record_reflection` |
| `pr_url` | TEXT | full GitHub PR URL |
| `ci_status` | TEXT | `passed` / `failed` / `pending` / `unknown` |
| `ci_summary` | TEXT | human-readable CI outcome |
| `review_state` | TEXT | `approved` / `changes_requested` / `pending` / `none` |
| `review_feedback_json` | TEXT | JSON list of reviewer comment bodies (max 3) |
| `promote_safe` | INTEGER | `1` = safe to promote; `0` = blocked |
| `provenance_json` | TEXT | JSON with `origin`, `owner`, `repo`, `pr_number`, `head_sha` |
| `recorded_at` | TEXT | ISO-8601 timestamp |

The schema is applied automatically on first `_connect()` — no migration script needed.

**API:**
```python
from memory.experience_pr import record_pr_outcome, fetch_pr_outcomes

# Fetch all outcomes where promotion is blocked
blocked = fetch_pr_outcomes(promote_safe=False, limit=20)
```

See `docs/pr_feedback.md` for the full architecture and deployment instructions.

## Memory change checklist

Before changing memory code:

1. Read `CLAUDE.md`.
2. Read this file.
3. Read `docs/STATE.md` if task JSON/control state is involved.
4. Read `docs/DANGER_MAP.md`.

After changing memory code:

1. Test REST failure fallback if possible.
2. Test disk write behavior.
3. Avoid requiring live Obsidian for normal fast tests.
4. Update docs if paths, note names, or fallback rules changed.
