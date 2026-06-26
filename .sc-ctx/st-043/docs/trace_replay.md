# Trace Replay

**Location:** `.claude/skills/trace_replay.md`  
**Companion README:** `.claude/skills/trace_replay/README.md`  
**CLI tool:** `agents/trace-replay.py`

---

## What it does

The `trace-replay` subagent loads archived 9TO5 execution traces (JSONL event logs) and
replays them step-by-step to surface divergence points — the exact moment where the
orchestrator deviated from the expected happy path.

---

## See also

- `.claude/skills/trace_replay.md` — LLM-facing protocol (phases 1–6, full prompt)
- `docs/TESTING.md` — how to run the narrowest useful test after a patch
