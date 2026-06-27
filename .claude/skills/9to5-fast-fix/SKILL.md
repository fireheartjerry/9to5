# 9TO5 Fast Fix

Use this skill for small code fixes where validated turnaround matters.

1. Inspect the nearest implementation and tests before editing.
2. Make the smallest behavior-level change that satisfies the request.
3. Run `python tools/dev.py check <changed-file>` when a mapped file exists.
4. Escalate to `python tools/dev.py fast` when the change touches shared behavior.
5. Report the commands run and any remaining risk.
