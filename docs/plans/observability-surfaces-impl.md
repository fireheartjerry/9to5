# Observability & Surfaces Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the 9to5 "surface layer" — a LiveEventBus nervous system, real-time subprocess feed, hyper-robust tunnel, a Bloomberg-terminal web dashboard with SSE, run codenames, Moments, self-reflection, narrative arc, proactive narration, comparative intelligence, attention modes, Discord surfaces, and a Health Aura.

**Architecture:** One process-global `LiveEventBus` singleton fans every event out to SSE browser tabs and a throttled Discord layer. Subprocess stdout is tapped line-by-line by a `SubprocessFeed` that emits structured tool events + heartbeats. A supervised `TunnelManager` exposes the local webdash publicly with provider failover. Surface "voice/story" logic (arc, narration, moments, reflection) lives in small dedicated `notifications/*` helper modules wired additively into the orchestration mixins. Health is a pure composite-score function surfaced on both web + Discord.

**Tech Stack:** Python stdlib only (`http.server`, `threading`, `queue`, `subprocess`, `urllib`, `json`, `dataclasses`, `collections.deque`). No new third-party deps. Tests via pytest (never bare unittest — local `.env` has live creds). All network mocked.

**Source of truth:** `docs/superpowers/specs/2026-06-28-observability-surfaces-design.md`.

**Path corrections vs spec (documented decisions):**
- Spec says `learning/experience.py`; the real module is `memory/experience.py` (a re-export facade). `compare_run()` is added to `memory/experience_runs.py` and re-exported through the facade.
- Spec lists `test_health_aura.py` but no `compute_health` module in "Files Changed". We add a small new module `notifications/health_aura.py` to host `compute_health()` / `aura_color()` (a dedicated, testable home — consistent with the codebase's small-module convention).
- Surface "voice" logic that would push `run_phase_mixin.py` (355 lines) / `execute_mixin.py` (453 lines) over the 450-line hard ceiling is extracted into new small modules: `notifications/run_arc.py`, `notifications/narration.py`, `notifications/reflection_post.py`. The mixins gain only thin additive call-sites. This honors the spec behavior while satisfying the hard modularity gate.

---

## File Structure

### New modules
| File | Responsibility | ~lines |
|---|---|---|
| `notifications/event_bus.py` | `LiveEventBus` singleton, `Event`/`RawLine` dataclasses, ring buffers, SSE pub/sub, history | ~190 |
| `notifications/subprocess_feed.py` | `SubprocessFeed`: parse Claude JSONL stdout → tool events; 30s heartbeat thread | ~160 |
| `notifications/tunnel_providers.py` | `TunnelProvider` base + Cloudflared/Ngrok/Bore/Localtunnel providers | ~280 |
| `notifications/tunnel.py` | `TunnelManager`: watchdog, HTTP probe, restart backoff, provider demotion, URL validation, resume | ~290 |
| `notifications/health_aura.py` | `compute_health(state)->int`, `aura_color(score)->str` | ~70 |
| `notifications/run_arc.py` | arc beat append + render (`append_beat`, `render_arc`, `beat_*` templates) | ~110 |
| `notifications/narration.py` | `Narrator` (60s-rate-limited proactive narration), moment detection+expression, attention-mode detection | ~230 |
| `notifications/reflection_post.py` | self-reflection generation (ollama) + save (state/Obsidian) + Discord post + comparative footer | ~120 |
| `platform_core/ops/codenames.py` | `generate()->str` (200 adj × 200 noun) | ~60 |

### Modified
| File | Change | Shared w/ Spec B? |
|---|---|---|
| `notifications/webdash.py` | Full Bloomberg `_PAGE` rewrite + `/api/events` SSE + health aura + wisdom/intelligence sections | no |
| `notifications/dashboard.py` | route `event()` through bus; `set_tunnel_url()` tunnel pin; health field | no |
| `notifications/cv2.py` | cockpit: codename in header, health field (ADDITIVE) | **yes** |
| `agents/executor_stream.py` | `runSubprocess(..., feed=None)` line-by-line streaming path | no |
| `agents/executor.py` | `runClaude(..., feed=None)` thread-through | no |
| `platform_core/orchestration/execute_mixin.py` | create `SubprocessFeed` per attempt; emit moments (ADDITIVE) | **yes** |
| `platform_core/orchestration/run_phase_mixin.py` | tunnel start; arc beats; self-reflection; narration (ADDITIVE) | **yes** |
| `state/task_schema.py` | new meta fields `codename`, `tunnel_url`, `arc`, `health_score` (ADDITIVE) | **yes** |
| `memory/experience_runs.py` + `memory/experience.py` | `compare_run(task_id)->dict` + re-export | no |

### Tests
`tests/test_event_bus.py`, `tests/test_subprocess_feed.py`, `tests/test_tunnel.py`, `tests/test_bloomberg_webdash.py`, `tests/test_codenames.py`, `tests/test_health_aura.py` (+ small focused tests: `test_compare_run.py`, `test_run_arc.py`, `test_narration.py`, `test_reflection_post.py`, `test_dashboard_bus.py`, `test_discord_surfaces.py`).

**Shared-file rule:** all edits to `task_schema.py`, `run_phase_mixin.py`, `execute_mixin.py`, `cv2.py` are strictly ADDITIVE (add fields/methods/call-sites; never rename or reflow unrelated code) to keep the eventual merge with `feat/intelligence-control` clean.

---

## Task 1: Run codenames

**Files:**
- Create: `platform_core/ops/codenames.py`
- Test: `tests/test_codenames.py`

- [ ] **Step 1: Write failing test**
```python
import re
from platform_core.ops import codenames

def test_generate_shape():
    name = codenames.generate()
    assert re.fullmatch(r"[A-Z]+_[A-Z]+", name), name

def test_generate_varies():
    seen = {codenames.generate() for _ in range(200)}
    assert len(seen) > 20

def test_word_list_sizes():
    assert len(codenames.ADJECTIVES) >= 200
    assert len(codenames.NOUNS) >= 200
```

- [ ] **Step 2: Run, expect fail** — `python -m pytest tests/test_codenames.py -q`
- [ ] **Step 3: Implement** `platform_core/ops/codenames.py` with `@AI-MAP v1` header, `from __future__ import annotations`, `ADJECTIVES`/`NOUNS` lists (≥200 each, ALL-CAPS single words) and `generate() -> str` returning `f"{random.choice(ADJECTIVES)}_{random.choice(NOUNS)}"`.
- [ ] **Step 4: Run, expect pass** — `python tools/dev.py check platform_core/ops/codenames.py`
- [ ] **Step 5: Commit** — `feat(codenames): run codename generator`

---

## Task 2: TaskState codename + surface meta fields

**Files:** Modify `state/task_schema.py` (the `meta` dict in `create()`, ADDITIVE only)

- [ ] **Step 1:** In `TaskState.create()` add to `meta` after `"discovery_report": None,`:
```python
                "codename": _gen_codename(),
                "tunnel_url": None,
                "arc": [],
                "health_score": 100,
```
with module-level helper:
```python
def _gen_codename() -> str:
    try:
        from platform_core.ops import codenames
        return codenames.generate()
    except Exception:  # noqa: BLE001
        return "RUN"
```

- [ ] **Step 2: Test** — extend `tests/test_codenames.py` asserting `TaskState.create(...).meta` has codename matching `[A-Z]+_[A-Z]+`, `arc==[]`, `tunnel_url is None`, `health_score==100`.
- [ ] **Step 3: Run** — `python -m pytest tests/test_codenames.py -q` → PASS
- [ ] **Step 4: Commit** — `feat(state): codename/tunnel_url/arc/health_score meta fields`

---

## Task 3: LiveEventBus

**Files:** Create `notifications/event_bus.py`; Test `tests/test_event_bus.py`

Interface: `Event(kind,sid,text,data,ts)` + `to_dict()` (adds wall-clock `at` HH:MM:SS); `RawLine(sid,line,ts)`; `LiveEventBus` with `emit_raw`, `emit`, `subscribe_sse`->Queue, `unsubscribe_sse`, `history(sid,last_n)`, `raw_history(sid,last_n)`, `sse_subscriber_count`, `set_discord_feed`; module `get_bus()` singleton + `reset_bus()` test hook. Rings: `_raw` maxlen 10_000, `_structured` 2_000, `_per_sid` dict of maxlen-1_000 deques. Lock-guarded. SSE fan-out `put_nowait`, drop on full.

- [ ] **Step 1: Write failing test** (see plan body): emit/history, raw per-sid ring, sse subscribe receives, history filter by sid, singleton+reset, full-queue-never-blocks.
- [ ] **Step 2: Run, expect fail** — `python -m pytest tests/test_event_bus.py -q`
- [ ] **Step 3: Implement** `notifications/event_bus.py` (`@AI-MAP v1`). `emit`/`emit_raw` ≤25 lines; SSE put `try/except queue.Full: pass`.
- [ ] **Step 4: Run, expect pass** — `python tools/dev.py check notifications/event_bus.py`
- [ ] **Step 5: Commit** — `feat(event-bus): LiveEventBus singleton nervous system`

---

## Task 4: Health Aura

**Files:** Create `notifications/health_aura.py`; Test `tests/test_health_aura.py`

`compute_health(state)->int` per spec formula (replans, adversary, failed verifies, retry count, pace<0.7); `aura_color(score)->str` green≥80 / amber 50-79 / red<50. Pure, never raises.

- [ ] **Step 1: Write failing test**: perfect run=100; 4 replans=70; advs5+1 failed verify=75; clamped to 0; colors 91→#00d4aa, 60→#ff9f00, 10→#ff4444.
- [ ] **Step 2: Run, expect fail** — `python -m pytest tests/test_health_aura.py -q`
- [ ] **Step 3: Implement** per spec formula; pace block wrapped in try/except.
- [ ] **Step 4: Run, expect pass** — `python tools/dev.py check notifications/health_aura.py`
- [ ] **Step 5: Commit** — `feat(health): composite health aura score`

---

## Task 5: SubprocessFeed

**Files:** Create `notifications/subprocess_feed.py`; Test `tests/test_subprocess_feed.py`; Depends T3

`SubprocessFeed(bus, sid, started_at, *, heartbeat=True)`: `consume(line)` stores raw + parses Claude JSONL (`assistant.message.content[].tool_use` OR flat `tool_use`) → tool Event per spec emoji table (Edit/Write/Bash[:70]/Read/Grep/Glob/Agent[:60]/other). Non-JSON/unknown → raw only. `stop()` joins heartbeat thread. 30s heartbeat emits `Event(kind="heartbeat", text="⏱ <sid> · <elapsed>s · still running · <N> tool calls so far")`. Private `_beat_once()` for direct test.

- [ ] **Step 1: Write failing test**: edit event, bash truncated, non-json raw only, unknown generic, heartbeat via `_beat_once`.
- [ ] **Step 2: Run, expect fail**
- [ ] **Step 3: Implement** (helpers `_parse`, `_tool_event`, `_beat_once`; daemon thread + stop Event). Functions ≤25 lines.
- [ ] **Step 4: Run, expect pass** — `python tools/dev.py check notifications/subprocess_feed.py`
- [ ] **Step 5: Commit** — `feat(feed): SubprocessFeed real-time stdout tap`

---

## Task 6: Executor streaming wiring

**Files:** Modify `agents/executor_stream.py`, `agents/executor.py`, `platform_core/orchestration/execute_mixin.py` (ADDITIVE); Depends T3,T5

- [ ] **Step 1:** `runSubprocess(..., feed=None)`. `feed is None` → unchanged `communicate()`. `feed` set → stdin write+close, `for line in proc.stdout: out_lines.append(line); feed.consume(line.rstrip())`, `err=proc.stderr.read()`, timeout-kill via `threading.Timer(timeout,_killProcessTree,[proc.pid])`. Extract `_drainStreaming(...)` helper to stay ≤70 lines. Then existing `_parseEnvelope` path.
- [ ] **Step 2:** `runClaude(..., feed=None)` → `run_kw["feed"]=feed`.
- [ ] **Step 3:** `_runOneAttempt` builds `feed=SubprocessFeed(get_bus(), sid, time.monotonic())`, passes to `hands(...)`, `feed.stop()` in finally. Ensure browser executor tolerates `feed=None` kwarg.
- [ ] **Step 4: Test** — extend `tests/test_subprocess_feed.py`: fake `Popen` whose `stdout` yields JSONL lines; assert `feed.consume` saw them and `out` == joined.
- [ ] **Step 5: Run** — `python tools/dev.py check agents/executor_stream.py agents/executor.py platform_core/orchestration/execute_mixin.py`
- [ ] **Step 6: Commit** — `feat(executor): line-by-line streaming feed (opt-in, zero regression)`

---

## Task 7: Tunnel providers

**Files:** Create `notifications/tunnel_providers.py`; tests in `tests/test_tunnel.py`

`TunnelProvider` base (`name`, `available`, `ensure_available`, `start(port)`, `parse_url(line)`, `probe(url,timeout)`); Cloudflared (PATH→`~/.cloudflared`→download latest), Ngrok (skip w/o `NGROK_AUTH_TOKEN`), Bore (bore.pub download), Localtunnel (`npx lt`, skip if node absent); `default_providers()` priority order. parse_url regexes per provider; probe via `urllib.request`, True if status<500. `_download_binary(url,dest)` helper. No network at import.

- [ ] **Step 1: Write failing tests** (`-k provider`): cloudflared/bore parse_url, ngrok skipped w/o token, default order, probe non-5xx (mock urlopen).
- [ ] **Step 2: Run, expect fail** — `python -m pytest tests/test_tunnel.py -q -k provider`
- [ ] **Step 3: Implement** (`@AI-MAP v1`). Functions ≤25 lines. No network at import.
- [ ] **Step 4: Run, expect pass** — `python tools/dev.py check notifications/tunnel_providers.py`
- [ ] **Step 5: Commit** — `feat(tunnel): provider implementations`

---

## Task 8: TunnelManager

**Files:** Create `notifications/tunnel.py`; Test `tests/test_tunnel.py` (manager); Depends T7

`TunnelManager(providers=None,*,state=None)`: `start(port)` non-blocking, `stop`, `on_url(cb)`, props `url`/`provider_name`/`is_alive`. Supervisor: poll 5s, probe 20s, backoff 1→2→4→8→15 (reset after 5min clean), 3 consec fails → demote+advance (re-qualify 5min), URL validated before `on_url`, persist `state.meta["tunnel_url"]` on change. Resume: live saved `tunnel_url` → reuse, fire `on_url`, no spawn. Timing constants are class attrs (tests set to 0). Decompose `_supervise/_launch_current/_demote/_validate_and_announce/_reader_thread`.

- [ ] **Step 1: Write failing tests** (`-k manager`, FAKE providers): start fires on_url; demotes after failures; resume reuses saved url; url not posted until valid; stop is clean. No real net/binaries.
- [ ] **Step 2: Run, expect fail** — `python -m pytest tests/test_tunnel.py -q -k manager`
- [ ] **Step 3: Implement** (`@AI-MAP v1`). Functions ≤70 (aim ≤25). `threading.Event` stop, daemon threads.
- [ ] **Step 4: Run, expect pass** — `python tools/dev.py check notifications/tunnel.py`
- [ ] **Step 5: Commit** — `feat(tunnel): supervised TunnelManager with failover + resume`

---

## Task 9: compare_run

**Files:** Modify `memory/experience_runs.py` (+facade re-export); Test `tests/test_compare_run.py`

`compare_run(task_id, db_path=None)->dict` — this run vs rolling avg of prior runs (pace/innovation/adversary/replans) as display strings + `raw` numeric deltas. Defensive (no div-by-zero, missing cols tolerated). Never raises.

- [ ] **Step 1: Write failing test** (temp sqlite, `init`, `record_run` rows, `compare_run`); no-history path returns `n/a`-ish without raising.
- [ ] **Step 2: Run, expect fail**
- [ ] **Step 3: Implement** + re-export in `memory/experience.py` `__all__`.
- [ ] **Step 4: Run, expect pass** — `python tools/dev.py check memory/experience_runs.py`
- [ ] **Step 5: Commit** — `feat(experience): compare_run rolling-average deltas`

---

## Task 10: Run narrative arc

**Files:** Create `notifications/run_arc.py`; Test `tests/test_run_arc.py`

`append_beat(state,text)`, `render_arc(state)->str`, `beat_discovery(n,theme)`, `beat_architect(n)`, `beat_first_verify()`, `beat_replan(reason)`, `beat_complete(status,done,total,elapsed)` per spec templates. `append_beat` tolerates missing `arc` key.

- [ ] **Step 1: Write failing test**: two beats render in order; templates produce spec strings.
- [ ] **Step 2: Run, expect fail**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run, expect pass** — `python tools/dev.py check notifications/run_arc.py`
- [ ] **Step 5: Commit** — `feat(arc): run narrative arc beats`

---

## Task 11: Narration + Moments + Attention modes

**Files:** Create `notifications/narration.py`; Test `tests/test_narration.py`

`Narrator(min_interval=60,clock=...)` with injectable `_sink` — `narrate(text,role,force)` rate-limited 1/min. `MomentDetector` (adversary_offplan, scope_expanded, redemption, perfect_run). `emit_moment(bus,sid,text)` → bus moment event + Cast channel post. `detect_mode(bus)` → "present" if sse subs>0 else "away". Never raises.

- [ ] **Step 1: Write failing test**: rate-limit (clock-injected), perfect_run moment, detect_mode.
- [ ] **Step 2: Run, expect fail**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run, expect pass** — `python tools/dev.py check notifications/narration.py`
- [ ] **Step 5: Commit** — `feat(narration): proactive narrator, moments, attention modes`

---

## Task 12: Self-reflection post

**Files:** Create `notifications/reflection_post.py`; Test `tests/test_reflection_post.py`

`write_reflection(state,*,chat,comparative=None,obs=None)->Optional[str]` — builds codename-aware spec prompt seed, generates ≤100-word first-person paragraph via `chat`, saves `state/tasks/<task_id>/reflection.md`, Obsidian note, returns text. `post_reflection(state,text,comparative=None)` Discord post `CODENAME — ...` + comparative footer. Never raises.

- [ ] **Step 1: Write failing test**: fake `chat` returns canned paragraph; tmp STATE dir; assert file written + text; junk/None chat never raises.
- [ ] **Step 2: Run, expect fail**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run, expect pass** — `python tools/dev.py check notifications/reflection_post.py`
- [ ] **Step 5: Commit** — `feat(reflection): self-reflection post + obsidian + comparative footer`

---

## Task 13: Bloomberg web dashboard + SSE + health aura

**Files:** Modify `notifications/webdash.py` (+ maybe `notifications/webdash_page.py` if size needs it); Test `tests/test_bloomberg_webdash.py`; Depends T3,T4,T9

- `_snapshot` gains `codename`, `tunnel_url`, `health`(+color), `arc`, `wisdom_trail`(top-3 reflections keyword-matched to goal), `intelligence_curve`(SIE best-effort, [] if NA), `comparative`(compare_run).
- New routes: `/api/events` SSE (`text/event-stream`, subscribe bus, stream `data: <json>\n\n`, unsubscribe on disconnect); `/api/raw?sid=` → last 500 raw lines JSON. Keep `/api/state` poll fallback + control token CSRF guard.
- `_PAGE` Bloomberg rewrite: true black, amber labels `#ff9f00`, green live `#00d4aa`, red `#ff4444`, 1px `#222`, monospace 13px, uppercase headers, 3-col fixed grid, bottom INTELLIGENCE CURVE bar; JS `EventSource('/api/events')` live append + filter bar + search + per-subtask EXPAND RAW STDOUT + auto-scroll lock; health aura dot+number top-right.
- Extract payload builders `_events_payload`, `_raw_payload(sid)` into ≤25-line helpers.

- [ ] **Step 1: Write failing test**: `_PAGE` contains Bloomberg tokens (#000000,#ff9f00,#00d4aa,EventSource,ui-monospace,EXPAND RAW STDOUT,INTELLIGENCE CURVE); `_raw_payload` reads bus; `_snapshot` has surface keys.
- [ ] **Step 2: Run, expect fail** — `python -m pytest tests/test_bloomberg_webdash.py -q`
- [ ] **Step 3: Implement**. If `_PAGE` pushes file >450 lines, move to `notifications/webdash_page.py` and import. Preserve `startWebDashboard`/`stopWebDashboard` + token guard.
- [ ] **Step 4: Run, expect pass** — `python tools/dev.py check notifications/webdash.py` + `python -m pytest tests/test_webdash_control.py -q` (no regression).
- [ ] **Step 5: Commit** — `feat(webdash): Bloomberg terminal rewrite with SSE + health aura`

---

## Task 14: Dashboard bus routing + tunnel pin + cockpit richness

**Files:** Modify `notifications/dashboard.py`, `notifications/cv2.py` (ADDITIVE); Test `tests/test_dashboard_bus.py`; Depends T3,T8

- [ ] **Step 1:** `DiscordDashboard.event()` also `get_bus().emit(Event(kind="narration",sid="system",text=text))` (try/except). Add `set_tunnel_url(url)` — second pinned `🖥 Live Dashboard → <url>`, gated, never raises. Add `Health` field to `_embed`.
- [ ] **Step 2:** `cv2.buildCockpit` header → `9TO5 · {codename} · {phase}` when `m.get("codename")`; add `Health {score}` token. ADDITIVE.
- [ ] **Step 3: Test** `tests/test_dashboard_bus.py` (DISCORD_DASHBOARD=False): event emits bus event; cockpit flattened text contains codename + "Health".
- [ ] **Step 4: Run** — `python tools/dev.py check notifications/dashboard.py notifications/cv2.py` + `python -m pytest tests/test_cv2.py tests/test_dashboard.py -q`.
- [ ] **Step 5: Commit** — `feat(dashboard): bus routing, tunnel pin, codename+health in cockpit`

---

## Task 15: Orchestration wiring

**Files:** Modify `run_phase_mixin.py`, `execute_mixin.py` (ADDITIVE call-sites); Depends T8,T9,T10,T11,T12,T14

- `_runPreamble`: start `TunnelManager(state=state)`, `on_url(dashboard.set_tunnel_url)`, `start(port)` (try/except).
- `_freshRunPhase`: after discovery → `append_beat(beat_discovery)` + narrate; after architect → `append_beat(beat_architect)`.
- teardown/`_phase4PrComplete`: tunnel `stop()`; `write_reflection(chat=self._ollamaChat, comparative=compare_run(...))` + `post_reflection`; `append_beat(beat_complete)`; final narration.
- `execute_mixin`: first verify pass → `beat_first_verify` once; replan → `beat_replan`; moments (redemption pass-after-2-fails; adversary-offplan) via `emit_moment` + narrate. Shared `self._narrator` (lazy).
- Extract `_postReflection(state,dashboard)` helper if a host function would exceed 70 lines.

- [ ] **Step 1:** Add lazy `self._narrator`, `self._tunnel=None`. Insert additive try/except call-sites.
- [ ] **Step 2: Test** `tests/test_orchestration_surfaces.py` (mock discord/ollama/tunnel): perfect run appends `beat_complete` + emits moment.
- [ ] **Step 3: Run** — `python tools/dev.py check platform_core/orchestration/run_phase_mixin.py platform_core/orchestration/execute_mixin.py`
- [ ] **Step 4:** `python tools/size_audit.py` → resolve must_split (additive split into a new mixin module if needed).
- [ ] **Step 5: Commit** — `feat(orchestration): wire tunnel, arc, narration, reflection, moments`

---

## Task 16: Discord on-demand surfaces

**Files:** Modify command dispatcher (inspect `notifications/commands.py` / gateway cog); Test `tests/test_discord_surfaces.py`; Depends T3,T10

Add NON-ephemeral handlers: `!logs [sid]` (last 100 raw as code block), `!stdout [sid]` (last 500 as thread), `!arc` (`render_arc`), `!history` (paginated `bus.history` thread). `!brief` is Spec B — leave a stub comment, do not implement.

- [ ] **Step 1: Inspect** dispatcher; find additive insertion point.
- [ ] **Step 2: Implement** handlers calling bus + run_arc.
- [ ] **Step 3: Test** call handlers directly with stub poster; assert bus pull + code-block/thread payload. No network.
- [ ] **Step 4: Run** — `python tools/dev.py check <changed files>`
- [ ] **Step 5: Commit** — `feat(discord): on-demand logs/stdout/arc/history surfaces`

---

## Task 17: Finalization

- [ ] **Step 1:** `python tools/repo_map.py` (regenerate AGENTS.md).
- [ ] **Step 2:** `python tools/size_audit.py` → zero must_split.
- [ ] **Step 3:** `python tools/dev.py fast` (broad pytest). Triage failures to changed code.
- [ ] **Step 4:** Update closest human docs (`docs/ARCHITECTURE.md`, `docs/STATE.md`) for surfaces + new meta fields.
- [ ] **Step 5: Commit** — `chore(observability): repo-map, size-audit, docs sync`

---

## Success Criteria → verification
- Tool calls <1s: `SubprocessFeed.consume` synchronous → bus → SSE (T5,T13).
- Tunnel ≤10s/restart/failover: `TunnelManager` (T8).
- Bloomberg + SSE + raw expand: T13.
- Codename on all surfaces: T1,T2,T14.
- Moments ≥1/5 runs: T11/T15 detectors.
- Self-reflection ≤30s + Obsidian: T12/T15.
- Health aura both surfaces, 30s: T4,T13,T14.
- Wisdom trail ≥1 lesson: T13 `_snapshot.wisdom_trail`.

## Self-review
- Every spec section maps to a task (bus→T3, feed→T5/6, tunnel→T7/8, Bloomberg→T13, codenames→T1/2, moments→T11/15, reflection→T12/15, arc→T10/15, narration→T11/15, comparative→T9/15, attention→T11, discord surfaces→T16, health→T4/13/14).
- Type consistency: `Event(kind,sid,text,data,ts)`, `get_bus()`, `SubprocessFeed(bus,sid,started_at)`, `TunnelManager.on_url`, `compute_health(state)`, `compare_run(task_id)`, `append_beat/render_arc`, `Narrator.narrate`, `emit_moment(bus,sid,text)` consistent across tasks.
- All network mocked in tests.
