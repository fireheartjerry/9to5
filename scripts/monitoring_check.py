"""monitoring_check.py -- acceptance check for enhanced monitoring.

Verifies that critical events are detected within 2 minutes of occurrence.

Expected output (stdout_contains): 'Critical event detected within 2 minutes'

Run:
    python C:\\9to5\\scripts\\monitoring_check.py
"""
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import monitoring
from monitoring.tracker import CRITICAL_DETECTION_WINDOW_SECS

monitoring.reset()

# Simulate a critical event that occurred 30 seconds ago (well within 2-min window).
occurred_at = time.time() - 30.0
monitoring.record_critical_event(
    event_id="evt-check-001",
    event_type="system_failure",
    occurred_at=occurred_at,
)

events = monitoring.get_critical_events()
alerts = monitoring.get_alerts()

late_ids = {
    a["event_id"]
    for a in alerts
    if a.get("type") == "critical_event_late_detection"
}

detected_in_time = [
    ev for ev in events
    if ev["lag_seconds"] <= CRITICAL_DETECTION_WINDOW_SECS
    and ev["event_id"] not in late_ids
]

if detected_in_time:
    for ev in detected_in_time:
        print(
            f"Critical event detected within 2 minutes "
            f"(lag: {ev['lag_seconds']:.1f}s, "
            f"event_id: {ev['event_id']}, "
            f"type: {ev['event_type']})"
        )
    sys.exit(0)
else:
    print("ERROR: No critical events detected within 2 minutes", file=sys.stderr)
    for ev in events:
        print(
            f"  event_id={ev['event_id']} lag={ev['lag_seconds']:.1f}s",
            file=sys.stderr,
        )
    sys.exit(1)
