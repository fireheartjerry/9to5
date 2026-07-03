# Localhost Web Dashboard — Full UI/UX Redesign — Design

> **Status:** approved design (brainstorming output, fast-track — user pre-approved
> scope and authorized autonomous subagent-driven execution, "approve everything").
> Next: implementation plan (`docs/superpowers/plans/2026-07-01-webdash-redesign.md`).

## Objective

Bring the localhost web dashboard (`http://localhost:8787`, aka the "Bloomberg
terminal") to top-tier UI/UX quality across accessibility, feedback/safety,
motion, responsiveness, and visual polish — without changing its backend
contract, its zero-dependency architecture, or its distinct black/teal/amber
trading-terminal identity.

## Scope

**In scope (frontend only):**
- `notifications/webdash_page.py` — the single self-contained `PAGE` HTML/CSS/JS
  string served at `GET /`.

**Out of scope (unchanged):**
- `notifications/webdash.py` — HTTP handler, routes, SSE, CSRF token flow.
- API contract: `/api/state`, `/api/events`, `/api/control`, `/api/raw` — same
  request/response shapes.
- Any dependency addition — stays stdlib-only, no CDN fetch, no build step, no
  Flask/Node. This is a hard architectural constraint (`docs/ARCHITECTURE.md`
  documents this as a deliberately zero-dependency local tool).

## Current state (baseline, read before this design)

168-line single HTML string. Dark-mode-only, true black bg, monospace, 3-column
CSS grid (meta/mission | live feed w/ filter+search | subtasks+narrative), SSE
event feed, per-subtask raw-stdout expand, health-aura dot, ASCII-bar
"intelligence curve." Functional, distinctive, but has real gaps:

- No confirm dialog before destructive actions (Abort/Reject fire immediately).
- Control actions (`ctl()`) swallow fetch errors silently — zero user feedback
  on success or failure.
- No loading/busy state on buttons during in-flight control calls.
- `#555555` muted text on `#000000` ≈ 3.5:1 contrast — fails WCAG AA (4.5:1).
- One emoji-as-icon (🖥) violates the no-emoji-icon rule.
- No `aria-live`, no visible focus rings, no aria-labels, no landmarks.
- No responsive breakpoint — fixed `230px 1fr 300px` grid breaks under ~960px.
- No connection-state indicator for SSE (silently retries every 3s).
- Zero animation/transition anywhere (instant hover/state changes).
- Intelligence-curve is a div-width hack, not a real chart (no tooltip/labels).
- Repeated raw hex values throughout CSS instead of token variables.

## Approaches considered

**A. Incremental polish, same architecture (recommended).** Fix every gap above
in place: add a CSS custom-property token layer, accessibility primitives,
confirm/toast/connection-status UI, responsive breakpoint, motion, and a real
inline-SVG chart — all still hand-written HTML/CSS/JS, still zero deps. Lowest
risk, preserves the existing visual identity the user already has, directly
addresses every checklist gap.

**B. Mini virtual-DOM diffing rewrite.** Replace the current
`innerHTML = ...` full-repaint pattern with a small hand-rolled diffing
renderer for smoother updates. Rejected: this is a low-traffic single-user
local dashboard: full-repaint on a 2s poll is not a measured problem, and this
adds real complexity (YAGNI) for no user-visible gain.

**C. CDN-based SPA framework (Preact/Lit/htm).** Rejected outright: breaks the
zero-dependency, localhost-only constraint the architecture doc requires, and
would silently fail if the tunnel/dashboard is used offline or the CDN is
blocked.

**Decision: A.**

## Design

### Token layer
Replace repeated raw hex with CSS custom properties on `:root`: `--bg`, `--fg`,
`--accent-teal` (#00d4aa), `--accent-amber` (#ff9f00), `--err` (#ff4444),
`--muted` (bumped to `#8a8a8a`, ~4.6:1 on black — passes AA), `--border`
(#222222), `--raw-bg` (#050505). No visual identity change other than the
muted-gray contrast fix.

### Accessibility
- `<header>`, `<nav>` (control bar), `<main>` (columns), `<aside>` landmarks.
- Visible `:focus-visible` ring (2px solid var(--accent-teal), offset 2px) on
  every interactive element.
- `aria-label` on icon-only / ambiguous controls; `aria-live="polite"` region
  wrapping the feed container so new events are announced without spamming.
- Replace 🖥 emoji with a small inline `<svg>` monitor glyph.
- Skip-link ("Skip to live feed") as first focusable element.

### Feedback & safety
- Confirm modal (in-page, not `window.confirm`, to stay on-brand) before
  `abort`/`reject`: "Abort this run? This cannot be undone." + Cancel/Confirm.
- Toast stack (bottom-right, auto-dismiss 4s, `aria-live="polite"`) reporting
  control-action success/failure instead of swallowing errors.
- Buttons disable + show inline spinner glyph while their `ctl()` call is
  in-flight; re-enable on response or timeout.
- Connection-status pill in header: `● live` (teal) / `● reconnecting` (amber,
  pulsing) / `● offline` (red) driven by `EventSource` open/error/close.
- Skeleton placeholders (subtle pulsing bars) in the three columns until the
  first `/api/state` response lands, replacing bare `—`.

### Motion
- 150–250ms `ease-out` transitions on hover/press/panel/toast/modal.
- New feed rows fade+slide in (translateY 4px → 0) over ~150ms.
- Health-aura dot gets a slow (2s) opacity pulse when health score is degraded,
  static when healthy.
- Whole motion layer wrapped in `@media (prefers-reduced-motion: reduce)` that
  disables it.

### Layout / responsive
- Breakpoint at 960px: 3-column grid collapses to a single scrollable column
  with tab-style section switcher (Meta / Feed / Subtasks) driven by pure CSS
  (radio-button tab hack, no JS needed) to keep zero-dependency simplicity.
- Draggable column splitters (CSS `resize: horizontal` on the first two
  columns) so the user can rebalance width.
- Sticky `.sec` section headers within scrolling columns.
- Custom dark scrollbar styling (`scrollbar-color`/`-webkit-scrollbar`).

### Visual polish
- Intelligence curve becomes a real inline `<svg>` horizontal bar chart:
  labeled axis, per-bar `<title>` tooltip (native, keyboard/screen-reader
  reachable), teal bars on a subtle gridline background — replacing the
  div-width hack.
- Copy-to-clipboard button on each expanded raw-stdout block.
- Keyboard shortcuts: `Ctrl/Cmd+K` focuses search, `Esc` closes the topmost
  open raw-stdout panel or modal.
- Dynamic `<title>` reflecting `codename` + `status` (so the browser tab is
  useful when backgrounded).
- Inline-SVG data-URI favicon (small terminal-glyph mark, teal on black).

## Data flow

Unchanged: `poll()` every 2s hits `/api/state`; `EventSource` streams
`/api/events`; `ctl()` posts to `/api/control` with the CSRF token. This design
only changes how the DOM renders that data and how the UI reports control
outcomes — no new endpoints, no new client-server contract.

## File layout (modularity)

Fully inlining all of the above would push `webdash_page.py` well past the
450-line `must_split` threshold. Split following the repo's existing
"module → sub-modules + re-export facade" pattern (see `discord_*.py`):

- `notifications/webdash_page.py` — thin facade: assembles and exports `PAGE`
  (unchanged public name, so `webdash.py` needs **zero** edits) by formatting
  the markup with styles/script substituted in.
- `notifications/webdash_styles.py` — exports `STYLES` (the `<style>` block
  contents, token layer + all rules above).
- `notifications/webdash_script.py` — exports `SCRIPT` (all client JS:
  render/poll/SSE/ctl/toast/modal/shortcuts).
- `notifications/webdash_markup.py` — exports `MARKUP` (the HTML skeleton with
  `{styles}`/`{script}` placeholders).

Each file targets ≤300 lines (ideal bucket). `__WEBDASH_TOKEN__` substitution
in `webdash.py` continues to work unchanged since it string-replaces inside the
final assembled `PAGE`.

## Testing

`tests/test_bloomberg_webdash.py` and `tests/test_webdash_control.py` test
backend behavior (HTTP responses, control routing, CSRF), not exact HTML
string content — expected to pass unchanged. Add/extend a lightweight
assertion that `PAGE` still contains the CSRF token placeholder and the core
`id="..."` hooks the backend/tests rely on (`feed`, `meta`, `subs`, `curve`,
etc.) so a future refactor can't silently break the JS/DOM contract.

## Risks / non-goals

- No new backend features (no run-history browsing, no multi-run switcher) —
  explicitly out of scope, would be scope creep beyond "improve the UI."
- No external font/CDN fetch — stays offline-safe.
- Visual identity (black/teal/amber, monospace, terminal feel) is preserved,
  not replaced — this redesign is depth/craft, not a reskin.
