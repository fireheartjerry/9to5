import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agents.execution import chatgpt_browser_driver as driver
from tools import chatgpt_browser_spike as spike


class TestChatGptBrowserSpike(unittest.TestCase):
    def test_parse_args_defaults(self):
        args = spike.parse_args([])
        self.assertEqual(args.profile, str(driver.DEFAULT_PROFILE))
        self.assertEqual(args.project_url, driver.DEFAULT_PROJECT_URL)
        self.assertEqual(args.model, driver.DEFAULT_MODEL)
        self.assertEqual(args.reasoning, driver.DEFAULT_REASONING)
        self.assertEqual(args.debug_port, driver.DEFAULT_PORT)

    def test_run_spike_calls_driver_and_prints_success(self):
        args = spike.parse_args([])
        with mock.patch.object(driver, "_verify_profile_is_gitignored", return_value=".gitignore:52:x"):
            with mock.patch.object(driver, "_ensure_debuggable_chrome", return_value="reused"):
                with mock.patch.object(
                    driver,
                    "send_prompt_to_project",
                    return_value="browser profile test complete",
                ) as send_prompt:
                    with mock.patch.object(spike, "_print") as printer:
                        rc = spike.run_spike(args)
        self.assertEqual(rc, 0)
        send_prompt.assert_called_once_with(
            project_url=driver.DEFAULT_PROJECT_URL,
            model=driver.DEFAULT_MODEL,
            reasoning=driver.DEFAULT_REASONING,
            prompt=driver.DEFAULT_PROMPT,
        )
        printed = " ".join(call.args[0] for call in printer.call_args_list if call.args)
        self.assertIn("[assistant]", printed)
        self.assertIn("browser profile test complete", printed)

    def test_run_spike_rejects_non_default_sensitive_overrides(self):
        args = spike.parse_args(["--debug-port", "9333"])
        with self.assertRaises(driver.ChatGptBrowserError):
            spike.run_spike(args)
