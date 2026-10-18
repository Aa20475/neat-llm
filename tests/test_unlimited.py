import asyncio
import json
from typing import TypedDict
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from langgraph.graph import StateGraph, END

from company.config import Settings
from company.organization import initial_manifest, validate_manifest
from company.runtime import BudgetExceeded, execute
from company.store import Store
from company.validation import EvaluationBudget


def test_unlimited_run_exceeds_old_graph_call_tool_and_worker_caps(tmp_path, monkeypatch):
    settings = Settings(api_key="test", model="test-model")
    store = Store(tmp_path / "company.sqlite3")
    store.initialize(initial_manifest(settings))
    class State(TypedDict):
        steps: int
    class Agent:
        async def ainvoke(self, inputs, config):
            trace = config["callbacks"][0]
            async def step(state):
                call = uuid4()
                trace.on_chat_model_start({}, [], run_id=call)
                message = AIMessage(content="continue", usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})
                trace.on_llm_end(LLMResult(generations=[[ChatGeneration(message=message)]]), run_id=call)
                tool_id = uuid4()
                trace.on_tool_start({"name": "task"}, "", run_id=tool_id,
                                    inputs={"subagent_type": "general-purpose", "description": "A short check"})
                trace.on_tool_end("done", run_id=tool_id)
                return {"steps": state["steps"] + 1}
            graph = StateGraph(State)
            graph.add_node("step", step)
            graph.set_entry_point("step")
            graph.add_conditional_edges("step", lambda s: "step" if s["steps"] < 60 else END)
            result = await graph.compile().ainvoke({"steps": 0}, config=config)
            return {"messages": [AIMessage(content=str(result["steps"]))]}
    monkeypatch.setattr("company.runtime.build_agent", lambda *_: Agent())
    result = asyncio.run(execute(store, settings, task_id="long", split="smoke", prompt="work", expected=60))
    assert result["run"]["status"] == "completed" and result["run"]["grade"]["passed"]
    assert result["run"]["usage"]["model_calls"] == 60
    assert result["run"]["usage"]["tool_calls"] == 60
    assert result["run"]["usage"]["temporary_workers"] == 60
    store.close()


def test_unlimited_shared_evaluation_still_measures_usage():
    budget = EvaluationBudget()
    for _ in range(1000):
        budget.reserve()
    assert budget.used == 1000 and budget.limit is None and budget.deadline is None
    assert budget.request_timeout(45) == 45
    finite = EvaluationBudget(2, 10)
    finite.reserve()
    finite.reserve()
    with pytest.raises(BudgetExceeded):
        finite.reserve()


def test_operator_change_preserves_history_and_is_idempotent(tmp_path):
    store = Store(tmp_path / "company.sqlite3")
    manifest = initial_manifest(Settings(api_key="test", model="test-model"))
    manifest["limits"].update(model_calls=10, tool_calls=16, workers=3, wall_seconds=150)
    manifest["inference"]["max_tokens"] = 1024
    before = store.initialize(manifest)
    run = store.start_run("existing", "learning", "Original task")
    store.finish(run["id"], "budget_exceeded", None, None, {"model_calls": 10}, "model_calls")
    replay = store.replay(run["id"])
    with store.controller():
        after = store.remove_budgets()
        assert store.remove_budgets() == after
    assert after["generation"] == 1 and after["version_id"] != before["version_id"]
    assert after["manifest"]["inference"]["max_tokens"] is None
    assert after["manifest"]["limits"]["model_calls"] is None
    assert store.replay(run["id"]) == replay
    assert store.manifest(before["version_id"]) == manifest
    assert store.db.execute("SELECT COUNT(*) FROM activations").fetchone()[0] == 0
    actions = store.db.execute("SELECT * FROM actions WHERE kind='runtime_settings'").fetchall()
    assert len(actions) == 1 and json.loads(actions[0]["result"])["from_version"] == before["version_id"]
    store.close()


def test_operator_change_does_not_interrupt_active_work(tmp_path):
    store = Store(tmp_path / "company.sqlite3")
    before = store.initialize(initial_manifest(Settings(api_key="test", model="test-model")))
    store.start_run("active", "learning", "Still running")
    with pytest.raises(ValueError, match="finish"):
        store.remove_budgets()
    assert store.active() == before
    store.close()


@pytest.mark.parametrize("value", [0, -1, True, "unlimited"])
def test_manifest_rejects_malformed_optional_limits(value):
    manifest = initial_manifest(Settings(api_key="test", model="test-model"))
    manifest["limits"]["model_calls"] = value
    with pytest.raises(ValueError, match="limit"):
        validate_manifest(manifest)


@pytest.mark.parametrize('raw,expected', [(None, None), ('', None), ('unlimited', None), ('None', None), ('16384', 16384)])
def test_optional_response_cap_from_environment(monkeypatch, raw, expected):
    monkeypatch.setattr('company.config.load_dotenv', lambda *args, **kwargs: None)
    monkeypatch.setenv('CRUSOE_API_KEY', 'test')
    monkeypatch.setenv('CRUSOE_MODEL', 'test-model')
    monkeypatch.delenv('CRUSOE_MAX_TOKENS', raising=False)
    if raw is not None:
        monkeypatch.setenv('CRUSOE_MAX_TOKENS', raw)
    settings = Settings.load()
    assert settings.max_tokens == expected
    manifest = initial_manifest(settings)
    assert manifest['inference']['max_tokens'] == expected
    validate_manifest(manifest)


@pytest.mark.parametrize('value', [0, -1, True, 'unlimited', 1.5])
def test_invalid_response_caps_are_rejected(value):
    with pytest.raises(ValueError, match='token limit'):
        Settings(api_key='test', model='test-model', max_tokens=value)
    manifest = initial_manifest(Settings(api_key='test', model='test-model'))
    manifest['inference']['max_tokens'] = value
    with pytest.raises(ValueError, match='token limit'):
        validate_manifest(manifest)


@pytest.mark.parametrize('cap', [None, 16384])
def test_real_sdk_omits_unset_token_cap_from_wire_request(cap):
    import httpx
    from openai import OpenAI
    from company.responses import require_complete_response
    requests = []
    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        if cap is None:
            assert not {'max_tokens', 'max_completion_tokens', 'max_output_tokens'} & body.keys()
        else:
            assert body['max_completion_tokens'] == cap
        return httpx.Response(200, json={
            'id':'mock-response', 'object':'chat.completion', 'created':0, 'model':'test-model',
            'choices':[{'index':0, 'message':{'role':'assistant','content':'Complete answer'}, 'finish_reason':'stop'}],
            'usage':{'prompt_tokens':1, 'completion_tokens':9000, 'total_tokens':9001},
        })
    settings = Settings(api_key='test-only', model='test-model', max_tokens=cap)
    with OpenAI(api_key='test-only', base_url=settings.base_url, http_client=httpx.Client(transport=httpx.MockTransport(respond))) as client:
        model = settings.chat_model()
        model.client = client.chat.completions
        answer = model.invoke('Synthetic test: return a complete answer.')
    assert len(requests) == 1
    assert answer.usage_metadata['output_tokens'] == 9000
    require_complete_response(answer, max_tokens=cap)
