# Theme: Human-Loop / Control-Safety

Cross-repo synthesis for 9TO5 gap **#6 / §2.8**. Covers inline per-step approval & interrupts,
capability scoping, guardian/rollback gated on approval, prompt-injection defense, spend
allowances, autonomy supervisors, action audit, and git-native coordination.

---

## 1. Theme intro + how 9TO5 handles this today

This theme is about *keeping a human meaningfully in control of an autonomous agent without
stalling it* — knowing **when** to escalate, **what** an action is allowed to do, and **how** to
undo it when it goes wrong. The hard part is doing this semantically (by what an action *does* and
how risky it is) rather than syntactically (by what path it touches), and at the right granularity
(a single dangerous step, not a whole phase).

**9TO5 today** has a real control plane but a coarse, syntactic safety model:
- **ControlBus** (`platform_core/runtime/control.py`) — file-backed, atomic, three-process
  (run + Discord bot + web) bus carrying abort / pause / `kill_subprocess` / `force_replan` / gate
  decisions / queued plan-ops, with cross-process locking and corrupt-bus rebuild.
- **Two control modes** (gated vs autonomous) and approval **gates** at `plan` and `pre_pr` with a
  deadline timeout (`run_phase_mixin.py`). Discord drains into ops (`control_mixin.py::_applyOps`:
  skip/add/retry/edit) plus operator **intents** folded into the next spec
  (`plan_mixin.py::_foldOperatorContext`, `state.activeIntents`).
- **Safety** = **universe** scoping (`allowed_paths` / `hard_boundaries`) + `self_modification_guard`
  + a destructive-pattern regex scan + `CORE_PROTECTED_FILES` `--disallowedTools` disallow.

**Where it is weak** (brief §2.8):
1. **Safety is path/regex, not semantic** — no judgment of *what an action does* or *how risky it
   is*; the executor runs `--dangerously-skip-permissions` on the real tree with no per-subtask
   capability sandbox.
2. **Human-loop is coarse** — approve/reject/skip whole gates or subtasks; **no inline per-step
   approval or interrupt**. By design the system *removes* the human: the brain **auto-answers
   clarifications** (`llm_mixin.py::_resolveClarifications`) instead of escalating.
3. **Rollback is narrow** — only the git snapshot *inside* adversary remediation; there is **no
   run-wide undo** gated on a human decision.
4. **Action audit is hook-granularity only** — no per-action provenance, no injection defense on
   retrieved context fed to the brain.

The harvest below is unusually rich here: most peer repos treat approval, capability scoping,
rollback, and spend as first-class subsystems, and several ship small, portable, MIT/Apache code
that maps almost 1:1 onto these four weaknesses.

---

## 2. Ranked technique table (best-of across all 23 repos)

`steal-effort`: **idea** = concept/prompt only · **port** = self-contained code to re-implement in
Python · **heavy** = needs new infra (checkpoint backbone, sandbox, eBPF).
`rank`: 5 = highest-leverage for this theme.

| # | technique | source repo (best-in-class) | what it does | 9TO5-fit | steal-effort | rank |
|---|---|---|---|---|---|---|
| 1 | **Semantic action-risk authorization gate** | **eliza** (`spend-allowance.ts::decideSpendAuthorization`) | Pure fn classifies each action `read/dry-run/mutating/paid/destructive`; **destructive ALWAYS escalates to human**, self-spend auto-authorizes only while running-total+estimate < cap, reads pass free; unknown cost ⇒ ask; spend-hint param stripped before the real call; durable monotonic per-session ledger. | Replaces 9TO5's binary gated/autonomous + path/regex guards with a **semantic risk → human-or-bounded-autonomy** decision. Directly re-inserts the human the system currently removes. Dedupes with agentscope's per-mode engine & metagpt's `NoMoneyException`. | port | 5 |
| 2 | **Capability-scoped tool policy (layered allow/deny + provenance)** | **openclaw** (`src/agents/sandbox/tool-policy.ts`) | Per-agent allow/deny/`alsoAllow` lists resolved through `agent > global > default` scopes with **source diagnostics** (which scope decided), glob + tool-group patterns, default-deny re-opened by explicit allows. | The per-subtask capability scoping 9TO5 lacks (today only coarse hook guards + `--disallowedTools`). Auditable "why was this allowed/denied". Best-in-class vs agentscope/owl/hermes/claude-code scoped subagents. | port | 5 |
| 3 | **Durable inline interrupt + typed HITL schema** | **langgraph** (`interrupt()`/`Command(resume)`, `prebuilt/.../interrupt.py::HumanInterrupt`) | `interrupt(value)` durably pauses *anywhere mid-node*; resume re-enters replaying completed steps. `HumanInterrupt` = `action_request{action,args}` + `config{allow_ignore,allow_respond,allow_edit,allow_accept}`. | The true **inline per-step approval** 9TO5 has no equivalent of; the accept/edit/respond/ignore vocabulary maps straight onto Discord controls. Needs the checkpoint backbone (gap #3) to be fully durable. | port (idea without checkpoints) | 5 |
| 4 | **Guardian git-checkpoint + approval-gated restore** | **swarmclaw** (`src/lib/server/agents/guardian.ts`) | Captures HEAD/branch/porcelain before a run; on failure files a `human_loop` approval (`guardian_restore`); only after approve does `git reset --hard <head>` + `clean -fd`. ~200 LOC. | **Run-wide undo gated on a human decision** — exactly the missing rollback beyond adversary remediation. The `human_loop` approval category maps 1:1 onto a ControlBus gate decision. Dedupes loom shadow-git / hermes / loki re-undoable rollback. | port | 5 |
| 5 | **Memory-as-untrusted-input sanitizer** | **loki-mode** (`memory/rag_injector.py::_sanitize_field`) | Collapses every retrieved memory field to one inline line before it enters a prompt: strip control chars, collapse newlines/tabs (kills injected `###`/fences/instruction lines), defang leading markdown markers, per-field char cap. | 9TO5 injects retrieved lessons + Obsidian context **raw** into brain prompts — a live prompt-injection hole. Cheap, direct hardening. Unique to loki across the set. | port | 5 |
| 6 | **Interruption decider (deliver/queue/interrupt/ignore)** | **eliza** (`interruption-decider.ts`) | Pure fn for a human message arriving mid-turn: bias = working agent keeps working; explicit stop/cancel interrupts; **additive ("also add X") never interrupts**; only an *addressed, non-additive course-correction* cancels the turn; ambient multi-party chatter ignored. | Inline mid-run human **steering** without derailing the executor — the nuance 9TO5's coarse gates lack. Pairs with #3. | port | 4 |
| 7 | **Per-agent spend budgets + threshold alerts** | **swarmclaw** (`src/lib/server/cost.ts`; Mission budgets in `CLAUDE.md`) | Rolling hourly/daily/monthly spend windows, warn-at-80% + hard exceed; Mission caps on USD/tokens/turns/wallclock that drain the queue + fire a final report, with **user-chat bypass** so a human can still talk to a capped run. | Turns 9TO5's opportunistic `cost_usd` into an enforced **autonomy budget governor** with a human-reachable override. | port | 4 |
| 8 | **Autonomy supervisor reflection** | **swarmclaw** (`autonomy/supervisor-reflection.ts`) | Post-run observer emits typed incidents + auto-actions (`block`/`replan`/`compact`/`budget_trim`) folded into next run's context; severity-scored. | A structured self-supervision loop richer than 9TO5's single advisory adversary verdict; the `block` action is an auto-escalation trigger. | heavy | 4 |
| 9 | **Counter-evidence override council (fail-closed, judge≠author)** | **loki-mode** (`loki-ts/src/runner/counter_evidence.ts`) | On a BLOCK, the dev agent emits typed proof; 3 judges mapped to **different** providers vote 2-of-3 to lift. Self-supplied evidence fails **CLOSED** — only an adjudicator the agent doesn't control may lift. | Lets a 9TO5 adversary/gate block be **appealed with evidence** instead of being flat, while preserving "the thing being checked can't approve itself." | port | 4 |
| 10 | **Durable pause/resume HITL surviving a crash** | **crewai** (`flow/human_feedback.py` + `flow/persistence/sqlite.py`) / **MAF** (`_request_info_mixin.py`) / **dify** (`PauseReason`+resume token) | A node suspends the whole run with a typed request captured *in the checkpoint*; `from_pending(id).resume(answer)` continues in a **fresh process**. crewai also distills the human feedback into reusable lessons. | 9TO5 gates block *in-process* with a timeout; this is a gate that survives process death and resumes exactly where it paused. Three repos converge on the pattern. | port (needs journal) | 4 |
| 11 | **Per-tool approval as data + before/after hooks** | **openclaw** (`agent-loop.ts` before/afterToolCall) / **pydantic-ai** (`ApprovalRequired`/`CallDeferred`, `ApprovalRequiredToolset`) / **claude-code** SDK `can_use_tool` | `beforeToolCall` can `block` with a reason (permission as a returned value, not an exit-2 hook); `afterToolCall` can rewrite/terminate; pydantic wraps any toolset to demand approval conditioned on args. claude-code's NDJSON `can_use_tool` callback is the same gate 9TO5 already runs but doesn't use. | The **inline per-tool gate** seam. Key realization: 9TO5 drives Claude via flags + stdout tap and *cannot* intercept individual tool calls — adopting claude-code's SDK control protocol is the concrete path to inline approval. | port / idea | 4 |
| 12 | **Per-mode permission engine + inherited worker scopes** | **agentscope** (`permission/_engine.py`, `_agent_create.py::_merge_leader_permissions`) | Allow/deny/ask rule lists keyed by tool across 5 modes (DEFAULT/EXPLORE/ACCEPT_EDITS/BYPASS/DONT_ASK); matching delegated to each tool (Bash=cmd-prefix, file tools=glob). Spawned workers **inherit** the leader's already-granted scope so they don't re-prompt. | A richer mode model than 9TO5's two control modes; inheritance is the pattern for scoping parallel workers without re-asking the operator. | port | 4 |
| 13 | **Signed-action integrity + tiered danger gate + audit log** | **agx** (`lib/security.js`) | Tasks HMAC-SHA256 signed (timing-safe verify, tamper detect); severity-tiered dangerous-pattern scan (**critical blocks, high/med confirm**); JSON-line audit of every execution. | Upgrades 9TO5's binary destructive-regex scan to a **tiered** block-vs-confirm gate, plus tamper-evident task integrity across its 3-process setup. | port | 4 |
| 14 | **Per-artefact lineage (transparency log)** | **bernstein** (`core/lineage/`, `agent_card_signer.py`) | Every file write records producer + inputs + prompt SHA + model + cost, HMAC-chained and verifiable (`bernstein lineage verify <run_id>`); one signed record per scheduling decision. | The **semantic action audit** ("what did this action actually do, from what inputs") far beyond 9TO5's hook-granularity audit. Heavyweight but the reference design. | heavy | 3 |
| 15 | **Git-native coordination: commit-as-event journal + lock-free claim** | **gnap** (spec) / **guild** (`quest/accept.go`, `bounties.go`) | gnap: `<agent>: <action> <entity>` commit convention makes `git log` a tamper-evident, replayable audit trail; lock-free task claim via git non-fast-forward + pull-rebase-retry. guild: atomic CAS claim (`UPDATE…WHERE claimed_by IS NULL`) + **file-disjointness parallel-safety** test. | An **audit-by-default** action log 9TO5 gets for free from git, plus the race-free claim + disjointness test that would let parallel workers coordinate instead of clobbering one tree (and stop disabling adversary remediation). | idea / port | 4 |
| 16 | **Transparent shadow-git checkpoint + rollback** | **hermes** (`tools/checkpoint_manager.py`) / **loom** (`auto-commit` PostToolsHook) | Auto-snapshot once/turn before mutating ops into a dedup'd shadow git store; rollback to any checkpoint; loom auto-commits each mutating tool with an LLM-authored message (fail-open, invisible to the model). | Run-wide undo points **per step** without polluting the real history — complements #4 (guardian = the approval gate, this = the snapshot substrate). | port | 4 |
| 17 | **Verification-evidence ledger (proof, not assertion)** | **hermes** (`verification_evidence.py` + `verify_on_stop`) / **loki** Evidence Receipt (`proof-generator.py`) | A WAL ledger classifying each command as "what was actually proven"; a turn-end guard nudges a bounded verify if the model finishes after editing code with no fresh evidence. loki splits re-derivable **facts** from LLM **assessments** so an opinion can never flip a gate green. | The per-run **audit/proof trail** 9TO5's observability lacks; doubles as a control-safety record of what really ran before a gate passed. | port | 4 |
| 18 | **Capability-gated staged rollout of risky behavior** | **warp** (feature-flag lanes; `add-feature-flag/SKILL.md`) / **crewai** (`CREWAI_ALLOW_FLOW_SCRIPT_EXECUTION`) | Every risky change is gated behind a flag with dogfood→preview→release staged enablement; inline code-exec disabled by default behind an env flag. | Mirrors and extends 9TO5's "self-edits inert until fresh process" — a discipline for **staging** new autonomous behaviors behind a human-flippable gate. | idea | 3 |
| 19 | **Secret-handling discipline in agent prompts** | **warp** (`onboarding-verification-skill/SKILL.md`) | Never echo/log/screenshot tokens; no `xdg-open` of token URLs; treat redirect URLs as secret-bearing; user-only temp file perms. | Semantic capability scoping at the **prompt** layer for 9TO5's executor invocation spec — cheap, no infra. | idea | 3 |
| 20 | **Semantic syscall audit + sandbox-escape detection** | **loom** (`weaver-ebpf-audit`) | eBPF sidecar captures exec/file/net/privilege syscalls, flags `unshare/setns/mount/bpf` escapes, DNS↔connection correlation. | The deepest "what did the action actually do" audit; the correct end-state for replacing regex guards, but K8s/eBPF-heavy — direction, not a near-term port. | heavy | 2 |
| 21 | **Capability-scoped env action registry** | **metagpt** (`mark_as_readable`/`mark_as_writeable`) / **owl** (per-worker scoped toolkits) | Explicit allow-listed, schema'd env actions per environment; each worker gets only the tools its role needs. | A declarative model for per-subtask capability sets; lighter-weight cousin of #2/#12. | idea | 3 |

---

## 3. If 9TO5 adopts ONE thing for this theme

**Adopt a semantic action-risk authorization gate, modeled on eliza's
`decideSpendAuthorization` (`references/eliza/plugins/plugin-agent-orchestrator/src/services/spend-allowance.ts`).**
9TO5's two deepest weaknesses here share one root cause: safety is decided by *path/regex* and the
human is *removed by default* (the brain auto-answers clarifications). eliza's gate is the cleanest,
purest, most portable fix — a single side-effect-free function that classifies every action by
**semantic risk** (`read/dry-run/mutating/paid/destructive`) and routes it three ways: proceed
silently, proceed only while a bounded autonomy budget holds, or **escalate to a human — always, for
anything destructive**. Porting it into the ControlBus path (risk-tier each ExecutionStep / tool
intent; auto-run reads, budget-meter mutating/paid work, and force a Discord gate decision on
destructive or unknown-cost actions, with the cost hint stripped before the real call) flips 9TO5
from "regex guard + auto-answer" to "risk-tiered human-in-the-loop" in one move. It is a pure,
unit-testable port that reuses the existing gate/Discord surface rather than new infrastructure, and
it establishes the **risk taxonomy** that every other technique in this theme builds on — capability
scoping (#2), spend budgets (#7), guardian-rollback approval (#4), and inline per-step approval (#3)
all need exactly this "how risky is this action, and does it need a human?" classifier underneath
them.
