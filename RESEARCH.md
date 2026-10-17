# Persistent Agent Organizations — research notebook

Updated: 2026-10-17, revision 1. Status: working hypothesis, literature review, and proposed evaluation; no implementation or experiments completed yet.

Companion: [short team proposal](PROPOSAL.md). Update this notebook as we investigate; revise the proposal when findings change the argument.

## Idea we are exploring

Persist an agent swarm's organization across tasks. Between tasks, use reflection on execution traces and outcomes to propose changes to roles and connections. Keep changes that improve subsequent performance. The product metaphor is a personal company of agents that becomes better suited to its owner's recurring work.

The user's central hypothesis is that agents with specialized roles perform better. The research question is which kinds of specialization help, under what conditions, and whether preserving and refining those specializations adds value beyond a strong shared memory system.

No task domain, framework, model, team size, or implementation budget has been selected. The architecture and experiments below record the current discussion; they remain proposals pending implementation and evidence.

## Three claims to keep separate

| Claim | Current evidence | What remains to establish |
| --- | --- | --- |
| Functional specialization improves performance. | Some direct support from role-comparison experiments; expert personas alone have weak support. | Improvement on our workload at comparable cost. More narrowly specified roles are not automatically better. |
| Persisting useful roles and coordination helps across tasks. | A closely related preprint reports benefits from cross-task persistence. | Advantage over a capable planner that can retrieve and reuse equivalent organizational knowledge from global memory. |
| Reflection can improve roles and topology over time. | Prompt/topology optimization studies support searching these configurations. | Whether our trace-based reflection produces changes that transfer to fresh tasks and repay their evaluation cost. |

Working thesis: **A system can learn reusable divisions of labor for recurring work by treating role definitions and coordination rules as versioned, testable configuration.**

## What counts as specialization

A role should define a responsibility, a procedure, relevant context or memory, available tools, an expected output, and a success criterion. A title such as “senior engineer” does not establish a distinct capability.

Illustrative role: an API compatibility reviewer checks changed public interfaces against existing callers and compatibility requirements, then returns concrete breakages and reproduction steps. It is invoked when interfaces change. This is a proposed design example, not a measured result.

Possible mechanisms to test: focused context, complementary checks, fewer duplicated investigations, and reusable procedures. Prompt specialization does not create new model knowledge or guarantee independent reasoning.

## Evidence ledger

All results below are reported by the authors. Scores from different papers are not directly comparable. Source contents were reviewed in this conversation on 2026-10-17.

| ID / source | Relevant observation | Interpretation and limits |
| --- | --- | --- |
| E1 — [AgentGroupChat-V2, §VI-B](https://arxiv.org/html/2506.15451v1) | On 100 MATH problems, five agents with functional roles averaged 53.5% accuracy across tested dialogue depths, versus 31.5% for five generalist agents, using Qwen2.5-72B. Roles included computation, error detection, comprehension, reasoning, and verification. | Direct support for distinct responsibilities in this setup. Small preprint experiment; equal agent count does not establish equal token cost. It does not test persistence or imply an unlimited benefit from finer specialization. |
| E2 — [MASS, Table 6](https://arxiv.org/html/2502.02533v2#A3) | With Gemini 1.5 Pro, mean scores across eight benchmarks were 67.44 for optimized single-agent prompting, 74.56 for optimized multi-agent building blocks, and 77.55 after topology optimization. | Supports optimizing both agents and their arrangement. These are aggregate benchmark scores, not one accuracy rate. The interventions combine prompting and workflow changes; this is not a global-memory comparison or a role-only test. |
| E3 — [MetaGen, §4.5](https://arxiv.org/html/2601.19290#S4.SS5) | HumanEval results: full system 95.1%; without query-conditioned role generation 92.1%; without cross-instance memory 92.7%. Persistence includes verified roles and selection/wiring state. | Closest prior work to our proposal. January 2026 preprint; author-reported results. Removing all organizational persistence is a weaker baseline than a capable shared-memory planner. These modest absolute differences need replication. |
| E4 — [Personas in System Prompts, EMNLP 2024](https://aclanthology.org/2024.findings-emnlp.888/) | Evaluation of 162 personas across four model families and 2,410 factual questions found no general performance improvement from adding personas. | Evidence against treating expert labels as sufficient specialization. Its factual-QA setting does not directly test functional delegation, tools, or reusable workflows. |
| E5 — [Multi-Agent Teams Hold Experts Back, ICML 2026](https://proceedings.mlr.press/v306/pappu26a.html) | In unconstrained, self-organizing teams, collaboration failed to match the expert member's performance; reported losses reached 41.1% on ML benchmarks. Analysis identified compromise between expert and non-expert views as a bottleneck. | Coordination can erase specialist advantages. This studies free interaction rather than every possible structured workflow. Our design should test whether routing and decision authority preserve useful expertise. |
| E6 — [GPTSwarm, ICML 2024](https://proceedings.mlr.press/v235/zhuge24a.html) | Represents language-agent systems as graphs and optimizes node prompts and graph connectivity. | Relevant architectural precedent. An optimizable agent graph is established prior work; this source alone does not validate personalization or superiority to shared memory. |

Research implication: distinguish an implementation opportunity from a claim of research novelty. MetaGen already covers substantial parts of role generation, structural adaptation, and reuse. A plausible product focus is adapting to one user's workload with transparent evidence for every retained organizational change.

## How we differ from MetaGen

Our original mechanism overlaps substantially with MetaGen. It generates and rewrites roles, adjusts connections during execution, caches successful role specifications, and updates role/edge selection preferences after tasks. Its task graph is constructed from a backbone, accumulated roles, and learned scores. Persistence and specialization alone are therefore not differentiators. [MetaGen, §3.3](https://arxiv.org/html/2601.19290#S3.SS3)

Candidate extensions for our prototype:

| Direction | Proposed implementation | What must be demonstrated |
| --- | --- | --- |
| Preserve the organization itself | Version a default graph with stable role identities, continuing responsibilities, project knowledge, and established handoffs; activate relevant parts per task. | Value beyond reconstructing teams from reusable roles and learned preferences. A different serialization format is insufficient. |
| Reflect across multiple tasks | Analyze recurring failures across a batch, propose a bounded change, and compare it with the incumbent on separate validation tasks. | Improvements transfer to fresh work and repay evaluation costs. |
| Adapt to one person's work | Learn from recurring requests, corrections, preferred workflows, and project-specific requirements. | Fewer repeated user corrections at comparable quality and cost. |

These are proposed extensions, not established research novelty. Position the project as building on prior work. The sharper question is: **Does maintaining and deliberately reorganizing a persistent team outperform assembling teams from a reusable role library?** A MetaGen-style comparator would be needed to support that specific claim; beating a fixed team would not suffice.

## Strongest objection: a good global memory could already do this

A shared memory can store procedures, successful role definitions, prior team structures, and routing lessons. A sufficiently capable planner can retrieve those and instantiate the appropriate team. Therefore, there is no inherent information advantage from storing the same knowledge in an explicit graph.

Our proposed advantage is operational: reusable defaults may reduce repeated planning and make useful procedures more consistently applied. The graph must earn its complexity through measured quality, cost, or latency benefits. This is an empirical hypothesis.

Fair comparison: give the memory-based planner the same task history, feedback, tools, and model access, and allow it to create specialists and retrieve organizational lessons. Restricting it to one weak generalist or withholding useful memory would not answer the objection.

## Candidate system

Persistent state: role specifications, conditional activation rules, delegation/review connections, handoff formats, outcome statistics, and a version history. Ordinary shared memory remains available.

Agents can be instantiated from saved configuration when needed; persistence does not require continuously running processes or model-weight updates.

```text
Task → select a team → execute → score outcome and record trace
                                      ↓
                            reflect on observed failures
                                      ↓
                           propose one bounded change
                                      ↓
                     evaluate candidate against current version
                                      ↓
                         retain or discard the change
```

Candidate mutations: revise a procedure or handoff; change a delegation/review connection; split, merge, or retire a role. A hackathon prototype should support only a small subset. Reflection generates hypotheses; outcome evaluation determines whether they are useful. A failure could require better tools or information rather than another role.

Avoid overfitting by using separate development/validation tasks for changes and untouched final tasks for evaluation. Keep an incumbent configuration so unsuccessful changes can be rolled back. Allow simpler teams to win.

## Temporary subagent spawning

Working design direction: allow task-local spawning while reserving lasting organizational edits for reflection between tasks. A role definition is persistent; an agent instance is a worker created to execute a particular task. The topology describes responsibilities and delegation rules without enumerating every runtime instance.

```text
Persistent organization: Planner → Implementer → Reviewer

Within one task:         Implementer
                        ├── Temporary library researcher
                        └── Temporary migration analyst
```

The temporary workers report to the implementer, who remains accountable for the handoff to the reviewer.

- Children share the parent's budget and delegated scope. Set a maximum spawning depth and worker count; exact limits remain open.
- Spawning preserves required handoffs and reviews. A child cannot silently change the permanent organization.
- Temporary roles are recorded in the trace but are not automatically added to the persistent role library.
- Reflection may propose retaining a recurring specialist, with an explicit activation rule. Frequency is evidence of demand, not proof of value; promotion requires a measured benefit.
- All evaluation baselines receive the same spawning capability and limits.

This lets execution adapt to the immediate task while reflection tests which successful improvisations deserve reuse. Recursion itself is not the claimed improvement.

## Proposed experiment

Objective: demonstrate a benefit on a defined workload under controlled budgets. A hackathon evaluation cannot establish universal superiority.

| Configuration | What changes between learning tasks | What the comparison establishes |
| --- | --- | --- |
| A. Memory-driven planner with transient teams | Shared memory can retain procedures, successful role arrangements, and reflection. The planner can instantiate specialists for each task. | C versus A tests the added value over capable global memory. |
| B. Fixed persistent organization | Shared memory grows; the initial role definitions and connections stay fixed. | C versus B tests organizational adaptation. |
| C. Evolving persistent organization | Shared memory grows; reflection can revise roles and connections. Start from the same organization as B. | The proposed system. Its overhead counts toward the budget. |

All three may spawn temporary workers. Match model versions, tools, initial information, feedback rules, spawning limits, and total spending caps. Allow A to reflect into memory; otherwise C could win simply because it received an extra reasoning step. Initial role definitions available to B and C should also be available to A as reference information.

### Learning and evaluation protocol

1. Choose one recurring task family with observable outcomes. Coding changes with hidden acceptance checks are a candidate; research tasks need a consistent rubric. Include recurring failure types without repeating identical tasks.
2. Set aside learning, candidate-validation, and final evaluation tasks before optimization. A possible demo scale is 10–15 learning tasks followed by 30–50 unseen evaluation tasks, subject to budget. These counts are an exploratory starting point, not a statistical-power claim.
3. Run learning tasks in the same order for each system. Provide the same kinds of outcome feedback. C proposes changes from traces and evaluates candidates using only development/validation tasks.
4. Freeze shared memory and persistent configurations after learning. Evaluate each fresh task from that system's frozen snapshot in an isolated environment. Task-local planning and spawning remain available; held-out outcomes cannot update memory, prompts, or topology during this evaluation.
5. Record paired task outcomes and repeat runs where feasible. Report uncertainty on the difference, keeping repeated runs of one task grouped rather than treating them as independent tasks. Preserve failures and unchanged results alongside successes.

Predeclare the budget allocation and success threshold. Include all model calls, tool costs where relevant, planning, temporary agents, reflection, and candidate evaluations. Report both adaptation expense and subsequent execution expense, plus task success, total cost, latency, and cost per successful task. Success means better quality under the same total budget, or equivalent quality at lower total cost; an equivalence tolerance must be chosen in advance.

### Attribute the improvement

- **Rollback:** keep the post-learning memory and knowledge available, but restore the original organization. Replay the same held-out tasks. A loss of performance supports a contribution from organizational changes beyond accumulated knowledge.
- **Role ablation:** compare generalist and functional role instructions with the same graph, agent count, and budget. This tests specialization directly; A versus B alone does not isolate it.
- **Topology ablation:** keep learned role prompts but restore the original connections. Compare against the fully evolved team to estimate the value of rewiring.
- **Prior-work comparison:** if claiming an advantage over MetaGen-style reuse, add a system that constructs teams from cached roles and learned selection preferences. The three primary configurations alone do not establish this advantage.

These checks are proposed experiments, not results. Report exactly which were run. If the sample is small or the uncertainty includes no gain, describe the result as inconclusive.

### Demo and failure criteria

Show one traceable example: recurring compatibility failures → proposed compatibility-review role → retained after validation → improved outcomes on fresh tasks → rollback removes the benefit. This is a target demonstration, not an observed result; the full evaluation must support the story.

Failure signals: gains disappear when compute is matched; a memory-based planner matches the adaptive team; role changes do not transfer; or coordination and reflection costs exceed their benefits.

## Next questions, in priority order

| Question | Why it matters | Status |
| --- | --- | --- |
| Which recurring workload and outcome measure? | Determines roles, feedback, and a credible demonstration. | Asked; open. |
| How much hackathon time, API budget, and existing infrastructure? | Determines feasible adaptation and evaluation scope. | Open. |
| What is the strongest shared-memory baseline we can implement? | Determines whether the experiment answers the central objection. | Open. |
| Which persistent fields and mutations fit the prototype? | Keeps implementation and attribution manageable. | Default organization with role definitions and connections proposed; exact schema open. |
| What spawning limits should apply? | Allows temporary delegation within a predictable cost envelope. | Shared parent budget and limited depth/count proposed; values open. |
| What will trigger a change, and what independently scores it? | Prevents persuasive reflections from substituting for improvement. | Between-task reflection and separate validation proposed; evaluator open. |
| What is our practical differentiation from MetaGen and MASS? | Shapes an honest team proposal and demo story. | Persistent organization, batch retrospectives, and personal workload adaptation are candidate extensions. |
| What result would justify implementation beyond the demo? | Prevents moving the success criterion after seeing results. | Metric, minimum gain, equivalence tolerance, and total budget open. |

## Update log

- 2026-10-17, revision 2: Implemented a prototype with three mutation families (skills, script tools, roles/topology), a replaceable reflection-decision policy, structured LLM proposal generation, paired candidate validation, versioned persistence, and rollback. See [design](docs/DESIGN.md) and [runtime setup](README.md). Core lifecycle tests and an explicitly simulated offline demo exercise the machinery; no comparative performance experiment has been run. Deep Agents SDK and live NemoClaw/provider integration still require verification in an environment with the dependencies installed.
- 2026-10-17: Consolidated the original personal-agent-company idea, specialization hypothesis, global-memory objection, supporting studies, counterevidence, and proposed experiments. Created proposal v0. No implementation or empirical validation has been completed.
- 2026-10-17, revision 1: Added the concrete MetaGen overlap and candidate distinctions; separated persistent roles from temporary worker instances; documented bounded spawning and evidence-based promotion; expanded the experiment with strong baselines, frozen held-out evaluation, full cost accounting, rollback, and component ablations. Revised proposal to v1. All design choices remain proposals and no performance gain has been measured.

For subsequent findings, record the source or experiment, the observed result, limitations, which claim it affects, and whether the proposal should change.

## Updated hypothesis: choose what kind of change earns its cost

The reflection controller can propose a skill procedure, a deterministic script exposed as a tool, or a role/topology change. These are distinct interventions. Memory stores knowledge; skills make procedures reusable; tools execute procedures; topology determines assignments and handoffs. A sufficiently capable memory-and-skills controller can represent and reconstruct all of these, so representational power is not our differentiation.

The testable hypothesis is that retaining an evaluated execution configuration improves measured outcomes or reduces repeated planning cost on a user's workload. The evaluation may conclude that skills and scripts provide all the useful gains and topology adds none. That result should simplify the product rather than be hidden.

For fair comparisons, the memory-and-skills baseline must also be able to generate scripts, invoke the same tools, retain successful configurations in memory, reflect, and spawn specialists. Run skill-only, tool-only, and topology-only ablations. A full-version rollback in the current CLI restores skills/tools as well as roles/edges; it therefore cannot isolate topology. A topology attribution experiment must explicitly construct an organization retaining learned skills and tools while restoring only the initial roles/connections, including compatible assignments.

The current retention gate is a practical validation heuristic: no per-case regression, candidate acceptance checks, then sufficient quality improvement or measured cost reduction. It is not statistical evidence of improvement. The example arithmetic suite and synthetic demo are plumbing checks. Task-family selection, capable baselines, final held-out tasks, confidence intervals, and total adaptation-cost analysis remain research work.

Implementation choices now concrete: acyclic handoff/delegation graphs; shared task limits of 30 model calls, 8 spawns, depth 2, and 30 script calls by default; separately bounded reflection; explicit script execution mode; latest outcome/trace evidence; an LLM-based decision policy replaceable through a Python protocol. Conditional activation and learned decision policies are future work.
