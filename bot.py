"""Kimielbot - Telegram investment platform bot."""

from __future__ import annotations

import asyncio
import logging

from telegram.ext import ApplicationBuilder

import config
from database import close_db
from handlers import register_all

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main():
    if not config.BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set. Check your .env file.")
        return

    app = ApplicationBuilder().token(config.BOT_TOKEN).build()
    register_all(app)

    app.add_handler(
        _shutdown_handler(app),
    )

    logger.info("Kimielbot starting...")
    app.run_polling(drop_pending_updates=True)


def _shutdown_handler(app):
    from telegram.ext import CommandHandler

    async def shutdown(update, context):
        if update.effective_user.id not in config.ADMIN_USER_IDS:
            return
        await update.message.reply_text("Shutting down...")
        await close_db()
        asyncio.get_event_loop().stop()

    return CommandHandler("shutdown", shutdown)


if __name__ == "__main__":
    main()
