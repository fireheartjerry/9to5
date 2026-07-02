"""RemoteEnvironment stubs: ssh command construction + clean degrade when host/SDK absent."""
from types import SimpleNamespace
from unittest import mock

import config
from platform_core.execution.backends import remote as rm
from platform_core.execution.environment import Capability


def test_healthcheck_false_when_no_host():
    with mock.patch.object(config, "EXECUTION_REMOTE_HOST", ""):
        assert rm.RemoteEnvironment().healthCheck() is False


def test_healthcheck_true_when_host_reachable():
    with mock.patch.object(config, "EXECUTION_REMOTE_HOST", "box.example"), \
         mock.patch.object(config, "EXECUTION_REMOTE_KIND", "ssh"), \
         mock.patch.object(rm, "_run_remote",
                           return_value=SimpleNamespace(returncode=0, stdout="ok", stderr="")):
        assert rm.RemoteEnvironment().healthCheck() is True


def test_provision_records_host_and_ephemeral_caps():
    with mock.patch.object(config, "EXECUTION_REMOTE_HOST", "box.example"), \
         mock.patch.object(config, "EXECUTION_REMOTE_KIND", "ssh"), \
         mock.patch.object(rm, "_run_remote",
                           return_value=SimpleNamespace(returncode=0, stdout="/remote/work", stderr="")):
        h = rm.RemoteEnvironment().provision(task_state=None, subtask={"subtask_id": "s1"},
                                             base_dir="/repo", policy=None)
    assert h.meta["host"] == "box.example"
    assert h.backend == "remote"
    assert Capability.PERSISTENT not in h.capabilities


def test_wraplauncher_prefixes_ssh():
    with mock.patch.object(config, "EXECUTION_REMOTE_HOST", "box.example"), \
         mock.patch.object(config, "EXECUTION_REMOTE_KIND", "ssh"):
        _env = rm.RemoteEnvironment()
    # build a handle directly to test wrapLauncher in isolation
    from platform_core.execution.environment import EnvHandle
    handle = EnvHandle(work_dir="/remote/work", backend="remote",
                       meta={"host": "box.example", "kind": "ssh", "remote_work": "/remote/work"},
                       capabilities=Capability.EXEC)
    out_cmd, out_work = rm.RemoteEnvironment().wrapLauncher(["claude", "--print"], handle)
    assert out_cmd[:3] == ["ssh", "box.example", "cd"]
    assert out_cmd[-2:] == ["claude", "--print"]
    assert out_work == "/remote/work"


def test_unknown_kind_degrades_healthcheck_false():
    with mock.patch.object(config, "EXECUTION_REMOTE_HOST", "box.example"), \
         mock.patch.object(config, "EXECUTION_REMOTE_KIND", "modal"), \
         mock.patch.object(rm, "_run_remote", side_effect=RuntimeError("SDK not installed")):
        assert rm.RemoteEnvironment().healthCheck() is False
