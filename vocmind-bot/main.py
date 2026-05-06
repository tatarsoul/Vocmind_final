import asyncio
import logging

from bot import bot, dp
from handlers.start import router as start_router
from handlers.profile import router as profile_router
from handlers.billing import router as billing_router


async def main():
    logging.basicConfig(level=logging.INFO)

    print("VocMind TG bot starting...")

    # На всякий случай убираем webhook, чтобы polling точно работал
    await bot.delete_webhook(drop_pending_updates=True)

    dp.include_router(start_router)
    dp.include_router(profile_router)
    dp.include_router(billing_router)

    me = await bot.get_me()
    print(f"Bot started: @{me.username}")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())