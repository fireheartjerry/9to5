# Observability & Surfaces — Design Spec

**Date:** 2026-06-28
**Status:** Approved for implementation
**Companion:** `2026-06-28-intelligence-control-design.md` (Spec B)
**Future:** `docs/plans/human-nature-insertion.md` (parked)

---

## Vision

9to5 should feel like a presence, not a tool. Every surface — web, Discord, tunnel — should make the user feel informed, in control, and watching something genuinely intelligent work. The goal is the feeling of excitement you get from a new AI model release: surprise, wonder, the sense that something alive is operating on your behalf.

This spec covers the **surface layer**: what you see and where you see it. Spec B covers the intelligence layer that feeds it.

---

## Architecture: LiveEventBus

**`notifications/event_bus.py`** — singleton, the nervous system of all surfaces.

Every event in the system — raw subprocess stdout lines, parsed tool calls, phase transitions, heartbeats, cost updates, moments, narration posts, learning signals — flows through one bus. Nothing bypasses it.

```python
class LiveEventBus:
    # Ring buffers
    _raw: deque[RawLine]            # all stdout lines, last 10,000
    _structured: deque[Event]       # parsed events, last 2,000
    _per_sid: dict[str, deque]      # per-subtask raw lines, last 1,000 each

    # Subscribers
    _sse_queues: list[Queue]        # one per open browser tab (web SSE)
    _discord_feed: DiscordFeed      # throttled + on-demand Discord layer

    def emit_raw(sid: str, line: str) -> None
    def emit(event: Event) -> None
    def subscribe_sse() -> Queue           # web SSE subscriber
    def unsubscribe_sse(q: Queue) -> None
    def history(sid=None, last_n=200) -> list[Event]
    def raw_history(sid: str, last_n=500) -> list[RawLine]
```

**Event types:**
```python
@dataclass
class Event:
    kind: str          # "tool_use" | "raw" | "heartbeat" | "phase" | "moment" |
                       # "narration" | "learning" | "health" | "predict" | "arc"
    sid: str           # subtask id or "system"
    text: str          # human-readable
    data: dict         # structured payload
    ts: float          # monotonic timestamp
```

All existing `dashboard.event()` / `dashboard.update()` calls are rerouted through the bus. The bus fans out to all subscribers.

---

## Subprocess Event Feed

**`notifications/subprocess_feed.py`** — `SubprocessFeed` class.

Created per Claude subprocess attempt in `execute_mixin._runOneAttempt`. Taps the stdout stream in real time.

```python
class SubprocessFeed:
    def __init__(self, bus: LiveEventBus, sid: str, started_at: float)
    def consume(line: str) -> None    # called per stdout line
    def stop() -> None                # called when process exits
```

`consume()` tries to parse each line as JSON (Claude's JSONL event format). On success, extracts tool events:

| Claude event | Bus event text |
|---|---|
| `tool_use` Edit | `✏️ editing path/to/file.py` |
| `tool_use` Write | `📝 writing path/to/file.py` |
| `tool_use` Bash | `⚡ bash: <cmd[:70]>` |
| `tool_use` Read | `👁 reading path/to/file.py` |
| `tool_use` Grep | `🔍 grep: <pattern>` |
| `tool_use` Glob | `🗂 glob: <pattern>` |
| `tool_use` Agent | `🤖 spawning agent: <desc[:60]>` |
| any other tool | `🔧 tool: <ToolName>` |
| non-JSON / unknown | stored as raw line only, not emitted as structured event |

Every raw line, parsed or not, is stored in `bus._raw` and `bus._per_sid[sid]`.

**Heartbeat thread:** fires every 30s while process is alive. Emits:
`⏱ <sid> · <elapsed>s · still running · <N> tool calls so far`

**`agents/executor_stream.py`** modification: `runSubprocess` gains optional `feed: SubprocessFeed = None`. When set, switches from `proc.communicate()` to line-by-line reading:
```python
for line in proc.stdout:
    out_lines.append(line)
    if feed:
        feed.consume(line.rstrip())
out = "".join(out_lines)
```
When `feed` is None: unchanged `communicate()` path. Zero regression.

**`agents/executor.py`**: `runClaude` gains `feed=None`, threads through to `runSubprocess`.

**`platform_core/orchestration/execute_mixin.py`**: `_runOneAttempt` creates `SubprocessFeed(bus, sid, time.monotonic())`, passes to `runClaude`, calls `feed.stop()` after result returns.

---

## Hyper-Robust Tunnel

**`notifications/tunnel.py`** — `TunnelManager`
**`notifications/tunnel_providers.py`** — provider implementations

### Provider chain (priority order)

```
1. CloudflaredProvider   — no account, binary auto-downloaded, most reliable
2. NgrokProvider         — skipped unless NGROK_AUTH_TOKEN in env
3. BoreProvider          — bore.pub open-source, binary auto-downloaded
4. LocaltunnelProvider   — npx lt, skipped if node/npx absent
5. (fallback)            — CV2 cockpit only, URL unavailable
```

Each provider implements:
```python
class TunnelProvider:
    name: str
    def available(self) -> bool
    def ensure_available(self) -> bool   # auto-download binary, returns success
    def start(self, port: int) -> subprocess.Popen
    def parse_url(self, line: str) -> Optional[str]
    def probe(self, url: str, timeout: float = 5.0) -> bool
```

**`CloudflaredProvider.ensure_available()`**: checks PATH → `~/.cloudflared/cloudflared[.exe]` → downloads platform-appropriate binary from `github.com/cloudflare/cloudflared/releases/latest` → caches permanently. Binary cached = fallback genuinely rare after first run.

### TunnelManager

```python
class TunnelManager:
    def start(self, port: int) -> None        # non-blocking; URL arrives via callback
    def stop(self) -> None
    def on_url(self, cb: Callable[[str], None]) -> None   # fires on first URL + every change
    @property
    def url(self) -> Optional[str]
    @property
    def provider_name(self) -> str
    @property
    def is_alive(self) -> bool
```

**Supervision (makes fallback genuinely rare):**

- **Process watchdog**: separate thread, checks `proc.poll()` every 5s
- **HTTP health probe**: GET to tunnel URL every 20s, 5s timeout — verifies end-to-end reachability, not just process liveness
- **Restart on failure**: exponential backoff 1s → 2s → 4s → 8s → 15s (cap). Resets to 1s after 5min of clean uptime.
- **Provider demotion**: if current provider fails 3 consecutive restarts → demote, try next provider. Demoted providers can re-qualify after 5min.
- **URL validation before posting**: new URL must return non-5xx within 10s before it is sent to Discord. Locally retries until valid, never posts a broken link.
- **Reconnect grace**: on reconnect, new URL is posted to Discord within 3s via message edit (not new message).
- **Resume support**: `state.meta["tunnel_url"]` written on every URL change. On `runFull` resume, probe saved URL first — if alive, reuse it, no new tunnel, no Discord edit.

**Non-blocking startup**: tunnel starts in background thread. Run proceeds immediately. Discord gets either the live URL within ~8s or a `🔗 Connecting…` placeholder that auto-edits when the URL is ready.

**Integration:**
- `_runPreamble` in `run_phase_mixin.py`: `tunnel = TunnelManager(); tunnel.on_url(dashboard.set_tunnel_url); tunnel.start(port)` alongside `startWebDashboard()`
- `dashboard.set_tunnel_url(url)`: edits the tunnel pin message with the new URL

---

## Bloomberg Terminal Web Dashboard

Full rewrite of `_PAGE` in `notifications/webdash.py`.

### Aesthetic

True Bloomberg density. No rounded cards. No gradients.
- Background: `#000000`
- Labels: `#ff9f00` (amber)
- Live/active: `#00d4aa` (green)
- Values: `#e8e8e8` (white)
- Error/fail: `#ff4444` (red)
- Muted: `#555555`
- Borders: 1px `#222222` — single pixel only
- Font: `ui-monospace` throughout, 13px
- Uppercase section headers everywhere

### Three-column fixed layout

```
┌─ 9TO5 ▸ IRON_PHOENIX ▸ [STATUS] ▸ goal text ──────────── tunnel URL ────┐
│ [ABORT] [PAUSE] [RESUME] [APPROVE] [REJECT]    ⬤ 91 HEALTH              │
├──────────────────┬──────────────────────────────┬────────────────────────┤
│ METADATA         │ LIVE FEED                    │ SUBTASKS               │
│                  │                              │                        │
│ MISSION          │ [filter: all ▾] [search___]  │ st-001 DONE      ✅    │
│ IRON_PHOENIX     │                              │ st-002 ACTIVE    ···   │
│                  │ 15:42:07 ✏️ run_loop.py      │ st-003 PENDING   —     │
│ TASK             │ 15:42:09 ⚡ git commit -m   │                        │
│ abc12345         │ 15:42:31 ⏱ heartbeat 30s    │ [SKIP] [RETRY]         │
│                  │ 15:43:02 👁 config.py        │ [VIEW LOGS]            │
│ MODEL            │ 15:43:15 📝 models.py        │                        │
│ sonnet-4.6       │ 15:43:45 ⏱ heartbeat 60s    │                        │
│                  │ 15:44:01 🔍 grep: pattern    │                        │
│ EFFORT   high    │ 15:44:22 ⚡ pytest -v        │                        │
│ MODE     watch   │                              │                        │
│ PHASE  executing │ ▼ EXPAND RAW STDOUT          │                        │
│                  │                              │                        │
│ ELAPSED  12m 04s │                              │                        │
│ ETA      ~8m     │                              │                        │
│ PROGRESS   1/3   │                              │                        │
│                  │                              │                        │
│ REPLANS    0     │                              │                        │
│ ADVERSARY  1     │                              │                        │
│ COST   $0.043    │                              │                        │
│                  │                              │                        │
│ DISCOVERY        │                              │                        │
│ 8 findings       │                              │                        │
│ theme: harden    │                              │                        │
│                  │                              │                        │
│ WISDOM TRAIL     │                              │                        │
│ · rate-limit fix │                              │                        │
│   (run #841)     │                              │                        │
│ · win path fix   │                              │                        │
│   (run #839)     │                              │                        │
└──────────────────┴──────────────────────────────┴────────────────────────┘
┌─ INTELLIGENCE CURVE ───────────────────────────────────────────────────────┐
│ subprocess   ████████████ +34%   verify     ████████░░░░ +19%            │
│ rate-limit   ████████░░░░ +12%   discovery  ████████████ +41%            │
└────────────────────────────────────────────────────────────────────────────┘
```

### Live feed features
- **SSE endpoint** `/api/events`: Server-Sent Events stream, pushes every `Event` from the bus as it arrives. Zero polling lag.
- **Filter bar**: filter by event kind (`tool_use`, `raw`, `heartbeat`, `moment`, `narration`, `phase`), by subtask ID, free-text search across text
- **Raw stdout expand**: click "▼ EXPAND RAW STDOUT" under any subtask → inline panel shows last 500 raw lines for that subprocess, auto-scrolling, live
- **Auto-scroll lock**: toggle — when locked, scrolls to latest; when unlocked, lets you read history
- **History**: feed keeps all 10,000 raw lines and 2,000 structured events. Scrollback shows everything.

### Health Aura
Single composite score (0–100) always visible top-right. Color encodes health:
- 80–100: green `#00d4aa`
- 50–79: amber `#ff9f00`
- 0–49: red `#ff4444`

Computed from: replan rate, adversary rejection rate, verify pass rate, subtask retry count, pace vs deadline. Updated every 30s.

### Wisdom Trail
Bottom of metadata column. Last 3 past-run lessons that are relevant to current goal (keyword match against SIE reflections). Shows: lesson summary, run number where it was learned. Makes the system's experience visible.

### Intelligence Curve
Bottom bar. Domain-by-domain confidence growth across last 30 runs, pulled from SIE ledger. Always visible. Updates after each run completes.

---

## Run Identity System

Every `TaskState.create()` call generates a codename stored in `state.meta["codename"]`.

**`platform_core/ops/codenames.py`** (new, small): `generate() -> str`
Word list: 200 adjectives × 200 nouns = 40,000 combinations. Examples: `IRON_PHOENIX`, `SILENT_THEOREM`, `EMBER_PROTOCOL`, `GLASS_MERIDIAN`.

The codename appears everywhere:
- Bloomberg terminal header: `9TO5 ▸ IRON_PHOENIX ▸ EXECUTING`
- Discord cockpit title: `IRON_PHOENIX · executing`
- The Cast narration: *"IRON_PHOENIX closed. Clean."*
- Self-reflection post header: `IRON_PHOENIX —`
- Obsidian note filename: `IRON_PHOENIX-abc12345.md`

---

## Moments

Certain events are elevated with ceremony. Emitted as `Event(kind="moment", ...)` into the bus.

**Triggers** (detected in `execute_mixin` and `run_phase_mixin`):
- Adversary catches a critical issue not in the original plan
- Claude expands scope autonomously (output contains more files touched than spec expected)
- Discovery finding rank 1 proves directly relevant to a failed subtask
- First subtask attempt that passes verify after 2+ prior failures (redemption)
- Run completes with 0 replans and 0 adversary triggers (perfect run)

**Expression:**
- Bus event with `kind="moment"`, elevated visually in both surfaces
- Web: feed row highlighted with left amber border
- Discord: The Cast posts in channel (not ephemeral) — one sentence, in voice:
  > *"⚡ MOMENT — Claude found something the subtask didn't ask for. Expanding. Watch this."*
- At most 2–3 moments per run. Rarity is the point.

---

## Self-Reflection Posts

At run end, before teardown, one paragraph posted to Discord and saved to Obsidian. Written by a fast Ollama call (llama3 / cheapest available) with the run summary as input.

**Prompt seed**: *"You are 9to5, an autonomous AI system. Write one short paragraph in first person about what you just did in run IRON_PHOENIX. Be specific about what surprised you, what you struggled with, and what you learned. Write as if in a personal journal, not a report. Max 100 words."*

**Output saved to**: `state/tasks/<task_id>/reflection.md` + Obsidian + Discord.

Accumulated reflections feed the institutional memory lens of the discovery engine.

Format in Discord:
```
IRON_PHOENIX — I came in thinking this was a rate-limit problem. It wasn't...
```

---

## Run Narrative Arc

A living story updated at key phase transitions. Stored in `state.meta["arc"]` (list of arc beats). Visible on web dashboard as a collapsible panel. Posted to Discord on demand via `!arc` or `/arc`.

Beat triggers and templates:
- After discovery: *"Chapter 1 — Discovery surfaced {N} findings. Theme: {theme}."*
- After architect: *"Chapter 2 — Architect chose {N} findings, shaped them into one narrative."*
- On first verify pass: *"Chapter 3 — First subtask closed clean."*
- On replan: *"Chapter {N} — Replanning. {reason}."*
- On completion: *"Final — {status}. {done}/{total} subtasks. {elapsed}."*

Arc beats accumulate; the arc is always readable as a story, not a log.

---

## Proactive Narration

Automatic posts to Discord when notable things happen — not on every event, only on meaningful transitions. One sentence, in The Cast's voice, posted as a normal channel message (not ephemeral, persists).

Triggers:
- Adversary triggers remediation: *"⚠️ Adversary flagged something in st-002. Remediating."*
- Replan fired: *"🔁 Replanning after st-003. Scope was wider than expected."*
- Subtask retry (attempt 2+): *"st-004 attempt {N}. Still working on it."*
- Discovery engine completes: *"🔍 Discovery: {N} findings, theme: {theme}."*
- Moment detected: (see Moments section above)
- Run complete: (arc final beat + self-reflection)

Rate-limited: at most one proactive narration per 60s, to prevent spam on rapid event bursts.

---

## Comparative Intelligence

After each run, pull relevant past-run statistics from the experience ledger and surface them in two places:
- Web dashboard: "COMPARATIVE" section in metadata column
- Discord: added to the self-reflection post as a footer line

Format:
```
THIS RUN vs AVG
pace         1.2x faster
innovation   73% (avg 41%)
adversary    0 triggers (avg 2.1)
replans      1 (avg 1.4)
```

Implementation: `learning/experience.py` already has `fetch_reflections` and `fetch_failure_modes`. New helper `compare_run(task_id) -> dict` computes deltas against rolling averages.

---

## Attention Modes

Two modes, switchable at any time:

**Away** (phone, Discord, on the go):
- Tunnel URL in Discord → tap to open Bloomberg terminal from anywhere
- The Cast narrates key moments
- Proactive narration fires on notable events
- `!brief` available any time

**Present** (desktop, web dashboard open):
- Full Bloomberg terminal with live SSE feed
- Raw stdout panel
- Filter and search
- All controls inline

Mode is detected heuristically (web dashboard has an active SSE subscriber → Present; otherwise Away) and can be forced with `/mode away` / `/mode present`.

In Away mode, Discord proactive narration is slightly more verbose. In Present mode, Discord narration is quieter (you can see everything yourself).

---

## Discord Surfaces

### Persistent (no bloat)

The cockpit remains one pinned message, edited in place. Max 1 edit per 5s.

A second persistent message: the **tunnel pin** — `🖥 Live Dashboard → <URL>`. Edited on URL change, never replaced.

Proactive narrations and Moments post as normal channel messages — they persist. These are intentional: they ARE the history. The Cast's voice over time becomes the run's chronicle.

### On-demand (not ephemeral — persists)

- `!logs [sid]` → posts last 100 raw lines of subprocess stdout as a code block
- `!stdout [sid]` → posts last 500 raw lines as a thread (thread keeps it off main channel)
- `!arc` → posts current narrative arc
- `!brief` → posts Briefing (see Spec B)
- `!history` → posts paginated event log as a thread

These persist. The Discord channel becomes a living log of the run.

---

## Health Aura

Composite score 0–100 computed every 30s:
```python
def compute_health(state) -> int:
    score = 100
    score -= min(30, replans * 10)          # replan rate
    score -= min(20, adv_triggers * 5)      # adversary friction
    score -= min(20, failed_verifies * 5)   # verify failure rate
    score -= min(20, retry_count * 3)       # retry overhead
    pace = done / elapsed_vs_expected       # pace vs deadline
    if pace < 0.7: score -= 10
    return max(0, min(100, score))
```

Surfaced as: colored dot + number on Bloomberg terminal (always visible), and as a field in the Discord cockpit embed.

---

## Files Changed

### New
- `notifications/event_bus.py` — `LiveEventBus` singleton
- `notifications/subprocess_feed.py` — `SubprocessFeed`
- `notifications/tunnel.py` — `TunnelManager`
- `notifications/tunnel_providers.py` — 4 providers
- `platform_core/ops/codenames.py` — run codename generator

### Modified
- `notifications/webdash.py` — full Bloomberg rewrite + SSE endpoint + health aura
- `notifications/dashboard.py` — tunnel URL pin, routes events through bus
- `notifications/cv2.py` — cockpit richness (Section + thumbnail header)
- `agents/executor_stream.py` — streaming mode for subprocess feed
- `agents/executor.py` — thread `feed` kwarg
- `platform_core/orchestration/execute_mixin.py` — create feed per attempt
- `platform_core/orchestration/run_phase_mixin.py` — tunnel start, codename, arc beats, self-reflection
- `state/task_schema.py` — `codename`, `tunnel_url`, `arc`, `health_score` fields
- `learning/experience.py` — `compare_run()` helper

### Tests
- `tests/test_event_bus.py`
- `tests/test_subprocess_feed.py`
- `tests/test_tunnel.py`
- `tests/test_bloomberg_webdash.py`
- `tests/test_codenames.py`
- `tests/test_health_aura.py`

---

## Success Criteria

- Running a subtask: Discord event ring shows tool calls within 1s of them happening
- Tunnel: URL posted to Discord within 10s of run start; survives process restart; falls back to next provider within 15s of failure
- Web dashboard: Bloomberg aesthetic, three-column layout, SSE feed with zero perceived lag, raw stdout expandable per subtask
- Run identity: every run has a codename visible on all surfaces
- Moments: at least one moment per 5 runs on average
- Self-reflection: posted within 30s of run completion, saved to Obsidian
- Health aura: visible on both surfaces, updates every 30s
- Wisdom trail: shows ≥1 relevant past lesson on web dashboard for any non-trivial goal
