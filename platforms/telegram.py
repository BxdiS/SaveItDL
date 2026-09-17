from __future__ import annotations

import hashlib
import logging
import re
from collections import OrderedDict

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from core.downloader import Downloader
from core.models import DownloadResult, MediaFormat, MediaInfo
from core.stats import StatsDB
from core.worker_pool import DownloadJob, WorkerPool
from platforms.base import BasePlatform

logger = logging.getLogger(__name__)

URL_REGEX = re.compile(r"https?://\S+")
TWITCH_VOD_REGEX = re.compile(r"twitch\.tv/videos/(\d+)")
TELEGRAM_FILE_LIMIT = 50 * 1024 * 1024
MAX_PENDING = 5000
VOD_DURATION_LIMIT = 30 * 60

AUDIO_PLATFORMS = {"SoundCloud", "Bandcamp", "Mixcloud"}


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
    rows = []
    for quality in ["1080", "720", "480"]:
        for f in info.formats:
            if f.is_audio_only:
                continue
            q = str(f.quality)
            if quality in q or q == quality + "p":
                label = f"🎬 {quality}p • {_format_size(f.filesize)}"
                rows.append([InlineKeyboardButton(
                    text=label,
                    callback_data=f"f:{url_id}:v:{f.format_id[:20]}",
                )])
                break

    if not rows:
        for f in info.formats:
            if not f.is_audio_only:
                label = f"🎬 {f.quality} • {_format_size(f.filesize)}"
                rows.append([InlineKeyboardButton(
                    text=label,
                    callback_data=f"f:{url_id}:v:{f.format_id[:20]}",
                )])
                if len(rows) >= 3:
                    break

    rows.append([
        InlineKeyboardButton(text="⬇️ Best Video", callback_data=f"q:{url_id}:video"),
        InlineKeyboardButton(text="🎵 MP3", callback_data=f"q:{url_id}:audio"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _build_audio_buttons(info: MediaInfo, url_id: str) -> InlineKeyboardMarkup:
    rows = []
    seen = set()
    for f in info.formats:
        q = str(f.quality)
        if q in seen:
            continue
        seen.add(q)
        label = f"🎵 {q} • {f.ext} • {_format_size(f.filesize)}"
        rows.append([InlineKeyboardButton(
            text=label,
            callback_data=f"f:{url_id}:a:{f.format_id[:20]}",
        )])
        if len(rows) >= 4:
            break

    rows.append([InlineKeyboardButton(
        text="🎵 Best Audio (MP3)",
        callback_data=f"q:{url_id}:audio",
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


class TelegramPlatform(BasePlatform):
    name = "telegram"

    def __init__(self, token: str, downloader: Downloader, pool: WorkerPool,
                 stats: StatsDB | None = None, admin_id: int | None = None):
        super().__init__(token, downloader)
        self.bot = Bot(token=token)
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

    def _register_handlers(self):
        @self.dp.message(CommandStart())
        async def cmd_start(message: types.Message):
            await message.answer(
                "🎬 Send me any link — I'll download it for you.\n\n"
                "Supported: YouTube, TikTok, Instagram, Twitter/X, "
                "SoundCloud, Reddit, VK, Rutube, Twitch, Facebook "
                "and 1000+ more.\n\n"
                "Just paste a link."
            )

        @self.dp.message(Command("stats"))
        async def cmd_stats(message: types.Message):
            if not self._stats:
                await message.answer("Stats not available.")
                return
            user_id = message.from_user.id
            us = await self._stats.get_user_stats(user_id)
            if not us:
                await message.answer("You haven't downloaded anything yet.")
                return
            text = (
                f"📊 **Your stats**\n\n"
                f"Downloads: **{us.total_downloads}**\n"
                f"Total size: **{_format_size(us.total_bytes)}**\n"
                f"Favorite source: **{us.favorite_platform or '—'}**\n"
                f"Favorite format: **{us.favorite_format or '—'}**"
            )
            await message.answer(text, parse_mode="Markdown")

        @self.dp.message(Command("adminstats"))
        async def cmd_adminstats(message: types.Message):
            if not self._admin_id or message.from_user.id != self._admin_id:
                await message.answer("Admin only.")
                return
            if not self._stats:
                await message.answer("Stats not available.")
                return

            gs = await self._stats.get_global_stats()
            platforms = "\n".join(f"  {p}: {c}" for p, c in gs.top_platforms[:5]) or "  —"
            formats = "\n".join(f"  {f}: {c}" for f, c in gs.top_formats) or "  —"

            total_gb = gs.total_bytes / (1024 ** 3)
            text = (
                f"📊 **Admin Dashboard**\n\n"
                f"👥 Users: **{gs.total_users}**\n"
                f"  Active today: {gs.active_today}\n"
                f"  Active this week: {gs.active_week}\n\n"
                f"⬇️ Downloads: **{gs.total_downloads}**\n"
                f"  Today: {gs.downloads_today}\n"
                f"  Total traffic: {total_gb:.2f} GB\n"
                f"  Avg file size: {_format_size(gs.avg_filesize)}\n"
                f"  Error rate: {gs.error_rate:.1%}\n"
                f"  Peak hour: {gs.peak_hour}:00 UTC\n\n"
                f"📍 Top platforms:\n{platforms}\n\n"
                f"🎬 Top formats:\n{formats}"
            )
            await message.answer(text, parse_mode="Markdown")

        @self.dp.message(Command("errors"))
        async def cmd_errors(message: types.Message):
            if not self._admin_id or message.from_user.id != self._admin_id:
                await message.answer("Admin only.")
                return
            if not self._stats:
                return
            errors = await self._stats.get_recent_errors(10)
            if not errors:
                await message.answer("No recent errors.")
                return
            lines = []
            for e in errors:
                lines.append(f"• {e['platform'] or '?'}: {e['error'][:80]}")
            await message.answer("🔴 **Recent errors:**\n\n" + "\n".join(lines), parse_mode="Markdown")

        @self.dp.message(F.text)
        async def handle_message(message: types.Message):
            user_id = message.from_user.id
            if self._stats:
                u = message.from_user
                await self._stats.track_user(
                    user_id, u.username, u.first_name, u.language_code,
                )

            if user_id in self._awaiting_range:
                await self._handle_vod_range(message)
                return

            urls = URL_REGEX.findall(message.text or "")
            if not urls:
                await message.answer("Send me a valid URL.")
                return
            url = urls[0]

            status_msg = await message.answer("🔍 Analyzing link...")

            try:
                info = await self.downloader.get_info(url)
            except Exception as e:
                logger.warning("Info extraction failed for %s: %s", url, e)
                await status_msg.edit_text(f"❌ Could not process this link.")
                return

            url_id = self._store_url(url, info)
            duration = info.duration or 0

            if _is_twitch_vod(url) and duration > VOD_DURATION_LIMIT:
                self._awaiting_range[user_id] = url_id
                await status_msg.edit_text(
                    f"**{info.title}**\n"
                    f"⏱ {_format_duration(duration)} — this VOD is over 30 minutes.\n\n"
                    "Send me the time range to download:\n"
                    "`0:00 - 15:00` or `1:30:00 - 2:00:00`\n\n"
                    "Or press the button to download a clip (first 30 min).",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(
                            text="⬇️ First 30 min",
                            callback_data=f"vod:{url_id}:0:1800",
                        ),
                        InlineKeyboardButton(
                            text="❌ Cancel",
                            callback_data=f"vod:{url_id}:cancel",
                        ),
                    ]]),
                )
                return

            header = f"**{info.title}**"
            if info.uploader:
                header += f"\n👤 {info.uploader}"
            if duration:
                header += f"\n⏱ {_format_duration(duration)}"
            if info.platform:
                header += f"\n📍 {info.platform}"

            is_audio = _is_audio_platform(info)

            if info.formats:
                header += "\n\nChoose quality:"
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

            await status_msg.edit_text(header, reply_markup=kb, parse_mode="Markdown")

        @self.dp.callback_query(F.data.startswith("q:"))
        async def handle_quick_download(callback: types.CallbackQuery):
            await callback.answer()
            parts = callback.data.split(":")
            if len(parts) < 3:
                return
            _, url_id, fmt = parts
            url = self._get_url(url_id)
            if not url:
                await callback.message.edit_text("⏳ Link expired. Send it again.")
                return
            media_format = MediaFormat.AUDIO if fmt == "audio" else MediaFormat.VIDEO
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
            _, url_id, kind, format_id = parts
            url = self._get_url(url_id)
            if not url:
                await callback.message.edit_text("⏳ Link expired. Send it again.")
                return
            media_format = MediaFormat.AUDIO if kind == "a" else MediaFormat.VIDEO
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
                await callback.message.edit_text("❌ Cancelled.")
                return

            start_sec = int(parts[2])
            end_sec = int(parts[3])
            url = self._get_url(url_id)
            if not url:
                await callback.message.edit_text("⏳ Link expired. Send it again.")
                return
            await self._start_download(
                callback.message, url, MediaFormat.VIDEO,
                download_range=(start_sec, end_sec),
                user_id=callback.from_user.id, url_id=url_id,
            )

    async def _handle_vod_range(self, message: types.Message):
        user_id = message.from_user.id
        url_id = self._awaiting_range.pop(user_id, None)
        if not url_id:
            return

        url = self._get_url(url_id)
        if not url:
            await message.answer("⏳ Link expired. Send it again.")
            return

        text = (message.text or "").strip()
        match = re.match(r"([\d:]+)\s*[-–—]\s*([\d:]+)", text)
        if not match:
            await message.answer(
                "❌ Invalid format. Use `0:00 - 15:00` or `1:30:00 - 2:00:00`",
                parse_mode="Markdown",
            )
            self._awaiting_range[user_id] = url_id
            return

        start = _parse_timestamp(match.group(1))
        end = _parse_timestamp(match.group(2))
        if start is None or end is None or end <= start:
            await message.answer("❌ Invalid range. End must be after start.")
            self._awaiting_range[user_id] = url_id
            return

        duration = end - start
        if duration > VOD_DURATION_LIMIT:
            await message.answer(
                f"❌ Max range is 30 minutes. You requested {_format_duration(duration)}."
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
            status_text = f"⏳ Queue position {queue_pos + 1} ({active} active)..."
        else:
            status_text = "⬇️ Downloading..."

        if download_range:
            start, end = download_range
            status_text += f"\n⏱ Range: {_format_duration(start)} — {_format_duration(end)}"

        status_msg = await message.answer(status_text)

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
            if filesize > TELEGRAM_FILE_LIMIT:
                await status_msg.edit_text(
                    f"❌ File too large ({_format_size(filesize)}). "
                    f"Telegram limit is 50 MB."
                )
                self.downloader.cleanup(result)
                return

            await status_msg.edit_text("📤 Uploading...")

            caption_parts = []
            if result.title:
                caption_parts.append(result.title)
            if result.duration:
                caption_parts.append(_format_duration(result.duration))
            caption_parts.append(_format_size(result.filesize))
            caption = " | ".join(caption_parts)

            try:
                input_file = FSInputFile(result.file_path)
                if media_format == MediaFormat.AUDIO:
                    await message.answer_audio(
                        audio=input_file,
                        caption=caption,
                        title=result.title,
                    )
                else:
                    await message.answer_video(
                        video=input_file,
                        caption=caption,
                        supports_streaming=True,
                    )
                await status_msg.delete()
            except Exception as e:
                logger.exception("Upload failed")
                await status_msg.edit_text(f"❌ Upload failed: {e}")
            finally:
                self.downloader.cleanup(result)

        job = DownloadJob(url=url, media_format=media_format, callback=on_complete)
        if format_id:
            job.format_id = format_id
        if download_range:
            job.download_range = download_range
        accepted = await self._pool.submit(job)
        if not accepted:
            await status_msg.edit_text("❌ Queue full. Try again later.")

    async def start(self) -> None:
        logger.info("Starting Telegram bot...")
        await self.dp.start_polling(self.bot)

    async def stop(self) -> None:
        await self.bot.session.close()
