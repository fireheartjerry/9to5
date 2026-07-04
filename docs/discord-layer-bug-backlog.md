# Discord Layer — Bug Backlog (2026-07-04)

Findings from a multi-agent adversarial audit + live probing of the Nightclaw Discord
layer (interaction handlers, dashboard/terminal surfaces, REST chokepoint, control
ingestion). Confidence: **CONFIRMED** (verified in code) vs **PLAUSIBLE** (needs a repro).

## Fixed in this pass (branch `fix/guard-unittest-false-positive`)

| #   | Sev  | File:line                                                                                 | Fix                                                                                                                                                                                            |
| --- | ---- | ----------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | High | `notifications/views_feedback.py`                                                         | **Auth bypass** — Approve/Reject/Retry buttons routed through `slash._runControl` (no owner check) while Skip was gated. Added `FeedbackView.interaction_check` owner-gate.                    |
| 2   | High | `notifications/terminal_surface.py`, `platform_core/orchestration/run_phase_mixin.py:380` | **Pin leak** — terminal preview was never unpinned at teardown → Discord's 50-pin cap fills → all pinning fails cross-run. Added `TerminalSurface.unpin()` + teardown call.                    |
| 3   | High | `notifications/cv2.py:165`                                                                | **Dead cockpit selects** — `cv2_effort_select`/`cv2_mode_select` had no handler → "interaction failed" on the live dashboard. Removed from the cockpit (re-add once wired to owner-gated ops). |
| 4   | High | `notifications/discord_channels.py:176,249,333,350`                                       | **Unclamped `content`** → 400 on >2000 chars (embed was clamped, content wasn't). Now `truncate(content, DISCORD_MAX_CONTENT)` in all four senders.                                            |
| 10  | Med  | `platform_core/orchestration/control_mixin.py:70`                                         | **Poll wedge** — `int(author_id)` outside the try → one non-numeric author id stalled in-run ingestion forever. Now fails closed.                                                              |
| 11  | Med  | `notifications/bot/cogs/admin.py:48,59`                                                   | **`/cockpit` & `/hud` not owner-gated** — any user could render run state / spam the cockpit. Added `isAuthorized` check.                                                                      |

## Open (not yet fixed)

- **#5 High — 401 latch is permanent** (`discord_client.py:161`): any single (possibly transient) 401 disables Discord for the whole process, no recovery. Needs a policy: N-consecutive-401s before latching, or a cooldown + half-open probe (mirror the 429 breaker).
- **#6 Med-High — per-bucket 429 arms the GLOBAL breaker** (`discord_client.py:119,144`): one noisy route stalls the control poll + all sends; `_RATE_LIMITED_UNTIL` is also lock-free across 4+ threads. Only arm the global breaker on a global 429 (`X-RateLimit-Global`).
- **#7 Med — `dashboard_message_id` not persisted on 404-recreate** (`dashboard.py:275-283`): orphaned pin + stale id after a resilience restart.
- **#8 Med — terminal `message_id` never persisted + `_recreated` one-shot wedges** (`terminal_surface.py:79,161`): orphaned pins across restarts; a second deletion goes permanently dark mid-run.
- **#9 Med — `_clampEmbed` ignores `footer.text`/`author.name`; budget shrinker only trims fields** (`discord_client.py:187,214`): >6000-char embed ships → 400 despite "guaranteed sendable".
- **#12 Med — edited `!`commands silently dropped** (`control_store.py:80`): `source_msg_id` dedup ignores an edited command (same id, new content); the user thinks they redirected the run.
- **#13 Med — `!add` text unbounded + injectable** (`commands.py:340`): breaks the plan-render code fence and feeds untrusted text into the Ollama auto-approve gate (prompt injection). Bound length + sanitize.
- **Follow-up to #3**: wire `cv2_effort_select`/`cv2_mode_select` to real `set_run_effort`/`set_mode` ops (owner-gated, persistent view) if the steering control is wanted.
- **Low / PLAUSIBLE**: oversized CV2 component collapses dashboard to "…" (`discord_client.py:278`); oversized attachment 413 mapped `transient` → retried forever (`discord_client.py:298`); missing/non-numeric owner id → BLOCKED ping silently doesn't notify (`discord_client.py:92`); `finalize()`'s "frozen frame" isn't actually frozen (`terminal_surface.py:136`); button/modal callbacks have no `on_error` net (`bot/core.py:125`); `retry_after==0` bucket 429 → `sleep(0)` busy-retry burst (`discord_client.py:141`); `_subtaskAutocomplete` hard subscripts vs `.get()` elsewhere (`slash.py:84`); rapid pause/resume toggle last-writer race (`control_store.py:197`).

## Note on the control-plane probe (not a bug)

An earlier "pause is ignored" observation was a **test artifact**: `control.db` is derived at
call time from `config.STATE_DIR.parent` (`control_store.py:99`), i.e. **projectRoot-local**.
A run launched from a git worktree reads `<worktree>/state/control.db`; a `ControlBus` process
started elsewhere writes a **different** DB. To drive a worktree run's control plane, set
`control_store._DB_OVERRIDE` (or run from the worktree) so writes land in the run's DB. The
pause/abort code paths (`control_mixin._waitWhilePaused`, the many `bus.isAbort()` checks) are
sound; a definitive live reaction test needs **gated mode** (the run blocks at the plan gate) —
fast sim runs finish their subtasks before a control flag is polled.
