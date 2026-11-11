"""In-process registry for webhook trade jobs that run after the HTTP ack.

TradingView drops a webhook request after about 3 seconds and never retries,
so the router answers as soon as the alert is authenticated and validated and
runs the exchange work as an asyncio task registered here.

The registry
  * keeps a strong reference to every running job, so it cannot be garbage
    collected mid-order;
  * remembers the dedupe key of every running job, so a second delivery of
    the same alert is refused while the first one is still executing;
  * lets the application lifespan drain running jobs on shutdown.

Jobs are never cancelled here: cancelling one in the middle of an order is
worse than letting it finish.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Coroutine

logger = logging.getLogger(__name__)

_jobs: dict[asyncio.Task, str] = {}
_inflight_keys: set[str] = set()
_accepting: bool = True


class NotAcceptingJobsError(Exception):
    """Raised when a job is submitted while the process is shutting down."""


def is_inflight(key: str) -> bool:
    """True while a job with this dedupe key is still running."""
    return key in _inflight_keys


def is_accepting() -> bool:
    return _accepting


def pending_jobs() -> list[str]:
    """Descriptions of the jobs that are still running."""
    return list(_jobs.values())


def submit(coro: Coroutine, key: str, description: str) -> asyncio.Task:
    """Start *coro* as a tracked background job.

    Callers must check ``is_inflight(key)`` and call this without awaiting in
    between, so that the check and the registration cannot interleave with
    another request.
    """
    if not _accepting:
        coro.close()
        raise NotAcceptingJobsError("Shutting down, not accepting new webhook jobs")

    task = asyncio.get_running_loop().create_task(coro, name=f"webhook-job {description}")
    _jobs[task] = description
    _inflight_keys.add(key)

    def _done(finished: asyncio.Task) -> None:
        _jobs.pop(finished, None)
        _inflight_keys.discard(key)
        if finished.cancelled():
            logger.error("Webhook job was cancelled before finishing: %s", description)
            return
        exc = finished.exception()
        if exc is not None:
            # The job handles its own errors; reaching this is a bug, but it
            # must still be visible in the logs.
            logger.error(
                "Webhook job crashed: %s: %s", description, exc, exc_info=exc
            )

    task.add_done_callback(_done)
    logger.info("Webhook job started: %s", description)
    return task


async def drain(timeout: float) -> list[str]:
    """Stop accepting jobs and wait up to *timeout* seconds for running ones.

    Returns the descriptions of jobs that were still running at the timeout.
    """
    global _accepting
    _accepting = False

    running = dict(_jobs)
    if not running:
        logger.info("No in-flight webhook jobs at shutdown")
        return []

    logger.warning(
        "Waiting for %d in-flight webhook job(s) before shutdown: %s",
        len(running),
        ", ".join(running.values()),
    )
    _, not_done = await asyncio.wait(list(running), timeout=timeout)
    if not_done:
        left = [running[task] for task in not_done]
        logger.error(
            "Shutdown drain timed out after %.1fs; %d webhook job(s) still running: %s",
            timeout,
            len(left),
            ", ".join(left),
        )
        return left

    logger.info("All %d in-flight webhook job(s) finished before shutdown", len(running))
    return []


def reset() -> None:
    """Forget all jobs and accept new ones again (tests only)."""
    global _accepting
    _jobs.clear()
    _inflight_keys.clear()
    _accepting = True
