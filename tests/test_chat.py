import asyncio
from copy import deepcopy
import json
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


def test_shared_followup_keeps_task_in_saved_replay_without_private_context(tmp_path, monkeypatch):
    settings = Settings(api_key="test", model="test-model")
    store = Store(tmp_path / "company.sqlite3")
    store.initialize(initial_manifest(settings))
    private = store.start_chat_turn("PRIVATE earlier conversation")
    private_run = store.start_run("private", "chat", "PRIVATE earlier conversation")
    store.link_chat_run(private["id"], private_run["id"])
    store.finish(private_run["id"], "completed", "PRIVATE reply", None, {})
    store.finish_chat_turn(private["id"], "completed")
    task_prompt = "Implement and execute a Python scheduler"
    shared = store.start_chat_turn(task_prompt, private["thread_id"])
    shared_run = store.start_run("task", "learning", task_prompt)
    store.link_chat_run(shared["id"], shared_run["id"])
    store.finish(shared_run["id"], "incomplete", "I will begin", None, {})
    store.finish_chat_turn(shared["id"], "incomplete")
    monkeypatch.setattr(Settings, "load", lambda: settings)
    async def execution(store, settings, **kwargs):
        assert kwargs["conversation"] == [] and kwargs["split"] == "learning"
        assert "PRIVATE" not in kwargs["prompt"]
        context = json.loads(kwargs["prompt"].split("\n", 1)[1])
        assert context["current_request"] == "Do it"
        assert context["previous_messages"][0]["content"] == task_prompt
        row = store.start_run(kwargs["task_id"], kwargs["split"], kwargs["prompt"])
        store.link_chat_run(kwargs["chat_turn_id"], row["id"])
        store.finish(row["id"], "completed", "Executed", None, {})
        return store.replay(row["id"])
    monkeypatch.setattr("company.chat.execute", execution)
    service = ChatService(store.path)
    result = service.submit({"message": "Do it", "thread_id": shared["thread_id"], "learn": True})
    assert service.busy.acquire(timeout=5)
    service.busy.release()
    turn = next(t for t in store.chat_turns() if t["id"] == result["id"])
    assert turn["prompt"] == "Do it" and turn["status"] == "completed"
    assert "Python scheduler" in store.replay(turn["run_id"])["run"]["prompt"]
    store.close()


@pytest.mark.parametrize("reference", [None, "reflection", "audit"])
def test_delete_conversation_removes_traces_or_preserves_referenced_evidence(tmp_path, reference):
    store = Store(tmp_path / "company.sqlite3")
    original = store.initialize(initial_manifest(Settings(api_key="test", model="test-model")))
    turn = store.start_chat_turn("Delete this task")
    run = store.start_run("task-delete", "learning", "Delete this task")
    store.link_chat_run(turn["id"], run["id"])
    store.start_project(run["id"], "learning", turn["id"])
    store.save_project(run["id"], {"answer.py": "print(42)"}, {})
    store.worker_start(run["id"], "child", run["id"] + ":root", "general-purpose", True, "Bounded check")
    store.finish(run["id"], "completed", "Answer", None, {})
    store.finish_chat_turn(turn["id"], "completed")
    other = store.start_chat_turn("Keep this conversation")
    store.finish_chat_turn(other["id"], "failed", "Fixture without run")
    if reference == "reflection":
        saved = store.start_reflection([run["id"]], [])
        store.finish_reflection(saved["id"], "no_change", {}, {"no_change": True, "reason": "Fixture"})
    elif reference == "audit":
        saved = store.start_audit("fixture-audit", {"source_run_id": run["id"]})
        store.update_audit(saved, "completed", {"run_ids": [run["id"]]})
    result = ChatService(store.path).delete({"thread_id": turn["thread_id"]})
    assert result["deleted_turns"] == 1 and result["deleted_runs"] == (0 if reference else 1)
    assert result["retained_evidence_runs"] == (1 if reference else 0)
    assert store.chat_turns(turn["thread_id"]) == [] and len(store.chat_turns(other["thread_id"])) == 1
    assert store.db.execute("SELECT id FROM chat_threads").fetchone()[0] == other["thread_id"]
    assert learning_evidence(store, original["version_id"]) == []
    assert store.active() == original and store.db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert store.db.execute("SELECT COUNT(*) FROM project_workspaces").fetchone()[0] == 0
    if reference:
        assert store.replay(run["id"])["run"]["output"] == "Answer"
        assert store.run_project(run["id"])["final_files"] == {"answer.py": "print(42)"}
        assert store.history()[0]["reflection_excluded"] == 1
    else:
        for table in ("runs", "workers", "events", "learning_exclusions", "run_projects"):
            assert store.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    with pytest.raises(ValueError, match="Unknown conversation"):
        ChatService(store.path).delete({"thread_id": turn["thread_id"]})
    store.close()


def test_delete_cannot_interrupt_running_work_or_cross_controller_lock(tmp_path):
    store = Store(tmp_path / "company.sqlite3")
    store.initialize(initial_manifest(Settings(api_key="test", model="test-model")))
    turn = store.start_chat_turn("Still running")
    with store.controller():
        with pytest.raises(RuntimeError, match="finish"):
            store.delete_chat_thread(turn["thread_id"])
        with pytest.raises(RuntimeError, match="Another controller"):
            ChatService(store.path).delete({"thread_id": turn["thread_id"]})
    assert len(store.chat_turns()) == 1
    store.close()
