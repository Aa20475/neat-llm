# Python for the agent team

`python_execute(code, files=None)` writes `/work/main.py`, stages optional text input files, and executes the code. Both the generalist and temporary workers get it by default. Reflection can bind it to a retained specialist through the existing approved-tool mechanism.

Use it for parsers, algorithms, simulations, data transformations, and assertions. An invocation accepts up to 32,000 bytes of source and 12 input files totaling at most 64,000 bytes. File paths must be relative; traversal and replacing `main.py` are rejected. Python's standard library is available, including `csv`, `json`, `sqlite3`, `decimal`, `unittest`, and `itertools`. Input `.py` files can be imported as helper modules. Package installation and network access are unavailable.

Each invocation starts with a fresh directory. Code can write files within `/work`, but those files disappear when that invocation ends. Print results or generated file contents to retain them in the tool response; to iterate, resubmit revised code and its inputs. This is not a persistent filesystem across tool calls or chat turns. It is separate from Deep Agents' read-only `/organization` configuration tree.

The result includes `status`, `exit_code`, `stdout`, `stderr`, and truncation flags. A final expression is displayed automatically, like a Python notebook; `None` stays silent. Python exceptions return stderr and a nonzero exit code, allowing the model to fix its code. The existing run explorer records the tool call and response with the owning worker. Reflection sees the latest four Python start/finish events from each selected learning run, capped at 1,000 characters each. Generated tests are learning evidence, not independent proof of correctness.

## Executor

The host needs Linux, unprivileged user namespaces, `bubblewrap` on PATH, and `/usr/bin/python3`. The demo uses Bubblewrap 0.13.0 and system Python 3.14.7. The Python dependencies in the project's virtual environment are not exposed as an execution environment. The tool fails closed if sandbox setup is unavailable. Nested container or development-sandbox policies must permit namespace creation for this tool to work.

The executor creates new user, PID, network, IPC, UTS, and supported cgroup namespaces. It mounts system runtime files read-only, provides a fresh `/proc` and minimal `/dev`, clears the environment and inherited file descriptors, drops capabilities, disables nested user namespaces, and exposes no home, repository, database, credential file, or host socket. `/work` is a 16 MiB tmpfs; `/tmp` points to it. Generated code cannot start extra processes. The controller does not use a shell to launch Python.

Fixed limits are 10 seconds wall time, 5 seconds CPU, 256 MiB address space, 1 MiB per file, and 4,000 captured bytes per output stream. Output beyond that is drained and discarded, with explicit truncation flags. Timeout and cancellation kill and reap the sandbox. Tool calls also consume the existing run-wide tool budget. These limits and the implementation are controller-owned; reflection cannot loosen them. The version's tool source digest includes both the tool registry and executor source, so updating either requires a new organization snapshot.

This local prototype uses the host kernel and read-only system runtime, rather than a pinned VM image. It is not a production multi-tenant execution service; packaging a dedicated execution image and integrating NemoClaw/OpenShell remain follow-up work. Bubblewrap provides the isolation mechanisms; the calling application defines the policy. See [Bubblewrap's security model](https://github.com/containers/bubblewrap#sandbox-security) and [Python resource limits](https://docs.python.org/3/library/resource.html).

## Task to try

In Chat, check **Use this task for reflection** and send:

> Implement a dependency planner in Python. Input is a JSON list of jobs with `id`, integer `duration`, and a list of dependency IDs. Reject duplicate IDs, missing dependencies, and cycles. Return a deterministic topological order (alphabetical tie breaks), each job's earliest finish time assuming unlimited workers, and the total project duration. Write and execute tests covering a chain, a diamond, independent jobs, zero duration, invalid references, and cycles. Report the implementation, test results, and any remaining limitations. Delegate a bounded test-design or implementation subtask if useful.

Then trigger reflection manually. This provides opportunities to learn reusable test design, validation, and delegation procedures. A successful first run may reasonably yield no change; Python access does not guarantee topology evolution or measured improvement.

## Verification

The full suite passes 73 tests, including real sandbox execution, input files and helper imports, final-expression display, unittest discovery, host/credential/network isolation, process and file restrictions, output bounds, timeout, cancellation, and bounded reflection evidence. A live Crusoe generalist delegated to a temporary worker, which ran Python to enumerate integers from 1 through 10,000 satisfying `n*n % 97 == 4`. Its returned count (207) and sum (1,039,066) matched the independently computed answer. That run used four model calls and one Python call; it ran in a temporary database, leaving the user's task history empty. The local trace is `artifacts/python-worker-check.json`.

The initial live attempt exposed a tool usability bug: a final expression produced no output, and the worker guessed an incorrect answer. Automatic final-expression display was added and tested before repeating the same task successfully. The failed attempt is preserved as `artifacts/python-worker-check-initial.json`. This is an implementation fix, not a reflection-generated improvement.
