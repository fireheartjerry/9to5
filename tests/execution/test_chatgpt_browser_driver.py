import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agents.execution import chatgpt_browser_driver as driver


class TestChatGptBrowserDriver(unittest.TestCase):
    def test_verify_profile_is_gitignored_accepts_ignored_path(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            profile = repo / "state" / "chatgpt_profile_recon"
            profile.mkdir(parents=True)
            with mock.patch.object(driver, "_git_repo_root", return_value=repo):
                with mock.patch.object(
                    driver,
                    "_run",
                    return_value=subprocess_result(0, ".gitignore:52:state/chatgpt_profile_recon/"),
                ):
                    line = driver._verify_profile_is_gitignored(profile)
        self.assertIn("state/chatgpt_profile_recon", line)

    def test_new_spike_page_uses_fresh_page_not_existing_tab(self):
        existing_page = mock.Mock(name="existing_page")
        fresh_page = mock.Mock(name="fresh_page")
        context = mock.Mock()
        context.pages = [existing_page]
        context.new_page.return_value = fresh_page

        with mock.patch.object(driver, "_wait_for_initial_page_state", return_value=None):
            page = driver._new_spike_page(context, driver.DEFAULT_PROJECT_URL, 12.0)

        self.assertIs(page, fresh_page)
        context.new_page.assert_called_once_with()
        fresh_page.set_default_timeout.assert_called_once_with(12000)
        fresh_page.goto.assert_called_once_with(driver.DEFAULT_PROJECT_URL, wait_until="domcontentloaded")
        existing_page.goto.assert_not_called()

    def test_send_prompt_to_project_closes_only_spike_page(self):
        browser = mock.Mock()
        context = mock.Mock()
        page = mock.Mock()
        browser.contexts = [context]
        context.new_page.return_value = page
        playwright_api = mock.Mock()
        playwright_api.chromium.connect_over_cdp.return_value = browser
        playwright_cm = FakeStartable(playwright_api)

        with mock.patch.object(driver, "_verify_profile_dir", return_value=None):
            with mock.patch.object(driver, "_verify_profile_is_gitignored", return_value=".gitignore:52:x"):
                with mock.patch.object(driver, "_ensure_debuggable_chrome", return_value="reused"):
                    with mock.patch.dict(
                        "sys.modules",
                        {"playwright.sync_api": mock.Mock(sync_playwright=mock.Mock(return_value=playwright_cm))},
                    ):
                        with mock.patch.object(driver, "_wait_for_initial_page_state", return_value=None):
                            with mock.patch.object(driver, "_is_login_blocked", return_value=False):
                                with mock.patch.object(driver, "_blocking_modal_present", return_value=None):
                                    with mock.patch.object(driver, "_visible_composer", return_value=object()):
                                        with mock.patch.object(driver, "_assert_project_context", return_value=None):
                                            with mock.patch.object(driver, "_verify_or_select_model_reasoning", return_value=[]):
                                                with mock.patch.object(driver, "_send_prompt", return_value=None):
                                                    with mock.patch.object(driver, "_wait_for_response", return_value="ok"):
                                                        response = driver.send_prompt_to_project(
                                                            project_url=driver.DEFAULT_PROJECT_URL,
                                                            model=driver.DEFAULT_MODEL,
                                                            reasoning=driver.DEFAULT_REASONING,
                                                            prompt="custom prompt",
                                                        )

        self.assertEqual(response, "ok")
        page.close.assert_called_once_with()
        browser.close.assert_not_called()
        playwright_api.stop.assert_called_once_with()

    def test_session_reuses_same_page_across_turns(self):
        browser = mock.Mock()
        context = mock.Mock()
        page = mock.Mock()
        page.url = driver.DEFAULT_PROJECT_URL.replace("/project", "/c/chat-1")
        browser.contexts = [context]
        context.new_page.return_value = page
        playwright_api = mock.Mock()
        playwright_api.chromium.connect_over_cdp.return_value = browser
        playwright_cm = FakeStartable(playwright_api)
        responses = ["first", "second"]

        with mock.patch.object(driver, "_verify_profile_dir", return_value=None):
            with mock.patch.object(driver, "_verify_profile_is_gitignored", return_value=".gitignore:52:x"):
                with mock.patch.object(driver, "_ensure_debuggable_chrome", return_value="reused"):
                    with mock.patch.dict(
                        "sys.modules",
                        {"playwright.sync_api": mock.Mock(sync_playwright=mock.Mock(return_value=playwright_cm))},
                    ):
                        with mock.patch.object(driver, "_wait_for_initial_page_state", return_value=None):
                            with mock.patch.object(driver, "_is_login_blocked", return_value=False):
                                with mock.patch.object(driver, "_blocking_modal_present", return_value=None):
                                    with mock.patch.object(driver, "_visible_composer", return_value=object()):
                                        with mock.patch.object(driver, "_assert_project_context", return_value=None) as assert_home:
                                            with mock.patch.object(driver, "_verify_or_select_model_reasoning", return_value=[]):
                                                with mock.patch.object(driver, "_send_prompt", return_value=None) as send:
                                                    with mock.patch.object(
                                                        driver,
                                                        "_wait_for_response",
                                                        side_effect=responses,
                                                    ):
                                                        session = driver.ChatGptBrowserSession(
                                                            project_url=driver.DEFAULT_PROJECT_URL,
                                                            model=driver.DEFAULT_MODEL,
                                                            reasoning=driver.DEFAULT_REASONING,
                                                        )
                                                        first = session.ask("turn one")
                                                        second = session.ask("turn two")
                                                        session.close()

        self.assertEqual((first, second), ("first", "second"))
        self.assertEqual(session.turn_count, 2)
        self.assertEqual(send.call_count, 2)
        context.new_page.assert_called_once_with()
        assert_home.assert_called_once()
        page.close.assert_called_once_with()
        browser.close.assert_not_called()


def subprocess_result(returncode: int, stdout: str) -> mock.Mock:
    proc = mock.Mock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = ""
    return proc


class FakeContextManager:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self.value

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeStartable:
    """Playwright-style handle: ``sync_playwright().start()`` / ``.stop()``."""

    def __init__(self, value):
        self.value = value

    def start(self):
        return self.value
