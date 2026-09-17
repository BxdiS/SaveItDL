from __future__ import annotations

import hashlib
import logging
import os
import re
from collections import OrderedDict
from pathlib import Path

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from core.downloader import Downloader
from core.models import DownloadResult, MediaFormat, MediaInfo
from core.stats import StatsDB
from core.worker_pool import DownloadJob, WorkerPool
from platforms.base import BasePlatform

logger = logging.getLogger(__name__)

URL_REGEX = re.compile(r"https?://\S+")
TWITCH_VOD_REGEX = re.compile(r"twitch\.tv/videos/(\d+)")
TELEGRAM_FILE_LIMIT_DEFAULT = 50 * 1024 * 1024
TELEGRAM_FILE_LIMIT_LOCAL = 2000 * 1024 * 1024
MAX_PENDING = 5000
VOD_DURATION_LIMIT = 30 * 60

AUDIO_PLATFORMS = {"SoundCloud", "Bandcamp", "Mixcloud"}

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 My Stats"), KeyboardButton(text="❓ Help")],
    ],
    resize_keyboard=True,
    is_persistent=True,
)


def _format_size(size_bytes: int | None) -> str:
    if not size_bytes:
        return "~"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.0f}KB"
    return f"{size_bytes / (1024 * 1024):.1f}MB"


def _format_duration(seconds: int | None) -> str:
    if not seconds:
        return ""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _parse_timestamp(ts: str) -> int | None:
    ts = ts.strip()
    parts = ts.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        if len(parts) == 1:
            return int(parts[0]) * 60
    except ValueError:
        return None
    return None


def _short_id(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:10]


def _is_audio_platform(info: MediaInfo) -> bool:
    if info.platform in AUDIO_PLATFORMS:
        return True
    has_video = any(not f.is_audio_only for f in info.formats)
    return not has_video


def _is_twitch_vod(url: str) -> bool:
    return bool(TWITCH_VOD_REGEX.search(url))


def _build_video_buttons(info: MediaInfo, url_id: str) -> InlineKeyboardMarkup:
    video_formats = []
    seen_quality = set()
    for i, f in enumerate(info.formats):
        if f.is_audio_only:
            continue
        q = str(f.quality)
        if q in seen_quality:
            continue
        seen_quality.add(q)
        video_formats.append((i, f))

    video_formats.sort(key=lambda x: _quality_sort_key(x[1].quality), reverse=True)

    rows = []
    for i, f in video_formats[:5]:
        q = str(f.quality)
        if q.isdigit():
            q = f"{q}p"
        label = f"🎬 {q}  ·  {f.ext}  ·  {_format_size(f.filesize)}"
        rows.append([InlineKeyboardButton(
            text=label,
            callback_data=f"f:{url_id}:v:{i}",
        )])

    rows.append([
        InlineKeyboardButton(text="⬇️ Best Video", callback_data=f"q:{url_id}:video"),
        InlineKeyboardButton(text="🎵 MP3", callback_data=f"q:{url_id}:audio"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _quality_sort_key(quality: str) -> int:
    q = str(quality).rstrip("pk").split("x")[-1]
    try:
        return int(q)
    except ValueError:
        return 0


def _build_audio_buttons(info: MediaInfo, url_id: str) -> InlineKeyboardMarkup:
    rows = []
    seen = set()
    for i, f in enumerate(info.formats):
        q = str(f.quality)
        if q in seen:
            continue
        seen.add(q)
        label = f"🎵 {q}  ·  {f.ext}  ·  {_format_size(f.filesize)}"
        rows.append([InlineKeyboardButton(
            text=label,
            callback_data=f"f:{url_id}:a:{i}",
        )])
        if len(rows) >= 5:
            break

    rows.append([InlineKeyboardButton(
        text="🎵 Best Audio (MP3)",
        callback_data=f"q:{url_id}:audio",
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


BANNER_PATH = Path(__file__).resolve().parent.parent / "assets" / "banner.jpg"

WELCOME_TEXT = (
    "🎬 <b>SaveItDL</b>\n\n"
    "Скачивай видео и аудио с любых платформ.\n"
    "Просто отправь ссылку."
)

WELCOME_KEYBOARD = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="📎  Отправить ссылку", callback_data="menu:hint")],
    [InlineKeyboardButton(text="📊  Моя статистика", callback_data="menu:stats")],
    [InlineKeyboardButton(text="❓  Как пользоваться", callback_data="menu:help")],
    [InlineKeyboardButton(text="📢  Канал обновлений", url="https://t.me/SaveItDLnews")],
])

HELP_TEXT = (
    "━━━━━━━━━━━━━━━━━━━━\n"
    "    ❓  <b>Помощь</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n\n"
    "<b>Как пользоваться:</b>\n"
    "1️⃣ Отправь мне ссылку на видео или аудио\n"
    "2️⃣ Я определю контент и покажу качества\n"
    "3️⃣ Выбери — и файл придёт в чат\n\n"
    "<b>Команды:</b>\n"
    "/start — Главное меню\n"
    "/stats — Твоя статистика\n\n"
    "<b>Поддержка:</b>\n"
    "▸ Видео: 1080p / 720p / 480p\n"
    "▸ Аудио: MP3 / лучшее качество\n"
    "▸ Twitch VOD: скачивание фрагмента\n\n"
    "📎 <i>Лимит файла: 50 МБ (ограничение Telegram)</i>"
)


class TelegramPlatform(BasePlatform):
    name = "telegram"

    def __init__(self, token: str, downloader: Downloader, pool: WorkerPool,
                 stats: StatsDB | None = None, admin_id: int | None = None,
                 api_url: str | None = None):
        super().__init__(token, downloader)
        self._api_url = api_url
        if api_url:
            base = api_url.rstrip("/")
            if base.endswith("/bot"):
                base = base[:-4]
            logger.info("Using local Bot API: %s", base)
            self.bot = Bot(token=token, base_url=base)
            self._file_limit = TELEGRAM_FILE_LIMIT_LOCAL
        else:
            self.bot = Bot(token=token)
            self._file_limit = TELEGRAM_FILE_LIMIT_DEFAULT
        logger.info("Banner path: %s, exists: %s", BANNER_PATH, BANNER_PATH.exists())
        self.dp = Dispatcher()
        self._pool = pool
        self._stats = stats
        self._admin_id = admin_id
        self._pending_urls: OrderedDict[str, str] = OrderedDict()
        self._pending_info: OrderedDict[str, MediaInfo] = OrderedDict()
        self._awaiting_range: dict[int, str] = {}
        self._register_handlers()

    def _store_url(self, url: str, info: MediaInfo | None = None) -> str:
        uid = _short_id(url)
        self._pending_urls[uid] = url
        if info:
            self._pending_info[uid] = info
        while len(self._pending_urls) > MAX_PENDING:
            k, _ = self._pending_urls.popitem(last=False)
            self._pending_info.pop(k, None)
        return uid

    def _get_url(self, uid: str) -> str | None:
        return self._pending_urls.get(uid)

    async def _track_user(self, user: types.User, start_param: str | None = None):
        if not self._stats:
            return
        await self._stats.track_user(
            user.id, user.username, user.first_name,
            user.language_code, last_name=user.last_name,
            is_premium=bool(user.is_premium),
            start_param=start_param,
        )

    def _register_handlers(self):
        @self.dp.update.outer_middleware()
        async def log_updates(handler, event, data):
            logger.info(
                "Update type=%s id=%s",
                event.event_type,
                event.update_id,
            )
            return await handler(event, data)

        @self.dp.message(CommandStart())
        async def cmd_start(message: types.Message):
            start_param = None
            if message.text and " " in message.text:
                start_param = message.text.split(" ", 1)[1]

            await self._track_user(message.from_user, start_param=start_param)
            if self._stats:
                await self._stats.track_action(message.from_user.id, "start", start_param)

            banner = BANNER_PATH
            logger.info("Banner path: %s, exists: %s", banner, banner.exists())
            if banner.exists():
                try:
                    await message.answer_photo(
                        photo=FSInputFile(banner),
                        caption=WELCOME_TEXT,
                        parse_mode="HTML",
                        reply_markup=WELCOME_KEYBOARD,
                    )
                except Exception as e:
                    logger.exception("Failed to send banner")
                    await message.answer(
                        WELCOME_TEXT,
                        parse_mode="HTML",
                        reply_markup=WELCOME_KEYBOARD,
                    )
            else:
                await message.answer(
                    WELCOME_TEXT,
                    parse_mode="HTML",
                    reply_markup=WELCOME_KEYBOARD,
                )
            await message.answer(
                "⬇️ Вставь ссылку:",
                reply_markup=MAIN_KEYBOARD,
            )

        @self.dp.message(Command("stats"))
        async def cmd_stats(message: types.Message):
            await self._send_user_stats(message)

        @self.dp.message(F.text == "📊 My Stats")
        async def btn_stats(message: types.Message):
            await self._send_user_stats(message)

        @self.dp.message(F.text == "❓ Help")
        async def btn_help(message: types.Message):
            if self._stats:
                await self._stats.track_action(message.from_user.id, "help")
            await message.answer(HELP_TEXT, parse_mode="HTML")

        @self.dp.message(Command("admin"))
        async def cmd_admin(message: types.Message):
            if not self._is_admin(message.from_user.id):
                await message.answer("⛔ Только для администратора.")
                return
            await self._send_admin_main(message)

        @self.dp.message(Command("adminstats"))
        async def cmd_adminstats(message: types.Message):
            if not self._is_admin(message.from_user.id):
                await message.answer("⛔ Только для администратора.")
                return
            await self._send_admin_main(message)

        @self.dp.message(Command("errors"))
        async def cmd_errors(message: types.Message):
            if not self._is_admin(message.from_user.id):
                await message.answer("⛔ Только для администратора.")
                return
            await self._send_admin_errors(message)

        @self.dp.callback_query(F.data.startswith("menu:"))
        async def handle_menu(callback: types.CallbackQuery):
            action = callback.data.split(":")[1]
            if action == "hint":
                await callback.answer("Просто отправь ссылку в чат!", show_alert=True)
            elif action == "stats":
                await callback.answer()
                await self._send_user_stats(callback.message)
            elif action == "help":
                await callback.answer()
                await callback.message.answer(HELP_TEXT, parse_mode="HTML")

        @self.dp.callback_query(F.data.startswith("adm:"))
        async def handle_admin_nav(callback: types.CallbackQuery):
            if not self._is_admin(callback.from_user.id):
                await callback.answer("⛔ Admin only", show_alert=True)
                return
            await callback.answer()
            section = callback.data.split(":")[1]
            if section == "main":
                await self._edit_admin_main(callback.message)
            elif section == "users":
                await self._edit_admin_users(callback.message)
            elif section == "downloads":
                await self._edit_admin_downloads(callback.message)
            elif section == "errors":
                await self._edit_admin_errors(callback.message)
            elif section == "top":
                await self._edit_admin_top(callback.message)
            elif section == "recent":
                await self._edit_admin_recent(callback.message)

        @self.dp.message(F.text)
        async def handle_message(message: types.Message):
            user_id = message.from_user.id
            await self._track_user(message.from_user)

            if user_id in self._awaiting_range:
                await self._handle_vod_range(message)
                return

            urls = URL_REGEX.findall(message.text or "")
            if not urls:
                await message.answer(
                    "📎 <i>Отправь мне ссылку на видео или аудио.</i>",
                    parse_mode="HTML",
                )
                return
            url = urls[0]

            if self._stats:
                await self._stats.track_action(user_id, "url_sent", url[:200])

            status_msg = await message.answer("🔍 <i>Анализирую ссылку...</i>", parse_mode="HTML")

            try:
                info = await self.downloader.get_info(url)
            except Exception as e:
                logger.warning("Info extraction failed for %s: %s", url, e)
                await status_msg.edit_text("❌ Не удалось обработать ссылку.")
                return

            url_id = self._store_url(url, info)
            duration = info.duration or 0

            if _is_twitch_vod(url) and duration > VOD_DURATION_LIMIT:
                self._awaiting_range[user_id] = url_id
                await status_msg.edit_text(
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"📺 <b>{info.title}</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"⏱ <b>{_format_duration(duration)}</b> — VOD дольше 30 минут.\n\n"
                    f"Отправь промежуток для скачивания:\n"
                    f"<code>0:00 - 15:00</code>  или  <code>1:30:00 - 2:00:00</code>\n\n"
                    f"Или нажми кнопку ниже:",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(
                            text="⬇️ Первые 30 мин",
                            callback_data=f"vod:{url_id}:0:1800",
                        ),
                        InlineKeyboardButton(
                            text="❌ Отмена",
                            callback_data=f"vod:{url_id}:cancel",
                        ),
                    ]]),
                )
                return

            header = f"━━━━━━━━━━━━━━━━━━━━\n"
            is_audio = _is_audio_platform(info)
            icon = "🎵" if is_audio else "🎬"
            header += f"{icon} <b>{info.title}</b>\n"
            header += "━━━━━━━━━━━━━━━━━━━━\n\n"

            details = []
            if info.uploader:
                details.append(f"👤 {info.uploader}")
            if duration:
                details.append(f"⏱ {_format_duration(duration)}")
            if info.platform:
                details.append(f"📍 {info.platform}")
            if details:
                header += "\n".join(details) + "\n"

            if info.formats:
                header += "\n<b>Выбери качество:</b>"
                if is_audio:
                    kb = _build_audio_buttons(info, url_id)
                else:
                    kb = _build_video_buttons(info, url_id)
            else:
                if is_audio:
                    kb = InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text="🎵 Best Audio (MP3)", callback_data=f"q:{url_id}:audio"),
                    ]])
                else:
                    kb = InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text="⬇️ Best Video", callback_data=f"q:{url_id}:video"),
                        InlineKeyboardButton(text="🎵 MP3", callback_data=f"q:{url_id}:audio"),
                    ]])

            await status_msg.edit_text(header, reply_markup=kb, parse_mode="HTML")

        @self.dp.callback_query(F.data.startswith("q:"))
        async def handle_quick_download(callback: types.CallbackQuery):
            await callback.answer()
            parts = callback.data.split(":")
            if len(parts) < 3:
                return
            _, url_id, fmt = parts
            url = self._get_url(url_id)
            if not url:
                await callback.message.edit_text("⏳ Ссылка устарела. Отправь заново.")
                return
            media_format = MediaFormat.AUDIO if fmt == "audio" else MediaFormat.VIDEO
            if self._stats:
                await self._stats.track_action(callback.from_user.id, "quality_pick", fmt)
            await self._start_download(
                callback.message, url, media_format,
                user_id=callback.from_user.id, url_id=url_id,
            )

        @self.dp.callback_query(F.data.startswith("f:"))
        async def handle_format_download(callback: types.CallbackQuery):
            await callback.answer()
            parts = callback.data.split(":")
            if len(parts) < 4:
                return
            _, url_id, kind, fmt_idx = parts
            url = self._get_url(url_id)
            if not url:
                await callback.message.edit_text("⏳ Ссылка устарела. Отправь заново.")
                return

            format_id = None
            info = self._pending_info.get(url_id)
            if info:
                try:
                    idx = int(fmt_idx)
                    if 0 <= idx < len(info.formats):
                        format_id = info.formats[idx].format_id
                except (ValueError, IndexError):
                    pass

            media_format = MediaFormat.AUDIO if kind == "a" else MediaFormat.VIDEO
            if self._stats:
                await self._stats.track_action(callback.from_user.id, "format_pick", f"{kind}:{format_id}")
            await self._start_download(
                callback.message, url, media_format, format_id,
                user_id=callback.from_user.id, url_id=url_id,
            )

        @self.dp.callback_query(F.data.startswith("vod:"))
        async def handle_vod_callback(callback: types.CallbackQuery):
            await callback.answer()
            parts = callback.data.split(":")
            if len(parts) < 3:
                return
            _, url_id = parts[0], parts[1]

            user_id = callback.from_user.id
            self._awaiting_range.pop(user_id, None)

            if parts[2] == "cancel":
                await callback.message.edit_text("❌ Отменено.")
                return

            start_sec = int(parts[2])
            end_sec = int(parts[3])
            url = self._get_url(url_id)
            if not url:
                await callback.message.edit_text("⏳ Ссылка устарела. Отправь заново.")
                return
            await self._start_download(
                callback.message, url, MediaFormat.VIDEO,
                download_range=(start_sec, end_sec),
                user_id=callback.from_user.id, url_id=url_id,
            )

    def _is_admin(self, user_id: int) -> bool:
        return bool(self._admin_id and user_id == self._admin_id)

    def _admin_nav(self, current: str = "") -> InlineKeyboardMarkup:
        buttons = {
            "main": "📊 Overview",
            "users": "👥 Users",
            "downloads": "⬇️ Downloads",
            "top": "🏆 Top Users",
            "recent": "🕐 Recent",
            "errors": "🔴 Errors",
        }
        rows = []
        row = []
        for key, label in buttons.items():
            if key == current:
                continue
            row.append(InlineKeyboardButton(text=label, callback_data=f"adm:{key}"))
            if len(row) == 3:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def _send_admin_main(self, message: types.Message):
        text = await self._build_admin_overview()
        await message.answer(text, parse_mode="HTML", reply_markup=self._admin_nav("main"))

    async def _edit_admin_main(self, message: types.Message):
        text = await self._build_admin_overview()
        await message.edit_text(text, parse_mode="HTML", reply_markup=self._admin_nav("main"))

    async def _build_admin_overview(self) -> str:
        if not self._stats:
            return "Stats not available."
        gs = await self._stats.get_global_stats()
        total_gb = gs.total_bytes / (1024 ** 3)
        avg_sec = gs.avg_download_time_ms / 1000 if gs.avg_download_time_ms else 0
        return (
            "━━━━━━━━━━━━━━━━━━━━\n"
            "    📊  <b>Admin Panel</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👥 <b>Users: {gs.total_users}</b>\n"
            f"  ▸ Active today: {gs.active_today}\n"
            f"  ▸ Active week: {gs.active_week}\n"
            f"  ▸ New today: +{gs.new_users_today}\n"
            f"  ▸ New week: +{gs.new_users_week}\n"
            f"  ▸ D1 retention: {gs.retention_d1:.0%}\n\n"
            f"⬇️ <b>Downloads: {gs.total_downloads}</b>\n"
            f"  ▸ Today: {gs.downloads_today}\n"
            f"  ▸ Unique URLs: {gs.unique_urls_today}\n"
            f"  ▸ Traffic: {total_gb:.2f} GB\n"
            f"  ▸ Avg size: {_format_size(gs.avg_filesize)}\n"
            f"  ▸ Avg speed: {avg_sec:.1f}s\n"
            f"  ▸ Error rate: {gs.error_rate:.1%}\n"
            f"  ▸ Peak hour: {gs.peak_hour}:00 UTC\n\n"
            f"🌐 <b>Languages:</b>\n"
            + ("\n".join(f"  ▸ {l}: <b>{c}</b>" for l, c in gs.top_languages) or "  —")
        )

    async def _edit_admin_users(self, message: types.Message):
        if not self._stats:
            return
        users = await self._stats.get_recent_users(10)
        if not users:
            await message.edit_text("Нет пользователей.", reply_markup=self._admin_nav("users"))
            return

        import datetime
        lines = []
        for u in users:
            name = u["username"] or u["first_name"] or str(u["user_id"])
            if u["username"]:
                name = f"@{name}"
            dt = datetime.datetime.fromtimestamp(u["first_seen"]).strftime("%d.%m %H:%M")
            premium = " ⭐" if u["is_premium"] else ""
            ref = f" ← {u['start_param']}" if u["start_param"] else ""
            lines.append(f"▸ <b>{name}</b>{premium}  {u['language'] or '?'}  {dt}{ref}")

        text = (
            "━━━━━━━━━━━━━━━━━━━━\n"
            "    👥  <b>Recent Users</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            + "\n".join(lines)
        )
        await message.edit_text(text, parse_mode="HTML", reply_markup=self._admin_nav("users"))

    async def _edit_admin_downloads(self, message: types.Message):
        if not self._stats:
            return
        gs = await self._stats.get_global_stats()
        platforms = "\n".join(f"  ▸ {p}: <b>{c}</b>" for p, c in gs.top_platforms[:10]) or "  —"
        formats = "\n".join(f"  ▸ {f}: <b>{c}</b>" for f, c in gs.top_formats) or "  —"

        text = (
            "━━━━━━━━━━━━━━━━━━━━\n"
            "    ⬇️  <b>Downloads</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<b>By platform:</b>\n{platforms}\n\n"
            f"<b>By format:</b>\n{formats}"
        )
        await message.edit_text(text, parse_mode="HTML", reply_markup=self._admin_nav("downloads"))

    async def _edit_admin_top(self, message: types.Message):
        if not self._stats:
            return
        users = await self._stats.get_top_users(10)
        if not users:
            await message.edit_text("Нет данных.", reply_markup=self._admin_nav("top"))
            return

        lines = []
        for i, u in enumerate(users, 1):
            name = u["username"] or u["first_name"] or str(u["user_id"])
            if u["username"]:
                name = f"@{name}"
            medal = ["🥇", "🥈", "🥉"][i - 1] if i <= 3 else f"{i}."
            lines.append(
                f"{medal} <b>{name}</b> — {u['downloads']} dl · {_format_size(u['total_bytes'])}"
            )

        text = (
            "━━━━━━━━━━━━━━━━━━━━\n"
            "    🏆  <b>Top Users</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            + "\n".join(lines)
        )
        await message.edit_text(text, parse_mode="HTML", reply_markup=self._admin_nav("top"))

    async def _edit_admin_recent(self, message: types.Message):
        if not self._stats:
            return
        downloads = await self._stats.get_recent_downloads(10)
        if not downloads:
            await message.edit_text("Нет скачиваний.", reply_markup=self._admin_nav("recent"))
            return

        import datetime
        lines = []
        for d in downloads:
            title = (d["title"] or "?")[:30]
            user = f"@{d['username']}" if d["username"] else "anon"
            dt = datetime.datetime.fromtimestamp(d["at"]).strftime("%H:%M")
            speed = f"{d['time_ms'] / 1000:.1f}s" if d["time_ms"] else "?"
            lines.append(
                f"▸ {dt}  <b>{title}</b>\n"
                f"    {d['platform'] or '?'} · {d['format']} · {_format_size(d['filesize'])} · {speed} · {user}"
            )

        text = (
            "━━━━━━━━━━━━━━━━━━━━\n"
            "    🕐  <b>Recent Downloads</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            + "\n".join(lines)
        )
        await message.edit_text(text, parse_mode="HTML", reply_markup=self._admin_nav("recent"))

    async def _send_admin_errors(self, message: types.Message):
        text = await self._build_admin_errors()
        await message.answer(text, parse_mode="HTML", reply_markup=self._admin_nav("errors"))

    async def _edit_admin_errors(self, message: types.Message):
        text = await self._build_admin_errors()
        await message.edit_text(text, parse_mode="HTML", reply_markup=self._admin_nav("errors"))

    async def _build_admin_errors(self) -> str:
        if not self._stats:
            return "Stats not available."
        errors = await self._stats.get_recent_errors(10)
        if not errors:
            return (
                "━━━━━━━━━━━━━━━━━━━━\n"
                "    ✅  <b>No Errors</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "Всё работает штатно."
            )
        lines = []
        for e in errors:
            lines.append(f"▸ <b>{e['platform'] or '?'}</b>: {e['error'][:80]}")
        return (
            "━━━━━━━━━━━━━━━━━━━━\n"
            "    🔴  <b>Recent Errors</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            + "\n".join(lines)
        )

    async def _send_user_stats(self, message: types.Message):
        if self._stats:
            await self._stats.track_action(message.from_user.id, "stats_view")

        if not self._stats:
            await message.answer("Статистика недоступна.")
            return
        user_id = message.from_user.id
        us = await self._stats.get_user_stats(user_id)
        if not us:
            await message.answer(
                "━━━━━━━━━━━━━━━━━━━━\n"
                "    📊  <b>Твоя статистика</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "<i>Пока нет скачиваний. Отправь ссылку!</i>",
                parse_mode="HTML",
            )
            return

        text = (
            "━━━━━━━━━━━━━━━━━━━━\n"
            "    📊  <b>Твоя статистика</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"⬇️ Скачиваний: <b>{us.total_downloads}</b>\n"
            f"💾 Объём: <b>{_format_size(us.total_bytes)}</b>\n"
            f"📍 Любимый источник: <b>{us.favorite_platform or '—'}</b>\n"
            f"🎬 Любимый формат: <b>{us.favorite_format or '—'}</b>"
        )
        await message.answer(text, parse_mode="HTML")

    async def _handle_vod_range(self, message: types.Message):
        user_id = message.from_user.id
        url_id = self._awaiting_range.pop(user_id, None)
        if not url_id:
            return

        url = self._get_url(url_id)
        if not url:
            await message.answer("⏳ Ссылка устарела. Отправь заново.")
            return

        text = (message.text or "").strip()
        match = re.match(r"([\d:]+)\s*[-–—]\s*([\d:]+)", text)
        if not match:
            await message.answer(
                "❌ Неверный формат. Используй <code>0:00 - 15:00</code> или <code>1:30:00 - 2:00:00</code>",
                parse_mode="HTML",
            )
            self._awaiting_range[user_id] = url_id
            return

        start = _parse_timestamp(match.group(1))
        end = _parse_timestamp(match.group(2))
        if start is None or end is None or end <= start:
            await message.answer("❌ Неверный диапазон. Конец должен быть после начала.")
            self._awaiting_range[user_id] = url_id
            return

        duration = end - start
        if duration > VOD_DURATION_LIMIT:
            await message.answer(
                f"❌ Максимум 30 минут. Ты запросил {_format_duration(duration)}."
            )
            self._awaiting_range[user_id] = url_id
            return

        url_id = _short_id(url)
        await self._start_download(
            message, url, MediaFormat.VIDEO,
            download_range=(start, end),
            user_id=message.from_user.id, url_id=url_id,
        )

    async def _start_download(
        self,
        message: types.Message,
        url: str,
        media_format: MediaFormat,
        format_id: str | None = None,
        download_range: tuple[int, int] | None = None,
        user_id: int | None = None,
        url_id: str | None = None,
    ):
        queue_pos = self._pool.queue_size
        active = self._pool.active_downloads
        if queue_pos > 0 or active >= self._pool._max_workers:
            status_text = f"⏳ Позиция в очереди: {queue_pos + 1} ({active} активных)..."
        else:
            status_text = "⬇️ <i>Скачиваю...</i>"

        if download_range:
            start, end = download_range
            status_text += f"\n⏱ Диапазон: {_format_duration(start)} — {_format_duration(end)}"

        status_msg = await message.answer(status_text, parse_mode="HTML")

        import time as _time
        dl_start_time = _time.time()

        info = self._pending_info.get(url_id) if url_id else None
        platform_name = info.platform if info else None

        async def on_complete(result: DownloadResult):
            dl_time_ms = int((_time.time() - dl_start_time) * 1000)

            if self._stats and user_id:
                await self._stats.track_download(
                    user_id=user_id, url=url, platform=platform_name,
                    media_format=media_format.value,
                    filesize=result.filesize, duration=result.duration,
                    title=result.title, success=result.success,
                    error=result.error, download_time_ms=dl_time_ms,
                )

            if not result.success:
                await status_msg.edit_text(f"❌ {result.error}")
                return

            filesize = result.filesize or 0
            if filesize > self._file_limit:
                await status_msg.edit_text(
                    f"❌ Файл слишком большой ({_format_size(filesize)}). "
                    f"Лимит — {_format_size(self._file_limit)}."
                )
                self.downloader.cleanup(result)
                return

            await status_msg.edit_text("📤 <i>Загружаю в Telegram...</i>", parse_mode="HTML")

            caption_parts = []
            if result.title:
                caption_parts.append(f"<b>{result.title}</b>")
            meta = []
            if result.duration:
                meta.append(_format_duration(result.duration))
            meta.append(_format_size(result.filesize))
            if meta:
                caption_parts.append(" · ".join(meta))
            caption = "\n".join(caption_parts)

            try:
                input_file = FSInputFile(result.file_path)
                if media_format == MediaFormat.AUDIO:
                    await message.answer_audio(
                        audio=input_file,
                        caption=caption,
                        parse_mode="HTML",
                        title=result.title,
                    )
                else:
                    await message.answer_video(
                        video=input_file,
                        caption=caption,
                        parse_mode="HTML",
                        supports_streaming=True,
                    )
                await status_msg.delete()
            except Exception as e:
                logger.exception("Upload failed")
                await status_msg.edit_text(f"❌ Ошибка загрузки: {e}")
            finally:
                self.downloader.cleanup(result)

        job = DownloadJob(url=url, media_format=media_format, callback=on_complete)
        if format_id:
            job.format_id = format_id
        if download_range:
            job.download_range = download_range
        accepted = await self._pool.submit(job)
        if not accepted:
            await status_msg.edit_text("❌ Очередь заполнена. Попробуй позже.")

    async def start(self) -> None:
        logger.info("Starting Telegram bot...")
        await self.dp.start_polling(self.bot)

    async def stop(self) -> None:
        await self.bot.session.close()
