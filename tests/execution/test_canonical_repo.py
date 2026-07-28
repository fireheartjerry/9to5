"""Native canonical-repository attestation and external-root registration tests."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from platform_core.runtime import canonical_repo as canonical_repo_mod
from platform_core.runtime.canonical_repo import (
    CanonicalRepositoryRefused,
    ExternalRootAuthorityRefused,
    ExternalRootCollision,
    ExternalStateAuthorityIssuer,
    attestCanonicalRepository,
    registerExternalRepositoryRoots,
)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    return result.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "canonical"
    repo.mkdir()
    _git(repo, "-c", "init.defaultBranch=main", "init")
    _git(repo, "config", "user.name", "Kernel Test")
    _git(repo, "config", "user.email", "kernel@example.invalid")
    (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "base")
    return repo


def test_owned_git_fence_requires_canonical_duplicate_free_json() -> None:
    valid = {
        "schema": "galaxy.index-fence/v1",
        "transaction_id": "attempt-1",
        "fence_nonce": "a" * 64,
    }
    canonical_repo_mod._validate_owned_fence(
        canonical_repo_mod.canonical_json_bytes(valid),
        schema="galaxy.index-fence/v1",
        label="canonical index lock",
    )
    duplicated = (
        b'{"fence_nonce":"'
        + b"a" * 64
        + b'","schema":"galaxy.index-fence/v1",'
        + b'"transaction_id":"attempt-1","transaction_id":"attempt-2"}'
    )
    with pytest.raises(CanonicalRepositoryRefused, match="owned fence"):
        canonical_repo_mod._validate_owned_fence(
            duplicated,
            schema="galaxy.index-fence/v1",
            label="canonical index lock",
        )


def test_native_attestation_binds_loose_head_config_index_and_identity(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    attestation = attestCanonicalRepository(repo)
    assert attestation.canonical_root == str(repo.resolve())
    assert attestation.git_common_dir == str((repo / ".git").resolve())
    assert attestation.head_ref == "refs/heads/main"
    assert attestation.head_oid == _git(repo, "rev-parse", "HEAD")
    assert attestation.object_format == "sha1"
    assert attestation.oid_length == 40
    assert attestation.ref_backend == "files"
    assert len(attestation.attestation_digest) == 64
    assert attestCanonicalRepository(repo).metadata_digest == attestation.metadata_digest


def test_attestation_binds_closed_inert_and_derived_metadata(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    git_dir = repo / ".git"
    (git_dir / "cursor").mkdir()
    (git_dir / "cursor" / "state.json").write_bytes(b'{"state":"one"}\n')
    (git_dir / "gk").mkdir()
    (git_dir / "gk" / "config").write_bytes(b"reviewed=true\n")
    (git_dir / "sg-hook-once-seed").write_bytes(b"opaque\n")
    (git_dir / "sg-reviewed-shas").write_bytes(b"reviewed\n")
    (git_dir / "info" / "exclude").write_bytes(b"ignored-by-git-only\n")

    _git(repo, "-c", "pack.writeReverseIndex=true", "repack", "-ad")
    _git(repo, "multi-pack-index", "write")
    _git(repo, "commit-graph", "write", "--reachable", "--split")
    _git(repo, "update-server-info")
    fanout = git_dir / "objects" / "aa"
    fanout.mkdir(exist_ok=True)
    temporary = fanout / "tmp_obj_attestation"
    temporary.write_bytes(b"unreachable-garbage\n")

    first = attestCanonicalRepository(repo)
    assert len(first.object_metadata_digest) == 64
    assert len(first.inert_metadata_digest) == 64

    (git_dir / "cursor" / "state.json").write_bytes(b'{"state":"two"}\n')
    second = attestCanonicalRepository(repo)
    assert second.object_metadata_digest == first.object_metadata_digest
    assert second.inert_metadata_digest != first.inert_metadata_digest
    assert second.attestation_digest != first.attestation_digest

    temporary.write_bytes(b"different-unreachable-garbage\n")
    third = attestCanonicalRepository(repo)
    assert third.object_metadata_digest != second.object_metadata_digest
    assert third.attestation_digest != second.attestation_digest


@pytest.mark.parametrize(
    "relative,kind",
    (
        ("reftable", "file"),
        ("index.lock", "file"),
        ("modules", "directory"),
        ("unknown-authority", "file"),
    ),
)
def test_unknown_or_active_git_metadata_is_refused(
    tmp_path: Path,
    relative: str,
    kind: str,
) -> None:
    repo = _repo(tmp_path)
    target = repo / ".git" / relative
    if kind == "directory":
        target.mkdir()
    else:
        target.write_bytes(b"opaque\n")

    with pytest.raises(CanonicalRepositoryRefused, match="metadata|surface|lock"):
        attestCanonicalRepository(repo)


def test_detached_linked_worktree_registry_is_opaque_but_closed(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    linked = tmp_path / "linked-user-worktree"
    _git(repo, "worktree", "add", "--detach", str(linked), "HEAD")
    goldstone = linked / "outside-goldstone.txt"
    goldstone.write_bytes(b"outside-unchanged\n")
    before = goldstone.stat()

    attestation = attestCanonicalRepository(repo)
    after = goldstone.stat()
    assert len(attestation.worktree_registry_digest) == 64
    assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)

    registry = next((repo / ".git" / "worktrees").iterdir())
    original_head = (registry / "HEAD").read_bytes()
    (registry / "HEAD").write_bytes(b"ref: refs/heads/main\n")
    with pytest.raises(CanonicalRepositoryRefused, match="target branch"):
        attestCanonicalRepository(repo)

    (registry / "HEAD").write_bytes(b"not-a-head\n")
    with pytest.raises(CanonicalRepositoryRefused, match="HEAD"):
        attestCanonicalRepository(repo)

    (registry / "HEAD").write_bytes(original_head)
    (registry / "unknown-authority").write_bytes(b"opaque\n")
    with pytest.raises(CanonicalRepositoryRefused, match="registry metadata"):
        attestCanonicalRepository(repo)

    assert goldstone.read_bytes() == b"outside-unchanged\n"


def test_malformed_or_unpaired_derived_object_sidecar_is_refused(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    _git(repo, "-c", "pack.writeReverseIndex=true", "repack", "-ad")
    pack_dir = repo / ".git" / "objects" / "pack"
    real_reverse_index = next(pack_dir.glob("pack-*.rev"))
    assert attestCanonicalRepository(repo).object_metadata_digest

    original = real_reverse_index.read_bytes()
    real_reverse_index.chmod(0o666)
    real_reverse_index.write_bytes(b"NOT-A-REVERSE-INDEX")
    with pytest.raises(CanonicalRepositoryRefused, match="accelerator|reverse index"):
        attestCanonicalRepository(repo)

    real_reverse_index.write_bytes(original)
    orphan = pack_dir / ("pack-" + "f" * 40 + ".rev")
    orphan.write_bytes(b"RIDX" + b"\x00" * 28)
    with pytest.raises(CanonicalRepositoryRefused, match="paired|sidecar"):
        attestCanonicalRepository(repo)


@pytest.mark.skipif(os.name != "nt", reason="Windows retained-handle boundary")
def test_attestation_refuses_a_rebound_canonical_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _repo(tmp_path)
    held = tmp_path / "canonical-held"
    real_open = canonical_repo_mod.openNativeDirectory
    rebound = False

    def open_then_rebind(path):
        nonlocal rebound
        directory = real_open(path)
        if Path(path) == repo and not rebound:
            repo.rename(held)
            repo.mkdir()
            (repo / "goldstone.txt").write_bytes(b"replacement\n")
            rebound = True
        return directory

    monkeypatch.setattr(canonical_repo_mod, "openNativeDirectory", open_then_rebind)
    with pytest.raises(CanonicalRepositoryRefused, match="identity|drift"):
        attestCanonicalRepository(repo)

    assert rebound is True
    assert (repo / "goldstone.txt").read_bytes() == b"replacement\n"
    assert (held / "tracked.txt").read_text(encoding="utf-8") == "base\n"


def test_linked_worktree_is_not_a_canonical_repository(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    linked = tmp_path / "linked"
    _git(repo, "worktree", "add", "--detach", str(linked), "HEAD")
    assert (linked / ".git").is_file()
    with pytest.raises(CanonicalRepositoryRefused, match="normal .git directory"):
        attestCanonicalRepository(linked)


def test_config_include_is_refused_without_opening_include_target(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    goldstone = tmp_path / "must-not-be-opened.cfg"
    goldstone.write_text("GOLDSTONE", encoding="utf-8")
    with (repo / ".git" / "config").open("a", encoding="utf-8") as handle:
        handle.write(f'\n[include]\n\tpath = {goldstone}\n')
    before = goldstone.stat()
    with pytest.raises(CanonicalRepositoryRefused, match="include"):
        attestCanonicalRepository(repo)
    after = goldstone.stat()
    assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)


def test_inert_vscode_merge_base_is_allowed_as_a_git_multivar(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    with (repo / ".git" / "config").open("a", encoding="utf-8") as handle:
        handle.write(
            '\n[branch "main"]\n'
            "\tvscode-merge-base = refs/remotes/origin/main\n"
            "\tvscode-merge-base = refs/remotes/origin/previous-main\n"
        )

    attestation = attestCanonicalRepository(repo)
    assert len(attestation.config_digest) == 64


def test_only_redundant_internal_default_hooks_path_is_allowed(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _git(repo, "config", "core.hooksPath", str(repo / ".git" / "hooks"))
    assert attestCanonicalRepository(repo).config_digest

    _git(repo, "config", "core.hooksPath", str(tmp_path / "external-hooks"))
    with pytest.raises(CanonicalRepositoryRefused, match="hooksPath|hookspath|hook"):
        attestCanonicalRepository(repo)


@pytest.mark.parametrize(
    "poison",
    (
        '[credential "https://example.invalid"]\n\thelper = !echo owned',
        '[core]\n\tattributesFile = C:/outside/attributes',
        '[gpg]\n\tprogram = C:/outside/signer.exe',
        '[alias]\n\tpwn = !echo owned',
        '[protocol "file"]\n\tallow = always',
    ),
)
def test_executable_or_external_config_surfaces_are_refused(
    tmp_path: Path,
    poison: str,
) -> None:
    repo = _repo(tmp_path)
    with (repo / ".git" / "config").open("a", encoding="utf-8") as handle:
        handle.write("\n" + poison + "\n")
    with pytest.raises(CanonicalRepositoryRefused, match="config|helper|section|key"):
        attestCanonicalRepository(repo)


def test_packed_only_target_ref_is_refused_but_matching_shadow_is_allowed(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "pack-refs", "--all")
    with pytest.raises(CanonicalRepositoryRefused, match="loose target ref"):
        attestCanonicalRepository(repo)

    loose = repo / ".git" / "refs" / "heads" / "main"
    loose.parent.mkdir(parents=True, exist_ok=True)
    loose.write_text(head + "\n", encoding="ascii")
    assert attestCanonicalRepository(repo).head_oid == head

    packed = repo / ".git" / "packed-refs"
    packed.write_text(
        packed.read_text(encoding="ascii").replace(head, "f" * 40),
        encoding="ascii",
    )
    with pytest.raises(CanonicalRepositoryRefused, match="packed target ref disagrees"):
        attestCanonicalRepository(repo)


def test_object_store_reparse_boundary_is_refused_without_touching_outside(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    outside = tmp_path / "outside-objects"
    outside.mkdir()
    goldstone = outside / "goldstone.txt"
    goldstone.write_bytes(b"outside-unchanged")
    junction = repo / ".git" / "objects" / "fe"
    if sys.platform == "win32":
        created = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode == 0
    else:
        try:
            junction.symlink_to(outside, target_is_directory=True)
            created = True
        except OSError:
            created = False
    if not created:
        pytest.skip("directory reparse points are unavailable for this account")

    with pytest.raises(CanonicalRepositoryRefused, match="reparse|mount"):
        attestCanonicalRepository(repo)
    assert goldstone.read_bytes() == b"outside-unchanged"


@pytest.mark.parametrize(
    "relative",
    ["objects/info/alternates", "objects/info/http-alternates", "shallow", "info/grafts"],
)
def test_lazy_or_replacement_object_sources_are_refused(
    tmp_path: Path, relative: str
) -> None:
    repo = _repo(tmp_path)
    poisoned = repo / ".git" / Path(relative)
    poisoned.parent.mkdir(parents=True, exist_ok=True)
    poisoned.write_text(str(tmp_path / "outside-objects"), encoding="utf-8")
    with pytest.raises(CanonicalRepositoryRefused, match="unsupported Git metadata"):
        attestCanonicalRepository(repo)


def test_missing_promisor_blob_never_invokes_transport_or_credential_helper(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    blob_oid = _git(repo, "rev-parse", "HEAD:tracked.txt")
    loose_blob = repo / ".git" / "objects" / blob_oid[:2] / blob_oid[2:]
    os.chmod(loose_blob, 0o600)
    loose_blob.unlink()
    goldstone = tmp_path / "credential-helper-ran.txt"
    with (repo / ".git" / "config").open("a", encoding="utf-8") as stream:
        stream.write(
            "\n[remote \"origin\"]\n"
            "\turl = https://example.invalid/repository.git\n"
            "\tpromisor = true\n"
            "\tpartialclonefilter = blob:none\n"
            "[credential]\n"
            f"\thelper = !powershell -NoProfile -Command Set-Content '{goldstone}' owned\n"
        )

    with pytest.raises(CanonicalRepositoryRefused, match="promisor|helper|config"):
        attestCanonicalRepository(repo)

    assert not goldstone.exists()


def test_canonical_info_attributes_and_filter_process_are_never_executed(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    goldstone = tmp_path / "filter-process-ran.txt"
    (repo / ".git" / "info" / "attributes").write_text(
        "* filter=host-command\n",
        encoding="utf-8",
    )
    with (repo / ".git" / "config").open("a", encoding="utf-8") as stream:
        stream.write(
            "\n[filter \"host-command\"]\n"
            f"\tprocess = powershell -NoProfile -Command Set-Content '{goldstone}' owned\n"
        )

    with pytest.raises(CanonicalRepositoryRefused, match="config|filter|metadata"):
        attestCanonicalRepository(repo)

    assert not goldstone.exists()


@pytest.mark.parametrize(
    "mode",
    (
        "assume-unchanged",
        "skip-worktree",
        "split-index",
        "intent-to-add",
    ),
)
def test_nonordinary_index_modes_are_refused_before_lease_creation(
    tmp_path: Path,
    mode: str,
) -> None:
    repo = _repo(tmp_path)
    if mode == "assume-unchanged":
        _git(repo, "update-index", "--assume-unchanged", "tracked.txt")
    elif mode == "skip-worktree":
        _git(repo, "update-index", "--skip-worktree", "tracked.txt")
    elif mode == "split-index":
        _git(repo, "update-index", "--split-index")
    else:
        (repo / "intent.txt").write_text("intent\n", encoding="utf-8")
        _git(repo, "add", "--intent-to-add", "intent.txt")

    with pytest.raises(CanonicalRepositoryRefused, match="canonical index"):
        attestCanonicalRepository(repo)


def test_external_roots_are_authority_bound_external_and_replay_exact(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    attestation = attestCanonicalRepository(repo)
    capability = object()
    issuer = ExternalStateAuthorityIssuer(
        domain_root=tmp_path / "installed-controller" / "state",
        controller_generation=7,
        process_capability=capability,
    )
    authority = issuer.issue(
        attestation=attestation,
        request_id="root-request-001",
        process_capability=capability,
    )
    assert "process_capability" not in authority.toDict()

    roots = registerExternalRepositoryRoots(
        attestation=attestation,
        authority=authority,
        issuer=issuer,
    )
    assert not os.path.commonpath((roots.controller_root, str(repo))).lower() == str(repo).lower()
    assert Path(roots.candidate_checkout_root).is_dir()
    assert Path(roots.verification_checkout_root).is_dir()
    assert registerExternalRepositoryRoots(
        attestation=attestation,
        authority=authority,
        issuer=issuer,
    ) == roots
    manifest = json.loads(Path(roots.manifest_path).read_text(encoding="utf-8"))
    assert manifest["repository_id"] == attestation.repository_id
    assert manifest["activation_authority"] is False


def test_external_root_refuses_inside_canonical_or_foreign_authority(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    attestation = attestCanonicalRepository(repo)
    capability = object()
    inside = ExternalStateAuthorityIssuer(
        domain_root=repo / "state" / "controller",
        controller_generation=1,
        process_capability=capability,
    )
    authority = inside.issue(
        attestation=attestation,
        request_id="root-request-inside",
        process_capability=capability,
    )
    with pytest.raises(ExternalRootAuthorityRefused, match="outside canonical"):
        registerExternalRepositoryRoots(
            attestation=attestation,
            authority=authority,
            issuer=inside,
        )

    other = ExternalStateAuthorityIssuer(
        domain_root=tmp_path / "other-controller",
        controller_generation=1,
        process_capability=object(),
    )
    with pytest.raises(ExternalRootAuthorityRefused, match="live issuer"):
        registerExternalRepositoryRoots(
            attestation=attestation,
            authority=authority,
            issuer=other,
        )


def test_existing_foreign_root_manifest_is_never_adopted(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    attestation = attestCanonicalRepository(repo)
    capability = object()
    domain = tmp_path / "installed-controller" / "state"
    issuer = ExternalStateAuthorityIssuer(
        domain_root=domain,
        controller_generation=1,
        process_capability=capability,
    )
    authority = issuer.issue(
        attestation=attestation,
        request_id="root-request-001",
        process_capability=capability,
    )
    foreign = domain / "repositories" / attestation.repository_id
    foreign.mkdir(parents=True)
    (foreign / "root-manifest.json").write_text('{"foreign":true}', encoding="utf-8")
    with pytest.raises(ExternalRootCollision):
        registerExternalRepositoryRoots(
            attestation=attestation,
            authority=authority,
            issuer=issuer,
        )
    assert (foreign / "root-manifest.json").read_text(encoding="utf-8") == '{"foreign":true}'
