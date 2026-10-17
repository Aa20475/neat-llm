# One-minute demo and visualization plan

Status: staged implementation, 2026-10-17. Persistent execution, a local graphical viewer, reflection memory, proposals, paired evaluation, activation, and revocation are implemented. See [Step 3 results](STEP3_RESULTS.md): real experiments rejected a regression, revoked an inconsistent adoption, and skipped a repeated candidate. The [frozen audit](STEP4_RESULTS.md) completed with 0/4 executions passing for both branches across two distinct tasks; improvement remains unproven. Chat with the active team and manual reflection triggering are available in the UI. The larger related-task campaign is deferred to [Step 5](BENCHMARK_ROADMAP.md).

## What the demonstration should communicate

Show a generalist agent learning a reusable way of working: it starts with temporary delegation, observes a recurring problem, proposes a change, tests it, and retains only a qualifying version. The visible improvement may be a skill, prompt, memory, tool, or conditional specialist. Do not force a more elaborate team if another change works better.

The one-hour workload is [order normalization](../fixtures/orders/spec.md), with exact decimal, sorting, and JSON checks. A generalist might repeatedly mishandle rounding or formatting; reflection could propose a procedure or a specialist check. This is a target scenario to test, not an observed result. API compatibility tasks can follow after the first demo.

## What NemoClaw provides

| Capability | Current documented availability | Use in our demo |
| --- | --- | --- |
| Sandbox monitoring and logs | OpenShell provides terminal monitoring and real-time sandbox logs | Diagnose execution and show infrastructure operating |
| Managed Deep Agents interface | Deep Agents Code is a terminal runtime; `dashboard-url` is not applicable | Show agent interaction in the terminal |
| Detailed execution traces | Opt-in trace export through a host-operated collector to an external backend | Optional debugging; requires setup beyond the default runtime |
| Persistent organization versions and reflection decisions | Our own application data and proposed UI | Show the actual mechanism built by our team |

The terminal/log capabilities are documented in [OpenShell logging](https://docs.nvidia.com/openshell/latest/observability/accessing-logs). The absence of a managed Deep Agents dashboard is explicit in [NemoClaw commands](https://docs.nvidia.com/nemoclaw/user-guide/deepagents/reference/commands). [Deep Agents trace export](https://docs.nvidia.com/nemoclaw/latest/user-guide/deepagents/monitoring/understand-deepagents-trace-export) is off by default and forwards to a separately operated collector/backend; it is not a bundled topology viewer. A custom SDK worker needs its own instrumentation adapter.

For our application, propose a small read-only replay view over stored versions and run events. It can show the saved organization and the actual task's temporary workers separately, the proposed configuration diff, the evaluation result, and the active-version pointer. Read these from the same records that drive execution. Provide a CLI report as the minimum implementation. Keep a richer viewer optional and cap the implementation effort until the lifecycle and measurements work.

The UI runs with `python -m company.viewer` at `http://127.0.0.1:8765`. It renders recorded worker trees, timelines, saved configurations, proposal diffs, paired results linked to their runs, reflection memory, and activation history without inference while browsing. Chat messages and the Run reflection button explicitly start bounded inference. Versions also shows the frozen held-out audit. CLI `history`, `show RUN_ID`, and `export RUN_ID` remain available. Usage is in the [README](../README.md).

## Video storyboard

Use recorded real runs, edited to fit one minute. Mark time-lapses or replay views clearly; retain original run IDs and reports. The exact change and scores must come from the experiment.

| Time | Show | Point to communicate |
| --- | --- | --- |
| 0–10 seconds | One task, v0 generalist, and temporary children if used | The initial agent chooses its own delegation |
| 10–20 seconds | A checked failure or repeated expensive operation | There is concrete evidence for an improvement attempt |
| 20–35 seconds | One proposal and its affected skill/tool/prompt/memory/role | Reflection proposes a specific, inspectable change |
| 35–45 seconds | Paired validation and retain/reject decision | The controller uses measured checks to choose the active version |
| 45–55 seconds | Frozen before/after results on unseen tasks, including adaptation cost | Show transfer and cost honestly; report no gain if that is the result |
| 55–60 seconds | Reloaded active version and a brief contribution statement | The learned configuration persists; identify what the team built |

The longer live demonstration can add rejection of a bad candidate, reflection-memory retrieval, and rollback. If performance gains are inconclusive, distinguish the working lifecycle from the unproven performance claim. The supplied event guide excludes projects where a dashboard is the main feature; the viewer should explain the learning mechanism and evidence.

## Submission checklist

These requirements come from the participant instructions supplied by the user. None is marked verified by this document.

- [ ] Public repository opens for a signed-out viewer.
- [ ] Approximately one-minute video plays through an accessible demo link.
- [ ] Video clearly identifies features, code, and functionality built during the hackathon and credits upstream components.
- [ ] All team members appear on the submission page.
- [ ] Repository link, demo link, and required project information are entered in the [submission form](https://cerebralvalley.ai/e/crusoe-recursive-agents-hackathon/hackathon/submit).

No submission, publication, or account changes have been performed.
