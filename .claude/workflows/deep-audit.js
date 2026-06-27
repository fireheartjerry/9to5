export const meta = {
  name: 'deep-audit',
  description: 'Hyper-comprehensive multi-agent audit of the 9to5 codebase: area-deep + cross-cutting finders, adversarial verification, synthesis',
  phases: [
    { title: 'Map', detail: 'parallel readers build a subsystem map' },
    { title: 'Audit', detail: 'area-deep + cross-cutting finders surface issues' },
    { title: 'Verify', detail: 'adversarially confirm each finding is real' },
    { title: 'Synthesize', detail: 'dedupe + rank confirmed issues with fixes' },
  ],
}

// ---- schemas -------------------------------------------------------------
const FINDINGS = {
  type: 'object',
  required: ['findings'],
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['title', 'file', 'severity', 'category', 'description', 'evidence', 'suggested_fix'],
        properties: {
          title: { type: 'string', description: 'one-line summary' },
          file: { type: 'string', description: 'path:line (relative to repo root)' },
          severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low'] },
          category: { type: 'string', description: 'bug|concurrency|error-handling|resource-leak|security|merge-artifact|contract|windows|data-integrity|config|test-gap|dead-code' },
          description: { type: 'string', description: 'what is wrong and the concrete impact at runtime' },
          evidence: { type: 'string', description: 'exact code snippet / reasoning proving it' },
          suggested_fix: { type: 'string', description: 'precise, minimal fix' },
        },
      },
    },
  },
}
const VERDICT = {
  type: 'object',
  required: ['is_real', 'confidence', 'reasoning', 'corrected_severity'],
  properties: {
    is_real: { type: 'boolean', description: 'true ONLY if this is a genuine defect that affects runtime/correctness/security; false if speculative, intended behavior, or already-handled' },
    confidence: { type: 'number', description: '0..1' },
    reasoning: { type: 'string', description: 'why real or not — cite the actual code path' },
    corrected_severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low', 'not-a-bug'] },
    refined_fix: { type: 'string', description: 'the minimal correct fix if real, else empty' },
  },
}

// ---- areas (deep, one agent reads the whole area) ------------------------
const AREAS = [
  { key: 'orchestrator-core', files: 'orchestrator.py, control.py — the run loop, gates (plan/pre_pr), execution loop, backfill/drain, finalize, _checkControl, _checkCodeDivergence, ControlBus' },
  { key: 'agents', files: 'agents/ (elaborator, architect, executor, adversary, replanner, verifier, browser_executor, chatgpt_driver, hooks)' },
  { key: 'notifications', files: 'notifications/ incl. bot/cogs/, slash.py, discord_bot.py, dashboard.py, webdash.py, command_bot.py, views.py, cast.py, cv2.py, console_hud.py, visuals.py, work_launcher.py' },
  { key: 'learning-sie', files: 'learning/ (sie.py orchestrator + policy, dataset, distill, finetune, eval_harness, eval_runner, preferences, lessons, reward, rollout, selfplay, meta_opt, knowledge_graph, postmortem, solution_cache, compute, safety)' },
  { key: 'memory-state', files: 'memory/ (obsidian, experience, retrieval, subtask_manager) and state/ (task.py) — JSON state read/write, atomicity, corruption handling' },
  { key: 'selfmod-safety', files: 'identity.py, epoch.py, selfmod.py, wipe.py — self-modification guard, epoch divergence fingerprinting, factory-reset safety (must never delete source code)' },
  { key: 'infra-entry', files: 'main.py (CLI/stdin/resume), config.py (env parsing/defaults), resilience.py, doctor.py, health.py, simulation.py, provenance.py, surfaces.py, llm_io.py, contracts.py' },
]

// ---- cross-cutting specialists (whole repo, one lens each) ---------------
const LENSES = [
  { key: 'concurrency', prompt: 'THREAD-SAFETY & RACES across the whole repo. The system runs concurrent threads: the run thread, Discord REST poll loops, a dedicated browser/Playwright thread, terminal stdin reader, the gateway command bot, and parallel subtask workers — all sharing the file-backed ControlBus + task-state JSON + in-process locks. Hunt: unguarded shared mutable state, check-then-act races on state/control files, lock ordering / deadlock, missing locks around dict mutation, TOCTOU on files, signal/abort propagation gaps, threads that can leak or never join.' },
  { key: 'security', prompt: 'SECURITY across the whole repo. Hunt: secret/.env handling & leakage into logs or committed files, subprocess/shell command construction from untrusted/goal-derived input (shell=True, unescaped args), the self_modification_guard PreToolUse hook bypass, wipe.py deleting beyond data files, path traversal, unsafe deserialization (pickle/yaml/eval), SSRF in browser/CDP, verify-cmd injection.' },
  { key: 'merge-artifact', prompt: 'MERGE / CORRUPTION artifacts across the whole repo (this branch is a 4-way consolidation). Hunt: duplicate function/class definitions, dropped or half-applied logic from a semantic merge, leftover conflict markers, mangled docstrings/imports (like a "\"\"\"from" splice), STRIPPED non-ascii/emoji in user-facing strings, dead re-implementations, two code paths that contradict, imports of removed symbols.' },
  { key: 'resource-leak', prompt: 'RESOURCE LEAKS across the whole repo. Hunt: files opened without context managers, subprocesses/Popen never waited/killed (zombie main.py, chromium), Playwright browsers/contexts not closed, threads/timers never stopped, sockets/HTTP sessions left open, temp dirs not cleaned, unbounded growth (caches, lists, state files).' },
  { key: 'windows-portability', prompt: 'WINDOWS PORTABILITY across the whole repo (target is Windows 11, PowerShell). Hunt: os.path vs pathlib misuse, hardcoded / vs \\ separators, file-locking issues (WinError 32 on open inode/WAL — sqlite, JSON rewrite, tar), CRLF/encoding assumptions, missing encoding="utf-8" on open(), console/emoji encoding (cp1252) crashes, subprocess argv quoting, signals not on Windows.' },
  { key: 'data-integrity', prompt: 'DATA INTEGRITY across the whole repo. Hunt: non-atomic JSON/state writes (partial write on crash), missing corruption handling on load (JSONDecodeError), unvalidated brain/LLM JSON parsed into state, schema drift between writers/readers of task-state, lost updates under concurrent writers, jsonl append races.' },
  { key: 'error-handling', prompt: 'ERROR HANDLING & RESILIENCE across the whole repo. Hunt: bare/broad except that swallows real errors silently, except that hides control-flow bugs, retries without backoff or with infinite loops, error paths that leave state half-mutated, missing timeouts on network/subprocess, exceptions that crash a background thread killing a surface silently.' },
  { key: 'contracts-deadcode', prompt: 'CROSS-MODULE CONTRACTS & DEAD CODE across the whole repo. Hunt: callers passing wrong arity/kwargs after a refactor, return-shape mismatches (dict vs object), config keys referenced but never defined (or defined never used), functions/branches now unreachable, stale TODO/FIXME that mark real gaps, public API drift between the cog refactor and its callers.' },
]

// ---- Phase 1: Map --------------------------------------------------------
phase('Map')
const maps = await parallel(AREAS.map(a => () =>
  agent(
    `Read and map the 9to5 subsystem: ${a.files}. Produce a concise structured map: each module's purpose, key public functions (name + 1-line), the threads/processes it touches, external I/O (files, network, subprocess), and the 3-5 riskiest spots an auditor should scrutinize. Be precise with file:line. This map seeds a deep audit.`,
    { label: `map:${a.key}`, phase: 'Map' }
  )
))
const mapDigest = AREAS.map((a, i) => `### ${a.key}\n${maps[i] || '(no map)'}`).join('\n\n')

// ---- Phase 2+3: Audit -> Verify (pipeline, no barrier) -------------------
// Each finder runs, and its findings flow straight into adversarial verification
// without waiting for the other finders.
const FINDERS = [
  ...AREAS.map(a => ({
    key: `area:${a.key}`,
    prompt: `You are a world-class auditor doing an EXHAUSTIVE review of this 9to5 subsystem:\n${a.files}\n\nRead every listed file fully. Find EVERY genuine defect across ALL categories (bug, concurrency, error-handling, resource-leak, security, merge-artifact, contract, windows, data-integrity, config, test-gap, dead-code). This branch is a fresh 4-way merge, so watch for semantic-merge breakage especially. Report only real issues with concrete runtime impact, each with file:line evidence and a precise fix. Subsystem map for context:\n\n${mapDigest}`,
  })),
  ...LENSES.map(l => ({ key: `lens:${l.key}`, prompt: `You are a specialist auditor. Sweep the WHOLE 9to5 repo through ONE lens:\n\n${l.prompt}\n\nRead the actual code (don't guess). Report only real issues with file:line evidence and a precise minimal fix. Repo map for orientation:\n\n${mapDigest}` })),
]

const verifyFinding = (finding) =>
  agent(
    `Adversarially verify this audit finding. DEFAULT TO is_real=false unless you can prove, by reading the actual code, that it is a genuine defect with real runtime/correctness/security impact (not intended behavior, not already-handled, not speculative).\n\nFINDING:\n${JSON.stringify(finding, null, 2)}\n\nOpen the cited file and surrounding code. Confirm or refute with specific reasoning citing the real code path.`,
    { label: `verify:${(finding.file || '?').split(/[\\/]/).pop()}`, phase: 'Verify', schema: VERDICT, effort: 'high' }
  ).then(v => ({ finding, verdict: v })).catch(() => null)

// Process finders in SMALL BATCHES so we never burst 16 heavy agents at once
// (that tripped a server-side rate limit on the first run). Each batch: finders
// run, their findings verify, then the next batch starts.
const CHUNK = 3
const verified = []
for (let i = 0; i < FINDERS.length; i += CHUNK) {
  const batch = FINDERS.slice(i, i + CHUNK)
  log(`audit batch ${Math.floor(i / CHUNK) + 1}/${Math.ceil(FINDERS.length / CHUNK)}: ${batch.map(b => b.key).join(', ')}`)
  const batchRes = await pipeline(
    batch,
    f => agent(f.prompt, { label: f.key, phase: 'Audit', schema: FINDINGS, effort: 'high' }),
    (res) => {
      const findings = (res && res.findings) || []
      if (!findings.length) return []
      return parallel(findings.map(finding => () => verifyFinding(finding)))
    }
  )
  verified.push(...batchRes.flat().filter(Boolean))
}

const confirmed = verified.filter(Boolean)
  .filter(x => x.verdict && x.verdict.is_real && x.verdict.confidence >= 0.6)
  .map(x => ({ ...x.finding, severity: x.verdict.corrected_severity !== 'not-a-bug' ? x.verdict.corrected_severity : x.finding.severity, refined_fix: x.verdict.refined_fix || x.finding.suggested_fix, verify_reasoning: x.verdict.reasoning }))

log(`confirmed ${confirmed.length} real findings (from ${verified.flat().filter(Boolean).length} candidates)`)

// ---- Phase 4: Synthesize -------------------------------------------------
phase('Synthesize')
const synth = await agent(
  `You are the lead auditor. Here are ${confirmed.length} adversarially-confirmed findings from a deep audit of the 9to5 codebase (JSON):\n\n${JSON.stringify(confirmed, null, 2)}\n\nProduce the final triage: (1) dedupe findings that are the same root issue, (2) order by severity then blast-radius, (3) for each, give a crisp title, file:line, why-it-matters, and the exact minimal fix. (4) Call out any finding that is risky to fix blindly. Return clear markdown the implementer will act on directly.`,
  { label: 'synthesize', phase: 'Synthesize', effort: 'high' }
)

return { confirmed_count: confirmed.length, confirmed, report: synth }
