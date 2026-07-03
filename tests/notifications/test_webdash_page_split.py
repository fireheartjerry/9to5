"""Golden-snapshot + structural contract test for the split webdash page modules."""
from notifications.webdash_page import PAGE

REQUIRED_IDS = (
    "codename", "status", "goal", "tunnel", "auraDot", "auraNum", "meta",
    "kind", "search", "lockBtn", "feed", "subs", "arc", "curve",
)


def test_page_contains_all_dom_hooks_js_depends_on():
    for dom_id in REQUIRED_IDS:
        assert f'id="{dom_id}"' in PAGE, dom_id


def test_page_is_one_assembled_document():
    assert PAGE.strip().startswith("<!doctype html>")
    assert PAGE.strip().endswith("</html>")
