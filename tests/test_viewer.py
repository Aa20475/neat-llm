import json
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import sqlite3
import threading
from types import SimpleNamespace

import pytest

from company.config import Settings
from company.organization import initial_manifest
from company.store import Store
from company.viewer import handler_for, open_reader, snapshot


def test_viewer_reader_cannot_mutate_or_create_database(tmp_path):
    path = tmp_path / "company.sqlite3"
    with pytest.raises(sqlite3.OperationalError):
        open_reader(path)
    assert not path.exists()
    store = Store(path)
    store.initialize(initial_manifest(Settings(api_key="test", model="test-model")))
    store.close()
    reader = open_reader(path)
    try:
        assert snapshot(reader)["active"]
        for statement in ("CREATE TABLE unexpected (id)", "DELETE FROM organization",
                          "UPDATE organization SET generation=9"):
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                reader.db.execute(statement)
    finally:
        reader.close()


def test_polling_readers_do_not_break_chat_writes(tmp_path):
    path = tmp_path / "company.sqlite3"
    store = Store(path)
    store.initialize(initial_manifest(Settings(api_key="test", model="test-model")))
    store.close()
    stop = threading.Event()
    ready = threading.Barrier(4)

    def poll():
        ready.wait(timeout=5)
        while not stop.is_set():
            reader = open_reader(path)
            try:
                snapshot(reader)
            finally:
                reader.close()

    with ThreadPoolExecutor(max_workers=3) as pool:
        readers = [pool.submit(poll) for _ in range(3)]
        ready.wait(timeout=5)
        try:
            for index in range(30):
                writer = Store(path)
                try:
                    turn = writer.start_chat_turn("Concurrent polling")
                    run = writer.start_run(str(index), "chat", "Concurrent polling")
                    writer.link_chat_run(turn["id"], run["id"])
                    writer.start_project(run["id"], "chat", turn["id"])
                    writer.finish(run["id"], "completed", "Answer", None, {})
                    writer.finish_chat_turn(turn["id"], "completed")
                finally:
                    writer.close()
        finally:
            stop.set()
        for reader in readers:
            reader.result(timeout=5)
    reader = open_reader(path)
    try:
        assert len(reader.chat_turns()) == 30
        assert all(turn["status"] == "completed" for turn in reader.chat_turns())
    finally:
        reader.close()


def test_viewer_reads_complete_history_without_exposing_credentials(tmp_path):
    settings = Settings(api_key="private-viewer-test-key", model="test-model")
    store = Store(tmp_path / "company.sqlite3")
    store.initialize(initial_manifest(settings))
    run = store.start_run("example", "learning", "public input")
    data = snapshot(store)
    assert data["runs"][0]["id"] == run["id"]
    assert data["active"]["version_id"] == run["version_id"]
    assert data["proposals"] == [] and data["reflection_memory"] == []
    assert settings.api_key not in json.dumps(data)
    store.close()


@pytest.mark.parametrize("origin,host,expected", [
    ("http://127.0.0.1:8765", "127.0.0.1:8765", 202),
    ("https://unrelated.example", "127.0.0.1:8765", 403),
    (None, "127.0.0.1:8765", 403),
    ("http://unrelated.example:8765", "unrelated.example:8765", 403),
])
@pytest.mark.parametrize("endpoint", ["/api/chat", "/api/reflect", "/api/chat/delete", "/api/chat/stop"])
def test_only_same_origin_local_actions_can_start_inference(tmp_path, monkeypatch, origin, host, expected, endpoint):
    calls = []
    def submit(self, payload):
        calls.append(payload)
        return {"id": "turn", "thread_id": "thread"}
    monkeypatch.setattr("company.viewer.ChatService.submit", submit)
    monkeypatch.setattr("company.viewer.ChatService.delete", submit)
    monkeypatch.setattr("company.viewer.ChatService.stop", submit)
    monkeypatch.setattr("company.viewer.ReflectionService.submit", lambda self: submit(self, {}))
    handler = handler_for(tmp_path / "company.sqlite3")
    request = handler.__new__(handler)
    payload = json.dumps({"message": "Hello"} if endpoint == "/api/chat" else {"thread_id": "a" * 32} if endpoint == "/api/chat/delete" else {}).encode()
    request.server = SimpleNamespace(server_port=8765)
    request.path = endpoint
    request.headers = {"Host": host, "Content-Type": "application/json", "Content-Length": str(len(payload))}
    if origin:
        request.headers["Origin"] = origin
    request.rfile, request.wfile = BytesIO(payload), BytesIO()
    statuses = []
    request.send_error = lambda status, *args: statuses.append(status)
    request.send_response = lambda status: statuses.append(status)
    request.send_header = lambda *args: None
    request.end_headers = lambda: None
    request.do_POST()
    assert statuses == [200 if endpoint == "/api/chat/delete" and expected == 202 else expected]
    assert len(calls) == (1 if expected == 202 else 0)


def test_chat_activity_is_bounded_scoped_and_omits_raw_model_and_tool_content(tmp_path):
    store = Store(tmp_path / 'activity.sqlite3')
    store.initialize(initial_manifest(Settings(api_key='test', model='test-model')))
    turn = store.start_chat_turn('Inspect a project')
    run = store.start_run('activity', 'chat', 'Inspect a project')
    store.link_chat_run(turn['id'], run['id'])
    root = run['id'] + ':root'
    worker = run['id'] + ':worker:1'
    store.worker_start(run['id'], worker, root, 'general-purpose', True, 'Read-only review')
    for _ in range(20):
        store.event(run['id'], 'model_finished', root, {'output':'RAW_MODEL_CONTENT', 'tool_calls':[]})
    store.event(run['id'], 'model_started', worker, {'call_number':7})
    store.event(run['id'], 'tool_started', worker, {'name':'python_execute', 'arguments':{'file_path':'test_merge.py','code':'RAW_CODE'}})
    store.event(run['id'], 'tool_finished', worker, {'name':'python_execute','output':json.dumps({'status':'error','exit_code':0,'reported_error':{'line':'RAW_ERROR'},'stdout':'RAW_STDOUT'})})
    other = store.start_run('unrelated', 'smoke', 'Different task')
    store.event(other['id'], 'tool_started', other['id'] + ':root', {'name':'project_read','arguments':{'path':'unrelated.txt'}})
    activity = snapshot(store)['chat_turns'][0]['activity']
    assert len(activity) == 3
    assert [event['seq'] for event in activity] == sorted([event['seq'] for event in activity], reverse=True)
    assert activity[0]['tone'] == 'error' and 'exit 0' in activity[0]['detail']
    assert activity[1]['detail'] == 'test_merge.py'
    assert activity[1]['worker'] == 'Worker 1 · general-purpose'
    assert activity[2]['detail'] == 'Model call 7'
    assert 'RAW_' not in json.dumps(activity) and 'unrelated.txt' not in json.dumps(activity)
    store.finish(run['id'], 'completed', 'Finished', None, {})
    store.finish_chat_turn(turn['id'], 'completed')
    assert 'activity' not in snapshot(store)['chat_turns'][0]
    store.close()


def test_chat_activity_before_run_link_and_python_success_is_not_a_test_verdict(tmp_path):
    store = Store(tmp_path / 'activity.sqlite3')
    store.initialize(initial_manifest(Settings(api_key='test', model='test-model')))
    turn = store.start_chat_turn('Run Python')
    assert snapshot(store)['chat_turns'][0]['activity'] == []
    run = store.start_run('activity', 'chat', 'Run Python')
    store.link_chat_run(turn['id'], run['id'])
    store.event(run['id'], 'tool_finished', run['id'] + ':root', {'name':'python_execute','output':json.dumps({'status':'ok','exit_code':0})})
    event = snapshot(store)['chat_turns'][0]['activity'][0]
    assert event['summary'] == 'Python process exited'
    assert 'not been independently verified' in event['detail']
    assert event['worker'] == 'Generalist'
    store.close()
