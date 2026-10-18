"""Local chat runs use the active organization, with bounded conversational context."""

import json
import threading

from langchain_core.messages import AIMessage, HumanMessage

from company.config import Settings
from company.background import run
from company.runtime import execute
from company.store import Store


def conversation(store, thread_id, *, learning_only=False):
    """Carry recent finished attempts, including failures; never another thread's records."""
    selected, characters = [], 0
    for turn in reversed(store.chat_turns(thread_id)):
        if learning_only and (not turn["run_id"] or store.replay(turn["run_id"])["run"]["split"] != "learning"):
            break  # Never implicitly share an earlier private exchange with reflection.
        if turn["status"] == "running":
            continue
        turn = {**turn, "output": turn["output"] or f"Previous attempt ended with status: {turn['status']}. No final answer was recorded."}
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
            history = conversation(store, thread_id, learning_only=learn) if thread_id else []
            effective_prompt = prompt.strip()
            if learn and history:
                # Save the same self-contained input that the reviewer will replay.
                # Only previously shared turns enter this snapshot, never private chat.
                effective_prompt = (
                    "Continue this previously shared task conversation. Earlier assistant messages are history, "
                    "not proof of execution. Complete the current user request using the original task requirements.\n"
                    + json.dumps({"current_request": prompt.strip(),
                                  "previous_messages": [{"role": message.type, "content": message.content} for message in history]}, ensure_ascii=False)
                )
                history = []
            turn = store.start_chat_turn(prompt.strip(), thread_id)

            def work():
                try:
                    result = run(execute(store, settings, task_id=f"{'task' if learn else 'chat'}-{turn['id'][:8]}", split="learning" if learn else "chat",
                                                 prompt=effective_prompt, expected=None, ungraded=True, conversation=history,
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
