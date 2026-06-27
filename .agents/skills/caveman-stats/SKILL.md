---
name: caveman-stats
description: >
  Show real token usage and estimated savings for the current session.
  Reads directly from the Codex session JSONL — no AI estimation.
  Triggers on /caveman-stats. Normally the UserPromptSubmit hook computes and
  displays the numbers and the model does nothing; the fallback below runs only
  if that hook is absent.
---

# caveman-stats

**Primary path (no model action):** a `UserPromptSubmit` hook —
`C:\Users\fireh\.Codex\hooks\caveman-stats.mjs`, registered in
`~/.Codex/settings.json` — intercepts `/caveman-stats`, reads the session
`transcript_path`, and returns `{"decision":"block","reason":<stats>}`. That
blocks the prompt and shows the numbers to the user directly. When this works you
will usually not even see this skill fire (the prompt is erased).

**Fallback (model action) — ONLY if you see this skill fire and NO stats were
already shown to the user** (i.e. the hook is missing/disabled): the same script
runs standalone and prints the stats to stdout. Do exactly this and nothing else:

```
node C:\Users\fireh\.Codex\hooks\caveman-stats.mjs --cli
```

`--cli` auto-discovers the newest `*.jsonl` under `~/.Codex/projects` (the current
session). If you already know the exact transcript path, pass it instead:
`node C:\Users\fireh\.Codex\hooks\caveman-stats.mjs --transcript "<path>"`.

Print the script's stdout to the user verbatim. Do not estimate the numbers
yourself — the script is the single source of truth (it parses the JSONL's
`message.usage`, summing `output_tokens` and `input_tokens` +
`cache_creation_input_tokens` + `cache_read_input_tokens`). The "saved" figure is
an explicit estimate (assumed `RETENTION` of a non-caveman baseline).
