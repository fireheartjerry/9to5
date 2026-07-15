# Accretion Context Virtualization Plane R1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-only, immutable, causally closed context-virtualization plane that preserves exact obligations across arbitrarily long runs while compiling safe provider-specific packets for Claude, Codex, and Ollama.

**Architecture:** New focused modules under `platform_core/context/` own canonical serialization, content-addressed pages, an append-only SQLite ledger, deterministic cuts/reduction, authenticated history, exact pins, lineage, packets, paging, and qualification. Existing orchestration and memory modules remain public facades/producers. Persistent segment, link-cut, and Li Chao backends are shadow-only and can never replace the flat replay, parent-chain, or exact/Pareto cepheids.

**Tech Stack:** Python 3.12, standard-library `dataclasses`, `hashlib`, `json`, `sqlite3`, `pathlib`, existing `platform_core.core.fsio`, pytest, Hypothesis when already installed with deterministic seeded fallback, Ruff, mypy, and local benchmark/replay fixtures.

**Authoritative spec:** `docs/superpowers/specs/2026-07-13-galaxy-r3-accretion-context-virtualization-r1.md`

---

## 1. Locked file map

### 1.1 New production modules

| File | One responsibility |
|---|---|
| `platform_core/context/__init__.py` | stable public exports only |
| `platform_core/context/contracts.py` | frozen enums, dataclasses, exceptions, and closed identities |
| `platform_core/context/canonical.py` | canonical JSON and domain-separated digest functions |
| `platform_core/context/blob_store.py` | immutable content-addressed byte storage |
| `platform_core/context/schema.py` | SQLite DDL and append-only triggers |
| `platform_core/context/store.py` | transactional ledger, cursor checks, root CAS, and reads |
| `platform_core/context/reducer.py` | causal-cut validation, deterministic reduction, and exact pins |
| `platform_core/context/history.py` | flat cepheid and authenticated append-only Merkle accumulator/MMR |
| `platform_core/context/dependencies.py` | exact typed causal-DAG closure |
| `platform_core/context/lineage.py` | parent-chain/persistent-stack active-lineage baseline |
| `platform_core/context/tokens.py` | provider-specific exact-or-conservative token accounting |
| `platform_core/context/packets.py` | dependency-closed portfolio compilation and completeness receipts |
| `platform_core/context/independence.py` | transitive ancestry comparison and BIF independence basis |
| `platform_core/context/selectors.py` | exhaustive and sorted-Pareto selectors |
| `platform_core/context/compaction.py` | publish-before-evict Evaporation transaction |
| `platform_core/context/paging.py` | opaque handles, bounded recall, and clean-epoch decisions |
| `platform_core/context/telemetry.py` | workload-shape, page-fault, and backend-trial receipts |
| `platform_core/context/ingress.py` | adapters from executor, retrieval, repository, and protected receipts |
| `platform_core/context/session.py` | provider-session binding and freshness predicate |
| `platform_core/context/retention.py` | immutable-root reachability and guarded blob collection |
| `platform_core/context/router.py` | closed legacy/observe/shadow/qualified backend routing |
| `platform_core/context/qualification.py` | exact differential replay and Quark P2 crossover decisions |
| `platform_core/context/shadow/segment_tree.py` | persistent interval candidate; never canonical |
| `platform_core/context/shadow/link_cut.py` | dynamic-forest path-aggregate candidate; never canonical |
| `platform_core/context/shadow/li_chao.py` | affine complete-packet selector candidate; never canonical |

### 1.2 Existing modules changed

| File | Planned change |
|---|---|
| `platform_core/core/fsio.py` | add crash-safe `atomicWriteBytes` |
| `platform_core/app_config/context.py` | new frozen context configuration domain |
| `platform_core/app_config/settings.py` | register `ContextCfg` |
| `platform_core/app_config/__init__.py` | expose the new config submodule |
| `platform_core/app_config/paths.py` | add local context root/database/blob/replay paths |
| `platform_core/orchestration/step_sink.py` | dark ingress fanout after journal/trajectory observation |
| `platform_core/orchestration/compaction.py` | preserve facade and add dark/qualified Evaporation routing |
| `platform_core/orchestration/brain_io.py` | mark blind truncation as legacy-only; reject it for hard packets |
| `platform_core/orchestration/step_resume.py` | enforce provider-session freshness binding |
| `platform_core/orchestration/llm_navigation.py` | adapt exact code candidates into typed page candidates |
| `memory/retrievals/core.py` | wrap retrieval results with source/provenance generations |
| `memory/retrievals/render.py` | preserve legacy functions; delegate qualified packet rendering |
| `platform_core/ops/retention.py` | reachability-driven context GC after leases exist |
| `tools/repo_map.py` output | regenerate `AGENTS.md` and `.repo-map.json` after implementation |

### 1.3 New tests and fixtures

All Accretion tests live under `tests/context/`. Deterministic generated fixtures
live under `tests/context/fixtures/`; benchmarks write only to pytest temporary
directories or `state/context/benchmarks/` when explicitly invoked.

---

## 2. Global implementation rules

1. No task may activate a live backend. All new flags default false.
2. Every optimized data structure is introduced after its simpler cepheid.
3. Immutable source tables reject update/delete at the database layer.
4. Tests never use the real `state/` tree, browser cookies, network, or paid APIs.
5. Fixed-point integers replace floating-point utility in canonical decisions.
6. Any unknown schema, edge kind, source generation, digest, authority reference,
   tokenizer, or required proof fails closed.
7. Context-store failure cannot be reinterpreted as an empty valid context.
8. Existing legacy behavior remains byte-for-byte unchanged while all Accretion
   flags are false, except for additive observation telemetry whose failures are
   explicitly isolated.
9. Each task commits only its listed files. Existing unrelated user changes remain
   untouched.
10. Run `python tools/dev.py check <file>` for every changed Python file and the
    task-specific pytest command before committing.
11. Production modules under `platform_core/context/` import
    `platform_core.app_config` rather than the root `config` facade; tests may use
    the compatibility facade.

---

### Task 1: Add the frozen context configuration domain and package shell

**Files:**
- Create: `platform_core/app_config/context.py`
- Create: `platform_core/context/__init__.py`
- Modify: `platform_core/app_config/settings.py`
- Modify: `platform_core/app_config/__init__.py`
- Modify: `platform_core/app_config/paths.py`
- Test: `tests/context/test_config.py`

- [ ] **Step 1: Write the failing configuration tests**

```python
import config
from platform_core.app_config import _env
from platform_core.app_config.paths import buildPathsCfg


def test_context_flags_are_dark_by_default():
    assert config.ACCRETION_OBSERVE is False
    assert config.ACCRETION_SHADOW is False
    assert config.ACCRETION_QUALIFIED is False
    assert config.ACCRETION_SEGMENT_SHADOW is False
    assert config.ACCRETION_LINK_CUT_SHADOW is False
    assert config.ACCRETION_LI_CHAO_SHADOW is False


def test_context_paths_are_local_and_beneath_state(monkeypatch, tmp_path):
    monkeypatch.setattr(_env, "_PROCESS_PROJECT_ROOT", str(tmp_path))
    paths = buildPathsCfg()
    assert paths.CONTEXT_ROOT == tmp_path / "state" / "context"
    assert paths.CONTEXT_DB_PATH == paths.CONTEXT_ROOT / "context.db"
    assert paths.CONTEXT_BLOB_DIR == paths.CONTEXT_ROOT / "blobs"
    assert paths.CONTEXT_REPLAY_DIR == paths.CONTEXT_ROOT / "replay"
```

- [ ] **Step 2: Run the tests and verify the new constants are absent**

Run: `python -m pytest tests/context/test_config.py -q`  
Expected: FAIL because `ContextCfg` and the context paths do not exist.

- [ ] **Step 3: Implement `ContextCfg` with closed defaults**

```python
from __future__ import annotations

from dataclasses import dataclass, field

from platform_core.app_config._env import _envBool, _envInt


@dataclass(frozen=True)
class ContextCfg:
    ACCRETION_OBSERVE: bool = field(default_factory=lambda: _envBool("ACCRETION_OBSERVE", False))
    ACCRETION_SHADOW: bool = field(default_factory=lambda: _envBool("ACCRETION_SHADOW", False))
    ACCRETION_QUALIFIED: bool = field(default_factory=lambda: _envBool("ACCRETION_QUALIFIED", False))
    ACCRETION_SEGMENT_SHADOW: bool = field(default_factory=lambda: _envBool("ACCRETION_SEGMENT_SHADOW", False))
    ACCRETION_LINK_CUT_SHADOW: bool = field(default_factory=lambda: _envBool("ACCRETION_LINK_CUT_SHADOW", False))
    ACCRETION_LI_CHAO_SHADOW: bool = field(default_factory=lambda: _envBool("ACCRETION_LI_CHAO_SHADOW", False))
    ACCRETION_MAX_PARENT_FANOUT: int = field(default_factory=lambda: _envInt("ACCRETION_MAX_PARENT_FANOUT", 64))
    ACCRETION_MAX_RECALLS_PER_EPOCH: int = field(default_factory=lambda: _envInt("ACCRETION_MAX_RECALLS_PER_EPOCH", 8))
    ACCRETION_RECALL_RESERVE_TOKENS: int = field(default_factory=lambda: _envInt("ACCRETION_RECALL_RESERVE_TOKENS", 2048))
```

Register `context: ContextCfg` in `Settings`, add `context` to `_DOMAINS`, build it
in `buildSettings`, and expose the `context` submodule in `_SUBMODULES`. Add
`CONTEXT_ROOT`, `CONTEXT_DB_PATH`, `CONTEXT_BLOB_DIR`, and
`CONTEXT_REPLAY_DIR` to `PathsCfg`, `buildPathsCfg`, and `requiredDirs`.

- [ ] **Step 4: Add the package shell without premature contracts**

```python
"""Accretion context-virtualization internals."""

__all__: list[str] = []
```

Do not create placeholder contract classes. Task 3 adds the complete frozen
contracts and updates this export surface atomically with their tests.

- [ ] **Step 5: Run the focused configuration and registry checks**

Run: `python -m pytest tests/context/test_config.py tests/platform/test_config_bootstrap.py -q`  
Expected: PASS.

- [ ] **Step 6: Commit**

```text
git add platform_core/app_config/context.py platform_core/app_config/settings.py
git add platform_core/app_config/__init__.py platform_core/app_config/paths.py
git add platform_core/context/__init__.py
git add tests/context/test_config.py
git commit -m "feat(context): add dark Accretion configuration"
```

---

### Task 2: Instrument the incumbent context path without changing behavior

**Files:**
- Create: `platform_core/context/telemetry.py`
- Modify: `platform_core/orchestration/compaction.py`
- Modify: `platform_core/orchestration/brain_io.py`
- Modify: `platform_core/orchestration/step_resume.py`
- Modify: `memory/retrievals/render.py`
- Test: `tests/context/test_incumbent_telemetry.py`
- Test: `tests/context/test_observe_off_invariance.py`

- [ ] **Step 1: Capture byte-for-byte off-invariance before adding observation**

```python
import hashlib

import pytest

import config
from memory.retrievals.render import render_solutions
from platform_core.orchestration.brain_io import _fitUserToCtx
from platform_core.orchestration.compaction import fitOrCompact


@pytest.mark.parametrize("enabled", [False])
def test_observe_off_preserves_incumbent_bytes(monkeypatch, enabled):
    monkeypatch.setattr(config, "ACCRETION_OBSERVE", enabled, raising=False)
    user = "old\n" * 10_000 + "new\n"
    before = hashlib.sha256(_fitUserToCtx("sys", user, 1024, 128).encode()).hexdigest()
    after = hashlib.sha256(_fitUserToCtx("sys", user, 1024, 128).encode()).hexdigest()
    assert after == before
    assert fitOrCompact("sys", "small", 8192, 2048, summarize=None) == "small"
    assert render_solutions([]) == ""
```

- [ ] **Step 2: Run the invariance test before editing production callers**

Run: `python -m pytest tests/context/test_observe_off_invariance.py -q`  
Expected: PASS after Task 1 configuration exists; record the fixture digests in
the test as explicit constants before proceeding.

- [ ] **Step 3: Implement an isolated append-only observation sink**

```python
import os
import threading

from platform_core import app_config as config


class ObservationKind(str, Enum):
    BRAIN_TRUNCATE = "brain_truncate"
    COMPACTION_ATTEMPT = "compaction_attempt"
    RETRIEVAL_RENDER = "retrieval_render"
    RESUME_SESSION_REUSE = "resume_session_reuse"


@dataclass(frozen=True, slots=True)
class ContextObservation:
    observation_id: str
    kind: ObservationKind
    run_id: str | None
    input_bytes: int
    output_bytes: int
    estimated_tokens: int
    elapsed_us: int
    dimensions: tuple[tuple[str, str | int | bool], ...]


_OBSERVATION_LOCK = threading.Lock()


def emit_observation(observation: ContextObservation, *, root: Path | None = None) -> None:
    if not config.ACCRETION_OBSERVE:
        return
    try:
        target = (root or config.CONTEXT_REPLAY_DIR) / f"incumbent-observations-{os.getpid()}.jsonl"
        with _OBSERVATION_LOCK:
            jsonl_io.appendRecord(target, dataclasses.asdict(observation))
    except Exception as exc:  # observation must not change incumbent behavior
        LOG.warning("context observation failed (ignored): %s", exc)
```

Use a closed `ObservationKind` enum rather than a free-form string. The kinds are
`brain_truncate`, `compaction_attempt`,
`retrieval_render`, and `resume_session_reuse`. Record sizes, budget, selected
item count, first-overbudget position, provider/session generation when known,
and elapsed microseconds. Never record raw prompt text, secrets, paths, or page
content. Each record has a nonempty immutable observation ID. One file per
process avoids cross-process append/rotation races; a module lock serializes
threads within that process. Qualification aggregates files by immutable
observation ID.

- [ ] **Step 4: Add observation calls after incumbent results are fixed**

In each brownfield function, compute and return the incumbent output exactly as
before. Emit in a `finally`-isolated helper after the result is determined. An
observation exception must not alter the returned bytes, raised exception, log
classification, or session choice.

- [ ] **Step 5: Test observation shape and failure isolation**

```python
def test_observation_failure_does_not_change_result(monkeypatch):
    monkeypatch.setattr(config, "ACCRETION_OBSERVE", True)
    monkeypatch.setattr("platform_core.context.telemetry.jsonl_io.appendRecord", lambda *_: (_ for _ in ()).throw(OSError("disk")))
    assert _fitUserToCtx("sys", "payload", 8192, 2048) == "payload"


def test_observations_contain_no_raw_content(observation_records):
    forbidden = {"prompt", "content", "raw", "path", "secret"}
    record = observation_records[0]
    assert record["observation_id"]
    assert not forbidden.intersection(record)
```

- [ ] **Step 6: Run the incumbent and affected suites**

Run: `python -m pytest tests/context/test_incumbent_telemetry.py tests/context/test_observe_off_invariance.py tests/orchestration/test_compaction.py tests/execution/test_step_resume.py tests/evolution/test_retrieval.py -q`  
Expected: PASS with identical off-mode fixture digests.

- [ ] **Step 7: Commit**

```text
git add platform_core/context/telemetry.py
git add platform_core/orchestration/compaction.py platform_core/orchestration/brain_io.py
git add platform_core/orchestration/step_resume.py memory/retrievals/render.py
git add tests/context/test_incumbent_telemetry.py tests/context/test_observe_off_invariance.py
git commit -m "feat(context): observe incumbent context workloads"
```

---

### Task 3: Freeze canonical contracts and domain-separated hashing

**Files:**
- Create: `platform_core/context/contracts.py`
- Create: `platform_core/context/canonical.py`
- Modify: `platform_core/context/__init__.py`
- Test: `tests/context/test_contracts.py`
- Test: `tests/context/test_canonical.py`

- [ ] **Step 1: Write contract and canonicalization tests**

```python
import dataclasses
import math

import pytest

from platform_core.context.canonical import canonical_bytes, digest
from platform_core.context.contracts import (
    CausalParent,
    ContextEvent,
    EventKind,
    SourceCursor,
    Taint,
    join_taint,
)


def test_event_contract_is_frozen_and_parent_order_is_canonical():
    p1 = CausalParent("a", 1, 2, "sha256:a")
    p2 = CausalParent("b", 1, 1, "sha256:b")
    ev = ContextEvent(
        event_id="e1", run_id="r1", kind=EventKind.ACCEPTANCE_ADDED,
        source=SourceCursor("kernel", 1, 3, "sha256:root"),
        parents=(p2, p1), payload_ref="sha256:payload",
        authority_ref="sha256:authority", origin_closure_ref="sha256:origin",
        taint=Taint.PROTECTED, sensitivity="run_private",
    )
    assert [p.source_id for p in ev.parents] == ["a", "b"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        ev.run_id = "changed"


def test_canonical_bytes_reject_float_and_are_order_independent():
    assert canonical_bytes({"b": 2, "a": 1}) == canonical_bytes({"a": 1, "b": 2})
    with pytest.raises(TypeError):
        canonical_bytes({"score": 0.5})
    with pytest.raises(TypeError):
        canonical_bytes({"score": math.nan})


def test_digest_is_domain_separated():
    body = {"schema_version": 1, "value": 7}
    assert digest("event", body) != digest("page", body)
    assert digest("event", body).startswith("sha256:")


def test_taint_join_is_monotone_and_never_cleans():
    assert join_taint(Taint.PROTECTED, Taint.UNTRUSTED) is Taint.UNTRUSTED
    assert join_taint(Taint.DERIVED_UNVERIFIED, Taint.TRUSTED_LOCAL) is Taint.DERIVED_UNVERIFIED
```

- [ ] **Step 2: Run and observe missing/full-contract failures**

Run: `python -m pytest tests/context/test_contracts.py tests/context/test_canonical.py -q`  
Expected: FAIL on missing enums, records, and digest functions.

- [ ] **Step 3: Implement the closed contracts**

Define frozen, slot-backed dataclasses with validation in `__post_init__`:

```python
class EventKind(str, Enum):
    MISSION_REVISION = "mission_revision"
    ACCEPTANCE_ADDED = "acceptance_added"
    ACCEPTANCE_DISCHARGED = "acceptance_discharged"
    REVOCATION_ADVANCED = "revocation_advanced"
    POLICY_ADVANCED = "policy_advanced"
    REPOSITORY_SNAPSHOT = "repository_snapshot"
    EXECUTION_OBSERVED = "execution_observed"
    VERIFIER_FAILED = "verifier_failed"
    VERIFIER_PASSED = "verifier_passed"
    ARTIFACT_PERSISTED = "artifact_persisted"
    CONTAMINATION_FOUND = "contamination_found"
    ATTEMPT_SUPERSEDED = "attempt_superseded"


class Taint(str, Enum):
    PROTECTED = "protected"
    TRUSTED_LOCAL = "trusted_local"
    DERIVED_UNVERIFIED = "derived_unverified"
    UNTRUSTED = "untrusted"


TAINT_ORDER = {
    Taint.PROTECTED: 0,
    Taint.TRUSTED_LOCAL: 1,
    Taint.DERIVED_UNVERIFIED: 2,
    Taint.UNTRUSTED: 3,
}


def join_taint(*values: Taint) -> Taint:
    if not values:
        raise ValueError("taint join requires at least one value")
    return max(values, key=TAINT_ORDER.__getitem__)


@dataclass(frozen=True, slots=True, order=True)
class CausalParent:
    source_id: str
    generation: int
    sequence: int
    event_digest: str


@dataclass(frozen=True, slots=True)
class SourceCursor:
    source_id: str
    generation: int
    sequence: int
    stream_root: str


@dataclass(frozen=True, slots=True)
class ContextEvent:
    event_id: str
    run_id: str
    kind: EventKind
    source: SourceCursor
    parents: tuple[CausalParent, ...]
    payload_ref: str
    authority_ref: str
    origin_closure_ref: str
    taint: Taint
    sensitivity: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "parents", tuple(sorted(self.parents)))
```

Also define `ContextCut`, `HardPin`, `SummaryArtifact`, `PageRef`,
`PacketCandidate`, `ContextPacket`, `CompletenessReceipt`, `PageHandle`,
`RootPublicationReceipt`, `BackendTrialReceipt`, `ContextUnsatisfiable`, and
`ContextInvariantError` exactly with the fields in spec sections 4–6. Validate
nonempty opaque IDs, nonnegative integer generations/sequences, digest prefixes,
closed sensitivity values, and duplicate parent/pin/page rejection.

Update `platform_core/context/__init__.py` in the same step to export only these
complete contracts. No partially defined public class is committed.

- [ ] **Step 4: Implement canonical bytes and digests**

```python
def _primitive(value):
    if dataclasses.is_dataclass(value):
        return _primitive(dataclasses.asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): _primitive(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_primitive(v) for v in value]
    if isinstance(value, float):
        raise TypeError("canonical context objects forbid floats")
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"unsupported canonical type: {type(value).__name__}")


def canonical_bytes(value) -> bytes:
    return json.dumps(
        _primitive(value), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")


def digest(domain: str, value) -> str:
    if not domain or "\x00" in domain:
        raise ValueError("invalid digest domain")
    body = b"9to5-accretion-v1\x00" + domain.encode("ascii") + b"\x00" + canonical_bytes(value)
    return "sha256:" + hashlib.sha256(body).hexdigest()
```

- [ ] **Step 5: Run contract tests and static checks**

Run: `python -m pytest tests/context/test_contracts.py tests/context/test_canonical.py -q`  
Expected: PASS.  
Run: `python tools/dev.py check platform_core/context/contracts.py`  
Expected: PASS.

- [ ] **Step 6: Commit**

```text
git add platform_core/context/contracts.py platform_core/context/canonical.py
git add platform_core/context/__init__.py
git add tests/context/test_contracts.py tests/context/test_canonical.py
git commit -m "feat(context): freeze canonical Accretion contracts"
```

---

### Task 4: Add crash-safe immutable blob storage

**Files:**
- Modify: `platform_core/core/fsio.py`
- Create: `platform_core/context/blob_store.py`
- Test: `tests/execution/test_fsio.py`
- Test: `tests/context/test_blob_store.py`

- [ ] **Step 1: Write byte-atomicity and immutability tests**

```python
from pathlib import Path

import pytest

from platform_core.context.blob_store import (
    BlobCollision,
    BlobStore,
    SecretDisposition,
    SecretPersistenceDenied,
    require_under_root,
)
from platform_core.context.contracts import ContextInvariantError
from platform_core.core.fsio import atomicWriteBytes


def test_atomic_write_bytes_round_trip(tmp_path):
    p = tmp_path / "nested" / "value.bin"
    atomicWriteBytes(p, b"\x00payload\xff", durable=True)
    assert p.read_bytes() == b"\x00payload\xff"


def test_blob_store_is_content_addressed_and_idempotent(tmp_path):
    store = BlobStore(tmp_path)
    first = store.put(
        b"payload", media_type="text/plain", sensitivity="run_private",
        secret_disposition=SecretDisposition.CLEARED,
    )
    second = store.put(
        b"payload", media_type="text/plain", sensitivity="run_private",
        secret_disposition=SecretDisposition.CLEARED,
    )
    assert first == second
    assert store.get(first.digest) == b"payload"
    assert str(store.path_for(first.digest)).startswith(str(tmp_path))


def test_existing_wrong_bytes_are_quarantined(tmp_path, monkeypatch):
    store = BlobStore(tmp_path)
    ref = store.ref_for(b"expected", "text/plain", "run_private")
    path = store.path_for(ref.digest)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"tampered")
    with pytest.raises(BlobCollision):
        store.put(
            b"expected", media_type="text/plain", sensitivity="run_private",
            secret_disposition=SecretDisposition.CLEARED,
        )


def test_plaintext_secret_is_never_persisted(tmp_path):
    store = BlobStore(tmp_path)
    with pytest.raises(SecretPersistenceDenied):
        store.put(
            b"token=super-secret", media_type="text/plain", sensitivity="secret",
            secret_disposition=SecretDisposition.SECRET,
        )
    assert not any(path.is_file() for path in tmp_path.rglob("*"))


def test_unknown_secret_classification_fails_toward_non_persistence(tmp_path):
    store = BlobStore(tmp_path)
    with pytest.raises(SecretPersistenceDenied):
        store.put(
            b"unclassified", media_type="application/octet-stream",
            sensitivity="run_private", secret_disposition=SecretDisposition.UNKNOWN,
        )
    assert not any(path.is_file() for path in tmp_path.rglob("*"))


def test_outside_path_is_rejected(tmp_path):
    root = tmp_path / "blobs"
    outside = tmp_path / "outside" / "value"
    with pytest.raises(ContextInvariantError):
        require_under_root(root, outside)
```

- [ ] **Step 2: Run and verify missing implementations**

Run: `python -m pytest tests/context/test_blob_store.py tests/execution/test_fsio.py -q`  
Expected: FAIL because `atomicWriteBytes` and `BlobStore` are absent.

- [ ] **Step 3: Add `atomicWriteBytes` using the existing unique-temp discipline**

Implement the byte equivalent of `atomicWriteText`: create parent directories,
write through `_uniqueTmp`, flush and optionally `fsync`, call `_atomicReplace`,
best-effort fsync the directory, and always remove a surviving temporary file in
`finally`. Do not shell out or cross filesystems.

- [ ] **Step 4: Implement `BlobStore`**

```python
from enum import Enum


class SecretDisposition(str, Enum):
    CLEARED = "cleared"
    SECRET = "secret"
    UNKNOWN = "unknown"


class BlobStore:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def ref_for(self, data: bytes, media_type: str, sensitivity: str) -> PageRef:
        prefix = b"9to5-accretion-v1\x00page-bytes\x00" + media_type.encode("utf-8") + b"\x00"
        hasher = hashlib.sha256()
        hasher.update(prefix)
        hasher.update(data)
        d = "sha256:" + hasher.hexdigest()
        return PageRef(digest=d, media_type=media_type, byte_length=len(data), sensitivity=sensitivity)

    def path_for(self, value_digest: str) -> Path:
        hex_digest = require_sha256(value_digest)
        return self.root / "sha256" / hex_digest[:2] / hex_digest[2:]

    def put(
        self,
        data: bytes,
        media_type: str,
        sensitivity: str,
        secret_disposition: SecretDisposition,
    ) -> PageRef:
        if (
            secret_disposition is not SecretDisposition.CLEARED
            or sensitivity in {"credential", "secret"}
            or deterministic_secret_scan(data)
        ):
            raise SecretPersistenceDenied("plaintext secret pages are not persisted")
        ref = self.ref_for(data, media_type, sensitivity)
        target = self.path_for(ref.digest)
        require_no_symlink_escape(self.root, target)
        if target.exists():
            current = target.read_bytes()
            if current != data:
                raise BlobCollision(ref.digest)
            return ref
        atomicWriteBytes(target, data, durable=True)
        if target.read_bytes() != data:
            raise BlobCollision(ref.digest)
        return ref
```

`get` verifies the digest and byte length before returning. `delete_unreachable`
accepts an explicit set of verified digests and refuses paths outside `root`.
`SecretDisposition` is mandatory and has no permissive default. The deterministic
scanner is defense in depth, not the classifier or an authority source.
Secret-bearing or unknown ingress stores only a digest/protected source handle or
a deterministically redacted derived page; only independently classified
`CLEARED` bytes may call `put`. Every path
operation resolves existing parents and rejects symlink/reparse-point escape
before opening or replacing a file.

- [ ] **Step 5: Run focused tests and checks**

Run: `python -m pytest tests/context/test_blob_store.py tests/execution/test_fsio.py -q`  
Expected: PASS.  
Run: `python tools/dev.py check platform_core/context/blob_store.py`  
Expected: PASS.

- [ ] **Step 6: Commit**

```text
git add platform_core/core/fsio.py platform_core/context/blob_store.py
git add tests/execution/test_fsio.py tests/context/test_blob_store.py
git commit -m "feat(context): add immutable content-addressed blobs"
```

---

### Task 5: Build the append-only SQLite ledger and root CAS

**Files:**
- Create: `platform_core/context/schema.py`
- Create: `platform_core/context/store.py`
- Test: `tests/context/test_store_schema.py`
- Test: `tests/context/test_store_transactions.py`

- [ ] **Step 1: Write append-only and CAS tests**

```python
import sqlite3

import pytest

from platform_core.context.store import ContextStore, RootConflict


def test_event_tables_reject_update_and_delete(store, event):
    store.append_event(event)
    with pytest.raises(sqlite3.IntegrityError):
        store.raw_execute("UPDATE context_events SET kind='x' WHERE event_id=?", (event.event_id,))
    with pytest.raises(sqlite3.IntegrityError):
        store.raw_execute("DELETE FROM context_events WHERE event_id=?", (event.event_id,))


def test_root_publication_is_generation_bound_cas(store, valid_cut, publication):
    store.publish_cut(valid_cut, publication, expected_generation=0, expected_digest=None)
    with pytest.raises(RootConflict):
        store.publish_cut(valid_cut, publication, expected_generation=0, expected_digest=None)


def test_conflicting_source_cursor_is_rejected(store, event, conflicting_event):
    store.append_event(event)
    with pytest.raises(sqlite3.IntegrityError):
        store.append_event(conflicting_event)
```

- [ ] **Step 2: Run and verify schema/store absence**

Run: `python -m pytest tests/context/test_store_schema.py tests/context/test_store_transactions.py -q`  
Expected: FAIL.

- [ ] **Step 3: Implement the exact schema**

Create the tables from spec section 5.2 with:

- primary keys on immutable digests/IDs;
- unique `(source_id, source_generation, sequence)`;
- foreign keys from parents to child events and known parent digests;
- checks for nonnegative generation/sequence/length;
- one current-root row per run;
- append-only `BEFORE UPDATE` and `BEFORE DELETE` triggers on every immutable
  table; and
- schema version `1` in `PRAGMA user_version`.

Connections set `foreign_keys=ON`, `journal_mode=WAL`, `synchronous=FULL`, and a
bounded busy timeout. A schema-version mismatch raises `ContextSchemaError`.

- [ ] **Step 4: Implement transactional store methods**

The public API is fixed:

| Method | Exact transaction |
|---|---|
| `append_page(page) -> None` | verify blob digest/length, then `INSERT OR IGNORE`; conflicting metadata raises |
| `append_event(event) -> str` | immediate transaction, cursor/parent validation, child insert, parent inserts, commit digest |
| `event_by_digest(digest) -> ContextEvent | None` | one event row plus canonically ordered parent rows |
| `events_through(cut) -> tuple[ContextEvent, ...]` | bounded source-range reads ordered by source/generation/sequence |
| `append_artifact(artifact) -> str` | recompute artifact digest and create-or-return identical row |
| `current_cut(run_id) -> ContextCut | None` | join current pointer to immutable cut; dangling pointer raises corruption |
| `publish_cut(cut, receipt, expected_generation, expected_digest) -> None` | candidate validation and one conditional current-root CAS in an immediate transaction |
| `append_fault(fault) -> None` | append immutable fault receipt with no state transition |
| `append_trial(trial) -> None` | append immutable Quark trial receipt with no route change |

`append_event` uses `BEGIN IMMEDIATE`, recomputes the event digest, validates the
source cursor and parent rows, inserts child and parent rows, and returns the
digest. Same digest is create-or-return; same cursor with different digest is a
hard conflict. `publish_cut` verifies candidate and receipt digests, then performs
one generation/digest-conditional update before commit.

- [ ] **Step 5: Add crash-boundary transaction tests**

Parameterize exceptions after every insert/update in `publish_cut`. Reopen the
database after each injected crash and assert the current root is exactly the old
root or the fully committed successor and all foreign keys pass.

- [ ] **Step 6: Run store tests and SQLite integrity checks**

Run: `python -m pytest tests/context/test_store_schema.py tests/context/test_store_transactions.py -q`  
Expected: PASS.  
Run: `python tools/dev.py check platform_core/context/store.py`  
Expected: PASS.

- [ ] **Step 7: Commit**

```text
git add platform_core/context/schema.py platform_core/context/store.py
git add tests/context/test_store_schema.py tests/context/test_store_transactions.py
git commit -m "feat(context): add append-only context ledger"
```

---

### Task 6: Validate causally closed cuts and reduce exact hard state

**Files:**
- Create: `platform_core/context/reducer.py`
- Test: `tests/context/test_causal_cut.py`
- Test: `tests/context/test_reducer.py`
- Test: `tests/context/test_hard_pins.py`

- [ ] **Step 1: Write fractured-cut, cycle, and pin tests**

```python
import pytest

from platform_core.context.contracts import ContextInvariantError
from platform_core.context.reducer import reduce_delta, validate_cut_delta


def test_cut_rejects_parent_beyond_selected_cursor(store, prior_cut, fractured_delta):
    with pytest.raises(ContextInvariantError, match="parent beyond cut"):
        validate_cut_delta(store, prior_cut, fractured_delta)


def test_cut_rejects_causal_cycle(store, prior_cut, cyclic_delta):
    with pytest.raises(ContextInvariantError, match="cycle"):
        validate_cut_delta(store, prior_cut, cyclic_delta)


def test_hard_pin_survives_after_one_million_prior_events(
    state_after_million_events, final_delta, next_cut,
):
    state = reduce_delta(state_after_million_events, final_delta, next_cut)
    assert state.active_pin_ids == ("acceptance:must-pass",)


def test_only_qualified_discharge_removes_pin(
    pinned_state, events_with_unqualified_discharge, next_cut,
):
    state = reduce_delta(pinned_state, events_with_unqualified_discharge, next_cut)
    assert "acceptance:must-pass" in state.active_pin_ids
```

- [ ] **Step 2: Run and verify reducer absence**

Run: `python -m pytest tests/context/test_causal_cut.py tests/context/test_reducer.py tests/context/test_hard_pins.py -q`  
Expected: FAIL.

- [ ] **Step 3: Implement causal closure**

`validate_cut_delta` validates the bounded event delta after the prior committed cut,
verifies the prior induction state and new stream roots, rejects duplicate stream
entries, ensures every typed parent is in the prior closure or delta at the exact
generation/digest, enforces the configured fanout bound, and uses Kahn’s algorithm
with canonical digest ordering to reject new cycles. Recovery streams bounded
batches with durable checkpoints. `Cepheid-F` alone scans the complete prefix in
shadow/offline replay.

- [ ] **Step 4: Implement deterministic reduction**

```python
@dataclass(frozen=True, slots=True)
class ReducedContextState:
    cut_digest: str
    logical_state_digest: str
    active_pins: tuple[HardPin, ...]
    active_pin_ids: tuple[str, ...]
    revocation_generation: int
    policy_generation: int
    origin_closure_ref: str


def reduce_delta(
    previous: ReducedContextState,
    events: Iterable[ContextEvent],
    cut: ContextCut,
) -> ReducedContextState:
    ordered = canonical_topological_order(events)
    pins = {pin.pin_id: pin for pin in previous.active_pins}
    policy_generation = previous.policy_generation
    revocation_generation = previous.revocation_generation
    for event in ordered:
        if event.kind in PIN_INTRODUCTION_KINDS:
            pin = hard_pin_from_event(event)
            previous = pins.get(pin.pin_id)
            if previous is not None and pin.current_generation <= previous.current_generation:
                raise ContextInvariantError("nonmonotone hard pin generation")
            pins[pin.pin_id] = pin
        elif event.kind in PIN_DISCHARGE_KINDS:
            apply_qualified_discharge(pins, event)
        elif event.kind is EventKind.POLICY_ADVANCED:
            policy_generation = require_monotone_generation(policy_generation, event)
        elif event.kind is EventKind.REVOCATION_ADVANCED:
            revocation_generation = require_monotone_generation(revocation_generation, event)
    active = tuple(sorted((p for p in pins.values() if p.discharged_by is None), key=lambda p: p.pin_id))
    return build_reduced_state(
        previous, cut, active, policy_generation, revocation_generation, ordered,
    )
```

Every handler is closed by `EventKind`; no generic default mutates canonical
state. Unknown/unhandled state-bearing kinds raise. Genesis is one explicit
`ReducedContextState.genesis()` value. Production publication calls only
`validate_cut_delta` plus `reduce_delta`; a complete-prefix `reduce_cut` exists
only inside the independent Task 20 `Cepheid-F` replay implementation.

- [ ] **Step 5: Differential-test against an independent dictionary reducer**

Generate bounded event DAGs exhaustively, then at least one million deterministic
seeded operations. Compare active pins, generations, logical digest, and failure
classification between production and independently implemented test cepheid.

- [ ] **Step 6: Run reducer tests and checks**

Run: `python -m pytest tests/context/test_causal_cut.py tests/context/test_reducer.py tests/context/test_hard_pins.py -q`  
Expected: PASS.

- [ ] **Step 7: Commit**

```text
git add platform_core/context/reducer.py
git add tests/context/test_causal_cut.py tests/context/test_reducer.py tests/context/test_hard_pins.py
git commit -m "feat(context): add causally closed exact reduction"
```

---

### Task 7: Add the flat history cepheid and authenticated append-only hierarchy

**Files:**
- Create: `platform_core/context/history.py`
- Test: `tests/context/test_history_cepheid.py`
- Test: `tests/context/test_merkle_accumulator.py`
- Test: `tests/context/test_merkle_tamper.py`

- [ ] **Step 1: Write append/root/proof and tamper tests**

```python
from platform_core.context.history import FlatHistory, MerkleAccumulator


def test_merkle_matches_flat_logical_stream_digest(event_digests):
    flat = FlatHistory()
    merkle = MerkleAccumulator()
    for value in event_digests:
        flat.append(value)
        merkle.append(value)
    assert merkle.logical_stream_digest == flat.logical_stream_digest


def test_every_prefix_root_is_stable(event_digests):
    acc = MerkleAccumulator()
    roots = [acc.append(value).root_digest for value in event_digests]
    rebuilt = MerkleAccumulator.from_leaves(event_digests)
    assert rebuilt.prefix_roots == tuple(roots)


def test_proof_rejects_leaf_sibling_domain_and_shape_tamper(event_digests):
    acc = MerkleAccumulator.from_leaves(event_digests)
    proof = acc.proof(3)
    assert acc.verify(event_digests[3], proof)
    assert not acc.verify("sha256:" + "0" * 64, proof)
    assert not acc.verify(event_digests[3], proof.with_wrong_domain())
    assert not acc.verify(event_digests[3], proof.with_wrong_height())
```

- [ ] **Step 2: Run and verify history module absence**

Run: `python -m pytest tests/context/test_history_cepheid.py tests/context/test_merkle_accumulator.py tests/context/test_merkle_tamper.py -q`  
Expected: FAIL.

- [ ] **Step 3: Implement `FlatHistory` as the permanent cepheid**

`FlatHistory.append` stores canonical leaf digests. `range_fold` scans `[left,
right)` with the specified associative aggregate. `logical_stream_digest` hashes
the ordered leaf list in a distinct domain. It does not reuse production Merkle
code.

- [ ] **Step 4: Implement the Merkle accumulator/MMR**

Use binary-carry peaks. A leaf is `H("history-leaf", {index,digest})`; merging two
equal-height peaks is `H("history-node", {height,left,right,aggregate})`. The root
bags peaks left-to-right with a shape-bound domain. `append` is `O(log N)` worst
case and `O(1)` amortized. Proofs bind leaf index, total leaf count, peak height,
sibling direction, schema, and domains.

- [ ] **Step 5: Add randomized differential and serialization tests**

For sizes `0..4096`, compare every prefix logical digest and sampled range
aggregate with `FlatHistory`. Serialize/reload peaks and verify identical roots.
Flip each proof field independently and require rejection.

- [ ] **Step 6: Run history tests and commit**

Run: `python -m pytest tests/context/test_history_cepheid.py tests/context/test_merkle_accumulator.py tests/context/test_merkle_tamper.py -q`  
Expected: PASS.

```text
git add platform_core/context/history.py
git add tests/context/test_history_cepheid.py tests/context/test_merkle_accumulator.py
git add tests/context/test_merkle_tamper.py
git commit -m "feat(context): add authenticated append-only history"
```

---

### Task 8: Add exact dependency closure and parent-chain lineage

**Files:**
- Create: `platform_core/context/dependencies.py`
- Create: `platform_core/context/lineage.py`
- Test: `tests/context/test_dependencies.py`
- Test: `tests/context/test_lineage.py`

- [ ] **Step 1: Write closure, multi-parent, fork, and cycle tests**

```python
import pytest

from platform_core.context.dependencies import DependencyGraph
from platform_core.context.lineage import LineageCycle, ParentChain


def test_dependency_closure_keeps_both_join_parents():
    graph = DependencyGraph({"join": ("left", "right"), "left": ("root",), "right": ("root",)})
    assert graph.closure(("join",)) == ("root", "left", "right", "join")


def test_parent_chain_is_not_dependency_closure():
    chain = ParentChain()
    chain.add("root", None, aggregate={"pins": 1})
    chain.add("join", "left", aggregate={"pins": 0})
    assert "right" not in chain.path("join")


def test_parent_chain_rejects_cycle():
    chain = ParentChain.from_edges({"a": None, "b": "a"})
    with pytest.raises(LineageCycle):
        chain.reparent("a", "b")


def test_corrupt_internal_parent_cycle_fails_bounded():
    chain = ParentChain.from_edges({"a": None, "b": "a"})
    corrupt_parent_for_test(chain, "a", "b")
    with pytest.raises(ContextInvariantError, match="corrupt lineage cycle"):
        chain.path("b")
```

- [ ] **Step 2: Run and verify modules are absent**

Run: `python -m pytest tests/context/test_dependencies.py tests/context/test_lineage.py -q`  
Expected: FAIL.

- [ ] **Step 3: Implement deterministic dependency closure**

`DependencyGraph` accepts canonical sorted adjacency, rejects unknown endpoints,
self-loops, excessive fanout, and cycles, and returns canonical topological closure.
It includes an SCC diagnostic method for invalid imported graphs but never treats
an SCC as a valid causal dependency.

- [ ] **Step 4: Implement parent-chain/persistent-stack lineage**

```python
@dataclass(frozen=True, slots=True)
class LineageNode:
    node_id: str
    parent_id: str | None
    depth: int
    path_digest: str
    aggregate: PathAggregate


class ParentChain:
    def add(self, node_id: str, parent_id: str | None, aggregate: PathAggregate) -> LineageNode:
        if node_id in self._nodes:
            raise ContextInvariantError("duplicate lineage node")
        parent = self._nodes.get(parent_id) if parent_id is not None else None
        if parent_id is not None and parent is None:
            raise ContextInvariantError("unknown lineage parent")
        combined = aggregate if parent is None else parent.aggregate.combine(aggregate)
        path_digest = digest("lineage-path", {"parent": parent.path_digest if parent else None, "node": node_id})
        node = LineageNode(node_id, parent_id, 0 if parent is None else parent.depth + 1, path_digest, combined)
        self._nodes[node_id] = node
        return node

    def fork(self, node_id: str, child_id: str, aggregate: PathAggregate) -> LineageNode:
        return self.add(child_id, node_id, aggregate)

    def path(self, node_id: str) -> tuple[str, ...]:
        result: list[str] = []
        visited: set[str] = set()
        current = self._require(node_id)
        while current is not None:
            if current.node_id in visited or len(visited) >= len(self._nodes):
                raise ContextInvariantError("corrupt lineage cycle")
            visited.add(current.node_id)
            result.append(current.node_id)
            current = self._nodes.get(current.parent_id) if current.parent_id is not None else None
        return tuple(reversed(result))

    def path_aggregate(self, node_id: str) -> PathAggregate:
        return self._require(node_id).aggregate

    def reparent(self, node_id: str, new_parent_id: str | None) -> None:
        if new_parent_id == node_id or new_parent_id in self._descendants(node_id):
            raise LineageCycle(node_id)
        edges = {key: value.parent_id for key, value in self._nodes.items()}
        edges[node_id] = new_parent_id
        rebuilt = ParentChain.from_edges_and_locals(edges, self._locals)
        self._nodes = rebuilt._nodes
```

Normal add/fork caches depth, forward path digest, and constant-size aggregate.
`reparent` exists only for cepheid/telemetry and performs an explicit descendant
scan; production callers cannot use it until a qualified dynamic backend exists.

- [ ] **Step 5: Differential fuzz parent chains against explicit path walks**

Generate deep, wide, star, broom, and random fork trees. For every node, compare
cached depth/digest/aggregate with an independent parent walk. Inject legal and
illegal reparent sequences and require exact classification.

- [ ] **Step 6: Run and commit**

Run: `python -m pytest tests/context/test_dependencies.py tests/context/test_lineage.py -q`  
Expected: PASS.

```text
git add platform_core/context/dependencies.py platform_core/context/lineage.py
git add tests/context/test_dependencies.py tests/context/test_lineage.py
git commit -m "feat(context): add exact dependency and lineage baselines"
```

---

### Task 9: Add provider token accounting and Chamaeleon rendering

**Files:**
- Create: `platform_core/context/tokens.py`
- Test: `tests/context/test_tokens.py`
- Test: `tests/context/test_provider_render.py`

- [ ] **Step 1: Write exact/conservative counter and envelope tests**

```python
from platform_core.context.tokens import TokenCounterRegistry, TokenCount, render_envelope


def test_unknown_tokenizer_returns_conservative_bound():
    count = TokenCounterRegistry().count("claude", "unknown", "héllo")
    assert count.exact is False
    assert count.tokens >= len("héllo".encode("utf-8"))


def test_provider_envelopes_are_separate(packet):
    claude = render_envelope(packet, provider="claude", model="claude-local")
    codex = render_envelope(packet, provider="codex", model="codex-local")
    assert claude.template_digest != codex.template_digest
    assert claude.packet_digest != codex.packet_digest


def test_hard_packet_never_calls_legacy_four_char_estimate(monkeypatch, packet):
    monkeypatch.setattr("memory.retrievals.render.approx_tokens", lambda _: (_ for _ in ()).throw(AssertionError))
    render_envelope(packet, provider="codex", model="codex-local")
```

- [ ] **Step 2: Run and verify token module absence**

Run: `python -m pytest tests/context/test_tokens.py tests/context/test_provider_render.py -q`  
Expected: FAIL.

- [ ] **Step 3: Implement counter registry**

```python
@dataclass(frozen=True, slots=True)
class TokenCount:
    tokens: int
    exact: bool
    tokenizer_digest: str


class TokenCounterRegistry:
    def register(self, provider: str, model: str, counter: Callable[[str], int], digest_value: str) -> None:
        key = (provider.strip().lower(), model.strip())
        if not key[0] or not key[1] or not digest_value.startswith("sha256:"):
            raise ContextInvariantError("invalid tokenizer registration")
        if key in self._counters:
            raise ContextInvariantError("duplicate tokenizer registration")
        self._counters[key] = counter
        self._digests[key] = digest_value

    def count(self, provider: str, model: str, text: str) -> TokenCount:
        counter = self._counters.get((provider, model))
        if counter is None:
            return TokenCount(len(text.encode("utf-8")), False, "sha256:" + "0" * 64)
        value = counter(text)
        if not isinstance(value, int) or value < 0:
            raise ContextInvariantError("invalid tokenizer result")
        return TokenCount(value, True, self._digests[(provider, model)])
```

- [ ] **Step 4: Implement deterministic provider envelopes**

Render fixed ordered sections: protected contract, exact hard pins, current
execution state, dependency closure, active lineage, selected evidence, selected
advisory memory, retrieval handles, and packet receipt. Escape untrusted text and
never render paths or authority capabilities. Bind provider, model, tokenizer,
template, cut, source snapshot, policy, revocation, and packet digests.

- [ ] **Step 5: Enforce final budget behavior**

If the exact/conservative count exceeds the provider budget and any hard section
is present, raise `ContextUnsatisfiable` with required/available counts and a
typed recommended action of `decompose`, `fresh_epoch`, or `operator`. Do not
truncate. Optional pages may be removed only by recompiling a complete packet.

- [ ] **Step 6: Run and commit**

Run: `python -m pytest tests/context/test_tokens.py tests/context/test_provider_render.py -q`  
Expected: PASS.

```text
git add platform_core/context/tokens.py
git add tests/context/test_tokens.py tests/context/test_provider_render.py
git commit -m "feat(context): add provider-specific safe rendering"
```

---

### Task 10: Compile complete packet portfolios

**Files:**
- Create: `platform_core/context/packets.py`
- Create: `platform_core/context/independence.py`
- Test: `tests/context/test_packet_compiler.py`
- Test: `tests/context/test_packet_completeness.py`
- Test: `tests/context/test_independence.py`

- [ ] **Step 1: Write hard-pin, DAG, lineage, and candidate tests**

```python
import pytest

from platform_core.context.contracts import ContextInvariantError, ContextUnsatisfiable
from platform_core.context.packets import PacketCompiler


def test_packet_is_union_of_pins_dependencies_and_lineage(context_fixture):
    portfolio = PacketCompiler(context_fixture).compile(query="fix parser", consumer="codex")
    for packet in portfolio.packets:
        assert set(context_fixture.hard_pin_refs) <= set(packet.page_refs)
        assert set(context_fixture.dependency_closure) <= set(packet.page_refs)
        assert set(context_fixture.active_lineage) <= set(packet.page_refs)


def test_incomplete_candidate_generation_is_rejected(context_fixture):
    fixture = context_fixture.with_missing_required_candidate()
    with pytest.raises(ContextInvariantError, match="incomplete candidate portfolio"):
        PacketCompiler(fixture).compile(query="fix parser", consumer="codex")


def test_unfit_hard_state_fails_closed(context_fixture):
    with pytest.raises(ContextUnsatisfiable):
        PacketCompiler(context_fixture, provider_budget=1).compile("x", "codex")
```

- [ ] **Step 2: Run and verify compiler absence**

Run: `python -m pytest tests/context/test_packet_compiler.py tests/context/test_packet_completeness.py -q`  
Expected: FAIL.

- [ ] **Step 3: Implement candidate lanes and closure**

Compile in this order:

1. exact hard pins;
2. exact `ExecutionStateCutRef` records;
3. exact causal-DAG hard dependency closure;
4. exact active parent path;
5. direct symbol/path/verification-command candidates;
6. bounded SCC/BM25 graph expansion;
7. provenance-wrapped ANN/lexical RRF candidates; and
8. optional advisory summaries.

Deduplicate by immutable content digest, union origin closure/taint, and reject
conflicting metadata for one digest.

- [ ] **Step 4: Construct complete packets rather than arbitrary fragments**

Every portfolio member starts with the identical hard closure and varies only in
admissible optional page bundles. Bundle dependencies are closed before cost and
utility calculation. Emit a `CompletenessReceipt` containing the input candidate
set digest, missing-ref scan result, hard-pin digest, dependency digest, lineage
digest, and provider renderer identity.

- [ ] **Step 5: Add adversarial portfolio tests**

Cover overlapping pages, duplicate content with different paths, optional pages
that depend on omitted pages, stale generations, expired pages, tainted summaries,
false independence, and arbitrary input order. Packet order and digests must be
deterministic.

- [ ] **Step 6: Implement and test the BIF independence basis**

```python
@dataclass(frozen=True, slots=True)
class IndependenceBasis:
    origin_closure: frozenset[str]
    provider_session_digest: str
    model_runtime_digest: str
    packet_root: str
    source_cut_digest: str
    derivation_closure: frozenset[str]


def independent(left: IndependenceBasis, right: IndependenceBasis) -> bool:
    return (
        left.origin_closure.isdisjoint(right.origin_closure)
        and left.derivation_closure.isdisjoint(right.derivation_closure)
        and left.provider_session_digest != right.provider_session_digest
        and left.model_runtime_digest != right.model_runtime_digest
        and left.packet_root != right.packet_root
    )
```

The protected BIF policy may require additional disjoint dimensions; it may never
weaken these minimum checks. Add tests where Red/Blue outputs share a summary,
packet, model runtime, provider session, or ancestor and therefore remain
correlated.

- [ ] **Step 7: Run and commit**

Run: `python -m pytest tests/context/test_packet_compiler.py tests/context/test_packet_completeness.py tests/context/test_independence.py -q`  
Expected: PASS.

```text
git add platform_core/context/packets.py platform_core/context/independence.py
git add tests/context/test_packet_compiler.py tests/context/test_packet_completeness.py
git add tests/context/test_independence.py
git commit -m "feat(context): compile complete context portfolios"
```

---

### Task 11: Add exact and Pareto packet selectors

**Files:**
- Create: `platform_core/context/selectors.py`
- Test: `tests/context/test_exact_selector.py`
- Test: `tests/context/test_pareto_selector.py`

- [ ] **Step 1: Write exhaustive/Pareto equivalence and tie tests**

```python
import itertools

from platform_core.context.selectors import ExactSelector, ParetoSelector


def test_pareto_matches_exact_for_every_small_portfolio(packet_factory):
    packets = [packet_factory(cost=c, utility=v) for c, v in [(1, 1), (2, 15), (3, 30), (2, 14)]]
    exact = ExactSelector(packets)
    pareto = ParetoSelector(packets)
    for budget in range(0, 6):
        assert pareto.select(budget).packet_digest == exact.select(budget).packet_digest


def test_tie_break_is_utility_coverage_fault_cost_tokens_latency_digest(packet_factory):
    packets = packet_factory.tie_fixture()
    winner = ExactSelector(packets).select(100)
    assert winner.packet_digest == min(p.packet_digest for p in packets if p.is_final_tie)


def test_unsupported_packet_is_filtered_before_scoring(packet_factory):
    stale = packet_factory(cost=1, utility=9999, generation_valid=False)
    valid = packet_factory(cost=2, utility=1)
    assert ExactSelector([stale, valid]).select(10) == valid
```

- [ ] **Step 2: Run and verify selector absence**

Run: `python -m pytest tests/context/test_exact_selector.py tests/context/test_pareto_selector.py -q`  
Expected: FAIL.

- [ ] **Step 3: Implement the permanent exhaustive cepheid**

`ExactSelector.select` filters hard feasibility, evaluates the frozen lexicographic
tuple using integers only, and returns the maximum with canonical digest as the
final reverse/min tie. Empty feasible sets raise `ContextUnsatisfiable`.

- [ ] **Step 4: Implement the sorted Pareto frontier**

Sort by `(rendered_tokens, packet_digest)`, keep the lexicographically best packet
at each cost, then retain prefix improvements. Query with `bisect_right`. Store
the original portfolio digest and refuse queries after generation expiry.

- [ ] **Step 5: Exhaustively compare bounded portfolios**

Enumerate all portfolios of up to eight packets over small cost/value/coverage
domains and every budget. Add 100,000 deterministic randomized portfolios up to
1,000 candidates. Require zero result divergence.

- [ ] **Step 6: Run and commit**

Run: `python -m pytest tests/context/test_exact_selector.py tests/context/test_pareto_selector.py -q`  
Expected: PASS.

```text
git add platform_core/context/selectors.py
git add tests/context/test_exact_selector.py tests/context/test_pareto_selector.py
git commit -m "feat(context): add exact and Pareto packet selection"
```

---

### Task 12: Implement the Evaporation publish-before-evict transaction

**Files:**
- Create: `platform_core/context/compaction.py`
- Test: `tests/context/test_compaction_transaction.py`
- Test: `tests/context/test_compaction_crash_matrix.py`
- Test: `tests/context/test_summary_invariants.py`

- [ ] **Step 1: Write transaction-order and no-loss tests**

```python
import pytest

from platform_core.context.compaction import CompactionStage, EvaporationCompactor


def test_compaction_publishes_before_eviction(context_runtime, completed_range):
    result = EvaporationCompactor(context_runtime).compact(completed_range)
    assert result.stages == (
        CompactionStage.RAW_PERSISTED,
        CompactionStage.LEAVES_APPENDED,
        CompactionStage.SUMMARY_VALIDATED,
        CompactionStage.CANDIDATE_VERIFIED,
        CompactionStage.ROOT_PUBLISHED,
        CompactionStage.HANDLE_PUBLISHED,
        CompactionStage.LOCAL_COPY_EVICTED,
    )


@pytest.mark.parametrize("stage", list(CompactionStage))
def test_crash_at_every_stage_keeps_old_or_complete_new_root(runtime_factory, completed_range, stage):
    runtime = runtime_factory(crash_after=stage)
    old = runtime.store.current_cut("run")
    with pytest.raises(InjectedCrash):
        EvaporationCompactor(runtime).compact(completed_range)
    reopened = runtime.reopen()
    current = reopened.store.current_cut("run")
    assert current == old or reopened.is_fully_committed_successor(old, current)
    assert reopened.all_live_pages_reachable()
```

- [ ] **Step 2: Run and verify the transaction module is absent**

Run: `python -m pytest tests/context/test_compaction_transaction.py tests/context/test_compaction_crash_matrix.py tests/context/test_summary_invariants.py -q`  
Expected: FAIL.

- [ ] **Step 3: Implement the closed state machine**

```python
class CompactionStage(str, Enum):
    RAW_PERSISTED = "raw_persisted"
    LEAVES_APPENDED = "leaves_appended"
    SUMMARY_VALIDATED = "summary_validated"
    CANDIDATE_VERIFIED = "candidate_verified"
    ROOT_PUBLISHED = "root_published"
    HANDLE_PUBLISHED = "handle_published"
    LOCAL_COPY_EVICTED = "local_copy_evicted"


class EvaporationCompactor:
    def compact(self, event_range: CompletedEventRange) -> CompactionResult:
        require_completed_typed_boundary(event_range)
        pages = self._persist_and_reread_raw(event_range)
        leaves = self._append_typed_leaves(event_range, pages)
        summary = self._summarize_candidate(event_range, pages)
        receipt = self._validate_summary(summary, event_range, pages, leaves)
        candidate = self._build_and_verify_candidate(receipt)
        self._publish_with_cas(candidate)
        handle = self._publish_handle(candidate, pages)
        self._evict_local_copy_after_publication(event_range, handle)
        return self._result(candidate, handle)
```

Define `CompletedEventRange`, `CompactionResult`, and the internal candidate
records as frozen slot-backed dataclasses in this module. Their constructors bind
run, cut, source range, prior root, policy/revocation generations, and stage
receipts; no untyped dictionaries cross the transaction boundary.

The summarizer may be absent or fail. In that case Evaporation publishes an exact
addressable range handle without a summary; it does not fall back to truncation.

- [ ] **Step 4: Validate summaries without trusting their prose**

Require exact source-page list, source-cut digest, dependency references,
unresolved hard-pin IDs, omission declaration, producer/model/prompt/tokenizer
digests, origin closure, taint, and byte/token bounds. Verify all deterministic
fields from the source range. Mark the text `derived_unverified` until an
independent validation receipt exists.

- [ ] **Step 5: Add concurrency and stale-CAS tests**

Run two compactors against the same old root. Exactly one candidate may publish;
the loser records a stale-candidate receipt and leaves all its immutable objects
reachable for later GC. A hard pin introduced between candidate construction and
CAS must make publication fail.

- [ ] **Step 6: Run and commit**

Run: `python -m pytest tests/context/test_compaction_transaction.py tests/context/test_compaction_crash_matrix.py tests/context/test_summary_invariants.py -q`  
Expected: PASS.

```text
git add platform_core/context/compaction.py
git add tests/context/test_compaction_transaction.py tests/context/test_compaction_crash_matrix.py
git add tests/context/test_summary_invariants.py
git commit -m "feat(context): add transactional Evaporation compaction"
```

---

### Task 13: Add opaque paging, bounded recall, and clean provider epochs

**Files:**
- Create: `platform_core/context/paging.py`
- Test: `tests/context/test_page_handles.py`
- Test: `tests/context/test_paging.py`
- Test: `tests/context/test_working_set.py`

- [ ] **Step 1: Write handle-scope, recall-budget, and replacement tests**

```python
import pytest

from platform_core.context.paging import Light-EchoBroker, HandleDenied, RecallAction


def test_handle_is_consumer_packet_and_purpose_bound(broker, handle):
    assert broker.resolve(handle, consumer="codex", purpose="implementation").digest == handle.content_digest
    with pytest.raises(HandleDenied):
        broker.resolve(handle, consumer="claude", purpose="implementation")
    with pytest.raises(HandleDenied):
        broker.resolve(handle, consumer="codex", purpose="review")


def test_in_session_recall_never_claims_reclamation(broker, near_full_epoch, handle):
    decision = broker.request(near_full_epoch, handle)
    assert decision.action is RecallAction.FRESH_EPOCH
    assert decision.reclaimed_tokens == 0


def test_recall_budget_exhaustion_fails_closed(broker, epoch, handles):
    for handle in handles[:epoch.max_recalls]:
        assert broker.request(epoch, handle).admitted
    assert broker.request(epoch, handles[-1]).action is RecallAction.RECALL_BUDGET_EXHAUSTED
```

- [ ] **Step 2: Run and verify paging absence**

Run: `python -m pytest tests/context/test_page_handles.py tests/context/test_paging.py tests/context/test_working_set.py -q`  
Expected: FAIL.

- [ ] **Step 3: Implement signed-by-digest opaque handles**

`PageHandle` contains no path. Validate run, consumer, purpose, packet root,
source snapshot, sensitivity, content digest, byte/page ceilings, issue/expiry
generation, and a domain-separated handle digest. Resolution rechecks disclosure,
current root, revocation generation, expiry, and blob digest.

- [ ] **Step 4: Implement recall decisions**

```python
class RecallAction(str, Enum):
    IN_SESSION = "in_session"
    FRESH_EPOCH = "fresh_epoch"
    CONTEXT_UNSATISFIABLE = "context_unsatisfiable"
    RECALL_BUDGET_EXHAUSTED = "recall_budget_exhausted"
    DENIED = "denied"


def decide_recall(epoch: ProviderEpoch, page: ResolvedPage) -> RecallDecision:
    if not page.disclosure_allowed or not page.generation_valid:
        return RecallDecision.denied()
    if epoch.recall_count >= epoch.max_recalls:
        return RecallDecision.exhausted()
    if page.tokens + epoch.response_reserve <= epoch.remaining_additive_tokens:
        return RecallDecision.in_session(reclaimed_tokens=0)
    if epoch.hard_packet_can_fit_fresh(page):
        return RecallDecision.fresh_epoch(reclaimed_tokens=0)
    return RecallDecision.unsatisfiable(reclaimed_tokens=0)
```

- [ ] **Step 5: Add WSM thrash detection**

Track fault/refault counts, reuse distance, hot-page set, bytes/tokens, and epoch
handoffs. Trigger containment after a fixed generation-bound threshold. The
allowed outcomes are pin-hot-set within budget, fresh epoch, decomposition,
delegation, or operator escalation—never unbounded refault.

- [ ] **Step 6: Run and commit**

Run: `python -m pytest tests/context/test_page_handles.py tests/context/test_paging.py tests/context/test_working_set.py -q`  
Expected: PASS.

```text
git add platform_core/context/paging.py
git add tests/context/test_page_handles.py tests/context/test_paging.py tests/context/test_working_set.py
git commit -m "feat(context): add bounded context paging"
```

---

### Task 14: Connect typed ingress adapters without promoting telemetry to truth

**Files:**
- Create: `platform_core/context/ingress.py`
- Modify: `platform_core/orchestration/step_sink.py`
- Modify: `platform_core/orchestration/llm_navigation.py`
- Modify: `memory/retrievals/core.py`
- Test: `tests/context/test_ingress.py`
- Test: `tests/context/test_candidate_adapters.py`
- Test: `tests/notifications/test_subprocess_feed.py`

- [ ] **Step 1: Write producer-classification and failure-isolation tests**

```python
from platform_core.context.ingress import IngressClass, adapt_step, adapt_retrieval


def test_executor_tool_step_is_observation_not_accepted_state(step_record):
    event = adapt_step(step_record)
    assert event.ingress_class is IngressClass.OBSERVATION
    assert event.authority_ref is None


def test_retrieval_candidate_is_advisory_and_generation_bound(retrieval_row):
    page = adapt_retrieval(retrieval_row, source_generation=7)
    assert page.advisory is True
    assert page.source_generation == 7
    assert page.origin_closure_ref


def test_secret_ingress_keeps_only_digest_and_protected_source_handle(secret_tool_record):
    event = adapt_step(secret_tool_record)
    assert event.payload_ref.startswith("sha256:")
    assert event.protected_source_handle
    assert event.plaintext_page_ref is None


def test_context_ingress_failure_never_breaks_existing_step_sink(monkeypatch, existing_sink_args):
    monkeypatch.setattr("platform_core.context.ingress.observe_step", lambda *_: (_ for _ in ()).throw(OSError("disk")))
    sink = makeSink(**existing_sink_args)
    sink(0, "tool", "summary", {"x": 1})
    assert existing_sink_args["recorder"].was_called
```

- [ ] **Step 2: Run and verify ingress absence**

Run: `python -m pytest tests/context/test_ingress.py tests/context/test_candidate_adapters.py tests/notifications/test_subprocess_feed.py -q`  
Expected: FAIL only in new tests.

- [ ] **Step 3: Implement closed ingress classifications**

```python
class IngressClass(str, Enum):
    OBSERVATION = "observation"
    ADVISORY = "advisory"
    KERNEL_QUALIFIED = "kernel_qualified"


def accept_ingress(item: IngressItem, verifier: AuthorityVerifier) -> ContextEvent:
    if item.ingress_class is IngressClass.KERNEL_QUALIFIED:
        verifier.require_valid(item.authority_ref, item.payload_digest)
    elif item.claims_state_transition:
        raise ContextInvariantError("unqualified ingress cannot change accepted state")
    return item.to_event()
```

Create adapters for executor steps, trajectory spans, repository snapshot refs,
direct navigation candidates, RRF retrieval candidates, verifier receipts, and
kernel-issued `ExecutionStateCutRef`. Each adapter binds source generation,
payload digest, origin closure, taint, sensitivity, and disclosure class.

- [ ] **Step 4: Wire only observation mode into `step_sink`**

After existing journal and trajectory calls have completed, invoke
`observe_step` only when `ACCRETION_OBSERVE` is true. Catch/log failures under a
distinct degradation key. Shadow/qualified state ingestion occurs through the
kernel receipt path, not this callback.

- [ ] **Step 5: Preserve existing navigation and retrieval ranking**

Add adapter functions returning typed candidates without changing incumbent
selection order or legacy rendered strings while flags are false. Direct
symbol/path hits and verification commands are marked non-droppable in typed
candidate metadata.

- [ ] **Step 6: Run affected suites and commit**

Run: `python -m pytest tests/context/test_ingress.py tests/context/test_candidate_adapters.py tests/notifications/test_subprocess_feed.py tests/platform/test_llm_navigation.py tests/evolution/test_retrieval.py -q`  
Expected: PASS.

```text
git add platform_core/context/ingress.py platform_core/orchestration/step_sink.py
git add platform_core/orchestration/llm_navigation.py memory/retrievals/core.py
git add tests/context/test_ingress.py tests/context/test_candidate_adapters.py
git add tests/notifications/test_subprocess_feed.py
git commit -m "feat(context): connect typed context ingress"
```

---

### Task 15: Enforce provider-session freshness on resume and retry

**Files:**
- Modify: `platform_core/orchestration/step_resume.py`
- Create: `platform_core/context/session.py`
- Test: `tests/context/test_session_freshness.py`
- Test: `tests/execution/test_step_resume.py`
- Test: `tests/execution/test_resume_wiring.py`

- [ ] **Step 1: Write the full freshness-matrix tests**

```python
import pytest

from platform_core.context.session import SessionBinding, may_resume_session


BASE = SessionBinding.fixture()


@pytest.mark.parametrize("field", [
    "transaction_id", "clone_digest", "provider", "capability_digest",
    "spec_digest", "packet_root", "source_snapshot", "revocation_generation",
    "context_cut_digest", "policy_generation",
])
def test_any_binding_change_forces_fresh_session(field):
    changed = BASE.replace(**{field: BASE.changed_value(field)})
    assert may_resume_session(BASE, changed) is False


def test_rejected_rollback_or_contaminated_attempt_forces_fresh_session():
    for terminal_reason in ("rejected", "rolled_back", "contaminated", "superseded"):
        assert may_resume_session(BASE, BASE.replace(prior_terminal_reason=terminal_reason)) is False
```

- [ ] **Step 2: Run and confirm current plan-signature behavior is insufficient**

Run: `python -m pytest tests/context/test_session_freshness.py tests/execution/test_step_resume.py -q`  
Expected: new tests FAIL; existing tests show plan-signature-only reuse.

- [ ] **Step 3: Implement immutable session bindings**

`SessionBinding` contains every field above plus run, work, attempt, provider
session ID, issued generation, and expiry. `may_resume_session` requires exact
equality, same transaction, current nonrevoked receipt, and no prohibited prior
terminal reason. Missing/unknown fields return false.

- [ ] **Step 4: Change `resumePlan` and `reconcileResume`**

Preserve step reconstruction, but return `resume_session_id` only when the full
binding validates. Otherwise clear it, mark the prior attempt superseded through
an append-only context event, and request a fresh provider epoch. Do not delete
canonical context history. The legacy operational step-journal deletion remains
temporarily compatible but cannot affect the context ledger.

- [ ] **Step 5: Update wiring tests for clean epochs**

Assert same-transaction crash may reuse a session only when every binding matches.
New attempt/retry/rollback always launches without `--resume` and receives a
fresh compiled packet containing exact open obligations.

- [ ] **Step 6: Run and commit**

Run: `python -m pytest tests/context/test_session_freshness.py tests/execution/test_step_resume.py tests/execution/test_resume_wiring.py -q`  
Expected: PASS.

```text
git add platform_core/context/session.py platform_core/orchestration/step_resume.py
git add tests/context/test_session_freshness.py tests/execution/test_step_resume.py
git add tests/execution/test_resume_wiring.py
git commit -m "fix(context): require fresh bound provider sessions"
```

---

### Task 16: Add reachability-driven retention and safe garbage collection

**Files:**
- Create: `platform_core/context/retention.py`
- Modify: `platform_core/ops/retention.py`
- Test: `tests/context/test_retention.py`
- Test: `tests/platform/test_retention.py`

- [ ] **Step 1: Write live-root, lease, audit, and path-safety tests**

```python
def test_gc_preserves_all_reachable_objects(context_store, live_graph):
    report = sweep_context(context_store, now_generation=100)
    assert live_graph.reachable_digests <= set(report.preserved)
    assert not live_graph.reachable_digests.intersection(report.deleted)


def test_unresolved_pin_and_verifier_evidence_are_gc_roots(context_store, pin_page, evidence_page):
    report = sweep_context(context_store, now_generation=1000)
    assert pin_page.digest in report.preserved
    assert evidence_page.digest in report.preserved


def test_gc_refuses_any_resolved_path_outside_blob_root(tmp_path):
    store = malicious_path_store(tmp_path)
    with pytest.raises(ContextInvariantError):
        sweep_context(store, now_generation=1)
```

- [ ] **Step 2: Run and verify retention module absence**

Run: `python -m pytest tests/context/test_retention.py tests/platform/test_retention.py -q`  
Expected: FAIL in new tests.

- [ ] **Step 3: Implement mark-and-sweep over immutable references**

Roots are current/published cuts, live runs, audits, packets, root receipts,
unresolved pins, verifier evidence, protected outcomes, backend trials under
review, and unexpired retention leases. Traverse event parents, page/artifact
references, summaries, origin closure, packet contents, and publication ancestry.
Sweep only content-addressed blobs with no reachable metadata row and an expired
quarantine generation.

- [ ] **Step 4: Integrate as a guarded retention phase**

`platform_core.ops.retention.sweepAll` calls context GC only when the schema is
healthy and `ACCRETION_SHADOW` or `ACCRETION_QUALIFIED` is enabled. Missing/corrupt
reachability data skips deletion and emits a failure receipt.

- [ ] **Step 5: Run and commit**

Run: `python -m pytest tests/context/test_retention.py tests/platform/test_retention.py -q`  
Expected: PASS.

```text
git add platform_core/context/retention.py platform_core/ops/retention.py
git add tests/context/test_retention.py tests/platform/test_retention.py
git commit -m "feat(context): add reachability-safe context retention"
```

---

### Task 17: Implement the persistent segment hierarchy as a shadow candidate

**Files:**
- Create: `platform_core/context/shadow/__init__.py`
- Create: `platform_core/context/shadow/segment_tree.py`
- Test: `tests/context/shadow/test_segment_tree.py`
- Test: `tests/context/shadow/test_segment_lazy.py`
- Test: `tests/context/shadow/test_segment_differential.py`

- [ ] **Step 1: Write monoid, persistence, version, and lazy-law tests**

```python
def test_old_roots_remain_unchanged_after_update(segment_fixture):
    tree, root0 = segment_fixture
    root1 = tree.point_update(root0, 7, aggregate_for(7))
    assert tree.range_query(root0, 0, 16) == ZERO_AGGREGATE
    assert tree.range_query(root1, 0, 16) == aggregate_for(7)


def test_lazy_tags_obey_composition_action_law(tag_factory, aggregate_factory):
    for t1, t2, aggregate in tag_factory.cross(aggregate_factory):
        assert apply(compose(t1, t2), aggregate) == apply(t1, apply(t2, aggregate))


def test_lazy_tag_type_cannot_contain_truth_fields():
    assert set(LazyMetadataTag.__dataclass_fields__) == {
        "minimum_generation", "visibility_mask", "minimum_expiry", "invalidated_generation"
    }
```

- [ ] **Step 2: Run and verify shadow module absence**

Run: `python -m pytest tests/context/shadow/test_segment_tree.py tests/context/shadow/test_segment_lazy.py -q`  
Expected: FAIL.

- [ ] **Step 3: Implement a path-copy persistent tree**

Use integer half-open intervals over a fixed coordinate universe. Nodes are
immutable and content-addressed. Point update/range query allocate or visit
`O(log U)` nodes. Range updates exist only for `LazyMetadataTag`; canonical event
leaves and truth aggregates cannot be changed by a tag.

- [ ] **Step 4: Differential-test every historical version**

Compare randomized point/range operations against an independent versioned list
fold for at least one million seeded operations. After every operation, sample old
and new roots. Tamper with node interval, child digest, aggregate, tag, and schema;
verification must reject all mutations.

- [ ] **Step 5: Leave activation impossible in this task**

The package export exposes only a `ShadowSegmentBackend`. It requires
`ACCRETION_SEGMENT_SHADOW`, emits comparison receipts, and has no method to publish
a context root or packet.

- [ ] **Step 6: Run and commit**

Run: `python -m pytest tests/context/shadow/test_segment_tree.py tests/context/shadow/test_segment_lazy.py tests/context/shadow/test_segment_differential.py -q`  
Expected: PASS.

```text
git add platform_core/context/shadow/__init__.py platform_core/context/shadow/segment_tree.py
git add tests/context/shadow/test_segment_tree.py tests/context/shadow/test_segment_lazy.py
git add tests/context/shadow/test_segment_differential.py
git commit -m "feat(context): add shadow persistent interval backend"
```

---

### Task 18: Implement the link-cut tree as a derived shadow accelerator

**Files:**
- Create: `platform_core/context/shadow/link_cut.py`
- Test: `tests/context/shadow/test_link_cut.py`
- Test: `tests/context/shadow/test_link_cut_differential.py`
- Test: `tests/context/shadow/test_link_cut_recovery.py`

- [ ] **Step 1: Write dynamic-forest cepheid tests**

```python
def test_link_cut_matches_parent_walk_on_legal_sequence(link_cut, naive_forest, operations):
    for operation in operations:
        apply_both(operation, link_cut, naive_forest)
        for node in operation.touched_nodes:
            assert link_cut.path_aggregate(node) == naive_forest.path_aggregate(node)


def test_cycle_and_arbitrary_evert_are_not_public(link_cut):
    link_cut.link("a", "root")
    link_cut.link("b", "a")
    with pytest.raises(LineageCycle):
        link_cut.link("root", "b")
    assert not hasattr(link_cut, "evert")


def test_internal_rotations_never_change_semantic_parent_digest(link_cut):
    before = link_cut.semantic_parent_digest()
    link_cut.path_aggregate("leaf")
    assert link_cut.semantic_parent_digest() == before
```

- [ ] **Step 2: Run and verify link-cut absence**

Run: `python -m pytest tests/context/shadow/test_link_cut.py tests/context/shadow/test_link_cut_differential.py -q`  
Expected: FAIL.

- [ ] **Step 3: Implement single-writer link-cut internals**

Each splay node stores left/right/parent pointers, reversal bit, local aggregate,
forward aggregate, and reverse aggregate. Semantic parent identity lives in a
separate map and is updated only after cycle validation. Public operations are
`link`, `cut`, and `path_aggregate`; no public `evert` or subtree query exists.

- [ ] **Step 4: Build atomically from an immutable cut**

`ShadowLinkCutBackend.rebuild(cut, parent_edges)` constructs a private instance,
differentially compares every path aggregate with `ParentChain`, then swaps the
version pointer. Any mismatch keeps the old version or falls back to parent walks.

- [ ] **Step 5: Run one million seeded operations and crash/rebuild cases**

Include deep, star, broom, alternating hot paths, legal middle cuts/relinks,
illegal cycles, duplicate link/cut, stale generation, and recovery during rebuild.
Require zero cepheid divergence.

- [ ] **Step 6: Run and commit**

Run: `python -m pytest tests/context/shadow/test_link_cut.py tests/context/shadow/test_link_cut_differential.py tests/context/shadow/test_link_cut_recovery.py -q`  
Expected: PASS.

```text
git add platform_core/context/shadow/link_cut.py
git add tests/context/shadow/test_link_cut.py tests/context/shadow/test_link_cut_differential.py
git add tests/context/shadow/test_link_cut_recovery.py
git commit -m "feat(context): add shadow link-cut accelerator"
```

---

### Task 19: Implement the segment Li Chao tree as an affine shadow candidate

**Files:**
- Create: `platform_core/context/shadow/li_chao.py`
- Test: `tests/context/shadow/test_li_chao.py`
- Test: `tests/context/shadow/test_li_chao_counterexamples.py`
- Test: `tests/context/shadow/test_li_chao_differential.py`

- [ ] **Step 1: Write affine-domain, interval, tie, and rejection tests**

```python
def test_li_chao_matches_exhaustive_affine_envelope(lines, xs):
    tree = SegmentLiChao(xs)
    for line in lines:
        tree.insert(line)
    for x in xs:
        assert tree.query(x) == exhaustive_affine_winner(lines, x)


def test_lagrangian_budget_counterexample_is_declared_unsupported(packet_factory):
    packets = [packet_factory(1, 10), packet_factory(2, 15), packet_factory(3, 30)]
    with pytest.raises(UnsupportedLiChaoDomain):
        AffinePacketAdapter.from_budget_portfolio(packets)


def test_nonaffine_overlap_and_deletion_are_rejected():
    for candidate in nonaffine_candidates():
        with pytest.raises(UnsupportedLiChaoDomain):
            validate_li_chao_domain(candidate)
```

- [ ] **Step 2: Run and verify Li Chao absence**

Run: `python -m pytest tests/context/shadow/test_li_chao.py tests/context/shadow/test_li_chao_counterexamples.py -q`  
Expected: FAIL.

- [ ] **Step 3: Implement fixed-point interval lines**

```python
@dataclass(frozen=True, slots=True)
class AffinePacketLine:
    packet_digest: str
    slope: int
    intercept: int
    x_left: int
    x_right: int
    generation: int

    def value(self, x: int) -> int:
        if not self.x_left <= x <= self.x_right:
            raise ValueError("query outside line validity interval")
        return self.slope * x + self.intercept
```

The segment Li Chao tree supports interval insertion in `O(log^2 M)` and point
query in `O(log M)` over a fixed sorted integer coordinate set. Ties resolve by
score, lower rendered tokens, then packet digest. Generational rebuild replaces
deletion.

- [ ] **Step 4: Enforce the domain certificate**

Construction requires a `LiChaoDomainCertificate` binding portfolio, cut,
provider/model/tokenizer/template, scalar meaning/units, fixed-point scale,
validity intervals, affine proof method, and exact-enumeration comparison digest.
No certificate means the backend is unavailable.

- [ ] **Step 5: Differential-test arbitrary insertion order and boundaries**

Cover equal slopes, equal intersections, extreme fixed-point values, interval
endpoints, expired generations, 1 to 100,000 lines, and arbitrary insertion order.
Require zero regret against exhaustive evaluation at every coordinate.

- [ ] **Step 6: Run and commit**

Run: `python -m pytest tests/context/shadow/test_li_chao.py tests/context/shadow/test_li_chao_counterexamples.py tests/context/shadow/test_li_chao_differential.py -q`  
Expected: PASS.

```text
git add platform_core/context/shadow/li_chao.py
git add tests/context/shadow/test_li_chao.py tests/context/shadow/test_li_chao_counterexamples.py
git add tests/context/shadow/test_li_chao_differential.py
git commit -m "feat(context): add shadow affine Li Chao backend"
```

---

### Task 20: Build exact replay, benchmark, and Quark qualification harnesses

**Files:**
- Create: `platform_core/context/qualification.py`
- Create: `tools/context_replay.py`
- Create: `tools/context_benchmark.py`
- Test: `tests/context/test_qualification.py`
- Test: `tests/context/test_replay.py`
- Test: `tests/context/test_benchmark_accounting.py`

- [ ] **Step 1: Write hard-gate and crossover tests**

```python
from platform_core.context.qualification import TrialMetrics, qualify


def test_candidate_cannot_qualify_below_need_floor():
    incumbent = TrialMetrics(p95_us=200, cpu_share_ppm=5_000)
    candidate = TrialMetrics(p95_us=50, cpu_share_ppm=1_000)
    assert qualify(incumbent, candidate).qualified is False


def test_candidate_requires_100us_and_30pct_lower_confidence_bounds():
    result = qualify(fixture_incumbent(), fixture_candidate())
    assert result.absolute_gain_lower_95_us >= 100
    assert result.relative_gain_lower_95_ppm >= 300_000


def test_any_correctness_divergence_vetoes_performance_gain():
    candidate = fixture_candidate(selector_regret=1)
    assert qualify(fixture_incumbent(), candidate).qualified is False
```

- [ ] **Step 2: Run and verify harness absence**

Run: `python -m pytest tests/context/test_qualification.py tests/context/test_replay.py tests/context/test_benchmark_accounting.py -q`  
Expected: FAIL.

- [ ] **Step 3: Implement `Cepheid-F` replay**

Replay immutable receipts by canonical source cursor, validate digest chains and
causal parents, reduce state independently, materialize parent paths, traverse
dependency closure, enumerate packets, and compare every production/shadow
result. Replay accepts only fixture files or a read-only copied database and never
mutates the live root.

- [ ] **Step 4: Implement complete end-to-end accounting**

Measure construction/amortization, update, serialization, SQLite/blob persistence,
proof verification, selection, provider rendering, fallback bookkeeping, and
recovery. Capture warm/cold p50/p95/p99, CPU share in parts per million, peak RSS,
disk bytes, packet tokens, page faults, and verified task outcome.

Use paired traces in identical order. Compute confidence bounds with a
deterministic 10,000-resample paired bootstrap keyed by the trial-manifest digest;
the lower bound is the 2.5th percentile. Deterministic replay fixtures permit zero
outcome regression. Stochastic held-out tasks use a preregistered one-percentage-
point noninferiority margin and must additionally report the unrounded paired
success difference and Wilson intervals for each arm.

- [ ] **Step 5: Implement the frozen P2 decision**

```python
need = incumbent.p95_us > 250 or incumbent.cpu_share_ppm >= 10_000
qualified = (
    need
    and candidate.hard_gates_pass
    and candidate.absolute_gain_lower_95_us >= 100
    and candidate.relative_gain_lower_95_ppm >= 300_000
    and candidate.verified_success_noninferior
)
```

The decision binds workload bucket and adjacent scale buckets. A candidate routes
below its proven crossover to the simpler backend.

- [ ] **Step 6: Add fixed workload families**

Generate event counts `10^2..10^6`, append/query mixtures, historical ranges,
deep/wide/churned forests, portfolios `1..10^5`, provider envelopes, buried hard
requirements, later corrections/revocations, stale attempts, contradictions,
injections, thrashing, and crash boundaries. Seed and persist fixture manifests.

- [ ] **Step 7: Run and commit**

Run: `python -m pytest tests/context/test_qualification.py tests/context/test_replay.py tests/context/test_benchmark_accounting.py -q`  
Expected: PASS.

```text
git add platform_core/context/qualification.py tools/context_replay.py tools/context_benchmark.py
git add tests/context/test_qualification.py tests/context/test_replay.py
git add tests/context/test_benchmark_accounting.py
git commit -m "feat(context): add exact replay qualification"
```

---

### Task 21: Integrate dark, shadow, and qualified routing without authority drift

**Files:**
- Modify: `platform_core/orchestration/compaction.py`
- Modify: `platform_core/orchestration/brain_io.py`
- Modify: `memory/retrievals/render.py`
- Create: `platform_core/context/router.py`
- Test: `tests/context/test_router.py`
- Test: `tests/context/test_flag_matrix.py`
- Test: `tests/context/test_authority_noninterference.py`
- Test: `tests/slow/test_accretion_shadow.py`

- [ ] **Step 1: Write the closed flag matrix**

```python
@pytest.mark.parametrize(
    "observe,shadow,qualified,expected",
    [
        (False, False, False, "legacy"),
        (True, False, False, "legacy_observed"),
        (True, True, False, "legacy_with_shadow_compare"),
        (True, True, True, "qualified_with_exact_fallback"),
    ],
)
def test_flag_matrix(observe, shadow, qualified, expected, monkeypatch):
    patch_flags(monkeypatch, observe, shadow, qualified)
    assert ContextRouter().mode.value == expected
```

Invalid combinations—qualified without observe/shadow, an accelerator flag
without shadow, stale qualification root, or missing rollback receipt—must fail
closed to legacy/exact behavior and emit a reason-complete diagnostic.

- [ ] **Step 2: Write authority noninterference tests**

Patch packet contents, summaries, selector utility, and backend results. Assert no
value can change kernel authority, acceptance, verifier truth, scheduler
reservation, dispatch capability, mutation warrant, or promotion receipt.

- [ ] **Step 3: Implement the router**

`ContextRouter` selects only implementation backends. It requires current
Quark qualification receipts before selecting a qualified accelerator, always
retains exact fallback, and returns a typed `ContextUnavailable` rather than an
empty packet when required state is unavailable.

- [ ] **Step 4: Preserve facade compatibility**

`fitOrCompact`, `_fitUserToCtx`, and legacy retrieval render functions retain their
signatures. In qualified mode, the orchestrator passes a fully compiled packet
through a new explicit path; it never smuggles hard packets through the legacy
raw-string truncator. The old functions remain only for legacy callers and
negative-control tests.

- [ ] **Step 5: Run the full flag/authority matrix**

Run: `python -m pytest tests/context/test_router.py tests/context/test_flag_matrix.py tests/context/test_authority_noninterference.py tests/slow/test_accretion_shadow.py -q`  
Expected: PASS.

- [ ] **Step 6: Commit**

```text
git add platform_core/context/router.py platform_core/orchestration/compaction.py
git add platform_core/orchestration/brain_io.py memory/retrievals/render.py
git add tests/context/test_router.py tests/context/test_flag_matrix.py
git add tests/context/test_authority_noninterference.py tests/slow/test_accretion_shadow.py
git commit -m "feat(context): integrate qualified context routing"
```

---

### Task 22: Freeze documentation, repository map, and activation evidence

**Files:**
- Modify: `docs/superpowers/specs/2026-07-13-galaxy-r3-accretion-context-virtualization-r1.md`
- Modify: `docs/superpowers/specs/2026-07-13-galaxy-r3-qualified-capability-topology.md`
- Modify: `docs/superpowers/plans/2026-07-13-galaxy-r3-accretion-r1-implementation-plan.md`
- Modify: `AGENTS.md`
- Create/Modify: `platform_core/context/AGENTS.md`
- Modify: `.repo-map.json`
- Test: `tests/context/test_spec_coverage.py`
- Test: `tests/context/test_activation_evidence.py`
- Create: `tests/context/requirement_test_manifest.json`

- [ ] **Step 1: Add executable spec-coverage assertions**

```python
import json
from pathlib import Path

from platform_core.context.router import activation_matrix


SPEC = Path("docs/superpowers/specs/2026-07-13-galaxy-r3-accretion-context-virtualization-r1.md")


def test_every_mn_requirement_has_an_implementation_test():
    text = SPEC.read_text(encoding="utf-8")
    requirements = {f"MN-R{i:02d}" for i in range(1, 35)}
    manifest = json.loads(Path("tests/context/requirement_test_manifest.json").read_text(encoding="utf-8"))
    assert requirements == set(manifest)
    assert all(manifest[key] for key in requirements)


def test_no_accelerator_can_activate_without_current_qualification():
    assert activation_matrix().requires("segment", "QuarkP2QualificationReceipt")
    assert activation_matrix().requires("link_cut", "QuarkP2QualificationReceipt")
    assert activation_matrix().requires("li_chao", "LiChaoDomainCertificate")
```

- [ ] **Step 2: Regenerate the repository map**

Run: `python tools/repo_map.py`  
Expected: `AGENTS.md`, `platform_core/context/AGENTS.md`, and `.repo-map.json`
describe every new module and mapped test without drift.

- [ ] **Step 3: Record evidence without activating live traffic**

Write immutable local receipts for A/A, replay, hard gates, shadow comparisons,
P2 calculations, current source tree digest, config digest, fixture digest, and
rollback procedure. Keep `ACCRETION_QUALIFIED=false` unless a separately reviewed
activation transaction installs a current valid qualification root.

- [ ] **Step 4: Run focused and affected test lanes**

Run: `python -m pytest tests/context -q`  
Expected: PASS.  
Run: `python tools/affected_tests.py $(git diff --name-only)`  
Expected: PASS for every mapped affected test. On PowerShell, pass the file list
as `python tools/affected_tests.py (git diff --name-only)` only if the helper
accepts an array; otherwise use the repository’s documented invocation exactly.

- [ ] **Step 5: Run static, map, and full-suite gates**

Run: `python tools/dev.py fast`  
Expected: PASS.  
Run: `python -m pytest tests/test_repo_map.py -q`  
Expected: PASS.  
Run: `python -m pytest -n auto -q`  
Expected: PASS with zero network or paid-provider calls.

- [ ] **Step 6: Run the dry-run pipeline with Accretion dark and shadowed**

Run: `python main.py --dry-run --goal "verify Accretion context continuity" --hours 1 --no-web`  
Expected: successful dry run; no live effects; observation/shadow receipts only;
legacy and exact results agree for the exercised path.

- [ ] **Step 7: Perform the final staged-file and authority audit**

Verify:

- only files named by Tasks 1–22 are staged;
- no runtime flag defaults true;
- no network or paid dependency was added;
- immutable-table triggers exist and are exercised;
- every hard gate has direct evidence;
- every advanced backend has a kill switch and exact fallback;
- the dashboard remains read-only;
- Obsidian remains a projection;
- Voyager remains disabled/tainted/read-only; and
- no context packet can mutate authority state.

- [ ] **Step 8: Commit the completed implementation**

```text
git add docs/superpowers/specs/2026-07-13-galaxy-r3-accretion-context-virtualization-r1.md
git add docs/superpowers/specs/2026-07-13-galaxy-r3-qualified-capability-topology.md
git add docs/superpowers/plans/2026-07-13-galaxy-r3-accretion-r1-implementation-plan.md
git add AGENTS.md platform_core/context/AGENTS.md .repo-map.json
git add tests/context/test_spec_coverage.py tests/context/test_activation_evidence.py
git add tests/context/requirement_test_manifest.json
git commit -m "docs(context): freeze Accretion activation evidence"
```

---

## 3. Requirement-to-task coverage

| Requirements | Implementing tasks |
|---|---|
| `AC-R01`–`AC-R04` | 3, 5, 6, 14, 21 |
| `AC-R05` | 5, 6, 20 |
| `AC-R06`–`AC-R10` | 3, 6, 8, 9, 10, 15 |
| `AC-R11`–`AC-R17` | 3, 4, 5, 7, 12, 16, 20 |
| `AC-R18`–`AC-R24` | 9, 12, 13, 15, 21 |
| `AC-R25`–`AC-R27` | 7, 17, 20 |
| `AC-R28`–`AC-R29` | 8, 18, 20 |
| `AC-R30`–`AC-R31` | 10, 11, 19, 20 |
| `AC-R32` | 17–22 |
| `AC-R33` | 4, 14, 16 |
| `AC-R34` | 5, 6, 7, 20 |

Task 22’s executable manifest maps every individual requirement to at least one
named test node. This table is the human summary, not the verification cepheid.

---

## 4. Stop and rollback rules

Stop the implementation wave and retain the last simple backend when any of the
following occurs:

1. flat replay and a production/shadow result diverge;
2. a hard pin, revocation, current verifier failure, or acceptance condition is
   omitted or summarized away;
3. crash recovery produces anything other than the old committed root or a fully
   committed successor;
4. a provider session is reused across a forbidden generation/revision boundary;
5. origin ancestry or taint decreases through a transformation;
6. a page handle resolves outside its consumer/purpose/snapshot scope;
7. a selector admits an infeasible packet or differs from the exact encoded
   objective;
8. a shadow backend changes canonical state or authority;
9. the P2 crossover disappears in an adjacent real workload bucket;
10. fixed-budget verified success regresses; or
11. any network, paid API, metered inference, or recurring SaaS dependency enters
    the qualification path.

Rollback disables the candidate flag, records a `BackendRolledBack` receipt, and
routes to MMR/parent-chain/exact-Pareto. Immutable candidate evidence remains for
audit; it cannot keep affecting live packet decisions.

---

## 5. Execution handoff

This plan is intentionally executable without another architecture phase. Start
with Task 1 only after the Accretion R1 candidate freeze is approved. Use an
isolated worktree at execution time, implement tasks in order, and review each
task’s spec conformance and code quality before advancing.

Recommended execution mode: **subagent-driven development**, with a fresh worker
per task and independent spec/code review between tasks. Inline execution remains
valid when the operator prefers fewer concurrent branches.
