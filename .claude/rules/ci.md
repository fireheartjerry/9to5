# 9TO5 CI Rules

- Lanes are now: PR = affected-tests-only, fail-closed; push-to-main = full suite, parallel;
  nightly = exhaustive + 3.11 compatibility.
- **PR lane** (`classify` job → `tools/ci_affected.py`) runs only the tests covering the
  PR's changed files, without the `-m "not slow"` filter. It falls back to the full fast
  lane whenever: >25 changed files; any non-`.py` change; any deleted/renamed file; a
  sensitive file changed (`tests/conftest.py`, any `*/conftest.py`, `pytest.ini`,
  `config.py`, `tests/factories.py`, `tests/progress_reporter.py`, `tools/repo_map.py`,
  `tools/affected_tests.py`, `tools/ci_affected.py`, `.github/workflows/*`,
  `requirements*`); or any changed non-test `.py` mapping to zero tests. PR fast lane is
  Python 3.12 only.
- **Push-to-main** runs `fast` (full `-m "not slow"`), `slow`, `dry-run-smoke`, and
  `e2e-smoke` concurrently — none of them wait on `fast`.
- **Nightly/manual** runs `exhaustive` (full slow lane, fuzz seeds) plus
  `nightly-fast-py311` (the 3.11 leg dropped from PRs) plus smokes.
- Workflow-only edits need workflow validation plus workflow registry tests.
- Docs-only edits need docs validation and repo-map checks, not the full slow suite.
- Use `python tools/dev.py ci-local` for a local approximation of the cheapest useful CI path.
- Long CI commands should show either pytest heartbeats or GitHub step summaries.
