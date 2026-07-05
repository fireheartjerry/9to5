# `memory/` -- durable experience and retrieval substrate

Most implementation modules live in subpackages:

- `ledger/`: experience schema, DDL, run/subtask/PR records, adapters, policies, and indexes.
- `retrievals/`: retrieval core, ranking, and prompt rendering.
- `novelty/`: novelty index and store.
- `stores/`: Obsidian and user preference stores.

Top-level modules such as `memory.experience_ddl`, `memory.retrieval_rank`, and
`memory.obsidian` remain compatibility aliases.
