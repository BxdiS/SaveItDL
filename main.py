import asyncio
import logging
import shutil
import sys

from config import Config
from core.downloader import Downloader
from core.notifier import AdminNotifier, AlertLevel
from core.stats import StatsDB
from core.worker_pool import WorkerPool
from platforms.telegram import TelegramPlatform

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

PLATFORM_REGISTRY = {
    "telegram": TelegramPlatform,
}

MAX_RESTART_ATTEMPTS = 5
RESTART_DELAY_BASE = 5


async def run_platform_isolated(
    name: str,
    factory,
    token: str,
    notifier: AdminNotifier,
):
    attempt = 0
    while attempt < MAX_RESTART_ATTEMPTS:
        try:
            platform = factory(token)
            if attempt > 0:
                logger.info("Platform %s recovered on attempt %d", name, attempt + 1)
            await platform.start()
        except asyncio.CancelledError:
            logger.info("Platform %s shutting down", name)
            return
        except Exception as e:
            attempt += 1
            delay = RESTART_DELAY_BASE * (2 ** (attempt - 1))
            await notifier.platform_down(name, str(e))

            if attempt < MAX_RESTART_ATTEMPTS:
                await notifier.platform_restarting(name, attempt)
                logger.warning(
                    "Platform %s crashed, restarting in %ds (attempt %d/%d): %s",
                    name, delay, attempt, MAX_RESTART_ATTEMPTS, e,
                )
                await asyncio.sleep(delay)
            else:
                await notifier.notify(
                    AlertLevel.CRITICAL,
                    name,
                    f"Gave up after {MAX_RESTART_ATTEMPTS} restarts. Manual intervention needed.",
                )
                logger.error("Platform %s permanently failed", name)
                return


async def monitor_health(pool: WorkerPool, notifier: AdminNotifier, temp_dir: str):
    error_window: list[bool] = []
    while True:
        await asyncio.sleep(60)
        try:
            disk = shutil.disk_usage(temp_dir)
            free_mb = disk.free // (1024 * 1024)
            if free_mb < 500:
                await notifier.disk_space_low(free_mb)

            if pool.queue_size >= pool._queue.maxsize * 0.9:
                await notifier.worker_pool_full()
        except Exception:
            logger.exception("Health monitor error")


async def main():
    cfg = Config.from_env()
    notifier = AdminNotifier(admin_id=cfg.admin_id)
    stats = StatsDB(db_path=cfg.stats_db)
    downloader = Downloader(temp_dir=cfg.temp_dir)
    pool = WorkerPool(
        downloader=downloader,
        max_workers=cfg.max_workers,
        queue_size=cfg.queue_size,
    )

    tokens = {
        "telegram": cfg.telegram_token,
        "discord": cfg.discord_token,
    }

    def make_tg_factory(dl, p, n, s, aid):
        def factory(token):
            platform = TelegramPlatform(token, dl, p, stats=s, admin_id=aid)
            n.set_bot(platform.bot)
            return platform
        return factory

    platform_factories = {
        "telegram": make_tg_factory(downloader, pool, notifier, stats, cfg.admin_id),
    }

    tasks = []
    for name in cfg.enabled_platforms:
        factory = platform_factories.get(name)
        if not factory:
            logger.warning("Unknown platform: %s — skipping", name)
            continue
        token = tokens.get(name, "")
        if not token:
            logger.error("No token for %s — set %s_TOKEN in .env", name, name.upper())
            sys.exit(1)
        logger.info("Starting platform: %s (isolated)", name)
        tasks.append(asyncio.create_task(
            run_platform_isolated(name, factory, token, notifier)
        ))

    if not tasks:
        logger.error("No platforms enabled")
        sys.exit(1)

    tasks.append(asyncio.create_task(pool.start()))
    tasks.append(asyncio.create_task(monitor_health(pool, notifier, cfg.temp_dir)))
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
