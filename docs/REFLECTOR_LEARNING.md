# Learning from completed solutions

The reflector uses the `full-trace-learning-v3` policy. A successful task can teach a reusable method, a repaired bug can teach a prevention rule, and a worker review can teach an additional test case. A final passing test run does not erase earlier failures.

The previous prompt emphasized failures and recurring cost. In the saved Git/scheduler reflection, the model returned `no_change` because both final results were successful. It received filenames and the final four Python events, so most development failures, implementation details, and review findings were absent. The prompt and evidence selection now address both causes.

| What was learned | Proposed component | Expected content |
| --- | --- | --- |
| A reusable implementation or testing method | `revise_skill` | When to use it, algorithm or representation, invariants, concrete edge cases, and verification steps. Short pseudocode is allowed. |
| How a particular project was implemented | `update_task_memory` | Project scope, API/files, design decisions, observed pitfalls, and verification limits. Inspect the current workspace before relying on saved file names. |
| A general workflow or delegation improvement | `replace_prompt` | A cross-task behavior supported by evidence, preserving useful existing instructions. |
| A worker's repeatable contribution | `retain_role` | A bounded specialist role grounded in an observed temporary worker. |

These are proposed changes to the saved organization. They become available to execution agents only after promotion. The separate reflection memory stores past improvement attempts and their outcomes; a prior `no_change` is fallible history, not a veto on later learning.

The reflector receives only eligible, completed learning runs from the active version, with deleted/excluded runs removed. Private chat, evaluation runs, and held-out records remain excluded. Each selected run includes:

- Every persisted event in sequence order, with its original timestamp, kind, call IDs, and complete stored payload: model outputs, tool arguments/results, errors, repairs, delegation, worker reviews, merges, and independent checks.
- Worker attribution on every event: ID, readable label (for example `Generalist` or `Worker 1 · general-purpose`), role, parent ID, and temporary/saved status. Events without a worker are labeled `Controller`; unrecognized IDs remain explicitly unknown.
- Every worker record, including its full assignment and lifecycle. There is no eight-worker cutoff.
- The full stored task and final answer.

Supplementary navigation summaries remain bounded; they do not replace the full trace:

- Up to two Python implementation excerpts and one test excerpt, with truncation marked. Changed files are prioritized; worker-review tests are preferred.
- Test names from up to four test files, explicitly treated as intended coverage rather than proof.
- Up to three failed tool results, preserving early failures alongside a later failure.
- Up to three successful edits, including before/after excerpts. Their chronological position does not establish that they fixed a specific bug.
- One worker's final report, labeled as a worker claim rather than an independent controller check.
- Recent Python events and independent-check excerpts. All such events are also included in full in `event_trace`.

Retrieval selects the latest six eligible learning runs and five reflection lessons. All selected runs and lessons are sent; the former 48,000-character cutoff and size-based run dropping have been removed. No extra model call is used for evidence preparation. The reflection record reports event/worker counts and input character count. Larger histories cost more to send. If the provider rejects the context size, the attempt records a visible failure without silently retrying with missing events or activating anything.

“Full trace” means all **persisted** events. The runtime already clips individual strings at 12,000 characters when recording them, and tools can bound their output. Reflection cannot reconstruct text that was never stored. `trace_coverage` discloses this distinction; the reflector adds no further event-payload truncation. Credentials are still redacted before sending. A full trace does not include every project file or unrecorded model input.

The prompt distinguishes observed bugs, reviewer-added coverage, and suspected gaps. Missing excerpts do not prove missing tests. A test edit must be checked against the requirements; a passing rerun alone does not establish that an assertion was correctly changed. Skills capture methods instead of exact benchmark answers or entire task solutions. Generic instructions such as “write more tests” are discouraged.

Each new reflection record includes its policy name, prompt digest, retrieval counts, and input character count. `no_change` remains valid when useful knowledge is already captured, the evidence is insufficient or contradictory, or there is no transferable method or scoped project fact. Success alone is not sufficient justification.

Proposal generation and promotion are separate. The existing paired evaluation and subjective user-task judge still decide whether a candidate becomes active. A knowledge-capture proposal can be rejected or tied; this prompt change does not establish improved performance on unseen tasks.

Regression coverage checks complete event preservation, worker attribution beyond eight workers, full assignments/task/output, requests larger than 48,000 characters, credential redaction, learning/evaluation isolation, and visible provider failures without a truncated fallback. The earlier excerpt-based policy also produced a reusable skill in a live synthetic LRU-cache check; that result does not establish the effectiveness of the full-trace policy.
