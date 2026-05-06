# Vocmind Mini App — Личный кабинет

Миниапп уже подключен к текущему backend проекта.

## Что сделано

- фронт переведен на реальные backend-роуты
- demo mode выключен
- добавлен backend endpoint `GET /miniapp/dashboard`
- миниапп можно открывать прямо с этого же сервера по адресу `/lk`

## Какие роуты использует mini app

- `POST /miniapp/auth`
- `GET /miniapp/dashboard`
- `POST /miniapp/activate-key`
- `POST /miniapp/extension-code`

## Где открывать

После запуска backend:

- веб-адрес миниаппа: `/lk`
- для BotFather и кнопки в боте указывай полный HTTPS URL вида:
  `https://твойдомен.ru/lk`

## Что поменять в боте

Если хочешь, чтобы кнопка в боте открывала встроенный миниапп с того же домена, обнови `vocmind-bot/.env` или `vocmind-bot/config.py`:

```env
MINI_APP_URL=https://твойдомен.ru/lk
```

## Важно

Миниапп открывается только внутри Telegram WebApp, потому что авторизация идет через `initData`.
Если открыть `/lk` просто в браузере, интерфейс загрузится, но вход без Telegram не пройдет.
