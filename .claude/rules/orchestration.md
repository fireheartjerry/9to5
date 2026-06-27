# 9TO5 Orchestration Rules

- `agents/executor.py`, `agents/hooks.py`, `config.py`, `main.py`, and `orchestrator.py` are core loop files.
- Hook changes must be non-blocking unless they are explicit safety guards.
- Executor telemetry should record prompt/context size, runtime, result, and cost when available.
- Do not change model or effort routing as part of speed work unless the task explicitly asks.
- Preserve existing dirty user changes and generated artifacts outside the requested scope.
