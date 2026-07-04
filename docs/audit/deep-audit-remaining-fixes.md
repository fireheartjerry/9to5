# 9TO5 Deep-Audit — Remaining Fixes Spec (Medium + Low)

> **Status:** The two HIGH-severity findings from the deep audit are ALREADY FIXED on this
> branch (webdash unauthenticated data routes; validation-cache 120s timeout). This spec
> covers **every remaining medium and low finding** for a follow-up implementation pass.
> Each item is adversarially-verified (a skeptic confirmed it against the real code).
>
> **How to use this doc:** work top-down (medium before low). Every item is independent —
> fix and verify one at a time. Items flagged **RISKY TO FIX BLINDLY** need care: read the
> note, do not auto-apply. Prefer the smallest change that removes the defect; match local
> style; run `python tools/dev.py check <file>` after each edit, then the mapped tests.

**Total items in this spec:** 31 (13 medium, 18 low)

## Already fixed (do NOT redo)

- **H1 — webdash data routes now token-gated.** `notifications/webdash.py` `do_GET` requires
  the per-run token on `/api/state|/api/events|/api/raw` (via `?token=` or `X-9to5-Token`);
  the HTML shell bootstraps the token from the URL. Client JS + startup URL updated. Regression
  test: `tests/control/test_webdash_control.py::TestControlToken::test_token_gates_data_gets`.
- **H2 — validation DAG no longer bounded by the git timeout.** New knob
  `VALIDATION_NODE_TIMEOUT_SECONDS` (default 1800) in `platform_core/app_config/llm.py`;
  `validation_cache._run_command` uses it instead of `GIT_TIMEOUT_SECONDS`.

## Known duplicate / related (already collapsed here)

- The fsync durability finding was reported twice (`fsio.py:75` and `fsio.py:64-82 via task_io`).
  Collapsed into **one** item below (M: task-state fsync).
- 'resume selection nondeterministic' (M) and 'lexicographic started_at sort' (L) are RELATED
  but DISTINCT — both are listed; a shared `__fork_` skip guard helps both. See the two
  `state/task_io.py` items.

---


## MEDIUM severity

### 1. sanitizeVerify allows unquoted `python -c` bodies to bypass the AST safety scan

- **Severity:** medium  |  **Category:** security
- **Location:** `agents/verifier_sanitize.py:112`
- **:warning: RISKY TO FIX BLINDLY:** Tighten carefully: over-aggressive fail-closed can drop legitimate quoted one-liners that already validate.

**What's wrong (impact):** The `python -c` AST safety validator only fires when the body is wrapped in a single matching quote: the regex requires `(['"])(.*)\1\s*$`. A `python -c` command whose body is NOT quote-wrapped in a way that regex captures (e.g. the verify cmd is authored with the code unquoted, or with mismatched/escaped quoting so the anchored group fails) makes `m` None. When `m is None`, the code only applies the shell-metacharacter denylist `[;&|`\n]|\$\(`; a `python -c` body using none of those (e.g. `python -c import shutil,sys; shutil.rmtree(sys.argv[1])` passed as a single token stream without shell metachars, or an import of a non-stdlib/project module) is NOT ast-validated and passes sanitization. The whole point of `_validatePythonOneliner` (blocking `os.system`, `rmtree`, `eval`, non-stdlib imports) is silently skipped for the unquoted shape, so a confused/hostile brain-authored verify can run a destructive or project-importing `python -c` that the quoted path would have dropped.

**Evidence:**

```
verifier_sanitize.py:112 `m = re.match(r"""(?:py|python|python3)\s+-c\s+(['\"])(.*)\1\s*$""", cmd, re.DOTALL)` then line 113 `if m and not _validatePythonOneliner(...)`. Line 117 `if m is None and re.search(r"[;&|`\n]|\$\(", cmd)` is the ONLY other gate -- a `python -c` with an unquoted/oddly-quoted body and no shell metachars reaches `return verify` unvalidated.
```

**Suggested fix:** Detect the `python -c` shape independent of quoting and fail closed when the body cannot be reliably extracted for AST validation. Concretely, after the arg-vector split (or before returning), if argv matches interpreter + `-c`, take the token following `-c` as the code and run `_validatePythonOneliner` on it; if the split produced extra trailing tokens after the -c body, or the body cannot be parsed, DROP the verify (return _targetsOnly) rather than falling through to the metachar-only check. This closes the single-token `__import__("shutil").rmtree(...)` / `__import__("agents.executor")` bypass while leaving legitimately quoted one-liners (already AST-validated) untouched.

**Verifier note:** Verified against the real code in agents/verifier_sanitize.py:112-119 and the execution path in agents/verification.py.

MECHANISM CONFIRMED: The AST validator `_validatePythonOneliner` fires ONLY when `m` is truthy, and `m` comes from `re.match(r"(?:py|python|python3)\s+-c\s+(['\"])(.*)\1\s*$")` — an anchored group requiring the whole body to be wrapped in one matching quote. A `python -c` whose body is not quote-wrapped in that exact shape makes `m is None`. The only other gate for `m is None` is the metachar denylist `re.search(r"[;&|`\n]|\$\(")`. A body with none of those metachars falls straight through to `return verify` with NO AST scan.

I proved a WORKING bypass. verification.py:runReceipt -> _splitCmd (shlex non-posix, whitespace_split) -> _runVector (subprocess.Popen shell=False, arg-vector).

---

### 2. check_workflow.py opens workflow JSON without encoding — cp1252 UnicodeDecodeError on non-ASCII content

- **Severity:** medium  |  **Category:** windows
- **Location:** `check_workflow.py:51`

**What's wrong (impact):** validateWorkflow() opens the workflow definition file with `workflow_file.open()` and no `encoding=` argument. On Windows, Path.open() text mode defaults to `locale.getpreferredencoding()` which is cp1252 on a US/EU Windows 11 box. Workflow definition JSON is authored by the Ollama brain / operators and routinely contains non-ASCII (emoji in step descriptions, en-dashes, smart quotes, accented paths). Any such byte outside cp1252 raises UnicodeDecodeError, which is NOT caught here (the try/except only guards workflow_file.exists()), so `python check_workflow.py --workflow-file <path>` crashes with a traceback instead of returning a clean pass/fail. This tool is the acceptance gate for bug-fixing workflows, so a decode crash reports the workflow as failed/erroring even when deliverables are present.

**Evidence:**

```
with workflow_file.open() as f:
        workflow = json.load(f)

(no encoding= argument; open() text-mode default on Windows is cp1252, and json.load does not force utf-8. Contrast the rest of the repo which consistently passes encoding="utf-8", e.g. state/task_io.py:75 `json.loads(p.read_text(encoding="utf-8"))`, workflows/registry.py:117, agents/executor_env.py:213.)
```

**Suggested fix:** Change line 51 to `with workflow_file.open(encoding="utf-8") as f:` (or `workflow = json.loads(workflow_file.read_text(encoding="utf-8"))`), matching the utf-8 discipline used throughout the repo, including sibling tools check_bugs.py and check_code_changes.py.

**Verifier note:** Confirmed by reading check_workflow.py. Line 51 `with workflow_file.open() as f:` opens in text mode with no encoding=; json.load(f) at line 52 reads bytes decoded via the file object's default, which on Windows is locale.getpreferredencoding() = cp1252 on typical US/EU Windows 11. Any byte outside cp1252 (raw emoji, en-dash, smart quotes, accented chars, or UTF-8-encoded content) raises UnicodeDecodeError. That call is NOT guarded: the only try/except-equivalent is the `if not workflow_file.exists()` check at lines 47-49 which returns before the open; json.load is unguarded and main() (lines 91-95) does not wrap validateWorkflow. So the tool crashes with a traceback and non-zero exit instead of a clean pass/fail. This tool is a bug-fixing-workflow acceptance gate, so a decode crash reads as the workflow failing even when deliverables exist.

---

### 3. tunnel_providers._download_binary fetches and executes a vendor binary with no integrity/checksum verification

- **Severity:** medium  |  **Category:** security
- **Location:** `notifications/tunnel_providers.py:76-85`

**What's wrong (impact):** CloudflaredProvider.ensure_available downloads cloudflared from a GitHub 'latest/download' URL via urllib.request.urlretrieve, marks it executable (chmod +x), and TunnelManager then runs it as a subprocess that exposes the local dashboard to the public internet. There is no checksum, signature, or TLS-pinning verification of the downloaded artifact. A MITM on the download (or a compromised release asset / DNS) results in an attacker-controlled binary being executed on the host with the user's privileges. The 'latest' URL also means the exact fetched artifact is not pinned.

**Evidence:**

```
tunnel_providers.py:80 `urllib.request.urlretrieve(url, dest)` then :81 `dest.chmod(... | S_IXUSR | S_IXGRP | S_IXOTH)`; the URL is `.../releases/latest/download/cloudflared-{os}-{arch}` (:120-121). CloudflaredProvider.start (:127-130) then Popens that binary. No hashlib/sha check anywhere in the download path.
```

**Suggested fix:** In CloudflaredProvider, pin a specific cloudflared version (replace the 'latest' URL with a fixed tag) and ship the expected per-(os,arch) SHA-256 in config. In _download_binary (or a cloudflared-specific wrapper), after urlretrieve compute hashlib.sha256 of the downloaded file and compare against the expected digest; if it mismatches, delete the file, log a warning, and return False (so ensure_available fails and TunnelManager demotes to the next provider) — do NOT chmod/execute. This keeps HTTPS-to-github.com as the transport but adds integrity verification and reproducible pinning.

**Verifier note:** Confirmed against the real code. notifications/tunnel_providers.py:76-85 (_download_binary) calls urllib.request.urlretrieve(url, dest) with no hashlib/sha/signature check, then dest.chmod(... | S_IXUSR | S_IXGRP | S_IXOTH). CloudflaredProvider.ensure_available (110-125) builds an unpinned URL: releases/latest/download/cloudflared-{os_token}-{arch}{suffix} (120-121) and passes it to _download_binary. CloudflaredProvider.start (127-130) then _spawn()s that binary as a subprocess, and the whole module's purpose (docstring, TunnelManager) is to expose the local dashboard to the public internet. I grep-confirmed no hashlib/checksum logic exists in the download path. The path is live in production: run_phase_mixin.py:214-220 starts TunnelManager whenever config.WEB_DASHBOARD is set (a normal prod config, only gated off for sim/fuzz/e2e).

---

### 4. Tunnel binary download has no timeout — urlretrieve can hang the tunnel supervisor thread indefinitely

- **Severity:** medium  |  **Category:** error-handling
- **Location:** `notifications/tunnel_providers.py:80`

**What's wrong (impact):** `_download_binary` calls `urllib.request.urlretrieve(url, dest)` with no timeout. urlretrieve uses the default socket timeout, which is None (block forever) unless a global `socket.setdefaulttimeout` was set — and a grep confirms it never is anywhere in the repo. If the GitHub release CDN stalls after the TCP handshake (common on flaky networks / captive portals), the download blocks forever. This runs inside `CloudflaredProvider.ensure_available` → `_run_provider_session` → the `tunnel-sup` daemon thread's `_supervise` loop. A hung download wedges the whole tunnel supervisor: no fallback provider is ever tried (the demotion/backoff logic at tunnel.py:214 is never reached because `_run_provider_session` never returns), and `stop()` (tunnel.py:82) can only `join(timeout=2.0)` — the daemon keeps blocking. The public dashboard URL silently never appears. Every other network probe in this file (`probe`) correctly passes `timeout=`; this one download path is the gap.

**Evidence:**

```
def _download_binary(url, dest):
    ...
    urllib.request.urlretrieve(url, dest)   # noqa: S310 -- pinned vendor URL
# grep for socket.setdefaulttimeout across repo -> no matches, so default is None (block forever)
```

**Suggested fix:** Replace urlretrieve with a bounded urlopen+copy in _download_binary:\n\n    import shutil as _shutil  # already imported at module top as shutil\n    req = urllib.request.Request(url, headers={\"User-Agent\": \"9to5-dl\"})\n    with urllib.request.urlopen(req, timeout=60) as r, open(dest, \"wb\") as f:  # noqa: S310\n        shutil.copyfileobj(r, f)\n\nUse a literal timeout (e.g. 60s) since config.TUNNEL_DOWNLOAD_TIMEOUT does not currently exist; a stalled CDN then raises after the timeout, the existing except clause logs and returns False, ensure_available returns False, and the supervisor's _handle_session_end demotes to the next provider.

**Verifier note:** Confirmed by reading the code. tunnel_providers.py:80 calls urllib.request.urlretrieve(url, dest) with no timeout arg. urlretrieve inherits the global default socket timeout, and a repo-wide grep for setdefaulttimeout returns zero matches, so the default is None (block forever). A mid-transfer CDN stall (server accepts the TCP connection then sends no bytes) blocks the socket recv indefinitely; connection-refused/DNS failures raise promptly and are caught, so the hang specifically requires a post-handshake stall.\n\nThe call path is real: CloudflaredProvider is the primary/first provider (default_providers, line 217) and auto-download is its documented main path when cloudflared is not on PATH and not cached (ensure_available lines 110-125).

---

### 5. FeedbackView Skip button never skips — always replies with a usage string instead of skipping the current subtask

- **Severity:** medium  |  **Category:** bug
- **Location:** `notifications/views_feedback.py:59-68`

**What's wrong (impact):** The persistent FeedbackView's Skip button calls slash._runControl(interaction, "skip") with NO subtask arg. _runControl builds commands.Command("skip", "") and calls applyCommand, whose skip branch does `if not _SKIP_ID_RE.match(cmd.arg): return "usage: !skip st-00N ..."`. Since the arg is empty, the regex never matches, so the button ALWAYS returns the usage help and never queues a skip op. Every other Skip surface (ControlPanelView.skip, BlockedView.skip) correctly uses _skipCurrent(), which resolves the next pending subtask id. FeedbackView regressed by routing through the raw spine without a subtask id.

**Evidence:**

```
views_feedback.py:63 `await slash._runControl(interaction, "skip")` (empty arg). commands.py:335-337: `if n == "skip": if not _SKIP_ID_RE.match(cmd.arg): return "usage: `!skip st-00N` ..."`. Confirmed _SKIP_ID_RE.match("") is False, so the skip op is never pushed. Compare views_control.py:66-89 _skipCurrent which targets `next((s for s in state.subtasks if s['status']=='pending'))`.
```

**Suggested fix:** In notifications/views_feedback.py, change FeedbackView.skip to call the shared helper instead of the raw spine: import _skipCurrent (from notifications.views_control) and replace `await slash._runControl(interaction, "skip")` with `await _skipCurrent(interaction, "feedback")`. This resolves the next pending subtask id and passes a valid `st-00N` arg to applyCommand, matching ControlPanelView/BlockedView.

**Verifier note:** Verified the full code path. FeedbackView.skip (notifications/views_feedback.py:63) calls slash._runControl(interaction, "skip") with no arg, so arg defaults to "". _runControl (slash.py:64) builds commands.Command("skip", "") and calls applyCommand. The skip branch in commands.py:335-338 does `if not _SKIP_ID_RE.match(cmd.arg): return "usage: \`!skip st-00N\`..."`. _SKIP_ID_RE = re.compile(r"^st-\d{3}$") (commands.py:33), and matching against "" returns None (falsy), so applyCommand returns the usage help string and never reaches bus.pushOp. Result: the FeedbackView Skip button always replies with usage text and never queues a skip op.

---

### 6. Authoritative task JSON is written without fsync — a crash can truncate the only source-of-truth file with no .bak recovery

- **Severity:** medium  |  **Category:** data-integrity
- **Location:** `platform_core/core/fsio.py:75`
- **:warning: RISKY TO FIX BLINDLY:** On Windows the parent-dir fsync is a no-op/unavailable; guard it or it raises.

**What's wrong (impact):** TaskState.save() (state/task_io.py:67) uses fsio.atomicWriteText, which does tmp.write_text() then os.replace() with NO fsync on the temp file or the parent directory. os.replace is atomic w.r.t. concurrent readers, but not durable: after a power loss / hard crash between write and the filesystem flushing data pages, the renamed file can be present but zero-length/truncated on ext4 (data=writeback) and some Windows configs. Unlike updateJson (which preserves corrupt content as <name>.bak via _readForUpdate), the task-save path has NO .bak fallback, and loadSafe()/iterStored() SILENTLY skip a corrupt/empty file — so the loss is invisible and unrecoverable for the run's single authoritative state file.

**Evidence:**

```
fsio.py:74-76 `tmp.write_text(text, encoding=encoding); _atomicReplace(tmp, p, ...)` — no os.fsync anywhere in fsio.py (grep for fsync returns no matches). task_io.py:58-68 save() calls atomicWriteText directly (not updateJson), so it never gets the .bak preservation. task_io.py:85 loadSafe swallows corruption; task_io.py:106-108 iterStored silently skips corrupt files.
```

**Suggested fix:** Give the state-store save a durable path: in fsio, add an atomicWriteText variant (or a durable=True flag) that opens the temp with a real fd, writes, flush()es, os.fsync(fd), closes, then os.replace; on POSIX also open the parent dir and os.fsync its fd after the replace (no-op/skip on Windows where directory fds aren't fsync-able). Have state/task_io.save() use that durable path. As a cheaper complementary safeguard, write the prior good task JSON to <id>.json.bak before swapping so a truncated write is recoverable, mirroring updateJson's _readForUpdate behavior, and have loadSafe/load fall back to the .bak when the primary is empty/corrupt instead of silently returning None.

**Verifier note:** All cited code is accurate. atomicWriteText (platform_core/core/fsio.py:74-76) does tmp.write_text() then _atomicReplace()->os.replace() with NO fsync; a repo-wide grep for "fsync" returns zero matches, confirming durability is nowhere enforced. state/task_io.py save() (lines 58-68) calls fsio.atomicWriteText directly, so it bypasses updateJson's _readForUpdate .bak preservation (fsio.py:105-126) — the task-save path has no .bak safety net that updateJson deliberately provides. On the read side, loadSafe (task_io.py:81-86) swallows all exceptions returning None, and iterStored (task_io.py:95-116) silently skips corrupt/unparseable files (only a once-per-scan WARNING count), so a truncated authoritative <id>.json disappears invisibly with no recovery.

---

### 7. doctor/health model-readiness check false-greens when a different tag of the same model is pulled

- **Severity:** medium  |  **Category:** config
- **Location:** `platform_core/ops/doctor.py:44`

**What's wrong (impact):** check_ollama strips the tag off both the installed model names and the configured OLLAMA_MODEL before comparing (splits on ':'), so a user who has `qwen2.5:14b` pulled while config wants `qwen2.5:7b` is reported READY even though the correct weights are absent. Because check_ollama is marked hard=True, this makes a genuine hard blocker report green, and the subsequent run silently uses the wrong model or fails at first brain call. health._ollama (health.py:42) does the opposite — it compares the FULL name including tag — so the two readiness surfaces disagree about the same fact.

**Evidence:**

```
doctor.py:44-46 `names = {(m.get("model") or m.get("name") or "").split(":")[0] for m in models}` / `want = config.OLLAMA_MODEL.split(":")[0]` / `if want in names: return _check(..., True, ...)`. check_embedder (doctor.py:69-71) has the identical tag-stripping defect.
```

**Suggested fix:** In doctor.py check_ollama and check_embedder, compare full tagged identifiers like health._ollama does. Build `names = {(m.get("model") or m.get("name") or "") for m in models}` and test `config.OLLAMA_MODEL in names`. If a tag-tolerant fallback is desired, only strip tags when config.OLLAMA_MODEL itself has no explicit `:` tag; otherwise require an exact tagged match so the "X ready" message is truthful and the hard blocker surfaces.

**Verifier note:** Confirmed against the real code. doctor.py:44-46 in check_ollama() strips the tag off both installed model names AND config.OLLAMA_MODEL via `.split(":")[0]`, then tests family membership: `names = {(m.get("model") or m.get("name") or "").split(":")[0] for m in models}` / `want = config.OLLAMA_MODEL.split(":")[0]` / `if want in names: return _check("Ollama brain", True, hard=True, ...)`. check_embedder (doctor.py:69-71) has the identical tag-stripping. By contrast health.py:42 compares the FULL tagged name: `if config.OLLAMA_MODEL not in models`. config default is `qwen2.5-coder:7b` (platform_core/app_config/llm.py:40), i.e. tags are real and configured. So with `qwen2.5-coder:14b` pulled but config wanting `qwen2.5-coder:7b`, doctor returns ok=True and even prints the misleading detail `"qwen2.5-coder:7b ready"` when that exact weight set is absent.

---

### 8. Discord poll cursor advanced before commands are applied; unhandled apply error drops control commands and can abort a gate wait

- **Severity:** medium  |  **Category:** error-handling
- **Location:** `platform_core/orchestration/control_mixin.py:65`

**What's wrong (impact):** In the degraded REST poller, `bus.setSeen(latest)` commits the cursor forward (line 66-67) BEFORE the per-message `commands.applyCommand(...)` loop runs (line 75). Two failure modes follow: (1) if `applyCommand` raises (e.g. `bus.pushOp` -> control_store SQLite error, or any parse issue), the message id is already marked seen, so on the next poll `fetchMessagesAfter(bus.getSeen())` skips it -- the operator's `!add`/`!skip`/`!intent` is silently and permanently lost; (2) the apply loop has NO try/except, so the exception propagates out of `_translateDiscord`, out of `on_tick`, and out of `ControlBus.waitDecision`. During a plan/pre_pr gate the on_tick is exactly `_translateDiscord`, so a transient control-store hiccup crashes the gate wait and routes the whole run through `_handleRunCrash` instead of continuing to wait for approval.

**Evidence:**

```
def _translateDiscord(...):
    ...
    msgs, latest = discord.fetchMessagesAfter(bus.getSeen())
    if latest != bus.getSeen():
        bus.setSeen(latest)              # cursor advanced FIRST
    for m in msgs:
        ...
        commands.applyCommand(bus, state, cmd, source_msg_id=m.get("id"))  # if this raises, message already 'seen' AND exception escapes on_tick
```

**Suggested fix:** In _translateDiscord, apply first then advance the cursor, and isolate per-message failures. Replace the early setSeen with: iterate msgs, wrap each applyCommand in try/except that logs+continues, track last_ok = m.get('id') on success (and skip advancing past a message that raised), then bus.setSeen(last successfully-processed id) after the loop. Because pushOp/decisions are idempotent via source_msg_id, re-polling an un-acked message next tick is safe and cannot double-apply. Minimal variant: wrap the whole apply loop in try/except (log+continue) and move setSeen(latest) to run only after the loop completes without an unhandled exception -- this alone stops both the lost-command skip and the gate-wait crash.

**Verifier note:** Code-verified both failure modes. (1) In platform_core/orchestration/control_mixin.py:_translateDiscord, bus.setSeen(latest) commits the poll cursor forward (lines 66-67) BEFORE the per-message loop (68-75) calls commands.applyCommand. applyCommand routes !skip/!add/!retry/intel to bus.pushOp and !approve/!reject/!pause to bus.decide/requestPause, all of which go through control_store._tx (BEGIN IMMEDIATE), which re-raises on any sqlite3 error (control_store.py:129-132, e.g. OperationalError 'database is locked' after busy_timeout, or a disk/IO error). If any message in the batch raises, the cursor is already at latest, so the next fetchMessagesAfter(getSeen()) skips every un-applied message in that batch -- the operator command is silently and permanently lost. (2) The apply loop has NO try/except, so the exception escapes _translateDiscord.

---

### 9. Parallel execution with worktree isolation disabled runs concurrent Claude subprocesses in the same working tree with no file-disjointness guard

- **Severity:** medium  |  **Category:** data-integrity
- **Location:** `platform_core/orchestration/run_loop.py:191`

**What's wrong (impact):** In `_parallelIteration`, the file-disjointness safety (`parallel_safety.safeParallelSet`, which serializes any subtasks whose planner-authored `files_touched` sets are unknown or overlapping) is applied ONLY when `WORKTREE_ISOLATION_ENABLED` is true. When isolation is disabled but `parallelism > 1`, the batch is `ready[:parallelism]` with no disjointness check and no per-subtask worktree, so `_handleParallelBatch` derives every worker's cwd via `_execCwd` (= the shared `work_dir` for non-self-ref runs) and launches up to `parallelism` concurrent Claude CLI subprocesses editing the SAME tree. Two workers touching the same file race on the working copy (lost edits, interleaved writes, git-index contention), and the evidence gate's git-diff facts become non-deterministic across workers.

**Evidence:**

```
if getattr(config, "WORKTREE_ISOLATION_ENABLED", False):
    batch = parallel_safety.safeParallelSet(state, ready, parallelism)
else:
    batch = ready[:parallelism]        # NO disjointness / serialization guard
...
# _handleParallelBatch non-isolate branch:
ctx = self._execCwd(state, sid, work_dir)   # == shared work_dir for all workers
```

**Suggested fix:** In platform_core/orchestration/run_loop.py `_parallelIteration`, apply the disjointness guard unconditionally instead of gating it on isolation. Replace the if/else at lines 191-194 with `batch = parallel_safety.safeParallelSet(state, ready, parallelism)` for both branches (it fails open to a single pick, so it never regresses safety and does not require worktrees). Alternatively, clamp `parallelism = 1` in run_loop_mixin.runExecutionLoop whenever `WORKTREE_ISOLATION_ENABLED` is false so the shared-tree path is always serial.

**Verifier note:** Every technical claim in the finding is verified against the code. In platform_core/orchestration/run_loop.py:191-194, `_parallelIteration` applies `parallel_safety.safeParallelSet` (which serializes overlapping/unknown `files_touched` sets) ONLY when `WORKTREE_ISOLATION_ENABLED` is true; the else branch is `batch = ready[:parallelism]` with no disjointness/serialization guard. `_parallelIteration` itself is reached whenever `parallelism > 1` (run_loop_mixin.py:301,309), fully DECOUPLED from `WORKTREE_ISOLATION_ENABLED`. In `_handleParallelBatch` (run_loop_mixin.py:194-214), the non-isolate branch derives every worker's ctx via `self._execCwd(state, sid, work_dir)`, and `_execCwd` (run_loop.py:52-60) returns the shared `work_dir` for the normal non-self-referential, fabric-off case.

---

### 10. state/perf.jsonl grows unbounded — no rotation and not covered by the retention sweep

- **Severity:** medium  |  **Category:** resource-leak
- **Location:** `platform_core/runtime/perf.py:26`

**What's wrong (impact):** perf.record() appends one JSON line to a single global file state/perf.jsonl on every call, and it is called on many hot paths: once per subtask verification (perf.record via webdash_snapshot), once per epoch fingerprint (epoch.py:121, which runs at run start AND every subtask boundary via diverged()), and once per webdash /api/state snapshot (webdash.py:211, polled by every open browser tab). The file is never rotated, capped, or truncated. summarize() only reads the tail (perf.py:41) so nothing ever prunes the head. The retention sweep (platform_core/ops/retention.py:123 sweepAll) prunes blackboard *.jsonl, compaction ctx-*.txt, and archives terminal task JSON, but has NO entry for perf.jsonl. For a system explicitly designed to run autonomously 9-to-5 for long stretches, this is monotonic unbounded disk growth on the busiest write path.

**Evidence:**

```
perf.py:32  with path.open("a", encoding="utf-8") as fh: fh.write(json.dumps(row,...) + "\n")  — appended per subtask/fingerprint/snapshot; retention.py sweepAll() covers only sweepBlackboard()/sweepCompaction()/archiveTerminalTasks(), none of which touch state/perf.jsonl.
```

**Suggested fix:** In platform_core/runtime/perf.py, replace the raw `with path.open("a")...` block in record() with a call to platform_core.core.jsonl_io.appendRecord(path, row, max_bytes=PERF_TELEMETRY_MAX_BYTES), mirroring notifications/audit.py:43 (which passes config.AUDIT_MAX_BYTES). Add a PERF_TELEMETRY_MAX_BYTES config knob (e.g. ~1-5 MB) next to AUDIT_MAX_BYTES so the file rotates to perf.jsonl.1 once it exceeds the cap. Keep the try/except so record() stays fail-open. This bounds disk to roughly 2x the cap and matches the existing audit-log rotation pattern; no change to summarize() is needed since it already reads only the tail.

**Verifier note:** Confirmed against the actual code. perf.record (platform_core/runtime/perf.py:26-35) appends one JSON line via a raw `path.open("a")` write to a single global file state/perf.jsonl with NO size check, rotation, or cap. summarize (perf.py:38-41) only reads the tail (`splitlines()[-limit:]`), so reads never prune the head — nothing truncates the file. retention.py sweepAll (lines 123-136) invokes only sweepBlackboard (`*.jsonl` in config.BLACKBOARD_DIR, not state/), sweepCompaction (`ctx-*.txt`), and archiveTerminalTasks (`*.json`) — none of these match or touch state/perf.jsonl, so the retention sweep genuinely does not cover it. The hot-path callers cited are real: epoch.py:121 (fingerprint(), invoked by both snapshot() and diverged()), webdash.py:211 (per /api/state snapshot), plus memory/retrieval.py (x3) and validation_cache.py (x2).

---

### 11. safety_gate keeps a broken/hanging core edit when the clean baseline also fails or times out

- **Severity:** medium  |  **Category:** bug
- **Location:** `selfmod.py:144-155`
- **:warning: RISKY TO FIX BLINDLY:** Self-modification trust boundary. An existing test (tests/.../test_selfmod.py) asserts the CURRENT keep-on-double-fail behavior and must be updated deliberately, not deleted.

**What's wrong (impact):** When the suite fails WITH the core change, the gate stashes the change and re-runs the suite on baseline; if the baseline ALSO fails it concludes 'pre-existing/flaky' and KEEPS the core change (kept_despite_failure). But _default_test_runner returns passed=False on TimeoutExpired (30-min timeout, line 60) exactly as it does for a real failure. If the self-edit introduces a hang/infinite loop in core code, the first run times out (fail). If the stashed baseline then ALSO fails for an UNRELATED reason -- a flaky test, an env hiccup, or its own timeout -- the causality logic mis-attributes the failure as pre-existing and ships the hanging edit. Two independent failures (very common with a 30-min suite) collapse to 'keep the change'.

**Evidence:**

```
selfmod.py:150 `_unstash_core(work_dir, restore=True)` then `return {... "reverted": False, "kept_despite_failure": True ...}`. _default_test_runner:63-64 returns (False, 'test runner error') on any exception incl. TimeoutExpired, indistinguishable from a genuine assertion failure.
```

**Suggested fix:** In _default_test_runner, catch subprocess.TimeoutExpired separately and return a distinct outcome (e.g. a 3-state enum: PASSED / FAILED / TIMEOUT, or a (passed, status, tail) tuple) instead of collapsing everything to (False, ...). In safety_gate, on a first-run TIMEOUT with the change present, never enter the keep path — revert immediately (a hang in core code must fail closed). For the FAILED-vs-baseline causality branch, only conclude "pre-existing" and keep when the baseline failure is itself FAILED (not TIMEOUT) and its failure signature matches the with-change failure; if signatures differ or either run timed out, fail closed and revert.

**Verifier note:** Verified against the real code path. Production calls selfmod.safety_gate with no injected runner (platform_core/orchestration/control_mixin.py:322), so _default_test_runner is used. _default_test_runner (selfmod.py:56-64) wraps subprocess.run with timeout=1800 in a bare try/except that returns (False, "test runner error: {e}") for ANY exception, including subprocess.TimeoutExpired — a timeout is bool-collapsed and indistinguishable from a genuine assertion failure. safety_gate (lines 132-155) then treats passed=False uniformly: it stashes the change, re-runs the baseline, and at line 150-155 if the baseline ALSO returns False it restores the change and returns kept_despite_failure=True. The tests (tests/evolution/test_selfmod.py:78-87) confirm this "keep on double failure" is intended design.

The defect is real but narrower than the finding frames it.

---

### 12. Fork-branch state clones pollute every STATE_DIR scan (phantom runs, ledger double-count, wrong-run resume)

- **Severity:** medium  |  **Category:** data-integrity
- **Location:** `state/task_io.py:103`

**What's wrong (impact):** iterStored() is the single scanner of STATE_DIR and globs `*.json`, filtering only with _taskShaped() (task_id present + dict meta). The solution-space fork feature writes throwaway branch clones as `state/tasks/{task_id}__fork_{branch}.json` via forkBranchState() (platform_core/orchestration/solution_space.py:36 sets data['task_id']=f'{orig}__fork_{branch}' and the clone's save() targets that path). Those clones are DEEP COPIES of the parent run data, so they are fully task-shaped and pass _taskShaped(). Consequences: (a) loadLatest()/listRecent() surface each fork as a distinct run; (b) experience_runs.backfill_from_store() and compare_run() iterate iterStored() and upsert/count every fork clone as a separate run_id, polluting SIE learning stats with N near-duplicate runs per forked subtask; (c) cleanupForkStates() is best-effort and only runs at the end, so a crash mid-fork leaves the clones behind permanently. This is a semantic gap between the fork feature and the shared scanner introduced across the merge.

**Evidence:**

```
task_io.py:92 `_taskShaped` accepts any dict with task_id+meta; task_io.py:103 `for f in config.STATE_DIR.glob("*.json")` has no suffix filter. solution_space.py:36 `data["task_id"] = f"{state.task_id}{_FORK_STATE_SUFFIX}{branch_id}"` (_FORK_STATE_SUFFIX='__fork_') then TaskState(data).save() writes STATE_DIR/{...__fork_x}.json. experience_runs.py:161 `for _f, data in TaskState.iterStored(): if sync_run(data...)` counts each clone as a run.
```

**Suggested fix:** In iterStored() (state/task_io.py, inside the `for f in config.STATE_DIR.glob("*.json")` loop) skip fork-state clones before parsing: `if "__fork_" in f.name: continue`. Prefer sourcing the marker from a shared constant to avoid drift with solution_space._FORK_STATE_SUFFIX (e.g. define the '__fork_' suffix in a low-level module both import, or re-declare with a comment cross-referencing solution_space.py:26). Alternatively, make forkBranchState write clones outside the scanner's reach (e.g. a state/tasks/.forks/ subdir) so `*.json` never matches them; cleanupForkStates' glob would need the same path update. The iterStored guard is the smaller, safer change and defends every consumer (loadLatest, listRecent, backfill_from_store, compare_run) at the single choke point.

**Verifier note:** All cited code paths verified against the actual source. (1) iterStored() (state/task_io.py:103) globs `*.json` in STATE_DIR and filters only via _taskShaped() (task_io.py:92: dict + task_id + dict meta) — no suffix filter. (2) forkBranchState (platform_core/orchestration/solution_space.py:35-37) deep-copies state.data and sets data["task_id"]=f"{orig}__fork_{branch}". (3) TaskState.path() (state/task_schema.py:114) is `config.STATE_DIR / f"{self.task_id}.json"` with NO validation, so the clone's file lands in STATE_DIR/tasks as `{uuid}__fork_{b}.json`, matching the glob. (4) The clone IS persisted: a branch runs orch._runAttemptLoop(branch_state, ...) (solution_space.py:112-113), and _runAttemptLoop calls state.updateSubtask (execute_mixin.py:178/260/330) → updateSubtask (task_schema.py:344) calls self.save(). So the clone hits disk during the branch window.

---

### 13. loadLatest() resume selection is nondeterministic when two non-terminal tasks share started_at (made reachable by fork clones)

- **Severity:** medium  |  **Category:** bug
- **Location:** `state/task_io.py:129`

**What's wrong (impact):** loadLatest() ranks tasks by key=(0 if terminal else 1, started_at) and keeps the max with strict `>`. Fork-branch clones (see finding #1) copy the parent's meta verbatim, including the identical started_at, and can carry a non-terminal status. When the canonical run and one or more fork clones are both non-terminal with equal started_at, all share the exact same key; the strict `>` means the FIRST one encountered in iteration order wins, and glob() order is filesystem-dependent. A crash-resume / orphan-resume path that calls loadLatest() can therefore adopt a fork-branch clone's state instead of the canonical run — resuming against a throwaway branch's subtask statuses. Even absent forks, two legitimately concurrent runs started in the same second tie-break arbitrarily.

**Evidence:**

```
task_io.py:129 `key = (0 if meta.get("status") in TaskState._TERMINAL else 1, meta.get("started_at", ""))` and :130 `if best_key is None or key > best_key:` — equal keys never replace, so order is glob-dependent. Fork clones (solution_space.py:35 `copy.deepcopy(state.data)`) keep the parent's meta.started_at.
```

**Suggested fix:** Make loadLatest()'s sort key total and deterministic by appending a stable unique final tie-breaker, e.g. key = (0 if meta.get("status") in TaskState._TERMINAL else 1, meta.get("started_at", ""), data.get("task_id", "")). Additionally exclude fork-state clones from resume candidacy by skipping task_ids containing the "__fork_" suffix in iterStored() (or filtering them in loadLatest()), so an orphaned throwaway branch can never be selected as the resume target.

**Verifier note:** Verified against the real code. loadLatest() (state/task_io.py:129-130) ranks candidates by key=(0 if meta.status in _TERMINAL else 1, meta.started_at) and replaces best only on strict `key > best_key`, so equal keys never replace and the winner is whichever equal-key file iterStored yields first. iterStored() (task_io.py:103) uses config.STATE_DIR.glob("*.json"), whose order is filesystem-dependent and unsorted — no stable final tie-breaker exists. The tie is genuinely reachable: forkBranchState (platform_core/orchestration/solution_space.py:35-36) does copy.deepcopy(state.data) and overwrites ONLY data["task_id"], so meta.started_at is byte-identical to the parent; started_at is written with timespec="seconds" (task_schema.py:62), so even legitimately concurrent runs in the same second collide.

---


## LOW severity

### 14. _drainStreaming calls proc.wait() with no timeout after a tree-kill -- can hang the executor thread indefinitely

- **Severity:** low  |  **Category:** resource-leak
- **Location:** `agents/executor_stream.py:273`
- **:warning: RISKY TO FIX BLINDLY:** The cited fix does NOT close the more-likely stdout-loop hang (line ~261); handle that separately.

**What's wrong (impact):** In the streaming drain path, after the timeout Timer fires `_killProcessTree(proc.pid)` and the stdout loop reaches EOF, the code does bounded joins on the stderr/stdin helper threads (`et.join(15.0)`, `wt.join(1.0)`) but then calls `proc.wait()` with NO timeout. If `taskkill /T /F` fails or is slow (e.g. an elevated grandchild, PID reuse, taskkill itself times out at 20s and swallows the exception in `_killProcessTree`), the child never reaches EOF/exit and `proc.wait()` blocks forever. This wedges the worker thread and, under the parallel batch executor, holds a ThreadPoolExecutor slot indefinitely -- the exact orphan/hang class this module was written to fix, reintroduced on the `feed`-enabled path. The non-streaming path (line 342/352) correctly bounds every `communicate` with a timeout; the streaming path does not.

**Evidence:**

```
`_drainStreaming` (executor_stream.py:269-273): `et.join(timeout=15.0)`, `wt.join(timeout=1.0)`, `err = ''.join(err_parts)`, then bare `proc.wait()`. `_killProcessTree` (line 34-42) swallows all exceptions including a taskkill timeout, so a failed kill returns silently and `proc.wait()` has no escape.
```

**Suggested fix:** Bound the wait at line 273 AND acknowledge the stdout-loop can itself block. Minimal safe change at line 273: `try: proc.wait(timeout=15)\n except subprocess.TimeoutExpired:\n     _killProcessTree(proc.pid)\n     try: proc.wait(timeout=5)\n     except subprocess.TimeoutExpired: LOG.warning('child survived tree-kill; abandoning wait for pid %s', proc.pid)`. For completeness the more impactful hang (a surviving grandchild pinning the `for line in proc.stdout` loop at line 261) should also be mitigated — but that is a separate defect from the one this finding cites.

**Verifier note:** Confirmed the cited code path. In `_drainStreaming` (agents/executor_stream.py:220-277), after the stdout loop and bounded helper-thread joins (`et.join(15.0)` line 270, `wt.join(1.0)` line 271), line 273 calls a BARE `proc.wait()` with no timeout. This is a genuine asymmetry: the two sibling wait sites in the same file both bound their wait — the non-streaming path uses `proc.communicate(input=..., timeout=timeout)` (line 342) and the timeout-recovery path uses `proc.communicate(timeout=15)` (line 352). The streaming path does not. `_killProcessTree` (lines 34-42) swallows ALL exceptions, including a `taskkill /T /F` that itself times out at 20s (line 37), so a failed/partial tree-kill returns silently.

---

### 15. logs/hooks.log grows unbounded — appended once per tool-use hook fire, never rotated

- **Severity:** low  |  **Category:** resource-leak
- **Location:** `agents/hooks.py:168`

**What's wrong (impact):** The telemetry hook appends one JSON line to a single logs/hooks.log file on every PreToolUse/PostToolUse dispatch, i.e. on essentially every tool call inside every Claude executor run — the highest-frequency write in the system. There is no RotatingFileHandler, size cap, or truncation, and the retention sweep (platform_core/ops/retention.py) does not prune logs/*.log or logs/guard_alerts.jsonl. Over sustained autonomous operation this file grows without bound. guard_alerts.jsonl (agents/hooks_destructive.py:62) has the same append-forever pattern.

**Evidence:**

```
hooks.py:168  with log_path.open("a", encoding="utf-8") as fh: fh.write(json.dumps(entry) + "\n")  — one line per tool_name per hook fire; no rotation. hooks_destructive.py:62 appends to guard_alerts.jsonl the same way. retention.sweepAll() has no logs/ pruning.
```

**Suggested fix:** Add a logs sweep to retention.sweepAll() that size-caps/truncates logs/hooks.log (and optionally logs/guard_alerts.jsonl) once it exceeds a configured byte threshold, or route logAll's write through a size-capped writer that truncates/rotates when the file exceeds a cap. Minimal option: in logAll (agents/hooks.py:168), before appending, if log_path.exists() and log_path.stat().st_size > CAP, rewrite it keeping only the last N lines. Prefer the retention-sweep route so the hot path stays a plain append.

**Verifier note:** Mechanics confirmed by reading the actual code. agents/hooks.py:168 (logAll) opens hooks.log in append mode and writes one JSON line per invocation. This handler is wired to a PostToolUse hook with matcher ".*" in .claude/settings.json:48-56 and in .codex/hooks.json:42, and is a per-run post/pre hook option in executor.py, plan_prompts.py, and llm.py — so it genuinely fires on essentially every tool call. There is no RotatingFileHandler, size cap, or truncation anywhere on that path. retention.py was read in full: sweepAll() only calls sweepBlackboard (state/ *.jsonl), sweepCompaction (COMPACTION_OFFLOAD_DIR ctx-*.txt), and archiveTerminalTasks (state/ *.json) — it never touches logs/ or hooks.log, so no sweep ever prunes this file. That confirms the unbounded-growth claim.\n\nTwo caveats that reduce severity below the finding's stated 'medium'.

---

### 16. native_executor leaks the launched Windows app on the success path when the spec has no 'close' action

- **Severity:** low  |  **Category:** resource-leak
- **Location:** `agents/native_executor.py:124`
- **:warning: RISKY TO FIX BLINDLY:** Must distinguish launched-vs-connected apps; a blind finally-kill would close user-owned apps that were merely attached.

**What's wrong (impact):** _run_native_actions kills the launched app ONLY inside the per-action except block (native_executor.py:131-135); the success path returns the transcript without terminating anything. The helper nativeActions() appends a 'close' step, but the primary entrypoint runNative() executes spec.get('native_actions') straight from the brain-authored spec (native_executor.py:151), which is not guaranteed to include a 'close'. A spec that does launch + interactions but omits close leaves a live Windows GUI process orphaned after the subtask completes successfully. Bounded to NATIVE_LAYER_ENABLED (off by default) + pywinauto installed, hence low severity, but it is a real orphan-process leak on the happy path.

**Evidence:**

```
native_executor.py:114-137: on success the loop simply `return "\n".join(lines)`; `app.kill()` appears only in the `except` branch (lines 131-135). runNative (line 156) passes brain-authored spec['native_actions'] with no enforced trailing 'close'.
```

**Suggested fix:** In `_run_native_actions`, track whether an app was launched (vs connected) and whether an explicit `close` action ran. Wrap the action loop in try/finally; in `finally`, kill only apps that this call launched AND that were not already closed by a `close` action, leaving `connect`-attached (pre-existing) apps untouched. Do not adopt an unconditional `finally: app.kill()`, which would kill user-owned connected apps and any intentionally-persistent launched apps. Alternatively, if leaving launched apps running on success is intended, document that native specs must include an explicit `close` action for cleanup and leave the code as-is.

**Verifier note:** The mechanical claims are accurate against the code. In `_run_native_actions` (native_executor.py:124-137), the success path does `return "\n".join(lines)` without ever calling `app.kill()`; `app.kill()` appears ONLY in the per-action `except` branch (lines 131-135) and is re-raised. The only success-path termination is an explicit `close` action (lines 99-102). `runNative` (line 151) executes `spec.get("native_actions")` straight from the brain-authored spec with no enforced trailing `close`; the `nativeActions()` helper that appends `close` (line 143) is a separate builder that `runNative` does not call. So a brain-authored spec like `[launch, type, extract]` (no `close`) does leave the launched Windows GUI process alive after a successful subtask — a genuine orphan-process leak on the happy path.

---

### 17. config.set_override reports failure (returns False) even though the knob was live-applied when persistence fails

- **Severity:** low  |  **Category:** contract
- **Location:** `config.py:95`

**What's wrong (impact):** settings.setOverride returns (True, False) on a persist failure — meaning the live registry WAS updated but the file write failed (documented as intentional at settings.py:350-351/372-373). config.set_override collapses this to `return applied and persisted`, i.e. returns False, telling the caller (meta_opt.apply) the override did NOT take effect. But the knob IS live for the current process, so callers that branch on the return (e.g. skipping re-application, or logging 'override rejected') will diverge from reality: the value silently changed the running engine while reporting it didn't. This is a contract mismatch between the two-bool source of truth and the single-bool facade.

**Evidence:**

```
config.py:92-95 `applied, persisted = _settings.setOverride(knob, value)` ... `return applied and persisted`; settings.py:372-373 returns `True, False` on persist exception with comment 'caller decides how loud to be'.
```

**Suggested fix:** In learning/meta_opt.py, consume the two-bool tuple directly instead of the collapsed facade bool, so an applied-but-unpersisted knob is still recorded/logged (as a warning). E.g. change the facade call site to use platform_core.app_config.settings.setOverride returning (applied, persisted), append to `applied` when `applied` is True, and LOG.warning when applied but not persisted. Alternatively, change config.set_override to `return applied` (live-apply is the operative effect) and surface persistence separately, and update its docstring/@AI-MAP. Keep the existing bounds-reject path returning False.

**Verifier note:** Confirmed the two-bool contract: settings.setOverride (platform_core/app_config/settings.py:346-373) live-applies the knob via replace(_SETTINGS,...) at line 358 BEFORE the persistence try/except, then returns (True, False) on a write exception (lines 372-373, documented "caller decides how loud to be"). config.set_override (config.py:92-95) collapses this to `return applied and persisted`, i.e. False, even though the knob is live for the process. So the facade misreports an applied-but-unpersisted change as "did not take effect" — a genuine contract mismatch, as described. However, the real-world impact is smaller than the finding's speculative framing ("skipping re-application", "override rejected"). The ONLY production consumer is learning/meta_opt.py:67: `if config.set_override(knob, val): applied.append(...); LOG.info(...)`.

---

### 18. _train_lora derives the HF base repo id from OLLAMA_MODEL, silently violating I1 base immutability assumption

- **Severity:** low  |  **Category:** contract
- **Location:** `learning/finetune.py:138`

**What's wrong (impact):** `_train_lora` computes the HuggingFace base model to fine-tune as `config.OLLAMA_MODEL.split(":")[0]`. The Ollama model name (e.g. `qwen2.5:7b`) is not a valid HF repo id, and the comment on the same line concedes 'HF repo id is configured separately in practice'. If the mapping is wrong, `AutoModelForCausalLM.from_pretrained(base, ...)` either errors out (caught -> cycle degrades to 'error', so no adapter is produced) or, worse, loads a DIFFERENT base model than the frozen Ollama base the adapter will be layered over at inference (`FROM {config.OLLAMA_MODEL}` in the Modelfile). The rollback/immutability guarantee (invariant I1, enforced by safety.verify_invariants comparing `base_model == OLLAMA_MODEL`) rests on the training base and the inference base being the same weights; this split can silently break that with no invariant catching it, because I1 only checks the stored `base_model` string equals OLLAMA_MODEL, not that the trained-against weights matched.

**Evidence:**

```
Line 138: `base = config.OLLAMA_MODEL.split(":")[0]  # HF repo id is configured separately in practice`. Line 140 uses it as the HF id. Line 88/229 Modelfile uses the full `config.OLLAMA_MODEL` as the inference base. safety.py:59-61 only checks `a["base_model"] != config.OLLAMA_MODEL` (a string equality, not weight identity).
```

**Suggested fix:** Add an explicit config key, e.g. LORA_HF_BASE_REPO (env OLLAMA_HF_BASE / LORA_HF_BASE_REPO) holding the true HuggingFace repo id (e.g. "Qwen/Qwen2.5-Coder-7B"). In _train_lora use it instead of config.OLLAMA_MODEL.split(":")[0], and raise a clear error if it is unset when the real trainer is actually invoked, so the cycle fails loudly with an actionable message rather than guessing an invalid id. Update the inline comment accordingly.

**Verifier note:** Code confirmed at learning/finetune.py:138: `base = config.OLLAMA_MODEL.split(":")[0]`, used directly at lines 139-140 as the HF id for AutoTokenizer/AutoModelForCausalLM.from_pretrained. config default (platform_core/app_config/llm.py:40) is OLLAMA_MODEL="qwen2.5-coder:7b", so the derived base is "qwen2.5-coder" — NOT a valid HuggingFace repo id (real id would be like Qwen/Qwen2.5-Coder-7B). Grep confirms there is NO separate HF-base-repo config key or id-mapping anywhere in the codebase, contradicting the inline comment "HF repo id is configured separately in practice." So on any real GPU host with training enabled (default_trainer gated only by compute.training_enabled() and should_use_gpu()), from_pretrained raises, run_finetune_cycle/run_dpo_cycle catch it and return {"skipped":"error"}.

---

### 19. run_finetune_cycle can pass a None dataset path to the trainer when min_examples is 0

- **Severity:** low  |  **Category:** error-handling
- **Location:** `learning/finetune.py:226`

**What's wrong (impact):** `distill.build` only writes the JSONL and sets `path` when `examples` is non-empty (distill.py:61); otherwise `ds["path"]` is None. `run_finetune_cycle` guards with `if n < need: return skipped`, but if `min_examples`/`LORA_MIN_EXAMPLES` is 0 and the ledger has zero gold examples, `n=0` is not `< 0`, so control falls through to `trainer(ds["path"], ...)` with `ds["path"]=None`, which then feeds `load_dataset("json", data_files=None)` and raises. It is caught and degrades to 'error', but it wastes a training attempt and logs a misleading failure. The same pattern applies to run_dpo_cycle with min_pairs=0.

**Evidence:**

```
distill.py:60-63 leaves `written=None` when `examples` is empty. finetune.py:218 `if n < need` then finetune.py:226 `lora_path = trainer(ds["path"], str(out_dir))`. Default LORA_MIN_EXAMPLES=50 makes this unreachable at defaults, but it is reachable via env/param override to 0.
```

**Suggested fix:** In run_finetune_cycle change the guard to `if n < need or not ds.get(\"path\"): return {\"skipped\": \"not_enough\", \"examples\": n, \"need\": need}` and analogously in run_dpo_cycle: `if n < need or not ds.get(\"path\"): return {\"skipped\": \"not_enough\", \"pairs\": n, \"need\": need}`. This ensures a None dataset path can never reach the trainer even when min_examples/min_pairs is 0.

**Verifier note:** The code path is real and accurately described. distill.build (distill.py:60-64) sets `written=None` and only assigns a path when `out_path is not None and examples` is non-empty, so `ds["path"]` is None on an empty dataset. In run_finetune_cycle, `n = ds["examples"]` is `len(examples)` = 0 when empty (finetune.py:216), and the guard `if n < need` (line 218) with `need=0` evaluates `0 < 0` = False, falling through. Control then reaches `trainer(ds["path"], ...)` at line 226 with a None path, which in the real trainer (_train_lora, line 152/145) calls `load_dataset("json", data_files=None)` and raises. The DPO path (lines 256-264) is identical with min_pairs.

---

### 20. Policy reward wallclock term is permanently zero (unpopulated field)

- **Severity:** low  |  **Category:** data-integrity
- **Location:** `learning/policy.py:58`

**What's wrong (impact):** `compute_reward` reads `row.get("_norm_wallclock")` to compute the wallclock penalty (`w["wallclock"]=0.1`). The rows come from `experience.fetch_subtasks`, which returns raw ledger columns; there is no `_norm_wallclock` column and no code anywhere in the repo sets `_norm_wallclock` on these rows (verified via grep). As a result `norm_wall` is always 0.0 and the wallclock component of the bandit reward is dead weight that never influences arm statistics. The documented reward formula (`- w_wall·norm_wallclock`) is therefore not actually being applied, so slow-but-passing actions are not penalized as intended.

**Evidence:**

```
Line 58: `norm_wall = min(1.0, float(row.get("_norm_wallclock") or 0.0))`. Grep for `_norm_wallclock` shows it is only ever READ (policy.py) and referenced in docs — never written onto any fetched row.
```

**Suggested fix:** Either wire up the signal or drop the term. To wire it: in rebuild_from_ledger (or in fetch_subtasks post-processing) compute a duration from the existing started_at/ended_at TEXT timestamps, normalize against a cap (mirroring _COST_CAP with a _WALL_CAP seconds constant), and set row["_norm_wallclock"] before calling compute_reward. Alternatively, if no duration signal is desired, remove the "wallclock" key from POLICY_REWARD_WEIGHTS and delete the norm_wall line and its term from compute_reward, updating the docstring formula so it matches reality.

**Verifier note:** Verified against the real code path. config.POLICY_REWARD_WEIGHTS (platform_core/app_config/llm.py:225-226) sets a non-zero "wallclock": 0.1. compute_reward (learning/policy.py:58) computes norm_wall = min(1.0, float(row.get("_norm_wallclock") or 0.0)) and subtracts w["wallclock"] * norm_wall (line 62). The rows are produced by experience.fetch_subtasks (memory/experience_subtasks.py:201-213) which does plain SELECT * FROM subtasks and returns dict(row) — no post-processing. The subtasks table schema (memory/experience_schema.py:55-83) has no _norm_wallclock column (it has started_at/ended_at TEXT timestamps and cost_usd, but nothing named wallclock/duration/_norm_wallclock). A repo-wide grep for _norm_wallclock returns exactly one hit — the READ on policy.py:58 — confirming nothing ever writes it onto a row.

---

### 21. Curriculum auto-queue bypasses human approval and can be driven by feedback volume

- **Severity:** low  |  **Category:** security
- **Location:** `learning/sie.py:295`

**What's wrong (impact):** When >=5 new human_feedback rows have accrued since the last consolidation, `_curriculum_and_report` spawns EVERY generated curriculum goal as a real detached orchestrator run via `work_launcher.spawn`, explicitly bypassing the human approval gate (comment at line 285 admits 'bypass human approval'). There is no cap on how many goals are queued (all of `goals` are spawned, one WorkRequest each), no de-duplication against already-queued/previously-auto-queued goals across maintenance passes, and no scoping constraint on the spawned runs. Because the trigger counts raw feedback rows with no trust boundary, a party who can write human_feedback rows (or a burst of legitimate feedback) drives the system to autonomously launch multiple self-authored 1-hour runs that consume compute and take autonomous action. Each SIE maintenance pass that finds >=5 new feedback re-spawns the current weak-family goals again.

**Evidence:**

```
Lines 295-302: `if new_feedback_count >= 5 and goals: for goal_dict in goals: req = work_launcher.WorkRequest(goal=goal_dict["goal"], hours=1.0); work_launcher.spawn(req)`. No per-day cap (unlike selfplay.py which enforces SELFPLAY_MAX_PER_DAY), no idempotency key, no config gate to disable auto-queue.
```

**Suggested fix:** Bring the curriculum auto-queue in line with the selfplay guardrails: (1) gate behind an explicit config flag (default off), e.g. `CURRICULUM_AUTO_QUEUE_ENABLED`; (2) add a per-day/per-window cap on auto-queued goals persisted in sie_state.json (mirror `SELFPLAY_MAX_PER_DAY`); (3) skip when a run is already active (`if work_launcher.activeRun() is not None: return` before spawning) so it does not violate the single-active-run invariant; and (4) de-duplicate by family/goal-text against a persisted set in sie_state.json so identical weak-family goals are not re-spawned on subsequent weekly passes. The `generate_goals(n=3)` default already bounds a single pass to 3, so the unbounded concern is minor, but the missing enable-flag, cross-pass cap, dedup, and busy check are the real gaps.

**Verifier note:** Code confirms the core defect. In learning/sie.py `_curriculum_and_report` (lines 295-302), when `new_feedback_count >= 5 and goals`, it loops over all generated goals and calls `work_launcher.spawn(WorkRequest(goal=..., hours=1.0))` for each. This path has NO config enable-flag, NO per-day/per-window cap, NO de-duplication, and NO busy check — verified by contrast with the sibling selfplay path (`_self_play` -> `selfplay.run`), which enforces `SELFPLAY_ENABLED`, `SELFPLAY_MAX_PER_DAY` (default 3), a work-window gate, and `is_busy=lambda: work_launcher.activeRun() is not None`.

---

### 22. Dashboard cockpit image-throttle timestamp (_last_image_ts) is read-modified-written outside any lock across parallel workers

- **Severity:** low  |  **Category:** concurrency
- **Location:** `notifications/dashboard.py:196`

**What's wrong (impact):** _cockpit() computes `want_image = ... (now - self._last_image_ts) >= COCKPIT_IMAGE_MIN_INTERVAL` (dashboard.py:182) and later sets `self._last_image_ts = now` (dashboard.py:196), both OUTSIDE self._lock (the surrounding lock acquired at :184-194 is self._state_lock, guarding only the state snapshot/render, and _last_image_ts is written at :196 after that lock is released). dashboard.update() is called by concurrent parallel workers, so two workers can both read the old _last_image_ts, both decide want_image=True, and both render+upload a hero image within the min-interval window -- exactly the rate-limit storm the throttle exists to prevent. The lost-update on the timestamp also means the throttle can drift. Advisory/cosmetic (worst case is an extra multipart upload / a 429 the breaker already handles), but the throttle guarantee is not actually thread-safe.

**Evidence:**

```
dashboard.py:181-182 `now = time.monotonic(); want_image = config.VISUALS_ENABLED and (now - self._last_image_ts) >= config.COCKPIT_IMAGE_MIN_INTERVAL` and dashboard.py:195-196 `if img: self._last_image_ts = now` -- neither the read at :182 nor the write at :196 is under self._lock; the only lock held in between is self._state_lock (:184-194) which is released before the write.
```

**Suggested fix:** In _cockpit(), replace the unguarded read/write of _last_image_ts with an atomic check-and-claim under self._lock: `now = time.monotonic()\nwith self._lock:\n    want_image = config.VISUALS_ENABLED and (now - self._last_image_ts) >= config.COCKPIT_IMAGE_MIN_INTERVAL\n    if want_image:\n        self._last_image_ts = now` — then render/upload based on want_image and drop the later `if img: self._last_image_ts = now`. Note: claiming the slot before render means a subsequent render failure (img falls back to None) still consumed the interval; acceptable given the throttle is advisory, but if that matters, roll back _last_image_ts under self._lock when img is None.

**Verifier note:** Confirmed by reading the actual code path. In notifications/dashboard.py:_cockpit(), `now = time.monotonic()` (181) and `want_image = config.VISUALS_ENABLED and (now - self._last_image_ts) >= config.COCKPIT_IMAGE_MIN_INTERVAL` (182) execute BEFORE any lock is taken; `lock = self._state_lock` is acquired at 184-185 and released at 194, and `self._last_image_ts = now` is written at 196 AFTER that release. self._lock (the mutex the class docstring says 'guards mutable state under parallel workers', line 62) is never held around this read-modify-write. Concurrency is real: run_loop_mixin.py:200 runs self._executeSubtask in a ThreadPoolExecutor(max_workers=parallelism), and _executeSubtask (execute_mixin.py:294) calls dashboard.update() (execute_mixin.py:141/300/338), and update() calls _cockpit() (dashboard.py:258). So multiple worker threads genuinely invoke _cockpit() concurrently.

---

### 23. OpsCog watchdog _alerted set grows unbounded across task ids (minor memory leak in long-lived gateway)

- **Severity:** low  |  **Category:** resource-leak
- **Location:** `notifications/ops_cog.py:33,85,93`

**What's wrong (impact):** OpsCog._alerted is an in-memory set that accumulates task_id strings for every run the watchdog has ever alerted on. It only discards a task_id when that exact task later becomes non-stale (ops.runIsStale returns False for the CURRENT latest task). Because the watchdog only ever inspects the single latest task each tick, older task_ids that were alerted and then superseded by a new run are never discarded — they remain in the set for the lifetime of the gateway process. Over many runs this set grows without bound. Impact is small (one short string per run) but it is a genuine unbounded accumulation in a forever-running process.

**Evidence:**

```
ops_cog.py:33 `self._alerted: set = set()`; :85 `self._alerted.add(state.task_id)`; :93 `self._alerted.discard(state.task_id)` only runs when the CURRENT latest task is not stale, so a stale-then-superseded task's id is never removed. watchdog only ever sees resolveTargetTask() (the latest task).
```

**Suggested fix:** Since only the latest run is ever evaluated, keep _alerted to at most the current task. In the watchdog, when the resolved task_id differs from the previously seen one, reset the set: track a self._last_task_id, and on change do self._alerted.clear(); self._last_task_id = state.task_id before the stale check. Alternatively replace the set with a single Optional[str] holding the id of the currently-alerted stale run, since multi-entry membership serves no purpose given only one task is inspected per tick.

**Verifier note:** The code path is exactly as described (though the real path is notifications/bot/cogs/ops_cog.py, not notifications/ops_cog.py). OpsCog._alerted is a set() (line 33). The watchdog (60s loop) only ever inspects spine.resolveTargetTask(), which returns TaskState.loadLatest() (notifications/commands.py:114-115) — always the single latest run. Line 85-86 adds state.task_id when the CURRENT latest task is stale and unseen. Line 92-93 discards only the CURRENT latest task's id when that task is NOT stale. No other code clears _alerted. Consequence: when run A goes stale, gets alerted (its id added), and is then superseded by a newer run B, the watchdog never inspects A again, so A's id is never discarded. Over the lifetime of the forever-running gateway process, one short task_id string per alerted-then-superseded stale run accumulates permanently.

---

### 24. Epoch divergence check re-runs git subprocess at every subtask boundary despite git_sha not being compared

- **Severity:** low  |  **Category:** bug
- **Location:** `platform_core/core/epoch.py:120`
- **:warning: RISKY TO FIX BLINDLY:** Feeds a self-mod safety decision; prefer always-hashing over a doc-only note.

**What's wrong (impact):** `_checkCodeDivergence` calls `epoch.diverged()` at every subtask boundary; `diverged()` compares only `fingerprint()['files']` against the pinned files dict (line 171). But `fingerprint()` unconditionally calls `_gitSha()` (line 120), which spawns `git rev-parse HEAD` with a 10s timeout on every invocation, even though the resulting `git_sha` is discarded by `diverged()`. On a run with many subtasks (self-improvement horizon-fill runs churn through dozens), this is one blocking git subprocess per subtask on the hot loop path for a value that is never used, and up to a 10s stall each time git is slow/absent.

**Evidence:**

```
def diverged(pinned: Epoch) -> bool:
    return fingerprint()["files"] != pinned.code.get("files", {})
# fingerprint():
    result = {"git_sha": _gitSha(), "files": files, "root_hash": _rootHash(files)}   # _gitSha() spawns git every call; only 'files' is used by diverged()
```

**Suggested fix:** Add a files-only helper and use it on the divergence hot path so the git subprocess is skipped. In epoch.py, factor the files computation out of `fingerprint()`:

def _fingerprintFiles() -> dict[str, str]:
    paths = identity.selfCodeFiles()
    if getattr(config, "REPO_MERKLE_CACHE_ENABLED", True):
        return _fingerprintCached(paths)
    return {str(p).lower(): _hashFile(p) for p in paths}

Have `fingerprint()` call `_fingerprintFiles()` for its `files` entry (preserving `git_sha`/`root_hash` for snapshot()), and change `diverged()` to:

def diverged(pinned: Epoch) -> bool:
    return _fingerprintFiles() != pinned.code.get("files", {})

The git SHA is only needed at snapshot() time, so this removes the per-subtask `git rev-parse` fork with no behavior change.

**Verifier note:** Verified against the real code. epoch.py:169-171 `diverged()` compares only `fingerprint()["files"]` against `pinned.code.get("files", {})`; the `git_sha` and `root_hash` fields of the fingerprint dict are never consulted. epoch.py:111-122 `fingerprint()` unconditionally calls `_gitSha()` (line 120), and `_gitSha()` (line 31-37) spawns `subprocess.run(["git","rev-parse","HEAD"], timeout=10)` with no caching (confirmed via grep: only call sites are line 120 and a test monkeypatch). Caller path confirmed: execute_mixin.py:304-309 calls `_checkCodeDivergence(state)` once per subtask inside `self._state_lock` (a serialized/blocking section), and subtask.py:22-33 routes that straight into `epoch.diverged()`. So on every subtask boundary a git subprocess is spawned and its result thrown away.

---

### 25. epoch fingerprint SQLite connection leaked on every subtask boundary

- **Severity:** low  |  **Category:** resource-leak
- **Location:** `platform_core/core/epoch.py:82`
- **:warning: RISKY TO FIX BLINDLY:** Feeds a self-mod safety decision; prefer always-hashing over a doc-only note.

**What's wrong (impact):** _fingerprintCached opens the cache DB with `with _cacheConn() as conn:`. The sqlite3 connection context manager commits/rolls back the transaction but does NOT close the connection (verified: the connection stays open after the with-block). fingerprint() is invoked at run start (snapshot) and again at EVERY subtask boundary through _checkCodeDivergence -> epoch.diverged() -> fingerprint(). A run with hundreds of subtasks leaks hundreds of open sqlite connections and OS file handles to state/epoch_fingerprint_cache.db, relying on GC. On Windows these open handles also hold locks on the cache db file, which can block later cleanup/wipe of state/ and eventually exhaust file descriptors on very long runs.

**Evidence:**

```
`with _cacheConn() as conn:` (epoch.py:82) where _cacheConn returns a fresh `sqlite3.connect(...)` each call (line 47). Demonstrated that sqlite3's `with conn` does not close the connection. diverged() (line 171) calls fingerprint() -> _fingerprintCached on every call; _checkCodeDivergence (subtask.py:29) calls diverged() at each subtask boundary.
```

**Suggested fix:** Close the connection deterministically in _fingerprintCached (platform_core/core/epoch.py). Wrap the existing block: `import contextlib` then `with contextlib.closing(_cacheConn()) as conn:` `\n    with conn:` `\n        ...` so both the transaction commits AND the handle/file lock is released on function exit rather than waiting for the cyclic GC. Equivalent: `conn = _cacheConn(); try:` `\n    with conn: ...` `\nfinally: conn.close()`.

**Verifier note:** The core mechanism is verified. `with _cacheConn() as conn:` (platform_core/core/epoch.py:82) uses sqlite3's connection context manager, which commits/rolls back but does NOT close the connection — confirmed empirically (connection remains usable after the with-block). And _fingerprintCached is genuinely invoked once per subtask boundary: execute_mixin.py:307 calls _checkCodeDivergence(state) -> epoch.diverged() (subtask.py:29) -> fingerprint() -> _fingerprintCached. So a connection is opened per boundary and never deterministically closed. Worse than the finding states in one respect: because conn.execute()/SELECT create cursor objects that form reference cycles with the connection, the handle is not even reclaimed by CPython immediate refcounting — it survives until the cyclic GC runs (verified: with gc disabled, 200 boundaries -> 200 open handles).

---

### 26. Divergence check missed when a self-edit preserves file size and mtime (cache never rehashes)

- **Severity:** low  |  **Category:** data-integrity
- **Location:** `platform_core/core/epoch.py:93`
- **:warning: RISKY TO FIX BLINDLY:** Feeds a self-mod safety decision; prefer always-hashing over a doc-only note.

**What's wrong (impact):** _fingerprintCached returns the cached sha256 whenever the current file's size and mtime_ns both equal the cached row's values, without rehashing content. If a mid-run core edit rewrites a self.code file to the same byte length and the filesystem/tooling preserves mtime_ns (coarse-mtime filesystems, an editor that restores timestamps, or a same-size in-place patch on a low-resolution clock), fingerprint() returns the stale hash, diverged() returns False, _checkCodeDivergence never sets meta['code_diverged'], and safety_gate does NOT short-circuit -- it proceeds to run/bless edited-but-never-executed bytecode as 'verified by this run'. The divergence detector is the guard that prevents exactly that, and it can be bypassed by a size+mtime collision.

**Evidence:**

```
epoch.py:93 `if row and int(row["size"]) == size and int(row["mtime_ns"]) == mtime_ns: digest = str(row["sha256"])` -- content is not re-read when size+mtime match. diverged() (line 171) and the safety_gate short-circuit (selfmod.py:116) both depend on this hash being accurate.
```

**Suggested fix:** For the divergence-feeding fingerprint path specifically, do not trust the (size, mtime_ns) cache: either always hash content in fingerprint()/_checkCodeDivergence (the selfCodeFiles set is small, ~0.3s), or keep the cache only for non-safety callers and force a content hash when the result feeds diverged(). Minimal change: in fingerprint(), skip _fingerprintCached and use the direct {path: _hashFile(path)} branch, or add a force_content flag threaded from diverged()/_checkCodeDivergence. At minimum, document in config that REPO_MERKLE_CACHE_ENABLED=True weakens mid-run divergence detection on coarse-mtime filesystems.

**Verifier note:** Code path is confirmed exactly as described. epoch.py:93 (_fingerprintCached) returns the cached sha256 whenever the current stat's st_size and st_mtime_ns both equal the cached row, with no content re-read. The cache is ON by default (fingerprint() at line 116 gates on REPO_MERKLE_CACHE_ENABLED defaulting True). This hash is the sole input to diverged() (epoch.py:171: fingerprint()['files'] != pinned.code['files']), which drives _checkCodeDivergence (subtask.py:29-31) setting state.meta['code_diverged'], which drives the safety_gate short-circuit (control_mixin.py:322-323 -> selfmod.py:116). So a stale hash genuinely can make a mid-run self.code edit be blessed as verified. Trusting (size, mtime_ns) for a SAFETY decision rather than a build-speed decision is a real design defect -- the classic rsync 'checksum vs quick-check' issue -- and it is not intended behavior nor fully handled.

---

### 27. PROJECT_ROOT source mismatch: self-ref detection uses config.PROJECT_ROOT, fingerprint uses identity.PROJECT_ROOT

- **Severity:** low  |  **Category:** contract
- **Location:** `platform_core/core/identity.py:39`

**What's wrong (impact):** identity.PROJECT_ROOT falls back to the file-derived _SELF_ROOT whenever config.PROJECT_ROOT != _SELF_ROOT (the documented 'config mis-resolves to a sub-dir with no .env' case). epoch.fingerprint()/diverged() and selfCodeFiles() all root on identity.PROJECT_ROOT. But _detectSelfReferential (run_loop.py:70) and _prepareSelfReferential root on config.PROJECT_ROOT. When the two roots disagree, a run can be classified self-referential (and have core-file locks applied / branch checked out) against config.PROJECT_ROOT while the epoch pin + divergence check fingerprint a DIFFERENT tree (identity's). The safety gate then reasons about a code set that isn't the one the run edited, undermining the divergence/gate guarantees in exactly the environment the identity fallback was written to handle.

**Evidence:**

```
identity.py:39 `PROJECT_ROOT = _CFG_ROOT if _CFG_ROOT == _SELF_ROOT else _SELF_ROOT`. run_loop.py:70 `os.path.abspath(work_dir).lower() == os.path.abspath(str(config.PROJECT_ROOT)).lower()`. epoch.py:33/115 use identity.PROJECT_ROOT / identity.selfCodeFiles().
```

**Suggested fix:** Assert one root at startup and hard-fail/log when config.PROJECT_ROOT.resolve() != identity.PROJECT_ROOT so the safety subsystem never silently reasons about two trees. Alternatively route _detectSelfReferential/_execCwd/_prepareSelfReferential through identity.PROJECT_ROOT so self-ref classification, core-file locks, and the epoch fingerprint all key off the same root. Also update the stale identity.py:30-33 docstring, whose cited 'config mis-resolves to a sub-dir' trigger no longer matches locateRepoRoot's behavior.

**Verifier note:** The two root sources and consumers are exactly as the finding states. identity.PROJECT_ROOT (identity.py:39) = _CFG_ROOT if _CFG_ROOT==_SELF_ROOT else _SELF_ROOT, where _SELF_ROOT is identity.py.resolve().parents[2]. epoch.snapshot()->fingerprint() (epoch.py:115) and diverged() (epoch.py:171) fingerprint identity.selfCodeFiles(), which walks os.walk(identity.PROJECT_ROOT) (identity.py:161). Meanwhile _detectSelfReferential (run_loop.py:70), _execCwd (run_loop.py:56), and _prepareSelfReferential root on config.PROJECT_ROOT. orchestrator.py:123-131 calls _detectSelfReferential/_prepareSelfReferential and epoch.snapshot in the same path, so a mismatch would indeed classify/lock/branch against config.PROJECT_ROOT while the epoch pin fingerprints identity.PROJECT_ROOT -- the described contract gap is real in code.

However, the divergence is NOT reachable on a normal run.

---

### 28. doctor._git can hang startup on a git credential/terminal prompt (missing GIT_TERMINAL_PROMPT/stdin guard)

- **Severity:** low  |  **Category:** windows
- **Location:** `platform_core/ops/doctor.py:79`

**What's wrong (impact):** doctor.run() is invoked warn-only on EVERY fresh run at startup (main.py:310-314 via _elaborateGoal). Its _git helper spawns `git rev-parse --is-inside-work-tree` with a 15s timeout but WITHOUT stdin=subprocess.DEVNULL and WITHOUT env GIT_TERMINAL_PROMPT=0. The sibling health._git (health.py:146-149) was explicitly hardened with exactly those two flags for this reason. If git tries to prompt for credentials (e.g. a repo whose remote requires auth, or a locked/partial index that makes git open the pager or ask a question), the subprocess blocks on the inherited terminal for up to the 15s timeout on the launch hot path, and on Windows a credential-helper GUI prompt can block even longer than the timeout can cleanly cancel.

**Evidence:**

```
doctor.py:79-81 `return subprocess.run(["git", *args], cwd=str(config.PROJECT_ROOT), capture_output=True, text=True, timeout=15)` — compare health.py:146-149 which adds `stdin=subprocess.DEVNULL, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}` with the comment 'a hung git ... must never wedge'.
```

**Suggested fix:** Mirror the already-hardened sibling. Replace doctor.py:79-81 with: `def _git(*args: str) -> subprocess.CompletedProcess:\n    return subprocess.run(["git", *args], cwd=str(config.PROJECT_ROOT), capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})` and ensure `import os` is present at module top.

**Verifier note:** All cited facts verified in the real code. doctor.py:79-81 `_git` runs `subprocess.run(["git", *args], cwd=..., capture_output=True, text=True, timeout=15)` with NO `stdin=subprocess.DEVNULL` and NO `GIT_TERMINAL_PROMPT=0`. The sibling health.py:141-154 `_git` was deliberately hardened with exactly those two flags, with a comment (health.py:143-145) stating a hung git "must never wedge". The invocation claim is also true: main.py:309-316 calls `doctor.run()` warn-only inside `_elaborateGoal` on every fresh (non-sim) run before elaboration, and doctor.run() (doctor.py:126-131) includes `check_git()`, which calls the unguarded `_git("rev-parse", "--is-inside-work-tree")` at doctor.py:90. So the hot-path exposure and the guard asymmetry are both genuine. This is a real defensive-hardening inconsistency worth fixing, and the suggested fix (mirror health._git) is correct and safe.

---

### 29. Lazy-init of the review-dedup lock and dict is itself unsynchronized, defeating the per-sid dedup lock under parallel workers

- **Severity:** low  |  **Category:** concurrency
- **Location:** `platform_core/orchestration/control_review_mixin.py:40`

**What's wrong (impact):** _worthGptReview() is the cost-guard called from _postSubtaskEnrich -> _runAdversaryReview -> adversary_loop.runReview -> _adversaryReview, which runs inside parallel ThreadPoolExecutor workers (_handleParallelBatch, run_loop_mixin.py:200-214). It serializes access to the dedup cursor via self._reviewHashLock() and self._reviewHashes(). But BOTH the lock and the dict are lazily created with an unguarded check-then-set: `lk = getattr(self,'_review_hash_lock',None); if lk is None: lk = self._review_hash_lock = threading.Lock()` (lines 40-43) and the same for _review_hashes (lines 45-49). Neither is initialized in Orchestrator.__init__ (orchestrator.py:74-106 sets only _state_lock/_poll_lock/etc). If two workers first-touch _worthGptReview concurrently, each sees None and constructs its OWN Lock object and/or its own dict; the two workers then acquire DIFFERENT locks and mutate DIFFERENT dicts, so the intended serialization never happens. This is the exact class of bug the sibling _trajectoryRecorder (execute_mixin.py:99-110) avoids by double-checking the field UNDER self._state_lock.

**Evidence:**

```
control_review_mixin.py:40-49:
        lk = getattr(self, "_review_hash_lock", None)
        if lk is None:
            lk = self._review_hash_lock = threading.Lock()
        return lk
    def _reviewHashes(self) -> dict:
        hs = getattr(self, "_review_hashes", None)
        if hs is None:
            hs = self._review_hashes = {}
        return hs
Contrast the safe pattern at execute_mixin.py:102-104: `with self._state_lock: rec = getattr(self,'_trajectory',None) # re-check inside the lock`.
```

**Suggested fix:** Eagerly initialize both fields in Orchestrator.__init__ alongside the other locks (orchestrator.py ~95-96): `self._review_hash_lock = threading.Lock()` and `self._review_hashes = {}`. Then simplify `_reviewHashLock()`/`_reviewHashes()` to plain attribute returns (`return self._review_hash_lock` / `return self._review_hashes`), removing the lazy check-then-set entirely and eliminating the first-touch race. This mirrors how _state_lock/_poll_lock are already handled.

**Verifier note:** The race is real and provable in the code. `_reviewHashLock()` (control_review_mixin.py:40-43) and `_reviewHashes()` (45-49) both use an unguarded check-then-set: `lk = getattr(self,'_review_hash_lock',None); if lk is None: lk = self._review_hash_lock = threading.Lock()`. Neither `_review_hash_lock` nor `_review_hashes` is initialized in `Orchestrator.__init__` (orchestrator.py:74-106 sets `_state_lock`, `_poll_lock`, `_last_review_hash`, etc., but never these two — grep confirms the only references in the whole repo are inside control_review_mixin.py). The call path is genuinely concurrent: `_worthGptReview` is invoked from `_adversaryReview` (review_mixin.py:38-39), the default reviewer bound in `__init__` (orchestrator.py:89), and `_executeSubtask` runs inside a `ThreadPoolExecutor` (run_loop_mixin.py:200-215).

---

### 30. Lazy-init of the shared per-run CostBudget is unsynchronized; parallel workers can build two budget objects that each track a partial total

- **Severity:** low  |  **Category:** concurrency
- **Location:** `platform_core/orchestration/execute_mixin.py:112`

**What's wrong (impact):** _costBudget() lazily builds ONE CostBudget per run and caches it on self, but the check-then-set is not guarded: `cb = getattr(self,'_cost_budget',None); if cb is None: cb = self._cost_budget = CostBudget(...)`. It is consumed on the per-attempt cost path which runs inside parallel workers. Two workers first-touching it concurrently each construct a separate CostBudget; the running total is then split across two independent objects (each with its own internal _lock and _total), so the 80%-warn / hard-ceiling thresholds compute against a partial sum and can under-report or double-fire, and one CostBudget instance is silently orphaned. Unlike _trajectoryRecorder in the same file (which double-checks under self._state_lock at execute_mixin.py:102), _costBudget has no such guard. Impact is limited because CostBudget is advisory (fail-open, never aborts a run) and COST_BUDGET_ENABLED defaults off.

**Evidence:**

```
execute_mixin.py:112-118:
    def _costBudget(self, state):
        cb = getattr(self, "_cost_budget", None)
        if cb is None:
            from platform_core.runtime.cost_budget import CostBudget
            cb = self._cost_budget = CostBudget(state.task_id)
        return cb
CostBudget itself is internally locked (cost_budget.py:33-59) but that does not help when two DIFFERENT instances exist.
```

**Suggested fix:** Mirror _trajectoryRecorder's double-checked lock in _costBudget (execute_mixin.py:112): `cb = getattr(self, "_cost_budget", None); if cb is not None: return cb; with self._state_lock: cb = getattr(self, "_cost_budget", None); if cb is None: from platform_core.runtime.cost_budget import CostBudget; cb = self._cost_budget = CostBudget(state.task_id); return cb`. (Eager construction in __init__ would also work but the double-check keeps the lazy/disabled-off behavior consistent with the sibling helper.)

**Verifier note:** Verified against the actual code. execute_mixin.py:112-118 `_costBudget` does an unsynchronized check-then-set (`cb=getattr(self,"_cost_budget",None); if cb is None: cb=self._cost_budget=CostBudget(...)`), while the sibling `_trajectoryRecorder` at execute_mixin.py:94-110 double-checks the identical lazy-init under `self._state_lock` — so the codebase author demonstrably knows this pattern is needed and omitted it here. The consumption path is genuinely concurrent on a shared `self`: run_loop_mixin.py:200-214 submits `self._executeSubtask` for every subtask in a batch to a `ThreadPoolExecutor(max_workers=parallelism)`; that chains _runOneAttempt -> _invokeHands (execute_attempt_mixin.py:148-165) -> `self._costBudget(state).add(_res.get("cost_usd"))` at line 162.

---

### 31. loadLatest tie-break sorts started_at as a lexicographic string with timezone offsets, mis-ordering runs across an offset change

- **Severity:** low  |  **Category:** data-integrity
- **Location:** `state/task_io.py:118-132 (and listRecent :151)`

**What's wrong (impact):** loadLatest picks the 'most-recently-STARTED active task' by comparing key=(terminal?, meta['started_at']) with plain tuple/string comparison. started_at is written as `datetime.now().astimezone().isoformat(timespec='seconds')` (task_schema.create:62), which includes a UTC offset suffix (e.g. -04:00). Lexicographic comparison of two ISO strings with DIFFERENT offsets (DST transition, or a machine/tz change between runs) does NOT equal chronological order — '2026-07-03T09:00:00-04:00' sorts after '2026-07-03T10:00:00-05:00' though the latter is later in absolute time. Result: after a DST change, resume/inspection can pick the WRONG active run. Same lexicographic bug in listRecent's sort key.

**Evidence:**

```
`key = (0 if ...terminal else 1, meta.get('started_at', ''))` then `if best_key is None or key > best_key`. started_at format from create(): `started.isoformat(timespec='seconds')` on an aware datetime -> offset-suffixed string.
```

**Suggested fix:** In state/task_io.py, replace the string-based ordering with parsed aware-datetime comparison. Add a helper: `from datetime import datetime, timezone` and `def _startedDt(meta):\n    s = meta.get("started_at", "")\n    try:\n        return datetime.fromisoformat(s)\n    except (ValueError, TypeError):\n        return datetime.min.replace(tzinfo=timezone.utc)`. In loadLatest, build `key = (0 if meta.get("status") in TaskState._TERMINAL else 1, _startedDt(meta))`. In listRecent, sort with `out.sort(key=lambda d: _startedDt({"started_at": d["started_at"]}), reverse=True)` (or store the parsed datetime alongside). fromisoformat yields aware datetimes whose comparison normalizes offsets, restoring true chronological order; ensure the naive fallback carries a tzinfo so it never raises "can't compare offset-naive and offset-aware datetimes" when mixed with aware values.

**Verifier note:** Verified against real code. state/task_schema.py:52,62 writes started_at as datetime.now().astimezone().isoformat(timespec="seconds"), which emits an offset-suffixed ISO string (e.g. 2026-07-03T09:00:00-04:00). task_io.py:129 builds key=(0 if terminal else 1, meta.get("started_at","")) and task_io.py:130 selects via plain tuple/string `key > best_key`; task_io.py:151 sorts listRecent by the raw started_at string. Lexicographic comparison of two ISO strings with DIFFERENT offsets does not equal chronological order: '...T09:00:00-04:00' (13:00Z) compares GREATER than '...T10:00:00-05:00' (15:00Z) because at the hour digits '09' beats '10' lexically, yet the latter is 2h later in absolute time. So after a DST transition (twice yearly) or a machine/tz reconfiguration between two runs, ordering can invert.

---
