"""Verify the Phase 3 native layer architecture sketch (docs/phase_3_architecture.md).

Tests cover:
  * Architecture doc -- presence + required section headings.
  * native_executor module -- public interface matches the spec.
  * NativeExecutor behaviour -- result contract, degradation, error handling.
  * Dispatch routing -- selectForSurface routes correctly with / without the flag.
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

# ── locate repo root (tests/ lives one level below C:\9to5) ──────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import config
from agents import native_executor
from agents import architect


# ─────────────────────────────────────────────────────────────────────────────
# Architecture document validation
# ─────────────────────────────────────────────────────────────────────────────

class TestArchDocExists(unittest.TestCase):
    DOC_PATH = REPO_ROOT / "docs" / "phase_3_architecture.md"

    def setUp(self):
        self.text = self.DOC_PATH.read_text(encoding="utf-8")

    def test_doc_file_exists(self):
        self.assertTrue(self.DOC_PATH.exists(), "phase_3_architecture.md must exist")

    def test_required_headings_present(self):
        for heading in ("Key Components", "Interactions", "Degradation Contract",
                        "Testing Strategy", "Implementation Order"):
            self.assertIn(heading, self.text, f"Missing section: {heading!r}")

    def test_required_symbols_documented(self):
        for sym in ("NativeUnavailable", "_run_native_actions", "runNative", "nativeActions"):
            self.assertIn(sym, self.text, f"Symbol {sym!r} must be documented")

    def test_action_primitives_documented(self):
        for action in ("launch", "connect", "find", "click", "type", "press",
                       "extract", "screenshot", "close"):
            self.assertIn(f'"action": "{action}"', self.text,
                          f"Action primitive {action!r} must appear in doc")

    def test_config_additions_mentioned(self):
        for name in ("NATIVE_LAYER_ENABLED", "NATIVE_SCREENSHOT_DIR", "NATIVE_ACTION_TIMEOUT_MS"):
            self.assertIn(name, self.text, f"Config constant {name!r} must be documented")

    def test_surface_routing_documented(self):
        self.assertIn('surface="native"', self.text)
        self.assertIn("native_executor.runNative", self.text)


# ─────────────────────────────────────────────────────────────────────────────
# native_executor module interface
# ─────────────────────────────────────────────────────────────────────────────

class TestNativeExecutorInterface(unittest.TestCase):
    def test_module_exports_required_symbols(self):
        self.assertTrue(hasattr(native_executor, "NativeUnavailable"))
        self.assertTrue(hasattr(native_executor, "_run_native_actions"))
        self.assertTrue(hasattr(native_executor, "runNative"))
        self.assertTrue(hasattr(native_executor, "nativeActions"))
        self.assertTrue(hasattr(native_executor, "selectForSurface"))

    def test_NativeUnavailable_is_exception(self):
        self.assertTrue(issubclass(native_executor.NativeUnavailable, Exception))

    def test_runNative_is_callable(self):
        self.assertTrue(callable(native_executor.runNative))

    def test_nativeActions_is_callable(self):
        self.assertTrue(callable(native_executor.nativeActions))

    def test_module_level_timeout_constant(self):
        self.assertIsInstance(native_executor.NATIVE_ACTION_TIMEOUT_MS, int)
        self.assertGreater(native_executor.NATIVE_ACTION_TIMEOUT_MS, 0)

    def test_config_has_native_layer_flag(self):
        self.assertIsInstance(config.NATIVE_LAYER_ENABLED, bool)


# ─────────────────────────────────────────────────────────────────────────────
# native_executor behaviour (all mock _run_native_actions -- no real pywinauto)
# ─────────────────────────────────────────────────────────────────────────────

class TestNativeExecutor(unittest.TestCase):
    def tearDown(self):
        mock.patch.stopall()

    def test_result_matches_runclaude_contract(self):
        with mock.patch.object(native_executor, "_run_native_actions",
                               return_value="launch 'notepad.exe'\nextract:\nhello world"):
            res = native_executor.runNative(
                {"surface": "native", "native_actions": [{"action": "launch", "app": "notepad.exe"},
                                                          {"action": "extract"}]})
        for key in ("ok", "returncode", "stdout", "stderr", "is_error", "spec", "profile"):
            self.assertIn(key, res, f"Result must contain key {key!r}")
        self.assertTrue(res["ok"])
        self.assertFalse(res["is_error"])
        self.assertIn("notepad", res["stdout"])

    def test_result_surface_is_native(self):
        with mock.patch.object(native_executor, "_run_native_actions", return_value="ok"):
            res = native_executor.runNative(
                {"surface": "native", "native_actions": [{"action": "launch", "app": "calc.exe"}]})
        self.assertEqual(res.get("surface"), "native")

    def test_unavailable_backend_degrades(self):
        def raise_unavail(actions, **kw):
            raise native_executor.NativeUnavailable("pywinauto not installed")

        with mock.patch.object(native_executor, "_run_native_actions", side_effect=raise_unavail):
            res = native_executor.runNative(
                {"native_actions": [{"action": "launch", "app": "notepad.exe"}]})
        self.assertFalse(res["ok"])
        self.assertTrue(res["is_error"])
        self.assertIn("pywinauto", res["stderr"])

    def test_generic_exception_returns_error_result(self):
        def raise_generic(actions, **kw):
            raise TimeoutError("UIA timeout after 10000ms")

        with mock.patch.object(native_executor, "_run_native_actions", side_effect=raise_generic):
            res = native_executor.runNative(
                {"native_actions": [{"action": "click", "title": "OK"}]})
        self.assertFalse(res["ok"])
        self.assertTrue(res["is_error"])
        self.assertIn("native run failed", res["stderr"])

    def test_no_actions_is_clean_error(self):
        res = native_executor.runNative({"surface": "native", "native_actions": []})
        self.assertFalse(res["ok"])
        self.assertTrue(res["is_error"])
        self.assertIn("native_actions", res["stderr"])

    def test_no_actions_prompt_no_url_is_clean_error(self):
        res = native_executor.runNative({"surface": "native", "prompt": "do something"})
        self.assertFalse(res["ok"])
        self.assertTrue(res["is_error"])


# ─────────────────────────────────────────────────────────────────────────────
# nativeActions helper
# ─────────────────────────────────────────────────────────────────────────────

class TestNativeActionsHelper(unittest.TestCase):
    def test_prepends_launch_appends_close(self):
        steps = [{"action": "type", "text": "hello"}]
        actions = native_executor.nativeActions("notepad.exe", steps)
        self.assertEqual(actions[0]["action"], "launch")
        self.assertEqual(actions[0]["app"], "notepad.exe")
        self.assertEqual(actions[-1]["action"], "close")
        self.assertEqual(actions[-1]["app"], "notepad.exe")

    def test_middle_steps_preserved(self):
        steps = [{"action": "find", "title": "Untitled"},
                 {"action": "type", "text": "hello"},
                 {"action": "extract"}]
        actions = native_executor.nativeActions("notepad.exe", steps)
        middle = actions[1:-1]
        self.assertEqual(middle, steps)

    def test_empty_steps_still_wraps(self):
        actions = native_executor.nativeActions("calc.exe", [])
        self.assertEqual(len(actions), 2)
        self.assertEqual(actions[0]["action"], "launch")
        self.assertEqual(actions[1]["action"], "close")


# ─────────────────────────────────────────────────────────────────────────────
# Dispatch routing via selectForSurface
# ─────────────────────────────────────────────────────────────────────────────

_SENTINEL_FN = lambda *a, **k: {"ok": True}  # noqa: E731 -- module-level for identity tests


class TestNativeDispatch(unittest.TestCase):
    def tearDown(self):
        mock.patch.stopall()

    def test_dispatcher_routes_native_when_enabled(self):
        with mock.patch.object(config, "NATIVE_LAYER_ENABLED", True):
            hands = native_executor.selectForSurface(_SENTINEL_FN, {"surface": "native"})
        self.assertIs(hands, native_executor.runNative)

    def test_dispatcher_falls_back_when_disabled(self):
        with mock.patch.object(config, "NATIVE_LAYER_ENABLED", False):
            hands = native_executor.selectForSurface(_SENTINEL_FN, {"surface": "native"})
        self.assertIs(hands, _SENTINEL_FN)

    def test_dispatcher_falls_back_for_terminal_surface(self):
        with mock.patch.object(config, "NATIVE_LAYER_ENABLED", True):
            hands = native_executor.selectForSurface(_SENTINEL_FN, {"surface": "terminal"})
        self.assertIs(hands, _SENTINEL_FN)

    def test_dispatcher_falls_back_for_browser_surface(self):
        with mock.patch.object(config, "NATIVE_LAYER_ENABLED", True):
            hands = native_executor.selectForSurface(_SENTINEL_FN, {"surface": "browser"})
        self.assertIs(hands, _SENTINEL_FN)

    def test_dispatcher_falls_back_when_no_surface_key(self):
        with mock.patch.object(config, "NATIVE_LAYER_ENABLED", True):
            hands = native_executor.selectForSurface(_SENTINEL_FN, {})
        self.assertIs(hands, _SENTINEL_FN)


def test_author_architect_prompt_injects_discovery_report():
    """When discovery_report is passed, its content appears in the authored prompt."""
    from agents.discovery.models import Finding, DiscoveryReport
    f = Finding("Rewrite orchestrator", "reimagining", 5, 4, 5,
                "Current approach is tightly coupled", ["orchestrator.py"], "lens_3")
    f.rank = 1
    report = DiscoveryReport(theme_suggestion="transform the orchestrator layer", findings=[f])

    with mock.patch.object(architect, "_getOllama") as mock_oll:
        mock_oll.return_value.chat.return_value = {"message": {"content": "design the architecture"}}
        prompt = architect.authorArchitectPrompt("spec text", discovery_report=report)
    # Either the theme or the finding title should appear in the final prompt
    assert "transform the orchestrator layer" in prompt or "Rewrite orchestrator" in prompt
