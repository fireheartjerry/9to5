# 9TO5 Iteration Bench

Use this skill to compare speed changes without guessing.

1. Run `python tools/dev.py iteration-health` to inspect the current state.
2. List benchmark tasks with `python tools/dev.py bench-iteration --dry-run`.
3. Run `python tools/dev.py bench-iteration` when the worktree is ready for measurements.
4. Compare reports under `logs/iteration_bench/`.
5. Treat validated task time and successful checks as the primary speed metric.
