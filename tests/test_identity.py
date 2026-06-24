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


if __name__ == "__main__":
    unittest.main()
