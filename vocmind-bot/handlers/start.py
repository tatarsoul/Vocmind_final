from aiogram import Router, F
from aiogram.types import Message

from config import settings
from keyboards.inline import main_menu
from services.backend_api import backend_api

router = Router()


async def _ensure_auth(event) -> str:
    tg_user = {
        "id": event.from_user.id,
        "username": event.from_user.username,
        "first_name": event.from_user.first_name,
        "last_name": event.from_user.last_name,
    }
    auth = await backend_api.auth_by_telegram(tg_user)
    return auth["access_token"]


@router.message(F.text == "/start")
async def cmd_start(message: Message):
    token = await _ensure_auth(message)
    me = await backend_api.get_me(token)
    user = me["user"]
    name = user.get("first_name") or message.from_user.first_name or "друг"

    await message.answer(
        f"Привет, {name}!\n\n"
        "Это бот VocMind. Здесь можно открыть кабинет, посмотреть тариф, "
        "активировать ключ и получить код для подключения расширения.",
        reply_markup=main_menu(settings.mini_app_url),
    )