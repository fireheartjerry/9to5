"""contracts -- the central 9to5 data contracts as TypedDicts.

(Named ``contracts`` not ``types`` -- a top-level ``types.py`` would shadow Python's stdlib
``types`` module on sys.path and break the whole interpreter.)

These four dicts flow through dozens of modules as opaque ``dict`` today. Naming their shapes
here gives an LLM (and the type checker) exact key/field knowledge -- so an agent never has to
re-grep "what keys does this dict have" -- without any runtime change (TypedDict is erased at
runtime; `total=False` because most call sites populate a subset).

Adoption is progressive: annotate signatures as `InvocationSpec`/`Verdict`/`ExecutorResult`/
`Verify` instead of `dict` while touching each module (Phase 1 pilot, Phase 2 scale).

Sources of truth (kept in sync by hand -- if a key is added there, add it here):
  * InvocationSpec  -> agents/executor.py::normalizeSpec base
  * ExecutorResult  -> agents/executor.py / agents/browser_executor.py::_result
  * Verdict         -> agents/adversary.py + agents/second_brain.py (tier/session_dead)
  * Verify          -> agents/verifier.py
"""
from __future__ import annotations

from typing import Any, Optional, TypedDict


class InvocationSpec(TypedDict, total=False):
    """The brain-authored spec the executor turns into a Claude Code CLI invocation."""
    prompt: str
    claude_md_inject: str
    skills_to_invoke: list[str]
    effort_level: str               # default | high | xhigh | ultracode
    subagent: Optional[str]         # None | "architect" | "security-reviewer"
    pre_tool_hooks: list[str]
    post_tool_hooks: list[str]
    use_workflow: bool
    workflow_definition: Optional[dict]
    surface: str                    # "terminal" | "browser" | "native"
    browser_actions: list[dict[str, Any]]
    verify: "Verify"


class ExecutorResult(TypedDict, total=False):
    """The uniform result dict every executor surface returns (terminal/browser/native)."""
    ok: bool
    returncode: int
    stdout: str
    stderr: str
    is_error: bool
    effort: str
    effort_flag: Optional[str]
    spec: InvocationSpec
    claude_md_path: Optional[str]
    profile: str
    blocked: bool
    surface: str


class Verdict(TypedDict, total=False):
    """The adversary/second-brain review verdict (rich contract; tier/session_dead from router)."""
    verdict: str                    # "approved" | "challenged"
    trigger_reason: str
    concerns: list[str]
    notes: str
    stub: bool
    severity: str                   # "none" | "low" | "medium" | "high"
    must_fix: list[str]
    suggested_fix: str
    confidence: Optional[float]
    surface: str                    # "ollama" | "browser"
    review_type: str                # "subtask" | "plan" | "architecture" | "pre_pr_diff"
    tier: str                       # "gpt" | "ollama" | "stub"
    session_dead: bool


class Verify(TypedDict, total=False):
    """A brain-authored verification check run after the executor."""
    cmd: str
    expect: str                     # "exit_zero" | "stdout_contains:<t>" | "stdout_regex:<re>"
