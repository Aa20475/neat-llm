# Plan to reduce reflection and evaluation cost

Status: proposed, 2026-10-17. Companion: [architecture and lifecycle](DESIGN.md).

Implemented in Step 3: phase-specific usage, one proposal call per cycle, six-trace/five-lesson retrieval bounds, a 48,000-character reflection context cap, a shared 24-call evaluation budget, deterministic structural checks, early rejection, and behavioral duplicate detection before evaluation. Three live reflection attempts consumed 12,580 tokens; their comparisons consumed 22,519 tokens. The third duplicate incurred a proposal call but no evaluation. Dollar admission control, automatic batching, exact cache reuse, and model selection remain planned. See [results](STEP3_RESULTS.md).

The prototype may incur substantial reflection overhead while we establish that the learning loop works. Measure that overhead from the first run, keep it within an explicit budget, and optimize using the recorded results. Advanced experiment selection is not required for the first prototype. Lower cost must not become an excuse to activate an untested proposal.

V0 is one capable generalist that spawns temporary subagents as needed. Improvements should reuse useful work the generalist already performs. A permanent specialist means a saved role definition; it is invoked only when relevant. Keeping the single-generalist layout is a valid outcome.

## 1. Account for the entire learning loop

Record costs by experiment, organization version, candidate, task, and phase:

| Phase | Include |
| --- | --- |
| Normal execution | Generalist, children, ordinary checks, model retries, context handling, tool execution |
| Reflection | Evidence preparation requiring model calls, memory summarization/retrieval services if billed, proposal generation and repairs |
| Candidate evaluation | Both incumbent and candidate executions, component tests, graders, repetitions, failed attempts |
| Milestone/final measurement | Broader regression checks and frozen unseen-task comparison |

Capture tokens, calls, latency, provider-reported usage, and dollar estimates with the pricing configuration. Keep unresolved reservations visible. Distinguish billed inference from local compute time; local tests are cheaper than agent reruns but still consume resources. Any extra runtime cost of learned instructions, memory, tools, or specialists belongs in normal execution.

The report should show:

- Total task cost, reflection cost, evaluation cost, and final-measurement cost separately.
- Adaptation overhead share: `(reflection + candidate evaluation) / (normal execution + reflection + candidate evaluation)`.
- Cost per evaluated candidate and per retained change, including failed proposals in the experiment total.
- Task success, cost per successful task, and execution latency before and after learning.
- Whether retained changes recover their adaptation expense over the expected workload.

Where quality is comparable, an illustrative break-even calculation is:

```text
adaptation cost = reflection + candidate evaluation, including discarded attempts
saving per future task = incumbent execution cost - retained-version execution cost
break-even task count = ceil(adaptation cost / saving per future task)
```

Only compute this when the measured saving is positive and the workload is representative. For example, $0.60 of adaptation with a measured $0.03 saving per comparable task needs 20 future tasks to recover its cost. These numbers illustrate the calculation; they are not results. Higher quality at higher cost can still be worthwhile, but requires a declared quality/budget objective rather than a cost-saving claim. Report final-measurement expense separately and include it in the full experiment total.

## 2. Establish controls before optimizing

Set explicit experiment, adaptation, per-proposal, and per-evaluation ceilings before live runs. Reserve a portion of the available balance for the final comparison and demo. Choose allocations after the initial call-cost measurement; no specific percentage is assumed to be optimal.

Every nested call and retry uses the same budget ledger. If the required comparison is unaffordable, mark the proposal `deferred_budget`, keep the current version active, and continue normal work within its separate remaining allocation. A deferred proposal is not a failed experiment. Do not borrow the reserved final-evaluation budget silently.

For the initial prototype, one proposal and a fixed small paired suite per reflection cycle are sufficient. Configure the trigger explicitly; after-every-run reflection can be used to demonstrate the lifecycle, while batched reflection is the intended steady-state option. No large benchmark is required after every task.

## 3. Optimize in this order

| Stage | Change | How to assess it |
| --- | --- | --- |
| P0: first prototype | Cost ledger, finite call limits, one candidate per cycle, separate reflection memory, fixed small validation suite | Every charged call maps to a phase; reports include rejected attempts; budget exhaustion leaves current version active |
| P1: first savings | Batch reflection, use deterministic event triggers, retrieve bounded evidence, avoid duplicate proposals | Lower adaptation cost per learning task without an observed loss of final-task quality |
| P2: reduce evaluations | Local component checks first, targeted controller-selected cases plus required regression cases, stop a comparison when a hard rejection is established | Lower spend per rejected candidate; activation still requires every prescribed check |
| P3: reuse measured work | Cache eligible incumbent results and component-test results with strict configuration keys | Cache hits save calls; changed inputs/configuration invalidate reuse; uncertainty remains explicit |
| P4: tune proposal generation | Compare smaller proposal models, context budgets, and trigger frequencies | Compare total cost per useful retained change and frozen task outcomes, not just proposal token cost |

P0 is required for a credible demo. Start P1 when the lifecycle works. Implement P2–P4 only when measurements identify the relevant cost source; do not build a second complex optimizer before observing the first one.

### P1: spend reflection calls on recurring evidence

Extract outcome codes, costs, child roles, repeated operations, and handoff failures directly from existing traces. This does not need a new model call after every task. A fixed trigger can run after a configured batch or repeated checked failures. It can also consider recurring successful delegation worth retaining. Frequency identifies demand; it does not establish benefit.

Retrieve a bounded summary and a few relevant examples instead of replaying the complete history into the reflector. Include relevant prior proposals and their measured results from reflection memory. Keep original records available for inspection. Charge any model-based consolidation to reflection and perform it periodically.

Skip an equivalent rejected proposal under unchanged conditions. Reconsider it if the task slice, implementation, evidence, or runtime has materially changed. Avoid converting one failed experiment into a permanent prohibition. Prefer small, independently testable changes when evidence is weak, and allow `no_change` without further proposal-generation attempts.

### P2: use an evaluation funnel

Reject malformed bindings, impossible routes, broken prompt templates, and failing tool unit checks before agent reruns. These tests assess validity, not whether task performance improves.

Use a predeclared small validation slice and fixed regression cases appropriate to the change. A conditional specialist can first be assessed on its target slice plus routing checks on other tasks; broad changes to the generalist prompt require broader coverage. The controller chooses coverage using the configured policy. The reflector cannot select only favorable examples.

Stop on a hard rejection, such as a required regression case failing. A candidate that looks promising on the first case must still finish all required checks. If uncertainty would require extra repetitions, run them only within the declared evaluation plan and budget; otherwise return `inconclusive`. More adaptive statistical stopping rules can be added later with an appropriate analysis plan.

### P3: reuse valid measurements without inventing comparisons

Cache incumbent outcomes only when the full relevant execution identity matches: organization and memory revisions, task/fixture contents, initial filesystem and tool state, model configuration, runtime build, tool implementations, policy, budgets, and scorer. Store outputs, checks, usage, timing, and measurement date. External state or upstream model drift may invalidate a cache even when a local ID is unchanged.

A cached stochastic result is one historical sample, not a guarantee that another run would match. Refresh controls where needed and use fresh pairs when a decision is sensitive to noise. Never compare a candidate on today's task with an incumbent result from a merely similar task. Keep original measurement costs in the experiment ledger and report incremental savings separately.

Reusing a validated tool test or an unchanged incumbent result can avoid calls. Reusing an upstream workflow fragment is only a component check unless the candidate's dependencies and execution effects are equivalent; it cannot silently stand in for end-to-end evaluation. Cache reuse must respect task partitions and never expose final held-out answers to learning.

### P4: optimize for useful learning

A smaller model may generate cheaper but less useful proposals that require more evaluation. Compare complete adaptation expense and retained-version quality under matched total budgets. Keep evaluator definitions and final task partitions fixed during each experiment. Do not change the task execution model at the same time as the proposal model when trying to measure the latter's effect.

Prioritize recurring problems whose potential benefit could repay testing within the expected task volume. Treat estimates as search priorities, not measured gains. Use reflection memory to identify unproductive mutation families or redundant roles on the current workload, while retaining a bounded opportunity to revisit them with new evidence.

## 4. Review checkpoints

After the first complete learning cycle, report where adaptation spend went. After several cycles, select the largest avoidable cost and implement one optimization. Compare against the recorded policy on a matched learning workload before claiming savings. Changing batching, memory access, or proposal generation is itself an experiment configuration change and must be logged.

Freeze the execution configuration and disable reflection for the final unseen-task evaluation. Preserve reflection history, including rejected and inconclusive attempts, but do not feed final results back into either memory store while that set is still a held-out benchmark.

The target is better work within an acceptable total budget. If improvements do not transfer or do not repay their cost at the expected task volume, reduce reflection frequency, narrow the search space, or keep the generalist baseline. A more complicated organization is not a required outcome.
