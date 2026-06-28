# Intelligence & Control — Design Spec

**Date:** 2026-06-28
**Status:** Approved for implementation
**Companion:** `2026-06-28-observability-surfaces-design.md` (Spec A)
**Future:** `docs/plans/human-nature-insertion.md` (parked — opinions, instincts, emotions, self-awareness)

---

## Vision

The system should feel available — always ready to tell you exactly what you want to know, at exactly the level of detail you want, tuned to how you think. Alongside that, the system's accumulated knowledge should permeate every interaction: you should feel it drawing on experience, not starting from zero each time.

This spec covers the **intelligence and control layer**: how the system understands what you want, how you steer it mid-run, how it pre-empts your questions, and how its accumulated knowledge makes all of it smarter over time.

---

## Concept 1: The Briefing

On demand, always fast, always tuned to your preferences.

### Interface
- `!brief` in Discord → Nightclaw posts one message (persists, not ephemeral)
- `/brief` slash command → same
- `Brief` button in Discord cockpit
- `[BRIEF]` button on Bloomberg web dashboard

### What it produces
Fast Ollama call (cheapest available model, target <3s). Not a dump of raw data — a synthesized paragraph written as if from a colleague:

> *"IRON_PHOENIX is 47% through. st-003 is active — Claude's been on it 2min, edited 4 files, no issues flagged yet. One thing to watch: the adversary pushed back on st-002's verify spec, which might surface again on st-004. Innovation ratio this run is 73% — higher than usual. ETA ~11min if pace holds."*

### Depth levels

User can always request more or less:
- `!brief` → default level (preference-stored)
- `!brief one-line` → single sentence: `IRON_PHOENIX · 47% · st-003 active · ⬤ 87 health · ~11min`
- `!brief deep` → full breakdown: each subtask status, all tool calls in last 5min, adversary history, discovery findings in play, cost breakdown, SIE signals active
- `!brief raw` → raw event log snapshot, last 50 lines

### Preference memory
The briefing remembers your preferences across sessions. Stored in `memory/user_prefs.py`:
```python
{
    "brief_default_depth": "standard",      # one-line | standard | deep | raw
    "brief_include_cost": True,
    "brief_include_adversary": True,
    "brief_include_discovery": True,
    "brief_include_tool_calls": False,      # user turned off
    "brief_tone": "colleague",             # colleague | analyst | minimal
}
```

User adjusts preferences by saying: `!brief set tool-calls off` or `!prefer brief without cost`.
These are stored and applied on every future `!brief` call, this run and all future runs.

### Fast Ollama call spec
Input: compact JSON of current state (subtasks, events last 5min, health score, SIE signals).
Target: <3s response. Uses `config.BRIEF_MODEL` (defaults to smallest available Ollama model).
Prompt seeds the tone from user preference (`brief_tone`).
Never blocks a run — fires off-thread, result posted when ready.

---

## Concept 2: Intent Injection

Steer the system mid-run with high-level intent. Not mechanical controls ("skip st-004") but genuine direction ("focus on the Windows edge case, the cleanup subtasks can wait").

### Interface
- Discord: `!intent <text>` — persists in channel
- Discord: `Intent` button in cockpit → modal with text field
- Web dashboard: `[ADD INTENT]` button → text field inline
- `/intent <text>` slash command

### How it works
Intent text is stored in `state.meta["user_intents"]` (list, append-only).
The Ollama brain reads `user_intents` at every replanning decision and plan-gate approval.
The executor's `CLAUDE.md` inject includes the latest active intent at the top.

The intent is NOT a command. It is context. The Ollama brain decides how to act on it.
If the intent contradicts the current plan, the brain surfaces that: *"New intent conflicts with st-005 — should I adjust the plan?"*

### Intent lifecycle
- Intents expire after 2 subtasks complete (they're for now, not forever)
- User can cancel: `!intent clear`
- User can make permanent: `!intent persist <text>` → stored in user prefs, applied every run

### Example intents
- `!intent the windows path separator edge case matters more than I said`
- `!intent deprioritize the cleanup subtasks, ship the core feature first`
- `!intent I just realized the verify spec for st-004 is wrong, adjust accordingly`
- `!intent be more conservative, we're close to the deadline`

---

## Concept 3: Brain Dialogue

A direct window into the Ollama brain's current reasoning. Ask it anything mid-run.

### Interface
- `!why` → why is the current subtask ordered this way?
- `!why <decision>` → why did you make this specific decision?
- `!explain st-003` → what is this subtask trying to achieve?
- `!plan-rationale` → why was the plan structured this way overall?
- `!ask <question>` → open-ended question to the brain

### How it works
Fast Ollama call with: the architect doc, current plan, last 3 events, and the user's question.
Response is direct: the brain answers in the voice of its reasoning, not a system message.
Persists in Discord as a normal message.

Example:
> You: `!why st-004 before st-005?`
> Brain: *"st-005 depends on the connection pool fix that st-004 produces. Running st-005 first would mean verifying against a broken pool — the verify would pass for the wrong reason. The ordering is a dependency constraint, not preference."*

### Tone
Not robotic. The brain has the voice of a thoughtful engineer explaining their work.
`config.BRAIN_DIALOGUE_SYSTEM_PROMPT` controls the framing.

---

## Concept 4: Predictive Flags

The system warns you before things go wrong. Surfaced proactively — you don't ask.

### Detection (cheap, heuristic-first)

**Statistical:**
- Subtask runtime > 2.5x historical average for similar subtask type → flag
- Replan count > 2x average for this goal type → flag
- Adversary rejection rate this run > 2x historical → flag
- Verify spec similarity to past failing specs (string overlap > 70%) → flag

**Pattern-based:**
- File cluster was a bug hotspot in last 5 runs → flag when subtask touches it
- Current subtask type has > 30% historical retry rate → pre-flag before attempt starts
- Deadline < 20% of time remaining but > 40% of work remaining → pace flag

**Optional Ollama enhancement:**
When a statistical flag fires, optionally run a cheap Ollama call to produce a natural-language explanation. Gated by `config.PREDICTIVE_FLAG_OLLAMA` (default False — heuristics only, fast).

### Expression
Posted to Discord as a normal message (persists):
> *"⚠️ st-003 verify spec looks similar to one that caused 3 retries in run #839. Pre-flagging."*
> *"⏱ st-002 is 2.3x slower than comparable subtasks. Watching."*
> *"📁 notifications/discord_client.py has been modified in 6 of the last 8 runs — elevated change risk."*

Rate-limited: at most 1 predictive flag per 90s, and never for the same signal twice in a run.

---

## Concept 5: Nightclaw Instinct

Occasional, unprompted pattern signals that aren't derived from explicit rules. The first step toward the human nature layer (see `docs/plans/human-nature-insertion.md`).

### What it is
A periodic Ollama call (every ~15min, or after significant state change) that reads:
- Current run state
- Last 10 SIE reflections
- Last 5 failure modes from experience ledger
- Current event stream

Prompt: *"You are 9to5's pattern-recognition layer. Read the current run state and your accumulated experience. If anything feels wrong or unexpected — even if you can't articulate why — say so in one sentence. If everything looks normal, say nothing. Do not explain, do not list evidence. Trust your pattern."*

If the model returns a non-empty response, post it to Discord:
> *"Something feels off about this approach. Can't point to a specific signal — just pattern. Flagging."*

The key: it is sometimes wrong. That's intentional. An instinct that's always right is just a rule. An instinct that's sometimes wrong but earns your trust over time is alive.

### User response
- `!ignore` → tells the system to proceed, not refile this signal
- `!explain` → asks the brain to try to articulate why it flagged
- Default: acknowledged with a thumbs-up reaction, run continues

### Rate
At most once per run. More would be noise. Less than one per 5 runs would be invisible.

---

## Concept 6: Granular Mid-Run Controls

Beyond the existing skip/retry/abort — fine-grained steering of the live run.

### New controls

**Subtask-level:**
- `!retry <sid>` — retry a specific subtask (already exists via ControlBus; surface more prominently)
- `!kill-subprocess` — terminate the current Claude process (not the run, just the current attempt); useful when Claude is stuck
- `!inject-context <text>` — add text to the next attempt's CLAUDE.md inject without replanning
- `!set-effort <sid> <level>` — override effort for a specific subtask's next attempt
- `!inspect <sid>` — post full raw stdout of a subtask's last attempt to Discord

**Run-level (mid-run, no restart):**
- `!effort <level>` — change default effort for all future subtasks this run
- `!mode gated|watch` — switch control mode live
- `!add <description>` — inject new subtask (already exists; surface in cockpit UI)
- `!replan` — force a replanning pass now (don't wait for a subtask failure)
- `!deadline +1h` — extend the run horizon

**Information:**
- `!cost` — current estimated cost breakdown by phase
- `!tokens` — token usage this run by phase
- `!git` — what git changes have been made so far this run
- `!diff` — post the current `git diff` as a thread

### Discord cockpit selects (CV2)
Three String Select menus embedded in cockpit (from frontier spec, now wired to these controls):
1. **Subtask select** — choose any subtask → actions: skip / retry / inject context / inspect
2. **Effort select** — change run effort level live
3. **Mode select** — watch ↔ gated

### Web dashboard controls
All of the above available as buttons/inputs in the Bloomberg terminal:
- Per-subtask row: [SKIP] [RETRY] [KILL] [INJECT] [INSPECT]
- Global bar: [ADD SUBTASK input] [SET EFFORT ▾] [REPLAN] [EXTEND +1H]
- Info bar: [COST] [TOKENS] [GIT] [DIFF]

---

## Concept 7: Availability — Preference-Tuned Information

Nightclaw always knows what YOU want to know.

### Preference model
`memory/user_prefs.py` — persistent across all sessions:
```python
{
    # Briefing preferences (see Concept 1)
    "brief_default_depth": "standard",
    "brief_include_cost": True,
    "brief_include_adversary": True,
    "brief_include_discovery": True,
    "brief_include_tool_calls": False,
    "brief_tone": "colleague",

    # Narration preferences
    "narration_include_tool_calls": False,
    "narration_subtask_transitions": True,
    "narration_adversary_events": True,
    "narration_replan_events": True,
    "narration_moments": True,

    # Alert preferences
    "predictive_flags_enabled": True,
    "instinct_enabled": True,
    "flag_min_severity": "medium",   # low | medium | high

    # Information level preference
    "default_detail_level": "standard",   # one-line | standard | deep | raw
}
```

### Preference update commands
- `!prefer brief without cost` → sets `brief_include_cost: False`
- `!prefer no tool-call narration` → sets `narration_include_tool_calls: False`
- `!prefer deep` → sets `default_detail_level: deep` (applies to brief + all on-demand posts)
- `!prefer one-line` → everything defaults to tightest format
- `!prefs show` → posts current preferences as a formatted message
- `!prefs reset` → resets to defaults

### The availability guarantee
Whatever the user asks, Nightclaw can answer — immediately, from live data, at the requested depth:
- Current state → `!brief`
- Specific subtask → `!explain st-003`
- Raw output → `!stdout st-003`
- What changed → `!diff`
- Why a decision → `!why`
- Full history → `!history`
- Learning signals → `!wisdom`

All commands are always available during a run. None block. All persist in Discord.

---

## Concept 8: Self-Improvement Made Visible

The system's accumulated experience permeates all output. The user sees the system getting smarter.

### Wisdom trail (web + Discord)
On web dashboard: "WISDOM TRAIL" section in metadata column — last 3 SIE reflections relevant to the current goal (keyword-matched against `state.meta["goal_raw"]`).

On Discord: `!wisdom` posts the full wisdom trail — all reflections tagged as relevant to this run's domain, with run numbers and confidence scores.

### Learning signals in narration
When a decision is influenced by past experience, the narration says so:
> *"Using the concurrency guard pattern learned in run #839. Applying proactively."*
> *"This file cluster failed in 3 past runs. Taking extra care."*

The system learns to surface these signals from the SIE reflection tags. Each reflection has a `domain` tag; when a subtask touches files in that domain, the relevant reflection is surfaced.

### Post-run learning update
After each run, before teardown:
1. Self-reflection written (see Spec A)
2. `!growth` is posted to Discord — a 2-line learning summary:
   > *"IRON_PHOENIX taught me: Windows subprocess timing under heavy load is less reliable than I modeled. Updated confidence: subprocess domain +2pts."*
3. Intelligence curve on web dashboard updates (pulls new SIE data)

### `!growth` command
Available any time:
- `!growth` → what did the last 5 runs teach the system?
- `!growth <domain>` → learning trajectory for a specific domain
- `!growth curve` → posts the full intelligence curve as a formatted message

---

## Self-Improvement Permeation: Integration Points

How past knowledge flows into all 8 concepts above:

| Concept | SIE / Experience connection |
|---|---|
| Briefing | Includes active wisdom trail in deep mode |
| Intent Injection | Intents are contextualized against past failure modes |
| Brain Dialogue | Brain has access to SIE reflections in its context |
| Predictive Flags | File hotspot detection uses SIE failure modes |
| Nightclaw Instinct | Reads last 10 reflections + 5 failure modes |
| Mid-Run Controls | `!inspect` output tagged with past similar subtask outcomes |
| Availability | `!wisdom` command gives direct access to SIE |
| Growth | Every run adds to SIE; surfaced explicitly |

---

## New Files

### New
- `memory/user_prefs.py` — preference store + update commands
- `notifications/briefing.py` — `generate_brief(state, prefs, depth) -> str`
- `notifications/instinct.py` — `NightclawInstinct` — periodic Ollama call + flag logic
- `notifications/predictive.py` — `PredictiveFlags` — heuristic + optional Ollama flag engine
- `notifications/bot/cogs/log_cog.py` — `/logs`, `/stdout`, `/inspect`, `/brief`, `/why`, `/arc`, `/wisdom`, `/growth`, `/intent`, `/prefer` slash commands + `!` prefix equivalents
- `notifications/bot/cogs/context_cog.py` — 3 context-menu commands (from frontier spec)

### Modified
- `notifications/commands.py` — new pure routers for all new commands
- `notifications/cv2.py` — cockpit selects (subtask / effort / mode) + Section header
- `platform_core/orchestration/execute_mixin.py` — kill-subprocess, inject-context, set-effort-per-sid
- `platform_core/orchestration/run_loop_mixin.py` — replan-on-demand, deadline extend
- `platform_core/runtime/control.py` — new ControlBus ops: `kill_subprocess`, `inject_context`, `set_effort`, `force_replan`, `extend_deadline`
- `platform_core/orchestration/run_phase_mixin.py` — instinct periodic call, growth post at teardown
- `orchestrator.py` — user_prefs loaded at run start, threaded into all relevant calls
- `state/task_schema.py` — `user_intents` list, `instinct_flags` list

### Tests
- `tests/test_briefing.py`
- `tests/test_user_prefs.py`
- `tests/test_predictive_flags.py`
- `tests/test_instinct.py`
- `tests/test_intent_injection.py`
- `tests/test_brain_dialogue.py`
- `tests/test_log_cog.py`
- `tests/test_context_cog.py`

---

## Success Criteria

- `!brief` returns a response in <3s during a live run
- `!brief one-line` returns a single clean sentence
- `!intent <text>` is reflected in the Ollama brain's next replanning decision
- `!why` produces a coherent explanation of the current plan's reasoning
- Predictive flag fires correctly for a subtask touching a file with ≥3 past failures
- Nightclaw instinct fires at most once per run
- `!prefer brief without cost` persists across sessions
- `!wisdom` surfaces at least one relevant past reflection for any non-trivial goal
- `!growth` posts after every run within 30s of completion
- Intelligence curve on web dashboard reflects updated SIE data after run

---

## Implementation Order

1. `memory/user_prefs.py` + basic `!prefer` commands (foundation for everything)
2. `notifications/briefing.py` + `!brief` (highest immediate value)
3. Intent Injection + ControlBus ops (enables run steering)
4. Brain Dialogue + `!why` (transparency)
5. Predictive Flags (proactive value)
6. Granular mid-run controls (kill-subprocess, inject-context, force-replan)
7. Nightclaw Instinct (last — most experimental)
8. `!wisdom`, `!growth`, learning permeation across narration
