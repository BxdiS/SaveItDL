from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

START_PARAM_MAX = 64
PENDING_TTL_S = 24 * 3600
AWAITING_TTL_S = 15 * 60


@dataclass
class UserStats:
    user_id: int
    total_downloads: int
    total_bytes: int
    first_seen: float
    last_active: float
    favorite_platform: str | None
    favorite_format: str | None


@dataclass
class GlobalStats:
    total_users: int
    active_today: int
    active_week: int
    total_downloads: int
    total_bytes: int
    downloads_today: int
    top_platforms: list[tuple[str, int]]
    top_formats: list[tuple[str, int]]
    avg_filesize: int
    peak_hour: int | None
    error_rate: float
    new_users_today: int = 0
    new_users_week: int = 0
    avg_download_time_ms: int = 0
    top_languages: list[tuple[str, int]] = field(default_factory=list)
    retention_d1: float = 0.0
    unique_urls_today: int = 0


class StatsDB:
    def __init__(self, db_path: str = "stats.db"):
        self._db_path = db_path
        self._lock = asyncio.Lock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    language_code TEXT,
                    is_premium INTEGER DEFAULT 0,
                    start_param TEXT,
                    first_seen REAL NOT NULL,
                    last_active REAL NOT NULL,
                    total_sessions INTEGER DEFAULT 1,
                    premium_until REAL DEFAULT 0,
                    bonus_bytes INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS pending_urls (
                    url_id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    url TEXT NOT NULL,
                    formats_json TEXT,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS awaiting_range (
                    user_id INTEGER PRIMARY KEY,
                    url_id TEXT NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    stars INTEGER NOT NULL,
                    charge_id TEXT,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS downloads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    url TEXT NOT NULL,
                    platform TEXT,
                    media_format TEXT NOT NULL,
                    quality TEXT,
                    filesize INTEGER,
                    duration INTEGER,
                    title TEXT,
                    success INTEGER NOT NULL DEFAULT 1,
                    error TEXT,
                    download_time_ms INTEGER,
                    created_at REAL NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                );

                CREATE TABLE IF NOT EXISTS user_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    detail TEXT,
                    created_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_downloads_user ON downloads(user_id);
                CREATE INDEX IF NOT EXISTS idx_downloads_created ON downloads(created_at);
                CREATE INDEX IF NOT EXISTS idx_downloads_platform ON downloads(platform);
                CREATE INDEX IF NOT EXISTS idx_actions_user ON user_actions(user_id);
                CREATE INDEX IF NOT EXISTS idx_actions_created ON user_actions(created_at);
            """)
            self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection):
        cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        for col, typ in [
            ("last_name", "TEXT"),
            ("is_premium", "INTEGER DEFAULT 0"),
            ("start_param", "TEXT"),
            ("total_sessions", "INTEGER DEFAULT 1"),
            ("premium_until", "REAL DEFAULT 0"),
            ("bonus_bytes", "INTEGER DEFAULT 0"),
        ]:
            if col not in cols:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} {typ}")

    async def track_user(
        self, user_id: int, username: str | None = None,
        first_name: str | None = None, language_code: str | None = None,
        last_name: str | None = None, is_premium: bool = False,
        start_param: str | None = None,
    ):
        now = time.time()
        async with self._lock:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, self._track_user_sync,
                user_id, username, first_name, last_name,
                language_code, is_premium, start_param, now,
            )

    def _track_user_sync(self, user_id, username, first_name, last_name,
                          language_code, is_premium, start_param, now):
        if start_param:
            start_param = start_param[:START_PARAM_MAX]
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT first_seen, last_active FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()

            session_inc = 0
            if existing:
                last_active = existing[1]
                if now - last_active > 1800:
                    session_inc = 1

            if existing:
                conn.execute("""
                    UPDATE users SET
                        username = COALESCE(?, username),
                        first_name = COALESCE(?, first_name),
                        last_name = COALESCE(?, last_name),
                        language_code = COALESCE(?, language_code),
                        is_premium = ?,
                        start_param = COALESCE(start_param, ?),
                        last_active = ?,
                        total_sessions = total_sessions + ?
                    WHERE user_id = ?
                """, (username, first_name, last_name, language_code,
                      int(is_premium), start_param, now, session_inc, user_id))
            else:
                conn.execute("""
                    INSERT INTO users
                    (user_id, username, first_name, last_name, language_code,
                     is_premium, start_param, first_seen, last_active, total_sessions)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """, (user_id, username, first_name, last_name, language_code,
                      int(is_premium), start_param, now, now))

    async def track_action(self, user_id: int, action: str, detail: str | None = None):
        now = time.time()
        async with self._lock:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._track_action_sync, user_id, action, detail, now)

    def _track_action_sync(self, user_id, action, detail, now):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO user_actions (user_id, action, detail, created_at) VALUES (?, ?, ?, ?)",
                (user_id, action, detail, now),
            )

    async def track_download(
        self, user_id: int, url: str, platform: str | None,
        media_format: str, quality: str | None = None,
        filesize: int | None = None, duration: int | None = None,
        title: str | None = None, success: bool = True,
        error: str | None = None, download_time_ms: int | None = None,
    ):
        now = time.time()
        async with self._lock:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._track_download_sync,
                                       user_id, url, platform, media_format, quality,
                                       filesize, duration, title, success, error,
                                       download_time_ms, now)

    def _track_download_sync(self, user_id, url, platform, media_format, quality,
                              filesize, duration, title, success, error,
                              download_time_ms, now):
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO downloads
                (user_id, url, platform, media_format, quality, filesize, duration,
                 title, success, error, download_time_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_id, url, platform, media_format, quality, filesize, duration,
                  title, int(success), error, download_time_ms, now))

    async def get_global_stats(self) -> GlobalStats:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._global_stats_sync)

    def _global_stats_sync(self) -> GlobalStats:
        now = time.time()
        day_ago = now - 86400
        week_ago = now - 604800

        with self._conn() as conn:
            total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            active_today = conn.execute(
                "SELECT COUNT(*) FROM users WHERE last_active > ?", (day_ago,)
            ).fetchone()[0]
            active_week = conn.execute(
                "SELECT COUNT(*) FROM users WHERE last_active > ?", (week_ago,)
            ).fetchone()[0]

            new_users_today = conn.execute(
                "SELECT COUNT(*) FROM users WHERE first_seen > ?", (day_ago,)
            ).fetchone()[0]
            new_users_week = conn.execute(
                "SELECT COUNT(*) FROM users WHERE first_seen > ?", (week_ago,)
            ).fetchone()[0]

            total_downloads = conn.execute(
                "SELECT COUNT(*) FROM downloads WHERE success = 1"
            ).fetchone()[0]
            total_bytes = conn.execute(
                "SELECT COALESCE(SUM(filesize), 0) FROM downloads WHERE success = 1"
            ).fetchone()[0]
            downloads_today = conn.execute(
                "SELECT COUNT(*) FROM downloads WHERE created_at > ? AND success = 1",
                (day_ago,)
            ).fetchone()[0]

            unique_urls_today = conn.execute(
                "SELECT COUNT(DISTINCT url) FROM downloads WHERE created_at > ? AND success = 1",
                (day_ago,)
            ).fetchone()[0]

            top_platforms = conn.execute("""
                SELECT platform, COUNT(*) as cnt FROM downloads
                WHERE success = 1 AND platform IS NOT NULL
                GROUP BY platform ORDER BY cnt DESC LIMIT 10
            """).fetchall()

            top_formats = conn.execute("""
                SELECT media_format, COUNT(*) as cnt FROM downloads
                WHERE success = 1
                GROUP BY media_format ORDER BY cnt DESC LIMIT 5
            """).fetchall()

            avg_row = conn.execute(
                "SELECT AVG(filesize) FROM downloads WHERE success = 1 AND filesize > 0"
            ).fetchone()
            avg_filesize = int(avg_row[0]) if avg_row[0] else 0

            avg_dl_row = conn.execute(
                "SELECT AVG(download_time_ms) FROM downloads WHERE success = 1 AND download_time_ms > 0"
            ).fetchone()
            avg_download_time_ms = int(avg_dl_row[0]) if avg_dl_row[0] else 0

            peak_row = conn.execute("""
                SELECT CAST(strftime('%H', created_at, 'unixepoch') AS INTEGER) as hr,
                       COUNT(*) as cnt
                FROM downloads WHERE success = 1
                GROUP BY hr ORDER BY cnt DESC LIMIT 1
            """).fetchone()
            peak_hour = peak_row[0] if peak_row else None

            total_attempts = conn.execute("SELECT COUNT(*) FROM downloads").fetchone()[0]
            failed = conn.execute(
                "SELECT COUNT(*) FROM downloads WHERE success = 0"
            ).fetchone()[0]
            error_rate = failed / total_attempts if total_attempts > 0 else 0.0

            top_languages = conn.execute("""
                SELECT language_code, COUNT(*) as cnt FROM users
                WHERE language_code IS NOT NULL
                GROUP BY language_code ORDER BY cnt DESC LIMIT 5
            """).fetchall()

            two_days_ago = now - 172800
            cohort = conn.execute(
                "SELECT COUNT(*) FROM users WHERE first_seen BETWEEN ? AND ?",
                (two_days_ago, day_ago),
            ).fetchone()[0]
            returned = conn.execute("""
                SELECT COUNT(DISTINCT u.user_id) FROM users u
                JOIN downloads d ON d.user_id = u.user_id
                WHERE u.first_seen BETWEEN ? AND ?
                AND d.created_at > ?
            """, (two_days_ago, day_ago, day_ago)).fetchone()[0]
            retention_d1 = returned / cohort if cohort > 0 else 0.0

        return GlobalStats(
            total_users=total_users,
            active_today=active_today,
            active_week=active_week,
            total_downloads=total_downloads,
            total_bytes=total_bytes,
            downloads_today=downloads_today,
            top_platforms=top_platforms,
            top_formats=top_formats,
            avg_filesize=avg_filesize,
            peak_hour=peak_hour,
            error_rate=error_rate,
            new_users_today=new_users_today,
            new_users_week=new_users_week,
            avg_download_time_ms=avg_download_time_ms,
            top_languages=top_languages,
            retention_d1=retention_d1,
            unique_urls_today=unique_urls_today,
        )

    async def get_user_stats(self, user_id: int) -> UserStats | None:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._user_stats_sync, user_id)

    def _user_stats_sync(self, user_id: int) -> UserStats | None:
        with self._conn() as conn:
            user = conn.execute(
                "SELECT first_seen, last_active FROM users WHERE user_id = ?",
                (user_id,)
            ).fetchone()
            if not user:
                return None

            total = conn.execute(
                "SELECT COUNT(*) FROM downloads WHERE user_id = ? AND success = 1",
                (user_id,)
            ).fetchone()[0]
            total_bytes = conn.execute(
                "SELECT COALESCE(SUM(filesize), 0) FROM downloads WHERE user_id = ? AND success = 1",
                (user_id,)
            ).fetchone()[0]

            fav_platform = conn.execute("""
                SELECT platform, COUNT(*) as cnt FROM downloads
                WHERE user_id = ? AND success = 1 AND platform IS NOT NULL
                GROUP BY platform ORDER BY cnt DESC LIMIT 1
            """, (user_id,)).fetchone()

            fav_format = conn.execute("""
                SELECT media_format, COUNT(*) as cnt FROM downloads
                WHERE user_id = ? AND success = 1
                GROUP BY media_format ORDER BY cnt DESC LIMIT 1
            """, (user_id,)).fetchone()

            return UserStats(
                user_id=user_id,
                total_downloads=total,
                total_bytes=total_bytes,
                first_seen=user[0],
                last_active=user[1],
                favorite_platform=fav_platform[0] if fav_platform else None,
                favorite_format=fav_format[0] if fav_format else None,
            )

    async def get_recent_errors(self, limit: int = 10) -> list[dict]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._recent_errors_sync, limit)

    def _recent_errors_sync(self, limit: int) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT url, platform, error, created_at
                FROM downloads WHERE success = 0
                ORDER BY created_at DESC LIMIT ?
            """, (limit,)).fetchall()
            return [{"url": r[0], "platform": r[1], "error": r[2], "at": r[3]} for r in rows]

    async def get_top_users(self, limit: int = 10) -> list[dict]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._top_users_sync, limit)

    def _top_users_sync(self, limit: int) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT u.user_id, u.username, u.first_name,
                       COUNT(d.id) as cnt,
                       COALESCE(SUM(d.filesize), 0) as total_bytes
                FROM users u
                JOIN downloads d ON d.user_id = u.user_id AND d.success = 1
                GROUP BY u.user_id
                ORDER BY cnt DESC LIMIT ?
            """, (limit,)).fetchall()
            return [
                {"user_id": r[0], "username": r[1], "first_name": r[2],
                 "downloads": r[3], "total_bytes": r[4]}
                for r in rows
            ]

    async def get_recent_users(self, limit: int = 10) -> list[dict]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._recent_users_sync, limit)

    def _recent_users_sync(self, limit: int) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT user_id, username, first_name, language_code,
                       is_premium, first_seen, start_param
                FROM users ORDER BY first_seen DESC LIMIT ?
            """, (limit,)).fetchall()
            return [
                {"user_id": r[0], "username": r[1], "first_name": r[2],
                 "language": r[3], "is_premium": bool(r[4]),
                 "first_seen": r[5], "start_param": r[6]}
                for r in rows
            ]

    async def get_recent_downloads(self, limit: int = 10) -> list[dict]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._recent_downloads_sync, limit)

    def _recent_downloads_sync(self, limit: int) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT d.title, d.platform, d.media_format, d.filesize,
                       d.download_time_ms, d.created_at, u.username
                FROM downloads d
                LEFT JOIN users u ON u.user_id = d.user_id
                WHERE d.success = 1
                ORDER BY d.created_at DESC LIMIT ?
            """, (limit,)).fetchall()
            return [
                {"title": r[0], "platform": r[1], "format": r[2],
                 "filesize": r[3], "time_ms": r[4], "at": r[5],
                 "username": r[6]}
                for r in rows
            ]

    async def get_daily_chart(self, days: int = 30) -> list[tuple[str, int]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._daily_chart_sync, days)

    def _daily_chart_sync(self, days: int) -> list[tuple[str, int]]:
        cutoff = time.time() - days * 86400
        with self._conn() as conn:
            return conn.execute("""
                SELECT date(created_at, 'unixepoch') as day, COUNT(*) as cnt
                FROM downloads WHERE success = 1 AND created_at > ?
                GROUP BY day ORDER BY day
            """, (cutoff,)).fetchall()

    # ---- premium / quotas ----

    async def get_user_row(self, user_id: int) -> dict | None:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_user_row_sync, user_id)

    def _get_user_row_sync(self, user_id: int) -> dict | None:
        with self._conn() as conn:
            r = conn.execute(
                "SELECT user_id, username, first_seen, premium_until, "
                "bonus_bytes FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            if not r:
                return None
            return {
                "user_id": r[0], "username": r[1], "first_seen": r[2],
                "premium_until": r[3] or 0.0, "bonus_bytes": r[4] or 0,
            }

    async def get_user_usage_today(self, user_id: int) -> tuple[int, int]:
        """Returns (files_today, bytes_today) for successful downloads."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._usage_today_sync, user_id)

    def _usage_today_sync(self, user_id: int) -> tuple[int, int]:
        day_ago = time.time() - 86400
        with self._conn() as conn:
            r = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(filesize), 0) FROM downloads "
                "WHERE user_id = ? AND success = 1 AND created_at > ?",
                (user_id, day_ago),
            ).fetchone()
            return (int(r[0] or 0), int(r[1] or 0))

    async def set_premium(self, user_id: int, until_ts: float) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._set_premium_sync, user_id, until_ts)

    def _set_premium_sync(self, user_id: int, until_ts: float) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE users SET premium_until = ? WHERE user_id = ?",
                (until_ts, user_id),
            )

    async def extend_premium(self, user_id: int, add_seconds: float) -> float:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._extend_premium_sync, user_id, add_seconds
        )

    def _extend_premium_sync(self, user_id: int, add_seconds: float) -> float:
        now = time.time()
        with self._conn() as conn:
            r = conn.execute(
                "SELECT premium_until FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            current = float(r[0]) if r and r[0] else 0.0
            base = max(current, now)
            new_until = base + add_seconds
            conn.execute(
                "UPDATE users SET premium_until = ? WHERE user_id = ?",
                (new_until, user_id),
            )
        return new_until

    async def add_bonus_bytes(self, user_id: int, add_bytes: int) -> int:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._add_bonus_sync, user_id, add_bytes
        )

    def _add_bonus_sync(self, user_id: int, add_bytes: int) -> int:
        with self._conn() as conn:
            conn.execute(
                "UPDATE users SET bonus_bytes = COALESCE(bonus_bytes, 0) + ? "
                "WHERE user_id = ?", (add_bytes, user_id),
            )
            r = conn.execute(
                "SELECT bonus_bytes FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            return int(r[0] or 0)

    async def consume_bonus_bytes(self, user_id: int, used: int) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._consume_bonus_sync, user_id, used)

    def _consume_bonus_sync(self, user_id: int, used: int) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE users SET bonus_bytes = MAX(0, COALESCE(bonus_bytes,0) - ?) "
                "WHERE user_id = ?", (used, user_id),
            )

    async def record_payment(
        self, user_id: int, kind: str, stars: int, charge_id: str | None = None
    ) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, self._record_payment_sync, user_id, kind, stars, charge_id
        )

    def _record_payment_sync(self, user_id, kind, stars, charge_id):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO payments (user_id, kind, stars, charge_id, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, kind, stars, charge_id, time.time()),
            )

    async def revenue_stats(self) -> dict:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._revenue_sync)

    def _revenue_sync(self) -> dict:
        day_ago = time.time() - 86400
        with self._conn() as conn:
            total = conn.execute(
                "SELECT COALESCE(SUM(stars), 0), COUNT(*) FROM payments"
            ).fetchone()
            today = conn.execute(
                "SELECT COALESCE(SUM(stars), 0), COUNT(*) FROM payments "
                "WHERE created_at > ?", (day_ago,),
            ).fetchone()
            return {
                "total_stars": int(total[0] or 0),
                "total_count": int(total[1] or 0),
                "today_stars": int(today[0] or 0),
                "today_count": int(today[1] or 0),
            }

    # ---- pending URLs ----

    async def save_pending_url(
        self, url_id: str, user_id: int, url: str, formats: list | None = None
    ) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, self._save_pending_sync, url_id, user_id, url, formats
        )

    def _save_pending_sync(self, url_id, user_id, url, formats):
        payload = json.dumps(formats) if formats else None
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO pending_urls "
                "(url_id, user_id, url, formats_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (url_id, user_id, url, payload, time.time()),
            )

    async def get_pending_url(self, url_id: str) -> dict | None:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_pending_sync, url_id)

    def _get_pending_sync(self, url_id: str) -> dict | None:
        cutoff = time.time() - PENDING_TTL_S
        with self._conn() as conn:
            r = conn.execute(
                "SELECT url, user_id, formats_json, created_at "
                "FROM pending_urls WHERE url_id = ? AND created_at > ?",
                (url_id, cutoff),
            ).fetchone()
            if not r:
                return None
            formats = json.loads(r[2]) if r[2] else None
            return {
                "url": r[0], "user_id": r[1],
                "formats": formats, "created_at": r[3],
            }

    async def cleanup_pending(self) -> int:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._cleanup_pending_sync)

    def _cleanup_pending_sync(self) -> int:
        cutoff = time.time() - PENDING_TTL_S
        cutoff_r = time.time() - AWAITING_TTL_S
        with self._conn() as conn:
            n1 = conn.execute(
                "DELETE FROM pending_urls WHERE created_at < ?", (cutoff,)
            ).rowcount
            n2 = conn.execute(
                "DELETE FROM awaiting_range WHERE created_at < ?", (cutoff_r,)
            ).rowcount
            return int(n1 + n2)

    async def set_awaiting_range(self, user_id: int, url_id: str) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, self._set_awaiting_sync, user_id, url_id
        )

    def _set_awaiting_sync(self, user_id, url_id):
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO awaiting_range "
                "(user_id, url_id, created_at) VALUES (?, ?, ?)",
                (user_id, url_id, time.time()),
            )

    async def get_awaiting_range(self, user_id: int) -> str | None:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_awaiting_sync, user_id)

    def _get_awaiting_sync(self, user_id: int) -> str | None:
        cutoff = time.time() - AWAITING_TTL_S
        with self._conn() as conn:
            r = conn.execute(
                "SELECT url_id FROM awaiting_range "
                "WHERE user_id = ? AND created_at > ?",
                (user_id, cutoff),
            ).fetchone()
            return r[0] if r else None

    async def clear_awaiting_range(self, user_id: int) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._clear_awaiting_sync, user_id)

    def _clear_awaiting_sync(self, user_id: int):
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM awaiting_range WHERE user_id = ?", (user_id,)
            )

    # ---- shutdown ----

    async def wal_checkpoint(self) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._wal_checkpoint_sync)

    def _wal_checkpoint_sync(self) -> None:
        try:
            with self._conn() as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass
