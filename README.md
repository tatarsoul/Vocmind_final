# VocMind

VocMind — это AI-сервис для записи, транскрибации и анализа встреч. Проект объединяет backend на FastAPI, Chrome extension, Telegram Mini App и Telegram-бота. Пользователь подключает расширение, записывает встречу, получает транскрипт, AI-протокол, историю встреч и экспорт результатов.

Проект рассчитан на локальный запуск backend с публичным HTTPS-доступом через ngrok. Это важно, потому что Telegram Bot и Telegram Mini App должны обращаться к backend по публичному HTTPS URL.

## Возможности

* Запись аудио из микрофона и/или вкладки браузера через Chrome extension.
* Streaming-обработка аудио чанками через backend.
* Распознавание речи через `faster-whisper`.
* Очистка транскрипта от дублей, ASR-галлюцинаций и служебного шума.
* AI-протокол встречи через Groq LLM.
* Опциональная LLM-полировка транскрипта.
* Live-подсказки и live-протокол для тарифов, где функция включена.
* Telegram Mini App как личный кабинет пользователя.
* Telegram-бот для входа, профиля и работы с тарифами.
* Активационные ключи и тарифные ограничения.
* История встреч, поиск, удаление и экспорт в PDF/DOCX.

## Архитектура проекта

```text
Vocmind_final/
├── app/                   # FastAPI backend
│   ├── main.py             # основной API, streaming, завершение записи
│   ├── config.py           # настройки из .env
│   ├── db.py               # подключение к PostgreSQL
│   ├── models.py           # SQLAlchemy-модели
│   ├── routers/            # auth, billing, bot, extension, miniapp
│   └── services/           # ASR, Groq, протоколы, экспорт, usage, streaming
├── vocmind-extension/      # Chrome extension для записи встреч
├── vocmind-miniapp/        # Telegram Mini App / личный кабинет
├── vocmind-bot/            # Telegram-бот на aiogram
└── tests/                  # unit/e2e/quality-тесты
```

## Как это работает

1. Backend запускается локально на `localhost:8000`.
2. ngrok создаёт публичный HTTPS URL и проксирует запросы на локальный backend.
3. Telegram-бот использует ngrok URL как `BACKEND_BASE_URL`.
4. Telegram Mini App открывается по адресу `https://your-ngrok-domain.ngrok-free.app/lk`.
5. Пользователь открывает Mini App в Telegram и авторизуется через Telegram `initData`.
6. Пользователь генерирует код подключения расширения.
7. Chrome extension подключается к backend через публичный ngrok URL.
8. Расширение отправляет аудио чанками в backend.
9. Backend транскрибирует аудио, генерирует протокол и сохраняет встречу.
10. Пользователь видит встречу в истории Mini App и может скачать экспорт.

## Технологический стек

### Backend

* Python
* FastAPI
* SQLAlchemy
* PostgreSQL
* Pydantic Settings
* `faster-whisper` / `ctranslate2`
* NumPy
* FFmpeg
* Groq API
* HTTPX
* `python-docx`
* ReportLab

### Telegram Bot

* Python
* aiogram
* Pydantic Settings
* HTTPX

### Frontend

* Vanilla JavaScript
* HTML/CSS
* Telegram WebApp API
* Chrome Extension Manifest V3

## Требования

* Python 3.11+
* PostgreSQL
* FFmpeg
* ngrok
* Groq API key
* Telegram bot token
* Локальная или скачанная модель Whisper, совместимая с `faster-whisper`
* Chromium-based browser для расширения

## Установка backend

```bash
git clone https://github.com/tatarsoul/Vocmind_final.git
cd Vocmind_final
python -m venv .venv
source .venv/bin/activate
```

Если в проекте ещё нет `requirements.txt`, зависимости можно установить так:

```bash
pip install fastapi "uvicorn[standard]" python-multipart sqlalchemy "psycopg[binary]" pydantic-settings httpx faster-whisper ctranslate2 numpy webrtcvad python-docx reportlab pytest
```

## Переменные окружения backend

Создай файл `.env` в корне проекта:

```env
# Telegram
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
BOT_TOKEN=your_telegram_bot_token

# Auth
AUTH_SECRET=change_me_to_long_random_secret
BOT_INTERNAL_KEY=change_me_internal_backend_bot_key

# PostgreSQL
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=vocmind

# Groq
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=llama-3.1-8b-instant
GROQ_TIMEOUT_SECONDS=20

# ASR / Whisper
ASR_MODEL=/path/to/whisper-small
ASR_LANGUAGE=ru
ASR_DEVICE=auto
ASR_COMPUTE_TYPE=auto

# FFmpeg
FFMPEG_PATH=/usr/bin/ffmpeg

# Pipeline flags
ENABLE_LIVE_PROTOCOL=false
ENABLE_TRANSCRIPT_POLISH=true
ENABLE_FINAL_RETRANSCRIBE=false
```

> Для production и публичного тестирования обязательно замени `AUTH_SECRET` и `BOT_INTERNAL_KEY` на собственные секретные значения. Не коммить `.env` в репозиторий.

## Запуск backend

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Проверь healthcheck:

```bash
curl http://localhost:8000/health
```

Ожидаемый ответ:

```json
{"ok": true}
```

При старте backend создаёт таблицы и сидит тарифные планы. Для этого пользователь PostgreSQL должен иметь права на создание базы данных или база `vocmind` должна быть создана заранее.

## Запуск через ngrok

Telegram Mini App и часть интеграций должны работать через публичный HTTPS URL. Для локальной разработки используется ngrok.

В отдельном терминале запусти:

```bash
ngrok http 8000
```

ngrok выдаст публичный адрес примерно такого вида:

```text
https://your-ngrok-domain.ngrok-free.app
```

Дальше этот URL используется как публичный адрес backend:

```text
BACKEND_PUBLIC_URL=https://your-ngrok-domain.ngrok-free.app
MINI_APP_URL=https://your-ngrok-domain.ngrok-free.app/lk
```

Важно: если используется бесплатный ngrok-домен, URL может меняться после перезапуска туннеля. После смены URL нужно обновить настройки бота, Mini App и расширения.

## Запуск Telegram Mini App

Mini App лежит в папке `vocmind-miniapp` и отдаётся backend-ом как static app по адресу:

```text
/lk
```

Локально:

```text
http://localhost:8000/lk
```

Через ngrok:

```text
https://your-ngrok-domain.ngrok-free.app/lk
```

Именно ngrok URL нужно указывать в Telegram/BotFather и в настройках бота как `MINI_APP_URL`.

Mini App рассчитан на запуск внутри Telegram WebApp. При открытии обычным браузером интерфейс может загрузиться, но авторизация через Telegram `initData` не пройдёт.

## Настройка Telegram-бота

Создай файл `vocmind-bot/.env`:

```env
BOT_TOKEN=your_telegram_bot_token
BACKEND_BASE_URL=https://your-ngrok-domain.ngrok-free.app
BOT_INTERNAL_KEY=change_me_internal_backend_bot_key
MINI_APP_URL=https://your-ngrok-domain.ngrok-free.app/lk
```

Важно:

* `BACKEND_BASE_URL` должен указывать на публичный ngrok URL, а не на `localhost`.
* `MINI_APP_URL` должен вести на `/lk` через ngrok.
* `BOT_INTERNAL_KEY` должен совпадать с backend-переменной `BOT_INTERNAL_KEY`.
* После смены ngrok URL нужно обновить `.env` бота и перезапустить бота.

Запуск бота:

```bash
cd vocmind-bot
python -m venv .venv
source .venv/bin/activate
pip install aiogram pydantic-settings httpx
python main.py
```

Бот запускается в polling-режиме.

## Настройка Chrome extension

Расширение находится в папке `vocmind-extension`.

Локальная установка:

1. Открой `chrome://extensions/`.
2. Включи Developer Mode.
3. Нажми Load unpacked.
4. Выбери папку `vocmind-extension`.
5. Открой popup расширения и подключи его кодом из Mini App.

Если расширение обращается к backend через ngrok, в `manifest.json` нужно добавить публичный ngrok URL в `host_permissions`:

```json
"host_permissions": [
  "http://127.0.0.1/*",
  "http://localhost/*",
  "https://your-ngrok-domain.ngrok-free.app/*"
]
```

Если адрес backend захардкожен в JS-файлах расширения, его также нужно заменить на ngrok URL:

```text
https://your-ngrok-domain.ngrok-free.app
```

После изменения `manifest.json` или JS-файлов расширение нужно перезагрузить на странице `chrome://extensions/`.

## Основные backend endpoints

### Health

```http
GET /health
```

### Streaming записи

```http
POST /stream/start
POST /stream/chunk
POST /stream/finish
```

### Авторизация

```http
POST /auth/telegram
GET /auth/me
GET /auth/me/plan
```

### Личный кабинет / Mini App

```http
POST /miniapp/auth
GET /miniapp/dashboard
POST /miniapp/activate-key
POST /miniapp/extension-code
```

### Расширение

```http
POST /extension/connect
```

### История и экспорт

```http
GET /miniapp/meetings
GET /miniapp/meetings/{meeting_id}/export/pdf
GET /miniapp/meetings/{meeting_id}/export/docx
```

Актуальную схему API удобно смотреть в Swagger UI:

```text
http://localhost:8000/docs
```

Или через ngrok:

```text
https://your-ngrok-domain.ngrok-free.app/docs
```

## Тарифы и ограничения

Backend сидит несколько тарифов:

* `base` — базовый тариф: транскрипция и AI-протокол.
* `personal` — больше минут, экспорт PDF/DOCX.
* `pro` — задачи, решения, разделение спикеров, поиск, live-подсказки.
* `extended` — расширенные возможности, аналитика и неограниченное хранение.
* `admin` — полный доступ без ограничений.

Функции включаются/выключаются через `plan_features`, а ограничения по минутам и хранению проверяются на backend.

## Экспорт

Проект поддерживает экспорт встречи в:

* PDF
* DOCX

Для работы экспорта должны быть установлены:

```bash
pip install python-docx reportlab
```

PDF-экспорт пытается найти системный Unicode-шрифт, чтобы корректно отображать русский текст.

## Тесты

В проекте есть тесты качества, протокола, дедупликации, устойчивости и e2e-сценариев.

Запуск:

```bash
pytest
```

## Частые проблемы

### Telegram Mini App не открывается

Проверь, что в BotFather и в `.env` бота указан HTTPS URL через ngrok:

```text
https://your-ngrok-domain.ngrok-free.app/lk
```

### Бот не видит backend

Проверь `BACKEND_BASE_URL` в `vocmind-bot/.env`. Для Telegram-сценария он должен быть публичным:

```env
BACKEND_BASE_URL=https://your-ngrok-domain.ngrok-free.app
```

### Расширение не подключается

Проверь три вещи:

1. backend запущен на `localhost:8000`;
2. ngrok туннель активен;
3. ngrok URL добавлен в `host_permissions` расширения.




## Roadmap

* Backend + PostgreSQL.
* Отдельный `requirements.txt` для backend и bot.
* Alembic migrations.
* Production CORS и security hardening.
* CI pipeline для тестов.
* Инструкция по деплою на VPS.
* Переход с временного ngrok URL на постоянный домен.

