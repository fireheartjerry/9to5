"""BUG-016: _configureLogging()'s check-and-set on _LOGGER_CONFIGURED must be lock-protected --
otherwise two threads racing getLogger() at import time both pass the flag check and each add a
FileHandler/StreamHandler, doubling every log line for the rest of the process."""
import logging
import threading

import config


def test_concurrent_configure_logging_adds_handlers_once(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "_LOGGER_CONFIGURED", False)
    base = logging.getLogger("9to5")
    for h in list(base.handlers):
        base.removeHandler(h)
    monkeypatch.setenv("NINE_TO_FIVE_LOG_DIR", str(tmp_path))

    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()
        config._configureLogging()

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
