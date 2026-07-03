# tests/test_identity.py
"""The SELF manifest: canonicalization + role classification.

Merged (consolidation pass, tests/control sprawl reduction):
  - test_identity_perf.py -- guards for the selfCodeFiles repo-walk optimization
"""
import os
import tempfile
import unittest
from pathlib import Path

import platform_core.core.identity as identity


class TestCanonical(unittest.TestCase):
    def test_collapses_dotdot_and_normalizes_case(self):
        # Use the real project root so the `..` collapse is exercised cross-platform (the old
        # hardcoded `C:\9to5\...` literal only collapsed on Windows -> failed on Linux CI).
        base = identity.PROJECT_ROOT
        raw = str(base / "agents" / ".." / "config.py")
        self.assertEqual(identity._canonical(raw), identity._canonical(str(base / "config.py")))

    def test_absolute_and_relative_to_root_match(self):
        # A bare 'config.py' resolved against the project root equals the absolute form.
        # Restore cwd afterwards: a leaked chdir mutates this xdist worker's cwd for
        # every later test in the same process.
        prev_cwd = os.getcwd()
        os.chdir(identity.PROJECT_ROOT)
        try:
            self.assertEqual(identity._canonical("config.py"),
                             identity._canonical(str(identity.PROJECT_ROOT / "config.py")))
        finally:
            os.chdir(prev_cwd)


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
        # The link lives in a temp dir, NOT the live repo root: roleOf canonicalizes via
        # os.path.realpath before any containment check, so the link's location is
        # irrelevant to the property under test -- while an in-repo root-level *.py would
        # be visible to repo-scanning tests on other xdist workers (and could leak on a
        # crash). Out-of-tree is also the stronger assertion: without realpath the link
        # would classify OTHER_CONTENT instead of the target's SELF_CODE.
        with tempfile.TemporaryDirectory() as td:
            link = Path(td) / "_tmp_link_identity.py"
            try:
                os.symlink(identity.PROJECT_ROOT / "config.py", link)
            except (OSError, NotImplementedError):
                self.skipTest("symlink not permitted on this host")
            self.assertEqual(identity.roleOf(str(link)), identity.Role.SELF_CODE)

    def test_outside_tree_is_other_content(self):
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

    def test_self_code_files_excludes_test_dirs(self):
        files = identity.selfCodeFiles()
        # Test/harness files are SELF_CODE by role but must NOT be in the fingerprint set:
        # the running orchestrator never imports them, so editing a test must not look like
        # the running self diverging.
        self.assertFalse(any((os.sep + "tests" + os.sep) in f for f in files),
                         "tests/ files must be excluded from the fingerprint set")
        self.assertFalse(any((os.sep + "testing" + os.sep) in f for f in files),
                         "testing/ files must be excluded from the fingerprint set")
        # But real loop modules remain present:
        names = {Path(f).name for f in files}
        self.assertIn("orchestrator.py", names)


# =============================================================================
# Merged from test_identity_perf.py
# =============================================================================
"""Guards for the selfCodeFiles repo-walk optimization (perf/cicd-iteration).

The walk must stay correct after pruning excluded trees during traversal: it must never
include files under the non-self trees (.git/.claude/venv) and must still find the running
orchestrator's core modules. These invariants let us replace rglob-then-filter with a pruned
os.walk without changing the fingerprint set.
"""


def test_excludes_non_self_and_vcs_trees():
    # Check the path RELATIVE to the project root: the repo may itself live under a `.claude`
    # worktree path (e.g. C:/9to5/.claude/worktrees/...), so an absolute-substring scan would
    # false-flag every legitimate file. The invariant is about excluded SUBTREES under the root.
    root = str(identity.PROJECT_ROOT).replace("\\", "/").lower()
    rels = []
    for p in identity.selfCodeFiles():
        f = str(p).replace("\\", "/").lower()
        rels.append(f[len(root):] if f.startswith(root) else f)
    bad = [r for r in rels if any(seg in r for seg in ("/.git/", "/.claude/", "/venv/"))]
    assert bad == [], f"selfCodeFiles included excluded trees: {bad[:5]}"


def test_selfcodefiles_still_finds_core_modules():
    names = {p.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] for p in identity.selfCodeFiles()}
    assert {"orchestrator.py", "identity.py", "epoch.py"} <= names


def test_all_results_are_python_files():
    assert all(p.endswith(".py") for p in identity.selfCodeFiles())
