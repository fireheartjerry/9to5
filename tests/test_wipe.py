"""B31: wipe 'logs' category targets config.LOG_PATH; wipe never deletes Python source."""
import config
from platform_core.ops import wipe


def test_logs_category_targets_config_log_path():
    # 'logs' must resolve to the CONFIGURED LOG_PATH, not a hardcoded INSTALL_ROOT/logs.
    assert wipe.CATEGORIES["logs"]["paths"] == [config.LOG_PATH]


def test_logs_wipe_deletes_configured_dir(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "run.log").write_text("hi", encoding="utf-8")
    monkeypatch.setitem(wipe.CATEGORIES, "logs",
                        {"paths": [log_dir], "label": "Execution logs"})
    ok, msg = wipe.deleteCategory("logs")
    assert ok, msg
    assert not log_dir.exists()


def test_holds_python_source_fail_closed(tmp_path):
    py = tmp_path / "mod.py"
    py.write_text("x = 1", encoding="utf-8")
    assert wipe._holdsPythonSource(py) is True

    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    assert wipe._holdsPythonSource(pkg) is True                 # importable package

    data = tmp_path / "vault"
    data.mkdir()
    (data / "note.md").write_text("notes", encoding="utf-8")
    assert wipe._holdsPythonSource(data) is False               # data dir is deletable


def test_delete_category_refuses_python_source(tmp_path, monkeypatch):
    pkg = tmp_path / "learning"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "sie.py").write_text("x = 1", encoding="utf-8")
    monkeypatch.setitem(wipe.CATEGORIES, "learning",
                        {"paths": [pkg], "label": "Learning directory"})
    ok, msg = wipe.deleteCategory("learning")
    assert not ok
    assert "Python source" in msg
    assert pkg.exists() and (pkg / "sie.py").exists()           # never deleted .py
