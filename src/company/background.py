"""Keep SDK async connection pools on one event loop across local UI actions."""

import asyncio
import threading


_lock = threading.Lock()
_loop = None


class Cancellation:
    """Cancel the async task, but let its caller wait for cleanup to finish."""

    def __init__(self):
        self._lock = threading.Lock()
        self._task = self._loop = None
        self.requested = False

    def cancel(self):
        with self._lock:
            if self.requested:
                return
            self.requested = True
            if self._task is not None:
                self._loop.call_soon_threadsafe(self._task.cancel)

    async def wait(self, coroutine):
        with self._lock:
            self._loop = asyncio.get_running_loop()
            self._task = asyncio.create_task(coroutine)
            task = self._task
            if self.requested:
                task.cancel()
        try:
            return await task
        finally:
            with self._lock:
                self._task = self._loop = None


def run(coroutine, cancellation=None):
    global _loop
    with _lock:
        if _loop is None:
            _loop = asyncio.new_event_loop()
            threading.Thread(target=_loop.run_forever, name="company-async-runtime", daemon=True).start()
        loop = _loop
    # Callers are background job threads; the HTTP handler remains responsive.
    # Do not cancel this concurrent Future: it would return before the task's
    # finally blocks finish, allowing callers to close SQLite during cleanup.
    pending = cancellation.wait(coroutine) if cancellation else coroutine
    return asyncio.run_coroutine_threadsafe(pending, loop).result()
