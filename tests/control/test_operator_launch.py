"""RED behavioral contracts for the outer, operator-owned launch boundary."""
from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import struct
import sys

import pytest


def _mod():
    return importlib.import_module("platform_core.runtime.operator_launch")


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
        return type("RecordedChild", (), {"pid": None})()


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
            " print(json.dumps({'authorized':r.authorized,'pid':__import__('os').getpid()}))\n"
            "except Exception as exc:\n"
            " print(json.dumps({'authorized':False,'error':type(exc).__name__,'pid':__import__('os').getpid()}))\n"
            "finally:\n"
            " [ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(h)) for h in handles]\n"
        )
        for descriptor in capability_fds:
            os.set_inheritable(descriptor, True)
        try:
            proc = subprocess.Popen(
                [sys.executable, "-I", "-S", "-c", code], cwd=self.root, env={},
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
        return proc

    def consume_from_wrong_pid(self, argv, handles):
        wrong, writer = self._spawn_consumer(handles)
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


def _launcher(tmp_path, worker=None, channel=None, child=None):
    mod = _mod()
    return mod.OperatorLauncher(
        repository_attestation_digest="repo", expected_base_sha="a" * 40,
        worker=worker or Worker(), operator_channel=channel or Channel(),
        child_factory=child or ChildFactory(), nonce_factory=lambda: "n" * 64,
        canonical_spec_path=tmp_path / "spec.json",
    )


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
    assert not (tmp_path / "spec.json").exists()


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
        assert all(not os.get_inheritable(h) for h in handles)
        serialized = json.dumps({
            "argv": call["argv"], "env": call["env"], "task_state": result.task_state,
            "receipts": result.receipts, "logs": result.logs,
        }, default=str)
        assert "OperatorLaunchCapability" not in serialized
        assert "OperatorSpecApprovalCapability" not in serialized
        for handle in handles:
            assert str(handle) not in serialized
        with pytest.raises(mod.OperatorCapabilityPidMismatch):
            mod.consume_outer_capabilities(argv=call["argv"], capability_handles=handles)
        wrong = child.consume_from_wrong_pid(call["argv"], handles)
        assert wrong == {"authorized": False, "error": "OperatorCapabilityPidMismatch",
                         "pid": wrong["pid"]}
        assert wrong["pid"] != child.processes[0].pid
        right = child.consume_from_bound_pid(call["argv"], handles)
        assert right == {"authorized": True, "pid": child.processes[0].authority_pid}
        assert result.child_inheritance_probe == []
    finally:
        child.close()
        for handle in handles:
            try:
                os.close(handle)
            except OSError:
                pass
