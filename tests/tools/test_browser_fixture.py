from tools.browser_fixture import write_browser_fixture


def test_browser_fixture_contains_deterministic_production_cases(tmp_path):
    write_browser_fixture(tmp_path)
    page = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "#status" in page
    assert "next.html" in page
    assert "proof.txt" in page
    assert "delayed" in page
    assert (tmp_path / "timeout.html").exists()
    assert (tmp_path / "proof.txt").read_text(encoding="utf-8") == "browser-download-proof\n"
