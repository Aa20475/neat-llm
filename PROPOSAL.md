# A personal agent company that improves its organization

Working proposal v2 — 2026-10-17. [Research and evidence tracker](RESEARCH.md). [Implementation design](docs/DESIGN.md).

We propose a personal agent company that improves how it executes recurring work. Between tasks, reflection can update a skill, turn a repeated procedure into a script tool, or change roles and handoffs. Each proposal is tested against the current organization before adoption. During tasks, agents can spawn temporary specialists within a shared budget.

Good memory and skills can encode the same knowledge. Our hypothesis concerns execution: does explicitly testing and retaining procedures, tools, and coordination rules reduce repeated mistakes or planning cost? For example, arithmetic errors may call for a tested tool, while missed compatibility checks may call for a review handoff. More roles are not inherently better.

This builds on existing research. [MetaGen](https://arxiv.org/html/2601.19290#S3.SS3) already evolves roles and connections and retains state across tasks. Our candidate extension is a user-specific reflection loop that chooses among several kinds of change and retains only validated candidates. Persistence and specialization alone are not a novelty claim.

For the hackathon, choose one task family with objective checks. Compare a capable memory-and-skills planner, a fixed organization, and an evolving organization. Give each equivalent models, tools, code-generation ability, initial information, spawning capabilities, and total budgets. Count reflection and candidate evaluation costs. Add component ablations so a new tool's benefit is not misattributed to topology.

After learning, freeze state and evaluate unseen tasks. Success means higher completion within the same total budget, or equivalent quality at lower cost. Preserve learned knowledge and tools while rolling back only roles and connections to test topology's contribution. A MetaGen-style comparator is needed before claiming superiority to that approach.

The prototype provides the execution, reflection, validation, versioning, and rollback mechanisms. The offline demo verifies that lifecycle using simulated model responses; it establishes no performance advantage. The next milestone is the controlled workload experiment and a measured decision on whether the added organization earns its cost.
