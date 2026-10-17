"""Keep SDK async connection pools on one event loop across local UI actions."""

import asyncio
import threading


_lock = threading.Lock()
_loop = None


def run(coroutine):
    global _loop
    with _lock:
        if _loop is None:
            _loop = asyncio.new_event_loop()
            threading.Thread(target=_loop.run_forever, name="company-async-runtime", daemon=True).start()
        loop = _loop
    # Callers are background job threads; the HTTP handler remains responsive.
    return asyncio.run_coroutine_threadsafe(coroutine, loop).result()
