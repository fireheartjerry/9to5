# Discord Bot Elevation — State-of-the-Art Control Surface — Design

> **Status:** approved design (brainstorming output). Next: implementation plan.
> Builds directly on the shipped hardening branch (`commands.py` spine, `discord_bot.py`
> REST chokepoint, dashboard, `command_bot` gateway, `work_launcher`). Continues on the
> `feat/discord-work-hardening` branch.

## Objective

Elevate the 9TO5 Discord bot to a best-in-class, "enterprise / state-of-the-art" control
surface for driving autonomous runs — applying top-tier bot engineering and UX standards
to this bot's actual domain (controlling 9to5 runs), not generic community-bot features.
Six pillars, all in this cycle:

1. Slash-command suite + autocomplete (slash-first; `!` kept as alias)
2. Persistent interactive control panel (dashboard buttons that survive restarts)
3. Design system + branding + live presence
4. Observability (`/ping`, `/diagnostics`, `/metrics`, audit log)
5. Safety & robustness (cooldowns, confirm dialogs, pagination, global error UX, perms)
6. Multi-run lifecycle (`/runs`, `/run`, `/resume`)

**Decisions (locked):** everything (1–6) this cycle; **slash-first, keep `!` as alias**
(both share the `commands.py` spine, so the orchestrator's in-run `!` poller still works).

## Non-goals (YAGNI for a single-guild personal bot)

Sharding, i18n, a database (stay file-backed — matches project philosophy), premium tiers,
moderation/leveling/music. No new third-party deps (stdlib + `requests` + `discord.py 2.7.1`).

## Architecture (layering)

```
discord_bot.py   REST chokepoint + primitives (statusColor, progressBar, truncate,
                 _clampEmbed, _nowIso) + existing milestone embeds + blockedComponents   [shipped]
commands.py      pure '!'/logic spine: parseCommand/applyCommand/decide/isAuthorized/
                 isRunActive/resolveTargetTask + COMMAND_REGISTRY                          [shipped]
        ▲
branding.py(new) design system: BRAND_COLOR/VERSION, brandEmbed(); all NEW rich embeds
                 (help/status/plan/runs/run/diagnostics/metrics/ping/audit); control-panel
                 component-row builder + cp_* custom-id constants. Imports config + discord_bot.
audit.py(new)    file-backed who-did-what (state/audit.jsonl): record() / recent(). Pure.
metrics.py(new)  aggregate state/tasks/*.json → metrics dict. Pure.
views.py(new)    discord.py Views: ControlPanelView + BlockedView (persistent, timeout=None),
                 ConfirmView, Paginator, WorkModal/WorkSetupView (moved from command_bot).
slash.py(new)    registerSlashCommands(tree, client, started_at): every / command; thin —
                 delegates to commands spine / work_launcher / branding builders.
command_bot.py   slim gateway: client+tree, sync-once, add_view persistent views, presence
                 loop, '!' legacy via spine, global tree.error. (on_interaction removed —
                 persistent views + tree auto-route.)
work_launcher.py +resume: taskExists / buildResumeArgv / spawnResume (shared _spawnArgv)
health.py        refactor: collectHealth()->list[dict]; runHealthChecks() prints from it
state/task.py    +listRecent(n) summaries
dashboard.py     attach controlPanelRow() components to the pinned embed
orchestrator.py  poller records audit on applied commands
config.py        VERSION, BRAND_COLOR, BRAND_ICON_URL, COOLDOWN_*, PRESENCE_INTERVAL, AUDIT_*
```

No import cycles: `discord_bot` (leaf) ← `branding` ← {`views`, `slash`, `dashboard`,
`command_bot`}; `commands`/`audit`/`metrics`/`work_launcher` sit beside `branding` and are
imported by `views`/`slash`; nothing imports `views`/`slash`/`command_bot`.

## Pillar 1 — Slash-command suite + autocomplete

`slash.py` exposes `registerSlashCommands(tree, client, started_at)` adding (alongside the
existing `/work`):

- **Control** (mutating → owner-only + cooldown): `/abort` (confirm), `/pause`, `/resume`,
  `/approve`, `/reject`, `/skip subtask:<autocomplete>`, `/add title:<str>`, `/retry`.
- **Info** (read → open to all): `/status`, `/plan` (paginated), `/log`, `/help`, `/ping`,
  `/diagnostics`, `/metrics`, `/audit`.
- **Run**: `/runs` (paginated), `/run id:<autocomplete>`, `/resume id:<autocomplete>`.

Every control command body: `authorize` (read open; mutating requires `isAuthorized`) →
`interaction.response.defer(ephemeral=True)` → resolve task (`commands.resolveTargetTask`;
`NO_TASK` if none) → `audit.record(...)` for mutating → `commands.applyCommand(bus, state,
Command(name, arg))` → `followup.send`. Read commands render a **branding embed** rather
than raw text (interaction responses render embeds reliably). **No logic duplication** —
slash is a thin shell over the same spine `!` uses.

**Autocomplete:**
- `_subtaskAutocomplete(interaction, current)` → pending subtask ids of the current task
  (`st-00N — title`), filtered by `current`, max 25 `app_commands.Choice`.
- `_taskAutocomplete(interaction, current)` → recent task ids (`TaskState.listRecent`),
  `id8 — goal…`, filtered, max 25.

## Pillar 2 — Persistent interactive control panel

`branding.py` defines `CONTROL_PANEL_IDS = {"pause":"cp_pause","resume":"cp_resume",
"abort":"cp_abort","approve":"cp_approve","reject":"cp_reject","skip":"cp_skip"}` and
`controlPanelRow() -> list` (two action rows: Pause/Resume/Abort, Approve/Reject/Skip — ≤5
buttons/row).

`dashboard.py` attaches `controlPanelRow()` to the pinned embed on create and edits, so the
live dashboard has the buttons. `views.py.ControlPanelView(discord.ui.View, timeout=None)`
has six `@discord.ui.button(custom_id="cp_…")` callbacks; the gateway calls
`client.add_view(ControlPanelView())` on startup → **clicks are handled across bot restarts
and even though the orchestrator (a different process) created the message via REST**
(persistent views match by custom_id). Each callback: `defer(ephemeral)` → authorize
(owner) → destructive (`cp_abort`) routes through `ConfirmView` → `audit.record` →
`commands.applyCommand` → ephemeral followup. A button for an inapplicable state (e.g.
`cp_approve` with no pending gate) returns the spine's graceful message ("No gate pending").

The blocked-embed buttons (`sc_answer/sc_skip/sc_abort`, already emitted by
`discord_bot.blockedComponents()`) become `views.py.BlockedView(timeout=None)`, also
`add_view`'d. The old `command_bot.on_interaction` handler is **removed** (persistent views
auto-route).

## Pillar 3 — Design system + branding + presence

`branding.py`:
- `brandEmbed(title, *, description=None, color=None, fields=None, footer_extra=None) ->
  dict` — sets `author={"name": f"9TO5 v{VERSION}", "icon_url": BRAND_ICON_URL or omit}`,
  `color = color or BRAND_COLOR`, `_nowIso()` timestamp, and a footer
  `9TO5 v{VERSION} · up {uptime}` (uptime injected where available, else just version).
- `helpEmbed()` — categorized (Control / Info / Run) from `COMMAND_REGISTRY` + a small
  slash-only metadata table, so it can't go stale.

Gateway **presence loop**: every `PRESENCE_INTERVAL`s, read `commands.resolveTargetTask`;
set `change_presence(activity=Activity(type=watching, name="3/8 · executing"))` when active,
else `"idle"`. Runs as an `asyncio` task started in `on_ready`.

`config`: `VERSION="1.0.0"`, `BRAND_COLOR=0x5865F2`, `BRAND_ICON_URL=os.getenv(...,"")`.

## Pillar 4 — Observability

- `/ping` → `pingEmbed(latency_ms=round(client.latency*1000), uptime, VERSION)`.
- `/diagnostics` → `health.collectHealth()` (new) → `diagnosticsEmbed(checks)`; each check
  `{name, ok, detail, fix}`. `runHealthChecks()` reuses `collectHealth()`.
- `/metrics` → `metrics.compute()` (scans `STATE_DIR/*.json`): `total_runs`, `by_status`,
  `success_rate` (`(done+complete)/terminal`), `avg_duration_seconds`, `subtasks_total`,
  `subtasks_passed`. → `metricsEmbed(m)`.
- **Audit log** `audit.py`: `record(user_id, action, task_id, detail="")` appends a JSON
  line to `AUDIT_LOG_PATH = STATE_DIR.parent/"audit.jsonl"` with a local-ISO timestamp;
  rotates to `audit.jsonl.1` when over `AUDIT_MAX_BYTES`. `recent(n=20) -> list[dict]`.
  Recorded by the gateway (knows `interaction.user.id`) and the orchestrator poller (knows
  `author_id`) at every mutating command. `/audit` → `auditEmbed(recent(20))`.

## Pillar 5 — Safety & robustness

- **Cooldowns:** `@app_commands.checks.cooldown(COOLDOWN_RATE, COOLDOWN_PER,
  key=lambda i: i.user.id)` on mutating commands (`COOLDOWN_RATE=3`, `COOLDOWN_PER=10.0`).
- **ConfirmView** (`views.py`): ephemeral Confirm/Cancel, `timeout=30`; the caller awaits
  `view.wait()` then checks `view.value`. Gates `/abort` and the `cp_abort` button.
- **Paginator** (`views.py`): Prev/Next over a list of page embeds; bound to the invoking
  user; `timeout=120`; disables on timeout. Used by `/plan`, `/runs`, `/audit` when long.
- **Global error UX:** `tree.on_error` renders a friendly embed; `CommandOnCooldown` →
  "⏳ slow down, try again in Ns" ephemeral; everything else → "internal error (see logs)"
  + `LOG.exception`.
- **Permissions:** read commands open to all; mutating require `commands.isAuthorized`
  (owner). Enforced once via a `_requireOwner(interaction)` helper in `slash.py` and the
  view callbacks.

## Pillar 6 — Multi-run lifecycle

- `TaskState.listRecent(n=10) -> list[dict]` — summaries `{task_id, status, goal,
  done, total, started_at}` sorted by `started_at` desc (reads `STATE_DIR/*.json`).
- `/runs` → paginated `runsEmbed(summaries, page)` via `Paginator`.
- `/run id:<autocomplete>` → load + `runEmbed(state)` (status, progress, subtasks, PR,
  timings); friendly error if id unknown.
- `/resume id:<autocomplete>` → `_requireOwner` → block if `work_launcher.activeRun()` →
  `work_launcher.taskExists(id)` → `work_launcher.spawnResume(id)` (spawns
  `main.py --resume <id>` detached) → launch confirmation. `work_launcher` refactor:
  `_spawnArgv(argv) -> int` (the shared detached-Popen body); `spawn` and new
  `spawnResume(task_id)` both call it; `buildResumeArgv(task_id)`; `taskExists(task_id)`.

## Data flow (representative)

```
/abort → _requireOwner → defer(ephemeral) → ConfirmView → confirm
       → audit.record(user, "abort", task_id) → commands.applyCommand(bus,state,("abort",""))
       → followup ✅      # identical spine path as the cp_abort button and `!abort`

dashboard (orchestrator REST) embeds controlPanelRow() ── click ──> gateway ControlPanelView
       (persistent, add_view'd) ── same _requireOwner/audit/applyCommand path
```

## File map

| File | New? | Responsibility |
|------|------|----------------|
| `config.py` | modify | VERSION, BRAND_COLOR, BRAND_ICON_URL, COOLDOWN_RATE/PER, PRESENCE_INTERVAL, AUDIT_LOG_PATH/AUDIT_MAX_BYTES |
| `notifications/branding.py` | **new** | design system + all new rich embeds + controlPanelRow + cp_* ids |
| `notifications/audit.py` | **new** | file-backed audit log (record/recent + rotation) |
| `notifications/metrics.py` | **new** | aggregate task files → metrics dict |
| `notifications/views.py` | **new** | ControlPanelView/BlockedView (persistent), ConfirmView, Paginator, WorkModal/WorkSetupView |
| `notifications/slash.py` | **new** | registerSlashCommands(tree, client, started_at) — all / commands + autocomplete |
| `notifications/command_bot.py` | modify | slim gateway: sync-once, add_view, presence loop, `!` legacy, tree.error; remove on_interaction |
| `notifications/dashboard.py` | modify | attach controlPanelRow() components to the pinned embed |
| `notifications/work_launcher.py` | modify | resume: `_spawnArgv`, `spawnResume`, `buildResumeArgv`, `taskExists` |
| `orchestrator.py` | modify | poller records audit on applied commands |
| `health.py` | modify | `collectHealth() -> list[dict]`; `runHealthChecks()` prints from it |
| `state/task.py` | modify | `listRecent(n)` |
| `tests/test_branding.py` | **new** | embed builders valid + clamped; help lists all cmds; pagination math |
| `tests/test_metrics.py` | **new** | aggregation over synthetic task files |
| `tests/test_audit.py` | **new** | append/read/rotation |
| `tests/test_health_collect.py` | **new** | collectHealth shape |
| `tests/test_work_launcher.py` | modify | resume argv + taskExists + spawnResume |
| `tests/test_task_listrecent.py` | **new** | listRecent sorting/shape |

## Error handling (summary)

- Slash: defer first; `tree.on_error` is the safety net; cooldown special-cased.
- Views: per-interaction owner re-check; ConfirmView/Paginator timeouts disable controls.
- Audit/metrics file IO: best-effort, never raise into a command; logged.
- Resume spawn failure → friendly error, logged (same pattern as `/work`).
- Branding builders never raise on missing fields (defensive `.get`); all sends pass through
  `discord._clampEmbed` so no embed can exceed Discord limits.

## Testing

Pure modules → `unittest` (run `venv\Scripts\python -m unittest discover -s tests`):
- `test_branding`: every builder returns a dict with a title and a `BRAND_COLOR`/status color;
  `helpEmbed` mentions every `COMMAND_REGISTRY` command; `planEmbed`/`runsEmbed` page math
  (`total_pages`) correct; built embeds pass `discord._clampEmbed` unchanged in field count
  within limits.
- `test_metrics`: synthetic task JSONs in a temp `STATE_DIR` (monkeypatch) → exact aggregates.
- `test_audit`: `record` then `recent` returns the written entries in order; rotation past
  `AUDIT_MAX_BYTES` creates `.1` and keeps `recent` working.
- `test_health_collect`: `collectHealth()` returns a list of `{name, ok, detail, fix}`.
- `test_work_launcher` (extend): `buildResumeArgv` has `--resume <id>`; `taskExists`;
  `spawnResume` calls Popen with resume argv (mocked).
- `test_task_listrecent`: returns summaries sorted by `started_at` desc with `done/total`.

discord.py layers (`slash.py`, `views.py`, `command_bot.py`): `py_compile` + import-smoke +
a live manual checklist:
- slash sync logs N commands; `/help` renders categorized.
- dashboard control-panel buttons work; **still work after restarting the gateway bot**
  (persistent views).
- `/skip` and `/run`/`/resume` autocomplete populate.
- `/abort` shows a confirm dialog; cancel aborts nothing.
- `/plan`/`/runs` paginate.
- presence shows the live run; `/ping`/`/diagnostics`/`/metrics`/`/audit` render.
- a non-owner can run read commands but is refused mutating ones.

## Sequencing (build order; each commit green & reviewable)

1. `config.py` constants.
2. `audit.py` + `tests/test_audit.py`.
3. `metrics.py` + `tests/test_metrics.py`.
4. `state/task.py` `listRecent` + `tests/test_task_listrecent.py`.
5. `health.py` `collectHealth` refactor + `tests/test_health_collect.py`.
6. `work_launcher.py` resume (`_spawnArgv`/`spawnResume`/`buildResumeArgv`/`taskExists`) +
   extend `tests/test_work_launcher.py`.
7. `branding.py` (design system + all embeds + controlPanelRow) + `tests/test_branding.py`.
8. `views.py` (persistent views + Confirm + Paginator + moved Work modal/view).
9. `slash.py` (all slash commands + autocomplete) — import-smoke.
10. `command_bot.py` rewire (sync-once, add_view, presence loop, `!` legacy, tree.error,
    remove on_interaction).
11. `dashboard.py` attach controlPanelRow components.
12. `orchestrator.py` poller audit.
13. Final verification: full unittest suite + import-smoke + `--health` + live checklist.
