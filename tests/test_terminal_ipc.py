import notifications.terminal_ipc as ipc


def test_nav_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(ipc, "NAV_PATH", tmp_path / "nav.json")
    ipc.write_nav(page_idx=2, mode="raw", frozen=True)
    nav = ipc.read_nav()
    assert nav == {"page_idx": 2, "mode": "raw", "frozen": True}


def test_read_nav_defaults_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ipc, "NAV_PATH", tmp_path / "nope.json")
    assert ipc.read_nav() == {"page_idx": 0, "mode": "summary", "frozen": False}


def test_bump_nav_clamps_and_toggles(tmp_path, monkeypatch):
    monkeypatch.setattr(ipc, "NAV_PATH", tmp_path / "nav.json")
    ipc.write_nav(page_idx=0, mode="summary", frozen=False)
    n = ipc.bump_nav(delta_page=1, page_count=3)
    assert n["page_idx"] == 1
    n = ipc.bump_nav(delta_page=5, page_count=3)      # clamp to last
    assert n["page_idx"] == 2
    n = ipc.bump_nav(delta_page=-9, page_count=3)     # clamp to first
    assert n["page_idx"] == 0
    n = ipc.bump_nav(toggle_raw=True, page_count=3)
    assert n["mode"] == "raw"
    n = ipc.bump_nav(toggle_freeze=True, page_count=3)
    assert n["frozen"] is True


def test_mirror_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(ipc, "MIRROR_PATH", tmp_path / "mirror.json")
    ipc.write_mirror(body="hello", page_count=4, lanes=["brain", "st-001"])
    m = ipc.read_mirror()
    assert m["body"] == "hello" and m["page_count"] == 4 and m["lanes"] == ["brain", "st-001"]


def test_all_reads_are_best_effort_on_garbage(tmp_path, monkeypatch):
    p = tmp_path / "nav.json"; p.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(ipc, "NAV_PATH", p)
    assert ipc.read_nav() == {"page_idx": 0, "mode": "summary", "frozen": False}
