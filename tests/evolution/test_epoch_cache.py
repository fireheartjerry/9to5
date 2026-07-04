from __future__ import annotations

import sqlite3

import config
import platform_core.core.epoch as epoch


def test_epoch_fingerprint_cache_reuses_unchanged_file_hash(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    f = root / "m.py"
    f.write_text("x = 1\n", encoding="utf-8")
    calls = 0
    real_hash = epoch._hashFile

    def counted(path: str) -> str:
        nonlocal calls
        calls += 1
        return real_hash(path)

    monkeypatch.setattr(config, "PROJECT_ROOT", root, raising=False)
    monkeypatch.setattr(config, "REPO_MERKLE_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(epoch.identity, "selfCodeFiles", lambda: [str(f)])
    monkeypatch.setattr(epoch, "_gitSha", lambda: "head")
    monkeypatch.setattr(epoch, "_hashFile", counted)

    first = epoch.fingerprint()
    second = epoch.fingerprint()

    assert first == second
    assert calls == 1

    f.write_text("x = 2\n", encoding="utf-8")
    third = epoch.fingerprint()

    assert third["files"][str(f).lower()] != first["files"][str(f).lower()]
    assert calls == 2


def test_fingerprint_cached_closes_its_sqlite_connection(tmp_path, monkeypatch):
    """Finding 2 regression: sqlite3's own context manager only commits/rolls back the
    transaction, it does NOT close the connection -- _fingerprintCached must close it
    explicitly (contextlib.closing) so a long run does not leak one open handle per
    subtask boundary (and, on Windows, hold a file lock on state/epoch_fingerprint_cache.db)."""
    root = tmp_path / "repo"
    root.mkdir()
    f = root / "m.py"
    f.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(config, "PROJECT_ROOT", root, raising=False)

    opened: list[sqlite3.Connection] = []
    real_cache_conn = epoch._cacheConn

    def tracked():
        conn = real_cache_conn()
        opened.append(conn)
        return conn

    monkeypatch.setattr(epoch, "_cacheConn", tracked)

    epoch._fingerprintCached([str(f)])

    assert opened, "expected _cacheConn to be called at least once"
    for conn in opened:
        # A closed sqlite3.Connection raises ProgrammingError on any use.
        try:
            conn.execute("SELECT 1")
        except sqlite3.ProgrammingError:
            pass
        else:
            raise AssertionError("connection from _fingerprintCached was left open")


def test_fingerprint_files_always_hashes_content_even_with_stale_cache_row(tmp_path, monkeypatch):
    """Finding 3 regression: _fingerprintFiles() (the divergence-feeding path) must ignore
    the (size, mtime_ns) cache shortcut entirely. Simulate the exact hazard: a cache row
    claims the file's current (size, mtime_ns) already match a DIFFERENT sha256 than the
    file's real current content -- as would happen after a same-size, same-mtime in-place
    edit on a coarse-mtime filesystem. fingerprint()/the cache would return the stale
    cached digest; _fingerprintFiles() must return the true content hash regardless."""
    root = tmp_path / "repo"
    root.mkdir()
    f = root / "m.py"
    f.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(config, "PROJECT_ROOT", root, raising=False)
    monkeypatch.setattr(config, "REPO_MERKLE_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(epoch.identity, "selfCodeFiles", lambda: [str(f)])

    st = f.stat()
    poisoned_digest = "deadbeef" * 8  # a fake sha256-shaped value, deliberately wrong
    cache_path = epoch._cachePath()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(cache_path)) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS file_hashes ("
            "path TEXT PRIMARY KEY, size INTEGER, mtime_ns INTEGER, sha256 TEXT)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO file_hashes(path, size, mtime_ns, sha256) VALUES (?, ?, ?, ?)",
            (str(f).lower(), st.st_size, st.st_mtime_ns, poisoned_digest),
        )

    # The mtime-cached path trusts the poisoned row (proves the cache shortcut is live).
    cached = epoch._fingerprintCached([str(f)])
    assert cached[str(f).lower()] == poisoned_digest

    # The divergence-feeding path must NOT trust it -- always hash real content instead.
    direct = epoch._fingerprintFiles()
    assert direct[str(f).lower()] == epoch._hashFile(str(f))
    assert direct[str(f).lower()] != poisoned_digest
