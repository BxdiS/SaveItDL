# SaveItDL — Video & Audio Downloader Bot for Telegram

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/BxdiS/SaveItDL)](https://github.com/BxdiS/SaveItDL/stargazers)

Video and audio downloader — self-hosted or via Telegram bot.

**Don't want to host anything?** Just use [@SaveItDLbot](https://t.me/SaveItDLbot) in Telegram. Send a link, get the file. Free with a daily limit.

**Want your own instance?** Clone, configure, deploy. Full control, no limits.

## What it does

Send a video or audio link — get the file back. Supports YouTube, TikTok, Instagram, Twitter/X, SoundCloud, Reddit, Facebook, VK, Rutube, Twitch and [everything else yt-dlp supports](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md).

- Choose between video (MP4) or audio (MP3)
- Quality selection from available formats
- Audio metadata (ID3 tags) embedded automatically
- No watermarks on TikTok and similar
- No ads, no tracking

## Try it

[@SaveItDLbot](https://t.me/SaveItDLbot) — open in Telegram, paste a link.

## Self-hosting

### Requirements

- Python 3.11+
- ffmpeg
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

### Setup

```bash
git clone https://github.com/BxdiS/SaveItDL.git
cd SaveItDL
pip install -r requirements.txt
cp .env.example .env
# edit .env — set TELEGRAM_TOKEN and ADMIN_ID
python main.py
```

### Configuration

All config is in `.env`:

| Variable | Default | Description |
|---|---|---|
| `TELEGRAM_TOKEN` | — | Bot token from BotFather |
| `ADMIN_ID` | — | Your Telegram user ID (for admin panel) |
| `MAX_WORKERS` | 4 | Simultaneous downloads |
| `QUEUE_SIZE` | 100 | Max queued requests |
| `TEMP_DIR` | downloads | Temp file directory |
| `BOT_API_URL` | — | Local Bot API server URL (for 2GB uploads) |

### Deploy to a VPS

There's a cloud-init script and systemd unit in `deploy/`. Tested on Ubuntu 22.04, 2 vCPU / 4 GB RAM.

```bash
# on the server
bash deploy/cloud-init.sh
systemctl start saveitdl
```

Optionally, install [Telegram Bot API Local Server](https://github.com/tdlib/telegram-bot-api) to upload files up to 2 GB instead of the default 50 MB limit. See `deploy/install-bot-api.sh`.

## Architecture

```
main.py              — entry point, platform orchestration
config.py            — .env config loader
core/
  downloader.py      — yt-dlp wrapper (get_info, download)
  worker_pool.py     — async queue with semaphore
  metadata.py        — audio ID3 tag embedding (mutagen)
  stats.py           — SQLite analytics (users, downloads, errors)
  notifier.py        — admin alerts via Telegram
  models.py          — shared data models
platforms/
  base.py            — abstract platform adapter
  telegram.py        — Telegram bot (aiogram 3)
```

Download logic is shared — platform adapters are pluggable. Telegram is first, Discord is planned.

## Admin

Set `ADMIN_ID` in `.env` to your Telegram user ID. Then use `/admin` in the bot for:

- User stats and download counts
- Recent downloads and errors
- Top users
- System overview

---

## RU — Описание на русском

Бот для скачивания видео и аудио из YouTube, TikTok, Instagram, Twitter, SoundCloud и других сайтов.

**Не хочешь ничего устанавливать?** Открой [@SaveItDLbot](https://t.me/SaveItDLbot) в Telegram — отправь ссылку, получи файл. Бесплатно.

**Хочешь свой сервер?** Клонируй репо, настрой `.env`, запусти. Без ограничений.

### Возможности

- Скачать видео (MP4) или аудио (MP3) по ссылке
- Выбор качества из доступных форматов
- Без водяных знаков (TikTok и другие)
- ID3-теги для аудио (исполнитель, альбом, дата)
- Без рекламы, без трекинга
- Open source

### Поддерживаемые сайты

YouTube, TikTok, Instagram, Reels, Twitter/X, Reddit, Facebook, SoundCloud, VK, Rutube, Twitch и [все остальные через yt-dlp](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md).

## License

MIT
