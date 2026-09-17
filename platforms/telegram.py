from __future__ import annotations

import logging
import re

from aiogram import Bot, Dispatcher, F, Router, types
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from core.downloader import Downloader
from core.models import DownloadResult, MediaFormat
from core.worker_pool import DownloadJob, WorkerPool
from platforms.base import BasePlatform

logger = logging.getLogger(__name__)

URL_REGEX = re.compile(r"https?://\S+")

TELEGRAM_FILE_LIMIT = 50 * 1024 * 1024


def _format_size(size_bytes: int | None) -> str:
    if not size_bytes:
        return "unknown size"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def _format_duration(seconds: int | None) -> str:
    if not seconds:
        return ""
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


class TelegramPlatform(BasePlatform):
    name = "telegram"

    def __init__(self, token: str, downloader: Downloader, pool: WorkerPool):
        super().__init__(token, downloader)
        self.bot = Bot(token=token)
        self.dp = Dispatcher()
        self._pool = pool
        self._register_handlers()

    def _register_handlers(self):
        @self.dp.message(CommandStart())
        async def cmd_start(message: types.Message):
            await message.answer(
                "Send me any link and I'll download the media for you.\n\n"
                "Supported: YouTube, TikTok, Instagram, Twitter/X, "
                "SoundCloud, Reddit, VK, Twitch, Facebook and 1000+ more sites.\n\n"
                f"Workers: {self._pool._max_workers} | "
                f"Queue capacity: {self._pool._queue.maxsize}"
            )

        @self.dp.message(F.text)
        async def handle_url(message: types.Message):
            urls = URL_REGEX.findall(message.text or "")
            if not urls:
                await message.answer("Send me a valid URL to download.")
                return
            url = urls[0]

            kb = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="Video", callback_data=f"dl:video:{url}"),
                    InlineKeyboardButton(text="Audio (MP3)", callback_data=f"dl:audio:{url}"),
                ]
            ])
            await message.answer("Choose format:", reply_markup=kb)

        @self.dp.callback_query(F.data.startswith("dl:"))
        async def handle_download(callback: types.CallbackQuery):
            await callback.answer()
            parts = callback.data.split(":", 2)
            if len(parts) < 3:
                return
            _, fmt_str, url = parts
            media_format = MediaFormat.AUDIO if fmt_str == "audio" else MediaFormat.VIDEO

            queue_pos = self._pool.queue_size
            active = self._pool.active_downloads
            if queue_pos > 0 or active >= self._pool._max_workers:
                status_text = f"Queued (position {queue_pos + 1}, {active} active downloads)..."
            else:
                status_text = "Downloading..."

            status_msg = await callback.message.answer(status_text)

            async def on_complete(result: DownloadResult):
                if not result.success:
                    await status_msg.edit_text(f"Error: {result.error}")
                    return

                filesize = result.filesize or 0
                if filesize > TELEGRAM_FILE_LIMIT:
                    await status_msg.edit_text(
                        f"File is too large for Telegram ({_format_size(filesize)}). "
                        f"Telegram limit is 50 MB."
                    )
                    self.downloader.cleanup(result)
                    return

                await status_msg.edit_text("Uploading...")

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
                        await callback.message.answer_audio(
                            audio=input_file,
                            caption=caption,
                            title=result.title,
                        )
                    else:
                        await callback.message.answer_video(
                            video=input_file,
                            caption=caption,
                            supports_streaming=True,
                        )
                    await status_msg.delete()
                except Exception as e:
                    logger.exception("Failed to upload file")
                    await status_msg.edit_text(f"Upload failed: {e}")
                finally:
                    self.downloader.cleanup(result)

            job = DownloadJob(url=url, media_format=media_format, callback=on_complete)
            accepted = await self._pool.submit(job)
            if not accepted:
                await status_msg.edit_text("Queue is full. Try again later.")

    async def start(self) -> None:
        logger.info("Starting Telegram bot...")
        await self.dp.start_polling(self.bot)

    async def stop(self) -> None:
        await self.bot.session.close()
