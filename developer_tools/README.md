# Developer tools

`developer_tools/` is the one home for project-understanding and change-safety utilities:

- `introspection/` builds a typed model of a project tree.
- `exploration/` ranks solution approaches from that model.
- `refactoring/` predicts impact and applies guarded file transactions.

Use `python -m developer_tools.introspection`, `python -m developer_tools.exploration`, or `python -m developer_tools.refactoring` for their CLIs.
