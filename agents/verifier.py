"""Verifier -- run the brain-authored verification check for a subtask.

Each subtask carries a ``verify`` block authored by the Orchestrator brain:

    {"cmd": "python -m taskcli --help", "expect": "exit_zero"}

``expect`` is one of:
  * ``exit_zero``                -- the command returned exit code 0
  * ``stdout_contains:<text>``   -- <text> appears in stdout
  * ``stdout_regex:<pattern>``   -- <pattern> matches stdout (re.search)

If ``cmd`` is null/empty the gate falls back to "the executor process exited 0".
The command is run deterministically in the subtask's working directory; this
module never asks the model anything -- it only executes and compares.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import config

LOG = config.getLogger("verifier")

_MAX_CAP = 2000  # truncate captured output


def _cap(text: Optional[str]) -> str:
    text = text or ""
    return text if len(text) <= _MAX_CAP else text[:_MAX_CAP] + "\n...[truncated]"


def _runShell(cmd: str, work_dir: str) -> subprocess.CompletedProcess:
    """Run a verify command string via the native shell (cmd.exe on Windows).

    Verifies are constrained to ``python <path>`` shapes, so the native shell is
    correct: cmd.exe handles Windows backslash paths AND nested quotes the way a
    human would type them. (bash would treat the backslashes in C:\\... as escapes
    and mangle the path.)
    """
    Path(work_dir).mkdir(parents=True, exist_ok=True)
    # stdin=DEVNULL so a program that reads stdin gets EOF and exits instead of hanging to timeout.
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=work_dir, timeout=config.VERIFY_TIMEOUT_SECONDS,
                          stdin=subprocess.DEVNULL)


_VERIFY_STDLIB_OK = {
    "os", "sys", "json", "re", "pathlib", "subprocess", "math", "io", "time", "datetime",
    "collections", "itertools", "functools", "typing", "string", "random", "statistics",
    "textwrap", "shutil", "glob", "argparse", "csv", "hashlib", "base64", "unittest",
    "decimal", "fractions", "ast",
}


def sanitizeVerify(verify: Optional[dict]) -> Optional[dict]:
    """Drop a structurally-unreliable brain-authored verify so the subtask falls back to
    'executor exited 0' instead of failing forever on a bad check.

    Catches two failure modes: a malformed ``python -c`` one-liner (SyntaxError, e.g. a
    compound statement after ';'), AND a ``python -c`` that imports a non-stdlib / project
    module -- the 'guessed internal symbol' pattern (``from fibonacci import fib``) that
    fails even when the code under test is perfectly correct.
    """
    import ast
    if not isinstance(verify, dict):
        return None
    cmd = (verify.get("cmd") or "").strip()
    if not cmd:
        return None
    m = re.match(r"""(?:py|python|python3)\s+-c\s+(['"])(.*)\1\s*$""", cmd, re.DOTALL)
    if m:
        code = m.group(2)
        try:
            tree = ast.parse(code, "<verify>", "exec")
        except SyntaxError:
            LOG.info("sanitizeVerify: dropping malformed python -c verify: %s", cmd)
            return None
        for node in ast.walk(tree):
            mods: list[str] = []
            if isinstance(node, ast.Import):
                mods = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module.split(".")[0]]
            for mod in mods:
                if mod not in _VERIFY_STDLIB_OK:
                    LOG.info("sanitizeVerify: dropping verify importing non-stdlib '%s': %s", mod, cmd)
                    return None
    return verify


_COMPOUND_PREFIXES = ("stdout_contains_all:", "stdout_regex_all:")

# Filler / structural / HTML-ambient words that are NOT distinctive of a deliverable. Dropping them
# keeps a synthesized requirement marker from being satisfied by boilerplate that is ALWAYS present
# (e.g. a goal asking for an "auto-refresh meta tag" must key on 'refresh', not the ambient 'meta'
# that every HTML page already has) -- otherwise the compound verify would false-PASS partial work.
_MARKER_STOPWORDS = {
    "the", "a", "an", "and", "or", "with", "for", "to", "of", "in", "on", "at", "by", "as", "is",
    "be", "per", "each", "every", "via", "that", "this", "it", "its", "into", "from", "all", "any",
    "add", "adds", "added", "adding", "make", "makes", "made", "use", "uses", "using", "show",
    "shows", "showing", "display", "displays", "support", "supports", "new", "also", "should",
    "must", "will", "can", "line", "tag", "tags", "coding", "code", "feature", "features", "section",
    "field", "value", "values", "page", "pages", "block", "area", "part", "thing", "item", "items",
    "html", "div", "span", "head", "body", "title", "meta", "charset", "css", "style", "styles",
}


def extractRequirements(goal: str) -> list[str]:
    """Pull the EXPLICITLY enumerated deliverables out of a goal.

    Detects ``(1) ... (2) ... (3) ...``, ``1. ...`` and ``1) ...`` styles by locating the longest
    run of enumerators counting up from 1, then slicing the text between them. Returns the requirement
    phrases (>=2) or ``[]`` when the goal is not an enumerated multi-deliverable. Deliberately
    conservative: the run-from-1 check ignores stray numbers (versions, ``content=5``) so we never
    mistake a single-deliverable goal for a multi-part one.
    """
    g = goal or ""
    cand = [(m.start(), m.end(), int(m.group(1))) for m in re.finditer(r"\(?\b(\d{1,2})[).]", g)]
    run: list[tuple[int, int, int]] = []
    nxt = 1
    for start, end, num in cand:
        if num == nxt:
            run.append((start, end, num))
            nxt += 1
    if len(run) < 2:
        return []
    items: list[str] = []
    for i, (_s, end, _n) in enumerate(run):
        seg_end = run[i + 1][0] if i + 1 < len(run) else len(g)
        seg = g[end:seg_end].strip(" ,;:.\t\r\n-")
        if seg:
            items.append(seg)
    return items


_FILE_TOKEN_RE = re.compile(
    r"([A-Za-z0-9_./\\-]*[A-Za-z0-9_-]\.(?:py|md|txt|json|js|ts|tsx|jsx|html|css|csv|ya?ml|cfg|ini|"
    r"sh|bat|go|rs|java|c|cc|cpp|h|hpp|rb|php|swift|kt|sql|toml))\b")


def primaryTargetFile(goal: str) -> Optional[str]:
    """The single distinct file path a goal targets, else None (zero or several files named).
    Returned verbatim (may be relative, e.g. ``notifications/webdash.py``) -- the caller resolves it
    against the project root. Used to point a synthesized compound verify at the right file."""
    files = []
    for m in _FILE_TOKEN_RE.findall(goal or ""):
        norm = m.replace("\\", "/")
        if norm not in files:
            files.append(norm)
    return files[0] if len(files) == 1 else None


def requirementMarkers(phrase: str) -> list[str]:
    """Lowercased, distinctive content-word markers for one requirement phrase.

    Hyphenated/slashed compounds split into parts ("auto-refresh" -> auto, refresh; "green/red" ->
    green, red); stopwords + ambient boilerplate words are dropped. These are OR-matched within a
    requirement (any one present satisfies it), so synonyms reduce false-FAIL risk while distinctive
    tokens prevent false-PASS.
    """
    words = re.findall(r"[A-Za-z][A-Za-z0-9-]*", (phrase or "").lower())
    out: list[str] = []
    for w in words:
        for part in w.split("-"):
            if len(part) >= 3 and part not in _MARKER_STOPWORDS and part not in out:
                out.append(part)
    return out


def buildContentScanVerify(marker_groups: list[list[str]], target_path: str) -> dict:
    """A compound, deterministic, stdlib-only verify: the target file's (lowercased) source must
    contain >=1 marker from EVERY group. Marked ``strict`` so the orchestrator's behavioral
    repair-fallback never rescues genuinely-partial work. On failure it PRINTS the unmet groups so
    the retry feedback tells the executor exactly which deliverable is still missing.
    """
    groups = [[str(m).lower() for m in g if m] for g in marker_groups]
    groups = [g for g in groups if g]
    code = (
        "import io,sys; "
        f"s=io.open({str(target_path)!r},encoding='utf-8',errors='ignore').read().lower(); "
        f"g={groups!r}; "
        "miss=[grp for grp in g if not any(k in s for k in grp)]; "
        "print('MISSING_REQUIREMENTS '+repr(miss)) if miss else print('ALL_REQUIREMENTS_PRESENT'); "
        "sys.exit(1 if miss else 0)"
    )
    return {"cmd": f'python -c "{code}"', "expect": "exit_zero", "strict": True}


def buildRequirementsVerify(goal: str, target_path: str) -> Optional[dict]:
    """Synthesize a compound content-scan verify for an enumerated multi-deliverable `goal` against
    `target_path`. Returns ``None`` when the goal has <2 enumerated requirements (caller keeps the
    brain-authored verify) or when too few requirements yield distinctive markers.
    """
    reqs = extractRequirements(goal)
    if len(reqs) < 2:
        return None
    groups = [requirementMarkers(r) for r in reqs]
    groups = [g for g in groups if g]
    if len(groups) < 2:
        return None
    return buildContentScanVerify(groups, target_path)


def isStrictVerify(verify: Optional[dict]) -> bool:
    """True for a deliberate multi-requirement verify (compound expect or ``strict`` flag). The
    orchestrator must NOT rescue these with its 'just run the artifact' repair fallback -- the whole
    point is that partial work fails."""
    if not isinstance(verify, dict):
        return False
    if verify.get("strict"):
        return True
    return str(verify.get("expect") or "").startswith(_COMPOUND_PREFIXES)


def _evaluate(expect: str, returncode: int, stdout: str) -> bool:
    expect = (expect or config.VERIFY_DEFAULT_EXPECT).strip()
    if expect == "exit_zero":
        return returncode == 0
    if expect.startswith("stdout_contains:"):
        needle = expect[len("stdout_contains:"):]
        return needle in stdout
    if expect.startswith("stdout_regex:"):
        pattern = expect[len("stdout_regex:"):]
        try:
            return re.search(pattern, stdout) is not None
        except re.error:
            return False
    # Compound expectations -- pass ONLY if EVERY '||'-separated needle/pattern is present.
    # This is what lets one verify assert all N deliverables of a multi-requirement goal, so a
    # subtask that did 1 of 3 can no longer slip through (the original 'partial work passed' bug).
    if expect.startswith("stdout_contains_all:"):
        needles = [n for n in expect[len("stdout_contains_all:"):].split("||") if n]
        return bool(needles) and all(n in stdout for n in needles)
    if expect.startswith("stdout_regex_all:"):
        pats = [p for p in expect[len("stdout_regex_all:"):].split("||") if p]
        if not pats:
            return False
        try:
            return all(re.search(p, stdout) is not None for p in pats)
        except re.error:
            return False
    # Unknown expectation -> conservative default.
    return returncode == 0


def runVerification(verify: Optional[dict], work_dir: str, executor_result: dict) -> dict:
    """Return a verify_result dict: {passed, cmd, expect, returncode, stdout, stderr}."""
    cmd = (verify or {}).get("cmd") if verify else None
    expect = (verify or {}).get("expect") or config.VERIFY_DEFAULT_EXPECT

    # No command authored -> trust the executor's own exit status.
    if not cmd:
        passed = bool(executor_result.get("ok"))
        return {
            "passed": passed,
            "cmd": None,
            "expect": "executor_exit_zero",
            "returncode": executor_result.get("returncode"),
            "stdout": "",
            "stderr": "" if passed else _cap(executor_result.get("stderr")),
        }

    LOG.info("Verifying: %s  (expect: %s)", cmd, expect)
    try:
        proc = _runShell(cmd, work_dir)
        # Fold stderr into the haystack ONLY when the program exited cleanly (rc==0) -- legitimate
        # programs print to stderr, but a CRASHING program must not pass a stdout_contains gate via a
        # needle that happens to appear in its traceback.
        haystack = (proc.stdout or "") + (("\n" + (proc.stderr or "")) if proc.returncode == 0 else "")
        passed = _evaluate(expect, proc.returncode, haystack)
        result = {
            "passed": passed,
            "cmd": cmd,
            "expect": expect,
            "returncode": proc.returncode,
            "stdout": _cap(proc.stdout),
            "stderr": _cap(proc.stderr),
        }
    except subprocess.TimeoutExpired:
        result = {"passed": False, "cmd": cmd, "expect": expect, "returncode": -1,
                  "stdout": "", "stderr": f"verify TIMEOUT after {config.VERIFY_TIMEOUT_SECONDS}s"}
    except Exception as e:  # noqa: BLE001
        result = {"passed": False, "cmd": cmd, "expect": expect, "returncode": -1,
                  "stdout": "", "stderr": f"verify error: {e}"}
    LOG.info("Verify %s -> %s (rc=%s)", "PASS" if result["passed"] else "FAIL", cmd, result["returncode"])
    return result
