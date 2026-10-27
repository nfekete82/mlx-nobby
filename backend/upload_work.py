"""Keep slow upload work and its in-memory payloads off the shared API pool."""

from functools import partial

import anyio


# Admission precedes bounded reads, so queued spooled files do not all become
# 250 MiB byte strings while waiting for slow PDF/STT processing.
upload_slot = anyio.Semaphore(2)
_workers = anyio.CapacityLimiter(2)


async def run_upload_work(function, *args):
    # Independent of Starlette's default limiter: two slow external requests
    # must not prevent health/status or other sync handlers from obtaining a
    # worker. Cancellation waits for worker cleanup rather than abandoning it.
    return await anyio.to_thread.run_sync(partial(function, *args), limiter=_workers)
