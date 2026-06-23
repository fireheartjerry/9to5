"""Unit tests for sim_error_handling — safeParseJson, safeWritePath, safeChatExtract."""
import tempfile
import unittest
from pathlib import Path

from sim_error_handling import safeChatExtract, safeParseJson, safeWritePath


class TestSafeParseJson(unittest.TestCase):
    def test_valid_dict(self):
        self.assertEqual(safeParseJson('{"k": 1}'), {"k": 1})

    def test_valid_list(self):
        self.assertEqual(safeParseJson('[1, 2]'), [1, 2])

    def test_malformed_returns_fallback(self):
        self.assertIsNone(safeParseJson("bad {json"))

    def test_none_input_returns_fallback(self):
        self.assertIsNone(safeParseJson(None))

    def test_bytes_input_parses(self):
        # json.loads accepts bytes in Python 3 — it is valid input, not an error
        self.assertEqual(safeParseJson(b'{"k":1}'), {"k": 1})

    def test_custom_fallback(self):
        self.assertIsNone(safeParseJson("!!!"))
        self.assertEqual(safeParseJson("!!!", fallback="DEFAULT"), "DEFAULT")

    def test_empty_string_returns_fallback(self):
        self.assertIsNone(safeParseJson(""))


class TestSafeWritePath(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_writes_file(self):
        p = self.tmp / "out.txt"
        result = safeWritePath(p, "hello")
        self.assertTrue(result["ok"])
        self.assertIsNone(result["error"])
        self.assertEqual(p.read_text(encoding="utf-8"), "hello")

    def test_creates_parent_dirs(self):
        p = self.tmp / "a" / "b" / "file.py"
        result = safeWritePath(p, "content")
        self.assertTrue(result["ok"])
        self.assertTrue(p.exists())

    def test_path_object_input(self):
        p = self.tmp / "path_obj.txt"
        result = safeWritePath(Path(p), "via Path")
        self.assertTrue(result["ok"])

    def test_string_path_input(self):
        p = self.tmp / "str_path.txt"
        result = safeWritePath(str(p), "via str")
        self.assertTrue(result["ok"])

    def test_empty_content(self):
        p = self.tmp / "empty.txt"
        result = safeWritePath(p, "")
        self.assertTrue(result["ok"])
        self.assertEqual(p.read_text(), "")

    def test_error_path_returns_ok_false(self):
        # Write to a non-existent root that cannot be created (file as parent)
        blocker = self.tmp / "blocker"
        blocker.write_text("I am a file")
        p = blocker / "child.txt"  # blocker is a file, not a dir
        result = safeWritePath(p, "data")
        self.assertFalse(result["ok"])
        self.assertIsInstance(result["error"], str)
        self.assertTrue(len(result["error"]) > 0)

    def test_result_contract_keys(self):
        p = self.tmp / "contract.txt"
        result = safeWritePath(p, "x")
        self.assertIn("ok", result)
        self.assertIn("error", result)


class TestSafeChatExtract(unittest.TestCase):
    def test_extracts_last_user_message(self):
        msgs = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "second"},
        ]
        self.assertEqual(safeChatExtract(msgs), "second")

    def test_none_messages_returns_empty(self):
        self.assertEqual(safeChatExtract(None), "")

    def test_empty_list_returns_empty(self):
        self.assertEqual(safeChatExtract([]), "")

    def test_no_matching_role_returns_empty(self):
        msgs = [{"role": "assistant", "content": "reply"}]
        self.assertEqual(safeChatExtract(msgs), "")

    def test_content_none_returns_empty(self):
        msgs = [{"role": "user", "content": None}]
        self.assertEqual(safeChatExtract(msgs), "")

    def test_non_dict_elements_ignored(self):
        msgs = ["string", None, {"role": "user", "content": "ok"}]
        self.assertEqual(safeChatExtract(msgs), "ok")

    def test_non_list_messages_returns_empty(self):
        self.assertEqual(safeChatExtract(42), "")  # type: ignore[arg-type]

    def test_assistant_role(self):
        msgs = [{"role": "assistant", "content": "assistant reply"}]
        self.assertEqual(safeChatExtract(msgs, role="assistant"), "assistant reply")

    def test_empty_role_returns_empty(self):
        msgs = [{"role": "user", "content": "hi"}]
        self.assertEqual(safeChatExtract(msgs, role=""), "")

    def test_missing_content_key_returns_empty(self):
        msgs = [{"role": "user"}]
        self.assertEqual(safeChatExtract(msgs), "")


if __name__ == "__main__":
    unittest.main()
