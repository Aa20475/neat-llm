import asyncio
from copy import deepcopy
from uuid import uuid4

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from company.config import Settings
from company.organization import initial_manifest
from company.responses import IncompleteResponse, require_complete_response
from company.runtime import execute
from company.store import Store


@pytest.mark.parametrize('model', ['zai-org/GLM-5.3', 'zai/GLM-5.3-Flash'])
def test_glm_settings_keep_reasoning_parser_enabled(model):
    settings = Settings(api_key='test', model=model)
    assert settings.chat_model().extra_body == {'chat_template_kwargs': {'enable_thinking': True, 'reasoning_effort': 'low'}}
    manifest = initial_manifest(settings)
    assert manifest['inference']['enable_thinking'] is True
    assert manifest['inference']['reasoning_effort'] == 'low'
    legacy = Settings(api_key='test', model=model, enable_thinking=False)
    assert legacy.chat_model().extra_body == {'chat_template_kwargs': {'enable_thinking': False}}
    assert Settings(api_key='test', model='other').enable_thinking is False


@pytest.mark.parametrize('reason', ['length', 'max_tokens', 'content_filter'])
def test_rejects_partial_response_even_if_it_looks_like_valid_json(reason):
    with pytest.raises(IncompleteResponse):
        require_complete_response(AIMessage(content='{"winner":"B","reason":"better"}', response_metadata={'finish_reason': reason}))


def test_no_content_is_valid_only_with_a_native_tool_call():
    with pytest.raises(IncompleteResponse, match='no final answer'):
        require_complete_response(AIMessage(content=''))
    require_complete_response(AIMessage(content='', tool_calls=[{'name': 'project_list', 'args': {}, 'id': 'tool'}]))


def test_missing_finish_reason_with_exhausted_tokens_is_incomplete():
    message = AIMessage(content='partial', usage_metadata={'input_tokens': 1, 'output_tokens': 4096, 'total_tokens': 4097})
    with pytest.raises(IncompleteResponse, match='token limit'):
        require_complete_response(message, max_tokens=4096)
    message.response_metadata['finish_reason'] = 'stop'
    require_complete_response(message, max_tokens=4096)


def test_reasoning_upgrade_preserves_old_version_and_work(tmp_path):
    settings = Settings(api_key='test', model='zai-org/GLM-5.3', enable_thinking=False)
    store = Store(tmp_path / 'test.sqlite3')
    original = store.initialize(initial_manifest(settings))
    old_manifest = deepcopy(original['manifest'])
    run = store.start_run('task', 'learning', 'input')
    with store.controller(), pytest.raises(ValueError, match='Wait'):
        store.upgrade_reasoning_policy()
    store.finish(run['id'], 'completed', 'answer', None, {})
    with store.controller():
        active = store.upgrade_reasoning_policy()
        assert store.upgrade_reasoning_policy() == active
    assert active['generation'] == 1
    assert active['manifest']['inference']['enable_thinking'] is True
    assert active['manifest']['inference']['reasoning_effort'] == 'low'
    assert store.manifest(original['version_id']) == old_manifest
    assert active['manifest']['limits'] == old_manifest['limits']
    assert active['manifest']['topology'] == old_manifest['topology']
    assert store.replay(run['id'])['run']['output'] == 'answer'
    assert store.db.execute('SELECT COUNT(*) FROM actions').fetchone()[0] == 1
    store.close()


@pytest.mark.parametrize('child', [False, True])
def test_real_sdk_does_not_execute_truncated_tools_or_accept_worker_report(tmp_path, monkeypatch, child):
    calls = []
    class Model(BaseChatModel):
        @property
        def _llm_type(self): return 'truncated-fixture'
        def bind_tools(self, tools, **kwargs): return self
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            step = len(calls)
            calls.append(messages)
            assert step <= int(child), 'No continuation should consume a partial reply'
            if child and step == 0:
                message = AIMessage(content='', tool_calls=[{'name':'task', 'args':{'subagent_type':'general-purpose','description':'Review this project'},'id':uuid4().hex}])
                reason = 'tool_calls'
            else:
                message = AIMessage(content='An unfinished worker report' if child else '', tool_calls=[] if child else [
                    {'name':'project_write','args':{'path':'unsafe.txt','content':'partial tool arguments'},'id':uuid4().hex}])
                reason = 'length'
            message.usage_metadata = {'input_tokens':1,'output_tokens':2,'total_tokens':3}
            return ChatResult(generations=[ChatGeneration(message=message, generation_info={'finish_reason':reason})])
    settings = Settings(api_key='test', model='test-model')
    store = Store(tmp_path / 'company.sqlite3')
    store.initialize(initial_manifest(settings))
    monkeypatch.setattr(Settings, 'chat_model', lambda _: Model())
    monkeypatch.setattr('company.runtime.InMemoryRateLimiter', lambda **kwargs: None)
    result = asyncio.run(execute(store, settings, task_id='partial', split='learning', prompt='Review', expected=None, ungraded=True))
    assert result['run']['status'] == 'incomplete', result['run']
    assert 'token limit' in result['run']['output']
    assert result['project']['final_files'] == {}
    finished = [e for e in result['events'] if e['kind'] == 'model_finished']
    assert finished[-1]['payload']['finish_reason'] == 'length'
    assert finished[-1]['payload']['trace_output_truncated'] is False
    if child:
        assert result['workers'][1]['status'] == 'incomplete'
        assert next(iter(result['project']['branches'].values()))['status'] == 'incomplete'
    store.close()


def test_complete_final_answer_is_not_clipped_to_trace_limit(tmp_path, monkeypatch):
    settings = Settings(api_key='secret-value', model='test-model')
    store = Store(tmp_path / 'test.sqlite3')
    store.initialize(initial_manifest(settings))
    output = 'x' * 13000 + settings.api_key + ' THE END'
    class Agent:
        async def ainvoke(self, inputs, config):
            return {'messages':[AIMessage(content=output, response_metadata={'finish_reason':'stop'})]}
    monkeypatch.setattr('company.runtime.build_agent', lambda *_: Agent())
    result = asyncio.run(execute(store, settings, task_id='long', split='chat', prompt='Return long text', expected=None, ungraded=True))
    assert result['run']['status'] == 'completed'
    assert result['run']['output'] == output.replace(settings.api_key, '[REDACTED]')
    store.close()
