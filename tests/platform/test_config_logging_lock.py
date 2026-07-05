"""BUG-016: _configureLogging()'s check-and-set on _LOGGER_CONFIGURED must be lock-protected --
otherwise two threads racing getLogger() at import time both pass the flag check and each add a
FileHandler/StreamHandler, doubling every log line for the rest of the process.

_LOGGER_CONFIGURED/_configureLogging live in platform_core.app_config.settings (config.py is a
thin facade re-exporting getLogger only) -- monkeypatch the real owner, not a copy that a facade
import would rebind locally without the actual guard ever seeing the patched value."""
import logging
import threading
from pathlib import Path

import pytest

from platform_core.app_config import settings


@pytest.fixture
def _restore_logging():
    """Snapshot/restore the shared ``9to5`` logger handlers + configured flag so a test that
    re-points the FileHandler at a per-test tmp dir can't leave a dangling handler behind."""
    base = logging.getLogger("9to5")
    saved_handlers = list(base.handlers)
    saved_flag = settings._LOGGER_CONFIGURED
    yield
    for h in list(base.handlers):
        base.removeHandler(h)
    for h in saved_handlers:
        base.addHandler(h)
    settings._LOGGER_CONFIGURED = saved_flag


def test_concurrent_configure_logging_adds_handlers_once(monkeypatch, tmp_path, _restore_logging):
    monkeypatch.setattr(settings, "_LOGGER_CONFIGURED", False)
    base = logging.getLogger("9to5")
    for h in list(base.handlers):
        base.removeHandler(h)
    monkeypatch.setenv("NINE_TO_FIVE_LOG_DIR", str(tmp_path))

    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()
        settings._configureLogging()

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    file_handlers = [h for h in base.handlers if isinstance(h, logging.FileHandler)]
    stream_handlers = [h for h in base.handlers
                       if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)]
    assert len(file_handlers) == 1, f"expected exactly 1 FileHandler, got {len(file_handlers)}"
    assert len(stream_handlers) == 1, f"expected exactly 1 StreamHandler, got {len(stream_handlers)}"


def test_log_dir_override_redirects_file_handler(monkeypatch, tmp_path, _restore_logging):
    """NINE_TO_FIVE_LOG_DIR must actually redirect the 9to5.log FileHandler. conftest.py relies on
    this to keep the whole test session out of the real logs/9to5.log; the override was silently
    dead (production read LOG_PATH, not NINE_TO_FIVE_LOG_DIR) so tests polluted prod."""
    base = logging.getLogger("9to5")
    for h in list(base.handlers):
        base.removeHandler(h)
    monkeypatch.setattr(settings, "_LOGGER_CONFIGURED", False)
    monkeypatch.setenv("NINE_TO_FIVE_LOG_DIR", str(tmp_path))

    settings._configureLogging()

    file_handlers = [h for h in base.handlers if isinstance(h, logging.FileHandler)]
    assert len(file_handlers) == 1
    assert Path(file_handlers[0].baseFilename).parent == tmp_path, (
        f"FileHandler wrote to {file_handlers[0].baseFilename}, not override dir {tmp_path}")
