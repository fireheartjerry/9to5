# `agents/` -- agent roles and execution helpers

Most implementation modules live in subpackages:

- `execution/`: executors, streams, sessions, Gemini/browser/native drivers, workflow resolution.
- `review/`: adversary, architect, verifier, and verification helpers.
- `hook_handlers/`: hook entrypoints and safety checks.
- `trace/`: trace replay CLI, events, output, and self-test helpers.
- `planning/`: clarifier, elaborator, replanner, playbook, and completion-envelope helpers.
- `discovery/`: discovery and corpus support.

Top-level modules such as `agents.executor` and `agents.verifier` remain compatibility aliases.
