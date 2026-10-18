import asyncio
from copy import deepcopy
import threading

import pytest
from langchain_core.messages import AIMessage

from company.chat import ChatService, conversation
from company.config import Settings
from company.organization import initial_manifest
from company.reflection import learning_evidence
from company.runtime import execute
from company.store import Store


def test_chat_uses_active_version_each_turn_and_keeps_private_history(tmp_path, monkeypatch):
    settings = Settings(api_key="chat-test-secret", model="test-model")
    store = Store(tmp_path / "company.sqlite3")
    base = store.initialize(initial_manifest(settings))
    monkeypatch.setattr(Settings, "load", lambda: settings)
    release = threading.Event()
    seen = []

    async def fake_execute(store, settings, **kwargs):
        run = store.start_run(kwargs["task_id"], kwargs["split"], kwargs["prompt"])
        store.link_chat_run(kwargs["chat_turn_id"], run["id"])
        seen.append((run["version_id"], [message.content for message in kwargs["conversation"]]))
        assert kwargs["ungraded"] and kwargs["expected"] is None
        assert release.wait(5)
        store.finish(run["id"], "completed", "First response", None, {"model_calls": 1, "complete": True})
        return store.replay(run["id"])

    monkeypatch.setattr("company.chat.execute", fake_execute)
    service = ChatService(store.path)
    turn = service.submit({"message": "Remember my order"})
    try:
        with pytest.raises(RuntimeError, match="answering"):
            service.submit({"message": "Duplicate concurrent submission"})
        with pytest.raises(RuntimeError, match="Another controller"):
            with store.controller():
                pass
    finally:
        release.set()
    assert service.busy.acquire(timeout=5)
    service.busy.release()
    assert store.chat_turns()[0]["status"] == "completed"

    candidate = deepcopy(base["manifest"])
    candidate["label"] = "next"
    candidate["prompts"]["generalist"] += " Be concise."
    reflection = store.start_reflection([], [])
    proposal_id = store.save_proposal(reflection, candidate, {})
    version = store.proposal(proposal_id)["candidate_version"]
    store.set_evaluation(proposal_id, "qualified", {"decision": "retain", "reason": "test fixture", "base_version": base["version_id"], "candidate_version": version})
    store.activate(proposal_id)
    service.submit({"message": "What did I say?", "thread_id": turn["thread_id"]})
    assert service.busy.acquire(timeout=5)
    service.busy.release()
    assert seen == [(base["version_id"], []), (version, ["Remember my order", "First response"])]
    assert conversation(store, "another-thread") == []
    assert learning_evidence(store, version) == []
    assert all(run["grade"] is None and run["split"] == "chat" for run in store.history())
    store.close()


def test_chat_runtime_passes_history_and_does_not_grade_free_text(tmp_path, monkeypatch):
    settings = Settings(api_key="test", model="test-model")
    store = Store(tmp_path / "company.sqlite3")
    store.initialize(initial_manifest(settings))
    from langchain_core.messages import HumanMessage
    class Agent:
        async def ainvoke(self, state, config):
            assert [message.content for message in state["messages"]] == ["Previous question", "Previous reply", "Follow up"]
            return {"messages": [AIMessage(content="A conversational response, not JSON.")]}
    monkeypatch.setattr("company.runtime.build_agent", lambda *args: Agent())
    result = asyncio.run(execute(store, settings, task_id="chat", split="chat", prompt="Follow up", expected=None,
                                ungraded=True, conversation=[HumanMessage(content="Previous question"), AIMessage(content="Previous reply")]))
    assert result["run"]["status"] == "completed" and result["run"]["grade"] is None
    assert not any(event["kind"] == "evaluation_finished" for event in result["events"])
    store.close()


def test_recovery_closes_abandoned_chat_and_preserves_completed_reply(tmp_path):
    store = Store(tmp_path / "company.sqlite3")
    store.initialize(initial_manifest(Settings(api_key="test", model="test-model")))
    abandoned = store.start_chat_turn("Abandoned")
    completed = store.start_chat_turn("Completed")
    run = store.start_run("chat", "chat", "Completed")
    store.link_chat_run(completed["id"], run["id"])
    store.finish(run["id"], "completed", "Reply", None, {})
    with store.controller():
        store.recover_interrupted()
    turns = {turn["id"]: turn for turn in store.chat_turns()}
    assert turns[abandoned["id"]]["status"] == "interrupted"
    assert turns[completed["id"]]["status"] == "completed"
    assert turns[completed["id"]]["output"] == "Reply"
    store.close()


def test_opted_in_task_is_learning_evidence_without_private_chat_context(tmp_path, monkeypatch):
    settings = Settings(api_key="test", model="test-model")
    store = Store(tmp_path / "company.sqlite3")
    active = store.initialize(initial_manifest(settings))
    private = store.start_chat_turn("Private earlier chat")
    row = store.start_run("private", "chat", "Private earlier chat")
    store.link_chat_run(private["id"], row["id"])
    store.finish(row["id"], "completed", "Private reply", None, {})
    store.finish_chat_turn(private["id"], "completed")
    monkeypatch.setattr(Settings, "load", lambda: settings)
    async def execution(store, settings, **kwargs):
        assert kwargs["conversation"] == [] and kwargs["split"] == "learning" and kwargs["ungraded"]
        row = store.start_run(kwargs["task_id"], kwargs["split"], kwargs["prompt"])
        store.link_chat_run(kwargs["chat_turn_id"], row["id"])
        store.finish(row["id"], "completed", "Task answer", None, {})
        return store.replay(row["id"])
    monkeypatch.setattr("company.chat.execute", execution)
    service = ChatService(store.path)
    service.submit({"message": "A standalone task", "thread_id": private["thread_id"], "learn": True})
    assert service.busy.acquire(timeout=5)
    service.busy.release()
    evidence = learning_evidence(store, active["version_id"])
    assert len(evidence) == 1 and evidence[0]["task"] == "A standalone task"
    assert evidence[0]["grade"] is None and "Private" not in str(evidence)
    store.close()
