# VocMind

VocMind — это AI-сервис для записи, транскрибации и анализа встреч. Проект объединяет backend на FastAPI, расширение для браузера, Telegram Mini App и Telegram-бота. Пользователь может подключить расширение, записать встречу, получить транскрипт, AI-протокол, историю встреч и экспорт результатов.

## Возможности

* Запись аудио из микрофона и/или вкладки браузера через Chrome extension.
* Streaming-обработка аудио чанками через backend.
* Распознавание речи через `faster-whisper`.
* Очистка транскрипта от дублей, ASR-галлюцинаций и служебного шума.
* AI-протокол встречи через Groq LLM.
* Опциональная LLM-полировка транскрипта.
* Live-подсказки и live-протокол для тарифов, где функция включена.
* Telegram Mini App как личный кабинет пользователя.
* Активационные ключи и тарифные ограничения.
* История встреч, поиск, удаление и экспорт в PDF/DOCX.
* Telegram-бот для входа, профиля и работы с тарифами.

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

## Основной пользовательский сценарий

1. Пользователь открывает Telegram Mini App.
2. Авторизуется через Telegram `initData`.
3. Активирует тарифный ключ или использует текущую подписку.
4. Генерирует код подключения расширения.
5. Устанавливает Chrome extension и вводит код подключения.
6. Запускает запись встречи.
7. Расширение отправляет аудио чанками в backend.
8. Backend транскрибирует аудио, собирает итоговый текст и генерирует протокол.
9. Пользователь видит встречу в истории Mini App и может скачать экспорт.

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

### Frontend

* Vanilla JavaScript
* HTML/CSS
* Telegram WebApp API
* Chrome Extension Manifest V3

## Требования

* Python 3.11+
* PostgreSQL
* FFmpeg
* Groq API key
* Telegram bot token
* Локальная или скачанная модель Whisper, совместимая с `faster-whisper`
* Chromium-based browser для расширения
* HTTPS-домен для production-запуска Telegram Mini App

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

> Для production обязательно замени `AUTH_SECRET` и `BOT_INTERNAL_KEY` на собственные секретные значения. Не коммить `.env` в репозиторий.

## Установка backend

```bash
git clone https://github.com/tatarsoul/Vocmind_final.git
cd Vocmind_final
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
```

Если в проекте ещё нет `requirements.txt`, можно установить зависимости по импортам проекта:

```bash
pip install fastapi "uvicorn[standard]" python-multipart \
  sqlalchemy "psycopg[binary]" pydantic-settings httpx \
  faster-whisper ctranslate2 numpy webrtcvad \
  python-docx reportlab pytest
```

## Запуск backend

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

После запуска проверь healthcheck:

```bash
curl http://localhost:8000/health
```

Ожидаемый ответ:

```json
{"ok": true}
```

При старте backend создаёт таблицы и сидит тарифные планы. Для этого пользователь PostgreSQL должен иметь права на создание базы данных или база `vocmind` должна быть создана заранее.

## Запуск Telegram Mini App

Mini App лежит в папке `vocmind-miniapp` и подключается backend-ом как static app по адресу:

```text
/lk
```

Локально:

```text
http://localhost:8000/lk
```

Для BotFather и кнопки в Telegram нужно указывать HTTPS URL:

```text
https://your-domain.com/lk
```

Mini App рассчитан на запуск внутри Telegram WebApp. При открытии обычным браузером интерфейс может загрузиться, но авторизация через Telegram `initData` не пройдёт.

## Настройка Telegram-бота

Создай файл `vocmind-bot/.env`:

```env
BOT_TOKEN=your_telegram_bot_token
BACKEND_BASE_URL=http://localhost:8000
BOT_INTERNAL_KEY=change_me_internal_backend_bot_key
MINI_APP_URL=https://your-domain.com/lk
```

Важно: `BOT_INTERNAL_KEY` должен совпадать с backend-переменной `BOT_INTERNAL_KEY`.

Запуск бота:

```bash
cd vocmind-bot
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
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

По умолчанию в `manifest.json` указаны host permissions для локального backend:

```json
"host_permissions": [
  "http://127.0.0.1/*",
  "http://localhost/*"
]
```

Для production добавь домен backend, например:

```json
"host_permissions": [
  "https://your-domain.com/*"
]
```

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

Названия отдельных routes могут меняться при доработке проекта, поэтому перед интеграцией удобно проверить актуальный OpenAPI:

```text
http://localhost:8000/docs
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

## Рекомендации для production

* Запускать backend через `gunicorn`/`uvicorn` под process manager или systemd.
* Использовать HTTPS-домен для Mini App и API.
* Хранить `.env` вне репозитория.
* Заменить все dev-секреты.
* Ограничить CORS вместо `allow_origins=["*"]`.
* Настроить отдельного PostgreSQL-пользователя с минимальными правами.
* Добавить `requirements.txt` или `pyproject.toml` для воспроизводимой установки.
* Добавить миграции Alembic, если схема будет активно меняться.
* Проверить rate limits Groq и при необходимости отключить `ENABLE_TRANSCRIPT_POLISH` или `ENABLE_LIVE_PROTOCOL`.

## Roadmap

* Docker Compose для backend + PostgreSQL.
* Отдельный `requirements.txt` для backend и bot.
* Alembic migrations.
* Production CORS и security hardening.
* CI pipeline для тестов.
* Инструкция по деплою на VPS.

## Лицензия

Лицензия в репозитории пока не указана. Добавь `LICENSE`, если проект планируется публиковать или передавать другим разработчикам.
