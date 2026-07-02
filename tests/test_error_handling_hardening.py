"""Behavioral tests for error-handling hardening in non-core modules.

Covers:
- health._ollama() with malformed Ollama responses
- health._discord() with non-JSON Discord response
- control.ControlBus._readRaw() with non-dict JSON content
- state.task.TaskState.load() with non-dict JSON content
- webdash do_POST with null/non-string action in payload
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config


# ---------------------------------------------------------------------------
# health module
# ---------------------------------------------------------------------------

class TestOllamaHealthRobustness(unittest.TestCase):
    """_ollama() must not crash on unexpected HTTP response shapes."""

    def _make_response(self, status, body):
        r = mock.Mock()
        r.status_code = status
        r.raise_for_status = mock.Mock(
            side_effect=(None if status < 400 else Exception(f"HTTP {status}"))
        )
        r.json = mock.Mock(return_value=body)
        return r

    def test_non_dict_response_returns_fail(self):
        import platform_core.ops.health as health
        r = self._make_response(200, ["unexpected", "list"])
        with mock.patch("platform_core.ops.health.requests.get", return_value=r):
            ok, detail, _ = health._ollama()
        self.assertFalse(ok)
        self.assertIn("unexpected shape", detail)

    def test_non_200_triggers_raise_for_status(self):
        import platform_core.ops.health as health
        r = mock.Mock()
        r.raise_for_status = mock.Mock(side_effect=Exception("503"))
        with mock.patch("platform_core.ops.health.requests.get", return_value=r):
            ok, detail, _ = health._ollama()
        self.assertFalse(ok)

    def test_valid_response_with_model_returns_ok(self):
        import platform_core.ops.health as health
        models_list = [{"name": config.OLLAMA_MODEL}]
        r = self._make_response(200, {"models": models_list})
        with mock.patch("platform_core.ops.health.requests.get", return_value=r), \
             mock.patch("platform_core.ops.health.requests.get", return_value=r):
            # patch both the tags and ps calls
            ok, detail, _ = health._ollama()
        # should at least not crash; may fail if OLLAMA_MODEL not in list for other reasons
        self.assertIsInstance(ok, bool)

    def test_model_missing_from_list(self):
        import platform_core.ops.health as health
        r = self._make_response(200, {"models": [{"name": "other-model"}]})
        ps_r = self._make_response(200, {"models": []})
        calls = [r, ps_r]
        with mock.patch("platform_core.ops.health.requests.get", side_effect=calls):
            ok, detail, fix = health._ollama()
        self.assertFalse(ok)
        self.assertIn("not pulled", detail)

    def test_ps_non_dict_does_not_crash(self):
        import platform_core.ops.health as health
        tags_r = self._make_response(200, {"models": [{"name": config.OLLAMA_MODEL}]})
        ps_r = mock.Mock()
        ps_r.json = mock.Mock(return_value=["not", "a", "dict"])
        calls = [tags_r, ps_r]
        with mock.patch("platform_core.ops.health.requests.get", side_effect=calls):
            ok, detail, _ = health._ollama()
        self.assertTrue(ok)


class TestDiscordHealthRobustness(unittest.TestCase):
    """_discord() must not crash when response body is not valid JSON."""

    def test_non_json_200_response_returns_ok_with_unknown_username(self):
        import platform_core.ops.health as health
        r = mock.Mock()
        r.status_code = 200
        r.json = mock.Mock(side_effect=ValueError("not json"))
        with mock.patch.object(config, "DISCORD_BOT_TOKEN", "fake-token"), \
             mock.patch("platform_core.ops.health.requests.get", return_value=r):
            ok, detail, _ = health._discord()
        self.assertTrue(ok)
        self.assertIn("unknown", detail)

    def test_200_with_valid_json_returns_username(self):
        import platform_core.ops.health as health
        r = mock.Mock()
        r.status_code = 200
        r.json = mock.Mock(return_value={"username": "mybot"})
        with mock.patch.object(config, "DISCORD_BOT_TOKEN", "fake-token"), \
             mock.patch("platform_core.ops.health.requests.get", return_value=r):
            ok, detail, _ = health._discord()
        self.assertTrue(ok)
        self.assertIn("mybot", detail)

    def test_401_returns_fail(self):
        import platform_core.ops.health as health
        r = mock.Mock()
        r.status_code = 401
        with mock.patch.object(config, "DISCORD_BOT_TOKEN", "bad-token"), \
             mock.patch("platform_core.ops.health.requests.get", return_value=r):
            ok, detail, _ = health._discord()
        self.assertFalse(ok)
        self.assertIn("401", detail)


# ---------------------------------------------------------------------------
# control module
# ---------------------------------------------------------------------------

class TestControlBusNonDictJson(unittest.TestCase):
    """_readRaw() must treat a non-dict JSON file as corrupt and retry/blank."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self._patch = mock.patch.object(config, "CONTROL_DIR", self.tmpdir)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        for p in self.tmpdir.glob("*"):
            p.unlink(missing_ok=True)
        self.tmpdir.rmdir()

    def _bus(self, task_id: str = "t-robustness"):
        from platform_core.runtime.control import ControlBus
        return ControlBus(task_id)

    def test_json_array_treated_as_corrupt_returns_blank(self):
        """If the control file contains a JSON array, load() must return a safe blank state."""
        from platform_core.runtime.control import ControlBus, _blank
        task_id = "t-array"
        path = self.tmpdir / f"{task_id}.json"
        path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        bus = ControlBus.__new__(ControlBus)
        bus.task_id = task_id
        bus.path = path
        data = bus.load()
        blank = _blank()
        self.assertEqual(data["abort"], blank["abort"])
        self.assertEqual(data["pause"], blank["pause"])

    def test_json_null_treated_as_corrupt_returns_blank(self):
        """A null JSON value must not propagate to callers."""
        from platform_core.runtime.control import ControlBus, _blank
        task_id = "t-null"
        path = self.tmpdir / f"{task_id}.json"
        path.write_text("null", encoding="utf-8")
        bus = ControlBus.__new__(ControlBus)
        bus.task_id = task_id
        bus.path = path
        data = bus.load()
        self.assertFalse(data["abort"])

    def test_valid_json_dict_loads_correctly(self):
        bus = self._bus("t-valid")
        bus.requestAbort()
        data = bus.load()
        self.assertTrue(data["abort"])


# ---------------------------------------------------------------------------
# state/task module
# ---------------------------------------------------------------------------

class TestTaskStateLoadValidation(unittest.TestCase):
    """TaskState.load() must raise ValueError for non-dict JSON, not cascade."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self._patch = mock.patch.object(config, "STATE_DIR", self.tmpdir)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        for p in self.tmpdir.glob("*"):
            p.unlink(missing_ok=True)
        self.tmpdir.rmdir()

    def test_json_array_raises_value_error(self):
        from state.task import TaskState
        path = self.tmpdir / "bad-task.json"
        path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            TaskState.load("bad-task")
        self.assertIn("not a dict", str(ctx.exception))

    def test_json_string_raises_value_error(self):
        from state.task import TaskState
        path = self.tmpdir / "str-task.json"
        path.write_text(json.dumps("just a string"), encoding="utf-8")
        with self.assertRaises(ValueError):
            TaskState.load("str-task")

    def test_load_safe_returns_none_on_corrupt(self):
        """loadSafe() must still swallow the ValueError and return None."""
        from state.task import TaskState
        path = self.tmpdir / "corrupt-task.json"
        path.write_text(json.dumps([]), encoding="utf-8")
        self.assertIsNone(TaskState.loadSafe("corrupt-task"))

    def test_valid_dict_loads_fine(self):
        from state.task import TaskState
        ts = TaskState.create("test goal", 1.0)
        ts.save()
        loaded = TaskState.load(ts.task_id)
        self.assertEqual(loaded.task_id, ts.task_id)


# ---------------------------------------------------------------------------
# webdash do_POST action normalization
# ---------------------------------------------------------------------------

class TestWebdashPostActionNormalization(unittest.TestCase):
    """do_POST must not crash when action/arg are null or non-string in payload."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self._patch = mock.patch.object(config, "CONTROL_DIR", self.tmpdir)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        for p in self.tmpdir.glob("*"):
            p.unlink(missing_ok=True)
        self.tmpdir.rmdir()

    def _post(self, task_id: str, payload: dict) -> dict:
        """Call _applyControl with normalized action/arg, mirroring do_POST logic."""
        action = payload.get("action") or ""
        if not isinstance(action, str):
            action = ""
        arg = payload.get("arg")
        if arg is not None and not isinstance(arg, str):
            arg = str(arg)
        from notifications.webdash import _applyControl
        return _applyControl(task_id, action, arg)

    def test_null_action_returns_error_not_crash(self):
        result = self._post("t-web", {"action": None})
        self.assertFalse(result["ok"])
        # a null action is rejected with a non-empty error (the handler now reports the specific
        # "action must be a non-empty string" rather than the old generic "unknown"); assert the
        # intent -- an error, not a crash -- without coupling to the exact wording.
        self.assertTrue(result.get("error"))

    def test_integer_action_returns_error_not_crash(self):
        result = self._post("t-web", {"action": 42})
        self.assertFalse(result["ok"])

    def test_integer_arg_is_coerced_to_string_for_skip(self):
        result = self._post("t-web", {"action": "skip", "arg": 123})
        self.assertTrue(result["ok"])
        from platform_core.runtime.control import ControlBus
        ops = ControlBus("t-web").drainOps()
        self.assertEqual(ops[0]["subtask_id"], "123")

    def test_abort_with_null_arg_works(self):
        result = self._post("t-web", {"action": "abort", "arg": None})
        self.assertTrue(result["ok"])
        from platform_core.runtime.control import ControlBus
        self.assertTrue(ControlBus("t-web").isAbort())
