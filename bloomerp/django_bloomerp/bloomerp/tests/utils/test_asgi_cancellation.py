"""Bound cancellation regressions in a subprocess so an event-loop deadlock cannot hang CI."""

import asyncio
from pathlib import Path
import subprocess
import sys
import threading
import unittest

from asgiref.sync import ThreadSensitiveContext, async_to_sync, sync_to_async


async def exercise_cancelled_request() -> None:
    """Allow a cancelled thread-sensitive request to finish its asynchronous cleanup."""
    started = asyncio.Event()
    release = threading.Event()
    finished = threading.Event()
    loop = asyncio.get_running_loop()

    async def finish_request() -> None:
        """Model async response handling invoked by synchronous middleware."""
        await asyncio.sleep(0)

    def synchronous_request() -> None:
        """Continue worker execution after cancellation, as Python threads must."""
        loop.call_soon_threadsafe(started.set)
        if not release.wait(timeout=3):
            raise AssertionError("The event loop blocked during request cancellation")
        async_to_sync(finish_request)()
        finished.set()

    async def request() -> None:
        """Use the thread-sensitive context that Django creates for ASGI requests."""
        async with ThreadSensitiveContext():
            await sync_to_async(synchronous_request)()

    task = asyncio.create_task(request())
    await started.wait()
    loop.call_later(0.05, release.set)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    if not finished.is_set():
        raise AssertionError("Request cleanup did not allow the event loop to progress")


class RequestCancellationTests(unittest.TestCase):
    """Verify the dependency contract independently of Django settings and databases."""

    def test_cancelled_request_does_not_deadlock_event_loop(self) -> None:
        """
        Use case: A cancelled ASGI request's worker still needs the event loop.
        Expected result: Cleanup completes without blocking the loop or hanging CI.
        """
        # 1. Exercise real cancellation with a process-level deadline.
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--scenario"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        # 2. Require both event-loop progress and completed worker cleanup.
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    if sys.argv[1:] == ["--scenario"]:
        asyncio.run(exercise_cancelled_request())
    else:
        unittest.main()
