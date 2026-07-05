"""Tests for tunnel providers and the supervised TunnelManager. No real network/binaries."""

import hashlib
import io
import time

from notifications import tunnel_providers as tp
from notifications.tunnel import TunnelManager


# --------------------------------------------------------------------------- providers
def test_cloudflared_parse_url():
    p = tp.CloudflaredProvider()
    assert p.parse_url("INF |  https://abc-def.trycloudflare.com  |") == "https://abc-def.trycloudflare.com"
    assert p.parse_url("no url here") is None


def test_bore_parse_url():
    p = tp.BoreProvider()
    assert p.parse_url("listening at bore.pub:12345") == "http://bore.pub:12345"
    assert p.parse_url("nothing") is None


def test_localtunnel_start_resolves_full_npx_path(monkeypatch):
    """REGRESSION: bare 'npx' is npx.CMD on Windows and Popen(['npx',...]) raises WinError 2,
    so localtunnel failed to launch on every attempt. start() must spawn the shutil.which-
    resolved full path (which Popen can launch), not the bare 'npx' string."""
    monkeypatch.setattr(tp.shutil, "which", lambda name: "C:\\node\\npx.CMD" if name == "npx" else None)
    captured = {}
    monkeypatch.setattr(tp, "_spawn", lambda cmd: captured.update(cmd=cmd))
    tp.LocaltunnelProvider().start(8787)
    assert captured["cmd"][0] == "C:\\node\\npx.CMD"  # resolved path, NOT bare "npx"
    assert captured["cmd"][0] != "npx"
    assert "localtunnel" in captured["cmd"]


def test_localtunnel_parse_url():
    p = tp.LocaltunnelProvider()
    assert p.parse_url("your url is: https://tasty-cat-12.loca.lt") == "https://tasty-cat-12.loca.lt"


def test_ngrok_skipped_without_token(monkeypatch):
    monkeypatch.delenv("NGROK_AUTH_TOKEN", raising=False)
    assert tp.NgrokProvider().available() is False
    monkeypatch.setenv("NGROK_AUTH_TOKEN", "tok")
    assert tp.NgrokProvider().available() is True


def test_default_providers_order():
    names = [p.name for p in tp.default_providers()]
    assert names[0] == "cloudflared"
    assert {"cloudflared", "ngrok", "bore", "localtunnel"} <= set(names)


# --------------------------------------------------------------------------- _download_binary
class _FakeHttpResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_download_binary_passes_bounded_timeout(monkeypatch, tmp_path):
    """B(hang): urlopen must be called with a finite timeout, never the default (None/block
    forever) that urlretrieve used."""
    seen = {}

    def _fake_urlopen(req, timeout=None):
        seen["timeout"] = timeout
        return _FakeHttpResp(b"binary-bytes")

    monkeypatch.setattr(tp.urllib.request, "urlopen", _fake_urlopen)
    dest = tmp_path / "cloudflared.exe"
    assert tp.TunnelProvider._download_binary("https://example.com/cloudflared", dest) is True
    assert seen["timeout"] == tp._DOWNLOAD_TIMEOUT_S
    assert seen["timeout"] is not None
    assert dest.read_bytes() == b"binary-bytes"


def test_download_binary_checksum_match_succeeds(monkeypatch, tmp_path):
    payload = b"totally-a-real-cloudflared-binary"
    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(tp.urllib.request, "urlopen", lambda req, timeout=None: _FakeHttpResp(payload))
    dest = tmp_path / "cloudflared"
    ok = tp.TunnelProvider._download_binary("https://example.com/cloudflared", dest, expected_sha256=digest)
    assert ok is True
    assert dest.exists()


def test_download_binary_checksum_mismatch_deletes_and_fails(monkeypatch, tmp_path):
    """A(integrity): a digest mismatch must delete the file and return False -- the caller
    must never chmod/execute an unverified binary."""
    monkeypatch.setattr(
        tp.urllib.request, "urlopen", lambda req, timeout=None: _FakeHttpResp(b"tampered-payload")
    )
    dest = tmp_path / "cloudflared"
    ok = tp.TunnelProvider._download_binary("https://example.com/cloudflared", dest, expected_sha256="0" * 64)
    assert ok is False
    assert not dest.exists()


def test_cloudflared_ensure_available_refuses_unpinned_arch(monkeypatch, tmp_path):
    """When there is no pinned checksum for the current (os, arch), ensure_available must
    refuse to download rather than fetching an unverifiable binary."""
    p = tp.CloudflaredProvider()
    monkeypatch.setattr(tp.shutil, "which", lambda name: None)
    monkeypatch.setattr(p, "_cached_path", lambda: tmp_path / "cloudflared")
    monkeypatch.setattr(tp, "_plat", lambda: ("windows", "arm64", ".exe"))
    called = {"count": 0}

    def _boom(*a, **k):
        called["count"] += 1
        raise AssertionError("should not attempt download without a pinned checksum")

    monkeypatch.setattr(tp.urllib.request, "urlopen", _boom)
    assert p.ensure_available() is False
    assert called["count"] == 0


def test_cloudflared_ensure_available_downloads_and_verifies(monkeypatch, tmp_path):
    """ensure_available uses the pinned version tag + expected digest end-to-end."""
    p = tp.CloudflaredProvider()
    payload = b"fake-cloudflared-binary"
    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(tp.shutil, "which", lambda name: None)
    monkeypatch.setattr(p, "_cached_path", lambda: tmp_path / "cloudflared.exe")
    monkeypatch.setattr(tp, "_plat", lambda: ("windows", "amd64", ".exe"))
    monkeypatch.setitem(tp._CLOUDFLARED_SHA256, ("windows", "amd64"), digest)
    seen_urls = []

    def _fake_urlopen(req, timeout=None):
        seen_urls.append(req.full_url if hasattr(req, "full_url") else req)
        return _FakeHttpResp(payload)

    monkeypatch.setattr(tp.urllib.request, "urlopen", _fake_urlopen)
    assert p.ensure_available() is True
    assert seen_urls and tp._CLOUDFLARED_VERSION in seen_urls[0]
    assert "latest" not in seen_urls[0]


def test_probe_non5xx(monkeypatch):
    p = tp.CloudflaredProvider()

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(tp.urllib.request, "urlopen", lambda *a, **k: _Resp())
    assert p.probe("https://x.trycloudflare.com") is True


def test_probe_5xx_is_false(monkeypatch):
    p = tp.CloudflaredProvider()

    class _Resp:
        status = 503

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(tp.urllib.request, "urlopen", lambda *a, **k: _Resp())
    assert p.probe("https://x.trycloudflare.com") is False


def test_probe_connection_error_is_false(monkeypatch):
    p = tp.CloudflaredProvider()

    def _boom(*a, **k):
        raise OSError("refused")

    monkeypatch.setattr(tp.urllib.request, "urlopen", _boom)
    assert p.probe("https://x.trycloudflare.com") is False


# --------------------------------------------------------------------------- manager fakes
class _FakePopen:
    def __init__(self, line):
        self._lines = iter([line + "\n"])
        self.stdout = self
        self.pid = 999
        self._alive = True

    def __iter__(self):
        return self._lines

    def readline(self):
        return next(self._lines, "")

    def poll(self):
        return None if self._alive else 0

    def terminate(self):
        self._alive = False

    def kill(self):
        self._alive = False

    def wait(self, timeout=None):
        self._alive = False
        return 0


class _FakeProvider:
    def __init__(self, name="fake", url="https://live.example.com", probe_ok=True, can_start=True):
        self.name = name
        self._url = url
        self._probe_ok = probe_ok
        self._can_start = can_start
        self.started = 0

    def available(self):
        return True

    def ensure_available(self):
        return self._can_start

    def start(self, port):
        self.started += 1
        return _FakePopen(f"connected at {self._url}")

    def parse_url(self, line):
        return self._url if self._url in line else None

    def probe(self, url, timeout=5.0):
        return self._probe_ok


def _fast(mgr):
    """Collapse all supervisor timings so tests run instantly."""
    mgr.POLL_INTERVAL = 0.01
    mgr.PROBE_INTERVAL = 0.02
    mgr.VALIDATE_TIMEOUT = 0.1
    mgr.URL_WAIT_TIMEOUT = 0.4
    mgr.BACKOFF_BASE = 0.01
    mgr.BACKOFF_CAP = 0.02
    mgr.UPTIME_RESET = 0.05
    mgr.DEMOTE_REQUALIFY = 0.05
    return mgr


def _wait_until(pred, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


def test_manager_start_fires_on_url():
    mgr = _fast(TunnelManager(providers=[_FakeProvider()]))
    got = []
    mgr.on_url(got.append)
    mgr.start(8787)
    assert _wait_until(lambda: bool(got))
    assert got[0] == "https://live.example.com"
    assert mgr.url == "https://live.example.com"
    assert mgr.provider_name == "fake"
    mgr.stop()


def test_manager_url_not_posted_until_valid():
    prov = _FakeProvider(probe_ok=False)
    mgr = _fast(TunnelManager(providers=[prov]))
    got = []
    mgr.on_url(got.append)
    mgr.start(8787)
    # probe always False -> URL must never be announced
    assert not _wait_until(lambda: bool(got), timeout=0.5)
    mgr.stop()


def test_manager_demotes_after_failures():
    bad = _FakeProvider(name="bad", probe_ok=False)
    good = _FakeProvider(name="good", url="https://good.example.com")
    mgr = _fast(TunnelManager(providers=[bad, good]))
    got = []
    mgr.on_url(got.append)
    mgr.start(8787)
    assert _wait_until(lambda: mgr.provider_name == "good", timeout=4.0)
    assert _wait_until(lambda: got and got[-1] == "https://good.example.com")
    mgr.stop()


def test_manager_resume_reuses_saved_url():
    class _StubState:
        def __init__(self):
            self.meta = {"tunnel_url": "https://saved.example.com"}

        def save(self):
            pass

    prov = _FakeProvider()
    state = _StubState()
    mgr = _fast(TunnelManager(providers=[prov], state=state))
    got = []
    mgr.on_url(got.append)
    mgr.start(8787)
    assert _wait_until(lambda: bool(got))
    assert got[0] == "https://saved.example.com"
    assert prov.started == 0  # reused the saved tunnel, no new process
    mgr.stop()


def test_manager_stop_is_clean():
    mgr = _fast(TunnelManager(providers=[_FakeProvider()]))
    mgr.start(8787)
    assert _wait_until(lambda: mgr.url is not None)
    mgr.stop()
    assert mgr.is_alive is False


def test_announce_saves_state_under_the_state_lock():
    """The supervisor daemon thread mutates shared TaskState -- _announce must hold the
    orchestrator's state lock around meta mutation + save (same discipline as dashboard)."""

    class _SpyLock:
        def __init__(self):
            self.held = 0
            self.acquisitions = 0

        def __enter__(self):
            self.held += 1
            self.acquisitions += 1
            return self

        def __exit__(self, *a):
            self.held -= 1
            return False

    lock = _SpyLock()

    class _StubState:
        def __init__(self):
            self.meta = {}
            self.saved_under_lock = None

        def save(self):
            self.saved_under_lock = lock.held > 0

    state = _StubState()
    mgr = _fast(TunnelManager(providers=[_FakeProvider()], state=state, state_lock=lock))
    mgr.start(8787)
    assert _wait_until(lambda: state.meta.get("tunnel_url"))
    mgr.stop()
    assert state.meta["tunnel_url"] == "https://live.example.com"
    assert state.saved_under_lock is True, "state.save() ran outside the state lock"
    assert lock.acquisitions >= 1


def test_stop_joins_promptly_when_no_url():
    """B15(a): the supervisor must wake on stop() even while blocked waiting for a URL that
    never arrives -- otherwise stop() hangs for the full URL_WAIT_TIMEOUT (the join hang)."""
    prov = _FakeProvider(probe_ok=False)  # a URL is parsed but never validates -> never announced
    mgr = TunnelManager(providers=[prov])
    mgr.POLL_INTERVAL = 0.01
    mgr.PROBE_INTERVAL = 0.02
    mgr.VALIDATE_TIMEOUT = 0.05
    mgr.URL_WAIT_TIMEOUT = 30.0  # unpatched stop() would block here for 30s
    mgr.BACKOFF_BASE = 0.01
    mgr.BACKOFF_CAP = 0.02
    mgr.start(8787)
    assert _wait_until(lambda: prov.started >= 1, timeout=3.0)
    t0 = time.time()
    mgr.stop()
    assert time.time() - t0 < 1.0, "stop() did not join promptly"
    assert mgr.is_alive is False


def test_same_url_reannounces_after_restart():
    """B15(b): a fresh provider session must re-announce even an identical URL so consumers are
    re-notified after a tunnel restart (a stable/named tunnel keeps the same host)."""

    class _DyingPopen:
        def __init__(self, line):
            self._lines = iter([line + "\n"])
            self.stdout = self
            self.pid = 1
            self._polls = 1  # alive for exactly one watch poll, then reports exit

        def __iter__(self):
            return self._lines

        def poll(self):
            if self._polls > 0:
                self._polls -= 1
                return None
            return 0

        def terminate(self):
            self._polls = 0

        def kill(self):
            self._polls = 0

        def wait(self, timeout=None):
            self._polls = 0
            return 0

    class _RestartProvider(_FakeProvider):
        def start(self, port):
            self.started += 1
            return _DyingPopen(f"connected at {self._url}")

    prov = _RestartProvider()
    mgr = _fast(TunnelManager(providers=[prov]))
    got = []
    mgr.on_url(got.append)
    mgr.start(8787)
    assert _wait_until(lambda: len(got) >= 2, timeout=4.0), "same URL was not re-announced"
    assert got[0] == got[1] == "https://live.example.com"
    assert prov.started >= 2  # the session actually restarted
    mgr.stop()
