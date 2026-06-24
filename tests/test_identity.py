# tests/test_identity.py
"""The SELF manifest: canonicalization + role classification."""
import os, tempfile, unittest
from pathlib import Path

import identity


class TestCanonical(unittest.TestCase):
    def test_collapses_dotdot_and_normalizes_case(self):
        raw = r"C:\9to5\agents\..\config.py"
        self.assertEqual(identity._canonical(raw), identity._canonical(r"C:\9to5\config.py"))

    def test_absolute_and_relative_to_root_match(self):
        # A bare 'config.py' resolved against the project root equals the absolute form.
        os.chdir(identity.PROJECT_ROOT)
        self.assertEqual(identity._canonical("config.py"),
                         identity._canonical(str(identity.PROJECT_ROOT / "config.py")))


class TestRoleOf(unittest.TestCase):
    def test_loop_module_is_self_code(self):
        self.assertis = identity.roleOf(str(identity.PROJECT_ROOT / "orchestrator.py"))
        self.assertEqual(self.assertis, identity.Role.SELF_CODE)

    def test_project_claude_md_is_object_meta_not_instructions(self):
        # The decisive distinction: 9to5 EDITS this file but must never OBEY it.
        r = identity.roleOf(str(identity.PROJECT_ROOT / "CLAUDE.md"))
        self.assertEqual(r, identity.Role.SELF_OBJECT_META)

    def test_experience_db_is_learned(self):
        r = identity.roleOf(str(identity.PROJECT_ROOT / "state" / "experience.db"))
        self.assertEqual(r, identity.Role.SELF_LEARNED)

    def test_env_is_hard_boundary(self):
        self.assertEqual(identity.roleOf(str(identity.PROJECT_ROOT / ".env")),
                         identity.Role.HARD_BOUNDARY)

    def test_symlink_into_config_classifies_as_target_role(self):
        # Evasion: a link whose basename is innocuous still classifies by its real target.
        import os, tempfile
        link = identity.PROJECT_ROOT / "_tmp_link_identity.py"
        try:
            os.symlink(identity.PROJECT_ROOT / "config.py", link)
        except (OSError, NotImplementedError):
            self.skipTest("symlink not permitted on this host")
        try:
            self.assertEqual(identity.roleOf(str(link)), identity.Role.SELF_CODE)
        finally:
            link.unlink()

    def test_outside_tree_is_other_content(self):
        import tempfile
        self.assertEqual(identity.roleOf(tempfile.gettempdir()), identity.Role.OTHER_CONTENT)


class TestPredicates(unittest.TestCase):
    def test_object_meta_is_editable_but_not_obeyable(self):
        p = str(identity.PROJECT_ROOT / "CLAUDE.md")
        self.assertTrue(identity.isEditable(p))
        self.assertFalse(identity.isObeyable(p))

    def test_env_is_not_editable(self):
        self.assertFalse(identity.isEditable(str(identity.PROJECT_ROOT / ".env")))

    def test_user_global_claude_md_is_obeyable(self):
        self.assertTrue(identity.isObeyable(str(identity._USER_GLOBAL_CLAUDE_MD)))

    def test_self_code_files_lists_loop_modules(self):
        files = identity.selfCodeFiles()
        names = {Path(f).name for f in files}
        self.assertIn("orchestrator.py", names)
        self.assertIn("identity.py", names)
        self.assertNotIn("CLAUDE.md", names)  # object_meta, not code


if __name__ == "__main__":
    unittest.main()
