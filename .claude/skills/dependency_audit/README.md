# dependency-audit

Know what's in your supply chain before it bites you. Catch CVEs, bloat, and license risk early.

## What it does

Audits a project's dependency manifest (requirements.txt, pyproject.toml, package.json) across
four dimensions: security vulnerabilities, version staleness, license risk, and unused packages.
Produces a CRITICAL/HIGH/MED/LOW prioritized action list with exact upgrade commands.

## How to invoke

```
/dependency-audit
audit dependencies
check for vulnerabilities
```

Triggers: before release, after adding a new package, after a CVE advisory, requirements untouched
for 3+ months.

## Audit dimensions

| Dimension | Tool (Python) | Tool (Node) |
|-----------|--------------|-------------|
| Security  | `pip-audit` or `safety check` | `npm audit` |
| Staleness | compare pinned vs. latest on PyPI/npm | same |
| License   | manual review or `pip-licenses` | `license-checker` |
| Unused    | `pip-autoremove --list` or grep imports | `depcheck` |

## Output format

```
DEPENDENCY AUDIT REPORT
=======================
Project: <name>
Manifest: <file>

CRITICAL (fix before release):
  [ ] <pkg>==<ver> — CVE-XXXX — upgrade to >=<safe>

HIGH:
  [ ] <pkg>==<ver> — <major behind / AGPL license>

MED:
  [ ] <pkg>==<ver> — <stale / LGPL>

LOW:
  [ ] <pkg> — possibly unused

CLEAN:
  <packages with no issues>
```

## Example

```
DEPENDENCY AUDIT REPORT
Manifest: requirements.txt

CRITICAL:
  [ ] cryptography==3.4.7 — CVE-2023-49083 — upgrade to >=41.0.6

HIGH:
  [ ] Pillow==8.3.1 — 3 major versions behind; multiple CVEs in 8.x

MED:
  [ ] requests==2.27.1 — 18 months stale

CLEAN:
  python-dotenv, colorama, discord.py
```

## Rules

- Never upgrade blindly. Read the changelog for breaking changes.
- Pin versions after upgrade (`==X.Y.Z` not `>=X.Y`). Unpinned = non-reproducible.
- `git+` deps without a commit hash are functionally unpinned — flag as HIGH.
- After any upgrade: run full test suite.
- Do not audit `venv/` or `node_modules/` — audit the manifest only.

## See also

- [`../dependency_audit.md`](../dependency_audit.md) — full LLM-facing protocol
- `../test_coverage_triage/README.md` — run after upgrade to verify nothing broke
