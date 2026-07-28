"""LocalEnvironment must be a provable identity no-op (regression guard: fabric off == today)."""
from platform_core.execution.backends.local import LocalEnvironment
from platform_core.execution.environment import Capability


def test_provision_returns_base_dir_unchanged():
    env = LocalEnvironment()
    h = env.provision(task_state=None, subtask={"subtask_id": "s1"},
                      base_dir="/repo/root", policy=None)
    assert h.work_dir == "/repo/root"
    assert h.backend == "local"
    assert Capability.PERSISTENT in h.capabilities


def test_wraplauncher_is_identity():
    env = LocalEnvironment()
    h = env.provision(task_state=None, subtask=None, base_dir="/repo", policy=None)
    cmd = ["cmd", "/c", "claude.cmd", "--print", "--dangerously-skip-permissions"]
    out_cmd, out_work = env.wrapLauncher(cmd, h)
    assert out_cmd == cmd          # byte-for-byte identical command
    assert out_work == "/repo"     # unchanged cwd


def test_collect_and_teardown_are_noops():
    env = LocalEnvironment()
    h = env.provision(task_state=None, subtask=None, base_dir="/repo", policy=None)
    summary = env.collectChanges(h, task_state=None, subtask=None)
    assert summary["backend"] == "local" and summary["merged"] is False
    assert env.teardown(h) is None
    assert env.healthCheck() is True


def test_local_handle_is_explicitly_non_landing():
    env = LocalEnvironment()
    h = env.provision(task_state=None, subtask=None, base_dir="/repo", policy=None)
    assert h.requires_canonical_landing is False


def test_local_backend_declares_unconfined_external_trust_boundary():
    env = LocalEnvironment()
    h = env.provision(task_state=None, subtask=None, base_dir="/repo", policy=None)

    assert env.OS_ENFORCED is False
    assert env.REQUIRES_EXTERNAL_TRUST is True
    assert h.meta == {
        "os_enforced": False,
        "trust_authority": "external_required",
    }
    assert "eligibility" not in h.meta
