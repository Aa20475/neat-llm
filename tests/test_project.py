import asyncio
from copy import deepcopy
import json
from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from company.config import Settings
from company.organization import initial_manifest
from company.project import Project, project_tools
from company.project_runner import run_project, validate_files
from company.runtime import NoProgress, RunTrace, execute
from company.store import Store


def test_saved_modules_tests_generated_files_and_targeted_edits_survive_calls():
    async def check():
        project = Project()
        tools = project_tools(project)
        await tools['project_write'].ainvoke({'path': 'scheduler.py', 'content': 'def duration(start, finish):\n    return finish - start\n'})
        test = """import unittest
from pathlib import Path
from scheduler import duration
class ScheduleTests(unittest.TestCase):
    def test_duration(self): self.assertEqual(duration(1, 3), 2)
Path('result.txt').write_text('executed saved module')
unittest.main()
"""
        await tools['project_write'].ainvoke({'path': 'tests/test_scheduler.py', 'content': test})
        result = await tools['python_execute'].ainvoke({'file_path': 'tests/test_scheduler.py', 'script_args': ['-v']})
        assert result['status'] == 'ok', result
        assert 'Ran 1 test' in result['stderr']
        assert project.files['result.txt'] == 'executed saved module'
        read = await tools['project_read'].ainvoke({'path': '/work/result.txt'})
        assert 'executed saved module' in read['text']
        found = await tools['project_search'].ainvoke({'query': 'def duration'})
        assert found['matches'][0]['path'] == 'scheduler.py'
        await tools['project_edit'].ainvoke({'path': 'scheduler.py', 'old_text': 'finish - start', 'new_text': 'finish + start'})
        failed = await tools['python_execute'].ainvoke({'file_path': 'tests/test_scheduler.py'})
        assert failed['status'] == 'error' and 'AssertionError' in failed['stderr']
        assert 'tests/test_scheduler.py' in project.files
        await tools['project_edit'].ainvoke({'path': 'scheduler.py', 'old_text': 'finish + start', 'new_text': 'finish - start'})
        assert (await tools['python_execute'].ainvoke({'file_path': 'tests/test_scheduler.py'}))['status'] == 'ok'
        assert (await tools['project_delete'].ainvoke({'path': 'result.txt'}))['status'] == 'ok'
    asyncio.run(check())


def test_worker_copy_requires_explicit_merge_and_conflicts_are_atomic():
    async def check():
        parent = Project({'scheduler.py': 'original', 'tests.py': 'original tests'})
        child = parent.fork()
        tools, child_tools = project_tools(parent), project_tools(child)
        await child_tools['project_write'].ainvoke({'path': 'scheduler.py', 'content': 'worker change'})
        await child_tools['project_write'].ainvoke({'path': 'tests.py', 'content': 'worker tests'})
        assert parent.files['scheduler.py'] == 'original'
        assert (await tools['project_merge'].ainvoke({'worker_id': child.branch_id, 'paths': ['tests.py']}))['status'] == 'error'
        child.status = 'completed'
        await tools['project_write'].ainvoke({'path': 'scheduler.py', 'content': 'parent change'})
        before = dict(parent.files)
        conflict = await tools['project_merge'].ainvoke({'worker_id': child.branch_id, 'paths': ['tests.py', 'scheduler.py']})
        assert conflict['status'] == 'error' and parent.files == before
        diff = await tools['project_diff'].ainvoke({'worker_id': child.branch_id})
        assert '+worker change' in diff['diff']
        assert (await tools['project_merge'].ainvoke({'worker_id': child.branch_id, 'paths': ['tests.py']}))['status'] == 'ok'
        assert parent.files == {'scheduler.py': 'parent change', 'tests.py': 'worker tests'}
        assert (await child_tools['project_merge'].ainvoke({'worker_id': child.branch_id, 'paths': ['tests.py']}))['status'] == 'error'
    asyncio.run(check())


def test_project_isolation_export_validation_and_fresh_variables(tmp_path, monkeypatch):
    secret = tmp_path / 'controller-secret'
    secret.write_text('must stay private')
    monkeypatch.setenv('CRUSOE_API_KEY', 'not-for-sandbox')
    async def check():
        project = Project()
        tools = project_tools(project)
        script = f"""import os, pathlib, socket
assert not pathlib.Path({str(secret)!r}).exists()
assert not pathlib.Path({str(Path.cwd())!r}).exists()
assert 'CRUSOE_API_KEY' not in os.environ
try:
    socket.create_connection(('1.1.1.1', 80), timeout=0.1)
except OSError: pass
else: raise AssertionError('network available')
try: os.fork()
except OSError: pass
else: raise AssertionError('fork available')
value = 42
pathlib.Path('answer.txt').write_text(str(value))
print('isolated')
"""
        result = await tools['python_execute'].ainvoke({'code': script})
        assert result['status'] == 'ok', result
        later = await tools['python_execute'].ainvoke({'code': "from pathlib import Path\nassert 'value' not in globals()\nprint(Path('answer.txt').read_text())"})
        assert later['stdout'] == '42\n'
        invalid = await tools['python_execute'].ainvoke({'code': "import os\nos.symlink('/etc/passwd', 'escape')"})
        assert invalid['status'] == 'error' and 'regular files' in invalid['persistence_error']
        assert 'escape' not in project.files
        assert secret.read_text() == 'must stay private'
    asyncio.run(check())


@pytest.mark.parametrize('path', ['../company.sqlite3', '/etc/passwd', '/organization/prompt.md', 'a/../b', 'a//b', 'a\\b'])
def test_project_tools_reject_host_paths(path):
    project = Project()
    result = asyncio.run(project_tools(project)['project_write'].ainvoke({'path': path, 'content': 'no'}))
    assert result['status'] == 'error' and project.files == {}


def test_directory_tools_accept_conventional_project_roots_and_explain_missing_files():
    async def check():
        tools = project_tools(Project({'tests/test_example.py': 'assert True'}))
        for prefix in ('', '.', './', '/work', '/work/'):
            listing = await tools['project_list'].ainvoke({'prefix': prefix})
            assert listing['status'] == 'ok' and listing['files'][0]['path'] == 'tests/test_example.py'
            search = await tools['project_search'].ainvoke({'query': 'assert', 'prefix': prefix})
            assert search['matches'][0]['path'] == 'tests/test_example.py'
        assert 'directory' in (await tools['project_read'].ainvoke({'path': 'tests'}))['error']
        assert 'project_write' in (await tools['project_read'].ainvoke({'path': 'missing.py'}))['error']
    asyncio.run(check())


def test_project_timeout_and_cancellation_leave_saved_input_unchanged(monkeypatch):
    from company.python_runner import POLICY
    monkeypatch.setitem(POLICY, 'wall_seconds', 0.3)
    async def check():
        files = {'slow.py': "import time\ntime.sleep(60)"}
        result = await run_project(files, 'slow.py')
        assert result['status'] == 'timed_out' and 'files' not in result
        task = asyncio.create_task(run_project(files, 'slow.py'))
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert files == {'slow.py': "import time\ntime.sleep(60)"}
    asyncio.run(check())


def test_workspace_continues_after_restart_but_private_and_new_threads_are_isolated(tmp_path):
    path = tmp_path / 'company.sqlite3'
    store = Store(path)
    store.initialize(initial_manifest(Settings(api_key='test', model='test-model')))
    turn = store.start_chat_turn('Create module')
    run = store.start_run('one', 'learning', 'Create module')
    store.link_chat_run(turn['id'], run['id'])
    assert store.start_project(run['id'], 'learning', turn['id']) == {}
    store.save_project(run['id'], {'module.py': 'value = 42'}, {})
    store.finish(run['id'], 'completed', 'Done', None, {})
    store.finish_chat_turn(turn['id'], 'completed')
    store.close()
    store = Store(path)
    next_turn = store.start_chat_turn('Test it', turn['thread_id'])
    next_run = store.start_run('two', 'learning', 'Test it')
    assert store.start_project(next_run['id'], 'learning', next_turn['id']) == {'module.py': 'value = 42'}
    assert store.run_project(run['id'])['initial_files'] == {}
    private = store.start_run('private', 'chat', 'Private task')
    assert store.start_project(private['id'], 'chat', next_turn['id']) == {}
    other_turn = store.start_chat_turn('Independent task')
    other = store.start_run('other', 'learning', 'Independent task')
    assert store.start_project(other['id'], 'learning', other_turn['id']) == {}
    store.close()


def test_repeated_failure_stops_without_a_call_budget_and_edits_allow_progress(tmp_path, monkeypatch):
    store = Store(tmp_path / 'company.sqlite3')
    settings = Settings(api_key='test', model='test-model')
    store.initialize(initial_manifest(settings))
    class Agent:
        async def ainvoke(self, inputs, config):
            trace = config['callbacks'][0]
            for i in range(3):
                call = uuid4()
                trace.on_tool_start({'name': 'python_execute'}, '', run_id=call, inputs={'file_path': 'tests.py'})
                trace.on_tool_end({'status': 'error', 'stderr': 'NameError: scheduler', 'workspace_digest': 'unchanged'}, run_id=call)
            trace.on_chat_model_start({}, [], run_id=uuid4())
            raise AssertionError('Another model call must not start')
    monkeypatch.setattr('company.runtime.build_agent', lambda *_: Agent())
    result = asyncio.run(execute(store, settings, task_id='stuck', split='learning', prompt='Run Python tests', expected=None, ungraded=True))
    assert result['run']['status'] == 'incomplete' and 'three times' in result['run']['error']
    assert any(e['kind'] == 'no_progress' for e in result['events'])
    run = store.start_run('progress', 'learning', 'Fix tests')
    trace = RunTrace(store, run)
    for i in range(5):
        call = uuid4()
        trace.on_tool_start({'name': 'python_execute'}, '', run_id=call, inputs={'file_path': 'tests.py'})
        trace.on_tool_end({'status': 'error', 'stderr': 'AssertionError', 'workspace_digest': str(i)}, run_id=call)
    assert trace.stall_reason is None
    store.close()


def test_workspace_upgrade_preserves_old_versions_and_unlimited_configuration(tmp_path):
    store = Store(tmp_path / 'company.sqlite3')
    old = initial_manifest(Settings(api_key='test', model='test-model'))
    old['tools'].update(filesystem='ephemeral_state', source_sha256='historical-tool-digest',
                        names=['decimal_product', 'decimal_sum', 'python_execute'])
    old['label'] = 'v0-unlimited'
    before = store.initialize(old)
    run = store.start_run('historical', 'learning', 'Old task')
    store.finish(run['id'], 'interrupted', None, None, {})
    with store.controller():
        after = store.enable_project_workspace()
        assert store.enable_project_workspace() == after
    assert after['generation'] == 1 and after['manifest']['limits'] == old['limits']
    assert after['manifest']['topology'] == old['topology']
    assert store.manifest(before['version_id']) == old
    assert store.replay(run['id'])['organization'] == old
    assert 'project_write' in after['manifest']['tools']['names']
    assert store.db.execute('SELECT COUNT(*) FROM activations').fetchone()[0] == 0
    store.close()


def test_real_sdk_subagent_gets_project_copy_and_parent_can_review_merge_and_execute(tmp_path, monkeypatch):
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langchain_core.messages import ToolMessage
    import re
    calls = []
    class ScriptedModel(BaseChatModel):
        @property
        def _llm_type(self): return 'workspace-integration-fixture'
        def bind_tools(self, tools, **kwargs): return self
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            step = len(calls)
            calls.append(messages)
            planned = [
                ('project_write', {'path': 'helper.py', 'content': "value = 1\nprint(value)\n"}),
                ('task', {'subagent_type': 'general-purpose', 'description': 'Change helper.py value from 1 to 2'}),
                ('project_read', {'path': 'helper.py'}),
                ('project_edit', {'path': 'helper.py', 'old_text': 'value = 1', 'new_text': 'value = 2'}),
                None, ('project_diff', {}), ('project_merge', {}),
                ('python_execute', {'file_path': 'helper.py'}), None,
            ]
            assert step < len(planned), 'Unexpected additional model call'
            action = planned[step]
            if step == 3:
                assert 'value = 1' in messages[-1].content
            if step in (5, 6):
                saved = store.run_project(store.history()[0]['id'])
                assert saved['final_files']['helper.py'].startswith('value = 1')
                task_result = next(m.content for m in messages if isinstance(m, ToolMessage) and m.name == 'task')
                branch_id = re.search(r'Workspace ID: (worker-[a-f0-9]+)', task_result)[1]
                action = (action[0], {'worker_id': branch_id, **({'paths': ['helper.py']} if step == 6 else {})})
            if step == 8:
                assert json.loads(messages[-1].content)['stdout'] == '2\n'
            message = AIMessage(content='Changed the file' if step == 4 else 'Executed result: 2' if not action else '',
                                tool_calls=[{'name': action[0], 'args': action[1], 'id': uuid4().hex}] if action else [],
                                usage_metadata={'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2})
            return ChatResult(generations=[ChatGeneration(message=message)])
    settings = Settings(api_key='test', model='test-model')
    store = Store(tmp_path / 'company.sqlite3')
    store.initialize(initial_manifest(settings))
    monkeypatch.setattr(Settings, 'chat_model', lambda _: ScriptedModel())
    monkeypatch.setattr('company.runtime.InMemoryRateLimiter', lambda **kwargs: None)
    result = asyncio.run(execute(store, settings, task_id='delegate', split='learning', prompt='Implement and execute a delegated file change', expected=None, ungraded=True))
    assert result['run']['status'] == 'completed', result['run']
    assert len(calls) == 9
    assert result['project']['final_files']['helper.py'].startswith('value = 2')
    assert result['workers'][1]['temporary'] == 1 and result['workers'][1]['status'] == 'completed'
    child_tools = [e for e in result['events'] if e['kind'] == 'tool_started' and e['worker_id'] == result['workers'][1]['id']]
    assert {e['payload']['name'] for e in child_tools} == {'project_read', 'project_edit'}
    store.close()
