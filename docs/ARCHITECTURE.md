# 9TO5 Architecture

9TO5 is a personal autonomous AI orchestration system for long-horizon work sessions.

It decomposes a human goal, executes work through Claude Code subprocesses, verifies outputs, runs adversarial critique, replans when needed, and reports through Discord/web dashboards.

## Core principle

```txt
strict protocol, replaceable intelligence
```

The lifecycle, schemas, guards, state machine, verification rules, and state ownership should be deterministic and boring.

Models, Claude Code, browser models, VLMs, reviewers, and executors should be replaceable intelligence modules plugged into that protocol.

## Current mental model

### Orchestrator brain

- Local Ollama model. Brain default `OLLAMA_MODEL = qwen2.5-coder:7b` (config.py);
  vision `VLM_MODEL = qwen2.5vl:7b`, embeddings `EMBED_MODEL = nomic-embed-text`.
- Reads task state JSON and Obsidian context.
- Authors prompts.
- Plans and replans.
- Owns decisions.

### Executor hands

- Claude Code CLI subprocess.
- Executes code edits, file edits, bash, git, and local tool work.
- Does not own orchestration state.

### Python plumbing

Python wires:

```txt
Ollama prompt/decision
-> Claude Code subprocess
-> output capture
-> verification
-> state/memory update
-> adversarial review
-> replanning
-> dashboard/control update
```

## Layers

Only Layer 3 is built as the primary phase.

| Layer | Status | Role |
|---|---|---|
| Layer 1 Browser | future/partial | CDP/Playwright generic browser surface (gated by `BROWSER_LAYER_ENABLED`) |
| Layer 2 Native | future/partial | UIA/pywinauto driving desktop apps |
| Layer 3 Terminal/CLI | live | Claude Code CLI, gh, git |
| Layer 4 Local model | live | Ollama brain |

## Agent roster

| Agent | Owner/model | Main files | Responsibility |
|---|---|---|---|
| Orchestrator | Ollama | `orchestrator.py` | Plans, authors prompts, coordinates loop |
| Elaborator | Ollama | `agents/elaborator.py` | Expands human goal into approved objective |
| Architect | Claude Code CLI | `agents/architect.py` | Produces `architect.md` design doc |
| Executor | Claude Code CLI | `agents/executor.py` | Runs actual code/file/bash/git work |
| Verifier | deterministic + authored commands | `agents/verifier.py` | Runs verification command and parses expectation |
| Adversary | Ollama-backed critique | `agents/adversary.py` | Reviews executor output and raises concerns |
| Replanner | Ollama | `agents/replanner.py` | Mutates remaining subtasks after each subtask |

## Core run lifecycle

```txt
Goal
-> ElaboratedGoal
-> Architect design doc
-> TaskGraph
-> Subtask
-> ExecutionStep
-> StepResult
-> VerificationResult
-> ReviewResult
-> ReplanDecision
-> FinalRunReport
```

Everything else should attach to this spine.

Dashboards, Obsidian, ControlBus, learning traces, and Discord events should observe or derive from this lifecycle. They should not invent parallel lifecycle models.

## Core loop

1. Human provides goal + time horizon.
2. Elaborator expands the goal.
3. Human approves/edits. This is normally the last human input.
4. Architect creates design doc.
5. Orchestrator plans a JSON subtask list.
6. For each subtask:
   - Orchestrator authors Claude prompt.
   - Executor runs Claude Code subprocess.
   - Verifier runs brain-authored verify command.
   - If verification fails, retry with failure context up to max attempts.
   - Save Obsidian note.
   - Run adversary when triggered.
   - Replan if needed.
   - Update state and dashboards.
   - Check ControlBus boundaries.
7. On complete:
   - create GitHub PR via `gh` best effort
   - send Discord complete embed

## Source-of-truth ownership

| Concern | Source of truth |
|---|---|
| Current run state | task JSON / canonical state store / SQLite if introduced |
| Control commands | ControlBus |
| Persistent notes/context | Obsidian + disk fallback |
| Execution transcript | run logs / task notes / trace records |
| Verification status | verifier result object |
| Human control | Discord/web UI commands |
| File safety boundaries | Universe + self-modification guard |
| Dashboard display | derived view only |

Discord and web dashboards are windows into state, not state machines.

## Verification gate

Verifier executes a brain-authored `{cmd, expect}`.

Supported expectation modes:

```txt
exit_zero
stdout_contains:<text>
stdout_regex:<regex>
```

A subtask is done only if verification passes.

If verification fails:

1. Capture command, stdout, stderr, exit code.
2. Feed failure context into a retry prompt.
3. Retry up to `MAX_SUBTASK_ATTEMPTS`.
4. Trigger adversary or replanner if repeated failure occurs.

## Adversary triggers

Trigger adversary review on:

- uncertainty strings in Claude output
- repeated failed attempts
- every 3rd subtask as heartbeat floor
- pre-PR boundary

Adversary verdicts are advisory unless the current run mode treats them as blocking.

## Universe-constrained execution

The universe is about surgical precision, not permission.

Fields:

- `description`: scope of task
- `allowed_paths`: expected focus area; precision hint, not hard allowlist
- `allowed_to_expand_to`: related code/dependencies that may be touched if needed
- `hard_boundaries`: actual forbidden paths

Hard boundaries should include secrets, VCS internals, venvs, generated/runtime state unless explicitly authorized, and other dangerous paths.

## Learning subsystem boundary

Learning should consume traces and propose improvements.

It should not bypass:

- verifier
- adversary
- guard hooks
- universe hard boundaries
- human gates where configured
- test requirements
- source-of-truth ownership

Recommended role:

- trace recorder
- failure taxonomy
- playbook miner
- eval generator
- prompt/router optimizer
- small LoRA/adapter experiment harness

## Design smell checklist

Be suspicious of:

- multiple status vocabularies
- dashboard becoming state source
- unstructured cross-module dicts
- side-effect-heavy functions
- dynamic imports without a central registry
- self-improvement mutating live behavior without eval gates
- generated artifacts patched as source
- test commands known only by tribal memory, a frankly ridiculous species tradition
