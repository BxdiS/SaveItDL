from __future__ import annotations

import asyncio
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path


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
                    total_sessions INTEGER DEFAULT 1
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
