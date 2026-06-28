"""Tests for tunnel providers and the supervised TunnelManager. No real network/binaries."""
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
