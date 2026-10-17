import asyncio
from concurrent.futures import ThreadPoolExecutor

from company.background import run


def test_sequential_ui_jobs_keep_the_same_live_connection_loop():
    async def loop():
        return asyncio.get_running_loop()
    # Different HTTP job threads must not close or replace the SDK client's loop.
    with ThreadPoolExecutor(max_workers=1) as first:
        before = first.submit(run, loop()).result()
    with ThreadPoolExecutor(max_workers=1) as second:
        after = second.submit(run, loop()).result()
    assert before is after and after.is_running() and not after.is_closed()
