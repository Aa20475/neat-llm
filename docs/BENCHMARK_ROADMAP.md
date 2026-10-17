# Step 5: benchmark campaigns and visible progression

Deferred by the user on 2026-10-17: get the runtime, reflection, and visualizer working first. Do not expand the task suite as part of Step 3.

Use a fixed campaign of related tasks with recurring skills and failure modes. Freeze learning, candidate-validation, and final held-out splits before the campaign begins. Repetition should let the organization test reusable procedures or useful specialist roles; complexity alone is not a reason to add workers.

At each checkpoint, save the organization version, run the predeclared comparison, and show:

- Task acceptance and execution cost, together with cumulative reflection/evaluation expense.
- Actual configuration changes: prompts, skills, memory, tools, retained roles, and delegation rules.
- Which temporary-worker patterns led to a proposal, and whether the proposal earned adoption.
- Rejected, duplicate, inconclusive, and no-change outcomes alongside retained changes.

Keep a fixed baseline and use repeated paired measurements where variability matters. Freeze the final versions and disable learning for unseen-task comparisons. Never use final held-out results to propose the next change and still call those tasks unseen.

Group history by campaign, checkpoint, proposal comparison, and task ID. Each execution remains a distinct run, linked to its parent comparison. Add server pagination and per-task drill-down instead of loading every run into one list. Archive raw traces under an explicit retention policy while retaining run IDs, grades, usage, versions, and evidence links. Reflection retrieves bounded evidence and summaries; it does not ingest the entire growing history.

A compelling demo may show a generalist gaining a skill while keeping the same topology, or a temporary pattern becoming an evaluated specialist. Show the measured outcome; do not script permanent-role growth to make the graph look more sophisticated.

Deployment polish is a separate optional follow-up. A larger benchmark or campaign UI is not required to finish the current working prototype.
