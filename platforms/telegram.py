from __future__ import annotations

import hashlib
import logging
import re
from collections import OrderedDict

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from core.downloader import Downloader
from core.models import DownloadResult, MediaFormat, MediaInfo
from core.worker_pool import DownloadJob, WorkerPool
from platforms.base import BasePlatform

logger = logging.getLogger(__name__)

URL_REGEX = re.compile(r"https?://\S+")
TELEGRAM_FILE_LIMIT = 50 * 1024 * 1024
MAX_PENDING = 5000


def _format_size(size_bytes: int | None) -> str:
    if not size_bytes:
        return "~"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.0f}KB"
    return f"{size_bytes / (1024 * 1024):.1f}MB"


def _format_duration(seconds: int | None) -> str:
    if not seconds:
        return ""
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _short_id(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:10]


def _build_format_buttons(info: MediaInfo, url_id: str) -> InlineKeyboardMarkup:
    video_buttons = []
    audio_buttons = []

    seen_video = set()
    seen_audio = set()

    for f in info.formats:
        if f.is_audio_only:
            label = f"{f.quality} • {f.ext} • {_format_size(f.filesize)}"
            key = f"{f.quality}:{f.ext}"
            if key in seen_audio:
                continue
            seen_audio.add(key)
            audio_buttons.append(InlineKeyboardButton(
                text=f"🎵 {label}",
                callback_data=f"f:{url_id}:a:{f.format_id[:20]}",
            ))
        else:
            label = f"{f.quality} • {f.ext} • {_format_size(f.filesize)}"
            key = f"{f.quality}:{f.ext}"
            if key in seen_video:
                continue
            seen_video.add(key)
            video_buttons.append(InlineKeyboardButton(
                text=f"🎬 {label}",
                callback_data=f"f:{url_id}:v:{f.format_id[:20]}",
            ))

    rows = []
    for btn in video_buttons[:8]:
        rows.append([btn])
    for btn in audio_buttons[:4]:
        rows.append([btn])

    rows.append([
        InlineKeyboardButton(text="⬇️ Best Video (MP4)", callback_data=f"q:{url_id}:video"),
        InlineKeyboardButton(text="🎵 Best Audio (MP3)", callback_data=f"q:{url_id}:audio"),
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


class TelegramPlatform(BasePlatform):
    name = "telegram"

    def __init__(self, token: str, downloader: Downloader, pool: WorkerPool):
        super().__init__(token, downloader)
        self.bot = Bot(token=token)
        self.dp = Dispatcher()
        self._pool = pool
        self._pending_urls: OrderedDict[str, str] = OrderedDict()
        self._register_handlers()

    def _store_url(self, url: str) -> str:
        uid = _short_id(url)
        self._pending_urls[uid] = url
        while len(self._pending_urls) > MAX_PENDING:
            self._pending_urls.popitem(last=False)
        return uid

    def _get_url(self, uid: str) -> str | None:
        return self._pending_urls.get(uid)

    def _register_handlers(self):
        @self.dp.message(CommandStart())
        async def cmd_start(message: types.Message):
            await message.answer(
                "🎬 Send me any link — I'll find all available formats.\n\n"
                "Supported: YouTube, TikTok, Instagram, Twitter/X, "
                "SoundCloud, Reddit, VK, Rutube, Facebook and 1000+ more.\n\n"
                "Just paste a link."
            )

        @self.dp.message(F.text)
        async def handle_url(message: types.Message):
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
                await status_msg.edit_text(f"❌ Could not process this link: {e}")
                return

            url_id = self._store_url(url)

            header = f"**{info.title}**"
            if info.uploader:
                header += f"\n👤 {info.uploader}"
            if info.duration:
                header += f"\n⏱ {_format_duration(info.duration)}"
            if info.platform:
                header += f"\n📍 {info.platform}"

            if info.formats:
                header += "\n\nChoose quality:"
                kb = _build_format_buttons(info, url_id)
            else:
                header += "\n\nNo specific formats found. Download best available:"
                kb = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="⬇️ Best Video", callback_data=f"q:{url_id}:video"),
                    InlineKeyboardButton(text="🎵 Best Audio", callback_data=f"q:{url_id}:audio"),
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
            await self._start_download(callback.message, url, media_format)

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
            await self._start_download(callback.message, url, media_format, format_id)

    async def _start_download(
        self,
        message: types.Message,
        url: str,
        media_format: MediaFormat,
        format_id: str | None = None,
    ):
        queue_pos = self._pool.queue_size
        active = self._pool.active_downloads
        if queue_pos > 0 or active >= self._pool._max_workers:
            status_text = f"⏳ Queue position {queue_pos + 1} ({active} active)..."
        else:
            status_text = "⬇️ Downloading..."

        status_msg = await message.answer(status_text)

        async def on_complete(result: DownloadResult):
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
        accepted = await self._pool.submit(job)
        if not accepted:
            await status_msg.edit_text("❌ Queue full. Try again later.")

    async def start(self) -> None:
        logger.info("Starting Telegram bot...")
        await self.dp.start_polling(self.bot)

    async def stop(self) -> None:
        await self.bot.session.close()
