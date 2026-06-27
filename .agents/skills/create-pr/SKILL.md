---
name: create-pr
description: Opens a GitHub PR with a proper title, body, and labels via gh.
---

# create-pr

Commit the finished work to a feature branch and open a GitHub pull request using
the `gh` CLI. Run every command from inside the working git repository.

## Preconditions

First confirm the working directory is a git repo:

```bash
git rev-parse --is-inside-work-tree
```

If this fails (not a git repo), **skip gracefully** — do not init a repo, do not
error out. Report that the working dir is not a git repo and that PR creation was
skipped, then stop.

## Steps

1. **Branch.** Create/switch to a descriptive feature branch (do not commit to the
   default branch):

   ```bash
   git checkout -b feat/<short-descriptive-slug>
   ```

2. **Stage and commit.** Stage the changes and commit with a clear message:

   ```bash
   git add -A
   git commit -m "<concise summary of what changed>"
   ```

3. **Push** the branch and set upstream:

   ```bash
   git push -u origin feat/<short-descriptive-slug>
   ```

4. **Open the PR** with a descriptive title, a body summarizing *what changed* and
   *how it was verified*, and appropriate labels:

   ```bash
   gh pr create \
     --title "<descriptive PR title>" \
     --body "$(cat <<'EOF'
   ## What changed
   - <bullet summary of the change>

   ## How it was verified
   - <tests run / commands / manual checks and their results>
   EOF
   )" \
     --label "<label-1>" --label "<label-2>"
   ```

   Choose labels that fit the change (e.g. `enhancement`, `bug`, `documentation`).
   If a label does not exist in the repo, drop it rather than failing the command.

## Notes

- Only commit/push when the work is actually complete and verified.
- Keep the title short and imperative; put detail in the body.
- If `gh` is not authenticated or `gh pr create` fails, report the exact error and
  the branch that was pushed so the work is not lost.
