# SEO & Growth Plan — SaveItDL

## 1. Название и отображение бота

### Display Name (видимое имя в Telegram)
Ключевое правило: **поисковые слова в начале display name**. Telegram индексирует display name с большим весом, чем username.

**Рекомендация:**
```
SaveItDL — Video & Music Downloader
```

Почему: "Video" и "Music Downloader" — ключевые слова, по которым ищут. Стоят после бренда, но в пределах индексации. Конкуренты используют тот же паттерн: "SaveVideoBot", "All Video Downloader", "YouTubot".

Username: `@SaveItDLbot`

### About (120 символов, показывается в профиле)
```
Download video & audio from any link — YouTube, TikTok, Instagram, SoundCloud, X and 1000+ sites. Fast, free, no ads.
```

### Description (512 символов, показывается при /start нового юзера)
```
🎬 Universal media downloader

Send any link — get video or MP3 back in seconds.

✅ Supported:
• YouTube, TikTok, Instagram, Reels
• Twitter/X, Reddit, Facebook
• SoundCloud, VK, Rutube
• 1000+ more sites

⚡ Features:
• Video (MP4) or Audio (MP3)
• Fast parallel downloads
• No watermarks, no ads
• Free: 10 downloads/day
• Premium: unlimited

Just paste a link and go!

@SaveItDLbot
```

### Short Description (для инлайн-поиска, 120 символов)
```
Download video & audio from TikTok, YouTube, Instagram, Twitter, SoundCloud. Any link, any site. Free & fast.
```

---

## 2. Конкуренты — анализ рынка

### Топ боты

| Бот | Поддержка | Модель | Юзеры | Слабости |
|---|---|---|---|---|
| @SaveVideoBot | Только Telegram-видео (forward) | Бесплатно | Крупнейший | Не качает по ссылкам |
| @SaveViBot | YouTube, Vimeo, Instagram, 9gag | Бесплатно | Высокие | Мало платформ |
| @allsaverbot | Forwarded messages | Бесплатно | Средне-высокие | Только forward, не URL |
| @youtubot | 1050+ сайтов, перевод, саммари | Freemium | Растущий | Перегружен фичами |
| @allvideo_downloader_bot | 1000+ (YT, TikTok, IG, FB, VK) | Бесплатно | Средние | Нет premium |
| @SaveVideoPro_bot | TikTok, IG, YT Shorts, X | Бесплатно (open-source) | Новый | Мало платформ |

### Наше конкурентное преимущество
1. **1000+ сайтов через yt-dlp** — большинство конкурентов поддерживают 5-20
2. **Выбор формата: видео или MP3** — многие отдают только видео
3. **Без водяных знаков** — TikTok и другие
4. **Premium через Stars** — почти никто не монетизирует, пустая ниша
5. **Мультиплатформенность** — Telegram + Discord + VK (один код)
6. **Fault-tolerant архитектура** — изоляция модулей, авто-рестарт, алерты админу

### Ценовые модели конкурентов
Большинство ботов **полностью бесплатные** — монетизация через рекламу каналов.
**Premium через Stars — недоиспользованная возможность.**

---

## 3. Аватарка бота

### Что работает у топов
- Красный/play-button (ассоциация с YouTube)
- Синий (нативный Telegram)
- Зелёный (download/save)
- Фиолетовый/градиент (современный feel)
- Иконки: стрелка вниз, play-кнопка, облако со стрелкой

### Рекомендация для SaveItDL
- **Цвет:** фиолетово-синий градиент — выделяется среди красных/синих конкурентов
- **Иконка:** жирная стрелка вниз (↓) в круге
- **Стиль:** flat, минимальный, без текста — должно читаться в 30px кружке
- **Размер:** 512x512 px
- **Сделать бесплатно:** Canva или Figma

---

## 4. Как вырваться в топ поиска

### Главный фактор ранжирования (с 2024): Premium-юзеры
Telegram Premium подписчики, взаимодействующие с ботом, дают **~3x вес** в алгоритме.
Даже 10-20 Premium-юзеров значительно влияют на позицию.

**Как привлечь Premium-юзеров:**
- Попросить друзей с Premium запустить бота
- Посты в Telegram-каналах с платёжеспособной аудиторией
- Качественный сервис → Premium-юзеры сами находят и остаются

### Все факторы ранжирования (по убыванию)
1. **Premium user engagement** — доминирующий сигнал
2. **Ключевые слова в display name** — "Video Downloader" в названии
3. **Username** — индексируется, но меньший вес
4. **Активность/uptime** — мёртвые боты удаляются из поиска
5. **Консистентность engagement** — регулярные взаимодействия
6. **Рейтинг на каталогах** — StoreBot, BotList

### Цикл обновления индекса: каждые 20-30 дней
После оптимизации ждать месяц до видимого эффекта.

---

## 5. Бесплатная реклама — пошаговый план

### Неделя 1: Базовое присутствие (2-3 часа)

- [ ] **BotFather полная настройка**
  - Display name с ключевыми словами (текст выше)
  - About, Description, Short Description
  - Аватарка (фиолетово-синий градиент, стрелка вниз)
  - Включить inline mode
  - /setcommands: start, help, formats

- [ ] **Каталоги ботов** (даёт 50-300 юзеров/мес)
  - findmini.app
  - toptelegrambots.com
  - botsfortelegram.com
  - botlist.co
  - botostore.com (русскоязычный)
  - storebot.me

### Неделя 2: GitHub + лендинг (2-3 часа)

- [ ] **GitHub README** (SEO-трафик из Google)
  - Заголовок: "SaveItDL — Telegram Bot to Download Videos from Any Site"
  - Topics: `telegram-bot`, `video-downloader`, `tiktok-downloader`, `youtube-downloader`, `instagram-downloader`, `media-downloader`, `python`, `yt-dlp`, `soundcloud-downloader`
  - Секция "Try it now" → t.me/SaveItDLbot
  - Бейджи: Python, License, Stars
  - Скриншоты работы
  - README на русском + английском

- [ ] **GitHub Pages лендинг** (бесплатный SEO-сайт)
  - Title: "Free Video Downloader Bot for Telegram — SaveItDL"
  - H1: "Download Videos from YouTube, TikTok, Instagram and 1000+ sites"
  - Русские ключевики в тексте
  - Кнопка "Open in Telegram"
  - Адрес: bxdis.github.io/SaveItDL

### Неделя 3: Форумы и Reddit (2-3 часа)

- [ ] **Reddit** (может дать 100-500 юзеров разово)
  - r/Telegram — "I built a free bot that downloads from 1000+ sites"
  - r/TelegramBots — демо + описание
  - r/selfhosted — open source аспект
  - r/Python — "Built with yt-dlp + aiogram"
  - Формат: "I made this, feedback welcome" (не реклама)

- [ ] **4PDA** (русскоязычная)
  - Раздел Telegram → тема со скриншотами

- [ ] **Habr** (1 час)
  - "Как я написал универсальный Telegram-бот для скачивания видео"
  - Технический контент + пользовательская ценность

### Неделя 4: Telegram-каналы

- [ ] **Каналы с подборками ботов**
  - Поиск: "полезные боты", "telegram лайфхаки", "подборка ботов"
  - Написать админам: "сделал бота, может подойдёт для подборки?"
  - Бартер: упоминание их канала в боте за пост

- [ ] **Тематические каналы**
  - TikTok: "бот для скачивания без водяного знака"
  - Музыкальные: "скачать с SoundCloud"
  - Контент-мейкеры: полезный инструмент

### Постоянно: виральный рост

- [ ] **Встроенное в бота:**
  - Caption на бесплатных загрузках: "Downloaded via @SaveItDLbot"
  - Кнопка "Share with friends" после /start
  - Реферальная система: пригласи 3 → +5 загрузок/день

- [ ] **Канал обновлений** (@SaveItDLnews)
  - Новые фичи, новые сайты, статус
  - Напоминание о боте для подписчиков

---

## 6. SEO ключевые слова

### Русские (GitHub README, лендинг)
- скачать видео с тикток без водяного знака
- скачать видео из инстаграм
- скачать музыку из саундклауд
- бот для скачивания видео телеграм
- скачать рилс инстаграм
- скачать видео с ютуба бесплатно
- скачать видео с твиттера
- скачать аудио mp3 телеграм бот
- универсальный загрузчик видео

### Английские (GitHub, BotFather, каталоги)
- telegram video downloader bot
- download tiktok without watermark
- save instagram reels telegram
- download soundcloud mp3 bot
- free video downloader bot telegram
- download twitter video bot
- youtube to mp3 telegram bot
- all in one video downloader

---

## 7. Метрики и цели

| Метрика | 1 мес | 3 мес | 6 мес |
|---|---|---|---|
| Всего юзеров | 300-500 | 2,000-5,000 | 10,000+ |
| DAU | 30-50 | 200-500 | 1,000+ |
| Загрузок/день | 100-200 | 1,000-3,000 | 5,000+ |
| Premium-юзеров | 5-10 | 30-50 | 100+ |
| Доход/мес | 300-650₽ | 2,000-3,500₽ | 7,000+₽ |
| Позиция "video downloader" | нет в топе | топ-20 | топ-10 |

Окупаемость (842₽/мес) на 2-3 месяц.

---

## 8. Стратегия прорыва в топ

Конкуренция высокая, но у топов есть слабости:
- **@SaveVideoBot** — только forward, не по ссылкам
- **@SaveViBot** — мало платформ
- **@allsaverbot** — только forward
- **Мелкие боты** — часто ломаются, нет поддержки

### Наша ниша: "скачать по ссылке из любого сайта"
Большинство топовых ботов НЕ качают по ссылкам — они работают с forwarded messages. Мы закрываем другой use case.

### План по месяцам:
1. **Месяц 1-2:** каталоги + Reddit + форумы → 500 юзеров
2. **Месяц 2-3:** привлечь 10-20 Premium-юзеров → рост в поиске
3. **Месяц 3-4:** канал + реферальная система → органический рост
4. **Месяц 4-6:** Habr статья + SEO лендинг → поисковый трафик
5. **Постоянно:** надёжность и скорость = сарафанное радио
