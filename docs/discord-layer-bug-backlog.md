# Discord Layer — Bug Backlog (2026-07-04)

Findings from a multi-agent adversarial audit + live probing of the Nightclaw Discord
layer (interaction handlers, dashboard/terminal surfaces, REST chokepoint, control
ingestion). Confidence: **CONFIRMED** (verified in code) vs **PLAUSIBLE** (needs a repro).

**Status: backlog complete.** Fixes landed across three commits on branch
`fix/guard-unittest-false-positive` (not pushed). Remaining items below are deliberate
deferrals with reasons, not misses.

## Fixed — pass 1 (interaction/surface top tier)

| #   | Sev  | File                                        | Fix                                                                                                                                       |
| --- | ---- | ------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | High | `views_feedback.py`                         | **Auth bypass** — Approve/Reject/Retry were ungated via `slash._runControl`. Added `FeedbackView.interaction_check` owner-gate.           |
| 2   | High | `terminal_surface.py`, `run_phase_mixin.py` | **Pin leak** — terminal preview never unpinned → 50-pin cap. Added `TerminalSurface.unpin()` + teardown call.                             |
| 3   | High | `cv2.py`                                    | **Dead cockpit selects** — `cv2_effort_select`/`cv2_mode_select` had no handler. Removed from the cockpit (see deferral note re: wiring). |
| 4   | High | `discord_channels.py`                       | **Unclamped `content`** → 400. Now `truncate`d in all 4 senders.                                                                          |
| 10  | Med  | `control_mixin.py`                          | **Poll wedge** — `int(author_id)` now fails closed.                                                                                       |
| 11  | Med  | `bot/cogs/admin.py`                         | **`/cockpit` & `/hud`** now owner-gated.                                                                                                  |

## Fixed — pass 2 (REST + surfaces + control ingestion)

| #   | Sev      | File                  | Fix                                                                                                                                                                                        |
| --- | -------- | --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 5   | High     | `discord_client.py`   | **401 latch** — now requires 2 consecutive 401s (reset on any 2xx); one transient 401 no longer blacks out the surface.                                                                    |
| 6   | Med-High | `discord_client.py`   | **429 scope** — only a **global** 429 (`X-RateLimit-Global`/`global:true`) arms the process-wide breaker; a per-bucket 429 backs off only its own call. Also floors `retry_after` above 0. |
| 7   | Med      | `dashboard.py`        | **`dashboard_message_id` now persisted** on the 404-recreate + fresh-create paths in `update()`.                                                                                           |
| 8   | Med      | `terminal_surface.py` | **`_recreated` wedge** — re-armed on a healthy edit so a _second_ deletion can recover; **frozen final frame** now honored (`_final` flag).                                                |
| 9   | Med      | `discord_client.py`   | **`_clampEmbed`** now clamps `footer.text`/`author.name`; the budget shrinker also trims description/footer/title so a field-less embed can't exceed 6000.                                 |
| 12  | Med      | `control_store.py`    | **Edited `!`commands** — dedup key now folds a hash of the op, so an edited command (same id, new content) is a fresh op and isn't dropped.                                                |
| 13  | Med      | `commands.py`         | **`!add`** text is bounded (200 chars) + defanged (backticks/mentions) before the plan render + Ollama gate.                                                                               |
| —   | Low      | `discord_client.py`   | Oversized CV2 TextDisplay is **shrunk in place** instead of collapsing the cockpit to "…".                                                                                                 |
| —   | Low      | `discord_channels.py` | A **413** (oversized image) now drops the image and posts text-only instead of retrying forever.                                                                                           |
| —   | Low      | `discord_client.py`   | Missing/non-numeric owner id now **warns once** (blocked/critical pings won't notify).                                                                                                     |
| —   | Low      | `discord_client.py`   | `retry_after==0` bucket 429 no longer busy-spins (floored at 0.25s).                                                                                                                       |
| —   | Low      | `terminal_surface.py` | `finalize()`'s final frame is now actually frozen.                                                                                                                                         |
| —   | Low      | `bot/core.py`         | Global **`View.on_error`** net so a component-callback exception no longer leaves a dead "thinking" spinner.                                                                               |
| —   | Low      | `slash.py`            | `_subtaskAutocomplete` uses `.get()` — a malformed subtask row no longer `KeyError`s.                                                                                                      |

## Deferred (deliberate, with reasons)

- **`_RATE_LIMITED_UNTIL` lock**: left lock-free. It's now written only on a _global_ 429 (rare), and it's a monotonic deadline — the last-writer race is benign. A lock would add contention on the hot REST path for no correctness gain.
- **`sendAs` (Cast) components unclamped**: skipped. `_clampComponents` is CV2-shaped and could mangle legacy action-row components on the Cast path; the risk outweighs the low-severity, lab-gated exposure. Callers should pre-clamp.
- **#3 steering-select _wiring_** (effort/mode dropdowns): the **bug** ("interaction failed" on the live cockpit) is fixed by removal. Re-adding them wired to the existing `set_run_effort`/`set_mode` ops is an **enhancement** (new persistent Select view + registration), not a defect — left as a feature request.
- **#8 cross-restart terminal `message_id` persistence**: the `_recreated` wedge and the teardown unpin cover the common cases; persisting the terminal id across a _resilience restart_ (to avoid a mid-run-restart orphan) needs state plumbing into `TerminalSurface` and is a narrow case.
- **Rapid pause/resume last-writer race**: inherent to last-write-wins flags written by two different-cadence processes; mitigated by `_waitWhilePaused`'s deadline/night-mode escapes (can't wedge forever). Accepted.

## Note on the control-plane probe (not a bug)

`control.db` is derived at call time from `config.STATE_DIR.parent` (`control_store.py`),
i.e. **projectRoot-local**. A run launched from a git worktree reads
`<worktree>/state/control.db`; a `ControlBus` started elsewhere writes a **different** DB.
To drive a worktree run's control plane set `control_store._DB_OVERRIDE` (or run from the
worktree). The pause/abort code paths are sound; a definitive live-reaction test needs
**gated mode** (the run blocks at the plan gate) — fast sim runs finish before a flag polls.
