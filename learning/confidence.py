"""Introspective confidence + calibrated deferral -- subsystem K of the SIE.

Train the brain to predict its OWN success probability for a subtask and act on it: low
confidence escalates effort/model or inserts a gate; high confidence takes the cheap path.
Reuses the logistic Calibrator from reward.py, fit on the ledger. Offline-testable.

See the spec (subsystem K).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import config
from learning import reward
from memory import experience

LOG = config.getLogger("sie.confidence")


def fit_from_ledger(*, db_path: Optional[Path] = None,
                    epochs: int = 300) -> reward.Calibrator:
    """Fit a success-probability head on all subtasks with a known verify outcome."""
    rows = [r for r in experience.fetch_subtasks(db_path=db_path)
            if r.get("verify_passed") is not None]
    return reward.Calibrator().fit(rows, epochs=epochs)


def predict(cal: reward.Calibrator, row: dict[str, Any]) -> float:
    return cal.predict(row)


def recommend(prob: float, *, threshold: Optional[float] = None) -> str:
    """Map a predicted success probability to an action.

    < threshold        -> 'escalate' (more effort / add a gate)
    < 1.5*threshold    -> 'proceed'
    otherwise          -> 'fast' (cheap path)
    """
    threshold = config.CONFIDENCE_DEFER_THRESHOLD if threshold is None else threshold
    if prob < threshold:
        return "escalate"
    if prob < min(1.0, threshold * 1.5):
        return "proceed"
    return "fast"


def should_escalate(cal: reward.Calibrator, row: dict[str, Any], *,
                    threshold: Optional[float] = None) -> bool:
    return recommend(predict(cal, row), threshold=threshold) == "escalate"
