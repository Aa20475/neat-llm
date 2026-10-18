import json
from io import BytesIO
from types import SimpleNamespace

import pytest

from company.config import Settings
from company.organization import initial_manifest
from company.store import Store
from company.viewer import handler_for, snapshot


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
