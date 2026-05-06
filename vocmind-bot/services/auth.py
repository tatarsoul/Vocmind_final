from aiogram.types import Message, CallbackQuery

from services.backend_api import backend_api


async def ensure_auth(event: Message | CallbackQuery) -> str:
    tg = event.from_user

    tg_user = {
        "id": tg.id,
        "username": tg.username,
        "first_name": tg.first_name,
        "last_name": tg.last_name,
    }

    auth = await backend_api.auth_by_telegram(tg_user)
    return auth["access_token"]