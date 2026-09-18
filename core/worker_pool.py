from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from core.downloader import Downloader
from core.models import DownloadResult, MediaFormat

logger = logging.getLogger(__name__)


@dataclass
class DownloadJob:
    url: str
    media_format: MediaFormat
    callback: Callable[[DownloadResult], Coroutine[Any, Any, None]]
    format_id: str | None = None
    download_range: tuple[int, int] | None = None
    user_id: int | None = None
    is_premium: bool = False
    enqueued_at: float = field(default_factory=time.time)


_SENTINEL = object()


class WorkerPool:
    """
    Async worker pool with:
      - Sentinel-based graceful shutdown.
      - Per-user concurrency cap (free=1, premium=N).
      - Two priority tracks: premium jumps the free queue, but every
        `priority_free_every` premium dispatches let one free job through.
      - Per-job timeout (SIGTERM-safe).
      - Active task tracking, drained on stop().
    """

    def __init__(
        self,
        downloader: Downloader,
        max_workers: int = 4,
        queue_size: int = 100,
        free_concurrent: int = 1,
        premium_concurrent: int = 3,
        priority_free_every: int = 4,
        download_timeout_s: int = 300,
    ):
        self._downloader = downloader
        self._max_workers = max_workers
        self._premium_q: deque[DownloadJob] = deque()
        self._free_q: deque[DownloadJob] = deque()
        self._queue_max = queue_size
        self._semaphore = asyncio.Semaphore(max_workers)
        self._nudge = asyncio.Event()
        self._free_conc = free_concurrent
        self._premium_conc = premium_concurrent
        self._priority_free_every = priority_free_every
        self._timeout_s = download_timeout_s

        self._active = 0
        self._active_by_user: dict[int, int] = {}
        self._active_tasks: set[asyncio.Task] = set()
        self._premium_streak = 0
        self._total_processed = 0
        self._running = False
        self._stopping = False

    @property
    def active_downloads(self) -> int:
        return self._active

    @property
    def queue_size(self) -> int:
        return len(self._premium_q) + len(self._free_q)

    @property
    def total_processed(self) -> int:
        return self._total_processed

    def user_active(self, user_id: int) -> int:
        return self._active_by_user.get(user_id, 0)

    def user_queued(self, user_id: int) -> int:
        return sum(1 for j in self._premium_q if j.user_id == user_id) + sum(
            1 for j in self._free_q if j.user_id == user_id
        )

    async def submit(self, job: DownloadJob) -> bool:
        if self._stopping:
            return False
        if self.queue_size >= self._queue_max:
            return False
        q = self._premium_q if job.is_premium else self._free_q
        q.append(job)
        self._nudge.set()
        return True

    def _pick_job(self) -> DownloadJob | None:
        """
        Pick next runnable job respecting per-user caps + fairness.
        Returns None if nothing can run right now.
        """
        # Fairness: after N premium jobs in a row, prefer free queue if any.
        prefer_free = (
            self._premium_streak >= self._priority_free_every
            and self._free_q
        )
        order = [self._free_q, self._premium_q] if prefer_free else [
            self._premium_q, self._free_q
        ]

        for q in order:
            for i, job in enumerate(q):
                cap = self._premium_conc if job.is_premium else self._free_conc
                if job.user_id is None:
                    picked = True
                else:
                    picked = self._active_by_user.get(job.user_id, 0) < cap
                if picked:
                    del q[i]
                    if job.is_premium and q is self._premium_q:
                        self._premium_streak += 1
                    else:
                        self._premium_streak = 0
                    return job
        return None

    async def start(self) -> None:
        self._running = True
        logger.info(
            "Worker pool started: %d workers, free=%d/user, premium=%d/user",
            self._max_workers, self._free_conc, self._premium_conc,
        )
        while self._running:
            if self.queue_size == 0:
                self._nudge.clear()
                try:
                    await self._nudge.wait()
                except asyncio.CancelledError:
                    break
                if self._stopping and self.queue_size == 0:
                    break
                continue

            job = self._pick_job()
            if job is None:
                # queue non-empty but every head is user-capped; wait for slot to free
                await asyncio.sleep(0.2)
                continue

            task = asyncio.create_task(self._process(job))
            self._active_tasks.add(task)
            task.add_done_callback(self._active_tasks.discard)

        # Drain remaining active tasks
        if self._active_tasks:
            logger.info("Draining %d active tasks...", len(self._active_tasks))
            await asyncio.gather(*self._active_tasks, return_exceptions=True)

    async def stop(self, drain_timeout: float = 30.0) -> None:
        self._stopping = True
        self._running = False
        self._nudge.set()
        # Reject remaining queued jobs
        for q in (self._premium_q, self._free_q):
            while q:
                job = q.popleft()
                try:
                    await job.callback(DownloadResult(
                        success=False, error="Bot shutting down"
                    ))
                except Exception:
                    logger.exception("Callback error during drain")
        if self._active_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._active_tasks, return_exceptions=True),
                    timeout=drain_timeout,
                )
            except asyncio.TimeoutError:
                logger.warning("Some workers did not drain in %.1fs", drain_timeout)

    async def _process(self, job: DownloadJob) -> None:
        async with self._semaphore:
            self._active += 1
            if job.user_id is not None:
                self._active_by_user[job.user_id] = (
                    self._active_by_user.get(job.user_id, 0) + 1
                )
            try:
                result = await asyncio.wait_for(
                    self._downloader.download(
                        job.url, job.media_format,
                        format_id=job.format_id,
                        download_range=job.download_range,
                    ),
                    timeout=self._timeout_s,
                )
                await job.callback(result)
            except asyncio.TimeoutError:
                logger.warning("Download timeout for %s", job.url)
                await job.callback(DownloadResult(
                    success=False,
                    error=f"Скачивание превысило {self._timeout_s} сек и было отменено.",
                ))
            except Exception:
                logger.exception("Worker error for %s", job.url)
                await job.callback(DownloadResult(
                    success=False, error="Internal worker error",
                ))
            finally:
                self._active -= 1
                self._total_processed += 1
                if job.user_id is not None:
                    n = self._active_by_user.get(job.user_id, 0) - 1
                    if n <= 0:
                        self._active_by_user.pop(job.user_id, None)
                    else:
                        self._active_by_user[job.user_id] = n
                # A user slot just freed; kick the loop in case another job for
                # that user was waiting.
                self._nudge.set()
