from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Limits:
    # Free tier
    free_max_height: int = 720
    free_max_duration_s: int = 15 * 60
    free_daily_files: int = 15
    free_daily_bytes: int = 1 * 1024 * 1024 * 1024
    free_concurrent: int = 1
    # Premium
    premium_daily_files: int = 100
    premium_daily_bytes: int = 10 * 1024 * 1024 * 1024
    premium_concurrent: int = 3
    # Rate limits
    rate_interval_s: float = 5.0
    burst_max: int = 3
    burst_window_s: float = 10.0
    callback_interval_s: float = 2.0
    new_user_interval_s: float = 10.0
    new_user_age_h: float = 24.0
    # Worker
    download_timeout_s: int = 300
    # Fair queue: after this many premium jobs, a free job is admitted
    priority_free_every: int = 4
    # Payment (Telegram Stars)
    stars_month: int = 150
    stars_year: int = 1500
    stars_5gb: int = 100
    premium_bonus_bytes_5gb: int = 5 * 1024 * 1024 * 1024


@dataclass
class Config:
    telegram_token: str = ""
    discord_token: str = ""
    temp_dir: str = str(Path("downloads"))
    enabled_platforms: list[str] = field(default_factory=lambda: ["telegram"])
    max_workers: int = 4
    queue_size: int = 100
    admin_id: int | None = None
    stats_db: str = "stats.db"
    bot_api_url: str | None = None
    limits: Limits = field(default_factory=Limits)

    @classmethod
    def from_env(cls) -> Config:
        enabled = os.getenv("ENABLED_PLATFORMS", "telegram")
        admin_raw = os.getenv("ADMIN_ID", "0")
        try:
            admin_id = int(admin_raw) or None
        except ValueError:
            admin_id = None
        return cls(
            telegram_token=os.getenv("TELEGRAM_TOKEN", ""),
            discord_token=os.getenv("DISCORD_TOKEN", ""),
            temp_dir=os.getenv("TEMP_DIR", "downloads"),
            enabled_platforms=[p.strip() for p in enabled.split(",")],
            max_workers=int(os.getenv("MAX_WORKERS", "4")),
            queue_size=int(os.getenv("QUEUE_SIZE", "100")),
            admin_id=admin_id,
            stats_db=os.getenv("STATS_DB", "stats.db"),
            bot_api_url=os.getenv("BOT_API_URL") or None,
            limits=Limits(),
        )
