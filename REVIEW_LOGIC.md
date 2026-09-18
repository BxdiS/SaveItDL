# Logic & Architecture Review

Проверка на race conditions, утечки, некорректную обработку ошибок, мёртвый код.

Уровни: **Critical** (баг с ущербом), **Bug** (пользователь заметит), **Smell** (техдолг).

---

## Исправлено в этом PR

### `handle_menu:stats` показывал статистику бота [Critical → done]
Обработчик передавал `callback.message` в `_send_user_stats`, а внутри читался `message.from_user.id`. Для сообщений, отправленных ботом, это **id самого бота**. То есть кнопка «Моя статистика» из /start показывала пустоту всегда.

Пофикшено: `_send_user_stats(user_id, message)` теперь явно принимает id.

### Deploy запускался с копии, а не из git-repo [Critical → done]
`cloud-init.yml` копировал `*.py`, `core/`, `platforms/` из `repo/` в `/opt/saveitdl/`. systemd работал из копии. `git pull` обновлял только `repo/`. Итог: **все фиксы попадали в git и не запускались в проде**, пока `update.sh` не сделает `cp` ещё раз.

Пофикшено: `WorkingDirectory=/opt/saveitdl/repo`, cp-строки удалены. `update.sh` теперь только `git pull` + `pip install` + `restart`.

---

## Не исправлено — на v1.1

### 1. WorkerPool не останавливается корректно [Bug]
```python
async def start(self) -> None:
    self._running = True
    while self._running:
        job = await self._queue.get()  # блокируется навсегда
        asyncio.create_task(self._process(job))

async def stop(self) -> None:
    self._running = False  # никогда не проверится, пока не придёт job
```

`stop()` устанавливает флаг, но `start()` висит на `await queue.get()`. Sentinel нужен:

```python
async def stop(self) -> None:
    self._running = False
    await self._queue.put(None)  # разбудить loop

async def start(self) -> None:
    while self._running:
        job = await self._queue.get()
        if job is None:
            break
        asyncio.create_task(self._process(job))
```

Плюс: активные `_process`-таски не отменяются при shutdown. Файл в `downloads/` останется. Нужно `asyncio.gather` активных с timeout.

### 2. `_process` создаёт fire-and-forget таск [Smell]
`asyncio.create_task(self._process(job))` — созданный таск нигде не хранится. GC может его собрать до завершения (в теории — на практике event loop держит ссылку через _ready). Но при shutdown мы про эти таски не знаем и не можем их дождаться.

**Fix:** `self._active_tasks: set[Task]`, добавлять/удалять через `add_done_callback`.

### 3. `_running` в WorkerPool никогда не проверяется в самом `_process` [Smell]
Задание, взятое из очереди, будет обработано полностью, даже если бот получил SIGTERM. Для download 2GB это может значить ждать минуту после stop.

### 4. `pool.start()` — если упадёт, никто не рестартует [Bug]
`main.py` создаёт `asyncio.create_task(pool.start())` в `bg_tasks`. Если исключение внутри while — таск отвалится, все subsequent job'ы будут висеть в очереди. `run_platform_isolated` есть только для платформ.

**Fix:** обернуть `pool.start()` в свой aналог `run_isolated` с рестартом.

### 5. `monitor_health` игнорирует `error_window` [Smell]
```python
async def monitor_health(pool, notifier, temp_dir):
    error_window: list[bool] = []  # <-- никогда не используется
    while True:
        ...
```

Мёртвая переменная. Изначально задумывалось скользящее окно ошибок для `download_error_spike`, но реализация не дописана. Или убрать переменную, или дописать проверку.

### 6. `MAX_FILESIZE = 2GB` в downloader.py — не связан с TELEGRAM_FILE_LIMIT [Smell]
```python
# downloader.py
MAX_FILESIZE = 2 * 1024 * 1024 * 1024  # 2 GB hard limit

# telegram.py
TELEGRAM_FILE_LIMIT_DEFAULT = 50 * 1024 * 1024
TELEGRAM_FILE_LIMIT_LOCAL = 2000 * 1024 * 1024
```

Downloader ограничивает 2GB **всегда**, независимо от того, есть ли local API. Если local API включён — файл до 2000MB (~2GB, чуть меньше). Если нет — файл до 2GB скачается, но потом на upload вернётся ошибка «слишком большой», и файл удалится. Трата трафика.

**Fix:** передавать `max_filesize` в `Downloader.download` из платформы. Тогда yt-dlp сам отклонит слишком большое видео до скачивания.

### 7. `_pending_urls` теряется при рестарте [Bug]
После рестарта бота (а он у нас каждые 5 минут — см. WatchdogSec, если ещё не убран) все `url_id` из callback-кнопок мертвы. Пользователь жмёт кнопку → «⏳ Ссылка устарела».

**Fix:** хранить в SQLite с TTL 24h. Или Redis. Не блокер, но UX страдает.

### 8. `_awaiting_range` — то же самое + утечка памяти [Smell]
Пользователь начал VOD-flow, не отправил диапазон → `_awaiting_range[user_id]` живёт до перезапуска. При 10k таких пользователей — небольшая, но растущая утечка.

**Fix:** TTL 10 минут на записи. Или сохранить в SQLite.

### 9. Callback answer > 30s → Telegram отругает [Bug]
Некоторые callback хендлеры делают тяжёлые DB-запросы (админские `_edit_admin_*` вызывают `get_global_stats`, который делает 15+ SELECT). Если БД занята — > 30 сек, Telegram считает callback необработанным.

Мы делаем `await callback.answer()` в начале, что должно решить это. Но `handle_menu:stats` делает answer первым, затем `_send_user_stats` — норм. Двойная проверка не помешает.

### 10. `URL_REGEX = r"https?://\S+"` жадный [Smell]
`https://example.com/path.` (с точкой в конце текста) — точка съедается regex. yt-dlp может отвергнуть URL. Заменить на `\S+?(?=[\s.,;!?)]|$)` или strip trailing punctuation после match.

### 11. `_short_id` дублируется [Smell]
```python
# _store_url:
uid = _short_id(url)
...
return uid

# _handle_vod_range:
url_id = _short_id(url)  # опять тот же хэш
```

Два раза считаем один и тот же хэш. Мелочь, но признак: логика хранения url_id должна быть в одном месте.

### 12. `info.formats` не ограничен по длине [Smell]
yt-dlp может вернуть 100+ форматов (YouTube с DASH). Мы храним весь список в `_pending_info`. 5000 пользователей × 100 форматов = много объектов. Обычно ок, но не помешает `info.formats = info.formats[:20]` при сохранении.

### 13. `StatsDB._conn()` создаёт новое соединение каждый вызов [Smell]
На каждый action/download/user-update — свежий connect + WAL setup. Не медленно, но не оптимально. Можно кэшировать одно read-only соединение для GET-запросов.

Или переехать на `aiosqlite` — единожды open, все запросы асинхронно. Уберёт также `run_in_executor`.

### 14. `_lock` в StatsDB избыточен [Smell]
`asyncio.Lock` вокруг `run_in_executor` — сериализует не потому что нужно, а потому что «на всякий случай». SQLite с `busy_timeout=5000` сам справится. Но лок мешает: два `track_action` не могут исполниться параллельно.

Убрать `_lock` — параллелизация UPDATE вырастет.

### 15. `stop()` в TelegramPlatform не останавливает polling [Bug]
```python
async def stop(self) -> None:
    await self.bot.session.close()
```

Это закрывает aiohttp session, но `dp.start_polling` в `start()` продолжает крутить loop. Отсюда 90-секундная задержка SIGKILL при shutdown.

**Fix:** `await self.dp.stop_polling()` перед закрытием сессии.

### 16. `run_platform_isolated` — CancelledError не пробрасывается [Smell]
```python
except asyncio.CancelledError:
    logger.info("Platform %s shutting down", name)
    return
```

По PEP: CancelledError надо re-raise, иначе внешний код думает, что таск завершился штатно. Не критично здесь (у нас именно этого и хотим), но не идиоматично.

### 17. `admin_id: int | str | None` в notifier.py [Smell]
```python
def __init__(self, admin_id: int | str | None = None):
```
Тип `str` не имеет смысла — Telegram user_id всегда int. Origin unclear. Убрать `str` из union.

### 18. `download` handle_message → info extraction blocking [Bug]
`await self.downloader.get_info(url)` — синхронный yt-dlp в executor. Для сложных URL может занять 5-10 сек. Мы уже отправили статус «🔍 Анализирую…», но если 10 пользователей одновременно шлют ссылки — executor будет забит. Дефолтный `ThreadPoolExecutor` имеет max_workers = cpu_count() (обычно 4-8).

**Fix:** свой ThreadPoolExecutor для yt-dlp, отдельно от general default. `loop.run_in_executor(self._executor, ...)`. Или timeout + fallback.

### 19. `_send_admin_main` в `cmd_adminstats` [Smell]
`/adminstats` = `/admin`. Копипаст обработчиков. Убрать один или сделать `Command("admin", "adminstats")`.

---

## Мертвый / неиспользуемый код

### `MAX_RESTART_ATTEMPTS`, `RESTART_DELAY_BASE` — ок, используются.
### `AlertLevel.INFO` — определён в enum, но никогда не вызывается. Оставить для будущего.
### `DownloadStatus.PENDING`, `.FAILED` — определены в models.py, не используются нигде. Можно удалить или заиспользовать в UI (показывать pending/failed).
### `on_progress` callback в downloader — определён, `progress_hooks` подключены, но ни одна платформа не передаёт колбэк. Мёртвый feature — пробуждается только когда сделаем progress bar в UI (см. REVIEW_UI_UX #7).

---

## Общее замечание про архитектуру

Разделение `Downloader` / `WorkerPool` / `TelegramPlatform` — чистое. Легко добавить Discord: только `platforms/discord.py`. Единственное подрастание — `TelegramPlatform` — 890 строк, из них половина — админка. Стоит выделить `admin.py` в отдельный файл-модуль (класс AdminHandlers, регистрируется через `dp.include_router`). Это упростит и тестирование, и параллельную работу — админ-фичи и user-фичи не смешиваются в diff'ах.
