"""Work-directory resolution returns an explicit lifetime-bearing value."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from platform_core.runtime.work_directory import LaunchError, resolveWorkDir


def test_resolution_raises_a_typed_error_instead_of_returning_an_int():
    args = SimpleNamespace(repo_ref="main", repo_url=None, work_dir=None, sim_run=False)

    with pytest.raises(LaunchError) as caught:
        resolveWorkDir(args)

    assert caught.value.exit_code == 2
    assert "requires --repo-url" in str(caught.value)


def test_sim_run_directory_is_a_managed_temporary_lease():
    args = SimpleNamespace(repo_ref=None, repo_url=None, work_dir=None, sim_run=True)

    with resolveWorkDir(args) as resolved:
        path = resolved.path
        assert isinstance(path, Path)
        assert path.is_dir()
        assert args.work_dir == str(path)

    assert not path.exists()


def test_user_directory_lease_never_deletes_the_user_directory(tmp_path):
    args = SimpleNamespace(repo_ref=None, repo_url=None, work_dir=str(tmp_path), sim_run=False)

    with resolveWorkDir(args) as resolved:
        assert resolved.path == tmp_path.resolve()

    assert tmp_path.is_dir()
