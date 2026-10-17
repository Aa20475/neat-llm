import asyncio
from copy import deepcopy
import json
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from company.config import Settings
from company.organization import initial_manifest, worker_files
from company.reflection import apply_proposal, learning_diagnostics, propose
from company.runtime import build_agent
from company.store import Store
from company.validation import EvaluationBudget, decide, evaluate


@pytest.fixture
def company(tmp_path):
    settings = Settings(api_key="reflection-test-secret", model="test-model")
    store = Store(tmp_path / "company.sqlite3")
    store.initialize(initial_manifest(settings))
    yield store, settings
    store.close()


def proposal(store):
    active = store.active()
    reflection = store.start_reflection([], [])
    document = {"title": "Verify final order", "rationale": "A learning run missed sorting", "expected_benefit": "Correct ordering",
                "operations": [{"op": "revise_skill", "role": "generalist", "id": "final-check", "text": "Verify every output array is sorted as required before returning JSON."}]}
    candidate, document = apply_proposal(active["manifest"], document, [], "candidate-test")
    return store.save_proposal(reflection, candidate, document)


def qualify(store, proposal_id):
    row = store.proposal(proposal_id)
    store.set_evaluation(proposal_id, "qualified", {"decision": "retain", "reason": "unit test evidence", "base_version": row["base_version"], "candidate_version": row["candidate_version"]})


def test_candidate_isolation_atomic_activation_and_stale_generation(company):
    store, _ = company
    original = store.active()
    in_flight = store.start_run("in-flight", "learning", "input")
    first, second = proposal(store), proposal(store)
    assert store.active() == original
    with pytest.raises(ValueError, match="not passed"):
        store.activate(first)
    qualify(store, first); qualify(store, second)
    activated = store.activate(first)
    assert activated["generation"] == 1
    assert activated["version_id"] != original["version_id"]
    assert store.replay(in_flight["id"])["run"]["version_id"] == original["version_id"]
    with pytest.raises(ValueError, match="Stale"):
        store.activate(second)
    # Even an ABA move back to the exact original digest must not admit the old proposal.
    with store.db:
        store.db.execute("UPDATE organization SET active_version=?,generation=2", (original["version_id"],))
    with pytest.raises(ValueError, match="Stale"):
        store.activate(second)
    assert store.active()["generation"] == 2
    assert store.db.execute("SELECT COUNT(*) FROM activations").fetchone()[0] == 1


def test_typed_mutations_and_role_file_scoping(company):
    store, settings = company
    base = store.active()["manifest"]
    document = {"title": "Retain a checker", "rationale": "Observed useful work", "expected_benefit": "Reusable review",
                "operations": [{"op": "retain_role", "id": "checker", "source_worker_id": "observed-worker", "description": "Check ordering when needed", "text": "Check array ordering", "tools": []}]}
    with pytest.raises(ValueError, match="observed"):
        apply_proposal(base, document, [], "candidate")
    evidence = [{"run_id": "observed-run", "workers": [{"id": "observed-worker", "temporary": 1}]}]
    candidate, _ = apply_proposal(base, document, evidence, "candidate")
    assert build_agent(candidate, settings) is not None
    assert "Check array ordering" in str(worker_files(candidate, "checker"))
    assert base["prompts"]["generalist"] not in str(worker_files(candidate, "checker"))
    assert candidate["inference"] == base["inference"] and candidate["limits"] == base["limits"]
    forbidden = deepcopy(document)
    forbidden["operations"] = [{"op": "change_budget", "model_calls": 100000}]
    with pytest.raises(ValueError, match="Unsupported"):
        apply_proposal(base, forbidden, [], "candidate")


def test_gate_does_not_call_ties_improvements_or_accept_regressions():
    pair = {"base_passed": True, "candidate_passed": True, "base_tokens": 100, "candidate_tokens": 101}
    assert decide([pair], True)[0] == "reject"
    assert decide([{**pair, "candidate_tokens": 85}], True)[0] == "retain"
    assert decide([{**pair, "base_passed": False}], True)[0] == "retain"
    assert decide([{**pair, "base_passed": False, "candidate_tokens": 151}], True)[0] == "reject"
    assert decide([{**pair, "candidate_passed": False}], True)[0] == "reject"
    assert decide([pair], False)[0] == "inconclusive"


@pytest.mark.parametrize("regress", [False, True])
def test_paired_evaluation_retains_improvement_and_rejects_regression(company, monkeypatch, regress):
    store, settings = company
    original = store.active()["version_id"]
    proposal_id = proposal(store)
    candidate = store.proposal(proposal_id)["candidate_version"]
    seen = []
    async def fake_execute(store, settings, **kwargs):
        assert store.active()["version_id"] == original
        assert kwargs["split"] == "validation" and kwargs["phase"] == "evaluation"
        assert not kwargs["task_id"].startswith("heldout")
        kwargs["budget"].reserve()
        seen.append((kwargs["task_id"], kwargs["version_id"]))
        is_candidate = kwargs["version_id"] == candidate
        passed = (not is_candidate) if regress else (is_candidate or kwargs["task_id"] != "learn-trim-and-empty")
        return {"run": {"id": uuid4().hex, "status": "completed", "grade": {"passed": passed}, "usage": {"input_tokens": 100, "output_tokens": 10, "complete": True}}}
    monkeypatch.setattr("company.validation.execute", fake_execute)
    result = asyncio.run(evaluate(store, settings, proposal_id))
    if regress:
        assert result["status"] == "rejected" and store.active()["version_id"] == original
        assert len(seen) == 2  # Stop once a real regression is demonstrated.
    else:
        assert result["status"] == "retained" and store.active()["version_id"] == candidate
        assert len(seen) == 8 and len(result["evaluation"]["pairs"]) == 4
    assert store.memories()[0]["proposal_id"] == proposal_id
    with pytest.raises(ValueError, match="already"):
        asyncio.run(evaluate(store, settings, proposal_id))


def test_provider_failure_cannot_qualify_or_count_as_quality_regression(company, monkeypatch):
    store, settings = company
    proposal_id = proposal(store)
    original = store.active()
    async def failed(*args, **kwargs):
        kwargs["budget"].reserve()
        return {"run": {"id": uuid4().hex, "status": "failed", "grade": None, "usage": {"input_tokens": 0, "output_tokens": 0, "complete": False}}}
    monkeypatch.setattr("company.validation.execute", failed)
    assert asyncio.run(evaluate(store, settings, proposal_id))["status"] == "inconclusive"
    assert store.active() == original


def test_next_reflection_retrieves_lessons_without_validation_answers(company, monkeypatch):
    store, settings = company
    learning = store.start_run("learning-evidence", "learning", "Normalize this public input")
    store.finish(learning["id"], "completed", "[]", {"passed": False}, {"model_calls": 1})
    heldout = store.start_run("heldout-private", "heldout", "PRIVATE_HELDOUT_INPUT")
    store.finish(heldout["id"], "completed", "PRIVATE_HELDOUT_ANSWER", {"passed": True}, {})
    reflection = store.start_reflection([], [])
    store.remember(reflection["id"], None, "rejected", "Repeating the old prompt did not help", {"case_count": 4})
    class Model:
        async def ainvoke(self, messages):
            context = json.loads(messages[1].content)
            assert len(context["reflection_memory"]) == 1
            assert "PRIVATE_HELDOUT" not in messages[1].content
            assert [item["run_id"] for item in context["learning_evidence"]] == [learning["id"]]
            return AIMessage(content='{"no_change":true,"reason":"Need new evidence"}', usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})
    monkeypatch.setattr(Settings, "chat_model", lambda self: Model())
    result = asyncio.run(propose(store, settings))
    assert result["status"] == "no_change" and len(result["retrieved_memory_ids"]) == 1
    assert result["usage"]["model_calls"] == 1


def test_recovery_never_promotes_partial_evaluation(company):
    store, _ = company
    proposal_id = proposal(store)
    original = store.active()
    store.set_evaluation(proposal_id, "evaluating", {"reason": "In progress", "pairs": []})
    with store.controller():
        store.recover_interrupted()
    assert store.proposal(proposal_id)["status"] == "inconclusive"
    assert store.active() == original


def test_learning_diagnostic_reports_property_without_answer_values():
    from company.workload import load_cases
    case = load_cases("learning")[0]
    output = json.dumps(list(reversed(case["expected"])))
    issues = learning_diagnostics(case["id"], output)
    assert issues[0]["property"] == "array_order"
    assert "a-1" not in str(issues) and "bob@example.com" not in str(issues)
    assert learning_diagnostics("heldout-independent-rounding", output) == []


def test_duplicate_proposal_skips_paid_evaluation_and_remembers_why(company, monkeypatch):
    store, settings = company
    prior = proposal(store)
    row = store.proposal(prior)
    store.set_evaluation(prior, "rejected", {"decision": "reject", "reason": "Regression"})
    run = store.start_run("learning-evidence", "learning", "public input")
    store.finish(run["id"], "completed", "[]", {"passed": False}, {})
    class Model:
        async def ainvoke(self, messages):
            return AIMessage(content=json.dumps({key: value for key, value in row["document"].items() if key != "changes"}),
                             usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})
    monkeypatch.setattr(Settings, "chat_model", lambda self: Model())
    result = asyncio.run(propose(store, settings))
    assert result["status"] == "duplicate" and result["proposal_id"] is None
    assert store.db.execute("SELECT COUNT(*) FROM proposals").fetchone()[0] == 1
    assert store.memories()[0]["outcome"] == "duplicate"


def test_revocation_restores_base_and_preserves_original_evidence(company):
    store, _ = company
    base = store.active()["version_id"]
    proposal_id = proposal(store)
    qualify(store, proposal_id)
    store.activate(proposal_id)
    active = store.revoke_activation(proposal_id, "Conflicting equivalent experiment")
    assert active["version_id"] == base and active["generation"] == 2
    assert store.proposal(proposal_id)["status"] == "revoked"
    assert store.proposal(proposal_id)["evaluation"]["decision"] == "retain"
    assert store.db.execute("SELECT COUNT(*) FROM activations").fetchone()[0] == 2
    assert store.memories()[0]["outcome"] == "revoked"
