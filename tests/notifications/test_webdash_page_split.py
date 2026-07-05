"""Golden-snapshot + structural contract test for the split webdash page modules."""

from notifications.webdash_page import PAGE

REQUIRED_IDS = (
    "codename",
    "status",
    "goal",
    "tunnel",
    "auraDot",
    "auraNum",
    "meta",
    "kind",
    "search",
    "lockBtn",
    "feed",
    "subs",
    "arc",
    "curve",
)


def test_page_contains_all_dom_hooks_js_depends_on():
    for dom_id in REQUIRED_IDS:
        assert f'id="{dom_id}"' in PAGE, dom_id


def test_page_is_one_assembled_document():
    assert PAGE.strip().startswith("<!doctype html>")
    assert PAGE.strip().endswith("</html>")


def test_quiet_server_swallows_connection_drops_but_delegates_real_errors(capsys):
    """REGRESSION: a client drop during the pre-dispatch raw_requestline read raises a
    ConnectionError before any handler guard, and the default handle_error dumps a full
    traceback to stderr (log noise). The server must swallow connection errors but STILL
    surface a real handler bug (so genuine defects aren't masked)."""
    from notifications.webdash import _QuietThreadingHTTPServer

    srv = _QuietThreadingHTTPServer.__new__(_QuietThreadingHTTPServer)  # no socket bind
    try:
        raise ConnectionAbortedError(10053, "aborted")
    except ConnectionAbortedError:
        srv.handle_error(None, ("127.0.0.1", 5))
    assert "Traceback" not in capsys.readouterr().err  # benign drop -> silent
    try:
        raise ValueError("real handler bug")
    except ValueError:
        srv.handle_error(None, ("127.0.0.1", 5))
    assert "ValueError" in capsys.readouterr().err  # real error -> still surfaced
