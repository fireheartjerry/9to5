---
name: dependency-audit
description: >
  Audit a project's direct and transitive dependencies for security vulnerabilities,
  version staleness, license conflicts, and unused packages. Produces a prioritized
  action list. Use before a release, after a CVE alert, or when adding new packages.
  Works for Python (requirements.txt/pyproject.toml) and Node.js (package.json).
---

## Purpose

Know what's in your supply chain before it bites you. Catch CVEs, bloat, and license risk early.

## When to invoke

- Before cutting a release
- After `pip install <new-package>` or `npm install <new-package>`
- CVE or security advisory mentions a package you use
- Explicitly: `/dependency-audit`, "audit dependencies", "check for vulnerabilities"
- When requirements.txt hasn't been touched in 3+ months

## Protocol

### Phase 1 — Locate dependency manifests

Check for:

```
requirements.txt          # Python pinned deps
requirements-dev.txt      # Python dev deps
pyproject.toml            # Python modern (check [tool.poetry.dependencies] or [project.dependencies])
setup.py / setup.cfg      # Python legacy
package.json              # Node.js
package-lock.json         # Node.js pinned
```

Read each manifest. Note:
- Pinned vs range versions (`==1.2.3` vs `>=1.2`)
- Dev vs prod deps separation
- Any `git+` or local path deps (high risk, no version pinning)

### Phase 2 — Security scan

**Python:**
```bash
pip-audit -r requirements.txt
# or:
safety check -r requirements.txt
```

If tools unavailable, grep CVE databases mentally for packages with known histories:
- `requests`, `cryptography`, `pillow`, `urllib3`, `setuptools`, `certifi` — frequently patched
- Any package pinned to a version > 12 months old is suspect

**Node.js:**
```bash
npm audit
```

### Phase 3 — Staleness check

For each direct dependency:

1. Check current latest version (via PyPI/npm if web available, else note for human follow-up).
2. Compare to pinned version.
3. Flag if pinned version is:
   - Major version behind (breaking changes likely)
   - > 6 months old with known active development upstream

### Phase 4 — License audit

Identify license for each direct dep. Flag:

| Risk | License | Reason |
|------|---------|--------|
| HIGH | GPL-2, AGPL | Copyleft — may require source disclosure |
| MED  | LGPL | Copyleft for modifications |
| LOW  | MIT, Apache-2, BSD | Permissive — generally fine |
| UNKNOWN | unlicensed | Cannot use legally |

For 9TO5 (private internal tool): LGPL is generally acceptable. GPL requires careful review.

### Phase 5 — Unused dependency check

**Python:**
```bash
pip-autoremove --list   # shows unused packages
# or manually: grep each dep name across src/*.py
```

A dep not imported anywhere in source is a candidate for removal.

### Phase 6 — Produce audit report

```
DEPENDENCY AUDIT REPORT
=======================
Project: <name>
Manifest: <file path>
Date: <session>

CRITICAL (fix before release):
  [ ] <package>==<version> — CVE-XXXX-XXXXX — upgrade to >=<safe_version>
  ...

HIGH (fix soon):
  [ ] <package>==<version> — <major version behind / AGPL license>
  ...

MED (track):
  [ ] <package>==<version> — <6+ months stale / LGPL>
  ...

LOW / info:
  [ ] <package> — possibly unused (no imports found in src/)
  ...

CLEAN (no action):
  <list of deps with no issues>

Recommended commands:
  pip install --upgrade <package1> <package2>
  pip-audit -r requirements.txt
```

## Examples

### Example A — Python project with stale cryptography

```
CRITICAL:
  [ ] cryptography==3.4.7 — CVE-2023-49083 (NULL ptr deref) — upgrade to >=41.0.6

HIGH:
  [ ] Pillow==8.3.1 — 3 major versions behind (current: 10.x); multiple CVEs in 8.x series

MED:
  [ ] requests==2.27.1 — 18 months stale; no CVEs but urllib3 dep has known issues

CLEAN:
  python-dotenv, colorama, discord.py
```

### Example B — Node project with GPL dep

```
HIGH (license):
  [ ] some-gpl-lib@1.2.0 — GPL-2.0 — private tool but copyleft still applies at distribution

LOW:
  [ ] lodash@4.17.21 — possibly unused; grep found 0 imports in src/
```

## Rules

- Never upgrade blindly. Read the changelog for breaking changes between current and target.
- Pin versions after upgrade (`==X.Y.Z` not `>=X.Y`). Unpinned deps = non-reproducible builds.
- Remove unused deps before adding new ones. Smaller surface = smaller risk.
- `git+` deps without a commit hash are functionally unpinned. Flag as HIGH regardless of other risk.
- After any upgrade: run full test suite. Dependency upgrades are silent behavior changes.
- Do not audit `venv/` or `node_modules/` contents — audit the manifest only.
