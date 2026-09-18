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
- [x] ReplyKeyboardMarkup — persistent bottom buttons
- [x] Banner image + inline menu on /start
- [x] Bot commands registered via set_my_commands (visible in "/" menu)
- [x] HTML-escaping for user-supplied strings in messages
- [x] Local Bot API Server support for 2GB uploads
- [x] Extended analytics: sessions, premium tracking, start params, user actions, D1 retention, language stats, new users, avg download speed

### Supported out of the box
YouTube, TikTok, Instagram + Reels, X.com, SoundCloud, Facebook, VK Video, Rutube, Twitch (clips + VODs), Pornhub, xHamster, xGroovy, FapHouse, YouPorn, Eporner

### Require extra work
- Spotify (spotdl), Yandex Music (cookies), Bluesky (custom), Kinopoisk (DRM — impossible)

---

## v1.1 — Reliability & hardening (next)
See `REVIEW_LOGIC.md` and `REVIEW_SECURITY.md` for the full list.

- [ ] Per-user rate limiting (1 req / 5 sec) — see REVIEW_SECURITY.md
- [ ] Per-user download quota (10/day free, ~500MB/day)
- [ ] Per-file size pre-check (reject huge files before download)
- [ ] Download timeout: kill stuck jobs after 5 min, free the slot
- [ ] Fair queue: round-robin per user, one active download per user max
- [ ] Worker pool: graceful shutdown via sentinel, drain queue on stop
- [ ] Trim callback-payload length (`start_param`, VOD range) to safe bounds
- [ ] URL allowlist / block internal hostnames (SSRF hardening)
- [ ] Migrate `_pending_urls` and `_awaiting_range` to SQLite or Redis (survive restarts)
- [ ] SQLite WAL checkpoint on shutdown

## v1.2 — UX polish
See `REVIEW_UI_UX.md`.

- [ ] Progress bar during download (edit status_msg every N%)
- [ ] Short video (<60s) → sent as video note (round preview)
- [ ] Thumbnail preview inside format-selection message
- [ ] Retry button on download failures
- [ ] "Cancel current download" button while queued/running
- [ ] i18n scaffold (RU/EN/ES) via language_code
- [ ] Web App button for a mini-app stats view (visually distinct blue button)
- [ ] Reply keyboard: hide once user is comfortable / on demand

## v1.3 — Extra sources
- [ ] Spotify (spotdl integration)
- [ ] Yandex Music (cookies auth)
- [ ] Bluesky (AT Protocol API)
- [ ] Pinterest, Likee
- [ ] Admin /setcookies for auth-required sites

## v1.4 — Deploy & ops (done)
- [x] Cloud-init script (Ubuntu + Python + ffmpeg + systemd)
- [x] systemd unit runs directly from `/opt/saveitdl/repo` (no cp duplication)
- [x] `deploy/update.sh` = git pull + restart (no manual copying)
- [x] Logrotate
- [x] Auto yt-dlp update (weekly cron)
- [x] Auto temp cleanup (hourly, files >1h old)
- [x] stats.db backup (daily)

## v1.5 — Monetization
- [ ] Telegram Stars payments (`pay=True` button — natively green)
- [ ] Premium: no limits, no caption, priority queue, 4K
- [ ] Referral: invite 3 → +5 downloads/day
- [ ] /premium command + inline payment
- [ ] Revenue tracking in /adminstats

## v1.6 — More bot platforms
- [ ] Discord adapter (discord.py)
- [ ] VK bot adapter (vkbottle)
- [ ] Per-platform file limits (Discord 25MB, Telegram 50MB / 2GB)
- [ ] Shared stats DB across platforms

## v1.7 — Growth & SEO
- [ ] Landing page (GitHub Pages)
- [ ] Bot catalog listings (findmini, toptelegrambots, botlist, botostore)
- [ ] GitHub README with screenshots + "Try It Now"
- [ ] Reddit / 4PDA / Habr launch posts
- [ ] @SaveItDL updates channel content plan
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
