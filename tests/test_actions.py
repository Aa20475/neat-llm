import json
import threading

import pytest

from company.actions import ReflectionService
from company.config import Settings
from company.organization import initial_manifest
from company.store import Store


@pytest.mark.parametrize("new_candidate", [False, True])
def test_ui_reflection_uses_pipeline_once_and_evaluates_only_new_candidates(tmp_path, monkeypatch, new_candidate):
    settings = Settings(api_key="test-key", model="test-model")
    store = Store(tmp_path / "company.sqlite3")
    store.initialize(initial_manifest(settings))
    learning = store.start_run("practice", "learning", "Practice input")
    store.finish(learning["id"], "completed", "[]", {"passed": False}, {})
    monkeypatch.setattr(Settings, "load", lambda: settings)
    release = threading.Event()
    calls = []
    async def propose(store, settings):
        assert release.wait(5)
        calls.append("propose")
        return {"status": "proposed" if new_candidate else "duplicate", "proposal_id": "candidate" if new_candidate else None}
    async def evaluate(store, settings, proposal_id):
        calls.append(proposal_id)
        return {"status": "rejected"}
    monkeypatch.setattr("company.actions.propose", propose)
    monkeypatch.setattr("company.actions.evaluate", evaluate)
    service = ReflectionService(store.path)
    result = service.submit()
    try:
        with pytest.raises(RuntimeError, match="already running"):
            service.submit()
        with pytest.raises(RuntimeError, match="Another controller"):
            with store.controller():
                pass
    finally:
        release.set()
    assert service.busy.acquire(timeout=5)
    service.busy.release()
    row = store.db.execute("SELECT * FROM actions WHERE id=?", (result["id"],)).fetchone()
    assert row["status"] == "completed"
    assert calls == (["propose", "candidate"] if new_candidate else ["propose"])
    assert json.loads(row["result"])["reflection"]["status"] == ("proposed" if new_candidate else "duplicate")
    assert store.active()["generation"] == 0
    store.close()


def test_ui_reflection_requires_learning_and_recovers_interruption(tmp_path, monkeypatch):
    settings = Settings(api_key="test-key", model="test-model")
    store = Store(tmp_path / "company.sqlite3")
    store.initialize(initial_manifest(settings))
    monkeypatch.setattr(Settings, "load", lambda: settings)
    service = ReflectionService(store.path)
    with pytest.raises(ValueError, match="learning task"):
        service.submit()
    assert service.busy.acquire(timeout=1)
    service.busy.release()
    action_id = store.start_action("reflection")
    with store.controller():
        store.recover_interrupted()
    assert store.db.execute("SELECT status FROM actions WHERE id=?", (action_id,)).fetchone()[0] == "interrupted"
    store.close()
