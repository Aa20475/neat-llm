NEAT-LLM elevator pitch

**Ten-second version:**

> NEAT-LLM versions an agent team's prompts, skills, tools, and structure, compares proposed improvements, and saves qualifying changes for future tasks.

**Thirty-second version:**

> NEAT-LLM gives agent teams a way to improve how they work. You start with one generalist that can recruit temporary helpers. We save the team's instructions, tools, memory, and structure, then use a separate reflection pass to propose reusable changes. Each candidate is compared with the current setup before it can become active. Future tasks load that saved version. Built with Deep Agents and Crusoe inference, the prototype makes proposed evolution visible, testable, and reversible.

**One-minute version:**

> When an agent finishes a task, useful lessons about testing, tools, and delegation often disappear. NEAT-LLM gives those lessons somewhere to go.
>
> We start with one generalist on Crusoe using GLM-5.3. It can write and execute code, keep project files across tasks, and delegate to temporary workers. We record what actually happened.
>
> A separate reflection pass reviews completed work and its own history of previous attempts. It can propose a better prompt, a reusable skill, a memory update, different tool bindings, or a saved specialist role. We then run the current and proposed versions from the same starting point and compare their results before activating a change.
>
> For custom tasks, that comparison currently uses a blinded LLM judge. We have also implemented a deterministic benchmark gate. Broad improvement is still something we need to prove. What works today is the machinery for proposing, comparing, remembering, and deploying changes to how an agent team operates.

**If someone asks what is novel:** “We persist and evaluate the team's operating configuration: its procedures, role-specific knowledge, tool access, and delegation structure. A useful temporary worker can become a reusable role if a proposal qualifies.”

**If someone asks where the intelligence lives:** “GLM-5.3 on Crusoe currently powers execution, reflection, and judging. Different contexts and prompts give those calls different responsibilities. Python code and SQL control which proposals are allowed and which version becomes active.”

**If the demo returns no change:** “The reflector found no justified change in this evidence. That outcome is saved too, so we can inspect its reasoning and avoid treating a larger team as an improvement by itself.”

**Delivery note:** Use the thirty-second version to open. Then show one real tool execution, one reflection decision, and the active saved version. Describe a promotion only when the UI actually records one. Model details, prompting, evaluation limits, and Q&A are in [PITCH_CHEATSHEET.md](PITCH_CHEATSHEET.md).
