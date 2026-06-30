# gnap — reference harvest

## 1. Repo

- **Name:** GNAP — Git-Native Agent Protocol (`farol-team/gnap`).
- **What it is:** A minimal *specification* (not a tool) for coordinating multi-agent AI teams using a shared git repo as the only transport + storage. Four JSON entities — `agents.json`, `tasks/*.json`, `runs/*.json`, `messages/*.json` — under a `.gnap/` dir; `git log` is the audit trail.
- **Maturity:** Draft v4, March 2026; pre-adoption (~20 stars). The repo itself admits it is "an RFC, not a tool" — no reference CLI exists.
- **Primary language:** None / Markdown. Content is `README.md` (the normative spec), `ONBOARDING.md`, `docs/article.md`, and 5 example JSON files. Zero executable code.
- **LICENSE:** MIT (Copyright 2026 Farol Labs). Verified in `references/gnap/LICENSE`.
- **NOT** the IETF GNAP authorization protocol — unrelated despite the acronym collision. No security/auth/capability-token content; gap #6 (sandbox/capability scoping) is **not** addressed here.

## 2. Architecture sketch

- Three-layer model: **Git** (transport/storage: push/pull/merge/history) ← **GNAP protocol** (4 entities) ← optional **application layer** (budgets, dashboards, governance — explicitly out of scope).
- Every agent runs an identical **heartbeat loop**: `git pull --rebase` → read `agents.json` (am I active?) → read `tasks/` (assigned + `ready`?) → read `messages/` → do work → write run + flip task state → commit → push. Poll interval per-agent via `heartbeat_sec` (default 300s).
- **Task** is a file with a state machine: `backlog → ready → in_progress → review → done`, plus `blocked`/`cancelled` and reverse edges (`review→in_progress` reject, `blocked→ready` unblock). Hierarchy via `parent`; explicit `blocked` + `blocked_reason`; `reviewer` field; inline `comments[]`.
- **Run** is a separate file = one *attempt* at a task. Many runs per task; a failed run does not fail the task. Carries `tokens{input,output}`, `cost_usd`, `started_at`/`finished_at`, `commits[]`, `artifacts[]`, `error`.
- **Message** is a file = agent-to-agent comms: `from`, `to[]` (with `["*"]` broadcast), `type` (directive/status/request/info/alert), `channel`, `thread` (reply-to), `read_by[]`.
- **Concurrency** is lock-free: two agents racing to claim a task collide on git's non-fast-forward push rejection; loser does pull-rebase-retry (max 3). Eventual consistency bounded by max heartbeat. Offline-capable by construction.
- **Audit/commit convention:** `<agent-id>: <action> <entity> [details]` (e.g. `carl: done FA-1 — Stripe test mode live`) so `git log` is a parseable, tamper-evident event stream.

## 3. Techniques table

| name | what | where (repo path) | lens | maps-to-9to5 | steal-effort | rank |
|---|---|---|---|---|---|---|
| Run-as-attempt ledger file | Each execution attempt is its own immutable record (`tokens`, `cost_usd`, timings, `commits[]`, `artifacts[]`, `error`), decoupled from the task; retry history + cost rollup + audit fall out for free | `README.md` §3, `examples/.gnap/runs/FA-1-1.json` | both | Observability #5 (consistent per-step token/cost series, failed-attempt replay) + Durability #3 (per-attempt journal). 9to5's `experience.db` stores this but the explicit "failed run ≠ failed task, sum-of-runs = budget, every attempt persisted" framing is cleaner than the current opportunistic `cost_usd` capture | idea-only | 4 |
| Structured commit-as-event journal | Mandate `<agent>: <action> <entity>` commit messages so `git log` is a tamper-evident, parseable step journal — no separate event DB | `README.md` Transport, `ONBOARDING.md` Quick Reference | both | Durability #3 (durable step-level journal to replay a partial subtask) + Observability #5. 9to5 forbids logs-as-source and lacks a transactional WAL; commit-per-step gives an auditable, replayable trail backed by git, not logs | idea-only | 4 |
| File-based message blackboard | Peer-to-peer messages as files with `to[]`/broadcast/`channel`/`thread`/`read_by[]` — a shared scratchpad any worker reads/writes | `README.md` §4, `examples/.gnap/messages/1.json` | both | Multi-agent topology #7 (the explicit gap: "no blackboard/scratchpad between concurrent workers"). GNAP's message dir IS a blackboard; `read_by[]` gives ack semantics, `thread` gives debate threading | idea-only | 4 |
| Lock-free claim via commit race | Concurrent task claim resolved by git non-fast-forward rejection + pull-rebase-retry(max 3) instead of a distributed lock | `README.md` Consistency, `docs/article.md` "Why Git" | both | Multi-agent topology #7 — directly addresses 9to5's "concurrent subtasks clobber one shared git tree" pain; per-worker worktree + claim-file commit race would let parallel workers coordinate without disabling adversary remediation | idea-only | 3 |
| Explicit `blocked` + `blocked_reason` + `reviewer` task fields | First-class blocked state with reason string and a named reviewer, plus `review→in_progress` reject edge | `README.md` §2, `examples/.gnap/tasks/FA-1.json` | 9to5-fit | Planning #1 / Verification #2 — 9to5's `task_schema` has dependencies but a structured machine-readable `blocked_reason` and an explicit reviewer/reject loop would make replanner + adversary verdicts more legible | idea-only | 3 |
| Agent registry w/ org tree + capability tags | `agents.json` with `reports_to` (org tree), `capabilities[]`, `type` ai/human, `status` active/paused/terminated, per-agent `heartbeat_sec` | `README.md` §1, `examples/.gnap/agents.json` | standout | Multi-agent topology #7 — capability tags enable capability-based task routing; humans + AI as first-class peers matches 9to5's human-loop goal | idea-only | 2 |
| Human + AI as symmetric participants | Same schema/loop for human and AI agents; humans are agents with `type:human`, no `runtime` | `README.md` "Why GNAP", `agents.json` | standout | Human-loop #2.8 — reframes the operator as a peer in the same task/message graph rather than an out-of-band gate approver | idea-only | 2 |
| Protocol version gate | `.gnap/version` plain integer; agents MUST refuse to operate if version exceeds what they support | `README.md` Protocol Version | standout | Schema-evolution discipline for 9to5's `task_schema`/state files across self-improvement runs | idea-only | 2 |
| Zero-infra / offline / eventual-consistency substrate | Whole-system philosophy: git as the only dependency, agents work disconnected and sync later | `docs/article.md` Coordination Matrix | standout | Architectural lens only; 9to5 is single-host so low direct fit, but the audit-by-default property is attractive | idea-only | 1 |

## 4. Top 3 takeaways

1. **Zero portable code, but two genuinely gap-pointed ideas.** This is a spec repo — nothing to `port-code`. The value is conceptual, and it lands squarely on two of 9to5's real gaps: the **Run-as-attempt ledger** (gap #5/#3) and the **structured commit-as-event journal** (gap #3). 9to5 already has an `experience.db` and forbids logs-as-source; GNAP's insight is that *git commits themselves* are the durable, tamper-evident, replayable step journal — a WAL you already have for free. Adopting a `<agent>: <action> <entity>` commit convention per ExecutionStep would give cheap mid-subtask replay without new infrastructure.
2. **The message dir is the blackboard 9to5 explicitly lacks.** Gap #7 names "no blackboard/scratchpad between concurrent workers." GNAP's `messages/` (with `to[]`, `read_by[]`, `thread`, `channel`) is exactly that, and its **lock-free claim-via-commit-race** pattern is a credible answer to 9to5's "parallel subtasks clobber one shared git tree" problem — give each parallel worker a worktree and a claim-file, let git's non-fast-forward rejection arbitrate.
3. **Not relevant to the capability-scoping/sandbox gap (#6).** Despite the acronym, this is *not* the GNAP authorization protocol — there is no capability, token, or sandbox content. It contributes nothing to safety/capability scoping; its only safety-adjacent value is "git history = audit log."

---
**One-line summary:** GNAP is a code-free MIT spec for git-as-coordination-substrate for agent teams; idea-only value, but its run-attempt ledger, commit-as-journal, and message-blackboard ideas hit 9to5 gaps #3/#5/#7.

**Highest-ranked technique:** Model every executor attempt as an immutable **Run record** (tokens, cost, commits, artifacts, error) decoupled from the task, and emit a **structured `<agent>: <action> <entity>` commit per step** — turning git history into a durable, replayable, cost-aware step journal (gaps #3 + #5) with no new infrastructure.
