"""Networkless logical-ID SQLite state-store worker entrypoint."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import TextIO

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_DATA_ROOT = Path("/data")
_MAX_LINE = 4 * 1024 * 1024
BOOT_RESOURCE_UNAVAILABLE_EXIT_CODE = 78


def _database(database_id: str, *, data_root: Path | None = None) -> sqlite3.Connection:
    if not _ID.fullmatch(database_id):
        raise ValueError("invalid logical database ID")
    root = _DATA_ROOT if data_root is None else Path(data_root)
    root.mkdir(mode=0o700, parents=False, exist_ok=True)
    connection = sqlite3.connect(root / f"{database_id}.sqlite3", timeout=5.0)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS kv ("
        "namespace TEXT NOT NULL, key TEXT NOT NULL, value_json TEXT NOT NULL, "
        "PRIMARY KEY(namespace, key))"
    )
    return connection


def _handle(value: object, *, data_root: Path | None = None) -> object:
    if not isinstance(value, dict):
        raise ValueError("request must be an object")
    operation = value.get("operation")
    database_id = value.get("database_id")
    namespace = value.get("namespace")
    key = value.get("key", "")
    if not isinstance(database_id, str) or not isinstance(namespace, str) or not _ID.fullmatch(namespace):
        raise ValueError("invalid logical state scope")
    if not isinstance(key, str) or (key and not _ID.fullmatch(key)):
        raise ValueError("invalid logical state key")
    with _database(database_id, data_root=data_root) as connection:
        if operation == "kv_get":
            row = connection.execute(
                "SELECT value_json FROM kv WHERE namespace=? AND key=?",
                (namespace, key),
            ).fetchone()
            return None if row is None else json.loads(row[0])
        if operation == "kv_put":
            payload = json.dumps(
                value.get("value"),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            connection.execute(
                "INSERT INTO kv(namespace,key,value_json) VALUES(?,?,?) "
                "ON CONFLICT(namespace,key) DO UPDATE SET value_json=excluded.value_json",
                (namespace, key, payload),
            )
            return {"stored": True}
        if operation == "kv_delete":
            cursor = connection.execute(
                "DELETE FROM kv WHERE namespace=? AND key=?",
                (namespace, key),
            )
            return {"deleted": cursor.rowcount}
        if operation == "kv_list":
            rows = connection.execute(
                "SELECT key,value_json FROM kv WHERE namespace=? ORDER BY key LIMIT 10000",
                (namespace,),
            ).fetchall()
            return [{"key": row[0], "value": json.loads(row[1])} for row in rows]
    raise ValueError("unknown logical state operation")


def _handleAtDiagnosticRoot(data_root: Path, value: object) -> object:
    """Brownfield-test seam; the installed container always uses fixed ``/data``.

    The host compatibility facade refuses this operation once controller paths
    are active.  Keeping the engine here lets pre-activation tests exercise the
    exact closed RPC without reintroducing a path engine into product modules.
    """

    root = Path(data_root)
    if not root.is_absolute():
        raise ValueError("diagnostic state-worker root must be absolute")
    root.parent.mkdir(parents=True, exist_ok=True)
    return _handle(value, data_root=root)


def _openDiagnosticConnection(path: Path) -> sqlite3.Connection:
    """Pre-activation SQL compatibility for the brownfield experience ledger.

    Production never exposes this function through the closed worker protocol.
    It exists only so legacy tests remain runnable while callers are migrated to
    logical operations; the host facade disables it under capsule configuration.
    """

    target = Path(path)
    if not target.is_absolute():
        raise ValueError("diagnostic SQL path must be absolute")
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(target), timeout=30.0)
    connection.row_factory = sqlite3.Row
    return connection


def serve(reader: TextIO, writer: TextIO) -> int:
    for line in reader:
        if len(line.encode("utf-8")) > _MAX_LINE:
            return 2
        try:
            request = json.loads(line)
            result = {"ok": True, "result": _handle(request)}
        except (ValueError, TypeError, json.JSONDecodeError, sqlite3.Error) as exc:
            result = {"error": type(exc).__name__, "ok": False}
        writer.write(
            json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
        )
        writer.flush()
    return 0


def main() -> int:
    """Remain dark until boot supplies an attested store and worker channel.

    ``serve`` and the path-taking helpers are retained only for fenced
    pre-activation brownfield tests.  Executing this module directly must not
    turn those diagnostic seams into a production state-store process.
    """

    return BOOT_RESOURCE_UNAVAILABLE_EXIT_CODE


if __name__ == "__main__":
    raise SystemExit(main())
