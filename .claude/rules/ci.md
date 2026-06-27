# 9TO5 CI Rules

- Treat PR fast, PR slow, smoke/e2e, and nightly exhaustive checks as separate lanes.
- Workflow-only edits need workflow validation plus workflow registry tests.
- Docs-only edits need docs validation and repo-map checks, not the full slow suite.
- Use `python tools/dev.py ci-local` for a local approximation of the cheapest useful CI path.
- Long CI commands should show either pytest heartbeats or GitHub step summaries.
