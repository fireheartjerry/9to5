"""DockerEnvironment command construction + security gate, with _run_docker mocked (no daemon)."""
from types import SimpleNamespace
from unittest import mock

import pytest

from platform_core.execution.backends import docker as dk
from platform_core.execution.environment import Capability
from platform_core.execution.security import CapabilityPolicy, MountSecurityError


def _ok(stdout="container123\n"):
    return SimpleNamespace(returncode=0, stdout=stdout, stderr="")


def test_healthcheck_true_when_docker_info_ok():
    with mock.patch.object(dk, "_run_docker", return_value=_ok("info ok")):
        assert dk.DockerEnvironment().healthCheck() is True


def test_healthcheck_false_when_docker_absent():
    with mock.patch.object(dk, "_run_docker", side_effect=FileNotFoundError("no docker")):
        assert dk.DockerEnvironment().healthCheck() is False


def test_provision_runs_container_and_records_cid():
    pol = CapabilityPolicy.resolve(None, None)
    captured = {}
    def _fake(args, **kw):
        captured["args"] = args
        return _ok("cid-abc\n")
    with mock.patch.object(dk, "_run_docker", side_effect=_fake):
        h = dk.DockerEnvironment().provision(task_state=None, subtask={"subtask_id": "s1"},
                                             base_dir="/project/repo", policy=pol)
    assert h.meta["cid"] == "cid-abc"
    assert h.backend == "docker"
    assert Capability.PERSISTENT not in h.capabilities    # docker tree is ephemeral
    assert "run" in captured["args"] and "-d" in captured["args"]


def test_provision_network_none_when_policy_denies_network():
    pol = CapabilityPolicy(allowed_paths=[], hard_boundaries=[], network=False,
                           disallowed_tools=[], source="risk:destructive")
    captured = {}
    def _cap(args, **kw):     # capture the docker args, return a valid CompletedProcess stand-in
        captured["args"] = args
        return _ok()
    with mock.patch.object(dk, "_run_docker", side_effect=_cap):
        dk.DockerEnvironment().provision(task_state=None, subtask=None,
                                         base_dir="/project/repo", policy=pol)
    args = captured["args"]
    assert "--network" in args and args[args.index("--network") + 1] == "none"


def test_provision_rejects_unsafe_mount():
    pol = CapabilityPolicy.resolve(None, None)
    with mock.patch.object(dk, "_run_docker", return_value=_ok()):
        with pytest.raises(MountSecurityError):
            dk.DockerEnvironment().provision(task_state=None, subtask=None,
                                             base_dir="/home/user/.ssh", policy=pol)


def test_wraplauncher_prefixes_docker_exec():
    pol = CapabilityPolicy.resolve(None, None)
    with mock.patch.object(dk, "_run_docker", return_value=_ok("cid-xyz\n")):
        env = dk.DockerEnvironment()
        h = env.provision(task_state=None, subtask=None, base_dir="/project/repo", policy=pol)
    out_cmd, out_work = env.wrapLauncher(["claude", "--print"], h)
    assert out_cmd == ["docker", "exec", "-w", h.meta["container_work"],
                       "cid-xyz", "claude", "--print"]
    assert out_work == h.work_dir
