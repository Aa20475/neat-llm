import asyncio
import json
from copy import deepcopy

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
    for split in ('chat','review','heldout'):
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


def test_context_drops_older_runs_before_losing_latest_solution_detail():
    evidence = [{'run_id':str(i),'project_artifacts':['x'*2000]} for i in range(6)]
    memories = [{'id':'memory','lesson':'A previous no_change is only historical evidence'}]
    originals = deepcopy((evidence, memories))
    context = reflection_context({'label':'v0'}, evidence, memories, max_chars=5000)
    assert len(canonical_json(context)) <= 5000
    assert context['learning_evidence'][0] == evidence[0]
    assert context['retrieval']['runs_omitted'] > 0
    assert context['reflection_memory'] == memories
    assert (evidence, memories) == originals


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
