"""Controller-owned paired gate. Evaluation cannot edit the active configuration."""

import hashlib
from pathlib import Path
import threading
import time

from company.organization import digest, validate_manifest
from company.runtime import BudgetExceeded, execute
from company.store import Store
from company.workload import FIXTURES, load_cases, task_prompt

POLICY = {
    "name": "paired-development-v1", "max_model_calls": 24, "wall_seconds": 240,
    "max_candidate_token_ratio": 1.5, "min_token_reduction": 0.15,
    "cases": ["learn-trim-and-empty", "learn-round-lines-first", "validate-leading-zero-quantity", "validate-stable-duplicates"],
}


class EvaluationBudget:
    def __init__(self, limit=POLICY["max_model_calls"], wall_seconds=POLICY["wall_seconds"]):
        self.limit, self.used = limit, 0
        self.deadline = time.monotonic() + wall_seconds
        self.lock = threading.Lock()

    def reserve(self):
        with self.lock:
            if self.used >= self.limit or time.monotonic() > self.deadline:
                raise BudgetExceeded("Shared evaluation budget exhausted")
            self.used += 1


def decide(pairs: list[dict], complete: bool) -> tuple[str, str]:
    if not complete:
        return "inconclusive", "Incomplete comparison or provider/usage failure"
    if any(pair["base_passed"] and not pair["candidate_passed"] for pair in pairs):
        return "reject", "Candidate regressed on a previously passing paired case"
    base_tokens = sum(pair["base_tokens"] for pair in pairs)
    candidate_tokens = sum(pair["candidate_tokens"] for pair in pairs)
    if candidate_tokens > base_tokens * POLICY["max_candidate_token_ratio"]:
        return "reject", "Candidate exceeded the declared 1.5× execution token ceiling"
    if any(not pair["base_passed"] and pair["candidate_passed"] for pair in pairs):
        return "retain", "At least one newly passed case, no paired regressions, within token ceiling"
    if all(pair["base_passed"] == pair["candidate_passed"] for pair in pairs) and base_tokens > 0 and candidate_tokens <= base_tokens * (1 - POLICY["min_token_reduction"]):
        return "retain", "Same paired outcomes with at least 15% fewer execution tokens"
    return "reject", "No measured quality gain or qualifying token reduction"


async def evaluate(store: Store, settings, proposal_id: str, activate: bool = True) -> dict:
    proposal = store.proposal(proposal_id)
    if proposal["status"] != "pending":
        raise ValueError("This proposal has already been evaluated; create a new proposal for another attempt")
    active = store.active()
    if (active["version_id"], active["generation"]) != (proposal["base_version"], proposal["base_generation"]):
        raise ValueError("Stale proposal; reflect against the current active organization")
    base = store.manifest(proposal["base_version"])
    candidate = store.manifest(proposal["candidate_version"])
    validate_manifest(candidate)
    for field in ("inference", "runtime", "limits", "tools"):
        if base[field] != candidate[field]:
            raise ValueError(f"Candidate cannot change controller-owned comparison field: {field}")
    cases = [(split, case) for split in ("learning", "validation") for case in load_cases(split)]
    if [case["id"] for _, case in cases] != POLICY["cases"]:
        raise ValueError("Fixed comparison suite changed; revise the declared policy explicitly")
    budget = EvaluationBudget()
    report = {"policy": POLICY, "base_version": proposal["base_version"], "candidate_version": proposal["candidate_version"],
              "suite_digest": digest({"spec": (FIXTURES / "spec.md").read_text(), "cases": cases}),
              "evaluator_digest": hashlib.sha256(Path(__file__).with_name("workload.py").read_bytes()).hexdigest(),
              "pairs": [], "decision": "pending", "reason": "Comparison in progress", "usage": {},
              "note": "Four fixed development cases, one fresh run per branch. No held-out transfer claim; validation reuse can overfit."}
    store.set_evaluation(proposal_id, "evaluating", report)
    completed_runs = []
    started = time.monotonic()
    complete = True
    try:
        for index, (split, case) in enumerate(cases):
            outputs = {}
            # Alternate branch order; neither branch learns or activates during evaluation.
            branches = ("base", "candidate") if index % 2 == 0 else ("candidate", "base")
            for branch in branches:
                if budget.used >= budget.limit or time.monotonic() > budget.deadline:
                    raise BudgetExceeded("Shared evaluation budget exhausted")
                print(f"Comparing {case['id']} · {branch}", flush=True)
                result = await execute(store, settings, task_id=case["id"], split="validation", prompt=task_prompt(case),
                                       expected=case["expected"], version_id=proposal[f"{branch}_version"], budget=budget, phase="evaluation")
                outputs[branch] = result["run"]
                completed_runs.append(result["run"])
                if result["run"]["status"] != "completed" or not result["run"]["usage"]["complete"]:
                    complete = False
            pair = {"task_id": case["id"], "split": "learning regression" if split == "learning" else "validation"}
            for branch, run in outputs.items():
                pair.update({f"{branch}_run_id": run["id"], f"{branch}_passed": bool((run["grade"] or {}).get("passed")),
                             f"{branch}_tokens": run["usage"]["input_tokens"] + run["usage"]["output_tokens"], f"{branch}_status": run["status"]})
            report["pairs"].append(pair)
            store.set_evaluation(proposal_id, "evaluating", report)
            if not complete:
                break  # Failed provider requests are not negative task scores; stop paid work.
            if pair["base_passed"] and not pair["candidate_passed"]:
                break  # A demonstrated regression is sufficient to reject; save remaining calls.
        complete &= len(report["pairs"]) == len(cases)
        regression = any(pair["base_passed"] and not pair["candidate_passed"] and pair["base_status"] == pair["candidate_status"] == "completed" for pair in report["pairs"])
        if regression:
            decision, reason = "reject", "Candidate regressed on a previously passing paired case; remaining comparisons skipped"
        else:
            decision, reason = decide(report["pairs"], complete)
    except BudgetExceeded as error:
        decision, reason = "inconclusive", str(error)
    except BaseException:
        report.update(decision="inconclusive", reason="Evaluation interrupted before completing the paired gate")
        store.set_evaluation(proposal_id, "inconclusive", report)
        raise
    report.update(decision=decision, reason=reason,
                  usage={"phase": "evaluation", "model_calls": budget.used,
                         "input_tokens": sum(run["usage"]["input_tokens"] for run in completed_runs),
                         "output_tokens": sum(run["usage"]["output_tokens"] for run in completed_runs),
                         "elapsed_seconds": round(time.monotonic() - started, 3),
                         "complete": all(run["usage"]["complete"] for run in completed_runs)},
                  run_ids=[run["id"] for run in completed_runs])
    status = {"retain": "qualified", "reject": "rejected", "inconclusive": "inconclusive"}[decision]
    store.set_evaluation(proposal_id, status, report)
    if decision == "retain" and activate:
        try:
            store.activate(proposal_id)
            status = "retained"
        except ValueError as error:
            status = "stale"
            report["reason"] = str(error)
            store.set_evaluation(proposal_id, status, report)
    # Store bounded findings, never validation inputs/outputs or answer keys.
    store.remember(proposal["reflection_id"], proposal_id, status,
                   f"{proposal['document']['title']}: {report['reason']}",
                   {"base_version": proposal["base_version"], "candidate_version": proposal["candidate_version"],
                    "operations": proposal["document"]["operations"], "decision": decision,
                    "base_passed": sum(pair["base_passed"] for pair in report["pairs"]),
                    "candidate_passed": sum(pair["candidate_passed"] for pair in report["pairs"]),
                    "case_count": len(report["pairs"]), "usage": report["usage"]})
    return {"proposal_id": proposal_id, "status": status, "evaluation": report, "active_version": store.active()["version_id"]}
