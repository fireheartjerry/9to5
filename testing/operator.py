"""VirtualOperator -- a scripted "human at the controls".

It observes a live run (status / progress / pending gate) and issues control actions
through the SAME entry points a real operator uses:

  * ``surface="web"``  -> notifications.webdash._applyControl (the HTTP control handler)
  * ``surface="bus"``  -> notifications.commands.applyCommand (the terminal/Discord spine)

Both converge on the file-backed ControlBus the run thread polls, so this exercises the
real control plane -- not a private back door. It is deterministic (not an LLM): the same
script yields the same run every time, which is what you want for regression testing.
"""
from __future__ import annotations

import time
from typing import Callable, Optional

from platform_core.runtime.control import ControlBus
from notifications import commands
from notifications import webdash
from state.task import TaskState


class OperatorTimeout(RuntimeError):
    """The operator waited for a condition that never happened (the run is stuck/broken)."""


class VirtualOperator:
    SURFACES = ("web", "bus")

    def __init__(self, task_id: str, *, surface: str = "web", poll: float = 0.02,
                 timeout: float = 15.0):
        if surface not in self.SURFACES:
            raise ValueError(f"surface must be one of {self.SURFACES}")
        self.task_id = task_id
        self.surface = surface
        self.poll = poll
        self.timeout = timeout
        self.bus = ControlBus(task_id)
        self.actions: list[tuple[str, str]] = []   # audit of what the "human" did

    # ---- observation ---------------------------------------------------
    def status(self) -> Optional[str]:
        st = TaskState.loadSafe(self.task_id)
        return st.meta.get("status") if st else None

    def progress(self) -> tuple[int, int]:
        st = TaskState.loadSafe(self.task_id)
        return st.progress() if st else (0, 0)

    def pendingGate(self) -> Optional[str]:
        return self.bus.getPendingGate()

    def _wait(self, predicate: Callable, what: str, timeout: Optional[float] = None):
        deadline = time.time() + (timeout if timeout is not None else self.timeout)
        while time.time() < deadline:
            try:
                val = predicate()
            except Exception:  # noqa: BLE001
                val = None
            if val:
                return val
            time.sleep(self.poll)
        raise OperatorTimeout(f"timed out waiting for {what}")

    def waitForGate(self, gate: Optional[str] = None, timeout: Optional[float] = None) -> str:
        """Block until the run is awaiting a gate (a specific one, or any)."""
        return self._wait(
            lambda: (g := self.pendingGate()) and (gate is None or g == gate) and g,
            f"gate {gate or 'any'}", timeout)

    def waitForStatus(self, *statuses: str, timeout: Optional[float] = None) -> str:
        want = set(statuses)
        return self._wait(lambda: (s := self.status()) in want and s, f"status in {want}", timeout)

    def waitDone(self, timeout: Optional[float] = None) -> str:
        return self._wait(lambda: (s := self.status()) in TaskState._TERMINAL and s,
                          "terminal status", timeout)

    # ---- actions (routed through a REAL human surface) -----------------
    def _do(self, action: str, arg: str = "") -> object:
        self.actions.append((action, arg))
        if self.surface == "web":
            return webdash._applyControl(self.task_id, action, arg or None)
        st = TaskState.loadSafe(self.task_id)
        return commands.applyCommand(self.bus, st, commands.Command(action, arg))

    def _awaitConsumed(self, gate: str) -> None:
        """After deciding a gate, wait until the run consumes it (pending gate clears/changes)
        so the next waitForGate sees a fresh gate rather than the one we just answered."""
        try:
            self._wait(lambda: self.pendingGate() != gate, f"gate {gate} consumed")
        except OperatorTimeout:
            pass   # the run may have ended (e.g. on reject) -- that's fine

    def approve(self, gate: Optional[str] = None) -> str:
        g = self.waitForGate(gate)
        self._do("approve")
        self._awaitConsumed(g)
        return g

    def reject(self, gate: Optional[str] = None) -> str:
        g = self.waitForGate(gate)
        self._do("reject")
        self._awaitConsumed(g)
        return g

    def pause(self) -> None:
        self._do("pause")

    def resume(self) -> None:
        self._do("resume")

    def abort(self) -> None:
        self._do("abort")

    def skip(self, subtask_id: str) -> None:
        self._do("skip", subtask_id)

    def add(self, title: str) -> None:
        self._do("add", title)
