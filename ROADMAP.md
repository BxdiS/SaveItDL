# All Downloader Bot — Roadmap

## v1.0 — MVP (done)
- [x] Core: yt-dlp downloader with video/audio support
- [x] Worker pool with async queue (MAX_WORKERS, QUEUE_SIZE)
- [x] Telegram adapter (aiogram)
- [x] Modular platform architecture (base adapter)
- [x] Config via .env

### Supported sites out of the box (yt-dlp)
- [x] YouTube (videos + music)
- [x] TikTok (without watermark)
- [x] Instagram (posts + reels)
- [x] X.com / Twitter
- [x] SoundCloud
- [x] Facebook
- [x] VK Video
- [x] Rutube

### Require extra work
- [ ] Spotify — no audio stream, needs spotdl integration
- [ ] Yandex Music — yt-dlp extractor exists but needs auth cookies
- [ ] Bluesky — no yt-dlp extractor, needs custom downloader
- [ ] HD Kinopoisk — DRM (Widevine), not possible without license keys

## v1.1 — User limits & anti-abuse
- [ ] SQLite database for user tracking
- [ ] Per-user daily download limit (default: 10/day free)
- [ ] Premium tiers: unlimited downloads via invite code or payment
- [ ] Rate limiting: max 1 request per 5 seconds per user
- [ ] Cooldown message with remaining time
- [ ] /mystats command — show user's usage today
- [ ] Admin commands: /setlimit, /ban, /stats

## v1.2 — Extra sources
- [ ] Spotify support via spotdl (audio download + metadata)
- [ ] Yandex Music via cookies auth flow
- [ ] Bluesky video download (custom extractor via AT Protocol API)
- [ ] Cookie management: /setcookies for sites that need auth

## v1.3 — Quality of life
- [ ] Inline progress bar (edit message with ▓░░░ 23%)
- [ ] Auto-detect format: short videos → send as video note, music links → audio
- [ ] Thumbnail preview before download
- [ ] /formats command — show available qualities
- [ ] Error messages in Russian
- [ ] Retry button on failed downloads

## v1.4 — Deploy & infrastructure
- [ ] Cloud-init script for one-click server setup (Ubuntu + Python + ffmpeg + systemd)
- [ ] systemd unit file for auto-restart
- [ ] Logrotate config
- [ ] Health check endpoint

## v1.5 — More bot platforms
- [ ] Discord adapter (discord.py)
- [ ] VK bot adapter
- [ ] Platform-specific file limits handling

## v1.6 — Monetization
- [ ] Telegram Stars payments for premium
- [ ] Referral system (invite 3 friends → +5 downloads/day)
- [ ] Ad insertion (optional promo caption on free downloads)

## v1.7 — Growth & SEO
- [ ] Landing page (GitHub Pages, free) with bot link + keywords
- [ ] Listings on Telegram bot catalogs (TelegramCatalog, BotFather catalog, t.me/bots)
- [ ] GitHub repo with good README (SEO for "telegram video downloader bot")
- [ ] Posts on relevant forums and channels

## v2.0 — Scale
- [ ] Redis queue instead of in-memory (multi-server)
- [ ] Horizontal scaling: worker nodes behind load balancer
- [ ] Download caching: same URL within 1h → serve from cache
- [ ] Prometheus metrics + Grafana dashboard
- [ ] Auto-update yt-dlp on schedule (sites change extractors often)
