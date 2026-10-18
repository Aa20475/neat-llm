import asyncio
import json
from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage

from company.config import Settings
from company.organization import canonical_json, initial_manifest, role_prompt
from company.reflection import REFLECTOR_POLICY, learning_evidence, propose, reflection_context
from company.store import Store


def record_solution(store, split='learning', marker='LEARNING_SOURCE'):
    run = store.start_run('solution-' + split, split, 'Implement immutable snapshots with atomic updates')
    root, worker = run['id'] + ':root', run['id'] + ':worker:1'
    store.start_project(run['id'], split, initial_files={})
    files = {'engine.py':f'# {marker}\nMISSING = object()\ndef merge():\n    return MISSING\n',
             'test_engine.py':'def test_aliasing():\n    assert True\n',
             'test_review.py':'def test_empty_vs_absent():\n    assert True\n'}
    store.save_project(run['id'], files, {})
    for i in range(6):
        store.event(run['id'], 'tool_started', root, {'name':'python_execute','call_id':str(i),'arguments':{'file_path':'test_engine.py'}})
        store.event(run['id'], 'tool_finished', root, {'name':'python_execute','call_id':str(i),'output':json.dumps({'status':'error','exit_code':1,'stderr':f'failure-{i}: aliasing detected'})})
        store.event(run['id'], 'tool_started', root, {'name':'project_edit','call_id':f'edit-{i}','arguments':{'path':'engine.py','old_text':f'old-{i}','new_text':f'new-{i}'}})
        store.event(run['id'], 'tool_finished', root, {'name':'project_edit','call_id':f'edit-{i}','output':{'status':'ok'}})
    store.worker_start(run['id'], worker, root, 'general-purpose', True, 'Review snapshot edge cases')
    store.event(run['id'], 'model_finished', worker, {'output':'Added empty versus absent tests. WORKER_REPORT','tool_calls':[]})
    store.worker_finish(worker, 'completed')
    for i in range(4):
        store.event(run['id'], 'tool_finished', root, {'name':'python_execute','call_id':f'pass-{i}','output':{'status':'ok','exit_code':0,'stdout':'OK'}})
    store.finish(run['id'], 'completed', 'Final tests passed; source remains ungraded.', None, {})
    return run


def test_solution_evidence_keeps_early_failures_code_reviews_and_coverage(tmp_path):
    store = Store(tmp_path / 'company.sqlite3')
    active = store.initialize(initial_manifest(Settings(api_key='test', model='test-model')))
    source = record_solution(store)
    for split in ('chat','review','validation','heldout'):
        record_solution(store, split, marker='FORBIDDEN_' + split)
    evidence = learning_evidence(store, active['version_id'])
    assert len(evidence) == 1 and evidence[0]['run_id'] == source['id']
    row = evidence[0]
    assert row['grade'] is None
    assert row['development_failures'][0]['excerpt'].startswith('failure-0')
    assert row['development_failures'][-1]['excerpt'].startswith('failure-5')
    assert len(row['development_failures']) == 3
    assert row['repair_edits'][0]['before'] == 'old-0'
    assert row['repair_edits'][-1]['after'] == 'new-5'
    assert row['evidence_limits']['failed_tool_calls'] == 6
    assert all('failure-' not in event['excerpt'] for event in row['python_trace'])
    assert 'LEARNING_SOURCE' in canonical_json(row['project_artifacts'])
    assert 'test_aliasing' in canonical_json(row['test_inventory'])
    assert 'WORKER_REPORT' in row['worker_reports'][0]['excerpt']
    assert 'not an independent' in row['worker_reports'][0]['source']
    replay = store.replay(source['id'])
    assert [{key: event[key] for key in saved} for event, saved in zip(row['event_trace'], replay['events'])] == replay['events']
    assert row['trace_coverage']['events_included'] == len(replay['events'])
    assert all(f'failure-{i}' in canonical_json(row['event_trace']) for i in range(6))
    assert 'FORBIDDEN' not in canonical_json(evidence)
    store.close()


def test_artifact_excerpts_are_bounded_and_disclose_omissions(tmp_path):
    store = Store(tmp_path / 'company.sqlite3')
    active = store.initialize(initial_manifest(Settings(api_key='test', model='test-model')))
    run = record_solution(store)
    store.save_project(run['id'], {f'module{i}.py':'# HEAD\n'+'x'*10000+'\n# TAIL' for i in range(20)}, {})
    row = learning_evidence(store, active['version_id'])[0]
    assert len(row['project_artifacts']) == 2
    assert row['evidence_limits']['files_available'] == 20
    for artifact in row['project_artifacts']:
        assert len(artifact['excerpt']) <= 1600
        assert artifact['excerpt'].startswith('# HEAD') and artifact['excerpt'].endswith('# TAIL')
        assert artifact['excerpt_truncated'] is True
    store.close()


def test_context_keeps_every_selected_trace_even_above_old_character_limit():
    evidence = [{'run_id':str(i),'event_trace':[{'payload':{'output':'x'*10000}}], 'workers':[]} for i in range(6)]
    memories = [{'id':'memory','lesson':'A previous no_change is only historical evidence'}]
    originals = deepcopy((evidence, memories))
    context = reflection_context({'label':'v0'}, evidence, memories)
    assert len(canonical_json(context)) > 48000
    assert context['learning_evidence'] == evidence
    assert context['retrieval']['runs_omitted'] == 0
    assert context['retrieval']['events_included'] == 6
    assert context['reflection_memory'] == memories
    assert (evidence, memories) == originals


def test_trace_attributes_every_worker_and_keeps_full_assignments(tmp_path):
    store = Store(tmp_path / 'company.sqlite3')
    active = store.initialize(initial_manifest(Settings(api_key='test', model='test-model')))
    task = 'Task requirements ' + 'x'*6000 + ' TASK_END'
    run = store.start_run('many-workers', 'learning', task)
    root = run['id'] + ':root'
    assignment = 'Review invariants ' + 'x'*2000 + ' ASSIGNMENT_END'
    for i in range(1, 10):
        worker = f"{run['id']}:worker:{i}"
        store.worker_start(run['id'], worker, root, 'general-purpose', True, assignment)
        store.event(run['id'], 'model_finished', worker, {'output':f'worker-{i}-review', 'tool_calls':[]})
        store.worker_finish(worker, 'completed')
    specialist = run['id'] + ':worker:10'
    store.worker_start(run['id'], specialist, root, 'checker', False, 'Check the result')
    store.event(run['id'], 'model_finished', specialist, {'output':'specialist-review', 'tool_calls':[]})
    store.event(run['id'], 'independent_check', None, {'passed':False, 'finding':'controller finding'})
    store.event(run['id'], 'legacy_event', 'missing-worker', {'detail':'unknown attribution'})
    output = 'Final answer ' + 'y'*4000 + ' ANSWER_END'
    store.finish(run['id'], 'completed', output, None, {})
    row = learning_evidence(store, active['version_id'])[0]
    assert row['task'] == task and row['output'] == output
    assert len(row['workers']) == 11  # No former eight-worker cutoff.
    assert row['workers'][9]['task'] == assignment
    events = row['event_trace']
    assert events[0]['worker_label'] == 'Generalist'
    assert events[9]['worker_label'] == 'Worker 9 · general-purpose'
    assert events[9]['worker_role'] == 'general-purpose' and events[9]['worker_temporary'] == 1
    assert events[9]['parent_worker_id'] == root
    assert events[10]['worker_label'] == 'Worker 10 · checker' and events[10]['worker_temporary'] == 0
    assert events[11]['worker_label'] == 'Controller' and events[11]['worker_role'] is None
    assert events[12]['worker_label'] == 'Unknown worker (missing-worker)'
    assert row['trace_coverage']['events_omitted'] == 0
    store.close()


@pytest.mark.parametrize('provider_error', [False, True])
def test_large_full_trace_reaches_model_redacted_and_never_falls_back_to_excerpts(tmp_path, monkeypatch, provider_error):
    settings = Settings(api_key='trace-test-secret', model='test-model')
    store = Store(tmp_path / 'company.sqlite3')
    active = store.initialize(initial_manifest(settings))
    run = store.start_run('large-trace', 'learning', 'Review all events')
    payload = {'name':'project_write', 'call_id':'full-call', 'arguments':{
        'path':'large.py', 'content':'BEGIN ' + 'x'*50000 + settings.api_key + ' END'}}
    store.event(run['id'], 'tool_started', run['id'] + ':root', payload)
    store.finish(run['id'], 'completed', 'Complete', None, {})
    seen = []
    class Reflector:
        async def ainvoke(self, messages, **kwargs):
            seen.append(messages[1].content)
            assert len(seen[-1]) > 48000
            assert settings.api_key not in seen[-1]
            context = json.loads(seen[-1])
            events = context['learning_evidence'][0]['event_trace']
            assert len(events) == 3
            assert events[1]['payload'] == json.loads(json.dumps(payload).replace(settings.api_key, '[REDACTED]'))
            assert events[1]['worker_label'] == 'Generalist'
            if provider_error:
                raise RuntimeError('Provider context window exceeded')
            return AIMessage(content='{"decision":{"no_change":true,"reason":"Fixture only"}}',
                             usage_metadata={'input_tokens':15000,'output_tokens':10,'total_tokens':15010})
    monkeypatch.setattr(Settings, 'chat_model', lambda _: Reflector())
    result = asyncio.run(propose(store, settings))
    assert result['status'] == ('failed' if provider_error else 'no_change')
    assert len(seen) == 1  # Never retry with missing evidence on a provider error.
    assert result['usage']['context_characters'] == len(seen[0])
    saved = json.loads(store.db.execute('SELECT response FROM reflections WHERE id=?', (result['reflection_id'],)).fetchone()[0])
    assert saved['reflector']['retrieval']['events_included'] == 3
    assert store.active() == active
    assert store.db.execute('SELECT COUNT(*) FROM proposals').fetchone()[0] == 0
    store.close()


def test_successful_solution_can_propose_bound_skill_and_scoped_memory_without_activation(tmp_path, monkeypatch):
    settings = Settings(api_key='test-secret', model='test-model')
    store = Store(tmp_path / 'company.sqlite3')
    active = store.initialize(initial_manifest(settings))
    run = record_solution(store)
    previous = store.start_reflection([run['id']], [])
    store.finish_reflection(previous['id'], 'no_change', {}, {'reason':'All tests passed'})
    store.remember(previous['id'], None, 'no_change', 'All tests passed', {'run_ids':[run['id']]})
    class Reflector:
        async def ainvoke(self, messages, **kwargs):
            context = json.loads(messages[1].content)
            item = context['learning_evidence'][0]
            assert item['development_failures'] and item['project_artifacts']
            assert context['reflection_memory'][0]['outcome'] == 'no_change'
            return AIMessage(content=json.dumps({'decision':{
                'title':'Retain atomic-update methods',
                'rationale':f"Run {run['id']} repaired aliasing in engine.py; this method is absent from saved skills.",
                'expected_benefit':'Reuse the validation-before-mutation procedure in related stateful tasks.',
                'operations':[
                    {'op':'revise_skill','role':'generalist','id':'atomic-updates','text':'For stateful APIs, validate a staged snapshot before changing live state. Check input/output aliasing and rollback on failure.'},
                    {'op':'update_task_memory','role':'generalist','id':'snapshot-engine','text':'For the snapshot-engine project, inspect engine.py before reuse. It uses a missing-value sentinel; self-tests passed but were not independently graded.'}
                ]}}), usage_metadata={'input_tokens':10,'output_tokens':20,'total_tokens':30})
    monkeypatch.setattr(Settings, 'chat_model', lambda _: Reflector())
    result = asyncio.run(propose(store, settings))
    assert result['status'] == 'proposed'
    proposal = store.proposal(result['proposal_id'])
    candidate = store.manifest(proposal['candidate_version'])
    assert 'atomic-updates' in candidate['skills']
    assert 'snapshot-engine' in candidate['task_memory']
    assert 'validate a staged snapshot' in role_prompt(candidate)
    assert store.active() == active
    saved = json.loads(store.db.execute('SELECT response FROM reflections WHERE id=?',(result['reflection_id'],)).fetchone()[0])
    assert saved['reflector']['policy'] == REFLECTOR_POLICY
    assert saved['reflector']['prompt_digest']
    store.close()
