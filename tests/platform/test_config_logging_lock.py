"""BUG-016: _configureLogging()'s check-and-set on _LOGGER_CONFIGURED must be lock-protected --
otherwise two threads racing getLogger() at import time both pass the flag check and each add a
FileHandler/StreamHandler, doubling every log line for the rest of the process.

_LOGGER_CONFIGURED/_configureLogging live in platform_core.app_config.settings (config.py is a
thin facade re-exporting getLogger only) -- monkeypatch the real owner, not a copy that a facade
import would rebind locally without the actual guard ever seeing the patched value."""
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from platform_core.app_config import settings

REPO_ROOT = Path(__file__).resolve().parents[2]


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


def test_ambient_file_handler_cannot_emit_after_runtime_poison(tmp_path):
    log_dir = tmp_path / "legacy-logs"
    code = f"""
import logging
import os
from pathlib import Path
os.environ['NINE_TO_FIVE_LOG_DIR'] = {str(log_dir)!r}
import platform_core.app_config.settings as settings
from platform_core.runtime import controller_state

base = logging.getLogger('9to5')
for handler in list(base.handlers):
    base.removeHandler(handler)
settings._LOGGER_CONFIGURED = False
logger = settings.getLogger('probe')
assert settings._SETTINGS is None
target = Path({str(log_dir / '9to5.log')!r})
assert not target.exists()
controller_state._RUNTIME_INSTALL_TERMINAL = (
    controller_state._PoisonedControllerRuntimeStateInstallation(
        bootstrap_id='a' * 64,
        reason='test-poison',
    )
)
logger.error('must not cross runtime poison')
assert not target.exists()
print('poisoned-log-handler-refused')
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "poisoned-log-handler-refused"


def test_log_formatting_cannot_reentrantly_poison_then_write(tmp_path):
    log_dir = tmp_path / "legacy-logs"
    code = f"""
import logging
import os
from pathlib import Path
os.environ['NINE_TO_FIVE_LOG_DIR'] = {str(log_dir)!r}
import platform_core.app_config.settings as settings
from platform_core.runtime import controller_state

base = logging.getLogger('9to5')
for handler in list(base.handlers):
    base.removeHandler(handler)
settings._LOGGER_CONFIGURED = False
logger = settings.getLogger('probe')
target = Path({str(log_dir / '9to5.log')!r})

class PoisonOnStr:
    def __str__(self):
        controller_state._RUNTIME_INSTALL_TERMINAL = (
            controller_state._PoisonedControllerRuntimeStateInstallation(
                bootstrap_id='a' * 64,
                reason='reentrant-poison',
            )
        )
        return 'poisoned-message'

logger.error(PoisonOnStr())
assert not target.exists()
print('reentrant-log-poison-refused')
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "reentrant-log-poison-refused"
