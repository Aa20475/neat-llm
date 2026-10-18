# Project workspace and coding tools

Each conversation has a persistent project under the agent-visible `/work` directory. Files survive tool calls, later conversation turns, and controller restarts. The controller stores text snapshots in SQLite and stages them into an isolated filesystem for execution. No host project or credential directory is mounted.

Private chat and opted-in learning tasks use separate workspaces, so checking “Use this task for reflection” does not silently share earlier private files. Start a new conversation for a new project.

## Tool interface

| Tool | Arguments | Behavior |
| --- | --- | --- |
| `project_list` | `prefix=""` | List file paths and sizes, optionally below a directory. |
| `project_read` | `path, start_line=1, max_lines=200` | Read a saved file with line numbers. |
| `project_search` | `query, prefix=""` | Literal text search; returns paths and matching lines. |
| `project_write` | `path, content` | Create or replace a UTF-8 file. |
| `project_edit` | `path, old_text, new_text` | Replace exactly one matching occurrence; ambiguous or stale edits fail. |
| `project_delete` | `path` | Delete one project file. |
| `python_execute` | `file_path, script_args=[]` | Execute a saved Python script or test file. |
| `python_execute` | `code, files=None` | Optional scratch mode: save code as `_scratch.py`, stage supplied files, then execute. |
| `project_diff` | `worker_id` | Inspect a completed worker's changes against its starting snapshot. |
| `project_merge` | `worker_id, paths` | Apply selected worker changes; parent edits cause a conflict instead of being overwritten. |

File paths are relative to the project, or begin with `/work/`. Host paths and traversal are rejected. Existing `read_file` reads the separate, read-only `/organization` configuration tree; project files use the tools above. Decimal arithmetic, planning, and delegation tools remain available.

## Coding workflow

For a scheduler task, the agent should build this tree:

```text
/work/
  scheduler.py
  tests/
    test_scheduler.py
  results.json
```

The normal sequence is:

```python
project_list()
project_write(path="scheduler.py", content="...")
project_write(path="tests/test_scheduler.py", content="...")
python_execute(file_path="tests/test_scheduler.py", script_args=["-v"])
project_read(path="scheduler.py")
project_edit(path="scheduler.py", old_text="...", new_text="...")
python_execute(file_path="tests/test_scheduler.py", script_args=["-v"])
```

These illustrate tool calls, not Python functions available inside the sandbox. Tests can import `scheduler` because `/work` is on the module search path. Standard-library `unittest`, JSON, CSV, and algorithm code are supported. Package installation, arbitrary shell commands, and network access are unavailable.

Every execution starts a fresh Python process. **Files persist; variables do not.** Save reusable definitions in modules and import them on the next call. A final expression is displayed automatically. Tools return the actual exit code, bounded stdout/stderr, changed file paths, and a workspace digest.

Text files created or changed by Python are saved after ordinary success or failure, including assertion failures. Timeout, cancellation, or an invalid export leaves the saved input files intact. Non-regular files and binary artifacts are not imported; invalid exports report a persistence error. `__pycache__` and `.pyc` files are excluded.

## Subagents

Each `task` invocation gets a copy of the parent's current project and its own role configuration. Workers can inspect and edit their copy. Their final response includes a workspace ID and changed paths. The parent uses `project_diff`, then `project_merge` to accept selected changes. Changes never merge automatically. Conflicting parent edits cause the entire requested merge to fail without partial changes; the parent can resolve them with targeted edits.

Worker branches are retained in that run's replay record. The merged parent project continues into later conversation turns. Unmerged branches stay in the historical run record and do not become the next turn's project.

## Persistence and reflection

`project_workspaces` stores each conversation's current files. `run_projects` saves the starting files, latest files, and worker branches for each run. Run explorer displays both the starting and latest file snapshots. Replay JSON also includes worker branches.

User-task evaluation gives both the incumbent and candidate independent copies of the source run's **starting** files. It never seeds either branch with the completed solution. Reflection receives bounded tool results and the saved file inventory. Self-written tests remain learning evidence, not independent proof of correctness.

Deleting a conversation removes its current workspace. Referenced historical runs retain their file snapshots for replay; unreferenced deleted runs lose their snapshots with the run.

## Loop handling

Aggregate execution budgets remain unlimited. If the same worker repeats the same failed coding tool call on identical project files three times, the controller marks the run **incomplete** and stops before another model call. Different file contents allow a new attempt. Saved files and failure traces remain inspectable.

This detects repeated failures, not every possible unproductive loop. It does not claim that a successful Python exit proves task correctness.

## Executor and limits

The host needs Linux, Bubblewrap, unprivileged user namespaces, and `/usr/bin/python3`. The executor uses isolated namespaces, a cleared environment, read-only system runtime files, and a 16 MiB `/work` tmpfs. A supervisor stages inputs, launches the restricted Python worker, drains output, and exports regular UTF-8 files. Generated code cannot start extra processes. No repository, database, credentials, home directory, or host socket is exposed.

Limits: 10 seconds wall time per execution, 5 seconds CPU, 256 MiB worker address space, 1 MiB per file, 128 persisted files totaling 4 MiB, and 4,000 bytes per output stream. These are execution and storage constraints, not aggregate model-call budgets. Timeout and cancellation kill and reap the sandbox. Production multi-tenant hosting and NemoClaw/OpenShell deployment remain separate work.

## Upgrade an existing organization

```bash
.venv/bin/python -m company workspace-upgrade
```

This creates an explicit new configuration with project tools and the current tool implementation digest, preserving the existing topology, budgets, history, and immutable older versions. It records an operator settings change, not a reflection promotion. The app does not restart or begin inference.

## Verification

The full suite has 113 passing tests. Coverage includes module imports across executions, edits followed by failing and repaired tests, generated text files, persistence after reopening SQLite, private/learning separation, path and sandbox isolation, worker-copy conflicts, real SDK delegation and merging with a scripted model, cancellation, repeated-failure termination, deletion, and equal starting files for paired evaluation. Browser checks cover file selection, starting/latest snapshots, mobile rendering, and literal rendering of file contents.

A bounded live Crusoe check saved `arithmetic.py`, executed an import, reopened the store, and used a later turn to create and run two unittest cases against the saved module. Both tests passed and the module survived unchanged. The first turn took three model calls; the follow-up took twelve. This verifies the persistence path, not a scheduler benchmark improvement or efficient model behavior. Local evidence is saved in `artifacts/workspace-live-check.json` and `artifacts/project-files-ui-check.json`.
