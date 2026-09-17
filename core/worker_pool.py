from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
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


class WorkerPool:
    def __init__(self, downloader: Downloader, max_workers: int = 4, queue_size: int = 100):
        self._downloader = downloader
        self._max_workers = max_workers
        self._queue: asyncio.Queue[DownloadJob] = asyncio.Queue(maxsize=queue_size)
        self._semaphore = asyncio.Semaphore(max_workers)
        self._active = 0
        self._total_processed = 0
        self._running = False

    @property
    def active_downloads(self) -> int:
        return self._active

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    @property
    def total_processed(self) -> int:
        return self._total_processed

    async def submit(self, job: DownloadJob) -> bool:
        try:
            self._queue.put_nowait(job)
            return True
        except asyncio.QueueFull:
            return False

    async def start(self) -> None:
        self._running = True
        logger.info("Worker pool started: %d max concurrent downloads", self._max_workers)
        while self._running:
            job = await self._queue.get()
            asyncio.create_task(self._process(job))

    async def stop(self) -> None:
        self._running = False

    async def _process(self, job: DownloadJob) -> None:
        async with self._semaphore:
            self._active += 1
            try:
                result = await self._downloader.download(
                    job.url, job.media_format,
                    format_id=job.format_id,
                    download_range=job.download_range,
                )
                await job.callback(result)
            except Exception:
                logger.exception("Worker error for %s", job.url)
                error_result = DownloadResult(success=False, error="Internal worker error")
                await job.callback(error_result)
            finally:
                self._active -= 1
                self._total_processed += 1
                self._queue.task_done()
