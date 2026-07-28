"""RED behavioral contracts for the outer, operator-owned launch boundary."""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import copy
import pickle
import struct
import subprocess
import sys
import threading
import time
from dataclasses import asdict, fields, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


def _mod():
    return importlib.import_module("platform_core.runtime.operator_launch")


_TRANSFER_TAG_LOCK = threading.Lock()
_TRANSFER_TAG_COUNTER = 0


def _next_transfer_tag() -> str:
    """Return a deterministic process-unique tag for one frame pair."""

    global _TRANSFER_TAG_COUNTER
    with _TRANSFER_TAG_LOCK:
        _TRANSFER_TAG_COUNTER += 1
        return f"transfer-{_TRANSFER_TAG_COUNTER}"


def _digest(*parts: object) -> str:
    encoded = ":".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _bootstrap_scope(
    tmp_path: Path | None = None,
    *,
    transfer_tag: object | None = None,
):
    """Build one valid v2 capsule scope without granting it authority."""

    scope_mod = importlib.import_module("platform_core.runtime.bootstrap_scope")
    tag = str(transfer_tag if transfer_tag is not None else _next_transfer_tag())
    path_tag = _digest("path", tag)[:16]
    if tmp_path is None:
        state_root = rf"C:\GalaxyOperatorLaunchTests\State\{path_tag}"
        source_root = rf"C:\GalaxyOperatorLaunchTests\Source\{path_tag}"
        installed_root = rf"C:\GalaxyOperatorLaunchTests\Installed\{path_tag}"
    else:
        base = Path(tmp_path).resolve()
        state_root = str(base / f"controller-state-{path_tag}")
        source_root = str(base / f"source-{path_tag}")
        installed_root = str(base / f"installed-{path_tag}")
    return scope_mod.CapsuleBootstrapScope(
        installed_repository_identity=_digest("installed-repository", tag),
        canonical_repository_id=_digest("canonical-repository", tag),
        run_id=f"run-{path_tag}",
        run_revision=0,
        controller_state_root=state_root,
        source_root=source_root,
        installed_controller_root=installed_root,
        external_roots_manifest_digest=_digest("external-roots-manifest", tag),
        repository_attestation_digest=_digest("repository-attestation", tag),
        expected_base_sha=_digest("expected-base", tag)[:40],
        source_snapshot_receipt_digest=_digest("source-snapshot-receipt", tag),
        anchor_receipt_digest=_digest("anchor-receipt", tag),
        boot_receipt_digest=_digest("boot-receipt", tag),
        controller_activation_receipt_digest=_digest(
            "controller-activation-receipt", tag
        ),
        recovery_receipt_digest=_digest("recovery-receipt", tag),
        activation_generation=3,
        boot_generation=5,
        controller_generation=7,
        watchdog_generation=11,
        revocation_generation=0,
        capability_expires_at="2099-01-01T01:00:00+00:00",
        run_deadline="2099-01-01T00:30:00+00:00",
    )


class Worker:
    def __init__(self, candidate=b'{"schema":1,"goal":"safe"}'):
        self.candidate = candidate
        self.launch = None
        self.quiesced = False

    def run(self, **launch):
        self.launch = launch
        return {"length_prefixed_bytes": self.candidate, "claimed_digest": "child-lie"}

    def revoke_and_quiesce_tree(self):
        self.quiesced = True
        return {"all_descendants_dead": True, "credential_channels_revoked": True}


class Channel:
    def __init__(self, response=None, *, prequeued=False):
        self.response = response
        self.prequeued = prequeued
        self.opened = False
        self.drained = False
        self.frame = None

    def drain_preexisting_input(self):
        self.drained = True
        return self.prequeued

    def exchange(self, frame, *, nonce):
        self.opened = True
        self.frame = frame
        if callable(self.response):
            return self.response(frame, nonce)
        return self.response


class ChildFactory:
    def __init__(self):
        self.calls = []

    def spawn(self, **kwargs):
        self.calls.append(kwargs)
        return type(
            "RecordedChild",
            (),
            {"pid": os.getpid(), "authority_pid": os.getpid()},
        )()


class QuiescibleChildFactory(ChildFactory):
    def __init__(self, *, on_spawn=None):
        super().__init__()
        self.on_spawn = on_spawn
        self.child = type(
            "QuiescibleRecordedChild",
            (),
            {
                "pid": os.getpid(),
                "authority_pid": os.getpid(),
                "terminated": False,
                "waited": False,
                "poll": lambda child: 0 if child.terminated else None,
                "terminate": lambda child: setattr(child, "terminated", True),
                "wait": lambda child, timeout=None: (
                    setattr(child, "waited", True) or 0
                ),
            },
        )()

    def spawn(self, **kwargs):
        self.calls.append(kwargs)
        if self.on_spawn is not None:
            self.on_spawn()
        return self.child


class AttackedChannel(Channel):
    """Test-local hostile implementation of the ordinary operator-channel protocol."""

    def __init__(self, attack, refusal_type):
        super().__init__()
        self.attack = attack
        self.refusal_type = refusal_type

    def attest_exclusive(self, **_kwargs):
        raise self.refusal_type(f"operator channel attack: {self.attack}")

    def exchange(self, frame, *, nonce):
        raise self.refusal_type(f"operator channel attack: {self.attack}")


class RealChildFactory:
    """Transfers PID-bound capabilities with an exact Win32 handle list."""

    def __init__(self, tmp_path):
        self.root = Path(tmp_path)
        self.calls = []
        self.processes = []
        self.control_writers = []
        self.replay_fds = []

    def _spawn_consumer(self, capability_fds=()):
        import msvcrt
        read_fd, write_fd = os.pipe()
        os.set_inheritable(read_fd, True)
        os.set_inheritable(write_fd, False)
        read_handle = msvcrt.get_osfhandle(read_fd)
        capability_handles = [msvcrt.get_osfhandle(fd) for fd in capability_fds]
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.lpAttributeList = {
            "handle_list": [read_handle, *capability_handles]
        }
        repo = Path(__file__).resolve().parents[2]
        code = (
            "import ctypes,json,os,struct,sys;"
            "print(json.dumps({'ready_pid':os.getpid()}),flush=True);"
            "stream=sys.stdin.buffer;"
            "read=lambda n: stream.read(n) if n else b'';"
            "size=struct.unpack('<I',read(4))[0];"
            "argv=json.loads(read(size).decode('utf-8'));"
            "count=struct.unpack('<I',read(4))[0];"
            "handles=list(struct.unpack('<'+'Q'*count,read(8*count)));"
            f"sys.path.insert(0,r'{repo}');"
            "from platform_core.runtime.operator_launch import consume_outer_capabilities as consume;"
            "\ntry:\n"
            " r=consume(argv=argv,capability_handles=handles);"
            " from dataclasses import replace\n"
            " from platform_core.runtime.operator_launch import OperatorCapabilityRefused,validate_authorized_outer_capabilities\n"
            " try:\n"
            "  validate_authorized_outer_capabilities(replace(r))\n"
            "  copied_outer_refused=False\n"
            " except OperatorCapabilityRefused:\n"
            "  copied_outer_refused=True\n"
            " from platform_core.runtime.bootstrap_authority import deriveInstalledBootstrapAuthorities\n"
            " bundle=deriveInstalledBootstrapAuthorities(outer_capabilities=r)\n"
            " controller=bundle.controller_state_authority\n"
            " issuer=bundle.landing_issuer\n"
            " admission=bundle.run_admission\n"
            " from platform_core.runtime.controller_state import ControllerStateRefused,currentControllerRuntimeStateBinding,installControllerRuntimeState,isInstalledControllerStateAuthority,validateControllerStateAuthority\n"
            " try:\n"
            "  validateControllerStateAuthority(replace(controller))\n"
            "  copied_controller_refused=False\n"
            " except ControllerStateRefused:\n"
            "  copied_controller_refused=True\n"
            " runtime_binding=installControllerRuntimeState(bootstrap_authorities=bundle)\n"
            " runtime_replay=installControllerRuntimeState(bootstrap_authorities=bundle) is runtime_binding\n"
            " runtime_current=currentControllerRuntimeStateBinding() is runtime_binding\n"
            " installed_controller=isInstalledControllerStateAuthority(controller)\n"
            " from platform_core.runtime import control_store,heartbeat\n"
            " from state import task_io\n"
            " from notifications.surfaces import terminal_ipc\n"
            " consumers=(control_store._binding(),heartbeat._binding(),task_io._binding(),terminal_ipc._binding())\n"
            " central_consumers=all(value is not None and value.store is runtime_binding.store and value.authority is runtime_binding.authority for value in consumers)\n"
            " control_store.setFlag('real-child-runtime','pause',True)\n"
            " control_roundtrip=control_store.getFlag('real-child-runtime','pause') is True\n"
            " heartbeat.writeHeartbeat('real-child-runtime',pid=os.getpid(),seq=1)\n"
            " heartbeat_roundtrip=runtime_binding.store.readJson('heartbeats/real-child-runtime',authority=runtime_binding.authority)['seq']==1\n"
            " terminal_ipc.write_nav(2,'raw',True)\n"
            " terminal_roundtrip=terminal_ipc.read_nav()=={'page_idx':2,'mode':'raw','frozen':True}\n"
            " import config\n"
            " config_bound=str(config.PROJECT_ROOT)==bundle.source_root and str(config.INSTALL_ROOT)==bundle.installed_controller_root\n"
            " print(json.dumps({'authorized':validate_authorized_outer_capabilities(r) is r,'pid':__import__('os').getpid(),'installed_issuer':issuer.isInstalledAuthority(),'admission_pid':admission.child_pid,'copied_outer_refused':copied_outer_refused,'copied_controller_refused':copied_controller_refused,'installed_controller':installed_controller,'runtime_replay':runtime_replay,'runtime_current':runtime_current,'central_consumers':central_consumers,'control_roundtrip':control_roundtrip,'heartbeat_roundtrip':heartbeat_roundtrip,'terminal_roundtrip':terminal_roundtrip,'config_bound':config_bound}))\n"
            " runtime_binding.store.close()\n"
            "except Exception as exc:\n"
            " print(json.dumps({'authorized':False,'error':type(exc).__name__,'pid':__import__('os').getpid()}))\n"
            "finally:\n"
            " [ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(h)) for h in handles]\n"
        )
        for descriptor in capability_fds:
            os.set_inheritable(descriptor, True)
        try:
            proc = subprocess.Popen(
                [sys.executable, "-I", "-c", code], cwd=self.root, env={},
                stdin=read_fd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                close_fds=True, startupinfo=startupinfo,
            )
        finally:
            os.close(read_fd)
            for descriptor in capability_fds:
                os.set_inheritable(descriptor, False)
        proc.galaxy_capability_handles = capability_handles
        ready = json.loads(proc.stdout.readline())
        proc.authority_pid = ready["ready_pid"]
        self.processes.append(proc)
        self.control_writers.append(write_fd)
        return proc, write_fd

    @staticmethod
    def _duplicate_into(process, handles):
        import ctypes
        import msvcrt
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # ctypes otherwise truncates the 64-bit pseudo-handle returned by
        # GetCurrentProcess to a signed c_int, turning -1 into the invalid
        # 0x00000000FFFFFFFF value at DuplicateHandle's Win64 boundary.
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.DuplicateHandle.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p), ctypes.c_ulong, ctypes.c_int,
            ctypes.c_ulong,
        ]
        kernel32.DuplicateHandle.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        current = kernel32.GetCurrentProcess()
        target_process = kernel32.OpenProcess(0x0040, False, process.pid)
        if not target_process:
            raise ctypes.WinError(ctypes.get_last_error())
        duplicated = []
        try:
            for fd in handles:
                target = ctypes.c_void_p()
                ok = kernel32.DuplicateHandle(
                    current, ctypes.c_void_p(msvcrt.get_osfhandle(fd)), target_process,
                    ctypes.byref(target), 0, False, 0x00000002,
                )
                if not ok:
                    raise ctypes.WinError(ctypes.get_last_error())
                duplicated.append(target.value)
            return duplicated
        finally:
            kernel32.CloseHandle(target_process)

    @staticmethod
    def _send(writer, argv, duplicated_handles):
        argv_bytes = json.dumps(argv, separators=(",", ":")).encode("utf-8")
        frame = (struct.pack("<I", len(argv_bytes)) + argv_bytes
                 + struct.pack("<I", len(duplicated_handles))
                 + struct.pack("<" + "Q" * len(duplicated_handles), *duplicated_handles))
        while frame:
            written = os.write(writer, frame)
            frame = frame[written:]
        os.close(writer)

    def spawn(self, **kwargs):
        self.calls.append(kwargs)
        proc, self.right_writer = self._spawn_consumer(kwargs["capability_handles"])
        self.replay_fds = [os.dup(fd) for fd in kwargs["capability_handles"]]
        return proc

    def consume_from_wrong_pid(self, argv, handles):
        del handles
        wrong, writer = self._spawn_consumer(self.replay_fds)
        self._send(writer, argv, wrong.galaxy_capability_handles)
        self.control_writers.remove(writer)
        out, err = wrong.communicate(timeout=10)
        assert wrong.returncode == 0, f"wrong-PID consumer failed\nstdout={out}\nstderr={err}"
        return json.loads(out)

    def consume_from_bound_pid(self, argv, handles):
        right = self.processes[0]
        self._send(self.right_writer, argv, right.galaxy_capability_handles)
        self.control_writers.remove(self.right_writer)
        out, err = right.communicate(timeout=10)
        assert right.returncode == 0, f"bound consumer failed\nstdout={out}\nstderr={err}"
        return json.loads(out)

    def close(self):
        for writer in self.control_writers:
            try:
                os.close(writer)
            except OSError:
                pass
        self.control_writers.clear()
        for descriptor in self.replay_fds:
            try:
                os.close(descriptor)
            except OSError:
                pass
        self.replay_fds.clear()
        for proc in self.processes:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            for stream in (proc.stdout, proc.stderr):
                if stream is not None:
                    stream.close()


class ImmediateRealChildFactory:
    """A true Win32 child that consumes before ``spawn`` returns to the issuer."""

    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path
        self.calls: list[dict[str, object]] = []
        self.process: subprocess.Popen[str] | None = None

    def spawn(self, **kwargs):
        import msvcrt

        self.calls.append(kwargs)
        descriptors = tuple(kwargs["capability_handles"])
        handles = [msvcrt.get_osfhandle(fd) for fd in descriptors]
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.lpAttributeList = {"handle_list": handles}
        repo = Path(__file__).resolve().parents[2]
        code = (
            "import json,os,sys;"
            f"sys.path.insert(0,r'{repo}');"
            "from platform_core.runtime.operator_launch import consume_outer_capabilities;"
            "print('READY '+str(os.getpid()),flush=True);"
            "\ntry:\n"
            f" r=consume_outer_capabilities(argv=['main.py','--operator-child-launch'],capability_handles={handles!r})\n"
            " print(json.dumps({'authorized':True,'pid':os.getpid()}),flush=True)\n"
            "except Exception as exc:\n"
            " print(json.dumps({'authorized':False,'error':type(exc).__name__,'message':str(exc),'pid':os.getpid()}),flush=True)\n"
        )
        for descriptor in descriptors:
            os.set_inheritable(descriptor, True)
        try:
            process = subprocess.Popen(
                [sys.executable, "-I", "-c", code],
                cwd=self.root,
                env={},
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                close_fds=True,
                startupinfo=startupinfo,
            )
        finally:
            for descriptor in descriptors:
                os.set_inheritable(descriptor, False)
        assert process.stdout is not None
        ready = process.stdout.readline().strip().split()
        assert len(ready) == 2 and ready[0] == "READY"
        process.authority_pid = int(ready[1])
        self.process = process
        return process

    def result(self) -> dict[str, object]:
        assert self.process is not None
        assert self.process.stdout is not None
        line = self.process.stdout.readline()
        _, error = self.process.communicate(timeout=10)
        assert self.process.returncode == 0, error
        return json.loads(line)

    def close(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=5)
        for stream in (self.process.stdout, self.process.stderr):
            if stream is not None:
                stream.close()


def _launcher(
    tmp_path,
    worker=None,
    channel=None,
    child=None,
    *,
    transfer_tag: object | None = None,
):
    mod = _mod()
    scope = _bootstrap_scope(tmp_path, transfer_tag=transfer_tag)
    return mod.OperatorLauncher(
        bootstrap_authority=mod._issueDiagnosticCapsuleBootstrapAuthority(scope),
        worker=worker or Worker(),
        operator_channel=channel or Channel(),
        child_factory=child or ChildFactory(),
        nonce_factory=lambda: "n" * 64,
    )


class SameProcessChildFactory(ChildFactory):
    """Test-only child seam whose bound PID is the current test process."""

    def spawn(self, **kwargs):
        self.calls.append(kwargs)
        self.consumer_handles = tuple(
            os.dup(descriptor) for descriptor in kwargs["capability_handles"]
        )
        return type(
            "SameProcessChild",
            (),
            {"pid": os.getpid(), "authority_pid": os.getpid()},
        )()


def _consume_same_process_outer(
    tmp_path: Path,
    *,
    transfer_tag: object | None = None,
):
    mod = _mod()
    tag = transfer_tag if transfer_tag is not None else _next_transfer_tag()
    scope = _bootstrap_scope(tmp_path, transfer_tag=tag)
    child = SameProcessChildFactory()
    channel = Channel(
        response=lambda frame, nonce: (
            f"APPROVE SPEC {frame.digest} NONCE {nonce}"
        )
    )
    launcher = mod.OperatorLauncher(
        bootstrap_authority=mod._issueDiagnosticCapsuleBootstrapAuthority(scope),
        worker=Worker(),
        operator_channel=channel,
        child_factory=child,
        nonce_factory=lambda: "1" * 64,
    )
    proposal = launcher.propose(raw_intent="do safe work", task_id="task")
    launcher.approve_and_spawn(proposal)
    handles = child.consumer_handles
    with mod._PARENT_BINDINGS_LOCK:
        for handle in handles:
            mod._PARENT_BINDINGS[handle] = os.getpid()
    try:
        value = mod.consume_outer_capabilities(
            argv=child.calls[0]["argv"], capability_handles=handles
        )
        return value
    finally:
        for handle in handles:
            try:
                os.close(handle)
            except OSError:
                pass


def _consume_wire_frames(
    *,
    overrides: dict[str, object] | None = None,
    second_overrides: dict[str, object] | None = None,
    transfer_tag: object | None = None,
):
    """Present desired-schema frames directly to the public consume boundary."""

    mod = _mod()
    launch, approval = _desired_wire_payloads(transfer_tag=transfer_tag)
    launch = {**launch, **(overrides or {})}
    approval = {**approval, **(second_overrides or overrides or {})}
    readers, writers = mod._new_capability_pipes()
    with mod._PARENT_BINDINGS_LOCK:
        for reader in readers:
            mod._PARENT_BINDINGS[reader] = os.getpid()
    frames = (
        mod._capability_payload(
            "launch",
            child_pid=os.getpid(),
            values={key: value for key, value in launch.items() if key != "kind"},
        ),
        mod._capability_payload(
            "spec_approval",
            child_pid=os.getpid(),
            values={key: value for key, value in approval.items() if key != "kind"},
        ),
    )
    try:
        for writer, frame in zip(writers, frames, strict=True):
            mod._write_all(writer, frame)
            os.close(writer)
        writers.clear()
        return mod.consume_outer_capabilities(
            argv=["main.py", "--operator-child-launch"],
            capability_handles=readers,
        )
    finally:
        for descriptor in readers + writers:
            with mod._PARENT_BINDINGS_LOCK:
                mod._PARENT_BINDINGS.pop(descriptor, None)
            try:
                os.close(descriptor)
            except OSError:
                pass


def _desired_wire_payloads(
    *,
    transfer_tag: object | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    tag = str(transfer_tag if transfer_tag is not None else _next_transfer_tag())
    scope = _bootstrap_scope(transfer_tag=tag)
    launch_secret = _digest("launch-secret", tag)
    approval_secret = _digest("approval-secret", tag)
    common: dict[str, object] = {
        **scope.wire_mapping(),
        "version": 2,
        "child_pid": os.getpid(),
        "launch_id": _digest("launch-id", tag),
        "task_id": f"task-{_digest('task', tag)[:16]}",
        "raw_intent_digest": _digest("raw-intent", tag),
        "spec_schema": 1,
        "canonical_spec_length": 26,
        "spec_digest": _digest("spec", tag),
        "approval_nonce": _digest("approval-nonce", tag),
        "launch_secret_digest": hashlib.sha256(
            launch_secret.encode("ascii")
        ).hexdigest(),
        "approval_secret_digest": hashlib.sha256(
            approval_secret.encode("ascii")
        ).hexdigest(),
    }
    return (
        {**common, "kind": "launch", "one_time_secret": launch_secret},
        {
            **common,
            "kind": "spec_approval",
            "one_time_secret": approval_secret,
        },
    )


def _frame_body(body: bytes) -> bytes:
    return struct.pack("<I", len(body)) + body


def _canonical_wire_frame(payload: dict[str, object]) -> bytes:
    body = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return _frame_body(body)


def _consume_raw_frames(
    frames: tuple[bytes, bytes],
    *,
    reverse_handles: bool = False,
    duplicate_first_handle: bool = False,
):
    mod = _mod()
    readers, writers = mod._new_capability_pipes()
    with mod._PARENT_BINDINGS_LOCK:
        for reader in readers:
            mod._PARENT_BINDINGS[reader] = os.getpid()
    try:
        for writer, frame in zip(writers, frames, strict=True):
            mod._write_all(writer, frame)
            os.close(writer)
        writers.clear()
        handles = list(reversed(readers)) if reverse_handles else list(readers)
        if duplicate_first_handle:
            handles = [readers[0], readers[0]]
        return mod.consume_outer_capabilities(
            argv=["main.py", "--operator-child-launch"],
            capability_handles=handles,
        )
    finally:
        for descriptor in readers + writers:
            with mod._PARENT_BINDINGS_LOCK:
                mod._PARENT_BINDINGS.pop(descriptor, None)
            try:
                os.close(descriptor)
            except OSError:
                pass


def test_prespec_worker_is_pipe_only_without_terminal_input_or_execution_authority(tmp_path):
    worker = Worker()
    launcher = _launcher(tmp_path, worker=worker)
    launcher.propose(raw_intent="do safe work", task_id="task")
    launch = worker.launch
    assert launch["stdin"] == "pipe" and launch["stdout"] == "pipe"
    assert launch["stderr"] == "pipe"
    assert launch["controlling_terminal"] is None
    assert launch["console_input_handle"] is None
    assert launch["operator_input_handle"] is None
    assert launch["local_trust_grant"] is None
    assert launch["execution_child_capability"] is None
    assert launch["authority"].kind == "pre_spec_analysis"
    assert len(launch["authority"].repository_attestation_digest) == 64
    assert len(launch["authority"].expected_base_sha) == 40
    assert len(launch["authority"].source_snapshot_receipt_digest) == 64


def test_entire_worker_tree_and_credentials_quiesce_before_operator_channel_opens(tmp_path):
    order = []
    worker = Worker()
    original = worker.revoke_and_quiesce_tree
    worker.revoke_and_quiesce_tree = lambda: (order.append("quiesce"), original())[1]
    channel = Channel(response=lambda frame, nonce: (
        order.append("approve"), f"APPROVE SPEC {frame.digest} NONCE {nonce}"
    )[1])
    child = ChildFactory()
    launcher = _launcher(tmp_path, worker=worker, channel=channel, child=child)
    proposal = launcher.propose(raw_intent="do safe work", task_id="task")
    launcher.approve_and_spawn(proposal)
    assert order == ["quiesce", "approve"]
    assert worker.quiesced and len(child.calls) == 1


def test_capsule_expiry_during_operator_exchange_is_permanent_and_has_zero_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _mod()
    now = [datetime(2098, 1, 1, tzinfo=timezone.utc)]
    monkeypatch.setattr(mod, "_utc_now", lambda: now[0])
    child = ChildFactory()

    def expire_during_exchange(frame, nonce):
        now[0] = datetime(2100, 1, 1, tzinfo=timezone.utc)
        return f"APPROVE SPEC {frame.digest} NONCE {nonce}"

    launcher = _launcher(
        tmp_path,
        channel=Channel(response=expire_during_exchange),
        child=child,
        transfer_tag="expires-during-exchange",
    )
    proposal = launcher.propose(raw_intent="raw", task_id="task")

    with pytest.raises(mod.OperatorLaunchRefused, match="expired"):
        launcher.approve_and_spawn(proposal)

    assert child.calls == []
    assert list(tmp_path.rglob("*.json")) == []
    with pytest.raises(mod.OperatorApprovalRefused, match="already spent|absent"):
        launcher.approve_and_spawn(proposal)


def test_capsule_expiry_is_rechecked_immediately_after_worker_quiescence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _mod()
    now = [datetime(2098, 1, 1, tzinfo=timezone.utc)]
    monkeypatch.setattr(mod, "_utc_now", lambda: now[0])

    class ExpiringWorker(Worker):
        def revoke_and_quiesce_tree(self):
            evidence = super().revoke_and_quiesce_tree()
            now[0] = datetime(2100, 1, 1, tzinfo=timezone.utc)
            return evidence

    channel = Channel(response="unused")
    child = ChildFactory()
    launcher = _launcher(
        tmp_path,
        worker=ExpiringWorker(),
        channel=channel,
        child=child,
        transfer_tag="expires-after-quiescence",
    )

    with pytest.raises(mod.OperatorLaunchRefused, match="expired"):
        launcher.approve_and_spawn(
            launcher.propose(raw_intent="raw", task_id="task")
        )

    assert channel.opened is False
    assert child.calls == []
    assert list(tmp_path.rglob("*.json")) == []


def test_capsule_expiry_is_rechecked_immediately_before_spec_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _mod()
    now = [datetime(2098, 1, 1, tzinfo=timezone.utc)]
    monkeypatch.setattr(mod, "_utc_now", lambda: now[0])
    original_path = mod.OperatorLauncher._canonicalSpecPath
    path_calls = 0

    def expire_after_path_derivation(scope, task_id):
        nonlocal path_calls
        result = original_path(scope, task_id)
        path_calls += 1
        if path_calls == 1:
            now[0] = datetime(2100, 1, 1, tzinfo=timezone.utc)
        return result

    monkeypatch.setattr(
        mod.OperatorLauncher,
        "_canonicalSpecPath",
        staticmethod(expire_after_path_derivation),
    )
    child = ChildFactory()
    launcher = _launcher(
        tmp_path,
        channel=Channel(
            response=lambda frame, nonce: (
                f"APPROVE SPEC {frame.digest} NONCE {nonce}"
            )
        ),
        child=child,
        transfer_tag="expires-before-spec-write",
    )

    with pytest.raises(mod.OperatorLaunchRefused, match="expired"):
        launcher.approve_and_spawn(
            launcher.propose(raw_intent="raw", task_id="task")
        )

    assert path_calls == 1
    assert child.calls == []
    assert list(tmp_path.rglob("*.json")) == []


def test_capsule_expiry_is_rechecked_immediately_before_child_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _mod()
    now = [datetime(2098, 1, 1, tzinfo=timezone.utc)]
    monkeypatch.setattr(mod, "_utc_now", lambda: now[0])
    original_pipes = mod._new_capability_pipes
    opened: list[int] = []

    def expire_after_pipe_creation():
        readers, writers = original_pipes()
        opened.extend(readers + writers)
        now[0] = datetime(2100, 1, 1, tzinfo=timezone.utc)
        return readers, writers

    monkeypatch.setattr(mod, "_new_capability_pipes", expire_after_pipe_creation)
    child = ChildFactory()
    launcher = _launcher(
        tmp_path,
        channel=Channel(
            response=lambda frame, nonce: (
                f"APPROVE SPEC {frame.digest} NONCE {nonce}"
            )
        ),
        child=child,
        transfer_tag="expires-before-child-spawn",
    )

    with pytest.raises(mod.OperatorLaunchRefused, match="expired"):
        launcher.approve_and_spawn(
            launcher.propose(raw_intent="raw", task_id="task")
        )

    assert child.calls == []
    assert len(list(tmp_path.rglob("*.json"))) == 1
    for descriptor in opened:
        with pytest.raises(OSError):
            os.get_inheritable(descriptor)


def test_launch_id_entropy_failure_occurs_before_any_pipe_allocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _mod()
    launcher = _launcher(
        tmp_path,
        channel=Channel(
            response=lambda frame, nonce: (
                f"APPROVE SPEC {frame.digest} NONCE {nonce}"
            )
        ),
        transfer_tag="launch-id-entropy-failure",
    )
    proposal = launcher.propose(raw_intent="raw", task_id="task")
    original_pipes = mod._new_capability_pipes
    allocations = 0
    opened: list[int] = []

    def tracking_pipes():
        nonlocal allocations
        allocations += 1
        readers, writers = original_pipes()
        opened.extend(readers + writers)
        return readers, writers

    def entropy_failure(_width: int) -> str:
        raise OSError("injected entropy failure")

    monkeypatch.setattr(mod, "_new_capability_pipes", tracking_pipes)
    monkeypatch.setattr(mod.secrets, "token_hex", entropy_failure)
    try:
        with pytest.raises(OSError, match="entropy failure"):
            launcher.approve_and_spawn(proposal)
    finally:
        for descriptor in opened:
            try:
                os.close(descriptor)
            except OSError:
                pass

    assert allocations == 0


def test_malformed_launch_id_is_refused_before_pipe_allocation_or_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _mod()
    child = ChildFactory()
    launcher = _launcher(
        tmp_path,
        channel=Channel(
            response=lambda frame, nonce: (
                f"APPROVE SPEC {frame.digest} NONCE {nonce}"
            )
        ),
        child=child,
        transfer_tag="malformed-launch-id",
    )
    proposal = launcher.propose(raw_intent="raw", task_id="task")
    allocations = 0

    def forbidden_pipes():
        nonlocal allocations
        allocations += 1
        raise AssertionError("malformed launch ID reached pipe allocation")

    monkeypatch.setattr(mod, "_new_capability_pipes", forbidden_pipes)
    monkeypatch.setattr(mod.secrets, "token_hex", lambda _width: "short")

    with pytest.raises(mod.OperatorLaunchRefused, match="launch ID|launch_id"):
        launcher.approve_and_spawn(proposal)

    assert allocations == 0
    assert child.calls == []


def test_capsule_expiry_immediately_after_spawn_quiesces_child_before_frames(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _mod()
    now = [datetime(2098, 1, 1, tzinfo=timezone.utc)]
    monkeypatch.setattr(mod, "_utc_now", lambda: now[0])
    child = QuiescibleChildFactory(
        on_spawn=lambda: now.__setitem__(
            0, datetime(2100, 1, 1, tzinfo=timezone.utc)
        )
    )
    writes: list[bytes] = []
    monkeypatch.setattr(
        mod,
        "_write_all",
        lambda _descriptor, payload: writes.append(payload),
    )
    launcher = _launcher(
        tmp_path,
        channel=Channel(
            response=lambda frame, nonce: (
                f"APPROVE SPEC {frame.digest} NONCE {nonce}"
            )
        ),
        child=child,
        transfer_tag="expires-immediately-after-spawn",
    )

    with pytest.raises(mod.OperatorLaunchRefused, match="expired"):
        launcher.approve_and_spawn(
            launcher.propose(raw_intent="raw", task_id="task")
        )

    assert len(child.calls) == 1
    assert child.child.terminated and child.child.waited
    assert writes == []


def test_capsule_expiry_before_frame_publication_quiesces_child_with_zero_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _mod()
    now = [datetime(2098, 1, 1, tzinfo=timezone.utc)]
    monkeypatch.setattr(mod, "_utc_now", lambda: now[0])
    original_payload = mod._capability_payload
    payload_count = 0

    def expire_after_payloads(kind, *, child_pid, values):
        nonlocal payload_count
        payload = original_payload(kind, child_pid=child_pid, values=values)
        payload_count += 1
        if payload_count == 2:
            now[0] = datetime(2100, 1, 1, tzinfo=timezone.utc)
        return payload

    writes: list[bytes] = []
    monkeypatch.setattr(mod, "_capability_payload", expire_after_payloads)
    monkeypatch.setattr(
        mod,
        "_write_all",
        lambda _descriptor, payload: writes.append(payload),
    )
    child = QuiescibleChildFactory()
    launcher = _launcher(
        tmp_path,
        channel=Channel(
            response=lambda frame, nonce: (
                f"APPROVE SPEC {frame.digest} NONCE {nonce}"
            )
        ),
        child=child,
        transfer_tag="expires-before-frame-publication",
    )

    with pytest.raises(mod.OperatorLaunchRefused, match="expired"):
        launcher.approve_and_spawn(
            launcher.propose(raw_intent="raw", task_id="task")
        )

    assert payload_count == 2
    assert writes == []
    assert child.child.terminated and child.child.waited


def test_capsule_expiry_after_first_bounded_write_stops_second_and_quiesces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _mod()
    now = [datetime(2098, 1, 1, tzinfo=timezone.utc)]
    monkeypatch.setattr(mod, "_utc_now", lambda: now[0])
    writes: list[bytes] = []

    def expire_after_write(_descriptor: int, payload: bytes) -> None:
        writes.append(payload)
        now[0] = datetime(2100, 1, 1, tzinfo=timezone.utc)

    monkeypatch.setattr(mod, "_write_all", expire_after_write)
    child = QuiescibleChildFactory()
    launcher = _launcher(
        tmp_path,
        channel=Channel(
            response=lambda frame, nonce: (
                f"APPROVE SPEC {frame.digest} NONCE {nonce}"
            )
        ),
        child=child,
        transfer_tag="expires-after-first-bounded-write",
    )

    with pytest.raises(mod.OperatorLaunchRefused, match="expired"):
        launcher.approve_and_spawn(
            launcher.propose(raw_intent="raw", task_id="task")
        )

    assert len(writes) == 1
    assert child.child.terminated and child.child.waited


@pytest.mark.parametrize(
    "invalid_now",
    [
        None,
        datetime(2098, 1, 1),
        datetime(2098, 1, 1, tzinfo=timezone(timedelta(hours=1))),
    ],
    ids=["not-datetime", "naive", "non-utc"],
)
def test_capsule_clock_seam_requires_an_exact_aware_utc_datetime(
    monkeypatch: pytest.MonkeyPatch,
    invalid_now: object,
) -> None:
    mod = _mod()
    monkeypatch.setattr(mod, "_utc_now", lambda: invalid_now)

    with pytest.raises(mod.OperatorLaunchRefused, match="clock|UTC|time"):
        mod._issueDiagnosticCapsuleBootstrapAuthority(_bootstrap_scope())


def test_canonical_spec_path_is_create_once_exact_idempotent_and_never_rewritten(
    tmp_path: Path,
) -> None:
    mod = _mod()

    def response(frame, nonce):
        return f"APPROVE SPEC {frame.digest} NONCE {nonce}"

    tag = "one-create-only-spec-path"

    first = _launcher(
        tmp_path,
        worker=Worker(b'{"schema":1,"goal":"sealed"}'),
        channel=Channel(response=response),
        transfer_tag=tag,
    )
    first_result = first.approve_and_spawn(
        first.propose(raw_intent="raw", task_id="task")
    )
    sealed_path = Path(first_result.canonical_spec_path)
    sealed_bytes = b'{"goal":"sealed","schema":1}'
    assert sealed_path.read_bytes() == sealed_bytes

    identical = _launcher(
        tmp_path,
        worker=Worker(b'{"goal":"sealed","schema":1}'),
        channel=Channel(response=response),
        transfer_tag=tag,
    )
    identical_result = identical.approve_and_spawn(
        identical.propose(raw_intent="raw", task_id="task")
    )
    assert identical_result.canonical_spec_path == str(sealed_path)
    assert sealed_path.read_bytes() == sealed_bytes

    differing_child = ChildFactory()
    differing = _launcher(
        tmp_path,
        worker=Worker(b'{"schema":1,"goal":"retargeted"}'),
        channel=Channel(response=response),
        child=differing_child,
        transfer_tag=tag,
    )
    with pytest.raises(mod.OperatorApprovalRefused, match="sealed|differ|existing"):
        differing.approve_and_spawn(
            differing.propose(raw_intent="raw", task_id="task")
        )
    assert differing_child.calls == []
    assert sealed_path.read_bytes() == sealed_bytes


def test_concurrent_differing_specs_publish_exactly_one_sealed_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _mod()
    original_write = mod._atomic_write_once_exact
    barrier = threading.Barrier(2)

    def race_write(path: Path, payload: bytes) -> None:
        barrier.wait()
        original_write(path, payload)

    monkeypatch.setattr(mod, "_atomic_write_once_exact", race_write)

    def response(frame, nonce):
        return f"APPROVE SPEC {frame.digest} NONCE {nonce}"

    children = [ChildFactory(), ChildFactory()]
    launchers = [
        _launcher(
            tmp_path,
            worker=Worker(
                json.dumps(
                    {"schema": 1, "goal": goal},
                    separators=(",", ":"),
                ).encode("utf-8")
            ),
            channel=Channel(response=response),
            child=child,
            transfer_tag="concurrent-sealed-path",
        )
        for goal, child in zip(("alpha", "beta"), children, strict=True)
    ]
    proposals = [
        launcher.propose(raw_intent="raw", task_id="task")
        for launcher in launchers
    ]
    successes: list[object] = []
    refusals: list[BaseException] = []
    result_lock = threading.Lock()

    def approve(index: int) -> None:
        try:
            result = launchers[index].approve_and_spawn(proposals[index])
        except BaseException as exc:
            with result_lock:
                refusals.append(exc)
        else:
            with result_lock:
                successes.append(result)

    threads = [threading.Thread(target=approve, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads)
    assert len(successes) == 1
    assert len(refusals) == 1
    assert isinstance(refusals[0], mod.OperatorApprovalRefused)
    sealed = tuple(tmp_path.rglob("*.json"))
    assert len(sealed) == 1
    assert sealed[0].read_bytes() in {
        b'{"goal":"alpha","schema":1}',
        b'{"goal":"beta","schema":1}',
    }
    assert sum(len(child.calls) for child in children) == 1


def test_canonical_success_recomputes_digest_uses_fresh_nonce_and_control_neutral_frame(tmp_path):
    candidate = b'{"schema":1,"goal":"line\\n\\t\\u0001 safe"}'
    worker = Worker(candidate)
    channel = Channel(response=lambda frame, nonce:
                      f"APPROVE SPEC {frame.digest} NONCE {nonce}")
    launcher = _launcher(tmp_path, worker=worker, channel=channel)
    proposal = launcher.propose(raw_intent="raw is not approval", task_id="task")
    result = launcher.approve_and_spawn(proposal)
    canonical = b'{"goal":"line\\n\\t\\u0001 safe","schema":1}'
    assert result.spec_digest == hashlib.sha256(canonical).hexdigest()
    assert result.spec_digest != "child-lie"
    assert channel.drained is True
    assert "\\n" in channel.frame.rendered and "\\t" in channel.frame.rendered
    assert all(ord(ch) >= 32 or ch == "\n" for ch in channel.frame.rendered)
    assert channel.frame.nonce == "n" * 64


@pytest.mark.parametrize("candidate", [
    b'{"schema":1,"goal":"a","goal":"b"}',
    b'{"schema":1,"goal":"\x1b[31mspoof"}',
    '{"schema":1,"goal":"\u202eevil"}'.encode(),
    '{"schema":1,"goal":"e\u0301"}'.encode(),
    '{"schema":1,"goal":"\ufdd0"}'.encode(),
    b'{"schema":1,"goal":"\xc2\x85"}',
    b'{"schema":1,"goal":"x"}\xff',
    b'{"schema":1,"goal":"x","extra":{"a":{"b":{"c":1}}}}',
    b"x" * (64 * 1024 + 1),
], ids=["duplicate-key", "ansi", "bidi", "non-nfc", "noncharacter", "c1",
        "invalid-utf8", "over-depth", "over-bytes"])
def test_invalid_ambiguous_spoofable_or_overbudget_specs_have_zero_child_effects(tmp_path, candidate):
    child = ChildFactory()
    launcher = _launcher(tmp_path, worker=Worker(candidate), child=child)
    proposal = launcher.propose(raw_intent="raw", task_id="task")
    with pytest.raises(_mod().OperatorApprovalRefused):
        launcher.approve_and_spawn(proposal)
    assert child.calls == []
    assert list(tmp_path.rglob("*.json")) == []


@pytest.mark.parametrize("response", [None, "", "yes", "APPROVE", "--auto-approve",
                                       "APPROVE SPEC stale NONCE stale"])
def test_eof_generic_automation_and_stale_responses_never_spawn(tmp_path, response):
    child = ChildFactory()
    launcher = _launcher(tmp_path, channel=Channel(response=response), child=child)
    proposal = launcher.propose(raw_intent="raw", task_id="task")
    with pytest.raises(_mod().OperatorApprovalRefused):
        launcher.approve_and_spawn(proposal)
    assert child.calls == []


def test_prequeued_input_and_nested_model_ancestry_are_separate_refusals(tmp_path):
    mod = _mod()
    launcher = _launcher(tmp_path, channel=Channel(prequeued=True))
    proposal = launcher.propose(raw_intent="raw", task_id="task")
    with pytest.raises(mod.OperatorApprovalRefused):
        launcher.approve_and_spawn(proposal)
    with pytest.raises(mod.OperatorLaunchRefused):
        mod.OperatorLauncher.assert_outer_ancestry(inside_registered_model_job=True)


@pytest.mark.parametrize("attack", [
    "concurrent_stdout", "console_reopen", "live_descendant", "child_channel_access",
])
def test_exclusive_operator_channel_attacks_have_zero_spawn_effects(tmp_path, attack):
    mod = _mod()
    child = ChildFactory()
    channel = AttackedChannel(attack, mod.OperatorApprovalRefused)
    launcher = _launcher(tmp_path, channel=channel, child=child)
    proposal = launcher.propose(raw_intent="raw", task_id="task")
    with pytest.raises(mod.OperatorApprovalRefused):
        launcher.approve_and_spawn(proposal)
    assert child.calls == []


@pytest.mark.parametrize("source", ["model_only", "task_state", "copied_evidence", "resume_without_fresh_approval"])
def test_nonoperator_approval_sources_never_authorize(source, tmp_path):
    mod = _mod()
    child = ChildFactory()
    launcher = _launcher(tmp_path, child=child)
    proposal = launcher.propose(raw_intent="raw", task_id="task")
    with pytest.raises(mod.OperatorApprovalRefused):
        launcher.approve_and_spawn(proposal, approval_source=source)
    assert child.calls == []


def test_bare_authorization_argv_is_only_a_request(tmp_path):
    mod = _mod()
    with pytest.raises(mod.OperatorLaunchRefused):
        mod.consume_outer_capabilities(argv=["main.py", "--authorize-trusted-local"],
                                        capability_handles=[])


def test_copied_authorized_outer_fields_do_not_recreate_live_authority() -> None:
    mod = _mod()
    copied = mod.AuthorizedOuterCapabilities(
        transfer_id="a" * 64,
        _token=object(),
    )

    with pytest.raises(mod.OperatorCapabilityRefused, match="live|capability"):
        mod.validate_authorized_outer_capabilities(copied)


def test_authorized_outer_handle_is_two_field_slotted_and_scope_opaque(
    tmp_path: Path,
) -> None:
    mod = _mod()
    live = _consume_same_process_outer(tmp_path)

    assert [item.name for item in fields(live)] == ["transfer_id", "_token"]
    assert not hasattr(live, "__dict__")
    assert mod.validate_authorized_outer_capabilities(live) is live
    for leaked_name in (
        "authorized",
        "repository_attestation_digest",
        "expected_base_sha",
        "task_id",
        "spec_digest",
        "_process_capability",
        "scope",
    ):
        assert not hasattr(live, leaked_name)


def test_outer_handle_copy_construction_and_id_token_splicing_are_refused(
    tmp_path: Path,
) -> None:
    mod = _mod()
    first = _consume_same_process_outer(tmp_path, transfer_tag=7)
    second = _consume_same_process_outer(tmp_path, transfer_tag=8)

    for forged in (
        replace(first),
        mod.AuthorizedOuterCapabilities(
            transfer_id=first.transfer_id,
            _token=first._token,
        ),
    ):
        with pytest.raises(mod.OperatorCapabilityRefused, match="live|issuer|transfer"):
            mod.validate_authorized_outer_capabilities(forged)

    transfer_retarget = _consume_same_process_outer(tmp_path, transfer_tag=9)
    object.__setattr__(transfer_retarget, "transfer_id", second.transfer_id)
    with pytest.raises(mod.OperatorCapabilityRefused, match="live|issuer|transfer"):
        mod.validate_authorized_outer_capabilities(transfer_retarget)

    token_retarget = _consume_same_process_outer(tmp_path, transfer_tag=10)
    object.__setattr__(token_retarget, "_token", second._token)
    with pytest.raises(mod.OperatorCapabilityRefused, match="live|issuer|transfer"):
        mod.validate_authorized_outer_capabilities(token_retarget)

    object.__setattr__(first, "transfer_id", second.transfer_id)
    object.__setattr__(first, "_token", second._token)
    with pytest.raises(mod.OperatorCapabilityRefused, match="live|issuer|transfer"):
        mod.validate_authorized_outer_capabilities(first)


def test_outer_issuer_scope_in_place_retarget_is_detected_by_independent_digest(
    tmp_path: Path,
) -> None:
    mod = _mod()
    live = _consume_same_process_outer(tmp_path, transfer_tag=11)
    issued = mod._OUTER_CAPABILITY_REGISTRY[live.transfer_id]

    object.__setattr__(issued.scope, "task_id", "retargeted-task")

    with pytest.raises(mod.OperatorCapabilityRefused, match="scope|issuer|live"):
        mod.validate_authorized_outer_capabilities(live)


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("task_id", 123),
        ("spec_schema", "1"),
        ("canonical_spec_length", True),
        ("controller_generation", "7"),
        ("run_revision", False),
        ("source_snapshot_receipt_digest", 0),
    ],
)
def test_outer_wire_scope_requires_exact_types_without_string_coercion(
    field_name: str,
    invalid_value: object,
) -> None:
    mod = _mod()

    with pytest.raises(
        mod.OperatorCapabilityRefused,
        match="type|typed|capsule bootstrap scope is invalid",
    ):
        _consume_wire_frames(overrides={field_name: invalid_value})


@pytest.mark.parametrize(
    "second_override",
    [
        {"raw_intent_digest": "9" * 64},
        {"canonical_spec_length": 27},
        {"controller_generation": 8},
        {"source_snapshot_receipt_digest": "9" * 64},
    ],
)
def test_outer_wire_frames_must_exact_match_every_common_binding(
    second_override: dict[str, object],
) -> None:
    mod = _mod()

    with pytest.raises(mod.OperatorCapabilityRefused, match="same scope|binding"):
        _consume_wire_frames(second_overrides=second_override)


def test_outer_wire_frames_bind_capsule_scope_dynamic_scope_and_split_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _mod()
    captured: list[bytes] = []
    original_write = mod._write_all

    def capture_and_write(descriptor: int, payload: bytes) -> None:
        captured.append(payload)
        original_write(descriptor, payload)

    monkeypatch.setattr(mod, "_write_all", capture_and_write)
    live = _consume_same_process_outer(tmp_path, transfer_tag=23)
    assert mod.validate_authorized_outer_capabilities(live) is live
    payloads = [mod._parse_payload(payload) for payload in captured]
    assert len(payloads) == 2

    common_fields = set(mod.CAPSULE_BOOTSTRAP_SCOPE_WIRE_FIELDS) | {
        "version",
        "child_pid",
        "launch_id",
        "task_id",
        "raw_intent_digest",
        "spec_schema",
        "canonical_spec_length",
        "spec_digest",
        "approval_nonce",
        "launch_secret_digest",
        "approval_secret_digest",
    }
    assert all(common_fields <= set(payload) for payload in payloads)
    assert all(payloads[0][name] == payloads[1][name] for name in common_fields)
    assert payloads[0]["raw_intent_digest"] == hashlib.sha256(
        b"do safe work"
    ).hexdigest()
    assert payloads[0]["spec_schema"] == 1
    assert payloads[0]["canonical_spec_length"] == len(
        b'{"goal":"safe","schema":1}'
    )
    resolved = mod._resolve_authorized_outer_capabilities(live)
    assert {
        name: payloads[0][name]
        for name in mod.CAPSULE_BOOTSTRAP_SCOPE_WIRE_FIELDS
    } == resolved.bootstrap_scope.wire_mapping()
    assert payloads[0]["controller_generation"] == 7

    secrets_by_kind = {
        payload["kind"]: payload["one_time_secret"] for payload in payloads
    }
    assert secrets_by_kind["launch"] != secrets_by_kind["spec_approval"]
    assert hashlib.sha256(secrets_by_kind["launch"].encode("ascii")).hexdigest() == (
        payloads[0]["launch_secret_digest"]
    )
    assert hashlib.sha256(
        secrets_by_kind["spec_approval"].encode("ascii")
    ).hexdigest() == payloads[0]["approval_secret_digest"]


def test_outer_transfer_revalidates_current_pid_on_every_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _mod()
    live = _consume_same_process_outer(tmp_path, transfer_tag=31)
    original_pid = os.getpid()
    assert mod.validate_authorized_outer_capabilities(live) is live

    monkeypatch.setattr(mod.os, "getpid", lambda: original_pid + 1)

    with pytest.raises(mod.OperatorCapabilityPidMismatch, match="PID"):
        mod.validate_authorized_outer_capabilities(live)
    with pytest.raises(mod.OperatorCapabilityPidMismatch, match="PID"):
        mod._resolve_authorized_outer_capabilities(live)


def test_outer_scope_digest_binds_domain_version_and_every_issuer_field(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _mod()
    live = _consume_same_process_outer(tmp_path, transfer_tag=32)
    issued = mod._OUTER_CAPABILITY_REGISTRY[live.transfer_id]
    assert len(issued.scope_digest) == 32

    monkeypatch.setattr(
        mod,
        "_OUTER_SCOPE_DIGEST_DOMAIN",
        "galaxy.authorized-outer-capability.retargeted",
    )

    with pytest.raises(mod.OperatorCapabilityRefused, match="live|scope"):
        mod.validate_authorized_outer_capabilities(live)


@pytest.mark.parametrize(
    ("field_name", "retargeted"),
    [
        ("protocol_version", 1),
        ("bootstrap_scope", None),
        ("task_id", "other-task"),
        ("raw_intent_digest", "0" * 64),
        ("spec_schema", 2),
        ("canonical_spec_length", 27),
        ("spec_digest", "0" * 64),
        ("approval_nonce", "0" * 64),
        ("child_pid", 1),
        ("launch_id", "0" * 64),
        ("launch_secret_digest", "0" * 64),
        ("approval_secret_digest", "0" * 64),
        ("argv_digest", "0" * 64),
        ("launch_frame_digest", "0" * 64),
        ("approval_frame_digest", "0" * 64),
        ("process_capability", None),
    ],
)
def test_every_outer_issuer_scope_field_is_covered_by_independent_digest(
    tmp_path: Path,
    field_name: str,
    retargeted: object,
) -> None:
    mod = _mod()
    live = _consume_same_process_outer(tmp_path, transfer_tag=39)
    issued = mod._OUTER_CAPABILITY_REGISTRY[live.transfer_id]

    if field_name == "bootstrap_scope":
        retargeted = replace(
            issued.scope.bootstrap_scope,
            controller_generation=(
                issued.scope.bootstrap_scope.controller_generation + 1
            ),
        )

    object.__setattr__(issued.scope, field_name, retargeted)

    with pytest.raises(mod.OperatorCapabilityRefused, match="live|scope|issuer"):
        mod.validate_authorized_outer_capabilities(live)


def test_outer_resolver_calls_pid_and_returns_with_transfer_lock_released(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _mod()
    live = _consume_same_process_outer(tmp_path, transfer_tag=33)
    real_getpid = os.getpid
    pid_probe_observed_unlocked: list[bool] = []

    def assert_pid_outside_registry_lock() -> int:
        acquired: list[bool] = []

        def contender() -> None:
            got = mod._OUTER_CAPABILITY_REGISTRY_LOCK.acquire(timeout=1)
            acquired.append(got)
            if got:
                mod._OUTER_CAPABILITY_REGISTRY_LOCK.release()

        thread = threading.Thread(target=contender)
        thread.start()
        thread.join(timeout=2)
        pid_probe_observed_unlocked.append(acquired == [True])
        return real_getpid()

    monkeypatch.setattr(mod.os, "getpid", assert_pid_outside_registry_lock)
    resolved = mod._resolve_authorized_outer_capabilities(live)

    assert pid_probe_observed_unlocked == [True]
    acquired_after = mod._OUTER_CAPABILITY_REGISTRY_LOCK.acquire(timeout=1)
    assert acquired_after
    mod._OUTER_CAPABILITY_REGISTRY_LOCK.release()
    assert resolved.child_pid == real_getpid()


def test_outer_handle_copy_deepcopy_pickle_and_manual_clone_are_refused(
    tmp_path: Path,
) -> None:
    mod = _mod()
    live = _consume_same_process_outer(tmp_path, transfer_tag=34)
    manual = object.__new__(mod.AuthorizedOuterCapabilities)
    object.__setattr__(manual, "transfer_id", live.transfer_id)
    object.__setattr__(manual, "_token", live._token)
    clones = [
        copy.copy(live),
        copy.deepcopy(live),
        pickle.loads(pickle.dumps(live)),
        manual,
    ]

    for clone in clones:
        assert clone is not live
        assert clone != live
        with pytest.raises(mod.OperatorCapabilityRefused, match="live|transfer"):
            mod.validate_authorized_outer_capabilities(clone)


def test_outer_handle_repr_asdict_and_json_do_not_disclose_issuer_scope_or_secrets(
    tmp_path: Path,
) -> None:
    live = _consume_same_process_outer(tmp_path, transfer_tag=35)
    rendered = "\n".join(
        (
            repr(live),
            repr(asdict(live)),
            json.dumps(asdict(live), default=lambda _value: "<opaque>"),
        )
    )

    for forbidden in (
        "do safe work",
        "task",
        "d" * 64,
        "a" * 40,
        "launch_secret",
        "approval_secret",
        "process_capability",
    ):
        assert forbidden not in rendered


def test_duplicate_generated_transfer_id_never_overwrites_existing_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _mod()
    first = _consume_same_process_outer(tmp_path, transfer_tag=36)
    original_record = mod._OUTER_CAPABILITY_REGISTRY[first.transfer_id]
    generated = iter((first.transfer_id, "9" * 64))
    monkeypatch.setattr(mod.secrets, "token_hex", lambda _width: next(generated))

    second = _consume_wire_frames()

    assert second.transfer_id == "9" * 64
    assert mod._OUTER_CAPABILITY_REGISTRY[first.transfer_id] is original_record
    assert mod.validate_authorized_outer_capabilities(first) is first
    assert mod.validate_authorized_outer_capabilities(second) is second


def test_outer_frames_reject_duplicate_keys_and_noncanonical_json() -> None:
    mod = _mod()
    launch, approval = _desired_wire_payloads()
    canonical_launch = json.dumps(
        launch, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    canonical_approval = json.dumps(
        approval, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    task_binding = (
        b'"task_id":'
        + json.dumps(launch["task_id"], separators=(",", ":")).encode("utf-8")
    )
    duplicate_launch = canonical_launch.replace(
        task_binding,
        task_binding + b',"task_id":"retargeted"',
    )
    assert duplicate_launch != canonical_launch

    with pytest.raises(mod.OperatorCapabilityRefused, match="duplicate"):
        _consume_raw_frames(
            (_frame_body(duplicate_launch), _frame_body(canonical_approval))
        )

    noncanonical_launch = json.dumps(
        launch, ensure_ascii=False, indent=1, sort_keys=False
    ).encode("utf-8")
    with pytest.raises(mod.OperatorCapabilityRefused, match="canonical"):
        _consume_raw_frames(
            (_frame_body(noncanonical_launch), _frame_body(canonical_approval))
        )


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("missing-version", "schema"),
        ("unknown-field", "schema"),
        ("version-1", "version"),
        ("version-3", "version"),
    ],
)
def test_outer_frames_require_the_exact_v2_wire_schema(
    mutation: str,
    expected: str,
) -> None:
    mod = _mod()
    launch, approval = _desired_wire_payloads()
    if mutation == "missing-version":
        launch.pop("version")
    elif mutation == "unknown-field":
        approval["future_authority"] = "forbidden"
    else:
        version = int(mutation.rpartition("-")[2])
        launch["version"] = version
        approval["version"] = version

    with pytest.raises(mod.OperatorCapabilityRefused, match=expected):
        _consume_raw_frames(
            (_canonical_wire_frame(launch), _canonical_wire_frame(approval))
        )


def test_outer_consume_refuses_one_extra_complete_frame_before_reading_any() -> None:
    mod = _mod()
    launch, approval = _desired_wire_payloads()
    frames = (
        _canonical_wire_frame(launch),
        _canonical_wire_frame(approval),
        _canonical_wire_frame(launch),
    )
    readers: list[int] = []
    writers: list[int] = []
    try:
        for _ in range(3):
            reader, writer = os.pipe()
            readers.append(reader)
            writers.append(writer)
        for writer, frame in zip(writers, frames, strict=True):
            mod._write_all(writer, frame)
            os.close(writer)
        writers.clear()
        with mod._PARENT_BINDINGS_LOCK:
            for reader in readers:
                mod._PARENT_BINDINGS[reader] = os.getpid()

        with pytest.raises(mod.OperatorLaunchRefused, match="two live"):
            mod.consume_outer_capabilities(
                argv=["main.py", "--operator-child-launch"],
                capability_handles=readers,
            )
    finally:
        for descriptor in readers + writers:
            with mod._PARENT_BINDINGS_LOCK:
                mod._PARENT_BINDINGS.pop(descriptor, None)
            os.close(descriptor)


def test_outer_frames_require_exact_kind_multiset_but_accept_reversed_handles() -> None:
    mod = _mod()
    launch, approval = _desired_wire_payloads()

    def canonical_frame(payload: dict[str, object]) -> bytes:
        body = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        return _frame_body(body)

    frames = (canonical_frame(launch), canonical_frame(approval))
    live = _consume_raw_frames(frames, reverse_handles=True)
    assert mod.validate_authorized_outer_capabilities(live) is live

    duplicate_kind = ({**approval, "kind": "launch"}, launch)
    with pytest.raises(mod.OperatorCapabilityRefused, match="kinds|duplicated"):
        _consume_raw_frames(
            (
                canonical_frame(duplicate_kind[0]),
                canonical_frame(duplicate_kind[1]),
            )
        )


def test_exact_outer_frame_pair_replay_is_refused_across_fresh_handles() -> None:
    mod = _mod()
    launch, approval = _desired_wire_payloads()

    def canonical_frame(payload: dict[str, object]) -> bytes:
        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return _frame_body(body)

    frames = (canonical_frame(launch), canonical_frame(approval))
    live = _consume_raw_frames(frames)
    assert mod.validate_authorized_outer_capabilities(live) is live

    with pytest.raises(mod.OperatorCapabilityRefused, match="already consumed|replay"):
        _consume_raw_frames(frames)


def test_exact_outer_frame_pair_replay_is_refused_when_handle_order_is_reversed() -> None:
    mod = _mod()
    launch, approval = _desired_wire_payloads()
    frames = (_canonical_wire_frame(launch), _canonical_wire_frame(approval))

    live = _consume_raw_frames(frames)
    assert mod.validate_authorized_outer_capabilities(live) is live
    with pytest.raises(mod.OperatorCapabilityRefused, match="already consumed|replay"):
        _consume_raw_frames(frames, reverse_handles=True)


def test_concurrent_consumers_of_one_exact_frame_pair_have_exactly_one_success() -> None:
    mod = _mod()
    launch, approval = _desired_wire_payloads()
    frames = (_canonical_wire_frame(launch), _canonical_wire_frame(approval))
    barrier = threading.Barrier(2)
    successes: list[object] = []
    refusals: list[BaseException] = []
    result_lock = threading.Lock()

    def consume() -> None:
        barrier.wait()
        try:
            result = _consume_raw_frames(frames)
        except BaseException as exc:
            with result_lock:
                refusals.append(exc)
        else:
            with result_lock:
                successes.append(result)

    threads = [threading.Thread(target=consume) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads)
    assert len(successes) == 1
    assert len(refusals) == 1
    assert isinstance(refusals[0], mod.OperatorCapabilityRefused)
    assert "consumed" in str(refusals[0]) or "replay" in str(refusals[0])
    assert mod.validate_authorized_outer_capabilities(successes[0]) is successes[0]


def test_fresh_dynamic_pairs_with_identical_static_capsule_scope_are_distinct() -> None:
    mod = _mod()
    first_launch, first_approval = _desired_wire_payloads(
        transfer_tag="shared-static-scope"
    )
    second_launch = dict(first_launch)
    second_approval = dict(first_approval)
    second_launch_secret = _digest("second-launch-secret", "shared-static-scope")
    second_approval_secret = _digest("second-approval-secret", "shared-static-scope")
    fresh_common = {
        "launch_id": _digest("second-launch-id", "shared-static-scope"),
        "approval_nonce": _digest("second-approval-nonce", "shared-static-scope"),
        "launch_secret_digest": hashlib.sha256(
            second_launch_secret.encode("ascii")
        ).hexdigest(),
        "approval_secret_digest": hashlib.sha256(
            second_approval_secret.encode("ascii")
        ).hexdigest(),
    }
    second_launch.update(fresh_common)
    second_approval.update(fresh_common)
    second_launch["one_time_secret"] = second_launch_secret
    second_approval["one_time_secret"] = second_approval_secret

    first = _consume_raw_frames(
        (
            _canonical_wire_frame(first_launch),
            _canonical_wire_frame(first_approval),
        )
    )
    second = _consume_raw_frames(
        (
            _canonical_wire_frame(second_launch),
            _canonical_wire_frame(second_approval),
        )
    )
    first_scope = mod._resolve_authorized_outer_capabilities(first)
    second_scope = mod._resolve_authorized_outer_capabilities(second)

    assert first is not second
    assert first.transfer_id != second.transfer_id
    assert first_scope.bootstrap_scope == second_scope.bootstrap_scope
    assert first_scope.launch_id != second_scope.launch_id


def test_outer_frames_reject_duplicate_handle_equal_secrets_and_read_after_preview_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _mod()
    launch, approval = _desired_wire_payloads()

    def canonical_frame(payload: dict[str, object]) -> bytes:
        body = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        return _frame_body(body)

    frames = (canonical_frame(launch), canonical_frame(approval))
    with pytest.raises(mod.OperatorCapabilityRefused):
        _consume_raw_frames(frames, duplicate_first_handle=True)

    same_secret = launch["one_time_secret"]
    same_digest = hashlib.sha256(str(same_secret).encode("ascii")).hexdigest()
    equal_launch = {
        **launch,
        "launch_secret_digest": same_digest,
        "approval_secret_digest": same_digest,
    }
    equal_approval = {
        **approval,
        "one_time_secret": same_secret,
        "launch_secret_digest": same_digest,
        "approval_secret_digest": same_digest,
    }
    with pytest.raises(mod.OperatorCapabilityRefused, match="split"):
        _consume_raw_frames(
            (canonical_frame(equal_launch), canonical_frame(equal_approval))
        )

    original_peek = mod._peek_capability
    changed = False

    def drift_after_preview(handle: int):
        nonlocal changed
        parsed, preview, reader = original_peek(handle)
        if not changed:
            changed = True
            return parsed, preview, lambda: preview + b"x"
        return parsed, preview, reader

    monkeypatch.setattr(mod, "_peek_capability", drift_after_preview)
    with pytest.raises(mod.OperatorCapabilityRefused, match="preview|changed"):
        _consume_raw_frames(frames)


def test_atomic_downstream_bundle_uses_the_exact_detached_outer_and_capsule_scopes(
    tmp_path: Path,
) -> None:
    mod = _mod()
    bootstrap = importlib.import_module("platform_core.runtime.bootstrap_authority")
    state = importlib.import_module("platform_core.runtime.controller_state")
    candidate = importlib.import_module("platform_core.runtime.candidate")
    live = _consume_same_process_outer(tmp_path, transfer_tag=37)
    resolved = mod._resolve_authorized_outer_capabilities(live)
    bundle = bootstrap.deriveInstalledBootstrapAuthorities(outer_capabilities=live)
    controller = bundle.controller_state_authority
    controller_scope = state._controllerAuthorityScope(controller)
    issuer = bundle.landing_issuer
    admission = bundle.run_admission

    assert controller_scope.outer_scope_digest == resolved.scope_digest
    assert controller_scope.capsule_scope_digest == resolved.bootstrap_scope.digest()
    assert controller_scope.process_capability is resolved.process_capability
    assert controller_scope.child_pid == resolved.child_pid
    assert issuer._process_capability is resolved.process_capability
    assert admission._process_capability is resolved.process_capability
    assert admission.child_pid == resolved.child_pid
    assert admission.run_id == resolved.bootstrap_scope.run_id
    assert admission.canonical_repository_id == (
        resolved.bootstrap_scope.canonical_repository_id
    )
    assert (
        state.deriveInstalledControllerStateAuthority(outer_capabilities=live)
        is controller
    )
    replay_issuer, replay_admission = candidate.deriveLandingAuthorityIssuer(
        outer_capabilities=live
    )
    assert replay_issuer is issuer
    assert replay_admission is admission


@pytest.mark.skipif(os.name != "nt", reason="Win32 anonymous-handle boundary")
def test_immediate_win32_child_waits_for_complete_frames_and_parent_copies_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _mod()
    child = ImmediateRealChildFactory(tmp_path)
    channel = Channel(
        response=lambda frame, nonce: f"APPROVE SPEC {frame.digest} NONCE {nonce}"
    )
    launcher = _launcher(tmp_path, channel=channel, child=child)
    original_write = mod._write_all
    first_write_pending = True

    def delayed_first_write(descriptor: int, payload: bytes) -> None:
        nonlocal first_write_pending
        if first_write_pending:
            first_write_pending = False
            time.sleep(0.08)
            assert os.write(descriptor, payload[:2]) == 2
            time.sleep(0.08)
            original_write(descriptor, payload[2:])
            return
        original_write(descriptor, payload)

    monkeypatch.setattr(mod, "_write_all", delayed_first_write)
    try:
        launcher.approve_and_spawn(
            launcher.propose(raw_intent="raw", task_id="task")
        )
        capability_handles = child.calls[0]["capability_handles"]
        assert isinstance(capability_handles, tuple)
        assert all(type(descriptor) is int for descriptor in capability_handles)
        parent_descriptors: tuple[int, ...] = capability_handles
        assert child.process is not None
        child_authority_pid = getattr(child.process, "authority_pid")

        assert child.result() == {
            "authorized": True,
            "pid": child_authority_pid,
        }
        with mod._PARENT_BINDINGS_LOCK:
            assert not any(
                descriptor in mod._PARENT_BINDINGS
                for descriptor in parent_descriptors
            )
        for descriptor in parent_descriptors:
            with pytest.raises(OSError):
                os.get_inheritable(descriptor)
    finally:
        child.close()


def test_trailing_bytes_and_second_canonical_frame_are_refused() -> None:
    mod = _mod()
    launch, approval = _desired_wire_payloads()

    def canonical_frame(payload: dict[str, object]) -> bytes:
        body = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        return _frame_body(body)

    launch_frame = canonical_frame(launch)
    approval_frame = canonical_frame(approval)
    second_canonical_frame = _frame_body(b"{}")
    for trailing in (b"x", second_canonical_frame):
        with pytest.raises(mod.OperatorCapabilityRefused, match="trailing|frame|closed"):
            _consume_raw_frames((launch_frame + trailing, approval_frame))


def test_duplicate_handles_refuse_before_any_peek_or_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _mod()
    observed: list[int] = []

    def forbidden_peek(handle: int):
        observed.append(handle)
        raise AssertionError("duplicate handles reached the pipe boundary")

    monkeypatch.setattr(mod, "_peek_capability", forbidden_peek)
    with mod._PARENT_BINDINGS_LOCK:
        mod._PARENT_BINDINGS[41] = os.getpid()

    with pytest.raises(mod.OperatorCapabilityRefused, match="distinct|duplicate"):
        mod.consume_outer_capabilities(
            argv=["main.py", "--operator-child-launch"],
            capability_handles=[41, 41],
        )
    assert observed == []
    with mod._PARENT_BINDINGS_LOCK:
        assert 41 not in mod._PARENT_BINDINGS


def test_constant_transfer_id_collision_is_bounded_and_preserves_original(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _mod()
    first = _consume_same_process_outer(tmp_path, transfer_tag=38)
    original = mod._OUTER_CAPABILITY_REGISTRY[first.transfer_id]
    assert type(mod._MAX_TRANSFER_ID_ATTEMPTS) is int
    assert 1 <= mod._MAX_TRANSFER_ID_ATTEMPTS <= 128
    monkeypatch.setattr(
        mod.secrets,
        "token_hex",
        lambda _width: first.transfer_id,
    )

    with pytest.raises(mod.OperatorCapabilityRefused, match="collision|unique|transfer"):
        _consume_wire_frames()

    assert mod._OUTER_CAPABILITY_REGISTRY[first.transfer_id] is original
    assert mod.validate_authorized_outer_capabilities(first) is first


def test_invalid_postspawn_pid_quiesces_child_and_cleans_every_parent_handle(
    tmp_path: Path,
) -> None:
    mod = _mod()

    class InvalidPidChild:
        pid = None
        authority_pid = None

        def __init__(self) -> None:
            self.terminated = False
            self.waited = False

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout=None) -> int:
            del timeout
            self.waited = True
            return 0

    class InvalidPidFactory(ChildFactory):
        def __init__(self) -> None:
            super().__init__()
            self.child = InvalidPidChild()

        def spawn(self, **kwargs):
            self.calls.append(kwargs)
            return self.child

    factory = InvalidPidFactory()
    launcher = _launcher(
        tmp_path,
        child=factory,
        channel=Channel(
            response=lambda frame, nonce: (
                f"APPROVE SPEC {frame.digest} NONCE {nonce}"
            )
        ),
    )

    with pytest.raises(mod.OperatorLaunchRefused, match="PID|child"):
        launcher.approve_and_spawn(
            launcher.propose(raw_intent="raw", task_id="task")
        )

    descriptors = tuple(factory.calls[0]["capability_handles"])
    assert factory.child.terminated and factory.child.waited
    with mod._PARENT_BINDINGS_LOCK:
        assert not any(descriptor in mod._PARENT_BINDINGS for descriptor in descriptors)
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.get_inheritable(descriptor)


def test_resistant_invalid_pid_child_raises_typed_containment_failure_with_evidence(
    tmp_path: Path,
) -> None:
    mod = _mod()

    class ResistantChild:
        pid = None
        authority_pid = None

        def __init__(self) -> None:
            self.actions: list[str] = []

        def poll(self):
            self.actions.append("poll")
            return None

        def terminate(self) -> None:
            self.actions.append("terminate")
            raise OSError("resisted terminate")

        def wait(self, timeout=None) -> int:
            del timeout
            self.actions.append("wait")
            raise TimeoutError("still live")

        def kill(self) -> None:
            self.actions.append("kill")
            raise OSError("resisted kill")

    class ResistantFactory(ChildFactory):
        def __init__(self) -> None:
            super().__init__()
            self.child = ResistantChild()

        def spawn(self, **kwargs):
            self.calls.append(kwargs)
            return self.child

    factory = ResistantFactory()
    launcher = _launcher(
        tmp_path,
        child=factory,
        channel=Channel(
            response=lambda frame, nonce: (
                f"APPROVE SPEC {frame.digest} NONCE {nonce}"
            )
        ),
    )

    with pytest.raises(mod.OperatorChildContainmentFailure) as caught:
        launcher.approve_and_spawn(
            launcher.propose(raw_intent="raw", task_id="task")
        )

    assert isinstance(caught.value.__cause__, mod.OperatorLaunchRefused)
    assert "PID" in str(caught.value.__cause__)
    assert caught.value.evidence.terminal_observed is False
    assert caught.value.evidence.attempts == (
        "poll_initial",
        "terminate",
        "wait_after_terminate",
        "kill",
        "wait_after_kill",
        "poll_final",
    )
    assert caught.value.evidence.failure_types == (
        "terminate:OSError",
        "wait_after_terminate:TimeoutError",
        "kill:OSError",
        "wait_after_kill:TimeoutError",
    )
    assert factory.child.actions == [
        "poll",
        "terminate",
        "wait",
        "kill",
        "wait",
        "poll",
    ]
    descriptors = tuple(factory.calls[0]["capability_handles"])
    with mod._PARENT_BINDINGS_LOCK:
        assert not any(descriptor in mod._PARENT_BINDINGS for descriptor in descriptors)
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.get_inheritable(descriptor)


def test_payload_write_failure_quiesces_child_cleans_bindings_and_allows_fd_reuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _mod()

    class QuiescibleChild:
        pid = os.getpid()
        authority_pid = os.getpid()

        def __init__(self) -> None:
            self.terminated = False
            self.waited = False

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout=None) -> int:
            del timeout
            self.waited = True
            return 0

    class QuiescibleFactory(ChildFactory):
        def __init__(self) -> None:
            super().__init__()
            self.child = QuiescibleChild()

        def spawn(self, **kwargs):
            self.calls.append(kwargs)
            return self.child

    factory = QuiescibleFactory()
    launcher = _launcher(
        tmp_path,
        child=factory,
        channel=Channel(
            response=lambda frame, nonce: (
                f"APPROVE SPEC {frame.digest} NONCE {nonce}"
            )
        ),
    )
    monkeypatch.setattr(
        mod,
        "_write_all",
        lambda _descriptor, _payload: (_ for _ in ()).throw(
            OSError("injected payload write failure")
        ),
    )

    with pytest.raises(OSError, match="payload write failure"):
        launcher.approve_and_spawn(
            launcher.propose(raw_intent="raw", task_id="task")
        )

    descriptors = tuple(factory.calls[0]["capability_handles"])
    assert factory.child.terminated and factory.child.waited
    with mod._PARENT_BINDINGS_LOCK:
        assert not any(descriptor in mod._PARENT_BINDINGS for descriptor in descriptors)
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.get_inheritable(descriptor)

    reused_reader, reused_writer = os.pipe()
    try:
        with mod._PARENT_BINDINGS_LOCK:
            assert reused_reader not in mod._PARENT_BINDINGS
            assert reused_writer not in mod._PARENT_BINDINGS
    finally:
        os.close(reused_reader)
        os.close(reused_writer)


@pytest.mark.parametrize("failure_call", [1, 2])
def test_pipe_pair_is_recorded_before_each_inheritability_mutation(
    monkeypatch: pytest.MonkeyPatch,
    failure_call: int,
) -> None:
    mod = _mod()
    original_pipe = mod.os.pipe
    original_set_inheritable = mod.os.set_inheritable
    original_get_inheritable = mod.os.get_inheritable
    original_close = mod.os.close
    created: list[int] = []
    calls = 0

    def recording_pipe():
        reader, writer = original_pipe()
        created.extend((reader, writer))
        return reader, writer

    def injected_set_inheritable(descriptor: int, inheritable: bool) -> None:
        nonlocal calls
        calls += 1
        if calls == failure_call:
            raise OSError(f"injected set-inheritable failure {failure_call}")
        original_set_inheritable(descriptor, inheritable)

    monkeypatch.setattr(mod.os, "pipe", recording_pipe)
    monkeypatch.setattr(mod.os, "set_inheritable", injected_set_inheritable)
    try:
        with pytest.raises(OSError, match="set-inheritable failure"):
            mod._new_capability_pipes()
        assert len(created) == 2
        for descriptor in created:
            with pytest.raises(OSError):
                original_get_inheritable(descriptor)
    finally:
        for descriptor in created:
            try:
                original_close(descriptor)
            except OSError:
                pass


def test_nonreading_full_capability_pipe_fails_within_bounded_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _mod()
    monkeypatch.setattr(mod, "_CAPABILITY_WRITE_SECONDS", 0.03, raising=False)
    monkeypatch.setattr(mod, "_CAPABILITY_WRITE_POLL_SECONDS", 0.001, raising=False)
    reader, writer = os.pipe()
    failures: list[BaseException] = []

    def fill_without_reader() -> None:
        try:
            mod._write_all(writer, b"x" * (4 * 1024 * 1024))
        except BaseException as exc:
            failures.append(exc)

    thread = threading.Thread(target=fill_without_reader)
    started = time.monotonic()
    thread.start()
    thread.join(timeout=0.5)
    try:
        if thread.is_alive():
            os.close(reader)
            reader = -1
            thread.join(timeout=1)
        elapsed = time.monotonic() - started
        assert not thread.is_alive()
        assert elapsed < 0.75
        assert len(failures) == 1
        assert isinstance(failures[0], mod.OperatorLaunchRefused)
        assert "deadline" in str(failures[0]) or "bounded" in str(failures[0])
    finally:
        for descriptor in (reader, writer):
            if descriptor < 0:
                continue
            try:
                os.close(descriptor)
            except OSError:
                pass


def test_closed_writer_is_retired_before_later_failure_can_close_reused_fd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _mod()
    original_write = mod._write_all
    original_close = mod.os.close
    original_pipe = mod.os.pipe
    original_get_inheritable = mod.os.get_inheritable
    first_writer: list[int] = []
    reused_pair: list[int] = []
    writes = 0

    def fail_second_write(descriptor: int, payload: bytes) -> None:
        nonlocal writes
        writes += 1
        if writes == 1:
            first_writer.append(descriptor)
            original_write(descriptor, payload)
            return
        raise OSError("injected second-frame failure")

    def close_then_reuse(descriptor: int) -> None:
        if first_writer == [descriptor] and not reused_pair:
            original_close(descriptor)
            source_reader, source_writer = original_pipe()
            if source_reader != descriptor:
                os.dup2(source_reader, descriptor)
                original_close(source_reader)
            reused_pair.extend((descriptor, source_writer))
            return
        original_close(descriptor)

    monkeypatch.setattr(mod, "_write_all", fail_second_write)
    monkeypatch.setattr(mod.os, "close", close_then_reuse)
    child = QuiescibleChildFactory()
    launcher = _launcher(
        tmp_path,
        channel=Channel(
            response=lambda frame, nonce: (
                f"APPROVE SPEC {frame.digest} NONCE {nonce}"
            )
        ),
        child=child,
        transfer_tag="closed-writer-fd-reuse",
    )
    try:
        with pytest.raises(OSError, match="second-frame failure"):
            launcher.approve_and_spawn(
                launcher.propose(raw_intent="raw", task_id="task")
            )

        assert len(reused_pair) == 2
        original_get_inheritable(reused_pair[0])
        assert child.child.terminated and child.child.waited
    finally:
        for descriptor in reused_pair:
            try:
                original_close(descriptor)
            except OSError:
                pass


def test_postapproval_handles_are_anonymous_one_use_noninheritable_and_absent_from_surfaces(tmp_path):
    mod = _mod()
    child = RealChildFactory(tmp_path)
    channel = Channel(response=lambda frame, nonce:
                      f"APPROVE SPEC {frame.digest} NONCE {nonce}")
    launcher = _launcher(tmp_path, channel=channel, child=child)
    handles = []
    try:
        result = launcher.approve_and_spawn(
            launcher.propose(raw_intent="raw", task_id="task"))
        call = child.calls[0]
        handles = list(call["capability_handles"])
        assert call["stdin"] == call["stdout"] == call["stderr"] == "DEVNULL"
        assert call["controlling_terminal"] is None
        assert len(handles) == 2
        with mod._PARENT_BINDINGS_LOCK:
            assert not any(handle in mod._PARENT_BINDINGS for handle in handles)
        for handle in handles:
            with pytest.raises(OSError):
                os.get_inheritable(handle)
        serialized = json.dumps({
            "argv": call["argv"], "env": call["env"], "task_state": result.task_state,
            "receipts": result.receipts, "logs": result.logs,
        }, default=str)
        assert "OperatorLaunchCapability" not in serialized
        assert "OperatorSpecApprovalCapability" not in serialized
        for handle in handles:
            assert str(handle) not in serialized
        wrong = child.consume_from_wrong_pid(call["argv"], handles)
        assert wrong["authorized"] is False
        assert wrong["error"] == "OperatorCapabilityPidMismatch"
        assert wrong["pid"] != child.processes[0].pid
        right = child.consume_from_bound_pid(call["argv"], handles)
        assert right == {
            "authorized": True,
            "pid": child.processes[0].authority_pid,
            "installed_issuer": True,
            "admission_pid": child.processes[0].authority_pid,
            "copied_outer_refused": True,
            "copied_controller_refused": True,
            "installed_controller": True,
            "runtime_replay": True,
            "runtime_current": True,
            "central_consumers": True,
            "control_roundtrip": True,
            "heartbeat_roundtrip": True,
            "terminal_roundtrip": True,
            "config_bound": True,
        }
        assert result.child_inheritance_probe == []
    finally:
        child.close()
        for handle in handles:
            try:
                os.close(handle)
            except OSError:
                pass
