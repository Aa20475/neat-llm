# Step 4: frozen audit and persistent control state

Recorded on 2026-10-17. Audit `18fafa37b078489f8af5ab528db147f7` completed on Crusoe. Neither version passed the held-out tasks. This is evidence that the comparison works, not that reflection improved performance.

The active version was still v0 after Step 3 revoked an inconsistent promotion. We therefore selected the already evaluated, revoked candidate-2 for a descriptive audit against its original v0 baseline. The candidate was explicitly labeled revoked before any held-out execution. The audit does not promote versions or write reflection memory.

| Frozen branch | Exact matches | Execution tokens |
| --- | --- | --- |
| v0 (`2e05ac3e`) | 0 / 4 | 7,185 |
| candidate-2 (`0118fc67`, revoked) | 0 / 4 | 8,133 |

There were **two distinct tasks**, each run twice on each branch: eight fresh executions total. Repetition is not additional task coverage. Branch order alternated for each task across repetitions. Both branches used identical provider settings, runtime packages, tool code, and budgets. No task-quality result stopped the comparison early.

The immutable SQL plan records exact configuration hashes, behavior hashes, component changes, suite and evaluator digests, candidate status, repetition policy, active pointer, prior activation history, and pre-audit adaptation usage. The fixed audit cap was 16 model calls with a 240-second admission deadline. Actual use was eight calls, 14,276 input tokens, 1,042 output tokens, and approximately 27.4 seconds. These are provider-reported tokens, not a dollar billing total.

Before the freeze, reflection had used 12,580 tokens in three calls; development comparisons had used 22,519 tokens in 12 calls. Their combined adaptation overhead was 35,099 tokens, reported separately from the 15,318-token final audit. Later chat and reflection actions are separate records and do not change this historical freeze.

Reopening SQLite verified that v0 remained active at generation 2, the audit plan persisted exactly, and reflection memory was unchanged. The real earlier activation and revocation remain in history as generation 1 and generation 2. No candidate was reactivated to stage this check. Automated tests also exercise revocation, stale-generation rejection, restart recovery, and frozen-plan immutability.

Held-out runs have their own split and remain excluded from reflection evidence. This suite is now consumed: the controller refuses another final audit on it, including after an interrupted audit. Further development must use learning/validation tasks; a new final transfer claim needs fresh held-out tasks. The larger benchmark campaign remains Step 5.

Open **Versions → Frozen held-out audit** for paired scores, component changes, costs, persistence checks, and links to all eight run traces. Read the complete record with `python -m company audits`. The local export is `artifacts/step4-report.json`.
