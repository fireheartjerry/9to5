# caveman-stats

Real session token receipts. No AI estimation.

## What it does

Parses the current Claude Code session JSONL and reports actual token usage
(`output_tokens`, and input as `input_tokens + cache_creation_input_tokens +
cache_read_input_tokens`) plus an estimated savings vs a non-caveman baseline.
Numbers come straight from the log on disk — the model does not estimate them.

One script does both jobs: `~/.claude/hooks/caveman-stats.mjs`.

- **Hook mode** (primary): registered on `UserPromptSubmit` in `~/.claude/settings.json`.
  It fires on every prompt, hard-gates on `/caveman-stats` (passing everything else
  through untouched), and on a match returns `{"decision":"block","reason":<stats>}`
  — which displays the numbers to the user and erases the prompt. Fail-open: any
  error exits 0 so it can never block normal prompts.
- **CLI / fallback mode**: `node ~/.claude/hooks/caveman-stats.mjs --cli` (auto-finds
  the newest session log) or `--transcript "<path>"`. Prints stats to stdout. `SKILL.md`
  tells the model to run this only if the hook is absent.

It also writes the session's estimated savings to `~/.claude/caveman-savings.txt`
(e.g. `⛏ 3.8M`) for an optional statusline badge.

## How to invoke

```
/caveman-stats
```

## Example output

```
⛏  CAVEMAN RECEIPTS — estimated
Assistant replies : 1,207   (user events: 685)
Output (caveman)  : 2,072,320 tok
Input total       : 590,192,601 tok  (fresh 262,081 · cache-read 585,468,295 · cache-write 4,462,225)
Baseline output   : 5,920,914 tok  (est. without caveman, ~35% retention)
Saved (est.)      : 3,848,594 tok  (~65%)
```

## Optional statusline badge

The script keeps `~/.claude/caveman-savings.txt` current. To surface it, add a
`statusLine` command in `~/.claude/settings.json` that prints the file's contents.
The `Saved` line is an **estimate** — tune `RETENTION` at the top of the script.

## See also

- [`SKILL.md`](./SKILL.md) — hook contract + model fallback
- [Caveman README](../../README.md) — repo overview
