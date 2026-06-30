"""Contract test for the ExecutionEnvironment ABC (no real backend)."""
from platform_core.execution.environment import (
    Capability, EnvHandle, ExecutionEnvironment,
)


class FakeEnvironment(ExecutionEnvironment):
    NAME = "fake"
    CAPABILITIES = Capability.FILE_RW | Capability.EXEC

    def __init__(self):
        self.calls = []

    def provision(self, *, task_state, subtask, base_dir, policy):
        self.calls.append("provision")
        return EnvHandle(work_dir=base_dir + "/wt", backend=self.NAME,
                         meta={"id": "x1"}, capabilities=self.CAPABILITIES)

    def wrapLauncher(self, run_cmd, handle):
        self.calls.append("wrap")
        return ["prefix", *run_cmd], handle.work_dir

    def collectChanges(self, handle, *, task_state, subtask):
        self.calls.append("collect")
        return {"merged": True}

    def teardown(self, handle):
        self.calls.append("teardown")


def test_capability_flag_is_combinable():
    caps = Capability.FILE_RW | Capability.NETWORK
    assert Capability.FILE_RW in caps
    assert Capability.SNAPSHOT not in caps


def test_envhandle_fields():
    h = EnvHandle(work_dir="/w", backend="fake", meta={}, capabilities=Capability(0))
    assert h.work_dir == "/w" and h.backend == "fake" and h.meta == {}


def test_lifecycle_ordering_and_workdir_honored():
    env = FakeEnvironment()
    handle = env.provision(task_state=None, subtask={"subtask_id": "s1"},
                           base_dir="/base", policy=None)
    assert handle.work_dir == "/base/wt"
    cmd, work = env.wrapLauncher(["claude", "--print"], handle)
    assert cmd == ["prefix", "claude", "--print"] and work == "/base/wt"
    summary = env.collectChanges(handle, task_state=None, subtask={"subtask_id": "s1"})
    assert summary == {"merged": True}
    env.teardown(handle)
    assert env.calls == ["provision", "wrap", "collect", "teardown"]


def test_default_healthcheck_true():
    assert FakeEnvironment().healthCheck() is True
