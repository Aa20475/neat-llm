"""Explicit UI actions run the same reflection pipeline as the CLI."""

import threading

from company.config import Settings
from company.background import run
from company.reflection import learning_evidence, propose
from company.store import Store
from company.validation import evaluate


class ReflectionService:
    def __init__(self, db_path):
        self.db_path = db_path
        self.busy = threading.Lock()

    def submit(self):
        if not self.busy.acquire(blocking=False):
            raise RuntimeError("Reflection is already running")
        store, controller, entered = None, None, False
        try:
            settings = Settings.load()
            store = Store(self.db_path)
            controller = store.controller()
            controller.__enter__()
            entered = True
            store.recover_interrupted()
            if not learning_evidence(store, store.active()["version_id"]):
                raise ValueError("Run at least one learning task on the active version before reflecting")
            action_id = store.start_action("reflection")

            async def pipeline():
                result = {"reflection": await propose(store, settings)}
                if result["reflection"].get("proposal_id"):
                    result["evaluation"] = await evaluate(store, settings, result["reflection"]["proposal_id"])
                return result

            def work():
                try:
                    result = run(pipeline())
                    failed = result["reflection"]["status"] == "failed"
                    store.finish_action(action_id, "failed" if failed else "completed", result,
                                        "Reflection failed; inspect the attempt record" if failed else None)
                except Exception as error:
                    store.finish_action(action_id, "failed", error=type(error).__name__)
                finally:
                    controller.__exit__(None, None, None)
                    store.close()
                    self.busy.release()

            threading.Thread(target=work, name=f"reflection-{action_id[:8]}", daemon=False).start()
            return {"id": action_id, "status": "running"}
        except BaseException:
            if entered:
                controller.__exit__(None, None, None)
            if store:
                store.close()
            self.busy.release()
            raise
