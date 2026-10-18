import asyncio
from concurrent.futures import CancelledError, ThreadPoolExecutor
import threading

import pytest

from company.background import Cancellation, run


def test_sequential_ui_jobs_keep_the_same_live_connection_loop():
    async def loop():
        return asyncio.get_running_loop()
    # Different HTTP job threads must not close or replace the SDK client's loop.
    with ThreadPoolExecutor(max_workers=1) as first:
        before = first.submit(run, loop()).result()
    with ThreadPoolExecutor(max_workers=1) as second:
        after = second.submit(run, loop()).result()
    assert before is after and after.is_running() and not after.is_closed()


def test_stop_waits_for_async_cleanup_and_repeated_stop_does_not_cancel_cleanup():
    cancellation = Cancellation()
    started, cleaning, release, cleaned = (threading.Event() for _ in range(4))
    async def task():
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            while not release.is_set():
                await asyncio.sleep(.01)
            cleaned.set()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run, task(), cancellation)
        try:
            assert started.wait(5)
            cancellation.cancel()
            assert cleaning.wait(5)
            cancellation.cancel()
            assert not future.done()
        finally:
            release.set()
        with pytest.raises(CancelledError):
            future.result(timeout=5)
    assert cleaned.is_set()


def test_stop_before_registration_never_starts_work():
    cancellation = Cancellation()
    cancellation.cancel()
    started = []
    async def task():
        started.append(True)
    with pytest.raises(CancelledError):
        run(task(), cancellation)
    assert started == []
