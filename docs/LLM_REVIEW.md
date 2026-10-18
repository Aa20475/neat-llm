# Try reflection on your own task

1. Open Chat and start a new conversation with the active generalist.
2. Check **Use this task for reflection** and send a self-contained task with clear requirements. The task runs independently of prior chat. Its input, answer, worker trace, and usage become learning evidence; its answer is not assigned an invented test score.
3. After the answer finishes, open Reflection lab and press **Run reflection**.

Reflection proposes at most one change. If it creates a new candidate, the controller replays the latest task from that proposal's recorded learning evidence on both the saved base version and the candidate. Each run starts from its pinned organization and fresh task state.

A separate LLM call receives the original task and two final answers labeled A and B. The assignment and execution order are randomized and recorded. It receives no candidate identity, proposal rationale, role prompts, or reflection history, and has no tools. It uses the configured Crusoe model in a new conversation; it is not a different set of model weights.

The reviewer chooses A, B, tie, or neither and gives a reason. A candidate preference qualifies the proposal for the existing atomic activation step. An incumbent preference, tie, or neither keeps the incumbent. Provider failure, incomplete usage, an invalid verdict, interruption, or budget exhaustion makes the comparison inconclusive and never promotes. Stale generations cannot activate.

This is the requested **subjective prototype gate**. It evaluates one reused task, can be biased or mistaken, and does not prove improvement on unseen work. Review labels and reasoning are visible in the UI. Responses remain ungraded; LLM preference is never shown as a deterministic pass. Saved benchmark proposals continue to use their existing exact-output checks.

The comparison has no shared model-call or admission-time budget. Both execution branches and their workers use their pinned run settings; new unlimited snapshots have no aggregate execution caps. The reviewer has at most 700 output tokens and no automatic retries. The preceding reflection call has its separate existing cap. Reviewer usage is stored explicitly and counted once in UI totals. Duplicate proposals skip comparison.

The initial reset archived all old records under ignored `data/archive/` and recreated v0 at generation 0: one generalist, no saved specialists, no bound skills or task memory, and empty run/reflection history. Resetting local state does not make the old published benchmark tasks unseen again. No tasks or reflection calls were seeded into the clean workspace.

Verification includes explicit opt-in, isolation from earlier private chat, subjective candidate promotion, incumbent/tie/neither rejection, and invalid-verdict handling. A separate live integration check used a clearly labeled controller-authored candidate in a temporary database. It replayed a three-step release-checklist task and made one independent review call. The reviewer preferred the incumbent, and generation stayed 0. That comparison used three calls, 2,978 input tokens, and 188 output tokens; its initial learning execution was separate. The full local record is `artifacts/llm-review-check.json`. This check verifies the mechanism and does not claim a learned gain.

The generalist and workers also have [Python execution](PYTHON_TOOL.md). Reflection receives bounded excerpts of the latest Python calls and results from opted-in learning runs. The reviewer still compares final answers only; it does not independently rerun generated tests or verify a claim that they passed.
