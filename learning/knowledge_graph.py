"""Project knowledge graph -- subsystem N of the SIE.

A growing map of the codebase/domain so the brain knows THIS project better every month.
Built from ledger outcomes + the failure taxonomy: one node per task family (its pass
rate) and one per recurring gotcha. Universe-scoped injection keeps it surgical. Pure-
stdlib + ledger; offline-testable.

See the spec (subsystem N).
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

import config
from learning.lessons import family_of
from memory import experience

LOG = config.getLogger("sie.kg")


def build_from_ledger(*, db_path: Optional[Path] = None) -> dict[str, int]:
    """Rebuild family + gotcha nodes from the ledger. Idempotent (upserts by key)."""
    agg: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in experience.fetch_subtasks(db_path=db_path):
        fam = family_of(r.get("title") or "", r.get("signature_tags"))
        agg[fam][0] += 1
        if r.get("verify_passed") == 1:
            agg[fam][1] += 1
    nodes = 0
    for fam, (total, passed) in agg.items():
        summary = f"{passed}/{total} subtasks passed ({passed / total:.0%})"
        if experience.upsert_kg_node("family", fam, summary, db_path=db_path):
            nodes += 1
    for fm in experience.fetch_failure_modes(db_path=db_path):
        key = f"{fm['signature_tags']}:{fm['taxonomy_class']}"
        if experience.upsert_kg_node("gotcha", key,
                                     f"{fm['root_cause']} -> {fm.get('mitigation', '')}",
                                     db_path=db_path):
            nodes += 1
    return {"nodes": nodes}


def context_for(title: str, *, db_path: Optional[Path] = None) -> str:
    """Best-effort knowledge-graph context for a subtask's family (or "")."""
    try:
        fam = family_of(title or "", None)
        for n in experience.fetch_kg_nodes("family", db_path=db_path):
            if n["key"] == fam:
                return f"## CODEBASE NOTE ('{fam}'): {n['summary']}\n\n"
        return ""
    except Exception as e:  # noqa: BLE001
        LOG.debug("kg context_for failed (ignored): %s", e)
        return ""
