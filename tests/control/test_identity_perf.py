"""Guards for the selfCodeFiles repo-walk optimization (perf/cicd-iteration).

The walk must stay correct after pruning excluded trees during traversal: it must never
include files under the non-self trees (.git/.claude/venv) and must still find the running
orchestrator's core modules. These invariants let us replace rglob-then-filter with a pruned
os.walk without changing the fingerprint set.
"""
import platform_core.core.identity as identity


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
