"""TaskState.save() must use a unique temp per writer so two processes/threads saving the same
task never collide on a shared '<id>.json.tmp' (the second os.replace would hit FileNotFoundError
after the first moved it). The final file must always be complete, valid JSON."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import config


class TestConcurrentSave(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self._p = mock.patch.object(config, "STATE_DIR", self.dir)
        self._p.start()

    def tearDown(self):
        self._p.stop()

    def test_many_threads_saving_same_task_never_clobber(self):
        from state.task import TaskState
        ts = TaskState.create("concurrent save goal", 1.0)
        errors: list[Exception] = []

        def worker() -> None:
            try:
                for _ in range(60):
                    ts.save()
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)

        self.assertEqual(errors, [], f"concurrent saves raised: {errors[:2]}")
        # final file is complete + valid, and no stray temp files linger
        self.assertIsInstance(json.loads(ts.path().read_text(encoding="utf-8")), dict)
        self.assertEqual(list(self.dir.glob("*.tmp")), [], "left a temp file behind")
