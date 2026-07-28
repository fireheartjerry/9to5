"""Controller-owned creation and collection of journaled local process resources.

A target process is created unable to execute target code, placed inside its
pre-registered OS cleanup boundary, and assigned a PID-reuse-safe identity.  Only
after the CREATED and STARTED observations are durable is the child released.  The
returned facade owns quiescence and advances the resource to COLLECTED.
"""
from __future__ import annotations

import hashlib
import os
import re
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence, cast

from platform_core.core.fsio import readNoFollowBytes
from platform_core.core.galaxy_evidence import canonical_digest
from platform_core.runtime.attempt_journal import (
    AttemptJournal,
    AttemptPhase,
    IncompleteResourceSet,
    JournalCorruption,
    JournalError,
    MissingResourceSet,
)
from platform_core.runtime.candidate import (
    CloneLease,
    LandingAuthorityIssuer,
    ProcessResourceState,
    ResourceRole,
    RunAdmissionAuthority,
    RunnerKind,
    RuntimeResourceLease,
    RuntimeResourceProbeRefused,
    processStartToken,
)
from platform_core.runtime.worktree import validateCloneLease

_CREATE_BREAKAWAY_FROM_JOB = 0x01000000
_PROCESS_ROLES = frozenset(role for role in ResourceRole if role is not ResourceRole.CREDENTIAL_LEASE)
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_PORTABLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class ProcessLaunchRefused(RuntimeError):
    """A process could not be launched under its exact registered plan."""


_REGISTERED_MANAGER_CONSTRUCTION = object()


def _registered_at(value: str) -> str:
    if type(value) is not str:
        raise TypeError("registered_at must be str")
    if not value:
        raise ValueError("registered_at must be a non-empty ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("registered_at must be a canonical ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("registered_at must include a timezone")
    if parsed.isoformat() != value:
        raise ValueError("registered_at must be a canonical ISO-8601 timestamp")
    return value


def _argv(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise TypeError("argv must be a non-empty sequence of strings")
    result = tuple(values)
    if not result or any(type(item) is not str or not item for item in result):
        raise ValueError("argv must contain non-empty strings")
    return result


def _environment(values: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(values, Mapping):
        raise TypeError("environment must be a mapping")
    result: dict[str, str] = {}
    for name, value in values.items():
        if type(name) is not str or not name or "=" in name or "\x00" in name:
            raise ValueError("environment contains an invalid name")
        if type(value) is not str or "\x00" in value:
            raise ValueError("environment contains an invalid value")
        result[name] = value
    return result


def _cwd(value: str | os.PathLike[str]) -> str:
    path = os.path.abspath(os.fspath(value))
    if not os.path.isabs(path):  # pragma: no cover - abspath guarantees this
        raise ValueError("cwd must resolve to an absolute path")
    return os.path.normcase(path)


def _cleanup_locator(
    *,
    run_id: str,
    transaction_id: str,
    controller_scope_id: str,
    resource_id: str,
    role: ResourceRole,
    ownership_nonce: str,
) -> str:
    identity = canonical_digest(
        {
            "schema": "galaxy.process-cleanup-locator/v1",
            "run_id": run_id,
            "transaction_id": transaction_id,
            "controller_scope_id": controller_scope_id,
            "resource_id": resource_id,
            "role": role.value,
            "ownership_nonce": ownership_nonce,
            "platform": os.name,
        }
    )
    if os.name == "nt":
        return f"Local\\GalaxyR3-{identity}"
    return f"process-group:{identity}"


def _kill_process_group(process_group: int, signal_number: int) -> None:
    killpg = getattr(os, "killpg", None)
    if not callable(killpg):
        raise RuntimeResourceProbeRefused("process-group operations are unavailable")
    killpg(process_group, signal_number)


def _plan_facts(
    *,
    argv: Sequence[str],
    cwd: str | os.PathLike[str],
    environment: Mapping[str, str],
    creationflags: int,
) -> tuple[str, str, str]:
    if type(creationflags) is not int or creationflags < 0:
        raise ValueError("creationflags must be a non-negative integer")
    args = _argv(argv)
    work = _cwd(cwd)
    env = _environment(environment)
    gate_name = "process_gate_windows.py" if os.name == "nt" else "process_gate.py"
    gate_path = Path(__file__).with_name(gate_name).resolve(strict=True)
    gate_digest = hashlib.sha256(
        readNoFollowBytes(gate_path, max_bytes=1024 * 1024)
    ).hexdigest()
    entrypoint_digest = canonical_digest(
        {
            "schema": "galaxy.local-process-entrypoint/v1",
            "argv": list(args),
            "creationflags": creationflags,
            "start_new_session": os.name != "nt",
            "gate_sha256": gate_digest,
        }
    )
    mount_digest = canonical_digest(
        {
            "schema": "galaxy.local-process-cwd/v1",
            "cwd": work,
        }
    )
    environment_digest = canonical_digest(
        {
            "schema": "galaxy.local-process-environment/v1",
            "environment": env,
        }
    )
    return entrypoint_digest, mount_digest, environment_digest


def planRegisteredProcessResource(
    *,
    run_id: str,
    transaction_id: str,
    controller_scope_id: str,
    resource_id: str,
    role: ResourceRole,
    backend: str,
    ownership_nonce: str,
    argv: Sequence[str],
    cwd: str | os.PathLike[str],
    environment: Mapping[str, str],
    creationflags: int,
    security_profile_digest: str,
    registered_at: str,
    depends_on: tuple[str, ...] = (),
) -> RuntimeResourceLease:
    """Build the exact REGISTERED plan that must be journaled before creation."""

    if not isinstance(role, ResourceRole) or role not in _PROCESS_ROLES:
        raise ValueError("role must identify a process resource")
    if type(backend) is not str or not backend:
        raise ValueError("backend must be non-empty")
    now = _registered_at(registered_at)
    entrypoint, mount, env_digest = _plan_facts(
        argv=argv,
        cwd=cwd,
        environment=environment,
        creationflags=creationflags,
    )
    locator = _cleanup_locator(
        run_id=run_id,
        transaction_id=transaction_id,
        controller_scope_id=controller_scope_id,
        resource_id=resource_id,
        role=role,
        ownership_nonce=ownership_nonce,
    )
    return RuntimeResourceLease(
        resource_id=resource_id,
        run_id=run_id,
        transaction_id=transaction_id,
        controller_scope_id=controller_scope_id,
        role=role,
        backend=backend,
        ownership_nonce=ownership_nonce,
        state=ProcessResourceState.REGISTERED,
        cleanup_locator_digest=canonical_digest(
            {
                "schema": "galaxy.process-cleanup-locator-digest/v1",
                "locator": locator,
            }
        ),
        pid=0,
        process_group_id=0,
        container_id="",
        image_digest="",
        entrypoint_digest=entrypoint,
        mount_digest=mount,
        environment_digest=env_digest,
        security_profile_digest=security_profile_digest,
        created_at=now,
        updated_at=now,
        depends_on=depends_on,
    )


class _WindowsJob:
    """One no-breakaway, kill-on-close Windows Job Object."""

    def __init__(self, name: str) -> None:
        import ctypes
        from ctypes import wintypes

        class _BasicLimit(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class _IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class _ExtendedLimit(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _BasicLimit),
                ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        class _Accounting(ctypes.Structure):
            _fields_ = [
                ("TotalUserTime", ctypes.c_longlong),
                ("TotalKernelTime", ctypes.c_longlong),
                ("ThisPeriodTotalUserTime", ctypes.c_longlong),
                ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
                ("TotalPageFaultCount", wintypes.DWORD),
                ("TotalProcesses", wintypes.DWORD),
                ("ActiveProcesses", wintypes.DWORD),
                ("TotalTerminatedProcesses", wintypes.DWORD),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        )
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        kernel32.QueryInformationJobObject.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.c_void_p,
        )
        kernel32.QueryInformationJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL

        ctypes.set_last_error(0)
        handle = kernel32.CreateJobObjectW(None, name)
        if not handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
        if ctypes.get_last_error() == 183:
            kernel32.CloseHandle(handle)
            raise ProcessLaunchRefused("registered Job Object name already exists")
        limits = _ExtendedLimit()
        # KILL_ON_JOB_CLOSE; deliberately omit both breakaway flags.
        limits.BasicLimitInformation.LimitFlags = 0x00002000
        if not kernel32.SetInformationJobObject(
            handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            error = ctypes.get_last_error()
            kernel32.CloseHandle(handle)
            raise OSError(error, "SetInformationJobObject failed")
        self._ctypes = ctypes
        self._kernel32 = kernel32
        self._Accounting = _Accounting
        self._handle = handle
        self._closed = False

    def assign(self, process: subprocess.Popen[Any]) -> None:
        handle = getattr(process, "_handle", None)
        if handle is None or not self._kernel32.AssignProcessToJobObject(
            self._handle, int(handle)
        ):
            raise OSError(self._ctypes.get_last_error(), "AssignProcessToJobObject failed")

    @property
    def handle(self) -> int:
        if self._closed:
            raise ProcessLaunchRefused("Windows Job Object is already closed")
        return int(self._handle)

    def terminate(self) -> None:
        if self._closed:
            return
        if not self._kernel32.TerminateJobObject(self._handle, 0xC000013A):
            error = self._ctypes.get_last_error()
            if error not in {5, 87}:
                raise OSError(error, "TerminateJobObject failed")

    def active(self) -> int:
        if self._closed:
            return 0
        info = self._Accounting()
        if not self._kernel32.QueryInformationJobObject(
            self._handle, 1, self._ctypes.byref(info), self._ctypes.sizeof(info), None
        ):
            raise OSError(
                self._ctypes.get_last_error(), "QueryInformationJobObject failed"
            )
        return int(info.ActiveProcesses)

    def close(self) -> None:
        if not self._closed:
            if not self._kernel32.CloseHandle(self._handle):
                raise OSError(self._ctypes.get_last_error(), "CloseHandle(Job) failed")
            self._closed = True


class _RegisteredProcess:
    def __init__(
        self,
        *,
        process: subprocess.Popen[Any],
        journal: AttemptJournal,
        resource: RuntimeResourceLease,
        boundary: _WindowsJob | int,
    ) -> None:
        self._process = process
        self._journal = journal
        self._resource = resource
        self._boundary = boundary
        self._closed = False
        self._lock = threading.Lock()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._process, name)

    @property
    def pid(self) -> int:
        return self._process.pid

    @property
    def returncode(self) -> int | None:
        return self._process.returncode

    def _terminate_boundary(self) -> None:
        if os.name == "nt":
            assert isinstance(self._boundary, _WindowsJob)
            self._boundary.terminate()
            deadline = time.monotonic() + 10.0
            while self._boundary.active() and time.monotonic() < deadline:
                time.sleep(0.01)
            if self._boundary.active():
                raise RuntimeResourceProbeRefused("Windows Job Object did not quiesce")
            self._boundary.close()
            return
        if not isinstance(self._boundary, int):
            raise RuntimeResourceProbeRefused("POSIX process-group identity is invalid")
        process_group = self._boundary
        try:
            _kill_process_group(process_group, int(signal.SIGTERM))
        except ProcessLookupError:
            return
        except PermissionError as exc:
            raise RuntimeResourceProbeRefused(
                "registered process group cannot be terminated"
            ) from exc
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            try:
                _kill_process_group(process_group, 0)
            except ProcessLookupError:
                return
            time.sleep(0.01)
        try:
            _kill_process_group(process_group, int(getattr(signal, "SIGKILL", 9)))
        except ProcessLookupError:
            return
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            try:
                _kill_process_group(process_group, 0)
            except ProcessLookupError:
                return
            time.sleep(0.01)
        raise RuntimeResourceProbeRefused("registered process group did not quiesce")

    def _collect(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._terminate_boundary()
            observed = processStartToken(self.pid)
            if observed == self._resource.process_start_token:
                raise RuntimeResourceProbeRefused("registered root process remains live")
            quiesced = self._journal.transition_resource(
                self._resource.transaction_id,
                self._resource.resource_id,
                ProcessResourceState.QUIESCED,
            )
            self._resource = self._journal.transition_resource(
                self._resource.transaction_id,
                self._resource.resource_id,
                ProcessResourceState.COLLECTED,
            )
            if quiesced.pid != self._resource.pid:
                raise RuntimeResourceProbeRefused("collected process identity changed")
            self._closed = True

    def communicate(self, *args: Any, **kwargs: Any) -> tuple[Any, Any]:
        result = self._process.communicate(*args, **kwargs)
        self._collect()
        return result

    def wait(self, *args: Any, **kwargs: Any) -> int:
        result = self._process.wait(*args, **kwargs)
        self._collect()
        return result

    def terminate(self) -> None:
        self._terminate_boundary()

    def kill(self) -> None:
        self._terminate_boundary()

    def terminateTree(self) -> None:
        """Terminate the exact registered boundary, including descendants."""

        self._terminate_boundary()

    def __enter__(self) -> "_RegisteredProcess":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        try:
            if self._process.poll() is None:
                self._terminate_boundary()
                self._process.wait(timeout=10)
        finally:
            self._collect()


class RegisteredProcessLauncher:
    """Popen-compatible factory bound to one exact REGISTERED resource plan."""

    def __init__(
        self,
        *,
        journal: AttemptJournal,
        resource: RuntimeResourceLease,
        security_profile_digest: str,
    ) -> None:
        if not isinstance(journal, AttemptJournal):
            raise TypeError("journal must be AttemptJournal")
        if not isinstance(resource, RuntimeResourceLease):
            raise TypeError("resource must be RuntimeResourceLease")
        if resource.state is not ProcessResourceState.REGISTERED:
            raise ProcessLaunchRefused("process resource is not REGISTERED")
        if resource.role not in _PROCESS_ROLES:
            raise ProcessLaunchRefused("credential resources cannot launch processes")
        if resource.backend != "local":
            raise ProcessLaunchRefused("registered launcher requires the local backend")
        if resource.security_profile_digest != security_profile_digest:
            raise ProcessLaunchRefused("security profile differs from the process plan")
        observed = self._durableRegisteredResource(journal, resource)
        if observed != resource:
            raise ProcessLaunchRefused("resource differs from the durable registry")
        self.journal = journal
        self.resource = resource
        self.security_profile_digest = security_profile_digest
        self._used = False
        self._lock = threading.Lock()

    @staticmethod
    def _durableRegisteredResource(
        journal: AttemptJournal,
        resource: RuntimeResourceLease,
    ) -> RuntimeResourceLease:
        try:
            record = journal.load(resource.transaction_id)
            if record.phase is not AttemptPhase.RUNNING:
                raise ProcessLaunchRefused("attempt is not durably RUNNING")
            resources = journal.load_resources(resource.transaction_id)
        except ProcessLaunchRefused:
            raise
        except MissingResourceSet as exc:
            raise ProcessLaunchRefused(
                "process resource closure is missing"
            ) from exc
        except IncompleteResourceSet as exc:
            raise ProcessLaunchRefused(
                "process resource closure is incomplete"
            ) from exc
        except JournalCorruption as exc:
            raise ProcessLaunchRefused(
                "process resource closure is corrupt"
            ) from exc
        except (JournalError, OSError, TypeError, ValueError) as exc:
            raise ProcessLaunchRefused(
                "process resource closure is unavailable"
            ) from exc
        observed = tuple(
            item
            for item in resources
            if item.resource_id == resource.resource_id
            and item.role is resource.role
        )
        if observed != (resource,):
            raise ProcessLaunchRefused("resource differs from the durable registry")
        if observed[0].state is not ProcessResourceState.REGISTERED:
            raise ProcessLaunchRefused("durable process resource is not pristine REGISTERED")
        return observed[0]

    def _validate_call(
        self,
        argv: Sequence[str],
        kwargs: dict[str, Any],
    ) -> tuple[tuple[str, ...], str, dict[str, str], int]:
        if kwargs.get("shell", False) or kwargs.get("executable") is not None:
            raise ProcessLaunchRefused("shell and executable overrides are forbidden")
        if kwargs.get("preexec_fn") is not None:
            raise ProcessLaunchRefused("preexec_fn is forbidden")
        if kwargs.get("startupinfo") is not None or kwargs.get("pass_fds"):
            raise ProcessLaunchRefused("caller-owned process attributes are forbidden")
        args = _argv(argv)
        work = _cwd(kwargs.get("cwd", os.getcwd()))
        env = _environment(kwargs.get("env", os.environ))
        creationflags = kwargs.get("creationflags", 0)
        if os.name == "nt" and creationflags & _CREATE_BREAKAWAY_FROM_JOB:
            raise ProcessLaunchRefused("Job Object breakaway is forbidden")
        entrypoint, mount, env_digest = _plan_facts(
            argv=args,
            cwd=work,
            environment=env,
            creationflags=creationflags,
        )
        actual_start_session = bool(kwargs.get("start_new_session", False))
        if actual_start_session != (os.name != "nt"):
            raise ProcessLaunchRefused("session-boundary mode differs from the process plan")
        if (
            entrypoint != self.resource.entrypoint_digest
            or mount != self.resource.mount_digest
            or env_digest != self.resource.environment_digest
        ):
            raise ProcessLaunchRefused("launch facts differ from the registered process plan")
        return args, work, env, creationflags

    def __call__(self, argv: Sequence[str], **kwargs: Any) -> _RegisteredProcess:
        with self._lock:
            if self._used:
                raise ProcessLaunchRefused("registered process plan is single-use")
            self._durableRegisteredResource(self.journal, self.resource)
            args, work, env, creationflags = self._validate_call(argv, kwargs)
            self._used = True
        locator = _cleanup_locator(
            run_id=self.resource.run_id,
            transaction_id=self.resource.transaction_id,
            controller_scope_id=self.resource.controller_scope_id,
            resource_id=self.resource.resource_id,
            role=self.resource.role,
            ownership_nonce=self.resource.ownership_nonce,
        )
        process: subprocess.Popen[Any] | None = None
        boundary: _WindowsJob | int | None = None
        release_fd: int | None = None
        gate_read_fd: int | None = None
        try:
            launch_kwargs = dict(kwargs)
            launch_kwargs["cwd"] = work
            launch_kwargs["env"] = env
            if os.name == "nt":
                import msvcrt

                boundary = _WindowsJob(locator)
                gate_read_fd, release_fd = os.pipe()
                os.set_inheritable(gate_read_fd, True)
                read_handle = int(msvcrt.get_osfhandle(gate_read_fd))
                gate = Path(__file__).with_name("process_gate_windows.py").resolve(
                    strict=True
                )
                gate_argv = [
                    sys.executable,
                    "-I",
                    "-S",
                    str(gate),
                    "--gate-handle",
                    str(read_handle),
                    "--",
                    *args,
                ]
                launch_kwargs["creationflags"] = creationflags
                launch_kwargs["start_new_session"] = False
                startupinfo = subprocess.STARTUPINFO()
                cast(dict[str, Any], startupinfo.lpAttributeList)["handle_list"] = [
                    read_handle
                ]
                launch_kwargs["startupinfo"] = startupinfo
                process = subprocess.Popen(gate_argv, **launch_kwargs)
                os.close(gate_read_fd)
                gate_read_fd = None
                boundary.assign(process)
                if boundary.active() != 1:
                    raise ProcessLaunchRefused(
                        "blocked gate did not enter the registered Job Object"
                    )
            else:
                gate_read_fd, release_fd = os.pipe()
                os.set_inheritable(gate_read_fd, True)
                gate = Path(__file__).with_name("process_gate.py").resolve(strict=True)
                gate_argv = [
                    sys.executable,
                    "-I",
                    "-S",
                    str(gate),
                    "--gate-fd",
                    str(gate_read_fd),
                    "--",
                    *args,
                ]
                launch_kwargs["creationflags"] = 0
                launch_kwargs["start_new_session"] = True
                launch_kwargs["pass_fds"] = (gate_read_fd,)
                process = subprocess.Popen(gate_argv, **launch_kwargs)
                os.close(gate_read_fd)
                gate_read_fd = None
                boundary = process.pid
            token = processStartToken(process.pid)
            if token is None:
                raise ProcessLaunchRefused("blocked child identity disappeared")
            self.journal.transition_resource(
                self.resource.transaction_id,
                self.resource.resource_id,
                ProcessResourceState.CREATED,
                pid=process.pid,
                process_group_id=process.pid,
                process_start_token=token,
            )
            started = self.journal.transition_resource(
                self.resource.transaction_id,
                self.resource.resource_id,
                ProcessResourceState.STARTED,
            )
            if os.name == "nt":
                assert release_fd is not None
                if os.write(release_fd, b"R") != 1:
                    raise OSError("blocked child release was incomplete")
                os.close(release_fd)
                release_fd = None
            else:
                assert release_fd is not None
                if os.write(release_fd, b"R") != 1:
                    raise OSError("blocked child release was incomplete")
                os.close(release_fd)
                release_fd = None
            return _RegisteredProcess(
                process=process,
                journal=self.journal,
                resource=started,
                boundary=boundary,
            )
        except BaseException:
            if gate_read_fd is not None:
                try:
                    os.close(gate_read_fd)
                except OSError:
                    pass
            if release_fd is not None:
                try:
                    os.close(release_fd)
                except OSError:
                    pass
            try:
                if isinstance(boundary, _WindowsJob):
                    boundary.terminate()
                    boundary.close()
                elif isinstance(boundary, int):
                    try:
                        _kill_process_group(
                            boundary, int(getattr(signal, "SIGKILL", 9))
                        )
                    except (ProcessLookupError, PermissionError):
                        pass
            except Exception:
                pass
            if process is not None:
                try:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=10)
                except Exception:
                    pass
            raise


class RegisteredProcessManager:
    """Bind exact local-driver plans to one live installed run admission."""

    def __init__(
        self,
        *,
        journal: AttemptJournal,
        controller_scope_id: str,
        security_profile_digest: str,
        landing_authority_issuer: LandingAuthorityIssuer,
        run_admission: RunAdmissionAuthority,
        _construction_authority: object = None,
    ) -> None:
        if _construction_authority is not _REGISTERED_MANAGER_CONSTRUCTION:
            raise ProcessLaunchRefused(
                "process manager requires installed run-admission composition"
            )
        if not isinstance(journal, AttemptJournal):
            raise TypeError("journal must be AttemptJournal")
        if type(landing_authority_issuer) is not LandingAuthorityIssuer:
            raise TypeError("landing_authority_issuer must be exact")
        if type(run_admission) is not RunAdmissionAuthority:
            raise TypeError("run_admission must be exact")
        # Validate portable identifiers/digests through the canonical resource contract
        # on first use; reject empty values eagerly for clearer composition failures.
        if (
            type(controller_scope_id) is not str
            or _PORTABLE_ID_RE.fullmatch(controller_scope_id) is None
        ):
            raise ValueError("controller_scope_id must be a portable identifier")
        if (
            type(security_profile_digest) is not str
            or _DIGEST_RE.fullmatch(security_profile_digest) is None
        ):
            raise ValueError("security_profile_digest must be a SHA-256 digest")
        self.journal = journal
        self.controller_scope_id = controller_scope_id
        self.security_profile_digest = security_profile_digest
        self.landing_authority_issuer = landing_authority_issuer
        self.run_admission = run_admission
        self._lock = threading.RLock()

    def productionReady(self) -> bool:
        try:
            return bool(
                self.landing_authority_issuer.isInstalledAuthority()
                and self.landing_authority_issuer._validateAdmission(
                    self.run_admission
                )
                is self.run_admission
                and self.run_admission.child_pid == os.getpid()
            )
        except Exception:
            return False

    def launcherFor(
        self,
        lease: CloneLease,
        *,
        argv: Sequence[str],
        cwd: str | os.PathLike[str],
        environment: Mapping[str, str],
        creationflags: int,
        security_profile_digest: str,
    ) -> RegisteredProcessLauncher:
        """Consume the exact pre-registered model-driver plan."""

        if not self.productionReady():
            raise ProcessLaunchRefused("installed process-manager authority is not live")
        if security_profile_digest != self.security_profile_digest:
            raise ProcessLaunchRefused("requested security profile differs")
        try:
            validateCloneLease(lease)
        except Exception as exc:
            raise ProcessLaunchRefused("clone lease is not live") from exc
        if lease.runner_kind is not RunnerKind.LOCAL:
            raise ProcessLaunchRefused("local process manager cannot launch another runner kind")
        with self._lock:
            record = self.journal.load(lease.transaction_id)
            exact = {
                "transaction_id": lease.transaction_id,
                "task_id": lease.task_id,
                "subtask_id": lease.subtask_id,
                "attempt_id": lease.attempt_id,
                "repository_id": lease.repository_id,
                "clone_path": lease.checkout_path,
                "ownership_nonce": lease.ownership_nonce,
                "base_revision": lease.expected_base_revision,
                "candidate_branch": lease.candidate_branch,
            }
            if any(getattr(record, name) != value for name, value in exact.items()):
                raise ProcessLaunchRefused("clone lease differs from attempt truth")
            if not (
                record.runtime_resource_manifest_json
                and record.runtime_resource_manifest_digest
            ):
                raise ProcessLaunchRefused(
                    "attempt has no workload-specific resource admission manifest"
                )
            if record.phase not in {
                AttemptPhase.LEASE_REGISTERED,
                AttemptPhase.RUNNING,
            }:
                raise ProcessLaunchRefused("attempt is not launch-eligible")
            try:
                registered = self.journal.load_resources(lease.transaction_id)
            except MissingResourceSet as exc:
                raise ProcessLaunchRefused(
                    "process resource closure is missing"
                ) from exc
            except IncompleteResourceSet as exc:
                raise ProcessLaunchRefused(
                    "process resource closure is incomplete"
                ) from exc
            except JournalCorruption as exc:
                raise ProcessLaunchRefused(
                    "process resource closure is corrupt"
                ) from exc
            except (JournalError, OSError, TypeError, ValueError) as exc:
                raise ProcessLaunchRefused(
                    "process resource closure is unavailable"
                ) from exc
            drivers = tuple(
                resource
                for resource in registered
                if resource.role is ResourceRole.MODEL_DRIVER
            )
            if len(drivers) != 1:
                raise ProcessLaunchRefused(
                    "process resource closure has no unique model driver"
                )
            durable_resource = drivers[0]
            if durable_resource.state is not ProcessResourceState.REGISTERED:
                raise ProcessLaunchRefused(
                    "durable model-driver resource is not pristine REGISTERED"
                )
            requested_resource = planRegisteredProcessResource(
                run_id=self.run_admission.run_id,
                transaction_id=lease.transaction_id,
                controller_scope_id=self.controller_scope_id,
                resource_id=durable_resource.resource_id,
                role=ResourceRole.MODEL_DRIVER,
                backend="local",
                ownership_nonce=lease.ownership_nonce,
                argv=argv,
                cwd=cwd,
                environment=environment,
                creationflags=creationflags,
                security_profile_digest=security_profile_digest,
                registered_at=record.created_at,
                depends_on=durable_resource.depends_on,
            )
            if requested_resource != durable_resource:
                raise ProcessLaunchRefused(
                    "requested launch differs from the pre-registered model-driver plan"
                )
            identities = tuple(
                f"{resource.role.value}:{resource.resource_id}"
                for resource in registered
            )
            if (
                record.phase is AttemptPhase.RUNNING
                and record.resource_lease_ids != identities
            ):
                raise ProcessLaunchRefused("attempt runtime resource set differs")
            try:
                running = self.journal.transition(
                    lease.transaction_id,
                    AttemptPhase.RUNNING,
                    resource_lease_ids=identities,
                )
            except (JournalError, OSError, TypeError, ValueError) as exc:
                raise ProcessLaunchRefused(
                    "attempt could not bind the completed process resource set"
                ) from exc
            if (
                running.phase is not AttemptPhase.RUNNING
                or running.resource_lease_ids != identities
            ):
                raise ProcessLaunchRefused(
                    "attempt differs from the completed process resource set"
                )
            return RegisteredProcessLauncher(
                journal=self.journal,
                resource=durable_resource,
                security_profile_digest=security_profile_digest,
            )


def buildInstalledRegisteredProcessManager(
    *,
    journal: AttemptJournal,
    controller_scope_id: str,
    security_profile_digest: str,
    landing_authority_issuer: LandingAuthorityIssuer,
    run_admission: RunAdmissionAuthority,
) -> RegisteredProcessManager:
    """Create production process authority only from the live installed issuer."""

    if (
        type(landing_authority_issuer) is not LandingAuthorityIssuer
        or not landing_authority_issuer.isInstalledAuthority()
        or type(run_admission) is not RunAdmissionAuthority
    ):
        raise ProcessLaunchRefused("installed run admission is required")
    try:
        landing_authority_issuer._validateAdmission(run_admission)
    except Exception as exc:
        raise ProcessLaunchRefused("run admission is not live") from exc
    if run_admission.child_pid != os.getpid():
        raise ProcessLaunchRefused("run admission is bound to another child process")
    manager = RegisteredProcessManager(
        journal=journal,
        controller_scope_id=controller_scope_id,
        security_profile_digest=security_profile_digest,
        landing_authority_issuer=landing_authority_issuer,
        run_admission=run_admission,
        _construction_authority=_REGISTERED_MANAGER_CONSTRUCTION,
    )
    if not manager.productionReady():  # pragma: no cover - constructor validation above
        raise ProcessLaunchRefused("process manager did not retain live authority")
    return manager


__all__ = [
    "ProcessLaunchRefused",
    "RegisteredProcessManager",
    "RegisteredProcessLauncher",
    "buildInstalledRegisteredProcessManager",
    "planRegisteredProcessResource",
]
