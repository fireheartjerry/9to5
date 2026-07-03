from __future__ import annotations

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
