#!/usr/bin/env python3
"""
skill-gap-analysis.py
Scan the skill inventory, score coverage against task history, emit a ranked gap report
with actionable recommendations for skill development.
Exits 0 on success, 1 on unrecoverable I/O error.

Configuration is read from skill-gap-analysis.yaml (co-located in the skills dir).
All constants fall back to hardcoded defaults when the YAML is absent or malformed.
"""
import json
import pathlib
import re
import sys
from collections import Counter

try:
    import yaml as _yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

# YAML config lives next to the other skill files; script may live elsewhere.
_YAML_CONFIG_PATH = pathlib.Path(__file__).parent.parent.parent / "skills" / "skill-gap-analysis.yaml"


def _loadYamlConfig() -> dict:
    if not _YAML_AVAILABLE:
        return {}
    for candidate in [_YAML_CONFIG_PATH]:
        if candidate.exists():
            try:
                return _yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
            except Exception:
                pass
    return {}


_YAML_CONFIG = _loadYamlConfig()
_cfg_inputs = _YAML_CONFIG.get("inputs", {})
_cfg_model  = _YAML_CONFIG.get("coverage_model", {})
_cfg_reco   = _YAML_CONFIG.get("recommendations", {})

# Resolve configured dirs against the repo root (this file lives at <repo>/.claude/skills/)
# so relative YAML values work in any checkout. Joining with an absolute right-hand side
# replaces the base, so an absolute override in the YAML still takes effect.
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

SKILLS_DIR = _REPO_ROOT / _cfg_inputs.get("skills_dir", "skills")
TASKS_DIR  = _REPO_ROOT / _cfg_inputs.get("tasks_dir",  "state/tasks")

# Skills needed to fully saturate coverage for a domain (any additional skills beyond this
# contribute nothing to coverage_fraction, which is capped at 1.0).
_COVERAGE_SAT = int(_cfg_model.get("saturation_skills", 2))
_TOP_N        = int(_cfg_reco.get("top_n", 5))

# Domain taxonomy: domain name -> set of keyword stems that signal demand/coverage
DOMAIN_MAP: dict = {
    "testing":       {"test", "tests", "pytest", "unittest", "validate", "coverage", "assert", "spec"},
    "debugging":     {"debug", "trace", "diagnos", "failure", "error", "troubleshoot", "replay", "inspect"},
    "documentation": {"doc", "docs", "documentation", "readme", "markdown", "wiki", "explain"},
    "workflow":      {"workflow", "orchestrat", "pipeline", "registry", "definition", "flow", "schedule"},
    "deployment":    {"deploy", "release", "cicd", "publish", "build", "container", "artifact"},
    "security":      {"security", "auth", "vulnerab", "secret", "credential", "permission", "audit"},
    "performance":   {"perform", "optim", "cache", "latency", "speed", "profil", "benchmark"},
    "memory":        {"memory", "obsidian", "knowledge", "persist", "context", "recall", "note"},
    "discord":       {"discord", "bot", "nightclaw", "notif", "slash", "command", "dashboard"},
    "subagent":      {"subagent", "agent", "executor", "orchestrat", "spawn", "dispatch"},
    "refactoring":   {"refactor", "cleanup", "simplif", "restructur", "modular", "extract"},
    "dependency":    {"depend", "package", "library", "requirem", "install", "lock", "version"},
    "contracts":     {"contract", "typeddict", "dataclass", "protocol", "typed", "schema", "interface"},
    "monitoring":    {"monitor", "health", "metric", "alert", "log", "observ", "telemetr"},
    "state":         {"state", "status", "lifecycl", "transition", "store", "atomic"},
    "git":           {"git", "commit", "branch", "merge", "pull", "push", "rebase", "diff"},
}

# Minimum content-token length for secondary coverage matching (avoids noise from short words)
_MIN_CONTENT_TOKEN_LEN = 5


def _stemTokens(text: str) -> list:
    """Lowercase words >=3 chars; truncate to 10 chars for crude prefix-stemming."""
    return [w[:10] for w in re.findall(r"\b[a-z][a-z0-9_]{2,}\b", text.lower())]


def loadSkillInventory() -> dict:
    """Return {skill_name: set_of_stem_tokens} for every skill in SKILLS_DIR."""
    inventory: dict = {}

    def _extractFromPath(name: str, paths: list) -> set:
        tokens: set = set(_stemTokens(name))
        for p in paths:
            if p.exists():
                tokens.update(_stemTokens(p.read_text(encoding="utf-8", errors="ignore")))
        return tokens

    if not SKILLS_DIR.exists():
        return {}
    for entry in SKILLS_DIR.iterdir():
        if entry.name.startswith(".") or entry.name.startswith("__"):
            continue
        # skip any Python scripts in the skills dir — they are not skill definitions
        if entry.suffix == ".py":
            continue
        if entry.is_dir():
            candidates = [
                entry / "skill.md",
                entry / "README.md",
                entry.parent / f"{entry.name}.md",
            ]
            inventory[entry.name] = _extractFromPath(entry.name, candidates)
        elif entry.suffix == ".md":
            inventory[entry.stem] = _extractFromPath(entry.stem, [entry])
        elif entry.suffix == ".yaml" and _YAML_AVAILABLE:
            # Register YAML-defined skills using their declared name and description.
            try:
                cfg = _yaml.safe_load(entry.read_text(encoding="utf-8", errors="ignore")) or {}
                skill_name = cfg.get("name", entry.stem)
                desc_text  = cfg.get("description", "")
                inventory[skill_name] = _extractFromPath(skill_name, []) | set(_stemTokens(desc_text))
            except Exception:
                inventory[entry.stem] = _extractFromPath(entry.stem, [])

    return inventory


def loadTaskHistory() -> list:
    if not TASKS_DIR.exists():
        return []
    tasks = []
    for tf in sorted(TASKS_DIR.glob("*.json")):
        try:
            tasks.append(json.loads(tf.read_text(encoding="utf-8")))
        except Exception as exc:
            print(f"[warn] could not parse {tf.name}: {exc}", file=sys.stderr)
    return tasks


def buildDemandCounter(tasks: list) -> Counter:
    """Count stem occurrences across goal text and subtask titles/descriptions."""
    counter: Counter = Counter()
    for task in tasks:
        meta = task.get("meta", {})
        counter.update(_stemTokens(meta.get("goal_raw", "")))
        counter.update(_stemTokens(meta.get("goal_elaborated", "")))
        for st in task.get("plan", {}).get("subtasks", []):
            counter.update(_stemTokens(st.get("title", "")))
            counter.update(_stemTokens(st.get("description", "")))
    return counter


def _skillNameTokens(skill_name: str) -> set:
    """Tokens derived from the skill name only (split on - and _)."""
    return set(re.split(r"[-_]", skill_name.lower()))


def scoreDomains(demand: Counter, inventory: dict) -> list:
    """Score each domain; return rows sorted by gap score descending.

    Primary coverage: skill name tokens matched against domain keywords.
    Secondary coverage: skill content tokens (longer words only, to reduce noise).
    Coverage saturates at _COVERAGE_SAT dedicated skills (gap_score floor is 0.0).
    """
    rows = []
    for domain, kw_stems in DOMAIN_MAP.items():
        demand_score = sum(
            cnt
            for token, cnt in demand.items()
            if any(token.startswith(kw) for kw in kw_stems)
        )

        covering_skills = [
            name
            for name, content_tokens in inventory.items()
            if (
                # primary: name-based match (high signal, low noise)
                any(
                    part.startswith(kw)
                    for part in _skillNameTokens(name)
                    for kw in kw_stems
                )
                # secondary: content-based match (only long tokens to reduce noise)
                or any(
                    tok.startswith(kw)
                    for tok in content_tokens
                    if len(tok) >= _MIN_CONTENT_TOKEN_LEN
                    for kw in kw_stems
                )
            )
        ]

        # min(.../ SAT, 1.0) caps at full coverage; 3+ skills still correctly give 1.0.
        coverage_fraction = min(len(covering_skills) / _COVERAGE_SAT, 1.0)
        gap_score = round(demand_score * (1.0 - coverage_fraction), 2)

        rows.append({
            "domain": domain,
            "demand": demand_score,
            "covered_by": covering_skills,
            "gap_score": gap_score,
        })

    return sorted(rows, key=lambda r: r["gap_score"], reverse=True)


def _coveragePct(row: dict) -> str:
    """Return human-readable coverage percentage for a scored row."""
    demand = row["demand"]
    gap = row["gap_score"]
    if demand == 0:
        return "--"
    pct = max(0.0, 100.0 * (1.0 - gap / demand))
    return f"{pct:.0f}%"


def printReport(rows: list, inventory: dict, task_count: int) -> None:
    divider = "=" * 62

    print(divider)
    print("SKILL GAP REPORT")
    print(divider)
    print(f"Tasks analyzed     : {task_count}")
    print(f"Skills in inventory: {len(inventory)}")
    print()

    print("-- Inventory ----------------------------------------------")
    for name in sorted(inventory):
        print(f"  {name}")
    print()

    print("-- Ranked Gaps (highest gap score first) ------------------")
    header = f"  {'#':<4} {'Domain':<18} {'Demand':>7}  {'Cov%':>5}  {'Covered By':<26} {'Gap':>7}"
    print(header)
    print("  " + "-" * (len(header) - 2))

    for rank, row in enumerate(rows, 1):
        coverage_label = ", ".join(row["covered_by"]) if row["covered_by"] else "NONE"
        if len(coverage_label) > 30:
            coverage_label = coverage_label[:27] + "..."
        cov_pct = _coveragePct(row)
        print(
            f"  {rank:<4} {row['domain']:<18} {row['demand']:>7}  "
            f"{cov_pct:>5}  {coverage_label:<26} {row['gap_score']:>7.2f}"
        )

    print()

    uncovered = [r for r in rows if not r["covered_by"] and r["demand"] > 0]
    if uncovered:
        print("-- Critical Gaps (demanded, zero coverage) ----------------")
        for row in uncovered:
            print(f"  * {row['domain']}  (demand={row['demand']})")
        print()

    latent = [r for r in rows if not r["covered_by"] and r["demand"] == 0]
    if latent:
        print("-- Latent Gaps (uncovered, not yet demanded) --------------")
        print("  " + ", ".join(r["domain"] for r in latent))
        print()

    # Actionable recommendations: top-N gap rows with positive gap score (N from YAML config)
    action_rows = [r for r in rows if r["gap_score"] > 0][:_TOP_N]
    if action_rows:
        print("-- Priority Actions (skill development recommendations) ---")
        for i, row in enumerate(action_rows, 1):
            if not row["covered_by"]:
                action = f"Create new skill for '{row['domain']}'"
            else:
                existing = ", ".join(row["covered_by"][:2])
                action = f"Strengthen '{row['domain']}' coverage (existing: {existing})"
            print(f"  {i}. {action}")
            print(f"     demand={row['demand']}, gap={row['gap_score']:.2f}, coverage={_coveragePct(row)}")
        print()

    print(divider)


def main() -> int:
    inventory = loadSkillInventory()
    if not inventory:
        print("[error] no skills found in", SKILLS_DIR, file=sys.stderr)
        return 1

    tasks = loadTaskHistory()
    demand = buildDemandCounter(tasks)
    rows = scoreDomains(demand, inventory)
    printReport(rows, inventory, len(tasks))
    return 0


if __name__ == "__main__":
    sys.exit(main())
