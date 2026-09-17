# SaveItDL — Roadmap

## v1.0 — MVP (done)
- [x] Core: yt-dlp downloader with video/audio support
- [x] Worker pool with async queue (MAX_WORKERS, QUEUE_SIZE)
- [x] Telegram adapter (aiogram 3)
- [x] Modular platform architecture (base adapter)
- [x] Config via .env
- [x] Smart format detection: video → 1080/720/480, audio → bitrate options
- [x] Twitch VOD range download (prompt for time range if >30 min)
- [x] Fault-tolerant: platform isolation, auto-restart, exponential backoff
- [x] Admin alerts via Telegram (crashes, queue full, disk space)
- [x] Health monitor (disk, queue saturation, every 60s)
- [x] Full statistics: SQLite tracking of users, downloads, platforms, errors
- [x] /stats — personal stats
- [x] /adminstats — full admin dashboard
- [x] /errors — recent download errors
- [x] Audio metadata embedding (ID3 tags: artist, album, date, genre via mutagen)
- [x] ReplyKeyboardMarkup — persistent bottom buttons (📊 My Stats, ❓ Help)
- [x] Beautiful UI: HTML formatting, banners, structured messages, Russian locale
- [x] Extended analytics: sessions, premium tracking, start params, user actions, D1 retention, language stats, new users, avg download speed

### Supported out of the box
YouTube, TikTok, Instagram + Reels, X.com, SoundCloud, Facebook, VK Video, Rutube, Twitch (clips + VODs)

### Require extra work
- Spotify (spotdl), Yandex Music (cookies), Bluesky (custom), Kinopoisk (DRM — impossible)

---

## v1.1 — User limits & anti-abuse
- [ ] Per-user daily download limit (10/day free)
- [ ] Premium tiers: unlimited via Stars payment
- [ ] Rate limiting: 1 req / 5 sec per user
- [ ] Cooldown message with remaining time
- [ ] Admin: /setlimit, /ban, /unban

## v1.2 — Extra sources
- [ ] Spotify (spotdl integration)
- [ ] Yandex Music (cookies auth)
- [ ] Bluesky (AT Protocol API)
- [ ] Pinterest, Likee
- [ ] Admin /setcookies for auth-required sites

## v1.3 — UX improvements
- [ ] Inline progress bar (▓▓▓░░ 60%)
- [ ] Short videos (<60s) → video note (circle)
- [ ] Thumbnail in format selection
- [ ] /help with full guide
- [ ] Retry button on failures
- [ ] "via @SaveItDLbot" caption (viral, free tier only)
- [ ] Share button after download

## v1.4 — Deploy & ops
- [x] Cloud-init script (Ubuntu + Python + ffmpeg + systemd)
- [x] systemd unit with watchdog
- [x] Logrotate
- [x] Auto yt-dlp update (weekly cron)
- [x] Auto temp cleanup (hourly, files >1h old)
- [x] stats.db backup (daily)

## v1.5 — Monetization
- [ ] Telegram Stars payments
- [ ] Premium: no limits, no caption, priority queue, 4K
- [ ] Referral: invite 3 → +5 downloads/day
- [ ] /premium command + inline payment
- [ ] Revenue tracking in /adminstats

## v1.6 — More bot platforms
- [ ] Discord adapter (discord.py)
- [ ] VK bot adapter (vkbottle)
- [ ] Per-platform file limits (Discord 25MB, Telegram 50MB)
- [ ] Shared stats DB across platforms

## v1.7 — Growth & SEO
- [ ] Landing page (GitHub Pages)
- [ ] Bot catalog listings (findmini, toptelegrambots, botlist, botostore)
- [ ] GitHub README with screenshots + "Try It Now"
- [ ] Reddit / 4PDA / Habr launch posts
- [ ] @SaveItDLnews updates channel
- [ ] Public download counter (trust signal)

## v2.0 — Scale
- [ ] Redis queue (multi-server)
- [ ] Horizontal scaling: worker nodes + shared queue
- [ ] Download cache (same URL within 1h → cached file)
- [ ] Prometheus + Grafana
- [ ] PostgreSQL migration
- [ ] API endpoint for integrations

## v2.1 — Advanced features
- [ ] Playlist download → zip or sequential
- [ ] Batch: multiple URLs in one message
- [ ] Audio trimming (user sends range)
- [ ] Video compression to fit 50MB limit
- [ ] Subtitle extraction (.srt/.vtt)
- [ ] Schedule downloads (off-peak)

## v2.2 — Analytics v2
- [ ] Weekly admin digest (automated Telegram report)
- [ ] Retention metrics: D7, D30
- [ ] Cohort analysis
- [ ] Geographic distribution (via language_code mapping)
- [ ] Download speed benchmarks per platform
- [ ] Cost per download tracking
- [ ] Funnel: URL sent → quality picked → download completed
- [ ] User segmentation (power users, one-time, returning)

## v2.3 — Security & compliance
- [ ] DMCA: block specific URLs/domains
- [ ] /mydata export (GDPR)
- [ ] /deletemydata
- [ ] Audit log for admin actions
- [ ] nginx rate limiting

## v3.0 — Platform
- [ ] Web admin dashboard
- [ ] Cross-platform user identity
- [ ] Plugin system for custom extractors
- [ ] White-label: custom branding per instance
- [ ] Webhook notifications
