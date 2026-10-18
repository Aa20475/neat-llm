"""One frozen, descriptive held-out comparison; no learning or activation side effects."""

import hashlib
import json
from pathlib import Path
import time

from company.organization import behavior_digest, digest, validate_manifest
from company.runtime import BudgetExceeded, execute
from company.store import Store
from company.validation import EvaluationBudget
from company.workload import FIXTURES, load_cases, task_prompt


POLICY = {
    "name": "frozen-heldout-v1", "suite_id": "orders-heldout-v1",
    "cases": ["heldout-independent-rounding", "heldout-zero-and-ordering"],
    "repetitions": 2, "max_model_calls": 16, "wall_seconds": 240,
    "activation": False, "reflection_feedback": False,
}


def pointer(store):
    active = store.active()
    return {key: active[key] for key in ("version_id", "generation")}


def adaptation_usage(store):
    """Recorded experiment overhead before freeze, separate from audit execution."""
    phases = {"reflection": [], "evaluation": []}
    phases["reflection"] = [json.loads(row[0]) for row in store.db.execute(
        "SELECT usage FROM reflections WHERE usage IS NOT NULL")]
    phases["evaluation"] = [run["usage"] for run in store.history()
                            if (run["usage"] or {}).get("phase") == "evaluation"]
    for row in store.db.execute("SELECT evaluation FROM proposals WHERE evaluation IS NOT NULL"):
        judge_usage = (json.loads(row[0]).get("judge") or {}).get("usage")
        if judge_usage:
            phases["evaluation"].append(judge_usage)
    return {phase: {**{key: sum(usage.get(key, 0) for usage in rows)
                           for key in ("model_calls", "input_tokens", "output_tokens")},
                    "complete": all(usage.get("complete", False) for usage in rows)}
            for phase, rows in phases.items()}


async def audit(store: Store, settings, proposal_id: str) -> dict:
    proposal = store.proposal(proposal_id)
    if proposal["status"] not in ("retained", "revoked", "rejected", "qualified"):
        raise ValueError("Freeze an already evaluated proposal before opening held-out tasks")
    versions = {branch: proposal[f"{branch}_version"] for branch in ("base", "candidate")}
    manifests = {branch: store.manifest(version) for branch, version in versions.items()}
    for manifest in manifests.values():
        validate_manifest(manifest)
    for field in ("inference", "runtime", "limits", "tools"):
        if manifests["base"][field] != manifests["candidate"][field]:
            raise ValueError(f"Frozen branches differ in controller-owned field: {field}")
    if behavior_digest(manifests["base"]) == behavior_digest(manifests["candidate"]):
        raise ValueError("Identical configurations do not need a held-out comparison")
    if store.db.execute("SELECT 1 FROM audits WHERE suite_id=?", (POLICY["suite_id"],)).fetchone():
        raise ValueError("Held-out suite already consumed; inspect its saved audit instead of retesting")
    if any(run["split"] == "heldout" for run in store.history()):
        raise ValueError("Existing held-out runs prevent claiming this suite was unseen")
    cases = load_cases("heldout")
    if [case["id"] for case in cases] != POLICY["cases"]:
        raise ValueError("Held-out suite changed; use a separately declared new suite")
    plan = {
        "policy": POLICY, "proposal_id": proposal_id, "candidate_status_at_freeze": proposal["status"],
        "versions": versions, "labels": {branch: value["label"] for branch, value in manifests.items()},
        "behavior_digests": {branch: behavior_digest(value) for branch, value in manifests.items()},
        "active_at_freeze": pointer(store), "changes": proposal["document"].get("changes", []),
        "suite_digest": digest({"spec": (FIXTURES / "spec.md").read_text(), "cases": cases}),
        "evaluator_digest": hashlib.sha256(Path(__file__).with_name("workload.py").read_bytes()).hexdigest(),
        "reflection_memory_digest": digest(store.memories(limit=1000000)),
        "adaptation_usage_before_freeze": adaptation_usage(store),
        "activation_history_at_freeze": [dict(row) for row in store.db.execute("SELECT * FROM activations ORDER BY generation")],
        "note": "Two distinct held-out tasks, two repetitions per branch. Descriptive audit only; no promotion or reflection feedback. A revoked candidate remains revoked.",
    }
    audit_id = store.start_audit(POLICY["suite_id"], plan)
    report = store.audit(audit_id)["report"]
    budget = EvaluationBudget(POLICY["max_model_calls"], POLICY["wall_seconds"])
    runs = []
    started = time.monotonic()
    status = "completed"

    def summarize():
        report["usage"] = {"phase": "heldout", "model_calls": budget.used,
                           "input_tokens": sum(run["usage"].get("input_tokens", 0) for _, run in runs),
                           "output_tokens": sum(run["usage"].get("output_tokens", 0) for _, run in runs),
                           "complete": bool(runs) and all(run["usage"].get("complete", False) for _, run in runs),
                           "elapsed_seconds": round(time.monotonic() - started, 3)}
        report["scores"] = {}
        for branch in versions:
            branch_runs = [run for name, run in runs if name == branch]
            graded = [run for run in branch_runs if run["status"] == "completed" and run.get("grade") is not None]
            report["scores"][branch] = {
                "passed": sum(bool(run["grade"].get("passed")) for run in graded),
                "graded": len(graded), "planned": len(cases) * POLICY["repetitions"],
                "tokens": sum(run["usage"].get("input_tokens", 0) + run["usage"].get("output_tokens", 0) for run in branch_runs),
            }

    try:
        for repetition in range(POLICY["repetitions"]):
            for index, case in enumerate(cases):
                pair = {"task_id": case["id"], "repetition": repetition + 1}
                report["pairs"].append(pair)
                # Each task sees both branch orders across its two repetitions.
                branches = ("base", "candidate") if (index + repetition) % 2 == 0 else ("candidate", "base")
                for branch in branches:
                    if budget.used >= budget.limit or time.monotonic() > budget.deadline:
                        raise BudgetExceeded("Frozen audit budget exhausted")
                    print(f"Auditing {case['id']} · repetition {repetition + 1} · {branch}", flush=True)
                    result = await execute(store, settings, task_id=case["id"], split="heldout", prompt=task_prompt(case),
                                           expected=case["expected"], version_id=versions[branch], budget=budget, phase="heldout")
                    run = result["run"]
                    runs.append((branch, run))
                    report["run_ids"].append(run["id"])
                    pair[branch] = {"run_id": run["id"], "status": run["status"],
                                    "passed": (run.get("grade") or {}).get("passed"),
                                    "tokens": run["usage"].get("input_tokens", 0) + run["usage"].get("output_tokens", 0)}
                    summarize()
                    store.update_audit(audit_id, "running", report)
                    if run["status"] != "completed" or not run["usage"].get("complete"):
                        raise BudgetExceeded("Incomplete execution or usage; audit is inconclusive, not a quality failure")
        report["reason"] = "Frozen comparison complete. Results are descriptive; no configuration was promoted."
    except BudgetExceeded as error:
        status, report["reason"] = "inconclusive", str(error)
    except BaseException:
        summarize()
        report["reason"] = "Audit interrupted; partial evidence preserved and held-out suite remains consumed"
        store.update_audit(audit_id, "inconclusive", report)
        raise
    summarize()
    # Reopen the database and verify the actual persisted control state without resetting it.
    reopened = Store(store.path)
    try:
        report["persistence"] = {
            "active_after_reopen": pointer(reopened),
            "active_unchanged": pointer(reopened) == plan["active_at_freeze"],
            "reflection_memory_unchanged": digest(reopened.memories(limit=1000000)) == plan["reflection_memory_digest"],
            "audit_plan_preserved": reopened.audit(audit_id)["plan"] == plan,
        }
    finally:
        reopened.close()
    if not all(report["persistence"][key] for key in ("active_unchanged", "reflection_memory_unchanged", "audit_plan_preserved")):
        status, report["reason"] = "inconclusive", "Persisted state did not match the frozen audit plan"
    store.update_audit(audit_id, status, report)
    return store.audit(audit_id)
