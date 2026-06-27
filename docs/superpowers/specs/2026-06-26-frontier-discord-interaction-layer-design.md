# Frontier Discord Interaction Layer — Design

**Date:** 2026-06-26
**Status:** Approved (design); pending implementation plan
**Scope:** Pure Discord frontend / UI for the Nightclaw bot surface. No AI image generation, no orchestration changes beyond a possible small ControlBus command.

## Background

The Nightclaw Discord surface already uses a large set of modern Discord
capabilities: a Components-V2 (CV2) live cockpit, modals, select menus (in setup
flows), slash commands with autocomplete, persistent button Views, native Polls,
Scheduled Events, threads/forum, webhook personas ("The Cast"), AutoMod, and
super-reaction approvals.

This work pushes three **untapped or under-used** frontier Discord interaction
features. It deliberately excludes AI-generated imagery (a separate earlier
direction that was dropped): the goal is richer *native Discord interactivity*,
not generated graphics.

## Goals

1. Add **context-menu (right-click) commands** — a surface the bot does not use at all today.
2. **Enrich the CV2 cockpit** with structural components (Section + thumbnail, polished separators, optional File component).
3. Add **live interactive control via select menus** embedded in the cockpit (jump/skip a subtask, change effort, switch control mode).

## Non-goals

- No AI image generation / asset library.
- No new Pillow card surfaces.
- No redesign of the existing embed/cockpit visual theme.
- No change to orchestration/verification logic beyond (possibly) one new ControlBus command for mid-run effort/mode changes.

## Existing patterns this builds on

- **Persistent Views** — fixed `custom_id`, registered via `bot.add_view` in `setup_hook`; survive restarts and cross-process messages (e.g. `views.ControlPanelView` with `cp_*` ids).
- **DynamicItem** — regex `custom_id`, stateless, registered via `bot.add_dynamic_items`; e.g. `bot/ui/dynamic.py` `SubtaskButton` with grammar `nc:st:<action>:<sid>`.
- **Pure routers on the `commands` spine** — logic is a pure function over `commands` + `ControlBus`, unit-testable without a gateway; the gateway callback is a thin async wrapper (e.g. `applySubtaskAction`).
- **Dual transport** — the cockpit is built once in `cv2.py` (raw component dicts for the loop-less orchestrator via `discord_bot.createComponentsV2` / `editComponentsV2Result`) AND rendered by the gateway as a `discord.ui.LayoutView` (`bot/ui`). Any new component must render in **both**.
- **Owner-gating + audit** — `commands.isAuthorized(user_id)` + `audit.record(...)` on every mutating action.

## Pillar A — Context-menu commands

**New file:** `notifications/bot/cogs/context_cog.py`

Three `@app_commands.context_menu` **message** commands (right-click a message → Apps):

1. **"Start run from this"** — uses the message content as a goal; opens the existing `views.WorkSetupView` (reuses `work_launcher`). Owner-gated.
2. **"Ask about the run"** — sends the message text as a question into the `/ask` war-room (reuses the `ask` path).
3. **"Abort current run"** — owner-gated; uses the existing `confirmDestructive` ephemeral confirm, then routes to `ControlBus.requestAbort()`.

**Logic placement:** pure router helpers added to the `commands` spine (consistent
with the existing `applyCommand` / `applySubtaskAction` routers) so each action is
testable without a gateway. The cog callbacks are thin async wrappers that call the
router and reply ephemerally.

**Registration:** context-menu commands are added to the command tree in the cog's
`__init__` / `cog_load` and synced like the existing app commands.

## Pillar B — Richer CV2 components

**Edit:** `notifications/cv2.py` (cockpit builder) and the gateway `bot/ui` LayoutView.

- **Section (type 9) with a thumbnail accessory** for the header zone — status glyph / logo beside the goal text, replacing the current flat `TextDisplay` header.
- **Polished separators / accent dividers** between zones (reuse existing `separator()` with intentional spacing).
- **File component (type 13)** — optional inline attachment of the run log on the cockpit (gated; off by default to avoid upload churn).

Constraint: the live dashboard must stay **calm and legible** — these are structural
refinements, not added color/noise. All additions must respect the existing CV2
clamp budget (`_clampComponents`: ≤40 components / ≤4000 chars).

## Pillar C — Live interactive control (selects)

**Edit:** `cv2.py` (raw select dicts in the cockpit tree), new gateway select handlers
(persistent or DynamicItem), and new pure routers on the `commands` spine.

Three String Select menus embedded in the cockpit container:

1. **Subtask select** — options are the run's subtasks; selecting one offers
   jump/skip/inspect. Extends the existing `applySubtaskAction` router from a
   button to a select (`nc:sel:subtask`).
2. **Effort select** — options are the configured effort levels; changes effort mid-run (`nc:sel:effort`).
3. **Mode select** — switch control mode watch ⇄ gated (`nc:sel:mode`).

**Wiring:** DynamicItem pattern (regex `custom_id` `nc:sel:<kind>`), stateless, registered
via `add_dynamic_items` in `setup_hook`. Each select's callback calls a pure router
on the `commands` spine + `ControlBus`, owner-gated + audited, mirroring
`applySubtaskAction`. Rendered in both transports (raw dict in `cv2.py`, `discord.ui.Select`
in the gateway LayoutView).

**Risk to verify in planning:** the `ControlBus` / `commands` spine must support
changing **effort** and **mode** mid-run. Subtask jump/skip is already supported.
If effort/mode mid-run changes are not supported, add a small explicit `ControlBus`
command for them rather than assuming — confirm before building the selects.

## Safety & invariants

- Every mutating select/context-menu action is owner-gated (`commands.isAuthorized`) and audited (`audit.record`).
- Source-of-truth unchanged: control commands go through `ControlBus`; run state stays canonical. The cockpit remains a derived view.
- Persistent/dynamic registration in `setup_hook` so everything survives gateway restarts.
- All surfaces degrade silently when Discord / the gateway is unconfigured (no run-breaking failures).
- CV2 additions respect the existing component/char clamp budget.

## Testing

- `tests/test_context_cog.py` — pure routers for the three context-menu actions (auth, no-task, happy path).
- `tests/test_selects.py` — pure routers for subtask/effort/mode selects (auth, no-task, value handling).
- Extend `tests/test_cv2.py` — assert the new Section/thumbnail/select component types appear and stay within the clamp budget.
- Canonical command: `python -m pytest tests/test_cv2.py tests/test_context_cog.py tests/test_selects.py`.

## Documentation

- Update `docs/NIGHTCLAW.md` — new context-menu surface, cockpit selects, CV2 component additions.
- Regenerate `.repo-map.json` (drift test).

## Phasing (for the implementation plan)

- **P1** — Pillar A: context-menu cog + pure routers + tests.
- **P2** — Pillar C: select routers + cockpit selects (both transports) + ControlBus support if needed + tests.
- **P3** — Pillar B: CV2 structural richness (Section/thumbnail/separators/File) + tests.
- **P4** — docs + repo-map regen + full focused test pass.
