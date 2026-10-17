import asyncio
from copy import deepcopy
import sqlite3

import pytest

from company.audit import POLICY, audit
from company.config import Settings
from company.organization import initial_manifest
from company.reflection import learning_evidence
from company.store import Store


@pytest.fixture
def company(tmp_path):
    settings = Settings(api_key="test-key", model="test-model")
    store = Store(tmp_path / "company.sqlite3")
    base = store.initialize(initial_manifest(settings))
    candidate = deepcopy(base["manifest"])
    candidate["label"] = "frozen-candidate"
    candidate["prompts"]["generalist"] += " Check ordering."
    reflection = store.start_reflection([], [])
    proposal_id = store.save_proposal(reflection, candidate, {"title": "Check ordering", "changes": []})
    row = store.proposal(proposal_id)
    store.set_evaluation(proposal_id, "qualified", {"decision": "retain", "reason": "test evidence",
                          "base_version": row["base_version"], "candidate_version": row["candidate_version"]})
    store.activate(proposal_id)
    store.revoke_activation(proposal_id, "test revocation")
    yield store, settings, proposal_id
    store.close()


def test_frozen_audit_cannot_promote_learn_or_repeat(company, monkeypatch):
    store, settings, proposal_id = company
    active, memories = store.active(), store.memories()
    branches = store.proposal(proposal_id)
    calls = []
    async def execute(store, settings, **kwargs):
        assert kwargs["split"] == kwargs["phase"] == "heldout"
        kwargs["budget"].reserve()
        calls.append((kwargs["task_id"], kwargs["version_id"]))
        run = store.start_run(kwargs["task_id"], kwargs["split"], kwargs["prompt"], kwargs["version_id"])
        store.finish(run["id"], "completed", "[]", {"passed": kwargs["version_id"] == branches["candidate_version"]},
                     {"input_tokens": 20, "output_tokens": 2, "complete": True})
        return store.replay(run["id"])
    monkeypatch.setattr("company.audit.execute", execute)
    result = asyncio.run(audit(store, settings, proposal_id))
    assert len(calls) == 8 and result["status"] == "completed"
    assert result["report"]["scores"]["candidate"]["passed"] == 4
    assert result["report"]["persistence"]["active_unchanged"]
    assert store.active() == active and store.memories() == memories
    assert store.proposal(proposal_id)["status"] == "revoked"
    assert learning_evidence(store, active["version_id"]) == []
    # Each task is paired twice and receives opposite branch ordering on repetition two.
    for task in POLICY["cases"]:
        versions = [version for task_id, version in calls if task_id == task]
        assert versions[:2] == list(reversed(versions[2:]))
    with pytest.raises(ValueError, match="consumed"):
        asyncio.run(audit(store, settings, proposal_id))
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        store.db.execute("UPDATE audits SET plan='{}' WHERE id=?", (result["id"],))
    store.db.rollback()


def test_partial_audit_is_inconclusive_not_a_failed_task(company, monkeypatch):
    store, settings, proposal_id = company
    async def failed(store, settings, **kwargs):
        kwargs["budget"].reserve()
        return {"run": {"id": "failed-run", "status": "failed", "grade": None,
                        "usage": {"input_tokens": 0, "output_tokens": 0, "complete": False}}}
    monkeypatch.setattr("company.audit.execute", failed)
    result = asyncio.run(audit(store, settings, proposal_id))
    assert result["status"] == "inconclusive"
    assert result["report"]["scores"]["base"]["graded"] == 0
    assert result["report"]["usage"]["complete"] is False


def test_recovery_preserves_frozen_plan_and_consumed_suite(company):
    store, _, _ = company
    audit_id = store.start_audit(POLICY["suite_id"], {"frozen": "before any inference"})
    with store.controller():
        store.recover_interrupted()
    assert store.audit(audit_id)["status"] == "inconclusive"
    assert store.audit(audit_id)["plan"] == {"frozen": "before any inference"}
    with pytest.raises(ValueError, match="consumed"):
        store.start_audit(POLICY["suite_id"], {})
    reopened = Store(store.path)
    try:
        assert reopened.active()["generation"] == 2
        assert reopened.db.execute("SELECT COUNT(*) FROM activations").fetchone()[0] == 2
    finally:
        reopened.close()
