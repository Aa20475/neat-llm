# Step 3: working lifecycle, inconclusive improvement

Implemented and tested on 2026-10-17. **The viewer and reflection lifecycle work. v0 remains active; no reliable improvement is claimed.**

## Live experiments

All calls used the configured Crusoe Nemotron model. Tests used fresh model runs, the unchanged strict grader, and the declared `paired-development-v1` gate. Held-out tasks were not run.

| Attempt | Observation | Outcome |
| --- | --- | --- |
| First reflection | Generated a prompt rewrite. It failed a learning case the incumbent passed. | Rejected after two pairs; remaining paid comparisons skipped. |
| Second reflection | Retrieved the rejection record but generated the same prompt again. This comparison scored 1/4 for v0 and 2/4 for the candidate, with about 13% more execution tokens. | Initially activated by the single-comparison gate; then explicitly revoked when the equivalent earlier regression was identified. |
| Third reflection | Retrieved three prior outcome records and again proposed the equivalent configuration. | Duplicate detected while ignoring display labels; zero additional evaluation calls. |

The second attempt's differing label had initially hidden that its behavioral configuration was identical to the first. Duplicate detection now compares manifests without the label before registering another proposal. The original rejection, activation, conflicting evidence, revocation, and later skipped duplicate are all preserved. Do not present the second table as established learning or transfer.

The active organization is v0 at generation 2. Generation 1 recorded adoption; generation 2 recorded restoration. The seed and both candidate manifests remain immutable and inspectable. Restart was checked against the final active digest and generation.

## Evidence and usage

| Phase | Calls | Input tokens | Output tokens |
| --- | ---: | ---: | ---: |
| Proposal generation, including the duplicate | 3 | 11,183 | 1,397 |
| Paired evaluation, including the rejected attempt | 12 | 21,178 | 1,341 |
| Total adaptation | 15 | 32,361 | 2,738 |

These are reported tokens, not dollar estimates. The second comparison's incumbent consumed 7,068 total tokens and its candidate 7,977. Neither execution savings nor a cost break-even is established. The duplicate guard avoided another evaluation; it did not avoid the proposal call itself.

`artifacts/step3-report.json` contains the persisted attempt records, activation history, phase totals, and final active version. All task outputs and traces remain in `data/company.sqlite3`. The visualizer links each paired score to its exact run and shows the candidate change, not a reconstructed explanation.

## Verification

- 32 local tests pass, including candidate isolation, stale-generation rejection, in-flight version pinning, negative/positive evaluation gates, provider-failure handling, duplicate suppression, revocation, bounded memory retrieval, role-scoped files, and recovery.
- Chrome exercised worker selection, event inspection, reflection and version tabs, paired-result navigation, and a 390-pixel mobile layout. No JavaScript errors were observed.
- The page and JSON endpoints return successful responses. The server reads SQLite in read-only mode, accepts no mutation requests, and exposes only its UI assets and selected record endpoints.
- A retained-specialist configuration compiles and its file projection is tested. No specialist has earned live adoption in these experiments.

## Remaining scope

Permanent optional specialist definitions are supported; mandatory review/workflow scheduling and generated executable tools are not. There is no hard dollar limit, forced process supervisor, automatic continuous reflection scheduler, or NemoClaw deployment. Invocation and usage budgets are bounded and explicit. Before claiming statistical improvement, use a predeclared repeated-evaluation policy and a final frozen unseen-task comparison.

The next product demonstration should use the planned [Step 5 benchmark campaign](BENCHMARK_ROADMAP.md), with related tasks and checkpoint comparisons. The current priority is a working, inspectable lifecycle rather than expanding the dataset.
