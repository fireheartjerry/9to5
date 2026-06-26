# Add Dashboard Metric

Use when adding metrics to Discord/web dashboards.

## Read first

- `CLAUDE.md`
- `docs/NIGHTCLAW.md`
- `docs/STATE.md`
- `docs/DANGER_MAP.md`

## Likely files

- `notifications/metrics.py`
- `notifications/dashboard.py`
- `notifications/webdash.py`
- dashboard tests
- `docs/NIGHTCLAW.md`

## Rules

- Dashboard metrics are derived display state.
- Do not mutate canonical run state for display convenience.
- Clamp verbose fields.
- Respect Discord embed limits.
- Keep missing data graceful.

## Verification

Run focused notification/dashboard tests. If no tests exist, add a small pure function test around metric formatting/clamping.
