import asyncio
import json
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from company.config import Settings
from company.organization import initial_manifest
from company.runtime import execute, requests_python_execution
from company.store import Store


@pytest.mark.parametrize("succeeds", [False, True])
def test_printed_tool_call_never_counts_as_execution(tmp_path, monkeypatch, succeeds):
    settings = Settings(api_key="test", model="test-model")
    store = Store(tmp_path / "company.sqlite3")
    store.initialize(initial_manifest(settings))
    attempts = []
    class Agent:
        async def ainvoke(self, inputs, config):
            attempts.append(inputs)
            if succeeds and len(attempts) == 2:
                trace, call = config["callbacks"][0], uuid4()
                trace.on_tool_start({"name": "python_execute"}, "", run_id=call, inputs={"code": "print(42)"})
                trace.on_tool_end(json.dumps({"status": "ok", "stdout": "42", "exit_code": 0}), run_id=call)
                return {"messages": [*inputs["messages"], AIMessage(content="The executed result is 42.")]}
            return {"messages": [*inputs["messages"], AIMessage(content='I will begin. ```json\n{"action":"read_file"}\n```')]}
    monkeypatch.setattr("company.runtime.build_agent", lambda *_: Agent())
    result = asyncio.run(execute(store, settings, task_id="work", split="learning", prompt="Implement and execute a Python scheduler.", expected=None, ungraded=True))
    assert result["run"]["status"] == ("completed" if succeeds else "incomplete")
    assert len(attempts) == (2 if succeeds else 3)
    assert result["run"]["grade"] is None
    assert any(event["kind"] == "execution_retry" for event in result["events"])
    if not succeeds:
        assert "no successful Python" in result["run"]["error"]
    store.close()


def test_explanations_do_not_require_code_execution():
    assert not requests_python_execution("Explain how to run Python code")
    assert not requests_python_execution("Write a three-step release checklist")
    assert requests_python_execution("Please run this Python code")
