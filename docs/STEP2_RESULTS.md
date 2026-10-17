# Step 2 verification

Verified locally on 2026-10-17 using the installed Deep Agents SDK and real Crusoe inference. The controller runs locally; this is not a NemoClaw or Crusoe VM deployment.

The active v0 digest is `2e05ac3eb86f5e3aea2530083c60a9101847bfcb69b15cfe89dd67ae824028af`, generation 0. Two scored learning tasks and a delegation check in a later process used that same digest. Running `init` again preserved it.

| Check | Observed result |
| --- | --- |
| Local tests | 20 passed: persistence, immutable versions, restart/recovery, controller exclusion, shared budgets, worker lineage, grading separation, SDK compilation, virtual file staging, and pure tools |
| `learn-trim-and-empty` | Completed; failed independent grading because orders remained in input order rather than sorted by `order_id` |
| `learn-round-lines-first` | Completed; passed strict output comparison |
| Temporary delegation | Passed: root delegated to a real child; child called built-in `read_file` and `decimal_product`; root returned 42 |
| Restart | Same active digest and generation, prior run records still readable |
| Held-out evaluation | Not run |

The two learning cases used 3,296 reported input tokens and 214 output tokens across two model calls. The successful delegation check used 5,059 input tokens and 234 output tokens across four model calls. These figures exclude failed development attempts; the local report and databases preserve those attempts separately. Some requests returned Crusoe HTTP 429 (`max_requests_limit`), so the runtime now shares a two-second request interval across parent and children. SDK retries remain disabled. Failed/interrupted calls can leave usage incomplete; recorded tokens are not a complete billing statement.

The baseline is **1/2 passing learning cases**, not a demonstrated improvement. Preserve the sorting failure as evidence for the next reflection stage. Do not tune against the held-out answers.

Local evidence, ignored by Git:

- `artifacts/step2-report.json`: run IDs, restart check, usage, and remaining scope.
- `artifacts/replay.json`: successful delegation replay, including the real worker tree.
- `artifacts/learn-trim-and-empty.json` and `artifacts/learn-round-lines-first.json`: learning-task traces.
- `data/company.sqlite3`: configuration, runs, workers, and ordered events.

The worker file tree is populated from the pinned role configuration. V0 contains `/organization/README.md` and `/organization/prompt.md`; bound skills and task memory will appear under their respective directories. Temporary children inherit a snapshot in their own graph state. Workers have no host-project mount, shell, or database tool. Reflection memory, promotion/evaluation, permanent specialist compilation, and the graphical viewer remain next steps. A future specialist promotion saves the evaluated role definition, not the original worker process.
