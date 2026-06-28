# External Projects

9TO5 can run against either a local checkout or a managed clone.

## Local checkout

```powershell
python main.py --goal "fix the parser bug" --work-dir C:\src\my-app --auto-approve
```

Nightclaw slash command:

```txt
/work goal:"fix the parser bug" work_dir:"C:\src\my-app"
```

## Managed clone

```powershell
python main.py --goal "add the missing test" --repo-url https://github.com/acme/app.git --auto-approve
```

Optional branch, tag, or ref:

```powershell
python main.py --goal "update docs" --repo-url https://github.com/acme/app.git --repo-ref docs-branch --auto-approve
```

Nightclaw slash command:

```txt
/work goal:"update docs" repo_url:"https://github.com/acme/app.git" repo_ref:"docs-branch"
```

Managed clones live under `state/external-projects/`. Failed clones are cleaned up.

## PR output

The run can edit files without GitHub setup, but PR creation needs:

- target is a git repo,
- `origin` remote exists,
- `gh` is installed and authenticated,
- push permission to the remote.

Launch replies warn when obvious PR prerequisites are missing.

## Safety boundaries

External runs are never self-referential unless the selected working directory is the 9TO5 install root. Common generated or sensitive paths are hard boundaries: `.env`, `.git`, `venv`, `.venv`, `node_modules`, `dist`, `build`, `.next`, `coverage`, and `__pycache__`.
