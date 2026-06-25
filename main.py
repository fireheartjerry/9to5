"""9TO5 entrypoint -- Step 0 / Step 0.5 + launch the autonomous run.

Usage:
    venv\\Scripts\\python main.py --goal "..." --hours 1
    venv\\Scripts\\python main.py --goal "..." --hours 1 --auto-approve
    venv\\Scripts\\python main.py --goal "..." --mode gated --parallel 2
    venv\\Scripts\\python main.py --resume <task_id>
    venv\\Scripts\\python main.py                                   # prompts for goal

The launching terminal is itself a control console (mirrors Discord): type
abort | pause | resume | skip <id> | add <text> | approve | reject | status.
Discord is the "second terminal" -- same controls from your phone.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from pathlib import Path

import config
from agents import elaborator
from control import ControlBus
from memory.obsidian import ObsidianClient
from orchestrator import Orchestrator, refreshClaudeKnowledge
from state.task import TaskState

LOG = config.getLogger("main")


def _runRefreshCommand() -> int:
    """`python main.py /refresh` -- manually rebuild the living Claude Code knowledge
    base (scrape latest docs + scan installed .claude + product-self-knowledge), overwrite
    claude_code.md, and recompute the injected CLAUDE CODE CAPABILITIES summary."""
    config.ensureDirs()
    print("Refreshing Claude Code knowledge base (fetching latest docs + scanning .claude)...")
    summary = refreshClaudeKnowledge(force=True)
    print(f"\nKnowledge written -> {config.CLAUDE_KNOWLEDGE_PATH}")
    print(f"Injected CLAUDE CODE CAPABILITIES summary: {len(summary)} chars\n")
    print("===== CLAUDE CODE CAPABILITIES (injected into every Ollama prompt) =====")
    print(summary)
    return 0

_CTL_HELP = ("[terminal control] commands: abort | pause | resume | skip <st-00N> | "
             "add <text> | approve | reject | status | help")


def _startTerminalControl(task_id: str) -> threading.Thread:
    """Daemon thread: read stdin and mirror Discord control commands to the ControlBus."""
    bus = ControlBus(task_id)

    def loop() -> None:
        print(_CTL_HELP, flush=True)
        for line in sys.stdin:
            cmd = line.strip()
            if not cmd:
                continue
            low = cmd.lower().lstrip("!")
            try:
                if low in ("abort", "stop", "quit"):
                    bus.requestAbort(); print("[ctl] abort requested", flush=True)
                elif low == "pause":
                    bus.requestPause(); print("[ctl] paused", flush=True)
                elif low == "resume":
                    bus.clearPause(); print("[ctl] resumed", flush=True)
                elif low in ("approve", "reject"):
                    gate = bus.getPendingGate()
                    if gate:
                        bus.decide(gate, "approve" if low == "approve" else "reject")
                        print(f"[ctl] gate {gate} -> {low}", flush=True)
                    else:
                        print("[ctl] no pending gate", flush=True)
                elif low.startswith("skip "):
                    bus.pushOp({"op": "skip", "subtask_id": cmd.split(None, 1)[1].strip()})
                    print("[ctl] skip queued", flush=True)
                elif low.startswith("add "):
                    text = cmd.split(None, 1)[1].strip()
                    bus.pushOp({"op": "add", "title": text, "description": text})
                    print("[ctl] add queued", flush=True)
                elif low == "status":
                    st = TaskState.load(task_id)
                    d, t = st.progress()
                    print(f"[ctl] {st.meta['status']} · {d}/{t} subtasks", flush=True)
                else:
                    print(_CTL_HELP, flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"[ctl] error: {e}", flush=True)

    thread = threading.Thread(target=loop, name="terminal-control", daemon=True)
    thread.start()
    return thread


def _collectEditedSpec() -> str:
    print("Enter the replacement specification. End with a single '.' on its own line:")
    buf: list[str] = []
    for line in sys.stdin:
        if line.rstrip("\n") == ".":
            break
        buf.append(line.rstrip("\n"))
    return "\n".join(buf).strip()


def _runDryRun(args) -> int:
    """Simulate a FULL run (architect -> plan -> execute -> verify -> complete) with no
    Ollama / Claude CLI / Discord / Obsidian. Proves the orchestration end-to-end."""
    import simulation
    import tempfile
    config.WEB_DASHBOARD = False
    config.CLAUDE_DOC_FETCH = False   # offline knowledge build only -- no web fetch in a dry-run
    config.ensureDirs()
    goal = (args.goal or "Simulated dry-run goal").strip()
    state = TaskState.create(goal, args.hours)
    state.setElaboratedGoal(goal)
    state.setUniverse({"description": "dry-run", "allowed_paths": [],
                       "allowed_to_expand_to": [], "hard_boundaries": []})
    state.save()
    # isolated temp work_dir: keeps the dry-run from tripping self-referential detection
    # (which would create a git branch) or writing into the real project tree.
    work_dir = tempfile.mkdtemp(prefix="9to5-dryrun-")
    print(f"[DRY-RUN] simulating a full run for {goal!r} — no Ollama/Claude/Discord/Obsidian touched.")
    orch = simulation.buildOrchestrator()
    summary = orch.runFull(state, work_dir=work_dir, auto_pr=False,
                           control_mode=args.mode, parallelism=max(1, args.parallel))
    print("\n===== DRY-RUN SUMMARY =====")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def _applyMentionShorthand(raw_args: list[str]) -> list[str]:
    """`python main.py @9to5 <free-text goal> [--flags]` -> fire-and-forget launch.

    Lowers the barrier from `--goal "..." --auto-approve` to a single chat-style line: the
    leading ``@9to5`` mention (optionally ``@9to5: goal`` with the goal on the same token)
    signals shorthand; every token up to the first ``-`` flag is the goal, real flags pass
    through untouched, and ``--auto-approve`` is implied so it truly fires and forgets.
    Returns the argv to feed argparse (unchanged when no @9to5 mention leads)."""
    token = raw_args[0].lstrip("/") if raw_args else ""
    if not token.lower().startswith("@9to5"):
        return raw_args
    lead = token[len("@9to5"):].lstrip(": ").strip()              # "@9to5:do x" -> "do x"
    goal_words: list[str] = [lead] if lead else []
    passthrough: list[str] = []
    rest = list(raw_args[1:])
    for i, tok in enumerate(rest):
        if tok.startswith("-"):
            goal_words += rest[:i]
            passthrough = rest[i:]
            break
    else:
        goal_words += rest
    new: list[str] = []
    goal = " ".join(goal_words).strip()
    if goal:
        new += ["--goal", goal]
    if "--auto-approve" not in passthrough:
        new.append("--auto-approve")
    return new + passthrough


def main() -> int:
    # `@9to5 <goal>` chat-style shorthand -> rewrite to `--goal "..." --auto-approve`.
    argv = _applyMentionShorthand(sys.argv[1:])

    # Standalone knowledge-refresh command (intercept before argparse, which would
    # reject the bare "/refresh" token): `python main.py /refresh`.
    if any(a.lstrip("-/").lower() == "refresh" for a in argv):
        return _runRefreshCommand()

    # Preflight doctor: `python main.py --doctor` -> report exactly what 'start' needs.
    if any(a.lstrip("-/").lower() == "doctor" for a in argv):
        import doctor
        report = doctor.run()
        print(doctor.render(report))
        return 0 if report["ready"] else 1

    parser = argparse.ArgumentParser(prog="9to5", description="Autonomous AI orchestrator.")
    parser.add_argument("--goal", help="Raw goal. If omitted you are prompted.")
    parser.add_argument("--hours", type=float, default=1.0, help="Time horizon in hours (default 1).")
    parser.add_argument("--work-dir", help="Working directory for Claude Code CLI (default PROJECT_ROOT).")
    parser.add_argument("--auto-approve", action="store_true", help="Skip the elaboration approval prompt.")
    parser.add_argument("--no-pr", action="store_true", help="Do not attempt to open a GitHub PR.")
    parser.add_argument("--mode", choices=["watch", "gated"], default=config.CONTROL_MODE_DEFAULT,
                        help="watch = autonomous + abort; gated = approval gates at plan/PR.")
    parser.add_argument("--parallel", type=int, default=config.DEFAULT_PARALLELISM,
                        help="Run up to N independent (deps-satisfied) subtasks concurrently.")
    parser.add_argument("--resume", help="Resume an existing task by its task_id.")
    parser.add_argument("--web-port", type=int, default=config.WEB_DASHBOARD_PORT, help="Web dashboard port.")
    parser.add_argument("--no-web", action="store_true", help="Disable the local web dashboard.")
    parser.add_argument("--task-id", help="Alias for --resume: restore + continue a task by id.")
    parser.add_argument("--night-mode", action="store_true",
                        help="Zero human interaction: watch mode, no adversary PR hold, auto-resume pauses.")
    parser.add_argument("--health", action="store_true", help="Run environment health checks and exit.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Simulate a full run with no external services (offline; for testing).")
    parser.add_argument("--e2e", action="store_true",
                        help="Run the virtual-operator end-to-end test suite (a scripted 'human' "
                             "drives full simulated runs through the real control surfaces) and exit.")
    args = parser.parse_args(argv)

    if args.health:
        import health
        return 0 if health.runHealthChecks() else 1

    if args.e2e:
        from testing.e2e import main as e2eMain
        return e2eMain()

    if args.dry_run:
        return _runDryRun(args)

    if args.task_id and not args.resume:   # --task-id is an alias for --resume
        args.resume = args.task_id

    config.WEB_DASHBOARD_PORT = args.web_port
    if args.no_web:
        config.WEB_DASHBOARD = False
    if args.night_mode:
        config.NIGHT_MODE = True
        args.mode = "watch"          # night mode is always watch — no human gates
        args.auto_approve = True     # suppress elaboration approval prompt
    config.ensureDirs()

    # Living knowledge refresh: the absolute first thing every session does, BEFORE any
    # Ollama call (elaborator/architect/planner/spec), so the brain reasons from the
    # current Claude Code feature set. Idempotent per process; never blocks the run.
    try:
        refreshClaudeKnowledge()
    except Exception as e:  # noqa: BLE001
        LOG.warning("startup knowledge refresh failed (non-fatal): %s", e)

    # A user-chosen --work-dir must exist (9to5 operates on YOUR project tree, not its own root).
    if args.work_dir and not Path(args.work_dir).is_dir():
        print(f"--work-dir does not exist or is not a directory: {args.work_dir}")
        return 2
    work_dir = args.work_dir or str(config.PROJECT_ROOT)
    if config.WEB_DASHBOARD:
        print(f"Live web dashboard -> http://127.0.0.1:{config.WEB_DASHBOARD_PORT}/  "
              f"(control: terminal / Discord !abort / web buttons)")

    # ---- Resume path ----
    if args.resume:
        try:
            state = TaskState.load(args.resume)
        except Exception as e:  # noqa: BLE001
            print(f"Cannot resume {args.resume}: {e}")
            return 2
        # Re-stamp the liveness beacon to THIS process up front: the loaded task still carries the
        # prior (now-dead) run's run_pid, so until _run_resume re-stamps it a concurrent activeRun()
        # could read a dead pid and mis-abort this live resume. Make it authoritative immediately.
        state.meta["run_pid"] = os.getpid()
        state.save()
        # remember the original working directory: explicit --work-dir overrides, else the one
        # the task was launched with, else the project root.
        resume_work_dir = args.work_dir or state.meta.get("work_dir") or str(config.PROJECT_ROOT)
        LOG.info("Resuming task %s in %s", state.task_id, resume_work_dir)
        _startTerminalControl(state.task_id)
        # Wrap the resume in the SAME supervisor as a fresh run (CB-12): a crash in runFull's setup
        # or a non-terminal return must auto-recover, not exit 0 and strand the task for the day.
        import resilience

        def _run_resume(st):
            st.meta["run_pid"] = os.getpid()   # liveness beacon so the launcher never double-spawns a live run
            st.save()
            return Orchestrator().runFull(st, work_dir=resume_work_dir, auto_pr=not args.no_pr,
                                          control_mode=args.mode, resume=True, parallelism=max(1, args.parallel))

        summary = resilience.run_with_recovery(_run_resume, state)
        print("\n===== RUN SUMMARY =====")
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0

    # ---- Fresh run ----
    missing = config.validateEnv()
    if missing:
        LOG.warning("Missing env values: %s (degraded mode)", ", ".join(missing))
    obs_health = ObsidianClient().health()
    LOG.info("Obsidian REST: reachable=%s authed=%s (disk fallback always available)",
             obs_health["rest_ok"], obs_health["authed"])

    try:
        goal = (args.goal or input("9TO5 goal> ")).strip()
    except EOFError:   # non-interactive stdin (e.g. launched detached) with no --goal -> abort cleanly
        goal = (args.goal or "").strip()
    if not goal:
        print("No goal given; aborting.")
        return 2

    state = TaskState.create(goal, args.hours)
    # Stamp the liveness beacon BEFORE the first save -- and crucially before the slow Ollama
    # elaboration/universe calls below. Otherwise the freshly-created task sits in status 'created'
    # with NO run_pid for the whole elaboration window; under VRAM-pressure model reloads that window
    # can exceed the _STALE_CREATED_SECONDS mtime cutoff, so a second activeRun() (a 2nd /work or SIE
    # self_play) would mis-declare this LIVE, still-initializing run 'stale', abort it on the bus, and
    # double-spawn a second orchestrator over the same repo. run_pid makes liveness authoritative for
    # the entire process lifetime so that path is never reached.
    state.meta["run_pid"] = os.getpid()
    state.save()
    LOG.info("Created task %s (horizon %sh, mode %s, parallel %s)",
             state.task_id, args.hours, args.mode, args.parallel)
    # Start control thread BEFORE elaboration so abort/pause work even if Ollama hangs.
    _startTerminalControl(state.task_id)
    # Best-effort preflight: surface any hard blocker up front (don't abort -- degraded
    # mode + the elaboration fallback keep a run going; the user just sees what's missing).
    try:
        import doctor
        _pf = doctor.run()
        if not _pf["ready"]:
            print(doctor.render(_pf))
            print("(continuing in degraded mode — run `python main.py --doctor` for details)\n")
    except Exception:  # noqa: BLE001
        pass

    elaborated = elaborator.elaborate(goal)
    state.setElaboratedGoal(elaborated)
    print("\n===== ELABORATED GOAL =====\n" + elaborated + "\n===========================\n")

    universe = elaborator.extractUniverse(goal, elaborated, work_dir)
    state.setUniverse(universe)
    LOG.info("Universe: %d allowed_paths, hard_boundaries=%s",
             len(universe.get("allowed_paths", [])), universe.get("hard_boundaries"))

    if not args.auto_approve:
        try:
            ans = input("Approve elaboration? [Y / edit / n] ").strip().lower()
        except EOFError:   # non-interactive without --auto-approve -> proceed (don't crash the run)
            ans = "y"
        if ans in {"n", "no"}:
            print("Aborted by human.")
            state.setStatus("aborted")
            return 1
        if ans == "edit":
            edited = _collectEditedSpec()
            if edited:
                state.setElaboratedGoal(edited)
                print("Elaboration replaced.")

    # Supervised run: send one sentence at 9am, return at 5pm to a finished job. If the
    # run crashes, the supervisor auto-resumes the SAME task (committed progress is the
    # source of truth) until it is terminal or the deadline passes -- no human needed.
    import resilience

    def _run(st):
        st.meta["run_pid"] = os.getpid()   # liveness beacon so the launcher never double-spawns a live run
        st.save()
        return Orchestrator().runFull(st, work_dir=work_dir, auto_pr=not args.no_pr,
                                      control_mode=args.mode, parallelism=max(1, args.parallel))

    summary = resilience.run_with_recovery(_run, state)
    print("\n===== RUN SUMMARY =====")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
