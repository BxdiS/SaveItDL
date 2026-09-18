from __future__ import annotations

import hashlib
import html
import logging
import re
import time
from collections import OrderedDict
from pathlib import Path

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BotCommand,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    PreCheckoutQuery,
)

from config import Limits
from core.downloader import Downloader
from core.limits import RateLimiter
from core.models import DownloadResult, MediaFormat, MediaInfo
from core.premium import is_premium, premium_expires_days, tariffs
from core.quota import check_daily_quota
from core.security import is_safe_url
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


def _build_video_buttons(
    info: MediaInfo, url_id: str,
    premium: bool, free_max_h: int,
    file_limit: int,
) -> InlineKeyboardMarkup:
    video_formats = []
    seen_quality = set()
    for i, f in enumerate(info.formats):
        if f.is_audio_only:
            continue
        h = _quality_sort_key(f.quality)
        if not premium and h > free_max_h:
            continue
        if f.filesize and f.filesize > file_limit:
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
        label = f"🎬 {q}  ·  {_format_size(f.filesize)}"
        rows.append([InlineKeyboardButton(
            text=label,
            callback_data=f"f:{url_id}:v:{i}",
        )])

    rows.append([
        InlineKeyboardButton(text="🎬 Лучшее видео", callback_data=f"q:{url_id}:video"),
        InlineKeyboardButton(text="🎵 MP3", callback_data=f"q:{url_id}:audio"),
    ])
    if not premium:
        rows.append([InlineKeyboardButton(
            text="⭐ Premium: FHD / 2K / 4K", callback_data="menu:premium",
        )])
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
        label = f"🎵 {q}  ·  {_format_size(f.filesize)}"
        rows.append([InlineKeyboardButton(
            text=label,
            callback_data=f"f:{url_id}:a:{i}",
        )])
        if len(rows) >= 5:
            break

    rows.append([InlineKeyboardButton(
        text="🎵 Лучшее качество (MP3)",
        callback_data=f"q:{url_id}:audio",
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


BANNER_PATH = Path(__file__).resolve().parent.parent / "assets" / "banner.jpg"
CHANNEL_URL = "https://t.me/SaveItDL"
HELP_URL = "https://t.me/SaveItDL?direct"

WELCOME_TEXT = (
    "🎬 <b>Welcome to the SaveItDL</b>\n\n"
    "Скачивай видео и аудио с ЛЮБЫХ платформ.\n"
    "Просто отправь ссылку..."
)

WELCOME_KEYBOARD = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🚀 Как пользоваться?", callback_data="menu:howto")],
    [
        InlineKeyboardButton(text="📊 Статистика", callback_data="menu:stats"),
        InlineKeyboardButton(text="💬 Помощь", url=HELP_URL),
    ],
])

BACK_KEYBOARD = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main")],
])

HOWTO_TEXT = (
    "🚀 <b>Как пользоваться</b>\n\n"
    "1. Пришли ссылку на видео или аудио.\n"
    "2. Выбери качество кнопкой.\n"
    "3. Получи файл в чат.\n\n"
    "<b>Форматы</b>\n"
    "▸ Видео — 1080p / 720p / 480p\n"
    "▸ Аудио — MP3, лучшее качество\n"
    "▸ Twitch VOD — фрагмент до 30 минут"
)

HELP_TEXT = HOWTO_TEXT  # backwards-compat for /help command


PREMIUM_TEXT = (
    "⭐ <b>SaveItDL Premium</b>\n\n"
    "<b>Free</b>\n"
    "▸ До 720p, ролики до 15 минут\n"
    "▸ 15 файлов / 1 ГБ в сутки\n"
    "▸ 1 активная загрузка\n\n"
    "<b>Premium</b>\n"
    "▸ FHD / 2K / 4K без ограничения длины\n"
    "▸ 100 файлов / 10 ГБ в сутки\n"
    "▸ 3 параллельных загрузки, приоритет в очереди\n\n"
    "Оплата в Telegram Stars. Стоимость ниже:"
)


class TelegramPlatform(BasePlatform):
    name = "telegram"

    def __init__(self, token: str, downloader: Downloader, pool: WorkerPool,
                 stats: StatsDB | None = None, admin_id: int | None = None,
                 api_url: str | None = None,
                 limits: Limits | None = None,
                 rate_limiter: RateLimiter | None = None):
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
        self._limits = limits or Limits()
        self._rl = rate_limiter or RateLimiter()
        self._pending_info: OrderedDict[str, MediaInfo] = OrderedDict()
        self._register_handlers()

    async def _store_url(self, url: str, user_id: int,
                          info: MediaInfo | None = None) -> str:
        uid = _short_id(url)
        if info:
            self._pending_info[uid] = info
            while len(self._pending_info) > MAX_PENDING:
                self._pending_info.popitem(last=False)
        if self._stats:
            formats = None
            if info:
                formats = [
                    {"format_id": f.format_id, "ext": f.ext,
                     "quality": f.quality, "filesize": f.filesize,
                     "is_audio_only": f.is_audio_only}
                    for f in info.formats
                ]
            await self._stats.save_pending_url(uid, user_id, url, formats)
        return uid

    async def _get_url(self, uid: str) -> str | None:
        if self._stats:
            row = await self._stats.get_pending_url(uid)
            if row:
                return row["url"]
        return None

    async def _user_is_premium(self, user_id: int) -> bool:
        if not self._stats:
            return False
        row = await self._stats.get_user_row(user_id)
        return is_premium(row)

    async def _check_rate(self, user_id: int, message: types.Message) -> bool:
        first_seen = None
        if self._stats:
            row = await self._stats.get_user_row(user_id)
            if row:
                first_seen = row.get("first_seen")
        ok, retry = self._rl.check_message(user_id, first_seen)
        if not ok:
            try:
                await message.answer(
                    f"⏱ Не так быстро. Подожди {int(retry) + 1} сек.",
                )
            except Exception:
                pass
        return ok

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
            logger.debug(
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
            sent_banner = False
            if banner.exists():
                try:
                    await message.answer_photo(
                        photo=FSInputFile(banner),
                        caption=WELCOME_TEXT,
                        parse_mode="HTML",
                        reply_markup=WELCOME_KEYBOARD,
                    )
                    sent_banner = True
                except Exception:
                    logger.exception("Failed to send banner")
            if not sent_banner:
                await message.answer(
                    WELCOME_TEXT,
                    parse_mode="HTML",
                    reply_markup=WELCOME_KEYBOARD,
                )

        @self.dp.message(Command("stats"))
        async def cmd_stats(message: types.Message):
            await self._send_user_stats(message.from_user.id, message)

        @self.dp.message(Command("help"))
        async def cmd_help(message: types.Message):
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
            await callback.answer()
            if action == "main":
                await self._edit_menu(callback.message, WELCOME_TEXT, WELCOME_KEYBOARD)
            elif action == "howto":
                await self._edit_menu(callback.message, HOWTO_TEXT, BACK_KEYBOARD)
            elif action == "stats":
                text = await self._build_user_stats_text(callback.from_user.id)
                await self._edit_menu(callback.message, text, BACK_KEYBOARD)
            elif action == "premium":
                await self._send_premium_offer(callback.message, callback.from_user.id)

        @self.dp.callback_query(F.data.startswith("buy:"))
        async def handle_buy(callback: types.CallbackQuery):
            await callback.answer()
            kind = callback.data.split(":", 1)[1]
            await self._send_invoice(callback.message, callback.from_user.id, kind)

        @self.dp.message(Command("premium"))
        async def cmd_premium(message: types.Message):
            await self._track_user(message.from_user)
            await self._send_premium_offer(message, message.from_user.id, new=True)

        @self.dp.message(Command("grantpremium"))
        async def cmd_grantpremium(message: types.Message):
            if not self._is_admin(message.from_user.id):
                await message.answer("⛔ Только для администратора.")
                return
            parts = (message.text or "").split()
            if len(parts) != 3:
                await message.answer("Использование: /grantpremium <user_id> <days>")
                return
            try:
                target = int(parts[1])
                days = int(parts[2])
            except ValueError:
                await message.answer("user_id и days должны быть числами.")
                return
            if not self._stats:
                await message.answer("Stats DB не подключена.")
                return
            new_until = await self._stats.extend_premium(target, days * 86400)
            await message.answer(
                f"✅ Premium для {target} активен до "
                f"{time.strftime('%d.%m.%Y', time.localtime(new_until))}."
            )

        @self.dp.pre_checkout_query()
        async def pre_checkout(q: PreCheckoutQuery):
            await self.bot.answer_pre_checkout_query(q.id, ok=True)

        @self.dp.message(F.successful_payment)
        async def on_success_payment(message: types.Message):
            await self._handle_payment(message)

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

            awaiting = None
            if self._stats:
                awaiting = await self._stats.get_awaiting_range(user_id)
            if awaiting:
                await self._handle_vod_range(message, awaiting)
                return

            urls = URL_REGEX.findall(message.text or "")
            if not urls:
                await message.answer(
                    "📎 <i>Отправь мне ссылку на видео или аудио.</i>",
                    parse_mode="HTML",
                )
                return
            if not await self._check_rate(user_id, message):
                return

            url = urls[0].rstrip(".,;!?)")

            if not is_safe_url(url):
                await message.answer("⛔ Ссылка ведёт во внутреннюю сеть — отклонено.")
                return

            if self._stats:
                await self._stats.track_action(user_id, "url_sent", url[:200])

            status_msg = await message.answer("🔍 <i>Анализирую ссылку...</i>", parse_mode="HTML")

            try:
                info = await self.downloader.get_info(url)
            except Exception as e:
                logger.warning("Info extraction failed for %s: %s", url, e)
                await status_msg.edit_text("❌ Не удалось обработать ссылку.")
                return

            url_id = await self._store_url(url, user_id, info)
            duration = info.duration or 0
            premium_user = await self._user_is_premium(user_id)

            safe_title = html.escape(info.title or "Без названия")

            if _is_twitch_vod(url) and duration > VOD_DURATION_LIMIT:
                if self._stats:
                    await self._stats.set_awaiting_range(user_id, url_id)
                await status_msg.edit_text(
                    f"📺 <b>{safe_title}</b>\n"
                    f"⏱ {_format_duration(duration)} — VOD дольше 30 минут.\n\n"
                    f"Пришли диапазон для скачивания:\n"
                    f"<code>0:00 - 15:00</code>  или  <code>1:30:00 - 2:00:00</code>",
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

            is_audio = _is_audio_platform(info)
            icon = "🎵" if is_audio else "🎬"
            lines = [f"{icon} <b>{safe_title}</b>"]

            details = []
            if info.uploader:
                details.append(f"👤 {html.escape(info.uploader)}")
            if duration:
                details.append(f"⏱ {_format_duration(duration)}")
            if info.platform:
                details.append(f"📍 {html.escape(info.platform)}")
            if details:
                lines.append(" · ".join(details))

            # Free: block long videos (audio always allowed)
            video_locked_by_duration = (
                not premium_user
                and not is_audio
                and duration > self._limits.free_max_duration_s
            )

            if video_locked_by_duration:
                lines.append(
                    f"\n⚠️ Ролик длиннее {self._limits.free_max_duration_s // 60} мин.\n"
                    "Скачать в MP3 можно, для видео нужен Premium."
                )
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🎵 Скачать MP3", callback_data=f"q:{url_id}:audio")],
                    [InlineKeyboardButton(text="⭐ Premium", callback_data="menu:premium")],
                ])
            elif info.formats:
                lines.append("\n<b>Выбери качество:</b>")
                if is_audio:
                    kb = _build_audio_buttons(info, url_id)
                else:
                    kb = _build_video_buttons(
                        info, url_id, premium_user,
                        self._limits.free_max_height, self._file_limit,
                    )
            else:
                if is_audio:
                    kb = InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text="🎵 MP3", callback_data=f"q:{url_id}:audio"),
                    ]])
                else:
                    kb = InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text="🎬 Видео", callback_data=f"q:{url_id}:video"),
                        InlineKeyboardButton(text="🎵 MP3", callback_data=f"q:{url_id}:audio"),
                    ]])

            await status_msg.edit_text("\n".join(lines), reply_markup=kb, parse_mode="HTML")

        @self.dp.callback_query(F.data.startswith("q:"))
        async def handle_quick_download(callback: types.CallbackQuery):
            user_id = callback.from_user.id
            ok, retry = self._rl.check_callback(user_id)
            if not ok:
                await callback.answer(f"Подожди {int(retry)+1} сек", show_alert=False)
                return
            await callback.answer()
            parts = callback.data.split(":")
            if len(parts) < 3:
                return
            _, url_id, fmt = parts
            url = await self._get_url(url_id)
            if not url:
                await callback.message.edit_text("⏳ Ссылка устарела. Отправь заново.")
                return
            media_format = MediaFormat.AUDIO if fmt == "audio" else MediaFormat.VIDEO
            info = self._pending_info.get(url_id)
            if not await self._enforce_tier(callback.message, user_id, info, media_format):
                return
            if self._stats:
                await self._stats.track_action(user_id, "quality_pick", fmt)
            await self._start_download(
                callback.message, url, media_format,
                user_id=user_id, url_id=url_id,
            )

        @self.dp.callback_query(F.data.startswith("f:"))
        async def handle_format_download(callback: types.CallbackQuery):
            user_id = callback.from_user.id
            ok, retry = self._rl.check_callback(user_id)
            if not ok:
                await callback.answer(f"Подожди {int(retry)+1} сек", show_alert=False)
                return
            await callback.answer()
            parts = callback.data.split(":")
            if len(parts) < 4:
                return
            _, url_id, kind, fmt_idx = parts
            url = await self._get_url(url_id)
            if not url:
                await callback.message.edit_text("⏳ Ссылка устарела. Отправь заново.")
                return

            format_id = None
            info = self._pending_info.get(url_id)
            if info:
                try:
                    idx = int(fmt_idx)
                    if 0 <= idx < len(info.formats):
                        f = info.formats[idx]
                        format_id = f.format_id
                        premium_user = await self._user_is_premium(user_id)
                        if not premium_user and not f.is_audio_only:
                            h = _quality_sort_key(f.quality)
                            if h > self._limits.free_max_height:
                                await callback.message.edit_text(
                                    "⭐ Это качество доступно только Premium-пользователям.\n"
                                    "Команда /premium — открыть тариф.",
                                    reply_markup=BACK_KEYBOARD,
                                )
                                return
                except (ValueError, IndexError):
                    pass

            media_format = MediaFormat.AUDIO if kind == "a" else MediaFormat.VIDEO
            if not await self._enforce_tier(callback.message, user_id, info, media_format):
                return
            if self._stats:
                await self._stats.track_action(user_id, "format_pick", f"{kind}:{format_id}")
            await self._start_download(
                callback.message, url, media_format, format_id,
                user_id=user_id, url_id=url_id,
            )

        @self.dp.callback_query(F.data.startswith("vod:"))
        async def handle_vod_callback(callback: types.CallbackQuery):
            user_id = callback.from_user.id
            ok, retry = self._rl.check_callback(user_id)
            if not ok:
                await callback.answer(f"Подожди {int(retry)+1} сек", show_alert=False)
                return
            await callback.answer()
            parts = callback.data.split(":")
            if len(parts) < 3:
                return
            _, url_id = parts[0], parts[1]

            if self._stats:
                await self._stats.clear_awaiting_range(user_id)

            if parts[2] == "cancel":
                await callback.message.edit_text("❌ Отменено.")
                return

            start_sec = int(parts[2])
            end_sec = int(parts[3])
            url = await self._get_url(url_id)
            if not url:
                await callback.message.edit_text("⏳ Ссылка устарела. Отправь заново.")
                return
            if not await self._enforce_tier(callback.message, user_id, None, MediaFormat.VIDEO):
                return
            await self._start_download(
                callback.message, url, MediaFormat.VIDEO,
                download_range=(start_sec, end_sec),
                user_id=user_id, url_id=url_id,
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
        langs = "\n".join(
            f"  ▸ {html.escape(l)}: <b>{c}</b>" for l, c in gs.top_languages
        ) or "  —"
        return (
            "📊 <b>Admin</b>\n\n"
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
            f"🌐 <b>Languages</b>\n{langs}"
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
            raw_name = u["username"] or u["first_name"] or str(u["user_id"])
            name = html.escape(str(raw_name))
            if u["username"]:
                name = f"@{name}"
            dt = datetime.datetime.fromtimestamp(u["first_seen"]).strftime("%d.%m %H:%M")
            premium = " ⭐" if u["is_premium"] else ""
            lang = html.escape(u["language"] or "?")
            ref = f" ← {html.escape(u['start_param'])}" if u["start_param"] else ""
            lines.append(f"▸ <b>{name}</b>{premium}  {lang}  {dt}{ref}")

        text = "👥 <b>Recent Users</b>\n\n" + "\n".join(lines)
        await message.edit_text(text, parse_mode="HTML", reply_markup=self._admin_nav("users"))

    async def _edit_admin_downloads(self, message: types.Message):
        if not self._stats:
            return
        gs = await self._stats.get_global_stats()
        platforms = "\n".join(
            f"  ▸ {html.escape(p)}: <b>{c}</b>" for p, c in gs.top_platforms[:10]
        ) or "  —"
        formats = "\n".join(
            f"  ▸ {html.escape(f)}: <b>{c}</b>" for f, c in gs.top_formats
        ) or "  —"

        text = (
            "⬇️ <b>Downloads</b>\n\n"
            f"<b>By platform</b>\n{platforms}\n\n"
            f"<b>By format</b>\n{formats}"
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
            raw_name = u["username"] or u["first_name"] or str(u["user_id"])
            name = html.escape(str(raw_name))
            if u["username"]:
                name = f"@{name}"
            medal = ["🥇", "🥈", "🥉"][i - 1] if i <= 3 else f"{i}."
            lines.append(
                f"{medal} <b>{name}</b> — {u['downloads']} dl · {_format_size(u['total_bytes'])}"
            )

        text = "🏆 <b>Top Users</b>\n\n" + "\n".join(lines)
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
            title = html.escape((d["title"] or "?")[:30])
            user = f"@{html.escape(d['username'])}" if d["username"] else "anon"
            dt = datetime.datetime.fromtimestamp(d["at"]).strftime("%H:%M")
            speed = f"{d['time_ms'] / 1000:.1f}s" if d["time_ms"] else "?"
            platform = html.escape(d["platform"] or "?")
            fmt = html.escape(d["format"] or "?")
            lines.append(
                f"▸ {dt}  <b>{title}</b>\n"
                f"    {platform} · {fmt} · {_format_size(d['filesize'])} · {speed} · {user}"
            )

        text = "🕐 <b>Recent Downloads</b>\n\n" + "\n".join(lines)
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
            return "✅ <b>No Errors</b>\n\nВсё работает штатно."
        lines = []
        for e in errors:
            platform = html.escape(e["platform"] or "?")
            err = html.escape((e["error"] or "")[:80])
            lines.append(f"▸ <b>{platform}</b>: {err}")
        return "🔴 <b>Recent Errors</b>\n\n" + "\n".join(lines)

    async def _build_user_stats_text(self, user_id: int) -> str:
        if not self._stats:
            return "Статистика недоступна."

        await self._stats.track_action(user_id, "stats_view")
        us = await self._stats.get_user_stats(user_id)
        if not us:
            return (
                "📊 <b>Твоя статистика</b>\n\n"
                "<i>Пока нет скачиваний. Пришли ссылку!</i>"
            )

        fav_platform = html.escape(us.favorite_platform) if us.favorite_platform else "—"
        fav_format = html.escape(us.favorite_format) if us.favorite_format else "—"
        return (
            "📊 <b>Твоя статистика</b>\n\n"
            f"⬇️ Скачиваний: <b>{us.total_downloads}</b>\n"
            f"💾 Объём: <b>{_format_size(us.total_bytes)}</b>\n"
            f"📍 Источник: <b>{fav_platform}</b>\n"
            f"🎬 Формат: <b>{fav_format}</b>"
        )

    async def _send_user_stats(self, user_id: int, message: types.Message):
        text = await self._build_user_stats_text(user_id)
        await message.answer(text, parse_mode="HTML")

    async def _edit_menu(
        self,
        message: types.Message,
        text: str,
        keyboard: InlineKeyboardMarkup,
    ) -> None:
        try:
            if message.photo:
                await message.edit_caption(
                    caption=text, parse_mode="HTML", reply_markup=keyboard,
                )
            else:
                await message.edit_text(
                    text=text, parse_mode="HTML", reply_markup=keyboard,
                )
        except Exception:
            logger.exception("Failed to edit menu")

    async def _handle_vod_range(self, message: types.Message, url_id: str):
        user_id = message.from_user.id
        url = await self._get_url(url_id)
        if not url:
            if self._stats:
                await self._stats.clear_awaiting_range(user_id)
            await message.answer("⏳ Ссылка устарела. Отправь заново.")
            return

        text = (message.text or "").strip()
        match = re.match(r"([\d:]+)\s*[-–—]\s*([\d:]+)", text)
        if not match:
            await message.answer(
                "❌ Неверный формат. Используй <code>0:00 - 15:00</code> или <code>1:30:00 - 2:00:00</code>",
                parse_mode="HTML",
            )
            return

        start = _parse_timestamp(match.group(1))
        end = _parse_timestamp(match.group(2))
        if start is None or end is None or end <= start or start < 0:
            await message.answer("❌ Неверный диапазон. Конец должен быть после начала.")
            return

        duration = end - start
        if duration > VOD_DURATION_LIMIT:
            await message.answer(
                f"❌ Максимум 30 минут. Ты запросил {_format_duration(duration)}."
            )
            return

        if self._stats:
            await self._stats.clear_awaiting_range(user_id)
        if not await self._enforce_tier(message, user_id, None, MediaFormat.VIDEO):
            return
        await self._start_download(
            message, url, MediaFormat.VIDEO,
            download_range=(start, end),
            user_id=user_id, url_id=url_id,
        )

    async def _enforce_tier(
        self,
        message: types.Message,
        user_id: int,
        info: MediaInfo | None,
        media_format: MediaFormat,
    ) -> bool:
        premium_user = await self._user_is_premium(user_id)
        # Duration cap on free video (audio exempt)
        if (
            not premium_user
            and media_format == MediaFormat.VIDEO
            and info is not None
            and info.duration
            and info.duration > self._limits.free_max_duration_s
        ):
            try:
                await message.edit_text(
                    f"⭐ Ролики длиннее {self._limits.free_max_duration_s // 60} мин — "
                    "только Premium. Команда /premium.",
                    reply_markup=BACK_KEYBOARD,
                )
            except Exception:
                await message.answer(
                    f"⭐ Ролики длиннее {self._limits.free_max_duration_s // 60} мин — Premium."
                )
            return False
        # Daily quota
        if self._stats:
            is_audio = media_format == MediaFormat.AUDIO
            q = await check_daily_quota(self._stats, user_id, self._limits, is_audio)
            if not q.allowed:
                try:
                    await message.edit_text(
                        f"⛔ {q.reason}\n\n"
                        f"Использовано сегодня: {q.files_used}/{q.files_limit} файлов, "
                        f"{q.bytes_used / (1024**3):.2f} ГБ.\n"
                        "Купить Premium: /premium",
                    )
                except Exception:
                    await message.answer(f"⛔ {q.reason}")
                return False
        return True

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
        premium_user = False
        if user_id and self._stats:
            premium_user = await self._user_is_premium(user_id)

        queue_pos = self._pool.queue_size
        active = self._pool.active_downloads
        if queue_pos > 0 or active >= self._pool._max_workers:
            tag = " ⭐" if premium_user else ""
            status_text = f"⏳ Позиция в очереди: {queue_pos + 1}{tag} ({active} активных)..."
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
                await status_msg.edit_text(f"❌ {html.escape(result.error or 'Ошибка')}")
                return

            filesize = result.filesize or 0
            if filesize > self._file_limit:
                await status_msg.edit_text(
                    f"❌ Файл слишком большой ({_format_size(filesize)}). "
                    f"Лимит — {_format_size(self._file_limit)}."
                )
                self.downloader.cleanup(result)
                return

            await status_msg.edit_text("📤 <i>Отправляю файл...</i>", parse_mode="HTML")

            caption_parts = []
            if result.title:
                caption_parts.append(f"<b>{html.escape(result.title)}</b>")
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
                await status_msg.edit_text(f"❌ Ошибка отправки: {html.escape(str(e))}")
            finally:
                self.downloader.cleanup(result)

        job = DownloadJob(
            url=url, media_format=media_format, callback=on_complete,
            user_id=user_id, is_premium=premium_user,
        )
        if format_id:
            job.format_id = format_id
        if download_range:
            job.download_range = download_range
        accepted = await self._pool.submit(job)
        if not accepted:
            await status_msg.edit_text("❌ Очередь заполнена. Попробуй позже.")

    async def _send_premium_offer(
        self, message: types.Message, user_id: int, new: bool = False
    ) -> None:
        text = PREMIUM_TEXT
        if self._stats:
            row = await self._stats.get_user_row(user_id)
            days = premium_expires_days(row)
            if days:
                text = (
                    f"⭐ <b>Premium активен ещё {days} дн.</b>\n\n"
                    "Можно продлить — новые дни добавятся к текущему сроку."
                )
        tar = tariffs(
            self._limits.stars_month, self._limits.stars_year, self._limits.stars_5gb
        )
        rows = [[InlineKeyboardButton(
            text=f"{t.label}  —  {t.stars} ⭐",
            callback_data=f"buy:{t.kind}",
        )] for t in tar]
        rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main")])
        kb = InlineKeyboardMarkup(inline_keyboard=rows)
        if new:
            await message.answer(text, parse_mode="HTML", reply_markup=kb)
        else:
            await self._edit_menu(message, text, kb)

    async def _send_invoice(
        self, message: types.Message, user_id: int, kind: str
    ) -> None:
        pricing = {
            "month": (self._limits.stars_month, "SaveItDL Premium — 30 дней",
                      "Premium-доступ на 30 дней: FHD/2K/4K, увеличенные лимиты."),
            "year": (self._limits.stars_year, "SaveItDL Premium — 12 месяцев",
                     "Premium на год со скидкой."),
            "5gb": (self._limits.stars_5gb, "+5 ГБ трафика",
                    "Разовое пополнение: +5 ГБ к дневной квоте (не сгорают)."),
        }
        if kind not in pricing:
            await message.answer("Неизвестный тариф.")
            return
        stars, title, desc = pricing[kind]
        payload = f"premium:{kind}:{user_id}:{int(time.time())}"
        try:
            await self.bot.send_invoice(
                chat_id=message.chat.id,
                title=title,
                description=desc,
                payload=payload,
                provider_token="",  # empty for Telegram Stars
                currency="XTR",
                prices=[LabeledPrice(label=title, amount=stars)],
            )
        except Exception as e:
            logger.exception("Failed to send invoice")
            await message.answer(f"❌ Не удалось создать счёт: {html.escape(str(e))}")

    async def _handle_payment(self, message: types.Message) -> None:
        sp = message.successful_payment
        if not sp or not self._stats:
            return
        payload = sp.invoice_payload or ""
        parts = payload.split(":")
        if len(parts) < 3 or parts[0] != "premium":
            logger.warning("Unexpected payment payload: %s", payload)
            return
        kind = parts[1]
        user_id = message.from_user.id
        stars = int(sp.total_amount)
        charge_id = sp.telegram_payment_charge_id

        await self._stats.record_payment(user_id, kind, stars, charge_id)

        if kind == "month":
            new_until = await self._stats.extend_premium(user_id, 30 * 86400)
            await message.answer(
                f"✅ Premium активен до "
                f"{time.strftime('%d.%m.%Y', time.localtime(new_until))}. Спасибо!"
            )
        elif kind == "year":
            new_until = await self._stats.extend_premium(user_id, 365 * 86400)
            await message.answer(
                f"✅ Premium активен до "
                f"{time.strftime('%d.%m.%Y', time.localtime(new_until))}. Спасибо!"
            )
        elif kind == "5gb":
            total = await self._stats.add_bonus_bytes(
                user_id, self._limits.premium_bonus_bytes_5gb,
            )
            await message.answer(
                f"✅ Начислено +5 ГБ. Доступный запас: {total / (1024**3):.1f} ГБ."
            )
        else:
            await message.answer("✅ Оплата получена. Спасибо!")

    async def _register_bot_commands(self) -> None:
        try:
            await self.bot.set_my_commands([
                BotCommand(command="start", description="Главное меню"),
                BotCommand(command="stats", description="Моя статистика"),
                BotCommand(command="premium", description="⭐ Premium"),
                BotCommand(command="help", description="Помощь"),
            ])
        except Exception:
            logger.exception("Failed to register bot commands")

    async def start(self) -> None:
        logger.info("Starting Telegram bot...")
        await self._register_bot_commands()
        await self.dp.start_polling(self.bot)

    async def stop(self) -> None:
        try:
            await self.dp.stop_polling()
        except Exception:
            pass
        await self.bot.session.close()
