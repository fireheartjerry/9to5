"""RED contracts for external, non-stageable per-attempt runtime projections."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def _projection():
    return importlib.import_module("platform_core.execution.runtime_projection")


def test_projection_is_external_content_addressed_and_candidate_stays_clean(
    tmp_path: Path,
) -> None:
    mod = _projection()
    candidate = tmp_path / "candidate"
    external = tmp_path / "external" / "runtime"
    candidate.mkdir()

    projection = mod.RuntimeProjection.create(
        root=external,
        transaction_id="tx_projection",
        settings={"permissions": {"allow": []}},
        context=b"bounded generated context",
        task_snapshot={"task_id": "task-1", "status": "running"},
        forbidden_roots=(candidate,),
    )

    assert projection.root.is_relative_to(external)
    assert projection.manifest_digest == projection.recomputeManifestDigest()
    assert projection.session_root.is_relative_to(projection.root)
    assert projection.telemetry_root.is_relative_to(projection.root)
    assert list(candidate.iterdir()) == []


def test_projection_refuses_candidate_or_canonical_overlap(tmp_path: Path) -> None:
    mod = _projection()
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    with pytest.raises(mod.RuntimeProjectionRefused):
        mod.RuntimeProjection.create(
            root=candidate / ".runtime",
            transaction_id="tx_projection",
            settings={},
            context=b"context",
            task_snapshot={"task_id": "task-1"},
            forbidden_roots=(candidate,),
        )
