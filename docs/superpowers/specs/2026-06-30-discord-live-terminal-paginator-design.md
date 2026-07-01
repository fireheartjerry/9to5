# Discord Live Terminal Paginator — Design

**Date:** 2026-06-30
**Status:** Approved (brainstorming) → ready for implementation plan
**Owner surface:** Nightclaw (Discord bot)

## 1. Problem

Today the raw, line-level terminal of 9to5's sub-processes is only visible on the
**web dashboard** (`localhost:8787`, `/api/raw?sid=`). Discord gets a *summarized*
step feed + the `console_hud` ANSI block, but no way to watch the live terminal of an
arbitrary sub-process. We want a **persistent, paginated "Live Terminal" surface in
Discord** — ◀ ▶ buttons (the Discord equivalent of the arrow-key paginators used by
Dank Memer et al.) that switch between the terminals of every running sub-process —
updating **very frequently** while staying **inside Discord's edit rate limits**.

## 2. Decisions (locked during brainstorming)

| # | Decision | Choice |
|---|----------|--------|
| Nav model | What ◀ ▶ navigate | **One page per sub-process** (lane) |
| Refresh | Liveness vs rate limits | **Adaptive + auto-backoff**: edit only the viewed page, only on content change, ≥1.2s floor while active, idle→5s heartbeat, 429→honor `Retry-After` + double the floor |
| Ownership | Message lifecycle | **One shared pinned message per run** + a 📷 **Snapshot** button (static ephemeral copy) |
| Page scope | Which processes | **Every layer**: `orchestrator`, `brain`, `browser`, `native`, and each Claude subtask `st-NNN` |
| Structure | Code architecture | **Approach A** — lane bus + persistent paginator view + dedicated edit loop |

## 3. Architecture (Approach A)

Three new, independently-testable units plus a small bus extension and five one-line
producer taps. Mirrors the proven `dashboard.py` manager/edit-loop discipline.

```
producers (emit_raw per lane)          bus (lanes)            Discord surface
────────────────────────────────       ───────────           ─────────────────────────
llm_io.py            → "brain"    ┐
run_loop/phase_mixin → "orchestr" ├──► LiveEventBus ──► TerminalSurface (manager)
browser_executor.py  → "browser"  │    + lane registry     · owns 1 pinned message/run
native_executor.py   → "native"   │    (ordered, ts,       · page idx / mode / freeze
execute_mixin (feed) → "st-NNN"   ┘     counts)            · adaptive edit loop (async)
                                                            · pure render via terminal_render
                                                                     ▲
                                                            TerminalView (persistent)
                                                            ◀ Prev · ⏸ Freeze · Raw ·
                                                            Next ▶ · 📷 Snapshot
```

### 3.1 Bus extension — `notifications/event_bus.py`
The bus already keys `emit_raw`/`raw_history` by an arbitrary string `sid`; a **lane is
just a well-known sid** (`"orchestrator"`, `"brain"`, `"browser"`, `"native"`, `"st-001"`).
Add lightweight lane bookkeeping:

- `_lanes: dict[str, LaneMeta]` — insertion-ordered (first-activity order), tracking
  `last_ts`, `line_count`, and a human `label` (optional).
- `emit_raw` updates the lane's `last_ts`/`line_count`.
- New `lanes() -> list[dict]` — ordered `[{id, label, last_ts, line_count, idle_s}]`,
  used by the paginator to know page order + which lane is active/idle.
- New optional `register_lane(sid, label)` — lets a producer set a friendly label
  before its first line (e.g. `st-002` → "authcache refactor"). No-op if unknown.

No change to existing `emit`/`raw_history`/SSE behavior. Ring buffers already bound
memory (1,000 raw lines/lane).

### 3.2 Pure renderer — `notifications/terminal_render.py`
`render(lane_id, lines, meta, *, page, page_count, mode, frozen, width=42) -> str`.
A **pure function** (no I/O, never raises) that returns the message body:

- Header: `🖥 LIVE TERMINAL   ◀ {page}/{page_count} ▶   {lane label} · {idle/running} · {elapsed}`.
- Body: last N lines that fit Discord's limits, inside a fenced block. Reuse the
  `console_hud` ANSI style for the summary mode; `raw` mode prints the raw stdout tail
  verbatim (ANSI-stripped, hard-truncated per line).
- Footer hint line: freeze/raw state, line count, "snapshot to keep".
- **Hard limits:** body ≤ ~1,900 chars (safe under the 2,000 content / 4,096 embed cap);
  per-line truncation; tail-only (newest lines win).

### 3.3 Manager — `notifications/terminal_surface.py`
`TerminalSurface` — sibling to `DiscordDashboard`. Owns the single pinned message and
the adaptive edit loop. One instance per run, started/stopped by the orchestrator with
the dashboard.

State (guarded by locks, like `DiscordDashboard`):
- `message_id`, `page_idx`, `mode` (`summary`|`raw`), `frozen` (bool)
- `_last_edit_ts`, `_edit_floor` (starts 1.2s, doubles on 429, decays back), `_last_body`
- `_send_lock` (serialize network), `_state_lock`

Behavior:
- `start()` — create + pin the message with `TerminalView`; kick the async edit loop.
- **Adaptive edit loop** (async task):
  1. Resolve the active lane from `bus.lanes()[page_idx]` (clamp if lanes changed).
  2. Render body via `terminal_render`.
  3. If `frozen` **or** body unchanged **or** `now - _last_edit_ts < _edit_floor` → skip.
  4. Else PATCH-edit the message; on `429` honor `Retry-After`, set `_edit_floor *= 2`
     (cap 10s); on `404` recreate once (mirror dashboard's `_recreated` guard); on
     success decay `_edit_floor` back toward 1.2s.
  5. Sleep a short base tick (~0.4s); the floor — not the tick — governs edit rate.
  - Idle lane (no new lines >5s) → the render shows a heartbeat; edits naturally stop
    because the body stops changing.
- Navigation hooks called by the view: `prev()`, `next()`, `toggle_raw()`,
  `toggle_freeze()`, `snapshot() -> str` (returns the current rendered body for the
  ephemeral reply). Each nav action requests an **immediate** (still floor-throttled)
  re-render so the UI feels responsive.
- `finalize()` — on run end, render a final static frame, disable the live loop, leave
  the message (a frozen record).

### 3.4 Persistent view — `notifications/views_terminal.py`
`TerminalView(discord.ui.View, timeout=None)` with stable `custom_id`s
(`term_prev`, `term_freeze`, `term_raw`, `term_next`, `term_snap`) so it survives
multi-hour runs **and** bot restarts. Registered in `notifications/bot/core.py`
alongside the other `bot.add_view(...)` calls.

- Button callbacks resolve the process-global `TerminalSurface` (via a small accessor,
  like the dashboard singleton) and call the matching nav hook, then
  `interaction.response.edit_message(...)` / ephemeral for snapshot.
- **Authorization:** nav buttons owner-gated via the existing `commands.isAuthorized`
  helper (consistent with `WorkSetupView`). Snapshot allowed for any viewer (read-only).
- If no active surface (run ended / bot restarted mid-gap), buttons reply ephemerally
  "No live run" instead of erroring.

### 3.5 Producer taps (five, one line each)
Each layer gets a best-effort `get_bus().emit_raw("<lane>", line)` (wrapped so a bus
hiccup never breaks the layer). Lanes:

| Lane | File | What it emits |
|------|------|---------------|
| `st-NNN` | `platform_core/orchestration/execute_mixin.py` | **Already tapped** via `SubprocessFeed` — no change |
| `brain` | `llm_io.py` | Ollama prompt/response boundaries + token/latency lines |
| `orchestrator` | `run_loop_mixin.py`, `run_phase_mixin.py` | phase transitions (plan/replan/execute/verify) |
| `browser` | `agents/browser_executor.py` | CDP actions / nav / screenshots (when `BROWSER_LAYER_ENABLED`) |
| `native` | `agents/native_executor.py` | UIA actions (when `NATIVE_LAYER_ENABLED`) |

Taps are **guarded and cheap** (a formatted string + one `deque.append` under a lock).
Disabled layers simply never produce a lane, so their page just doesn't appear.

## 4. Data flow

1. A layer does work → calls `emit_raw(lane, line)` → bus appends to the lane ring +
   updates lane meta.
2. `TerminalSurface`'s edit loop, once per floor window, reads `bus.lanes()` +
   `raw_history(active_lane)`, renders, and edits the pinned message **iff** changed.
3. Owner presses ◀/▶/Raw/Freeze → view callback mutates surface state → immediate
   throttled re-render.
4. 📷 Snapshot → view sends the current body as a private ephemeral message (static).
5. Run ends → `finalize()` freezes the surface.

## 5. Rate-limit safety (explicit)

- **Only the viewed page is ever edited** — N processes cost the same as 1.
- **Edit-on-change** — identical body ⇒ no request.
- **≥1.2s floor**, adaptive; **429 → `Retry-After` + doubled floor** (cap 10s), decays back.
- **Single shared message** — no per-viewer fan-out (snapshots are one-shot statics).
- Reuses `dashboard.py`'s `_send_lock` serialization + single-`404`-recreate guard so
  parallel workers can't storm the API.

## 6. Error handling

- Renderer is total (never raises; returns a minimal "terminal offline" frame on error),
  mirroring `console_hud`.
- Every producer tap is `try/except`-wrapped and best-effort.
- Edit loop swallows transient network errors, backs off on 429, recreates once on 404,
  and never lets an exception kill the loop.
- Bot-restart mid-run: persistent view re-binds; if the surface singleton is gone, the
  next run recreates it and stale buttons reply "No live run".

## 7. Testing

Pure/unit (no Discord, no network — pytest per `.claude/rules/tests.md`):
- `test_event_bus_lanes.py` — lane ordering, `last_ts`/`line_count`, `register_lane`,
  ring-buffer bounds, `lanes()` output shape.
- `test_terminal_render.py` — width/length caps, per-line truncation, tail selection,
  summary vs raw mode, frozen/idle headers, empty-lane + error → offline frame.
- `test_terminal_surface.py` — page clamp when lane set changes, edit-on-change skip,
  floor throttle, 429 backoff/decay math, freeze suppresses edits, snapshot returns
  current body. Discord client mocked.
- `test_views_terminal.py` — custom_id stability, owner-gating, "no live run" fallback.
- `test_terminal_taps.py` — each tap calls `emit_raw` with the right lane and is
  best-effort (bus raising doesn't propagate).

No live-Discord/e2e in the default lane (kept out per test rules).

## 8. Modularity budget

All new files target ≤300 lines (ideal). If `terminal_surface.py` approaches the limit,
split the pure render helpers into `terminal_render.py` (already separate) and keep the
manager thin. Add `@AI-MAP` headers to every new module; run `python tools/repo_map.py`
after.

## 9. Out of scope (YAGNI)

- Per-viewer independent navigation (rejected: 15-min ephemeral edit ceiling).
- Scrollback-within-page (2D nav) — tail-only for v1.
- Wiring browser/native beyond a basic action line (their deep telemetry stays on the web
  dashboard).
- Any change to model/effort routing, existing cockpit, or the web dashboard.

## 10. Files touched

**New:** `notifications/terminal_render.py`, `notifications/terminal_surface.py`,
`notifications/views_terminal.py`, plus 5 test modules.
**Edited (small):** `notifications/event_bus.py` (lane bookkeeping),
`notifications/bot/core.py` (register view), `llm_io.py`,
`platform_core/orchestration/run_loop_mixin.py`, `run_phase_mixin.py`,
`agents/browser_executor.py`, `agents/native_executor.py` (one tap each), and the
orchestrator start/stop path that owns `DiscordDashboard` (also start/stop
`TerminalSurface`).
**Docs:** update `docs/` observability doc + regenerate `AGENTS.md`.
