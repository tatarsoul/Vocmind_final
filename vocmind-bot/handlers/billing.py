from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from states import ActivateKeyState
from services.backend_api import backend_api
from services.auth import ensure_auth

router = Router()


@router.message(F.text == "/activate")
async def cmd_activate(message: Message, state: FSMContext):
    await state.set_state(ActivateKeyState.waiting_for_key)
    await message.answer("Отправь секретный ключ для активации тарифа.")


@router.callback_query(F.data == "menu:activate_key")
async def cb_activate(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ActivateKeyState.waiting_for_key)
    await callback.message.answer("Отправь секретный ключ для активации тарифа.")
    await callback.answer()


@router.message(ActivateKeyState.waiting_for_key)
async def process_key(message: Message, state: FSMContext):
    key = (message.text or "").strip()
    token = await ensure_auth(message)

    try:
        res = await backend_api.activate_key(token, key)
    except RuntimeError as e:
        msg = str(e)

        if "Activation key not found" in msg:
            await message.answer("Ключ не найден.")
            return
        if "Activation key inactive" in msg:
            await message.answer("Этот ключ неактивен.")
            return
        if "Activation key expired" in msg:
            await message.answer("Срок действия ключа истёк.")
            return
        if "Activation key limit reached" in msg:
            await message.answer("Лимит активаций этого ключа исчерпан.")
            return

        await message.answer(f"Ошибка активации: {msg}")
        return

    plan = res["plan"]

    await message.answer(
        "✅ Тариф активирован\n\n"
        f"Тариф: {plan['title']} ({plan['code']})\n"
        f"Старт: {res['starts_at']}\n"
        f"До: {res.get('ends_at') or 'без срока'}"
    )
    await state.clear()


@router.message(F.text == "/extension")
async def cmd_extension(message: Message):
    token = await ensure_auth(message)

    try:
        data = await backend_api.generate_extension_code(token)
    except RuntimeError as e:
        await message.answer(f"Не удалось получить код подключения: {e}")
        return

    await message.answer(
        "🔗 Код для подключения расширения\n\n"
        f"Код: `{data['code']}`\n"
        f"Действует до: {data['expires_at']}",
        parse_mode="Markdown",
    )


@router.callback_query(F.data == "menu:extension_code")
async def cb_extension(callback: CallbackQuery):
    token = await ensure_auth(callback)

    try:
        data = await backend_api.generate_extension_code(token)
    except RuntimeError as e:
        await callback.message.answer(f"Не удалось получить код подключения: {e}")
        await callback.answer()
        return

    await callback.message.answer(
        "🔗 Код для подключения расширения\n\n"
        f"Код: `{data['code']}`\n"
        f"Действует до: {data['expires_at']}",
        parse_mode="Markdown",
    )
    await callback.answer()