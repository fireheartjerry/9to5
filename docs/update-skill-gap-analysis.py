#!/usr/bin/env python3
"""
update-skill-gap-analysis.py
Acceptance check: validates that skill-gap-analysis documentation is comprehensive.
Exits 0 on pass, 1 on failure with a description of what is missing.
"""
import pathlib
import sys

SKILLS_ROOT = pathlib.Path("C:/9to5/.claude/skills")
SKILL_MD = SKILLS_ROOT / "skill_gap_analysis.md"
README_MD = SKILLS_ROOT / "skill_gap_analysis" / "README.md"

# Required sections in the main skill file
SKILL_MD_REQUIRED = [
    "## Purpose",
    "## When to invoke",
    "## Protocol",
    "### Phase 1",
    "### Phase 2",
    "### Phase 3",
    "### Phase 4",
    "### Phase 5",
    "## Examples",
    "## Rules",
    "SOLID",
    "FUZZY",
    "BLANK",
    "blast_radius",
    "Proceed:",
    "remediation:",
]

# Required sections in the README
README_REQUIRED = [
    "## What it does",
    "## How to invoke",
    "## Quick protocol",
    "## Output format",
    "## Rules",
    "## Example",
    "SOLID",
    "FUZZY",
    "BLANK",
    "blast_radius",
    "Proceed:",
]

FAILURES: list = []


def checkFile(path: pathlib.Path, required_strings: list, label: str) -> None:
    if not path.exists():
        FAILURES.append(f"[MISSING] {label}: {path}")
        return

    text = path.read_text(encoding="utf-8")

    if len(text.strip()) < 500:
        FAILURES.append(
            f"[TOO SHORT] {label}: only {len(text.strip())} chars — expected at least 500"
        )

    for needle in required_strings:
        if needle not in text:
            FAILURES.append(f"[MISSING CONTENT] {label} must contain: {needle!r}")


def main() -> int:
    checkFile(SKILL_MD, SKILL_MD_REQUIRED, "skill_gap_analysis.md")
    checkFile(README_MD, README_REQUIRED, "skill_gap_analysis/README.md")

    if FAILURES:
        print("FAIL — skill-gap-analysis documentation is incomplete:", file=sys.stderr)
        for msg in FAILURES:
            print(f"  {msg}", file=sys.stderr)
        return 1

    print("PASS — skill-gap-analysis documentation is comprehensive.")
    print(f"  skill_gap_analysis.md  : {SKILL_MD.stat().st_size} bytes")
    print(f"  README.md              : {README_MD.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
