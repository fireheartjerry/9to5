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
import sys
import threading

import config
from agents import elaborator
from control import ControlBus
from memory.obsidian import ObsidianClient
from orchestrator import Orchestrator
from state.task import TaskState

LOG = config.getLogger("main")

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


def main() -> int:
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
    parser.add_argument("--health", action="store_true", help="Run environment health checks and exit.")
    args = parser.parse_args()

    if args.health:
        import health
        return 0 if health.runHealthChecks() else 1

    if args.task_id and not args.resume:   # --task-id is an alias for --resume
        args.resume = args.task_id

    config.WEB_DASHBOARD_PORT = args.web_port
    if args.no_web:
        config.WEB_DASHBOARD = False
    config.ensureDirs()

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
        LOG.info("Resuming task %s", state.task_id)
        _startTerminalControl(state.task_id)
        summary = Orchestrator().runFull(state, work_dir=work_dir, auto_pr=not args.no_pr,
                                         control_mode=args.mode, resume=True, parallelism=max(1, args.parallel))
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

    goal = (args.goal or input("9TO5 goal> ")).strip()
    if not goal:
        print("No goal given; aborting.")
        return 2

    state = TaskState.create(goal, args.hours)
    state.save()
    LOG.info("Created task %s (horizon %sh, mode %s, parallel %s)",
             state.task_id, args.hours, args.mode, args.parallel)

    elaborated = elaborator.elaborate(goal)
    state.setElaboratedGoal(elaborated)
    print("\n===== ELABORATED GOAL =====\n" + elaborated + "\n===========================\n")

    if not args.auto_approve:
        ans = input("Approve elaboration? [Y / edit / n] ").strip().lower()
        if ans in {"n", "no"}:
            print("Aborted by human.")
            state.setStatus("aborted")
            return 1
        if ans == "edit":
            edited = _collectEditedSpec()
            if edited:
                state.setElaboratedGoal(edited)
                print("Elaboration replaced.")

    _startTerminalControl(state.task_id)
    summary = Orchestrator().runFull(state, work_dir=work_dir, auto_pr=not args.no_pr,
                                     control_mode=args.mode, parallelism=max(1, args.parallel))
    print("\n===== RUN SUMMARY =====")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
