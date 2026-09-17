from __future__ import annotations

import asyncio
import logging
from enum import Enum

logger = logging.getLogger(__name__)


class AlertLevel(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AdminNotifier:
    """Sends alerts to admin via any connected platform."""

    def __init__(self, admin_id: int | str | None = None):
        self._admin_id = admin_id
        self._bot = None
        self._error_counts: dict[str, int] = {}
        self._suppressed_until: dict[str, float] = {}

    def set_bot(self, bot) -> None:
        self._bot = bot

    async def notify(self, level: AlertLevel, module: str, message: str) -> None:
        key = f"{module}:{message[:50]}"
        self._error_counts[key] = self._error_counts.get(key, 0) + 1

        now = asyncio.get_event_loop().time()
        if now < self._suppressed_until.get(key, 0):
            return
        # suppress duplicate alerts for 5 minutes
        self._suppressed_until[key] = now + 300

        count = self._error_counts[key]
        prefix = {
            AlertLevel.INFO: "ℹ️",
            AlertLevel.WARNING: "⚠️",
            AlertLevel.CRITICAL: "🔴",
        }[level]

        text = f"{prefix} [{module}] {message}"
        if count > 1:
            text += f"\n(repeated {count} times)"

        logger.log(
            logging.CRITICAL if level == AlertLevel.CRITICAL else logging.WARNING,
            "[ADMIN] %s", text,
        )

        if self._bot and self._admin_id:
            try:
                await self._bot.send_message(self._admin_id, text)
            except Exception:
                logger.exception("Failed to send admin notification")

    async def platform_down(self, platform_name: str, error: str) -> None:
        await self.notify(
            AlertLevel.CRITICAL,
            platform_name,
            f"Platform crashed: {error}",
        )

    async def platform_restarting(self, platform_name: str, attempt: int) -> None:
        await self.notify(
            AlertLevel.WARNING,
            platform_name,
            f"Restarting (attempt #{attempt})",
        )

    async def worker_pool_full(self) -> None:
        await self.notify(
            AlertLevel.WARNING,
            "worker_pool",
            "Queue is full — new requests are being rejected",
        )

    async def download_error_spike(self, error_rate: float) -> None:
        await self.notify(
            AlertLevel.WARNING,
            "downloader",
            f"Error rate spiked to {error_rate:.0%}",
        )

    async def disk_space_low(self, free_mb: int) -> None:
        await self.notify(
            AlertLevel.CRITICAL,
            "system",
            f"Disk space low: {free_mb} MB remaining",
        )
