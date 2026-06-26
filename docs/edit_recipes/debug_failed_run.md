# Debug Failed Run

Use when diagnosing a failed 9TO5 run.

## Read first

- `CLAUDE.md`
- `docs/ARCHITECTURE.md`
- `docs/STATE.md`
- `docs/DANGER_MAP.md`

## Inspect

- task JSON
- ControlBus JSON
- Obsidian task notes
- run logs / traces
- verifier stdout/stderr
- adversary review
- replanner logs
- dashboard recent events

## Questions to answer

- What was the system trying to do?
- Who/what decided that?
- What files was it allowed to touch?
- What did it actually change?
- What did verification expect?
- Why did verification fail?
- What did the adversary object to?
- What did the replanner change?
- What final state did the system end in?

## Rules

Do not patch broadly before identifying the smallest likely cause.

## Verification

Rerun the failed focused command first. Then run the relevant module/integration test.
