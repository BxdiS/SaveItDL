from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


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

    @classmethod
    def from_env(cls) -> Config:
        enabled = os.getenv("ENABLED_PLATFORMS", "telegram")
        return cls(
            telegram_token=os.getenv("TELEGRAM_TOKEN", ""),
            discord_token=os.getenv("DISCORD_TOKEN", ""),
            temp_dir=os.getenv("TEMP_DIR", "downloads"),
            enabled_platforms=[p.strip() for p in enabled.split(",")],
            max_workers=int(os.getenv("MAX_WORKERS", "4")),
            queue_size=int(os.getenv("QUEUE_SIZE", "100")),
            admin_id=int(os.getenv("ADMIN_ID", "0")) or None,
            stats_db=os.getenv("STATS_DB", "stats.db"),
        )
