"""Data-quality & safety gate (subsystem G) -- guards every SIE training set.

Bad data is the fastest way to make a self-improving system *worse*, so nothing reaches
a trainer without passing through here: schema validation, eval-suite **decontamination**
(never train on what we grade with), **secret/PII scrubbing**, and **dedup**. Pure-stdlib
and fully offline-testable.

See the spec (subsystem G) + learning/distill.py.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable, Optional

import config
from learning import eval_harness

LOG = config.getLogger("sie.dataset")

# Secret signatures we refuse to train on (redacted, not just dropped, so a partially
# secret-bearing example can still contribute its non-secret content).
_SECRET_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"sk-[A-Za-z0-9]{16,}"),                       # OpenAI-style
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),                      # GitHub PAT
    re.compile(r"AKIA[0-9A-Z]{16}"),                          # AWS access key id
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),             # Slack token
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),        # private key blocks
    re.compile(r"(?i)\b(api[_-]?key|secret|token|password)\b\s*[:=]\s*\S+"),  # generic kv
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{12,}"),       # bearer tokens
)
_REDACTION = "<REDACTED>"


def has_secret(text: str) -> bool:
    return any(p.search(text or "") for p in _SECRET_PATTERNS)


def scrub(text: str) -> str:
    """Redact secret-looking spans. Idempotent."""
    out = text or ""
    for p in _SECRET_PATTERNS:
        out = p.sub(_REDACTION, out)
    return out


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def suite_signatures(suite: Optional[list[dict[str, Any]]] = None) -> set[str]:
    """Normalized goal strings of the eval suite -- the held-out set we must NOT train on."""
    goals = suite if suite is not None else eval_harness.load_suite()
    return {_norm(g.get("goal", "")) for g in goals if g.get("goal")}


def validate(example: dict[str, Any]) -> bool:
    """A trainable example needs a non-empty prompt and completion (both strings)."""
    p, c = example.get("prompt"), example.get("completion")
    return isinstance(p, str) and isinstance(c, str) and bool(p.strip()) and bool(c.strip())


def _hash(example: dict[str, Any]) -> str:
    return hashlib.sha256((example.get("prompt", "") + "\x00"
                           + example.get("completion", "")).encode("utf-8")).hexdigest()


def is_contaminated(example: dict[str, Any], sigs: set[str]) -> bool:
    """True if the example's goal/prompt overlaps the held-out eval suite."""
    text = _norm(example.get("goal", "") or example.get("prompt", ""))
    if not text:
        return False
    return any(sig and (sig in text or text in sig) for sig in sigs)


def clean(examples: Iterable[dict[str, Any]], *,
          suite: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    """Run the full gate. Returns {examples: [...clean...], stats: {...}}.

    Order: validate -> decontaminate -> scrub secrets -> dedup. The order matters:
    we scrub before dedup so two examples differing only in a secret collapse to one.
    """
    sigs = suite_signatures(suite)
    stats = {"in": 0, "dropped_invalid": 0, "dropped_contaminated": 0,
             "scrubbed": 0, "dropped_dup": 0, "out": 0}
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for ex in examples:
        stats["in"] += 1
        if not validate(ex):
            stats["dropped_invalid"] += 1
            continue
        if is_contaminated(ex, sigs):
            stats["dropped_contaminated"] += 1
            continue
        cleaned = dict(ex)
        if has_secret(cleaned["prompt"]) or has_secret(cleaned["completion"]):
            cleaned["prompt"] = scrub(cleaned["prompt"])
            cleaned["completion"] = scrub(cleaned["completion"])
            stats["scrubbed"] += 1
        h = _hash(cleaned)
        if h in seen:
            stats["dropped_dup"] += 1
            continue
        seen.add(h)
        out.append(cleaned)
    stats["out"] = len(out)
    LOG.info("dataset gate: %s", stats)
    return {"examples": out, "stats": stats}
