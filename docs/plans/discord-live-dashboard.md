# Discord Live Run Dashboard

## Goal
Replace scattered per-event messages with a single edit-in-place run dashboard message. Gives continuous presence without notification spam.

## Design

**One message per run**, edited in place throughout:

```
[RUN abc123] ████████░░ 78%
Phase: executing subtask 2/3
└─ Claude subprocess: refactoring run_loop.py (45s elapsed)
└─ Last event: adversary review passed ✓
Recently discovered: 2 size violations, 1 missing test
ETA: ~8min
```

At run end, the message becomes the final summary with PR link.

## Constraints
- Edit at most every 10s to stay safe from Discord rate limits
- Zero new messages mid-run
- Message must degrade gracefully if edit fails (don't crash the run)

## What to Show
- Run ID, progress bar, % complete
- Current phase name
- Active subprocess + elapsed time
- Last significant event
- Discoveries made so far (if running discovery engine)
- ETA estimate

## Files Likely Touched
- `notifications/discord_*.py` — add edit-message capability
- `platform_core/orchestration/run_phase_mixin.py` — emit progress events
- `platform_core/orchestration/run_loop.py` — create dashboard message at run start

## Status
PARKED — implement after Proactive Discovery Engine (#1)
