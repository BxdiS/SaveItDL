import asyncio
import logging
import sys

from config import Config
from core.downloader import Downloader
from core.worker_pool import WorkerPool
from platforms.telegram import TelegramPlatform

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    cfg = Config.from_env()
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

    platform_factories = {
        "telegram": lambda token: TelegramPlatform(token, downloader, pool),
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
        platform = factory(token)
        logger.info("Starting platform: %s", name)
        tasks.append(asyncio.create_task(platform.start()))

    if not tasks:
        logger.error("No platforms enabled. Set ENABLED_PLATFORMS in .env")
        sys.exit(1)

    tasks.append(asyncio.create_task(pool.start()))
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
