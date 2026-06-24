# provenance.py
"""Primitive 1 -- provenance. An origin tag carried on every ingested byte; provenance,
not location/format, decides whether content may be OBEYED or BELIEVED. See spec."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Origin(Enum):
    HUMAN = "human"        # authored by a person -> may be obeyed
    SCRAPE = "scrape"      # fetched from an external source -> data, attest before trust
    BRAIN = "brain"        # the Ollama brain produced it -> never self-authoritative
    EXECUTOR = "executor"  # the Claude executor produced it -> least trusted
    DERIVED = "derived"    # computed from other rows -> inherits weakest input


@dataclass(frozen=True)
class Provenance:
    origin: Origin
    attested_by: Optional[str] = None       # who independently vouched (e.g. a REAL adversary)
    integrity: Optional[str] = None         # content hash / sidecar digest
    authoring_task_id: Optional[str] = None

    def toDict(self) -> dict:
        return {"origin": self.origin.value, "attested_by": self.attested_by,
                "integrity": self.integrity, "authoring_task_id": self.authoring_task_id}

    @classmethod
    def fromDict(cls, d: dict) -> "Provenance":
        return cls(origin=Origin(d["origin"]), attested_by=d.get("attested_by"),
                   integrity=d.get("integrity"), authoring_task_id=d.get("authoring_task_id"))


def coerce(d: Optional[dict]) -> Provenance:
    """Best-effort parse; ANY malformed/absent provenance degrades to EXECUTOR (least
    trusted) so missing provenance can never be mistaken for human authority."""
    if not isinstance(d, dict):
        return Provenance(origin=Origin.EXECUTOR)
    try:
        return Provenance.fromDict(d)
    except Exception:  # noqa: BLE001
        return Provenance(origin=Origin.EXECUTOR)
