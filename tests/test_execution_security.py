"""CapabilityPolicy resolution + validateMounts threat-model port (openclaw)."""
import pytest

from platform_core.execution.security import (
    CapabilityPolicy, MountSecurityError, validateMounts,
)


class _TS:
    def __init__(self, universe):
        self._u = universe
    def universe(self):
        return self._u


def test_policy_resolves_from_universe():
    ts = _TS({"allowed_paths": ["src/"], "hard_boundaries": [".env", ".git"]})
    pol = CapabilityPolicy.resolve(ts, {"subtask_id": "s1"})
    assert "src/" in pol.allowed_paths
    assert ".env" in pol.hard_boundaries
    assert pol.network is True                 # default grant until a risk tier tightens it
    assert pol.source == "universe"


def test_policy_default_when_no_universe():
    pol = CapabilityPolicy.resolve(None, None)
    assert pol.network is True
    assert pol.source == "default"
    assert isinstance(pol.disallowed_tools, list)


@pytest.mark.parametrize("bad", [
    "/home/user/.ssh",
    "/home/user/.aws/credentials",
    "/home/user/.gnupg",
    "/var/run/docker.sock",
    "/project/.env",
    "/project/.git",
])
def test_validate_mounts_blocks_sensitive_paths(bad):
    pol = CapabilityPolicy.resolve(None, None)
    with pytest.raises(MountSecurityError):
        validateMounts(pol, [bad])


def test_validate_mounts_allows_repo_root():
    pol = CapabilityPolicy.resolve(None, None)
    validateMounts(pol, ["/project/repo"])   # repo root is fine (its .env is not a mount target)


def test_validate_mounts_blocks_host_network():
    pol = CapabilityPolicy.resolve(None, None)
    with pytest.raises(MountSecurityError):
        validateMounts(pol, ["/project/repo"], network_mode="host")


def test_validate_mounts_allows_none_network():
    pol = CapabilityPolicy.resolve(None, None)
    validateMounts(pol, ["/project/repo"], network_mode="none")   # no raise


def test_system_root_matched_by_segment_not_substring():
    # B32: '/etc' must block as a WHOLE path segment, not a bare substring that also
    # matches '/data/etcd/x' (etcd) or '/data/devel' (dev).
    pol = CapabilityPolicy.resolve(None, None)
    with pytest.raises(MountSecurityError):
        validateMounts(pol, ["/etc/passwd"])
    validateMounts(pol, ["/data/etcd/x"])     # 'etcd' != 'etc' segment -> allowed
    validateMounts(pol, ["/data/devel/y"])    # 'devel' != 'dev' segment -> allowed
