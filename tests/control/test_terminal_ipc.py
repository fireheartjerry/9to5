import notifications.terminal_ipc as ipc


def _controller_binding(tmp_path):
    from platform_core.runtime import controller_state

    capability = object()
    authority = controller_state.issueDiagnosticControllerStateAuthority(
        root=tmp_path / "controller-state",
        repository_id="repo_terminal_ipc_test",
        controller_generation=5,
        process_capability=capability,
        expires_at="2099-01-01T00:00:00+00:00",
    )
    store = controller_state.ControllerStateStore(
        root=tmp_path / "controller-state", authority=authority
    )
    return store, authority


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
    p = tmp_path / "nav.json"
    p.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(ipc, "NAV_PATH", p)
    assert ipc.read_nav() == {"page_idx": 0, "mode": "summary", "frozen": False}


def test_ipc_files_live_outside_the_task_store():
    # R9: IPC files moved to state/ipc/ so task_io.iterStored can never misparse them.
    assert ipc.NAV_PATH.parent.name == "ipc"
    assert ipc.MIRROR_PATH.parent.name == "ipc"
    assert ipc.NAV_PATH.parent.name != "tasks"


def test_clear_removes_both_files(tmp_path, monkeypatch):
    monkeypatch.setattr(ipc, "NAV_PATH", tmp_path / "nav.json")
    monkeypatch.setattr(ipc, "MIRROR_PATH", tmp_path / "mirror.json")
    ipc.write_nav(1, "raw", True)
    ipc.write_mirror("b", 2, [])
    ipc.clear()
    assert not (tmp_path / "nav.json").exists()
    assert not (tmp_path / "mirror.json").exists()


def test_diagnostic_ipc_uses_only_explicit_controller_store(
    tmp_path, monkeypatch
):
    store, authority = _controller_binding(tmp_path)
    poison = tmp_path / "target-repository" / "state" / "ipc"
    monkeypatch.setattr(ipc, "_INSTALLED_BINDING", None, raising=False)
    monkeypatch.setattr(ipc, "_controllerPathsActive", lambda: False)
    monkeypatch.setattr(ipc, "NAV_PATH", poison / "terminal_nav.json")
    monkeypatch.setattr(ipc, "MIRROR_PATH", poison / "terminal_mirror.json")
    ipc.installTerminalIpcStore(store=store, authority=authority)
    try:
        ipc.write_nav(2, "raw", True)
        ipc.write_mirror("body", 3, ["brain"])
        assert ipc.read_nav() == {"page_idx": 2, "mode": "raw", "frozen": True}
        assert ipc.read_mirror() == {
            "body": "body",
            "page_count": 3,
            "lanes": ["brain"],
        }
        assert not poison.exists()
        ipc.clear()
        assert ipc.read_nav() == {"page_idx": 0, "mode": "summary", "frozen": False}
        assert ipc.read_mirror() == {"body": "", "page_count": 0, "lanes": []}
    finally:
        store.close()


def test_capsule_ipc_without_binding_never_falls_back_to_target_path(
    tmp_path, monkeypatch
):
    from platform_core.app_config import paths

    poison = tmp_path / "target-repository" / "state" / "ipc"
    monkeypatch.setattr(ipc, "_INSTALLED_BINDING", None, raising=False)
    monkeypatch.setattr(paths, "controllerPathsActive", lambda: True)
    monkeypatch.setattr(ipc, "NAV_PATH", poison / "terminal_nav.json")
    monkeypatch.setattr(ipc, "MIRROR_PATH", poison / "terminal_mirror.json")

    ipc.write_nav(4, "raw", True)
    ipc.write_mirror("ignored", 1, [])
    assert ipc.read_nav() == {"page_idx": 0, "mode": "summary", "frozen": False}
    assert ipc.read_mirror() == {"body": "", "page_count": 0, "lanes": []}
    ipc.clear()
    assert not poison.exists()
