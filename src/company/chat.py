"""Local chat runs use the active organization, with bounded conversational context."""

import threading

from langchain_core.messages import AIMessage, HumanMessage

from company.config import Settings
from company.background import run
from company.runtime import execute
from company.store import Store


def conversation(store, thread_id):
    """Carry the most recent complete exchanges; never benchmark or other-thread records."""
    selected, characters = [], 0
    for turn in reversed(store.chat_turns(thread_id)):
        if turn["status"] != "completed" or not turn["output"]:
            continue
        size = len(turn["prompt"]) + len(turn["output"])
        if len(selected) == 5 or characters + size > 24000:
            break
        selected.append(turn)
        characters += size
    return [message for turn in reversed(selected)
            for message in (HumanMessage(content=turn["prompt"]), AIMessage(content=turn["output"]))]


class ChatService:
    def __init__(self, db_path):
        self.db_path = db_path
        self.busy = threading.Lock()

    def submit(self, payload):
        if not isinstance(payload, dict) or set(payload) - {"message", "thread_id", "learn"}:
            raise ValueError("Expected a message and optional conversation ID")
        prompt, thread_id = payload.get("message"), payload.get("thread_id")
        learn = payload.get("learn", False)
        if not isinstance(learn, bool):
            raise ValueError("Use for reflection must be true or false")
        if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 8000:
            raise ValueError("Message must contain 1–8,000 characters")
        if thread_id is not None and (not isinstance(thread_id, str) or len(thread_id) != 32):
            raise ValueError("Invalid conversation ID")
        if not self.busy.acquire(blocking=False):
            raise RuntimeError("The company is answering a message; wait for it to finish")
        store, controller = None, None
        entered = False
        try:
            settings = Settings.load()
            store = Store(self.db_path)
            controller = store.controller()
            controller.__enter__()
            entered = True
            store.recover_interrupted()
            # Opted-in tasks stand alone, so unrelated private chat is not shared with reflection.
            history = conversation(store, thread_id) if thread_id and not learn else []
            turn = store.start_chat_turn(prompt.strip(), thread_id)

            def work():
                try:
                    result = run(execute(store, settings, task_id=f"{'task' if learn else 'chat'}-{turn['id'][:8]}", split="learning" if learn else "chat",
                                                 prompt=prompt.strip(), expected=None, ungraded=True, conversation=history,
                                                 chat_turn_id=turn["id"], phase="chat"))
                    store.finish_chat_turn(turn["id"], result["run"]["status"], result["run"]["error"])
                except Exception as error:
                    store.finish_chat_turn(turn["id"], "failed", type(error).__name__)
                finally:
                    controller.__exit__(None, None, None)
                    store.close()
                    self.busy.release()

            # A normal server shutdown waits for an active run to finish.
            threading.Thread(target=work, name=f"chat-{turn['id'][:8]}", daemon=False).start()
            return turn
        except BaseException:
            if entered:
                controller.__exit__(None, None, None)
            if store:
                store.close()
            self.busy.release()
            raise
