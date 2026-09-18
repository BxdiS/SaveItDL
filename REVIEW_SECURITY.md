# Security Review

Проверка на инъекции, спам, DoS, утечки и обход авторизации.

Уровни риска: **High** (нужно чинить до релиза), **Medium** (не блокер, но легко эксплуатируется), **Low** (гипотетика или требует привилегий).

---

## Исправлено в этом PR

### HTML-инъекция в сообщениях бота [Medium → done]
Все поля из yt-dlp (`title`, `uploader`, `platform`, `error`) отправлялись в HTML parse_mode **без экранирования**. Заголовок вида `<b>hack</b>` ломал разметку. `title` c `<a href="...">` теоретически может вставить fake-ссылку в сообщение бота — фишинг.

Пофикшено: везде добавлен `html.escape(...)`. Проверил все `f"<...>{...}"` — user-контролируемые поля обёрнуты.

Также в `_edit_admin_users`/`_edit_admin_recent` — юзернеймы и `start_param` теперь тоже экранируются.

---

## Не исправлено — на v1.1

### 1. Нет rate-limit per user [High]
`handle_message` принимает любые ссылки без пауз. Один пользователь может отправить 100 ссылок за секунду, и все они пойдут в очередь. С учётом `MAX_WORKERS=4` и `QUEUE_SIZE=100`, один пользователь может забить всю очередь и заблокировать сервис для остальных.

**Fix:** декоратор middleware, который смотрит last_message_time для user_id, отклоняет если <5 сек.

### 2. Нет квоты по трафику per user [High]
Пользователь может скачать 1000 × 200MB в сутки → 200GB трафика с одного user_id. При платном исходящем трафике это счёт от хостера.

**Fix:** `stats.get_user_bytes_today(user_id)`, отклонять если >500MB. Уже в roadmap v1.1.

### 3. `download_range` от пользователя не ограничен снизу [Medium]
```python
start = _parse_timestamp(match.group(1))
end = _parse_timestamp(match.group(2))
if start is None or end is None or end <= start:
    ...
```

Проверяется `end - start <= 30min`. Но `start` может быть отрицательным? Нет, `_parse_timestamp` возвращает `None` для мусора и не парсит минусы. Но `start=0, end=1800` → OK. Что если `start=99999999`? Тогда `end` должен быть больше, парсится, ждёт `end - start ≤ 1800`. yt-dlp получит `download_ranges=[(99999999, ...)]` и просто не найдёт этот отрезок. Не критично, но лучше явно проверить `start >= 0 and end <= duration`.

### 4. `start_param` из deep-link → БД без ограничения длины [Medium]
`/start abc...500KB...` пойдёт в `users.start_param` целиком. SQLite не упадёт, но раздует таблицу.

**Fix:** обрезать до 64 символов в `_track_user`. `start_param[:64]`.

### 5. `MAX_PENDING = 5000` per instance [Medium]
Спамом можно вытеснить ссылки других пользователей из `_pending_urls` (LRU eviction). Их callback-кнопки перестанут работать → «⏳ Ссылка устарела».

**Fix:** LRU per-user, а не глобальный, ИЛИ хранить в БД с TTL.

### 6. Callback data не подписаны [Low]
`callback_data=f"f:{url_id}:v:{i}"` — если у пользователя A есть ссылка X с `url_id=abc`, а пользователь B получит `abc` в чате (например, скриншот), B нажать эту кнопку не сможет (Telegram привязывает callback к сообщению). Так что реальной атаки нет. Но админские `adm:*` — проверяются по user_id, ок.

### 7. `admin_id` из `.env` → ошибка парсинга рушит бот [Low]
```python
admin_id=int(os.getenv("ADMIN_ID", "0")) or None
```
Если `ADMIN_ID=abc` — `ValueError` на старте. Не эксплуатируется извне, но плохо для UX.

**Fix:** try/except, warning log, `admin_id = None`.

### 8. SSRF потенциал в yt-dlp [Low]
Пользователь может прислать `http://169.254.169.254/latest/meta-data/` (AWS metadata) или `http://localhost:8081/bot<token>/getMe` (наш локальный Bot API!). yt-dlp попытается это скачать. Обычно yt-dlp говорит «unsupported», но exploit-серия проверок для yt-dlp периодически появляется.

**Fix:** блокировать RFC1918 (10/8, 172.16/12, 192.168/16) и loopback (127/8, ::1) в URL_REGEX или отдельным чеком. Или запускать бота в изолированном netns без доступа к internal сети.

Приоритет — Medium если бот стоит рядом с чем-то чувствительным (тот же Bot API server слушает localhost:8081 без auth). У нас именно такой сценарий на сервере.

### 9. `.env` в `/opt/saveitdl/` — 0600 ok, но обе копии [Medium]
Раньше `.env` копировался и в `/opt/saveitdl/`, и в `/opt/saveitdl/repo/` — по 0600, но два места хранения секретов. После фикса деплоя (в этом PR) — один `/opt/saveitdl/.env`, systemd читает через `EnvironmentFile`. Стало лучше.

**Осталось:** на действующем сервере вручную удалить старый `/opt/saveitdl/.env` **после** миграции на новую схему деплоя. Пока просто убедиться, что оба идентичны.

### 10. SQLite: нет резервного бэкапа при вызовах [Low]
`stats.db` — единственный источник статистики. Cron делает `cp` daily в 3:30 UTC. Если бот прибит через 6 часов после бэкапа — теряется полдня данных.

**Fix:** `PRAGMA wal_checkpoint(TRUNCATE)` перед `stop()`. Уже в roadmap v1.1.

### 11. Отсутствие CSP/CORS для webhook [N/A]
Мы на polling, не webhook. Если перейдём на webhook — нужно валидировать `X-Telegram-Bot-Api-Secret-Token`.

### 12. Файлы во временной директории до cleanup [Low]
`Downloader.cleanup(result)` вызывается в `finally` внутри `on_complete`. Если процесс упадёт между записью файла и колбэком — файл остаётся. Cron `find -mmin +60 -delete` его подберёт — норм для 1-2 часов, но большие файлы могут забить диск.

**Fix:** cleanup на `SIGTERM` при shutdown. Или `find -mmin +30`.

### 13. Логи содержат токен [Low]
`aiogram` при retry-ошибке может логать URL с токеном в стектрейсе (`https://api.telegram.org/bot<TOKEN>/getUpdates`). Мы этого не видели, но стоит фильтровать в logging.

**Fix:** logging filter, который заменяет `bot\d+:[A-Za-z0-9_-]+` на `bot***`.

### 14. Нет audit-лога для админ-действий [Low]
Пока админ ничего не делает деструктивного, но когда добавим `/ban`, `/setlimit` — нужен `admin_actions` таблица. Уже в roadmap v2.3.

---

## Не-исправляемое (принято как есть)

- **DMCA-контент**: бот скачивает всё, что умеет yt-dlp. Юридический риск — на владельце инстанса. В /help стоит добавить disclaimer, но не блокер.
- **`_short_id(url)` 10 hex chars = 40 bits**: коллизии возможны после ~1M URL. Заменить на 16 chars = 64 bits тривиально, но не срочно.
