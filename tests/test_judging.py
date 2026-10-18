import asyncio
import json

import pytest
from langchain_core.messages import AIMessage

from company.config import Settings
from company.organization import initial_manifest
from company.reflection import apply_proposal, propose
from company.store import Store
from company.validation import evaluate


@pytest.mark.parametrize("winner,expected_status", [("B", "retained"), ("A", "rejected"), ("tie", "rejected"), ("neither", "rejected"), ("invalid", "inconclusive")])
@pytest.mark.parametrize("finish_reason", ["stop", "length"])
def test_independent_review_promotes_only_preferred_candidate(tmp_path, monkeypatch, winner, expected_status, finish_reason):
    settings = Settings(api_key="secret-judge-key", model="test-model")
    store = Store(tmp_path / "company.sqlite3")
    active = store.initialize(initial_manifest(settings))
    task = store.start_run("task-user", "learning", "Produce a concise plan with three steps")
    store.start_project(task["id"], "learning", initial_files={"input.txt": "starting input"})
    store.save_project(task["id"], {"input.txt": "starting input", "solution.py": "ANSWER_FROM_LEARNING"}, {})
    store.finish(task["id"], "completed", "Initial answer", None, {})
    reflection = store.start_reflection([task["id"]], [])
    document = {"title": "Check explicit requirements", "rationale": "INTERNAL_PROPOSAL_RATIONALE",
                "expected_benefit": "Follow the user's requested format",
                "operations": [{"op": "revise_skill", "role": "generalist", "id": "check-format", "text": "Check every explicit requirement before returning an answer."}]}
    candidate, document = apply_proposal(active["manifest"], document, [{"run_id": task["id"], "workers": []}], "candidate-test")
    document["evaluation_scope"] = "user-task"
    proposal_id = store.save_proposal(reflection, candidate, document)
    seen = []
    async def execution(store, settings, **kwargs):
        kwargs["budget"].reserve()
        assert kwargs["split"] == "review" and kwargs["ungraded"] and kwargs["expected"] is None
        assert store.active() == active
        assert kwargs["initial_files"] == {"input.txt": "starting input"}
        kwargs["initial_files"]["input.txt"] = "A branch's edits must not affect the next branch"
        row = store.start_run(kwargs["task_id"], kwargs["split"], kwargs["prompt"], kwargs["version_id"])
        store.finish(row["id"], "completed", "Answer " + kwargs["version_id"][:5], None,
                     {"model_calls": 1, "input_tokens": 100, "output_tokens": 20, "complete": True})
        seen.append(row["id"])
        return store.replay(row["id"])
    class Judge:
        async def ainvoke(self, messages, **kwargs):
            context = json.loads(messages[1].content)
            assert set(context) == {"task", "answers"} and set(context["answers"]) == {"A", "B"}
            assert "INTERNAL_PROPOSAL_RATIONALE" not in messages[1].content
            return AIMessage(content=json.dumps({"winner": winner, "reason": "The selected answer better satisfies the requested structure."}),
                             response_metadata={"finish_reason": finish_reason},
                             usage_metadata={"input_tokens": 60, "output_tokens": 25, "total_tokens": 85})
    async def no_wait(*args):
        pass
    monkeypatch.setattr("company.judging.execute", execution)
    monkeypatch.setattr("company.judging.secrets.choice", lambda options: options[0])
    monkeypatch.setattr("company.judging.asyncio.sleep", no_wait)
    def judge_model(self):
        assert self.max_tokens is None  # No hidden judge-specific token cap.
        return Judge()
    monkeypatch.setattr(Settings, "chat_model", judge_model)
    result = asyncio.run(evaluate(store, settings, proposal_id))
    assert result["status"] == ("inconclusive" if finish_reason == "length" else expected_status)
    assert result["evaluation"]["usage"]["model_calls"] == 3
    assert result["evaluation"]["usage"]["input_tokens"] == 260
    assert len(seen) == 2 and all(store.replay(run_id)["run"]["grade"] is None for run_id in seen)
    assert store.active()["generation"] == (1 if winner == "B" and finish_reason == "stop" else 0)
    assert store.memories()[0]["evidence"]["review_kind"] == "subjective_llm"
    assert result["evaluation"]["policy"]["objective"] is False
    assert result["evaluation"]["policy"]["judge_max_tokens"] is None
    store.close()


def test_ungraded_user_task_gets_user_task_evaluation_scope(tmp_path, monkeypatch):
    settings = Settings(api_key="test", model="test-model")
    store = Store(tmp_path / "company.sqlite3")
    store.initialize(initial_manifest(settings))
    task = store.start_run("task-user", "learning", "Write a three-step plan")
    store.finish(task["id"], "completed", "A plan", None, {})
    class Model:
        async def ainvoke(self, messages, **kwargs):
            assert json.loads(messages[1].content)["learning_evidence"][0]["grade"] is None
            return AIMessage(content=json.dumps({"title": "Check constraints", "rationale": "Better formatting", "expected_benefit": "Follow the requested structure",
                "operations": [{"op": "revise_skill", "role": "generalist", "id": "constraints", "text": "Check explicit output constraints before responding."}]}),
                usage_metadata={"input_tokens": 10, "output_tokens": 20, "total_tokens": 30})
    monkeypatch.setattr(Settings, "chat_model", lambda self: Model())
    result = asyncio.run(propose(store, settings))
    assert result["status"] == "proposed" and result["evaluation_scope"] == "user-task"
    assert store.proposal(result["proposal_id"])["document"]["evidence_ids"] == [task["id"]]
    store.close()
