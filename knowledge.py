"""Living Claude Code knowledge base -- mechanics for ``refreshClaudeKnowledge()``.

The Orchestrator brain (Ollama qwen2.5) has NO internet; the Python plumbing does.
This module exploits that asymmetry: it scrapes the latest Claude Code docs, reads
the installed ``.claude`` capability surface (skills / subagents / workflows / hooks /
settings) off disk, folds the existing maximalist ``claude_code.md`` self-analysis in,
writes ONE unified, timestamped reference, and compresses it into the structured
``CLAUDE CODE CAPABILITIES`` summary that ``orchestrator.refreshClaudeKnowledge`` injects
into every single Ollama system prompt.

Pure plumbing: no AI calls, no secrets, ``pathlib.Path`` everywhere, requests-only
(stdlib HTML parsing) so it adds no new dependency. Every network/disk op is best-effort
and never raises out of :func:`fetchClaudeDocs` / :func:`scanLocalClaude`.
"""
from __future__ import annotations

import re
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional

import config

LOG = config.getLogger("knowledge")

# --- canonical live-doc sources (best effort; both current + legacy domains) ----
# docs.claude.com is the current home; docs.anthropic.com still resolves/redirects.
_DOC_PAGES: tuple[str, ...] = (
    "overview", "setup", "quickstart", "common-workflows", "cli-reference",
    "interactive-mode", "slash-commands", "hooks", "hooks-guide", "sub-agents",
    "mcp", "settings", "memory", "skills", "output-styles", "statusline",
    "costs", "model-config", "headless", "sdk", "troubleshooting",
    "checkpointing", "github-actions", "iam", "security", "analytics",
)
_DOC_BASES: tuple[str, ...] = (
    "https://docs.claude.com/en/docs/claude-code/",
    "https://docs.anthropic.com/en/docs/claude-code/",
)
# Raw changelog ships in the public repo -- the single most up-to-date feature list.
_CHANGELOG_URLS: tuple[str, ...] = (
    "https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md",
)
# Where the product-self-knowledge skill may live (Anthropic-provided skill).
_PRODUCT_SELF_KNOWLEDGE_GLOBS: tuple[str, ...] = (
    "**/product-self-knowledge/SKILL.md",
    "**/product-self-knowledge/**/*.md",
    "**/claude-api/SKILL.md",
)


# ============================================================================
# HTML -> text (stdlib only, no bs4 dependency)
# ============================================================================
class _TextExtractor(HTMLParser):
    """Collect visible text, dropping <script>/<style>/<nav>/<head> content."""

    _SKIP = {"script", "style", "head", "nav", "svg", "noscript", "template"}
    _BLOCK = {"p", "div", "section", "article", "li", "tr", "br", "h1", "h2",
              "h3", "h4", "h5", "h6", "pre", "table", "ul", "ol"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._BLOCK:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in self._BLOCK:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data.strip():
            self._chunks.append(data)

    def text(self) -> str:
        raw = "".join(self._chunks)
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def _htmlToText(html: str) -> str:
    try:
        p = _TextExtractor()
        p.feed(html)
        return p.text()
    except Exception:  # noqa: BLE001
        # crude fallback: strip tags
        return re.sub(r"<[^>]+>", " ", html or "")


# ============================================================================
# 1) Fetch the latest docs (Python has internet; Ollama does not)
# ============================================================================
def fetchClaudeDocs(enabled: bool = True, timeout: Optional[int] = None) -> dict:
    """Scrape current Claude Code docs + changelog. Returns
    ``{pages: {url: text}, ok: [url...], failed: [url...], fetched_at: iso}``.
    Never raises -- a fully offline run yields empty pages and the disk knowledge
    still drives the injection."""
    timeout = timeout or config.CLAUDE_DOC_TIMEOUT_SECONDS
    result = {"pages": {}, "ok": [], "failed": [], "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds")}
    if not enabled:
        LOG.info("doc fetch disabled (CLAUDE_DOC_FETCH=false)")
        return result
    try:
        import requests  # local import: offline installs still load this module
    except Exception as e:  # noqa: BLE001
        LOG.warning("requests unavailable; skipping doc fetch (%s)", e)
        return result

    urls: list[str] = list(_CHANGELOG_URLS)
    # Prefer the current domain; fall back to legacy only for pages that 404.
    for page in _DOC_PAGES:
        urls.append(_DOC_BASES[0] + page)
    seen_pages: set[str] = set()
    for url in urls:
        try:
            r = requests.get(url, timeout=timeout, headers={"User-Agent": "9to5-knowledge-refresh"})
            if 200 <= r.status_code < 300 and r.text:
                body = r.text if url.endswith(".md") else _htmlToText(r.text)
                if body and len(body) > 200:
                    result["pages"][url] = body
                    result["ok"].append(url)
                    seen_pages.add(url.rsplit("/", 1)[-1])
                    continue
            result["failed"].append(url)
        except Exception as e:  # noqa: BLE001
            LOG.debug("doc fetch failed %s (%s)", url, e)
            result["failed"].append(url)
    # legacy-domain retry only for pages that failed on the current domain
    for page in _DOC_PAGES:
        if page in seen_pages:
            continue
        url = _DOC_BASES[1] + page
        try:
            import requests
            r = requests.get(url, timeout=timeout, headers={"User-Agent": "9to5-knowledge-refresh"})
            if 200 <= r.status_code < 300 and r.text:
                body = _htmlToText(r.text)
                if body and len(body) > 200:
                    result["pages"][url] = body
                    result["ok"].append(url)
        except Exception:  # noqa: BLE001
            result["failed"].append(url)
    LOG.info("doc fetch: %d ok, %d failed", len(result["ok"]), len(result["failed"]))
    return result


# ============================================================================
# 2) Scan the installed .claude capability surface off disk
# ============================================================================
def _parseFrontmatter(text: str) -> dict:
    """Tiny YAML-frontmatter reader (no pyyaml dep). Returns flat str->value."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    block = text[3:end]
    out: dict = {}
    key = None
    for line in block.splitlines():
        if not line.strip():
            continue
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if m:
            key, val = m.group(1).strip(), m.group(2).strip()
            out[key] = val.strip('"\'') if val else ""
        elif key and re.match(r"^\s*-\s+", line):  # YAML list item
            out.setdefault(key, [])
            if isinstance(out[key], str):
                out[key] = [out[key]] if out[key] else []
            out[key].append(re.sub(r"^\s*-\s+", "", line).strip().strip('"\''))
    return out


def _readText(p: Path, limit: int = 200_000) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")[:limit]
    except Exception:  # noqa: BLE001
        return ""


def scanLocalClaude(roots: Optional[tuple] = None) -> dict:
    """Recursively read every installed ``.claude`` surface. Returns a structured
    inventory of skills, subagents, workflows, commands, hooks, settings, MCP
    config -- the *authoritative, environment-specific* capability set. Never raises."""
    roots = roots or config.CLAUDE_SCAN_ROOTS
    inv: dict = {"skills": [], "agents": [], "workflows": [], "commands": [],
                 "settings": [], "hooks": [], "mcp_servers": [], "roots": [], "files_scanned": 0}
    seen_skill: set[str] = set()
    seen_agent: set[str] = set()
    for root in roots:
        root = Path(root)
        if not root.exists():
            continue
        inv["roots"].append(str(root))
        # --- skills: <root>/skills/<name>/SKILL.md (and plugin skills nested deeper)
        for skill_md in root.glob("**/SKILL.md"):
            inv["files_scanned"] += 1
            fm = _parseFrontmatter(_readText(skill_md))
            name = fm.get("name") or skill_md.parent.name
            if name in seen_skill:
                continue
            seen_skill.add(name)
            inv["skills"].append({"name": name, "description": (fm.get("description") or "")[:400],
                                  "allowed_tools": fm.get("allowed-tools") or fm.get("allowed_tools"),
                                  "path": str(skill_md)})
        # --- subagents: <root>/agents/*.md
        for agent_md in (root / "agents").glob("*.md") if (root / "agents").exists() else []:
            inv["files_scanned"] += 1
            fm = _parseFrontmatter(_readText(agent_md))
            name = fm.get("name") or agent_md.stem
            if name in seen_agent:
                continue
            seen_agent.add(name)
            inv["agents"].append({"name": name, "description": (fm.get("description") or "")[:400],
                                  "tools": fm.get("tools"), "model": fm.get("model"), "path": str(agent_md)})
        # --- workflows: <root>/workflows/*.{js,ts,md}
        for wf in (root / "workflows").glob("**/*") if (root / "workflows").exists() else []:
            if wf.is_file() and wf.suffix in (".js", ".ts", ".md"):
                inv["files_scanned"] += 1
                inv["workflows"].append({"name": wf.stem, "path": str(wf)})
        # --- custom slash commands: <root>/commands/*.md
        for cmd in (root / "commands").glob("**/*.md") if (root / "commands").exists() else []:
            inv["files_scanned"] += 1
            fm = _parseFrontmatter(_readText(cmd))
            inv["commands"].append({"name": cmd.stem, "description": (fm.get("description") or "")[:200],
                                    "path": str(cmd)})
        # --- settings + hooks + mcp: <root>/settings*.json , <root>/.mcp.json
        for sj in list(root.glob("settings*.json")) + list(root.glob(".mcp.json")) + \
                list((root.parent).glob(".mcp.json")):
            if not sj.exists():
                continue
            inv["files_scanned"] += 1
            inv["settings"].append(str(sj))
            try:
                import json
                data = json.loads(_readText(sj))
            except Exception:  # noqa: BLE001
                continue
            for ev, entries in (data.get("hooks") or {}).items():
                for entry in entries or []:
                    for h in entry.get("hooks", []) or []:
                        inv["hooks"].append({"event": ev, "matcher": entry.get("matcher", ""),
                                             "command": (h.get("command") or "")[:200]})
            for srv in (data.get("mcpServers") or {}):
                if srv not in inv["mcp_servers"]:
                    inv["mcp_servers"].append(srv)
    LOG.info("local .claude scan: %d skills, %d agents, %d workflows, %d hooks across %d files",
             len(inv["skills"]), len(inv["agents"]), len(inv["workflows"]), len(inv["hooks"]),
             inv["files_scanned"])
    return inv


def readProductSelfKnowledge(roots: Optional[tuple] = None) -> dict:
    """Locate + read the product-self-knowledge skill (Claude Code's own current
    state). Returns ``{found: bool, path: str|None, text: str}``. Never raises."""
    search_roots = list(roots or config.CLAUDE_SCAN_ROOTS) + [
        Path.home() / ".claude", config.SUPERCRITICAL_ROOT]
    for root in search_roots:
        root = Path(root)
        if not root.exists():
            continue
        for pattern in _PRODUCT_SELF_KNOWLEDGE_GLOBS:
            for hit in root.glob(pattern):
                if hit.is_file():
                    txt = _readText(hit, limit=60_000)
                    if txt:
                        LOG.info("product-self-knowledge found: %s", hit)
                        return {"found": True, "path": str(hit), "text": txt}
    LOG.info("product-self-knowledge skill not found in any scan root")
    return {"found": False, "path": None, "text": ""}


def readRecommendations(path: Optional[Path] = None) -> dict:
    """Read the expert recommendations doc (how 9to5 should wield Claude Code). Returns
    ``{found, path, text}``. Never raises."""
    path = Path(path or config.CLAUDE_RECOMMENDATIONS_PATH)
    if path.exists():
        txt = _readText(path, limit=300_000)
        if txt.strip():
            LOG.info("recommendations found: %s (%d chars)", path, len(txt))
            return {"found": True, "path": str(path), "text": txt}
    LOG.info("recommendations doc not present at %s", path)
    return {"found": False, "path": str(path), "text": ""}


def _executiveExcerpt(recs_text: str, max_chars: int = 2400) -> str:
    """Pull the 'Executive Recommendations' block (top-N) out of recommendations.md for
    the injection. Falls back to the document head if no executive header is found."""
    if not recs_text:
        return ""
    m = re.search(r"^##\s+Executive Recommendations.*$", recs_text, flags=re.M)
    if m:
        start = m.start()
        nxt = re.search(r"\n##\s+(?!#)", recs_text[m.end():])
        block = recs_text[start: m.end() + nxt.start()] if nxt else recs_text[start:]
    else:
        block = recs_text
    return block.strip()[:max_chars]


# ============================================================================
# 3) Build the unified, timestamped reference document
# ============================================================================
def _topHeadings(markdown: str) -> list[str]:
    return [ln.strip() for ln in (markdown or "").splitlines() if ln.startswith("## ")]


_AUTHORED_HEADER = "# Part A — Maximalist Self-Analysis (authored reference)"


def _extractAuthoredBody(prior_doc: str) -> str:
    """Pull ONLY the stable authored reference out of a prior unified doc so repeated
    refreshes never nest Parts A-D inside each other (the live Parts B/C/D are always
    regenerated). On the first run (raw authored sections, no provenance), returns the
    whole doc minus any leading provenance header."""
    if not prior_doc or not prior_doc.strip():
        return ""
    if _AUTHORED_HEADER in prior_doc:
        start = prior_doc.index(_AUTHORED_HEADER) + len(_AUTHORED_HEADER)
        rest = prior_doc[start:]
        # cut at the next top-level Part divider (B/C/D/E), tolerating a leading --- rule
        m = re.search(r"\n-{3,}\s*\n+# Part [BCDE]\b|\n# Part [BCDE]\b", rest)
        body = rest[:m.start()] if m else rest
        return body.strip()
    # first run: strip a provenance header if present, keep everything else
    return re.sub(r"^# Claude Code — Living Capability Reference.*?(?=\n## |\n# |\Z)",
                  "", prior_doc, flags=re.DOTALL).strip()


def buildUnifiedDoc(prior_doc: str, fetched: dict, local: dict, psk: dict, *,
                    refreshed_at: str, sources: list[str], recs: Optional[dict] = None) -> str:
    """Fold prior self-analysis + live docs + local capability surface +
    product-self-knowledge + expert recommendations into ONE maximalist reference,
    with provenance header."""
    recs = recs or {"found": False, "text": "", "path": None}
    lines: list[str] = []
    lines.append("# Claude Code — Living Capability Reference (9to5 knowledge base)")
    lines.append("")
    lines.append(f"> **Last refreshed:** {refreshed_at}")
    lines.append(f"> **Sources used this refresh:** {len(sources)} "
                 f"({len(fetched.get('ok', []))} live doc pages, "
                 f"{local.get('files_scanned', 0)} local .claude files, "
                 f"product-self-knowledge={'yes' if psk.get('found') else 'no'}, "
                 f"recommendations={'yes' if recs.get('found') else 'no'})")
    lines.append("> This file is regenerated by `orchestrator.refreshClaudeKnowledge()`; edit the "
                 "section authoring/compression there, not this file (it is overwritten each refresh).")
    lines.append("")
    lines.append("## Sources")
    for s in sources:
        lines.append(f"- {s}")
    lines.append("")

    # --- Part A: the maximalist self-analysis (stable authored body) ---
    authored = _extractAuthoredBody(prior_doc)
    if authored:
        lines.append("---")
        lines.append("")
        lines.append(_AUTHORED_HEADER)
        lines.append("")
        lines.append(authored)
        lines.append("")

    # --- Part B: installed capability surface (this environment, off disk) ---
    lines.append("---")
    lines.append("")
    lines.append("# Part B — Installed Capability Surface (this environment, scanned live)")
    lines.append("")
    lines.append(f"Scanned roots: {', '.join(local.get('roots', [])) or '(none found)'}")
    lines.append("")
    lines.append("## Installed skills")
    for s in local.get("skills", []):
        lines.append(f"- **{s['name']}** — {s['description']}")
    if not local.get("skills"):
        lines.append("- (none found on disk)")
    lines.append("")
    lines.append("## Installed subagents")
    for a in local.get("agents", []):
        lines.append(f"- **{a['name']}** (tools: {a.get('tools') or '*'}; model: {a.get('model') or 'inherit'}) — {a['description']}")
    if not local.get("agents"):
        lines.append("- (none found on disk)")
    lines.append("")
    lines.append("## Installed workflows")
    for w in local.get("workflows", []):
        lines.append(f"- {w['name']} — `{w['path']}`")
    if not local.get("workflows"):
        lines.append("- (none found on disk)")
    lines.append("")
    lines.append("## Custom slash commands")
    for c in local.get("commands", []):
        lines.append(f"- /{c['name']} — {c['description']}")
    if not local.get("commands"):
        lines.append("- (none found on disk)")
    lines.append("")
    lines.append("## Configured hooks")
    for h in local.get("hooks", []):
        lines.append(f"- `{h['event']}` matcher=`{h['matcher']}` -> `{h['command']}`")
    if not local.get("hooks"):
        lines.append("- (none configured)")
    lines.append("")
    lines.append("## MCP servers configured on disk")
    lines.append(", ".join(local.get("mcp_servers", [])) or "(none in scanned settings)")
    lines.append("")

    # --- Part C: product-self-knowledge (Claude's own current state) ---
    if psk.get("found"):
        lines.append("---")
        lines.append("")
        lines.append("# Part C — product-self-knowledge skill (verbatim)")
        lines.append(f"Source: `{psk.get('path')}`")
        lines.append("")
        lines.append(psk.get("text", "").strip())
        lines.append("")

    # --- Part D: latest live documentation (scraped) ---
    if fetched.get("pages"):
        lines.append("---")
        lines.append("")
        lines.append("# Part D — Latest Live Documentation (scraped this refresh)")
        lines.append("")
        for url, text in fetched["pages"].items():
            lines.append(f"## {url}")
            lines.append("")
            lines.append(text[:14_000].strip())
            lines.append("")

    # --- Part E: expert recommendations (how 9to5 should wield Claude Code) ---
    if recs.get("found") and recs.get("text", "").strip():
        lines.append("---")
        lines.append("")
        lines.append("# Part E — Expert Recommendations (how 9to5 should wield Claude Code)")
        lines.append(f"Source: `{recs.get('path')}`")
        lines.append("")
        lines.append(recs["text"].strip())
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def diffHeadings(prior_doc: str, new_doc: str) -> dict:
    """Naive 'what changed' delta on top-level headings (for the refresh log)."""
    old = set(_topHeadings(prior_doc))
    new = set(_topHeadings(new_doc))
    return {"added": sorted(new - old), "removed": sorted(old - new)}


# ============================================================================
# 4) Compress into the CLAUDE CODE CAPABILITIES injection summary
# ============================================================================
# A fixed, distilled cheat-sheet that always travels with the injection so Qwen
# can reason about primitives even when the live scrape is empty. Kept tight on
# purpose -- the 7B brain's context is the scarce resource.
_DISTILLED_CHEATSHEET = """\
### Effort levels (set `effort_level`)
- default -> --effort medium  (everyday file ops)
- high    -> --effort high    (normal coding)
- xhigh   -> --effort xhigh   (complex algorithmic/architectural work)
- ultracode -> --effort max   (hardest, deepest-reasoning subtasks; pairs with multi-agent workflows)

### Headless CLI the executor uses
`claude --print --dangerously-skip-permissions --settings <file> --fallback-model <m> [--effort <lvl>] --add-dir <root>`
- prompt is delivered on STDIN; output is captured. Hooks/permissions load from --settings.
- --fallback-model auto-fails-over on rate-limit/overload. --disallowedTools "Edit(<path>)" blocks edits.

### Primitives the brain composes per subtask (the invocation spec)
- claude_md_inject: rich just-in-time context auto-read from CLAUDE.md (exact paths, acceptance cmd, conventions, do-not-touch).
- skills_to_invoke: reusable playbooks (named with a leading /). Use when one matches the subtask.
- subagent: an isolated read-only analyst (separate context). Use for design/security review.
- effort_level: pick by difficulty (table above).
- pre_tool_hooks / post_tool_hooks: deterministic guardrails (block_destructive on any Bash; write_obsidian/log_all to persist).
- use_workflow + workflow_definition: DYNAMIC WORKFLOW. Set when the subtask has >3 internal steps, uses
  multiple tools, needs parallel reasoning, or benefits from structured orchestration -- emit a full multi-phase
  workflow_definition instead of a flat prompt. Otherwise keep use_workflow=false and author a precise prompt.

### Primitive-selection decision tree (ask before every spec)
1. Is there an installed SKILL for this exact job? -> name it in skills_to_invoke.
2. Is the work read-only analysis/review? -> route it to a SUBAGENT for isolation.
3. Is it a multi-step/parallel/structured job (>3 steps, many tools)? -> use_workflow=true with a workflow_definition.
4. Otherwise -> one self-contained imperative prompt with exact paths + acceptance criteria.
5. Pick effort by difficulty; add block_destructive whenever Bash may run; always persist via write_obsidian/log_all.
Never emit a generic flat prompt when a more powerful Claude Code primitive fits the subtask.

### Scheduling / waiting / recurrence (when a subtask must poll, wait, or repeat)
- Single event-gated wait (a script emits a line when ready) -> instruct the executor to use the Monitor tool (stream-and-wake; no polling).
- In-session recurring poll, fixed cadence -> /loop <interval> <prompt>  (units s/m/h/d; CronCreate-backed; session-scoped, 7-day expiry).
- In-session recurring, cadence should adapt -> /loop <prompt>  (dynamic; ScheduleWakeup-driven; bare continuation uses the <<autonomous-loop-dynamic>> sentinel).
- Durable agent that must run with NO open session (daily/cron, cloud) -> /schedule (cloud routine).
- A long background job already kicked off -> do NOT poll it (the harness re-invokes on completion); set only a long fallback wait.
- Cadence economics: prompt-cache TTL is ~300s and refreshes on each read. Warm polling stays UNDER 300s (≈240s); never pick exactly 300s; idle ticks 1200-1800s. delaySeconds is clamped to [60,3600].
- TWO FOOTGUNS to forbid: (a) NEVER schedule an expensive slash command as a wakeup prompt -- it re-fires the WHOLE command (sub-agents, side effects); use the sentinel instead. (b) NEVER author a tight, sleepless shell polling loop (it exhausts API quotas and orphans as a background process) -- add explicit sleeps or use Monitor."""


def compressForInjection(unified_doc: str, local: dict, fetched: dict,
                         max_chars: Optional[int] = None, recs: Optional[dict] = None) -> str:
    """Distill the unified reference into the structured ``CLAUDE CODE CAPABILITIES``
    block. Prioritizes (per spec): installed skills + invocation, installed subagents +
    tool access, workflows, effort levels, hook types, MCP servers, CLAUDE.md best
    practices, non-interactive CLI patterns, advanced chaining/dynamic-workflow guidance,
    plus the expert executive recommendations. Caps length so a 7B context never overflows."""
    max_chars = max_chars or config.CLAUDE_CAPABILITIES_MAX_CHARS
    parts: list[str] = []

    # Executive expert recommendations FIRST -- the highest-leverage, brain-actionable slice.
    if recs and recs.get("found"):
        ex = _executiveExcerpt(recs.get("text", ""))
        if ex:
            parts.append("### Expert recommendations (apply to EVERY spec; full set = Part E of claude_code.md)")
            parts.append(ex)
            parts.append("")

    skills = local.get("skills", [])
    if skills:
        parts.append("### Installed skills (invoke by name in skills_to_invoke / via /<name>)")
        for s in skills[:40]:
            parts.append(f"- {s['name']}: {s['description'][:160]}")
    parts.append("")
    agents = local.get("agents", [])
    if agents:
        parts.append("### Installed subagents (route isolated analysis here)")
        for a in agents[:30]:
            parts.append(f"- {a['name']} (tools: {a.get('tools') or '*'}): {a['description'][:140]}")
    parts.append("")
    if local.get("workflows"):
        parts.append("### Saved workflows")
        parts.append(", ".join(w["name"] for w in local["workflows"][:30]))
        parts.append("")
    if local.get("hooks"):
        parts.append("### Configured hooks (deterministic guardrails already wired)")
        evs: dict = {}
        for h in local["hooks"]:
            evs.setdefault(h["event"], set()).add(h["matcher"] or "*")
        for ev, ms in evs.items():
            parts.append(f"- {ev}: matchers {', '.join(sorted(ms))}")
        parts.append("")
    if local.get("mcp_servers"):
        parts.append("### MCP servers (tools named mcp__<server>__<tool>; load via ToolSearch)")
        parts.append(", ".join(local["mcp_servers"][:40]))
        parts.append("")

    parts.append(_DISTILLED_CHEATSHEET)
    parts.append("")
    # a pointer index into the full on-disk reference, so the brain knows what exists.
    # Skip scraped live-doc URL headings (Part D) -- they are noise the brain cannot fetch.
    idx = [h for h in _topHeadings(unified_doc)
           if "http://" not in h and "https://" not in h]
    if idx:
        parts.append("### Full reference index (see claude_code.md on disk for detail)")
        parts.append("; ".join(h.replace("## ", "") for h in idx[:60]))

    out = "\n".join(parts).strip()
    if len(out) > max_chars:
        out = out[:max_chars].rsplit("\n", 1)[0] + "\n... (truncated; full detail in claude_code.md)"
    return out
