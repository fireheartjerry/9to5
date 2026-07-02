"""best_effort degradation kernel: swallow/count/dedup, summary shapes, the
NINE_TO_FIVE_LOG_LEVEL + RotatingFileHandler logging config, and the dev.py
bare-swallow ratchet (count may only go down vs tools/swallow_baseline.json)."""
import contextlib
import json
import logging
import logging.handlers
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from platform_core.core.best_effort import (
    DEGRADATIONS,
    best_effort,
    degradationLine,
    degradationSummary,
    recordDegradation,
    resetDegradations,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(autouse=True)
def _clean_registry():
    resetDegradations(warnings=True)
    yield
    resetDegradations(warnings=True)


# --------------------------------------------------------------------- kernel
def test_swallows_and_counts_100_with_one_warning(caplog):
    lg = logging.getLogger("beffort-test-dedup")
    with caplog.at_level(logging.DEBUG, logger="beffort-test-dedup"):
        for _ in range(100):
            with best_effort("obsidian.write", log=lg):
                raise ValueError("vault down")
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING
                and "best_effort[obsidian.write]" in r.getMessage()]
    assert len(warnings) == 1, "exactly ONE WARNING per (name, exc_type) per process"
    debugs = [r for r in caplog.records if r.levelno == logging.DEBUG
              and "best_effort[obsidian.write]" in r.getMessage()]
    assert len(debugs) == 100, "every swallow logs its traceback at DEBUG"
    assert all(r.exc_info for r in debugs), "DEBUG records carry the full traceback"
    assert degradationSummary()["obsidian.write"]["count"] == 100


def test_new_exc_type_warns_again_but_same_name_counts_together(caplog):
    lg = logging.getLogger("beffort-test-types")
    with caplog.at_level(logging.DEBUG, logger="beffort-test-types"):
        with best_effort("tunnel.start", log=lg):
            raise ValueError("a")
        with best_effort("tunnel.start", log=lg):
            raise TypeError("b")
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2, "a NEW exception type for the same name warns once more"
    assert degradationSummary()["tunnel.start"]["count"] == 2


def test_summary_shape_and_line_grouping():
    for _ in range(2):
        with best_effort("obsidian.write"):
            raise ValueError("x")
    with best_effort("obsidian.read"):
        raise OSError("y")
    with best_effort("tunnel.start"):
        raise RuntimeError("z")
    summ = degradationSummary()
    assert set(summ) == {"obsidian.write", "obsidian.read", "tunnel.start"}
    for entry in summ.values():
        assert set(entry) == {"count", "last_error", "last_at"}
        assert entry["count"] >= 1 and entry["last_error"] and entry["last_at"]
    assert "ValueError: x" in summ["obsidian.write"]["last_error"]
    line = degradationLine()
    assert line.startswith("degraded surfaces: ")
    assert "obsidian x3" in line and "tunnel x1" in line


def test_no_failure_means_clean_registry_and_empty_line():
    with best_effort("noop"):
        pass
    assert degradationSummary() == {}
    assert degradationLine() == ""


def test_never_propagates_exception_but_passes_base_exception():
    with best_effort("x.y"):
        raise Exception("swallowed")   # noqa: TRY002 -- exercising the broadest case
    assert degradationSummary()["x.y"]["count"] == 1
    with pytest.raises(SystemExit):
        with best_effort("x.y"):
            sys.exit(0)
    with pytest.raises(KeyboardInterrupt):
        with best_effort("x.y"):
            raise KeyboardInterrupt


def test_record_degradation_counts_without_context_manager():
    recordDegradation("ledger.subtasks", ValueError("disk full"))
    assert degradationSummary()["ledger.subtasks"]["count"] == 1


def test_reset_clears_registry_only_then_warned_set_too():
    with best_effort("a.b"):
        raise ValueError("x")
    resetDegradations()
    assert degradationSummary() == {}
    assert not DEGRADATIONS
    resetDegradations(warnings=True)   # exercised for coverage; fixture relies on it


def test_ledger_health_filters_ledger_names():
    from memory.experience_schema import ledger_health
    with best_effort("ledger.subtasks"):
        raise ValueError("locked")
    with best_effort("obsidian.write"):
        raise ValueError("down")
    health = ledger_health()
    assert set(health) == {"ledger.subtasks"}
    assert health["ledger.subtasks"]["count"] == 1


# -------------------------------------------------------------------- logging
def test_log_level_env_parsing(monkeypatch):
    from platform_core.app_config import settings as settings_mod
    monkeypatch.delenv("NINE_TO_FIVE_LOG_LEVEL", raising=False)
    assert settings_mod._logLevelFromEnv() == logging.INFO
    monkeypatch.setenv("NINE_TO_FIVE_LOG_LEVEL", "debug")
    assert settings_mod._logLevelFromEnv() == logging.DEBUG
    monkeypatch.setenv("NINE_TO_FIVE_LOG_LEVEL", "WARNING")
    assert settings_mod._logLevelFromEnv() == logging.WARNING
    monkeypatch.setenv("NINE_TO_FIVE_LOG_LEVEL", "25")
    assert settings_mod._logLevelFromEnv() == 25
    monkeypatch.setenv("NINE_TO_FIVE_LOG_LEVEL", "garbage")
    assert settings_mod._logLevelFromEnv() == logging.INFO


def test_env_override_and_rotating_handler_smoke(tmp_path, monkeypatch):
    from platform_core.app_config import settings as settings_mod
    base = logging.getLogger("9to5")
    old_handlers, old_level, old_prop = base.handlers[:], base.level, base.propagate
    real = settings_mod.settings()
    monkeypatch.setattr(settings_mod, "_LOGGER_CONFIGURED", False)
    monkeypatch.setattr(settings_mod, "settings",
                        lambda: replace(real, paths=replace(real.paths, LOG_PATH=tmp_path)))
    monkeypatch.setenv("NINE_TO_FIVE_LOG_LEVEL", "DEBUG")
    base.handlers = []
    try:
        settings_mod._configureLogging()
        assert base.level == logging.DEBUG, "NINE_TO_FIVE_LOG_LEVEL overrides the base level"
        rots = [h for h in base.handlers
                if isinstance(h, logging.handlers.RotatingFileHandler)]
        assert len(rots) == 1
        assert rots[0].maxBytes == 10 * 1024 * 1024
        assert rots[0].backupCount == 5
        # rotation smoke: shrink the threshold, emit enough to roll, expect a backup file
        rots[0].maxBytes = 256
        lg = settings_mod.getLogger("rotation-smoke")
        for _ in range(50):
            lg.info("x" * 64)
        assert (tmp_path / "9to5.log").exists()
        assert (tmp_path / "9to5.log.1").exists(), "RotatingFileHandler rolled over"
    finally:
        for h in base.handlers:
            with contextlib.suppress(Exception):
                h.close()
        base.handlers, base.level, base.propagate = old_handlers, old_level, old_prop


# -------------------------------------------------------------------- ratchet
def _dev_checks():
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    import dev_checks
    return dev_checks


def test_swallow_ratchet_count_within_baseline():
    dev_checks = _dev_checks()
    count = sum(dev_checks.count_swallow_sites().values())
    baseline = json.loads(
        dev_checks.SWALLOW_BASELINE_FILE.read_text(encoding="utf-8"))["count"]
    assert count <= baseline, (
        f"{count} bare 'except Exception: pass/continue' sites > baseline {baseline}: "
        "route new swallows through platform_core.core.best_effort.best_effort()")


def test_swallow_regex_matches_the_target_pattern():
    dev_checks = _dev_checks()
    src = (
        "try:\n    x()\nexcept Exception:\n    pass\n"
        "try:\n    y()\nexcept Exception as e:  # noqa: BLE001\n    continue\n"
        "try:\n    z()\nexcept Exception as e:\n    LOG.warning('handled %s', e)\n"
    )
    assert len(dev_checks._SWALLOW_RE.findall(src)) == 2, \
        "bare pass/continue bodies count; logged handlers do not"
