"""Stage 0 provenance and immutable-baseline assertions."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GALAXY_CONFIG = ROOT / "config" / "galaxy"


def _load(name: str) -> dict:
    with (GALAXY_CONFIG / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def test_artifact_assertion_rehashes_every_frozen_input() -> None:
    assertion = _load("artifacts.v1.json")

    assert len(assertion["specifications"]) == 7
    assert len(assertion["implementation_plans"]) == 4
    assert len(assertion["research_artifacts"]) == 2
    for group in (
        "specifications",
        "implementation_plans",
        "research_artifacts",
    ):
        for artifact in assertion[group]:
            payload = (ROOT / artifact["path"]).read_bytes()
            assert hashlib.sha256(payload).hexdigest() == artifact["sha256"]


def test_migrated_child_plan_numbering_is_contiguous() -> None:
    assertion = _load("artifacts.v1.json")
    expected_counts = {
        "2026-07-13-galaxy-r3-transactional-kernel.md": 5,
        "2026-07-13-galaxy-r3-pulsar-r1-implementation-plan.md": 17,
        "2026-07-13-galaxy-r3-quark-r2-implementation-plan.md": 14,
        "2026-07-13-galaxy-r3-accretion-r1-implementation-plan.md": 22,
    }

    for artifact in assertion["implementation_plans"]:
        text = (ROOT / artifact["path"]).read_text(encoding="utf-8")
        numbers = []
        for raw in re.findall(r"^#{1,4}[^\n]*\bTask\s+(\d+)\b", text, re.M):
            number = int(raw)
            if number not in numbers:
                numbers.append(number)
        count = expected_counts[Path(artifact["path"]).name]
        assert numbers == list(range(1, count + 1))


def test_incumbent_baseline_is_pinned_before_behavior_changes() -> None:
    baseline = _load("incumbent-baseline.v1.json")

    assert baseline["source_revision"] == "c16bbebe880a9fa0963c79f707278c920aab6798"
    assert baseline["external_spend_allowed"] is False
    assert baseline["suite"]["passed"] == 4935
    assert baseline["suite"]["failed"] == 7
    assert baseline["suite"]["skipped"] == 3
    assert baseline["suite"]["exit_code"] == 1
