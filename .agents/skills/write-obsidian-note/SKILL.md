---
name: write-obsidian-note
description: Saves the current work output to the correct 9TO5 Obsidian vault path as a markdown note.
---

# write-obsidian-note

Persist the current work output as a markdown note in the correct 9TO5
vault location. Use this whenever a subtask produces an artifact, design, or log
that must survive past the session.

## Vault structure

All notes live under the disk-fallback vault root:

```
C:\9to5\vault\9to5\tasks\<task_id>_<date>\
  index.md                  task overview + status
  architect.md              architecture design doc
  replan-log.md             append-only record of replans
  subtasks\
    st-001.md               per-subtask output
    st-002.md
    ...
    st-00N-rv.md            review note for a subtask
  handoffs\
    ho-001.md               context handoff notes
```

`<task_id>` is the task's uuid4; `<date>` is the task start date. Pull both from
the task state — do not invent them.

## How to write the note

1. Resolve the target directory: `...\tasks\<task_id>_<date>\`.
2. Pick the correct file for the work:
   - Subtask output → `subtasks\st-00N.md` (zero-padded, matching the subtask id).
   - Subtask review → `subtasks\st-00N-rv.md`.
   - Architecture doc → `architect.md`.
   - Replan record → append to `replan-log.md`.
   - Task overview → `index.md`.
3. Write the content as clean markdown using the `Write` tool with the **absolute**
   path. Create parent folders if they do not exist.
4. Keep it self-contained: a heading, what was done, key decisions, and any
   references — readable by a future session with no other context.

If the task identifiers are unavailable, return the note content as markdown in
your final response instead of guessing a path.
