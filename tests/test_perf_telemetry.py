from __future__ import annotations

import config
from platform_core.runtime import perf


def test_perf_telemetry_summarizes_recent_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PERF_TELEMETRY_PATH", tmp_path / "perf.jsonl", raising=False)

    perf.record("validation_suite", 1.25, ok=True)
    perf.record("validation_suite", 0.75, ok=True)
    perf.record("retrieval_content", 0.5, ann_hit=True)

    summary = perf.summarize()

    assert summary["validation_suite"] == 2.0
    assert summary["retrieval_content"] == 0.5
