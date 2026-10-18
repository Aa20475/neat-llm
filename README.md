# neat-llm

[Proposed implementation design](docs/DESIGN.md): persistent agent organizations with reflection over memory, prompts, skills, tools, and topology, using LangChain's Deep Agents framework and Crusoe inference with a NemoClaw/OpenShell integration path.

V0 is one generalist that spawns temporary subagents as needed. The reflection loop has its own memory of improvement attempts and results. See the [reflection cost optimization plan](docs/REFLECTION_COST_PLAN.md) for staged guidelines on measuring and reducing learning overhead.

[Demo and submission plan](docs/DEMO.md): a one-minute storyboard, available NemoClaw visualization capabilities, and the submission checklist.

[Pitch cheat sheet](docs/PITCH_CHEATSHEET.md) covers the current models, prompts, architecture, and judging Q&A. [Elevator pitch scripts](docs/ELEVATOR_PITCH.md) provide ten-second, thirty-second, and one-minute versions.

Steps 1–4 include Crusoe integration, persistent execution, a local visualizer, separate reflection memory, typed proposals, paired evaluation, atomic activation, and a frozen held-out audit. The UI also supports chat with the active team and a button to run reflection. Real experiments exercised rejection, revocation, and duplicate detection. The active topology remains one generalist; an operator settings change removed execution budgets. Reliable learned improvement has not been demonstrated.

[Step 2 verification](docs/STEP2_RESULTS.md): 20 local tests pass, real temporary delegation passes, and restart preserves v0. The first learning run scored 1/2; the sorting failure is retained for reflection.

[Step 3 results](docs/STEP3_RESULTS.md) records the live experiments, their limits, and the adaptation overhead. [Step 4 results](docs/STEP4_RESULTS.md) records the final audit: both branches scored 0/4 executions across two distinct held-out tasks. Those historical records were archived locally when the workspace was reset to a fresh v0. The full test suite has 134 passing tests.

For interactive experimentation, [LLM-reviewed promotion](docs/LLM_REVIEW.md) replays your task on both versions and lets a separate, blinded LLM call select a preferred answer. This is a subjective prototype gate; it does not establish objective correctness or general improvement.

The generalist and its workers can [inspect, edit, and execute persistent projects](docs/PYTHON_TOOL.md). Files survive calls and conversation turns; Python processes remain isolated. Workers edit copies, and the parent reviews and merges selected changes. The run viewer shows saved files, and repeated identical coding failures stop with an incomplete result.

GLM-5.3 uses enabled thinking with low reasoning effort. An existing installation using the older disabled-thinking setting can apply `.venv/bin/python -m company reasoning-upgrade` while idle. This creates an operator version and preserves history, topology, and aggregate budgets. The [model documentation](https://docs.z.ai/guides/llm/glm-5.3) explains its always-on reasoning. Provider-truncated replies are recorded as incomplete, including child-worker responses; the trace records finish reasons. Complete final answers are no longer silently clipped to the trace excerpt size.

## Open the visualizer

```bash
.venv/bin/python -m company.viewer --port 8765
```

Open **http://127.0.0.1:8765**. Browsing records does not start inference. The UI refreshes every five seconds and supports narrow screens.

- **Chat:** send a task to the active topology. Each message pins the active version when execution starts and links to its actual workers and tool trace. Check **Use this task for reflection** to share a standalone task and its result as learning evidence. Opted-in follow-ups carry up to five earlier shared exchanges and 24,000 characters, stopping at a private-chat boundary. Their full input snapshot is saved for replay. Ordinary chat carries recent context and remains excluded from reflection; start a new conversation for an independent task. Each message is capped at 8,000 characters. New runs have no aggregate model-call, tool-call, worker-count, or wall-time budget. Enter sends; Shift+Enter adds a line. Responses are ungraded and do not automatically trigger reflection.

  Select a conversation and click **Delete conversation** to remove its messages, current workspace, and unreferenced run traces. Runs used by saved reflections, proposals, or audits retain historical file snapshots and remain inspectable, but are excluded from new reflection proposals. Existing versions and reflection lessons remain unchanged. Deletion requires confirmation and is available when the controller is idle.

  While a chat task is running, **Stop task** appears in the page header. It cancels that turn, including active worker/tool execution, preserves saved files and trace, and opens Chat with an editable status question. Nothing is sent automatically. Once cleanup finishes, send your question or a revised instruction. Recent tool results from interrupted attempts enter follow-up context; status questions do not automatically resume the earlier task. The button controls chat tasks started by this viewer, not reflection or another CLI process.
- **Run explorer:** inspect tasks, workers, events, outputs, pinned configurations, usage, and downloadable replay JSON. Learning means practice evidence; validation means candidate comparisons; checks verify execution plumbing; held-out means frozen final measurements.
- **Reflection lab:** attempts appear directly below **Run reflection**, newest first, including duplicates, failures, and no-change results. The sidebar badge counts attempts; the proposal panel separately counts saved candidates. Each attempt shows its outcome, time, usage, full record, and a link to its proposal when available. **Run reflection** starts the paid propose/evaluate/activate cycle. For custom tasks, the latest evidence task is replayed on both versions and a separate LLM can recommend promotion. The UI labels these results **LLM-reviewed · subjective**, with the reviewer's reason and answer trace links. Benchmark proposals retain their deterministic gate. Duplicates skip evaluation.
- **Versions:** inspect immutable configurations, the active pointer, activation/revocation and operator settings history, and frozen held-out comparisons with links to individual runs.

Chat and reflection use the same controller lock as CLI execution, so paid operations cannot overlap. The server accepts action requests only from its own local origin. API keys stay on the server. Conversation messages and model output render as text, not executable HTML.

[Interactive UI verification](docs/UI_RESULTS.md) records the successful live chat, contextual follow-ups, reflection-button check, and browser validation.

The viewer is bound to loopback and is not a public deployment. History currently lists all runs; campaign grouping and pagination are planned with the [Step 5 benchmark phase](docs/BENCHMARK_ROADMAP.md).

## Local setup

The project environment is `.venv`. For a fresh checkout:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
.venv/bin/python -m pip install --no-deps -e .
```

Copy `.env.example` to `.env` only if `.env` does not already exist, then configure the Crusoe key. The environment and credential file are ignored by Git. Installed package versions are pinned in `requirements.lock.txt`; Python 3.14 was used for this setup.

Python execution also requires Linux with unprivileged user namespaces, `bubblewrap` (`bwrap`) and `/usr/bin/python3`. Bubblewrap 0.13.0 is installed on the demo host. There is no fallback to running generated code on the host. See [Python tool setup and limits](docs/PYTHON_TOOL.md).

```bash
.venv/bin/python -m company.preflight
.venv/bin/python -m pytest -q
```

The preflight makes real Crusoe calls: model discovery, a multiplication tool round trip, then a Deep Agents general-purpose child delegation. It caps model calls at eight, disables SDK retries, sets per-call output/time limits, and records usage in `artifacts/preflight.json` with separate attempt history. It does not evaluate the held-out task set. Run it with outbound access to Crusoe enabled.

The configured model is `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` through Crusoe Chat Completions. The tested request path uses automatic tool selection and disables Nemotron thinking through `chat_template_kwargs`. Forced `tool_choice="required"` exhausted the response limit during setup; the preflight verifies actual tool invocation instead of relying on forced selection.

## Demo workload

[Order normalization](fixtures/orders/spec.md) provides two learning, two validation, and two held-out cases. Tasks cover exact decimal rounding, normalization, sorting, duplicate items, and strict JSON output. `company.workload.task_prompt()` exposes only the specification and inputs; `grade_output()` separately checks answers, types, array ordering, and extra fields. This is a tiny exploratory suite, not evidence of performance improvement.

## Persistent execution and replay

```bash
.venv/bin/python -m company init
.venv/bin/python -m company smoke
.venv/bin/python -m company run --split learning
.venv/bin/python -m company history
.venv/bin/python -m company status
.venv/bin/python -m company export RUN_ID --out artifacts/replay.json
```

`smoke` and `run` make paid Crusoe inference calls. The other commands only read/write local records. `run --case learn-trim-and-empty` selects one task. The held-out split is deliberately absent from the development CLI. Use `--db PATH` before the command to select another database.

SQLite at `data/company.sqlite3` stores the immutable manifest, active pointer, pinned runs, worker instances, and ordered events. Restarting `init` preserves the active version. Each run creates a fresh Deep Agents instance from its pinned manifest; conversation checkpoints and mid-run resumption are not implemented. The next controller marks an unfinished run interrupted and keeps its evidence. The controller uses a Linux file lock to prevent concurrent writers; read-only CLI reports can inspect an ongoing run.

V0 has one persistent generalist role. Aggregate model-call, tool-call, temporary-worker-count, and wall-time budgets are disabled (`null` in the saved manifest). One level of delegation remains supported. The old 50-step graph ceiling is also removed in practice by using the framework's maximum integer range. Parent and child requests retain provider pacing of one request every two seconds. The default response allowance is 4,096 tokens; individual provider requests retain their timeout and zero automatic retries. Python retains its separate sandbox limits. Usage is still measured across root and children; incomplete usage is flagged.

For an existing database, run `.venv/bin/python -m company unlimit`. This saves and activates an operator settings snapshot, preserves all earlier runs and immutable versions, and records the change separately from evaluated promotions. It refuses to interrupt active work and is idempotent. Restart the viewer after upgrading the code. Existing runs remain pinned to their original settings.

The model receives the task specification and input, never the expected output. Decimal tools provide exact arithmetic; `python_execute` writes and runs code with optional text input files, returning stdout, stderr, and exit status. Each Python invocation gets its own disposable `/work`, standard library, no network, and no repository or credentials. The SDK's own `read_file` separately reads a virtual `/organization/` tree containing the pinned prompt and bound skill/memory files. Each temporary child receives a snapshot in its own graph state; retained specialists receive their own role-scoped tree and return only their messages. Framework filesystem write tools remain disabled. Seed skills and task memory are empty; bound text entries are also included in the saved prompt. NemoClaw/OpenShell deployment is still optional follow-up work.

The replay export contains the saved organization, actual worker tree, model/tool events, objective grade, and usage. The viewer uses these records without model calls. A run marked `completed` can still have `grade.passed: false`.

## Reflection and adoption

```bash
.venv/bin/python -m company reflect
.venv/bin/python -m company reflect --propose-only
.venv/bin/python -m company evaluate PROPOSAL_ID
.venv/bin/python -m company proposals
```

`reflect` requests schema-constrained JSON with at most six completed learning traces, five previous lessons, 48,000 characters of initial context, and 4,096 output tokens per call. It makes one call normally and allows one corrective retry if the response fails controller validation. Rejected response excerpts and validation errors remain visible in the attempt's full record, with token usage summed across both calls. It can return no change, a duplicate, or one typed candidate. Duplicate configurations are compared without display labels and skipped before evaluation. Learning diagnostics name violated properties without exposing expected values; controller-recorded independent checks enter as bounded excerpts. Raw validation and held-out records do not enter reflection.

Supported mutations cover prompt replacement, skill revision, task-memory revision, binding approved tools, and retaining an observed temporary worker as an optional specialist. The compiler supports a generalist plus up to two specialists; these are saved role definitions, not long-lived processes. Arbitrary tool code, mandatory workflow scheduling, and provider/budget changes are not proposal capabilities.

For benchmark proposals, the fixed gate runs both versions freshly on two learning regression cases and two validation cases, alternates branch order, and has no shared model-call or admission-time cap. It requires no per-case regressions and either an additional passing case within a 1.5× token ceiling, or identical outcomes with at least 15% fewer execution tokens. A proven regression stops remaining comparisons. Provider errors, partial usage, and budget exhaustion cannot qualify a candidate. Custom-task proposals instead use the separate LLM reviewer, also without a shared model-call or admission-time cap. Held-out audits use the same unlimited admission policy. Previously saved reports preserve their original policies. Neither policy is a statistical guarantee.

The controller owns grading and compare-and-swap activation on version plus generation. Evaluation runs never change the active version. Outcomes enter a separate reflection-memory table; ordinary workers cannot read it. Explicit revocation preserves the original experiment and activation and appends the restoration. In-flight runs keep their pinned version. Interrupted evaluations are marked inconclusive after restart.

Reflection is explicitly triggered by the CLI or the UI button; it does not run automatically after every task. A future budgeted batch trigger can reflect after several learning runs or recurring failures.

## Frozen final audit

```bash
.venv/bin/python -m company audit PROPOSAL_ID
.venv/bin/python -m company audits
```

`audit` makes paid calls and consumes the existing held-out suite once per project database; it has already been run for this demo. It compares an evaluated candidate with its original baseline, freezes both configurations and the measurement policy before inference, and runs two repetitions of each held-out task per branch. It never promotes a candidate or feeds outcomes to reflection. A failed or interrupted audit remains consumed to prevent tuning through repeated final tests. `audits` only reads saved results.

An optional `python -m company check-regression` command makes paid calls to test a clearly labeled, controller-authored bad candidate. It is not presented as a model-generated proposal. It was unnecessary for the recorded demo because a real proposal already regressed and was rejected.

Explicit Python execution requests now receive up to two corrective continuations if the model returns without a successful Python tool call. Continued non-execution is marked `incomplete`; printed tool JSON never counts as execution. This protocol check does not establish that the implementation or tests are correct. Chat labels returned answers as unverified.
