"""trace-replay -- loads archived execution traces and surfaces brain divergence points.

Replays a run's JSONL event log step-by-step, identifies where the brain deviated
from the optimal path (verify failures, replans, adversary challenges, multi-attempt
subtasks), and prints a structured replay report.

Usage:
    python agents/trace-replay.py [--run-id RUN_ID] [--limit N] [--calibrate]
                                   [--format text|json] [--chart] [--no-color]

If --run-id is omitted, the most-recent run is used. Exits 0 even when no traces
exist (prints a notice and exits cleanly).

The high-activity threshold is derived empirically at startup from all available
run traces (90th-percentile of per-subtask event counts + 1). When no traces exist
the fallback is _FALLBACK_THRESHOLD.

Enhanced features:
  --chart       Print ASCII bar chart of per-subtask event distribution.
  --format json Emit machine-readable JSON report (suitable for CI pipelines).
  --no-color    Disable ANSI color output even on capable terminals.
  Parallel detection: events sharing the same timestamp across subtasks are
  flagged as concurrent execution for multi-env trace analysis.

@AI-MAP v2
EXPORTS: (standalone script — no importable API)
DEPENDS-ON: tracing, config
RUN/TEST: python C:\\9to5\\agents\\trace-replay.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

# path bootstrap: allow running from any cwd
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
import tracing  # noqa: E402

LOG = config.getLogger("trace_replay")

# ── ANSI color helpers ────────────────────────────────────────────────────────

def _colorEnabled() -> bool:
    """True when stdout is a real TTY and NO_COLOR / --no-color not set."""
    if os.environ.get("NO_COLOR"):
        return False
    if not sys.stdout.isatty():
        return False
    return True


_COLORS = {
    "FAIL":      "\033[31m",   # red
    "REPLAN":    "\033[33m",   # yellow
    "CHALLENGE": "\033[35m",   # magenta
    "PASS":      "\033[32m",   # green
    "INFO":      "\033[36m",   # cyan
    "HIGH":      "\033[91m",   # bright red (high-activity label)
    "HEADER":    "\033[1;34m", # bold blue
    "RESET":     "\033[0m",
}

# Module-level flag; main() sets this before calling _replayEvents.
_USE_COLOR: bool = False


def _c(kind: str, text: str) -> str:
    if not _USE_COLOR:
        return text
    return _COLORS.get(kind, "") + text + _COLORS["RESET"]


# ── Event classification ──────────────────────────────────────────────────────

_FAIL_EVENTS: frozenset[str] = frozenset({
    "verification_failed", "verify_fail", "verify_failed",
    "executor_failed", "step_failed", "run_failed", "subtask_failed",
})
_REPLAN_EVENTS: frozenset[str] = frozenset({
    "replan", "replan_split", "replanned", "replan_triggered",
})
_ADVERSARY_EVENTS: frozenset[str] = frozenset({
    "adversary_challenged", "adversary_challenge",
})
_PASS_EVENTS: frozenset[str] = frozenset({
    "verification_passed", "verify_pass", "verify_passed", "run_completed",
})
_DIVERGENCE_SIGNALS: frozenset[str] = _FAIL_EVENTS | _REPLAN_EVENTS | _ADVERSARY_EVENTS

# Fallback used when no trace data exists to calibrate from.
# Derived heuristically: a subtask with >10 events is already 3-4× a typical
# happy-path subtask (~3 events: start + verify_pass + run_completed).
_FALLBACK_THRESHOLD: int = 10


# ── Pure functions ────────────────────────────────────────────────────────────

def _computeThresholdFromCounts(counts: list[int]) -> int:
    """Return 90th-percentile + 1, floored at _FALLBACK_THRESHOLD.

    Pure function — no I/O.  Tested directly by _selfTest().
    """
    if not counts:
        return _FALLBACK_THRESHOLD
    sorted_counts = sorted(counts)
    p90_idx = min(int(len(sorted_counts) * 0.90), len(sorted_counts) - 1)
    return max(sorted_counts[p90_idx] + 1, _FALLBACK_THRESHOLD)


def _calibrateThreshold(run_ids: list[str]) -> int:
    """Derive high-activity threshold from empirical event distribution.

    Loads events from all provided run IDs, collects per-subtask event counts,
    and delegates to _computeThresholdFromCounts.  Falls back to
    _FALLBACK_THRESHOLD when no trace data is available.
    """
    counts: list[int] = []
    for run_id in run_ids:
        events = tracing.readEvents(run_id)
        bucket: dict[str, int] = {}
        for ev in events:
            st = ev.get("subtask_id") or "-"
            bucket[st] = bucket.get(st, 0) + 1
        counts.extend(bucket.values())
    return _computeThresholdFromCounts(counts)


def _parseTs(ts_str: Optional[str]) -> Optional[float]:
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
    except Exception:  # noqa: BLE001
        return None


def _fmtOffset(base_ts: float, ts: float) -> str:
    return f"T+{ts - base_ts:.2f}s"


def _classify(event: str) -> str:
    e = (event or "").lower()
    if e in _FAIL_EVENTS:
        return "FAIL"
    if e in _REPLAN_EVENTS:
        return "REPLAN"
    if e in _ADVERSARY_EVENTS:
        return "CHALLENGE"
    if e in _PASS_EVENTS:
        return "PASS"
    return "INFO"


def _keyFields(ev: dict) -> str:
    skip = {"ts", "run_id", "subtask_id", "event"}
    parts = []
    for k, v in ev.items():
        if k in skip or v is None:
            continue
        s = str(v)
        if len(s) > 80:
            s = s[:77] + "..."
        parts.append(f"{k}={s!r}")
    return "  ".join(parts[:6])


# ── Visual aids ───────────────────────────────────────────────────────────────

def _renderBarChart(subtask_event_count: dict[str, int], threshold: int) -> None:
    """Print ASCII bar chart of per-subtask event counts."""
    if not subtask_event_count:
        return
    max_count = max(subtask_event_count.values())
    bar_width = 30
    print(_c("HEADER", "\nEVENT DISTRIBUTION PER SUBTASK"))
    print(_c("HEADER", "─" * 56))
    for st, cnt in sorted(subtask_event_count.items(), key=lambda x: -x[1]):
        filled = int(bar_width * cnt / max_count) if max_count else 0
        bar = "█" * filled + "░" * (bar_width - filled)
        label = _c("HIGH", bar) if cnt > threshold else bar
        flag = _c("HIGH", " ← HIGH") if cnt > threshold else ""
        print(f"  {str(st):<16}  [{label}]  {cnt:>4}{flag}")
    print()


def _detectParallelSubtasks(events: list[dict]) -> list[tuple[float, list[str]]]:
    """Find timestamps where multiple distinct subtasks have events simultaneously.

    Returns list of (ts, [subtask_id, ...]) for each parallel moment.
    Useful for multi-environment / distributed execution traces.
    """
    ts_subtasks: dict[float, set[str]] = defaultdict(set)
    for ev in events:
        ts = _parseTs(ev.get("ts"))
        if ts is None:
            continue
        st = ev.get("subtask_id") or "-"
        ts_subtasks[ts].add(st)
    return [
        (ts, sorted(sids))
        for ts, sids in sorted(ts_subtasks.items())
        if len(sids) > 1
    ]


# ── Decision-point extraction ─────────────────────────────────────────────────

def _extractDecisionPoints(
    events: list[dict],
    context_window: int = 2,
) -> list[dict]:
    """Extract divergence events with surrounding context for step-by-step debugging.

    Returns a list of dicts, one per FAIL/REPLAN/CHALLENGE event, each with:
        index, event, subtask, kind, ts, offset, fields,
        context_before (up to context_window events before),
        context_after  (up to context_window events after)
    """
    if not events:
        return []
    base_ts = _parseTs(events[0].get("ts")) or 0.0

    def _ctx_entry(ev: dict) -> dict:
        return {
            "event": ev.get("event", "unknown"),
            "subtask": ev.get("subtask_id") or "-",
            "ts": _parseTs(ev.get("ts")),
        }

    decision_points: list[dict] = []
    for i, ev in enumerate(events):
        event = ev.get("event", "unknown")
        kind = _classify(event)
        if kind not in ("FAIL", "REPLAN", "CHALLENGE"):
            continue
        ts = _parseTs(ev.get("ts")) or base_ts
        subtask = ev.get("subtask_id") or "-"
        decision_points.append({
            "index": i,
            "event": event,
            "subtask": subtask,
            "kind": kind,
            "ts": ts,
            "offset": _fmtOffset(base_ts, ts),
            "fields": _keyFields(ev),
            "context_before": [_ctx_entry(e) for e in events[max(0, i - context_window):i]],
            "context_after": [_ctx_entry(e) for e in events[i + 1:i + 1 + context_window]],
        })
    return decision_points


# ── Core replay logic ─────────────────────────────────────────────────────────

def _replayEvents(
    events: list[dict],
    threshold: int,
    run_id: str = "?",
    show_chart: bool = False,
    output_format: str = "text",
) -> int:
    """Core replay logic over a pre-loaded event list. Pure — no disk I/O.

    Returns the count of divergence events so callers (including _selfTest)
    can assert on the number without parsing stdout.

    Args:
        events:        Pre-loaded event list.
        threshold:     High-activity cutoff (events per subtask).
        run_id:        Label for the trace header.
        show_chart:    When True, print ASCII bar chart after summary.
        output_format: 'text' (default) or 'json' (machine-readable).
    """
    base_ts = _parseTs(events[0].get("ts")) or 0.0 if events else 0.0
    divergences: list[dict] = []
    subtask_event_count: dict[str, int] = {}

    if output_format == "json":
        # Collect and emit structured JSON — no decorative print.
        for ev in events:
            ts = _parseTs(ev.get("ts")) or base_ts
            event = ev.get("event", "unknown")
            subtask = ev.get("subtask_id") or "-"
            kind = _classify(event)
            subtask_event_count[subtask] = subtask_event_count.get(subtask, 0) + 1
            if kind in ("FAIL", "REPLAN", "CHALLENGE"):
                divergences.append({
                    "offset": _fmtOffset(base_ts, ts),
                    "event": event,
                    "subtask": subtask,
                    "kind": kind,
                    "fields": _keyFields(ev),
                    "ts": ts,
                })
        high_activity = {
            st: cnt for st, cnt in subtask_event_count.items() if cnt > threshold
        }
        parallel_moments = _detectParallelSubtasks(events)
        report = {
            "run_id": run_id,
            "total_events": len(events),
            "divergence_count": len(divergences),
            "high_activity_count": len(high_activity),
            "parallel_moments": len(parallel_moments),
            "divergences": divergences,
            "high_activity_subtasks": high_activity,
        }
        print(json.dumps(report, indent=2))
        return len(divergences)

    # ── text output ──
    print(f"\n{_c('HEADER', 'TRACE REPLAY')}  run_id={run_id}  events={len(events)}  threshold={threshold}")
    print("=" * 72)
    print(f"{'OFFSET':<13}  {'KIND':<10}  {'SUBTASK':<14}  EVENT + FIELDS")
    print("-" * 72)

    for ev in events:
        ts = _parseTs(ev.get("ts")) or base_ts
        offset = _fmtOffset(base_ts, ts)
        event = ev.get("event", "unknown")
        subtask = ev.get("subtask_id") or "-"
        kind = _classify(event)
        fields = _keyFields(ev)

        subtask_event_count[subtask] = subtask_event_count.get(subtask, 0) + 1

        kind_label = _c(kind, f"[{kind:<9}]")
        line = f"{offset:<13}  {kind_label}  {str(subtask):<14}  {event}"
        if fields:
            line += f"  |  {fields}"
        print(line)

        if kind in ("FAIL", "REPLAN", "CHALLENGE"):
            divergences.append({
                "offset": offset,
                "event": event,
                "subtask": subtask,
                "kind": kind,
                "fields": fields,
                "ts": ts,
            })

    high_activity = {
        st: cnt
        for st, cnt in subtask_event_count.items()
        if cnt > threshold
    }

    # Parallel execution detection.
    parallel_moments = _detectParallelSubtasks(events)

    print("-" * 72)
    print(f"\n{_c('HEADER', 'SUMMARY')}")
    print(f"  Total events      : {len(events)}")
    print(f"  Divergence signals: {len(divergences)}")
    print(f"  High-activity     : {len(high_activity)} subtask(s) with >{threshold} events")
    if parallel_moments:
        print(f"  Parallel moments  : {len(parallel_moments)} timestamp(s) with concurrent subtasks")

    if divergences:
        print(f"\n{_c('HEADER', 'DIVERGENCE POINTS')}  (chronological)")
        for d in divergences:
            kind_label = _c(d["kind"], f"[{d['kind']:<9}]")
            print(f"  {d['offset']:>13}  {kind_label}  {d['subtask']:<14}  {d['event']}")
            if d["fields"]:
                print(f"  {'':13}  {'':10}  {'':14}  -> {d['fields']}")
        first = divergences[0]
        print(f"\n{_c('FAIL', 'EARLIEST DIVERGENCE')}: {first['offset']}  event={first['event']!r}"
              f"  subtask={first['subtask']!r}")
        print("  Next step: read the subtask's Obsidian note and verifier stdout/stderr")
        print("             for full context; the fields above are the primary signals.")
    else:
        print(f"\n  {_c('PASS', 'No divergence signals detected')} — run appears clean.")

    if high_activity:
        print(f"\n{_c('HIGH', 'HIGH-ACTIVITY SUBTASKS')} (possible retry storms):")
        for st, cnt in sorted(high_activity.items(), key=lambda x: -x[1]):
            print(f"  {_c('HIGH', str(st))}: {cnt} events")

    if parallel_moments:
        print(f"\n{_c('HEADER', 'PARALLEL EXECUTION MOMENTS')} (concurrent subtasks at same timestamp):")
        for ts_val, sids in parallel_moments[:10]:
            offset = _fmtOffset(base_ts, ts_val)
            print(f"  {offset:>13}  subtasks: {', '.join(sids)}")
        if len(parallel_moments) > 10:
            print(f"  ... and {len(parallel_moments) - 10} more")

    if show_chart:
        _renderBarChart(subtask_event_count, threshold)

    return len(divergences)


def replayTrace(run_id: str, threshold: int) -> int:
    """Load and replay one run's event trace. Returns count of divergence events."""
    events = tracing.readEvents(run_id)
    if not events:
        print(f"[trace-replay] No events found for run {run_id}.")
        return 0
    return _replayEvents(events, threshold, run_id=run_id)


# ── Built-in self-test ────────────────────────────────────────────────────────

def _selfTest() -> None:
    """Validate divergence detection + high-activity logic against synthetic fixtures.

    Runs in-process with no disk I/O.  Raises AssertionError on mismatch so any
    regression is caught immediately at startup.
    """
    fixtures: list[dict] = [
        {"ts": "2026-01-01T00:00:00+00:00", "run_id": "t", "subtask_id": "st-A", "event": "verification_failed"},
        {"ts": "2026-01-01T00:00:01+00:00", "run_id": "t", "subtask_id": "st-A", "event": "replan_triggered"},
        {"ts": "2026-01-01T00:00:02+00:00", "run_id": "t", "subtask_id": "st-B", "event": "adversary_challenged"},
        {"ts": "2026-01-01T00:00:03+00:00", "run_id": "t", "subtask_id": "st-B", "event": "executor_failed"},
        {"ts": "2026-01-01T00:00:04+00:00", "run_id": "t", "subtask_id": "st-C", "event": "run_completed"},
        {"ts": "2026-01-01T00:00:05+00:00", "run_id": "t", "subtask_id": "st-C", "event": "verify_passed"},
        {"ts": "2026-01-01T00:00:06+00:00", "run_id": "t", "subtask_id": "st-C", "event": "verify_passed"},
    ]

    # --- classification ---
    assert _classify("verification_failed") == "FAIL"
    assert _classify("verify_fail") == "FAIL"
    assert _classify("executor_failed") == "FAIL"
    assert _classify("replan_triggered") == "REPLAN"
    assert _classify("replan_split") == "REPLAN"
    assert _classify("adversary_challenged") == "CHALLENGE"
    assert _classify("run_completed") == "PASS"
    assert _classify("verify_passed") == "PASS"
    assert _classify("subtask_started") == "INFO"

    divergences = [ev for ev in fixtures if _classify(ev["event"]) in ("FAIL", "REPLAN", "CHALLENGE")]
    assert len(divergences) == 4, f"Expected 4 divergences, got {len(divergences)}"

    # --- high-activity detection at threshold=2 ---
    bucket: dict[str, int] = {}
    for ev in fixtures:
        st = ev.get("subtask_id") or "-"
        bucket[st] = bucket.get(st, 0) + 1
    high = {st: cnt for st, cnt in bucket.items() if cnt > 2}
    assert "st-C" in high, "st-C (3 events) must be flagged at threshold=2"
    assert "st-A" not in high, "st-A (2 events) must not be flagged at threshold=2"
    assert "st-B" not in high, "st-B (2 events) must not be flagged at threshold=2"

    # --- calibration: synthetic corpus of 10 subtasks (counts 1..10) ---
    # p90 index = int(10 * 0.90) = 9 → sorted[9] = 10; threshold = max(10+1, 10) = 11
    assert _computeThresholdFromCounts([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]) == 11
    # single-element corpus: p90_idx=0, value=3; threshold = max(3+1, 10) = 10 (floored)
    assert _computeThresholdFromCounts([3]) == _FALLBACK_THRESHOLD
    # empty corpus → fallback
    assert _computeThresholdFromCounts([]) == _FALLBACK_THRESHOLD
    # corpus where p90 exceeds fallback
    assert _computeThresholdFromCounts([20] * 10) == 21

    # --- full pipeline: fixture trace through _replayEvents returns correct count ---
    # threshold=2 → st-C (3 events) is high-activity; divergence count must be 4
    div_count = _replayEvents(fixtures, threshold=2, run_id="fixture-t")
    assert div_count == 4, f"_replayEvents on fixture trace: expected 4 divergences, got {div_count}"

    # fixture with zero divergences must return 0
    clean_fixtures: list[dict] = [
        {"ts": "2026-01-01T00:00:00+00:00", "run_id": "c", "subtask_id": "st-X", "event": "run_completed"},
        {"ts": "2026-01-01T00:00:01+00:00", "run_id": "c", "subtask_id": "st-X", "event": "verify_passed"},
    ]
    clean_count = _replayEvents(clean_fixtures, threshold=1, run_id="fixture-clean")
    assert clean_count == 0, f"_replayEvents on clean trace: expected 0 divergences, got {clean_count}"

    # --- parallel detection: two subtasks at same timestamp ---
    parallel_events: list[dict] = [
        {"ts": "2026-01-01T00:00:00+00:00", "run_id": "p", "subtask_id": "st-P1", "event": "run_completed"},
        {"ts": "2026-01-01T00:00:00+00:00", "run_id": "p", "subtask_id": "st-P2", "event": "verify_passed"},
        {"ts": "2026-01-01T00:00:01+00:00", "run_id": "p", "subtask_id": "st-P1", "event": "verify_passed"},
    ]
    parallel = _detectParallelSubtasks(parallel_events)
    assert len(parallel) == 1, f"Expected 1 parallel moment, got {len(parallel)}"
    assert set(parallel[0][1]) == {"st-P1", "st-P2"}

    # --- JSON output returns correct count ---
    import io
    _capture = io.StringIO()
    _old_stdout = sys.stdout
    sys.stdout = _capture
    json_count = _replayEvents(fixtures, threshold=2, run_id="json-t", output_format="json")
    sys.stdout = _old_stdout
    assert json_count == 4, f"JSON mode divergence count: expected 4, got {json_count}"
    parsed = json.loads(_capture.getvalue())
    assert parsed["divergence_count"] == 4
    assert parsed["run_id"] == "json-t"


# ── CLI entry point ───────────────────────────────────────────────────────────

def main() -> int:
    global _USE_COLOR

    parser = argparse.ArgumentParser(
        description="Replay a 9to5 execution trace and surface brain divergence points.",
    )
    parser.add_argument("--run-id", help="Run ID to replay (default: most recent)")
    parser.add_argument(
        "--limit", type=int, default=5,
        help="Max recent runs to consider when --run-id is omitted (default: 5)",
    )
    parser.add_argument(
        "--calibrate", action="store_true",
        help="Print the empirically derived threshold and exit without replaying",
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help="Run built-in self-tests against synthetic fixtures and exit (no trace needed)",
    )
    parser.add_argument(
        "--chart", action="store_true",
        help="Print ASCII bar chart of per-subtask event distribution",
    )
    parser.add_argument(
        "--format", choices=["text", "json"], default="text",
        help="Output format: text (default) or json (machine-readable)",
    )
    parser.add_argument(
        "--no-color", action="store_true",
        help="Disable ANSI color output",
    )
    args = parser.parse_args()

    _USE_COLOR = _colorEnabled() and not args.no_color

    # --self-test: validate logic integrity without loading any real trace data.
    if args.self_test:
        _selfTest()
        print("[trace-replay] All self-tests passed.")
        return 0

    # Always run the self-test to validate logic integrity.
    _selfTest()

    # Calibrate threshold from all available runs (not just the target run).
    all_run_ids = tracing.recentRunIds(limit=100)
    threshold = _calibrateThreshold(all_run_ids)
    if not all_run_ids:
        print(f"[trace-replay] No prior traces found — using fallback threshold={threshold}")
    else:
        print(f"[trace-replay] Calibrated threshold={threshold} from {len(all_run_ids)} run(s)")

    if args.calibrate:
        return 0

    run_id: Optional[str] = args.run_id
    if not run_id:
        recent = tracing.recentRunIds(limit=args.limit)
        if not recent:
            print("[trace-replay] No archived runs found under logs/runs/. Nothing to replay.")
            print("[trace-replay] Run 9to5 first to generate a trace, then replay with:")
            print("               python agents/trace-replay.py --run-id <run_id>")
            return 0
        run_id = recent[0]
        print(f"[trace-replay] Using most recent run: {run_id}")
        if len(recent) > 1:
            print(f"[trace-replay] Other available: {', '.join(recent[1:])}")

    events = tracing.readEvents(run_id)
    if not events:
        print(f"[trace-replay] No events found for run {run_id}.")
        return 0

    _replayEvents(
        events,
        threshold,
        run_id=run_id,
        show_chart=args.chart,
        output_format=args.format,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
