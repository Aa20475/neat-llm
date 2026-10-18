# Learning from completed solutions

The reflector uses the `solution-learning-v2` policy. A successful task can teach a reusable method, a repaired bug can teach a prevention rule, and a worker review can teach an additional test case. A final passing test run does not erase earlier failures.

The previous prompt emphasized failures and recurring cost. In the saved Git/scheduler reflection, the model returned `no_change` because both final results were successful. It received filenames and the final four Python events, so most development failures, implementation details, and review findings were absent. The prompt and evidence selection now address both causes.

| What was learned | Proposed component | Expected content |
| --- | --- | --- |
| A reusable implementation or testing method | `revise_skill` | When to use it, algorithm or representation, invariants, concrete edge cases, and verification steps. Short pseudocode is allowed. |
| How a particular project was implemented | `update_task_memory` | Project scope, API/files, design decisions, observed pitfalls, and verification limits. Inspect the current workspace before relying on saved file names. |
| A general workflow or delegation improvement | `replace_prompt` | A cross-task behavior supported by evidence, preserving useful existing instructions. |
| A worker's repeatable contribution | `retain_role` | A bounded specialist role grounded in an observed temporary worker. |

These are proposed changes to the saved organization. They become available to execution agents only after promotion. The separate reflection memory stores past improvement attempts and their outcomes; a prior `no_change` is fallible history, not a veto on later learning.

The reflector receives only eligible, completed learning runs from the active version, with deleted/excluded runs removed. Private chat, evaluation runs, and held-out records remain excluded. It now receives bounded evidence from each eligible run:

- Up to two Python implementation excerpts and one test excerpt, with truncation marked. Changed files are prioritized; worker-review tests are preferred.
- Test names from up to four test files, explicitly treated as intended coverage rather than proof.
- Up to three failed tool results, preserving early failures alongside a later failure.
- Up to three successful edits, including before/after excerpts. Their chronological position does not establish that they fixed a specific bug.
- One worker's final report, labeled as a worker claim rather than an independent controller check.
- The existing recent Python events, independent-check excerpts, task, bounded final answer, and worker assignments.

Retrieval considers up to six learning runs and five reflection lessons. If the 48,000-character context allowance would be exceeded, older runs are omitted before older lessons; the most recent solution remains. Counts and omissions are disclosed to the reflector. No extra model call is used for evidence preparation. This input-selection allowance is separate from response token limits, which remain uncapped by the app.

The prompt distinguishes observed bugs, reviewer-added coverage, and suspected gaps. Missing excerpts do not prove missing tests. A test edit must be checked against the requirements; a passing rerun alone does not establish that an assertion was correctly changed. Skills capture methods instead of exact benchmark answers or entire task solutions. Generic instructions such as “write more tests” are discouraged.

Each new reflection record includes its policy name, prompt digest, retrieval counts, and input character count. `no_change` remains valid when useful knowledge is already captured, the evidence is insufficient or contradictory, or there is no transferable method or scoped project fact. Success alone is not sufficient justification.

Proposal generation and promotion are separate. The existing paired evaluation and subjective user-task judge still decide whether a candidate becomes active. A knowledge-capture proposal can be rejected or tied; this prompt change does not establish improved performance on unseen tasks.

Verification: 169 regression tests passed. A live Crusoe call on a newly authored synthetic LRU-cache fixture proposed a reusable skill after a successful implementation, including algorithm steps, invariants, edge cases, and verification. It used one model call and did not activate the candidate. The check used a temporary database and no saved user task records.
