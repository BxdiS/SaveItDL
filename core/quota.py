from __future__ import annotations

from dataclasses import dataclass

from config import Limits
from core.stats import StatsDB
from core.premium import is_premium


@dataclass
class QuotaCheck:
    allowed: bool
    reason: str | None
    files_used: int
    bytes_used: int
    files_limit: int
    bytes_limit: int  # incl. bonus
    is_premium: bool


async def check_daily_quota(
    stats: StatsDB, user_id: int, limits: Limits, is_audio: bool = False
) -> QuotaCheck:
    row = await stats.get_user_row(user_id)
    premium = is_premium(row)

    files_used, bytes_used = await stats.get_user_usage_today(user_id)

    if premium:
        files_limit = limits.premium_daily_files
        bytes_limit = limits.premium_daily_bytes
    else:
        files_limit = limits.free_daily_files
        bytes_limit = limits.free_daily_bytes

    bonus = int(row.get("bonus_bytes") or 0) if row else 0
    bytes_limit_total = bytes_limit + bonus

    # Audio is small and lightly counted: no bytes limit for audio.
    if is_audio:
        if files_used >= files_limit:
            return QuotaCheck(
                False,
                f"Дневной лимит {files_limit} файлов исчерпан.",
                files_used, bytes_used, files_limit, bytes_limit_total, premium,
            )
        return QuotaCheck(True, None, files_used, bytes_used,
                          files_limit, bytes_limit_total, premium)

    if files_used >= files_limit:
        return QuotaCheck(
            False,
            f"Дневной лимит {files_limit} файлов исчерпан.",
            files_used, bytes_used, files_limit, bytes_limit_total, premium,
        )
    if bytes_used >= bytes_limit_total:
        gb_limit = bytes_limit_total / (1024 ** 3)
        return QuotaCheck(
            False,
            f"Дневной лимит трафика {gb_limit:.1f} ГБ исчерпан.",
            files_used, bytes_used, files_limit, bytes_limit_total, premium,
        )
    return QuotaCheck(True, None, files_used, bytes_used,
                      files_limit, bytes_limit_total, premium)
