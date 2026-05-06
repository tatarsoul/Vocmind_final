from aiogram import Router, F
from aiogram.types import Message, CallbackQuery

from services.backend_api import backend_api
from services.auth import ensure_auth

router = Router()


def _format_me(me: dict) -> str:
    user = me["user"]
    return (
        "👤 Профиль\n\n"
        f"ID: {user['id']}\n"
        f"Telegram ID: {user.get('telegram_id')}\n"
        f"Username: @{user.get('username') or '-'}\n"
        f"Имя: {user.get('first_name') or '-'} {user.get('last_name') or ''}\n"
        f"Роль: {user.get('role')}\n"
        f"Активен: {'да' if user.get('is_active') else 'нет'}"
    )


FEATURE_TITLES = {
    'transcription': 'Базовая транскрибация',
    'ai_protocol': 'AI-протокол встречи',
    'export_pdf': 'Экспорт в PDF',
    'export_docx': 'Экспорт в DOCX',
    'tasks_and_decisions': 'Задачи и решения',
    'speaker_diarization': 'Разделение спикеров',
    'meeting_search': 'Поиск по встречам',
    'live_hints': 'Live-подсказки',
    'unlimited_storage': 'Неограниченное хранение',
}


def _format_plan(data: dict) -> str:
    features = data.get("features", {})
    enabled = [FEATURE_TITLES.get(k, k) for k, v in features.items() if v.get("is_enabled")]
    return (
        "💼 Тариф\n\n"
        f"Код: {data.get('code')}\n"
        f"Название: {data.get('title')}\n"
        f"Минут в месяц: {data.get('monthly_minutes')}\n"
        f"Хранение встреч: {data.get('meeting_storage_limit') if data.get('meeting_storage_limit') is not None else '∞'}\n\n"
        "Доступные функции:\n- " + ("\n- ".join(enabled) if enabled else "нет")
    )


@router.message(F.text == "/profile")
async def cmd_profile(message: Message):
    token = await ensure_auth(message)
    me = await backend_api.get_me(token)
    await message.answer(_format_me(me))


@router.callback_query(F.data == "menu:profile")
async def cb_profile(callback: CallbackQuery):
    token = await ensure_auth(callback)
    me = await backend_api.get_me(token)
    await callback.message.answer(_format_me(me))
    await callback.answer()


@router.message(F.text == "/plan")
async def cmd_plan(message: Message):
    token = await ensure_auth(message)

    try:
        plan = await backend_api.get_plan(token)
    except RuntimeError as e:
        msg = str(e)
        if "Active subscription not found" in msg:
            await message.answer(
                "У вас пока нет активного тарифа.\n\nАктивируйте ключ в личном кабинете."
            )
            return
        raise

    await message.answer(_format_plan(plan))


@router.callback_query(F.data == "menu:plan")
async def cb_plan(callback: CallbackQuery):
    token = await ensure_auth(callback)

    try:
        plan = await backend_api.get_plan(token)
    except RuntimeError as e:
        msg = str(e)
        if "Active subscription not found" in msg:
            await callback.message.answer(
                "У вас пока нет активного тарифа.\n\nАктивируйте ключ в личном кабинете."
            )
            await callback.answer()
            return
        raise

    await callback.message.answer(_format_plan(plan))
    await callback.answer()
