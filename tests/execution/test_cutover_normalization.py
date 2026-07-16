"""RED behavioral contracts for initial cutover, exact bytes, refs, config and index."""
from __future__ import annotations

import importlib
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
BOM_PATHS = [
    "docs/simulated/README.md",
    "tests/orchestration/test_work_profile.py",
    "tests/review/test_verification.py",
    "tests/review/test_verification_error_handling.py",
    "tests/test_review_verification.py",
]


class LegacyGeneration:
    """Test-local implementation of the ordinary cutover legacy-generation port."""

    def __init__(self, *, processes=(), descendants=None, listeners=(),
                 provider_children=(), tunnels=(), cooperative_restart=True):
        self.processes = list(processes)
        self.descendants = descendants or {}
        self.listeners = list(listeners)
        self.provider_children = list(provider_children)
        self.tunnels = list(tunnels)
        self.cooperative_restart = cooperative_restart
        self.ingress_closed = False

    @classmethod
    def running(cls):
        return cls(processes=[100], listeners=["discord"], cooperative_restart=True)

    def close_ingress(self):
        self.ingress_closed = True

    def quiesce_all(self):
        self.processes.clear()
        self.descendants.clear()
        self.listeners.clear()
        self.provider_children.clear()
        self.tunnels.clear()

    def try_restart(self):
        return not self.ingress_closed and self.cooperative_restart

    def snapshot_bytes(self):
        return repr((self.processes, self.descendants, self.listeners,
                     self.provider_children, self.tunnels, self.ingress_closed)).encode()


def _anchor():
    return importlib.import_module("bootstrap.galaxy_launcher.anchor")


def _git(repo, *args, check=True):
    return subprocess.run(["git", *args], cwd=repo, check=check,
                          text=True, capture_output=True, timeout=20)


@pytest.fixture()
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "t@example.test")
    _git(path, "config", "user.name", "T")
    (path / "tracked.txt").write_bytes(b"one\n")
    (path / "run.ps1").write_bytes(b"machine-local\r\n")
    _git(path, "add", "tracked.txt")
    _git(path, "commit", "-m", "base")
    return path


def test_cutover_supervisor_fences_ingress_quiesces_descendants_and_denies_restart(tmp_path):
    mod = _anchor()
    legacy = LegacyGeneration(
        processes=[100, 101], descendants={100: [102]}, listeners=["discord", "cli"],
        provider_children=[200], tunnels=["tunnel-1"], cooperative_restart=True,
    )
    supervisor = mod.CutoverSupervisor(tmp_path, legacy=legacy)
    fence = supervisor.begin_create_only_maintenance_fence()
    receipt = supervisor.quiesce_and_watch(fence)
    assert receipt.ingress_closed
    assert receipt.processes_remaining == [] and receipt.listeners_remaining == []
    assert receipt.provider_children_remaining == [] and receipt.tunnels_remaining == []
    assert legacy.try_restart() is False
    assert supervisor.fence_owner(fence) == "bootstrap_supervisor"


@pytest.mark.parametrize("failpoint", [
    "before_commit", "after_commit", "before_inactive_install",
    "after_inactive_install", "before_anchor_handoff", "after_anchor_handoff",
])
def test_commit_install_handoff_failpoints_never_reopen_legacy(failpoint, tmp_path):
    mod = _anchor()
    supervisor = mod.CutoverSupervisor(tmp_path, legacy=LegacyGeneration.running())
    result = supervisor.run_inactive_cutover(failpoint=failpoint)
    assert result.ingress_closed is True
    assert result.legacy_restart_allowed is False
    if result.commit_persisted:
        assert result.outcome in {"inactive_installed", "fenced_for_verified_rollback"}
    else:
        assert result.outcome in {"old_generation_restored", "inactive_installed"}


def test_all_five_live_bom_files_preserve_one_parent_bom_and_rehash_parent_blob():
    mod = _anchor()
    bom = b"\xef\xbb\xbf"
    for rel in BOM_PATHS:
        raw = (ROOT / rel).read_bytes()
        parent = subprocess.check_output(["git", "show", f"HEAD:{rel}"], cwd=ROOT,
                                         timeout=20)
        assert raw.startswith(bom) and parent.startswith(bom)
        canonical = mod.canonicalize_source_bytes(raw, parent=parent, textual=True)
        assert canonical == parent
        assert mod.git_blob_oid(canonical) == mod.git_blob_oid(parent)
        for attack in (raw[len(bom):], bom + raw, b"x" + bom + raw[len(bom):]):
            with pytest.raises(mod.SourceNormalizationRefused):
                mod.canonicalize_source_bytes(attack, parent=parent, textual=True)


def test_text_and_binary_policy_allows_only_crlf_to_lf_and_exact_binary():
    mod = _anchor()
    assert mod.canonicalize_source_bytes(b"a\r\nb\r\n", parent=b"a\nb\n", textual=True) == b"a\nb\n"
    for bad in (b"a\rb", b"a\x00b", b"\xff", b"\xff\xfea\x00"):
        with pytest.raises(mod.SourceNormalizationRefused):
            mod.canonicalize_source_bytes(bad, parent=b"a\n", textual=True)
    binary = b"\x00\xff\r\n"
    assert mod.canonicalize_source_bytes(binary, parent=binary, textual=False) == binary
    with pytest.raises(mod.SourceNormalizationRefused):
        mod.canonicalize_source_bytes(binary + b"x", parent=binary, textual=False)


def test_packed_only_main_then_docs_commit_normalization_is_idempotent(repo):
    mod = _anchor()
    _git(repo, "pack-refs", "--all", "--prune")
    assert not (repo / ".git" / "refs" / "heads" / "main").exists()
    first = mod.normalize_repository(repo)
    assert first.loose_main_created and first.loose_oid == first.head_oid
    (repo / "docs.md").write_text("docs\n", encoding="utf-8")
    _git(repo, "add", "docs.md")
    _git(repo, "commit", "-m", "docs")
    second = mod.normalize_repository(repo)
    third = mod.normalize_repository(repo)
    assert second.head_oid == third.head_oid
    assert second.tree_digest == third.tree_digest
    assert third.changed is False


def test_git_config_normalization_preserves_duplicates_but_pins_safe_values_and_hooks(repo):
    mod = _anchor()
    config_path = repo / ".git" / "config"
    with config_path.open("a", encoding="utf-8") as fh:
        fh.write("\n[branch \"main\"]\n\tmerge = refs/heads/main\n")
        fh.write("[branch \"main\"]\n\tdescription = inert duplicate\n")
        fh.write("[extensions]\n\tworktreeConfig = true\n")
        fh.write("[core]\n\thooksPath = C:/unused/hooks\n")
    result = mod.normalize_git_config(repo, prove_hook_inactive=lambda path: True)
    text = config_path.read_text("utf-8")
    assert text.count('[branch "main"]') == 2
    assert "worktreeConfig" not in text
    assert result.values["core.autocrlf"] == "false"
    assert result.values["core.safecrlf"] == "true"
    assert result.values["maintenance.auto"] == "false"
    with pytest.raises(mod.ActiveHookRefused):
        mod.normalize_git_config(repo, prove_hook_inactive=lambda path: False)


def test_dirc_v2_tree_extension_is_validated_ignored_and_corruption_refused(repo):
    mod = _anchor()
    _git(repo, "read-tree", "HEAD")
    index = (repo / ".git" / "index").read_bytes()
    parsed = mod.parse_git_index(index)
    assert parsed.version == 2
    rebuilt = mod.materialize_index_from_tree(repo, parsed.head_tree, omit_extensions={"TREE"})
    assert mod.parse_git_index(rebuilt).entries == parsed.entries
    if parsed.extension("TREE") is not None:
        corrupt = mod.corrupt_extension(index, "TREE")
        with pytest.raises(mod.GitIndexRefused):
            mod.parse_git_index(corrupt)
    with pytest.raises(mod.GitIndexRefused):
        mod.add_required_extension(index, "link", b"bad")


def test_ps51_path_helper_accepts_live_forms_and_rejects_relative_unc_and_device_paths():
    script = ROOT / "bootstrap" / "galaxy_launcher" / "tofu_bootstrap.ps1"
    powershell = shutil.which("powershell.exe")
    assert powershell
    version = subprocess.run([powershell, "-NoLogo", "-NoProfile", "-NonInteractive",
                              "-Command", "$PSVersionTable.PSVersion.Major"],
                             text=True, capture_output=True, timeout=20)
    assert version.returncode == 0 and version.stdout.strip() == "5", (
        f"stdout={version.stdout}\nstderr={version.stderr}")
    for value in (r"C:\9to5", "C:/9to5"):
        cp = subprocess.run([powershell, "-NoLogo", "-NoProfile", "-NonInteractive",
                             "-File", str(script), "-SelfTestCanonicalPath", value],
                            text=True, capture_output=True, timeout=20)
        assert cp.returncode == 0, f"stdout={cp.stdout}\nstderr={cp.stderr}"
        assert cp.stdout.strip().lower() == r"c:\9to5"
    for value in (r"C:foo", r"\foo", r"\\server\share", r"\\?\C:\x",
                  r"\\.\pipe\x", "//?/C:/x", "//./pipe/x"):
        cp = subprocess.run([powershell, "-NoLogo", "-NoProfile", "-NonInteractive",
                             "-File", str(script), "-SelfTestCanonicalPath", value],
                            text=True, capture_output=True, timeout=20)
        assert cp.returncode != 0, f"unexpectedly accepted {value!r}\nstdout={cp.stdout}"


def test_live_git_root_forward_slash_form_roundtrips_through_ps51_helper():
    live = Path("C:/9to5")
    assert live.is_dir()
    git_root = _git(live, "rev-parse", "--show-toplevel").stdout.strip()
    assert git_root == "C:/9to5"
    powershell = shutil.which("powershell.exe")
    script = ROOT / "bootstrap" / "galaxy_launcher" / "tofu_bootstrap.ps1"
    cp = subprocess.run([powershell, "-NoLogo", "-NoProfile", "-NonInteractive",
                         "-File", str(script), "-SelfTestCanonicalPath", git_root],
                        text=True, capture_output=True, timeout=20)
    assert cp.returncode == 0 and cp.stdout.strip().lower() == r"c:\9to5", (
        f"stdout={cp.stdout}\nstderr={cp.stderr}")


def test_normalization_never_adopts_or_mutates_ignored_machine_run_script(repo):
    mod = _anchor()
    path = repo / "run.ps1"
    before = (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_mode)
    mod.normalize_repository(repo)
    after = (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_mode)
    assert after == before
    assert "run.ps1" not in _git(repo, "ls-files").stdout.splitlines()


def test_precommit_restore_needs_fresh_exact_approval_and_postcommit_uses_verified_rollback(tmp_path):
    mod = _anchor()
    supervisor = mod.CutoverSupervisor(tmp_path, legacy=LegacyGeneration.running())
    before = supervisor.snapshot_legacy_bytes()
    pre = supervisor.run_inactive_cutover(failpoint="before_commit", approval=None)
    assert pre.outcome == "old_generation_restored"
    assert supervisor.snapshot_legacy_bytes() == before
    for approval in ("yes", "preapproved", "TRUST GENERIC"):
        with pytest.raises(mod.FreshExactApprovalRequired):
            supervisor.run_inactive_cutover(approval=approval)
    challenge = supervisor.begin_fresh_exact_approval()
    approval = supervisor.accept_fresh_exact_approval(
        challenge, f"TRUST CUTOVER {challenge.digest} NONCE {challenge.nonce}")
    post = supervisor.run_inactive_cutover(
        failpoint="after_commit", approval=approval, verified_rollback=True)
    assert post.outcome == "fenced_for_verified_rollback" and post.ingress_closed


@pytest.mark.parametrize("attack", ["loose_mismatch", "symbolic_loose", "loose_race", "packed_mismatch"])
def test_loose_ref_mismatch_nonordinary_race_and_bad_packed_shadow_refuse(repo, attack):
    mod = _anchor()
    ref = repo / ".git" / "refs" / "heads" / "main"
    callback = None
    if attack == "loose_mismatch":
        ref.write_text("0" * 40 + "\n", encoding="ascii")
    elif attack == "symbolic_loose":
        ref.write_text("ref: refs/heads/other\n", encoding="ascii")
    elif attack == "packed_mismatch":
        (repo / ".git" / "packed-refs").write_text(
            "# pack-refs with: peeled fully-peeled sorted\n" + "0" * 40
            + " refs/heads/main\n", encoding="ascii")
    else:
        def replace_ref_during_recheck():
            ref.write_text("f" * 40 + "\n", encoding="ascii")

        callback = replace_ref_during_recheck
    with pytest.raises(mod.RefNormalizationRefused):
        mod.normalize_repository(repo, before_ref_recheck=callback)


def test_matching_stale_packed_shadow_is_tolerated(repo):
    mod = _anchor()
    head_oid = _git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / ".git" / "packed-refs").write_text(
        "# pack-refs with: peeled fully-peeled sorted\n"
        f"{head_oid} refs/heads/main\n", encoding="ascii")
    assert mod.normalize_repository(repo).head_oid == head_oid


@pytest.mark.parametrize("attack", [
    "untracked_collision", "ref_drift", "materialization_failure", "postwrite_mismatch",
])
def test_materialization_attacks_roll_back_index_and_worktree_byte_clean(repo, attack):
    mod = _anchor()
    before = mod.snapshot_repository_bytes(repo)
    with pytest.raises(mod.RepositoryMaterializationRefused):
        mod.normalize_repository(repo, failpoint=attack)
    assert mod.snapshot_repository_bytes(repo) == before
    assert _git(repo, "status", "--porcelain").stdout.strip() == ""


def test_guaranteed_malformed_tree_fixture_refuses_even_when_live_index_has_no_tree(repo):
    mod = _anchor()
    malformed = mod.build_dirc_v2_fixture(entries={"tracked.txt": b"one\n"},
                                          tree_extension=b"\xffmalformed")
    with pytest.raises(mod.GitIndexRefused):
        mod.parse_git_index(malformed)


def test_ps51_final_activation_snippet_parses_and_executes_fail_closed():
    powershell = shutil.which("powershell.exe")
    assert powershell
    script = ROOT / "bootstrap" / "galaxy_launcher" / "tofu_bootstrap.ps1"
    cp = subprocess.run([powershell, "-NoLogo", "-NoProfile", "-NonInteractive",
                         "-File", str(script), "-SelfTestFinalActivationSnippet"],
                        text=True, capture_output=True, timeout=30)
    assert cp.returncode == 0, f"stdout={cp.stdout}\nstderr={cp.stderr}"


def test_live_machine_run_script_bytes_metadata_unchanged_and_service_ignores_redirects():
    mod = _anchor()
    live = Path("C:/9to5")
    run = live / "run.ps1"
    assert run.is_file()
    before = (run.read_bytes(), run.stat().st_mtime_ns, run.stat().st_mode)
    record = mod.ProtectedAnchorRecord.discover_for_checkout(live, no_follow=True)
    plan = mod.SingularityAnchor(record).resolve_service_launch("diagnostic")
    assert all(Path(arg).name not in {"run.ps1", "developer_redirect.ps1"} for arg in plan.argv)
    assert (run.read_bytes(), run.stat().st_mtime_ns, run.stat().st_mode) == before
