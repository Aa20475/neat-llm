import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import sqlite3
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from company.agent_tools import decimal_product, decimal_sum
from company.config import Settings
from company.organization import digest, initial_manifest, validate_manifest, worker_files
from company.runtime import BudgetExceeded, RunTrace, build_agent, execute
from company.store import Store


@pytest.fixture
def state(tmp_path):
    settings = Settings(api_key="test-only-secret", model="test-model")
    store = Store(tmp_path / "test.sqlite3")
    manifest = initial_manifest(settings)
    store.initialize(manifest)
    yield store, settings, manifest
    store.close()


def test_restart_preserves_configuration_and_pinned_run(state):
    store, _, manifest = state
    run = store.start_run("task", "learning", "input only")
    changed = deepcopy(manifest)
    changed["prompts"]["generalist"] = "A later proposal"
    # Initialization with changed code/config must not silently replace v0.
    assert store.initialize(changed)["version_id"] == digest(manifest)
    reopened = Store(store.path)
    try:
        assert reopened.active()["version_id"] == run["version_id"]
        assert reopened.replay(run["id"])["organization"] == manifest
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            reopened.db.execute("UPDATE versions SET manifest='{}'")
        reopened.db.rollback()
        with store.controller():
            with pytest.raises(RuntimeError, match="Another controller"):
                with reopened.controller():
                    pass
    finally:
        reopened.close()


def test_recovery_preserves_events_and_marks_stale_run(state):
    store, _, _ = state
    run = store.start_run("task", "learning", "input")
    store.event(run["id"], "example", run["id"] + ":root", {"evidence": 1})
    with store.controller():
        store.recover_interrupted()
    replay = store.replay(run["id"])
    assert replay["run"]["status"] == "interrupted"
    assert replay["run"]["grade"] is None
    assert replay["run"]["usage"]["complete"] is False
    assert [event["seq"] for event in replay["events"]] == [1, 2, 3]
    assert replay["workers"][0]["status"] == "interrupted"


def test_child_trace_parentage_and_shared_budget(state):
    store, settings, _ = state
    run = store.start_run("task", "smoke", "input")
    trace = RunTrace(store, run, settings.api_key)
    trace.limits = {**trace.limits, "model_calls": 2}
    root_call, task_call, child_chain, child_call = [uuid4() for _ in range(4)]
    trace.on_chat_model_start({}, [], run_id=root_call)
    trace.on_tool_start({"name": "task"}, "", run_id=task_call,
                        inputs={"subagent_type": "general-purpose", "description": "multiply"})
    trace.on_chain_start({}, {}, run_id=child_chain, parent_run_id=task_call)
    trace.on_chat_model_start({}, [], run_id=child_call, parent_run_id=child_chain)
    message = AIMessage(content="42", usage_metadata={"input_tokens": 12, "output_tokens": 2, "total_tokens": 14})
    trace.on_llm_end(LLMResult(generations=[[ChatGeneration(message=message)]]), run_id=child_call)
    trace.on_tool_end("42", run_id=task_call)
    with pytest.raises(BudgetExceeded, match="model_calls"):
        trace.on_chat_model_start({}, [], run_id=uuid4(), parent_run_id=child_chain)
    replay = store.replay(run["id"])
    child = replay["workers"][1]
    assert child["temporary"] == 1 and child["parent_id"] == trace.root
    assert child["status"] == "completed"
    event = next(event for event in replay["events"] if event["kind"] == "model_finished")
    assert event["worker_id"] == child["id"]
    assert trace.usage()["input_tokens"] == 12
    assert not trace.usage()["complete"]  # Root never completed.
    assert trace.clean({"secret": settings.api_key}) == {"secret": "[REDACTED]"}


def test_budget_reservation_is_atomic_across_parallel_children(state):
    store, _, _ = state
    trace = RunTrace(store, store.start_run("task", "smoke", "input"))
    trace.limits = {**trace.limits, "model_calls": 3}
    def reserve(_):
        try:
            trace.on_chat_model_start({}, [], run_id=uuid4())
            return True
        except BudgetExceeded:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reserve, range(20))) == 3
    assert trace.calls == 3


def test_depth_and_tool_allowlist_are_enforced(state):
    store, _, _ = state
    trace = RunTrace(store, store.start_run("task", "smoke", "input"))
    task_call = uuid4()
    trace.on_tool_start({"name": "task"}, "", run_id=task_call,
                        inputs={"subagent_type": "general-purpose", "description": "child"})
    with pytest.raises(BudgetExceeded, match="worker_depth"):
        trace.on_tool_start({"name": "task"}, "", run_id=uuid4(), parent_run_id=task_call,
                            inputs={"subagent_type": "general-purpose"})
    separate = RunTrace(store, store.start_run("other", "smoke", "input"))
    with pytest.raises(BudgetExceeded, match="unapproved_tool"):
        separate.on_tool_start({"name": "execute"}, "", run_id=uuid4())


def test_runtime_grades_independently_and_never_sends_expected(monkeypatch, state):
    store, settings, _ = state
    class Agent:
        async def ainvoke(self, inputs, config):
            assert inputs["messages"][0].content == "Only the user input"
            return {"messages": [AIMessage(content='{"wrong": true}')]}
    monkeypatch.setattr("company.runtime.build_agent", lambda *_: Agent())
    result = asyncio.run(execute(store, settings, task_id="test", split="learning",
                                 prompt="Only the user input", expected={"secret_answer": 42}))
    assert result["run"]["status"] == "completed"
    assert result["run"]["grade"] == {"passed": False, "reason": "output_mismatch"}
    assert result["events"][-1]["kind"] == "run_finished"


def test_runtime_records_failure_without_sensitive_exception_text(monkeypatch, state):
    store, settings, _ = state
    class Agent:
        async def ainvoke(self, *args, **kwargs):
            raise RuntimeError(settings.api_key)
    monkeypatch.setattr("company.runtime.build_agent", lambda *_: Agent())
    result = asyncio.run(execute(store, settings, task_id="test", split="smoke", prompt="input", expected=42))
    assert result["run"]["status"] == "failed"
    assert result["run"]["error"] == "RuntimeError"
    assert settings.api_key not in str(result)


def test_authentication_failure_is_actionable_and_preserves_redacted_trace(monkeypatch, state):
    store, settings, _ = state

    class AuthenticationFailure(Exception):
        status_code = 401

    class Agent:
        async def ainvoke(self, *args, **kwargs):
            raise AuthenticationFailure(f"Rejected credential {settings.api_key}")

    monkeypatch.setattr("company.runtime.build_agent", lambda *_: Agent())
    result = asyncio.run(execute(store, settings, task_id="chat", split="chat", prompt="Hello", expected=None, ungraded=True))
    assert result["run"]["status"] == "failed"
    assert "HTTP 401" in result["run"]["error"]
    assert "CRUSOE_API_KEY" in result["run"]["error"]
    assert result["run"]["output"] is None
    assert settings.api_key not in str(result)
    event = next(event for event in result["events"] if event["kind"] == "run_error")
    assert event["payload"]["http_status"] == 401
    assert event["payload"]["error_type"] == "AuthenticationFailure"
    assert "[REDACTED]" in event["payload"]["detail"]


def test_tool_and_configuration_integrity(state):
    _, _, manifest = state
    assert decimal_product.invoke({"a": "3", "b": "0.335"}) == "1.01"
    assert decimal_sum.invoke({"values": ["1.01", "2.68"]}) == "3.69"
    assert decimal_sum.invoke({"values": []}) == "0.00"
    for number in ("NaN", "Infinity", "1e1000000"):
        with pytest.raises(ValueError):
            decimal_product.invoke({"a": number, "b": "1"})
    validate_manifest(manifest)
    changed = deepcopy(manifest)
    changed["tools"]["source_sha256"] = "different"
    with pytest.raises(ValueError, match="implementation changed"):
        validate_manifest(changed)


def test_saved_layout_compiles_with_installed_sdk(state):
    _, settings, manifest = state
    assert build_agent(manifest, settings) is not None


def test_worker_tree_contains_only_bound_configuration(state):
    _, settings, original = state
    manifest = deepcopy(original)
    manifest["skills"] = {"formatting": "Return valid JSON", "other-role": "Do not expose"}
    manifest["task_memory"] = {"project": "Preserve leading zeros"}
    manifest["topology"]["roles"][0].update(skills=["formatting"], memory=["project"])
    files = worker_files(manifest)
    assert set(files) == {"/organization/README.md", "/organization/prompt.md", "/organization/skills/formatting.md", "/organization/memory/project.md"}
    assert "Do not expose" not in str(files)
    assert settings.api_key not in str(files)
