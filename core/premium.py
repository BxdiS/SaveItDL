from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True)
class Tariff:
    kind: str  # "month" | "year" | "5gb"
    stars: int
    label: str
    payload: str

    @property
    def duration_seconds(self) -> int:
        if self.kind == "month":
            return 30 * 24 * 3600
        if self.kind == "year":
            return 365 * 24 * 3600
        return 0


def tariffs(stars_month: int, stars_year: int, stars_5gb: int) -> list[Tariff]:
    return [
        Tariff("month", stars_month, "⭐ Premium — 30 дней", f"premium:month:{stars_month}"),
        Tariff("year", stars_year, "⭐ Premium — 12 месяцев", f"premium:year:{stars_year}"),
        Tariff("5gb", stars_5gb, "📦 +5 ГБ трафика", f"bonus:5gb:{stars_5gb}"),
    ]


def is_premium(user_row: dict | None, now: float | None = None) -> bool:
    if not user_row:
        return False
    now = now or time.time()
    return float(user_row.get("premium_until") or 0) > now


def premium_expires_days(user_row: dict | None) -> int | None:
    if not user_row:
        return None
    pu = float(user_row.get("premium_until") or 0)
    now = time.time()
    if pu <= now:
        return None
    return max(1, int((pu - now) // 86400))
