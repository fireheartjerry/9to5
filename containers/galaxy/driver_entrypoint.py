"""Credentialed-driver JSONL protocol adapter.

The generic image contains no provider fallback.  Until an exact sealed provider
adapter is supplied by safe boot, requests terminate as typed unavailable.
"""

from __future__ import annotations

import json
import sys
from typing import TextIO

_MAX_LINE = 2 * 1024 * 1024


def _event(invocation_id: str, sequence: int, kind: str, payload: dict[str, object]) -> str:
    return (
        json.dumps(
            {
                "invocation_id": invocation_id,
                "kind": kind,
                "payload": payload,
                "sequence": sequence,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    )


def serve(reader: TextIO, writer: TextIO) -> int:
    for line in reader:
        if len(line.encode("utf-8")) > _MAX_LINE:
            return 2
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            return 2
        invocation_id = value.get("invocation_id") if isinstance(value, dict) else None
        if not isinstance(invocation_id, str) or not invocation_id:
            return 2
        writer.write(_event(invocation_id, 1, "started", {"adapter": "generic"}))
        writer.write(
            _event(
                invocation_id,
                2,
                "failure",
                {
                    "code": "provider_unavailable",
                    "reason": "no exact safe-booted provider adapter was mounted",
                },
            )
        )
        writer.flush()
    return 0


def main() -> int:
    return serve(sys.stdin, sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
