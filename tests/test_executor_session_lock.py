"""Session-limit window state must be concurrency-safe (B13).

Concurrent workers hitting the token limit at once must all observe ONE reset window,
never a lost/duplicated ``first_hit_at``.
"""
from __future__ import annotations

import threading

import pytest

from agents import executor_session as es


def test_register_first_hit_is_atomic():
    es._SESSION_LIMIT_STATE["first_hit_at"] = None
    results: list[float] = []
    results_lock = threading.Lock()
    n = 16
    barrier = threading.Barrier(n)

    def worker(t: float) -> None:
        barrier.wait()  # maximise contention on the read-modify-write
        val = es._registerFirstHit(t)
        with results_lock:
            results.append(val)

    threads = [threading.Thread(target=worker, args=(100.0 + i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Exactly one window wins; every worker sees the same baseline.
    assert len(results) == n
    assert len(set(results)) == 1
    assert es._SESSION_LIMIT_STATE["first_hit_at"] == results[0]
    es._clearSessionState()
    assert es._SESSION_LIMIT_STATE["first_hit_at"] is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
