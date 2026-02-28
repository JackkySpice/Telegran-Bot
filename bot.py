"""Kimielbot - Telegram investment platform bot.

Runs the Telegram bot with scheduled daily earnings and an IPN webhook server
for CoinPayments payment confirmations.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import time, timezone

from telegram.ext import ApplicationBuilder, CommandHandler

import config
from complan import process_daily_earnings
from database import close_db
from handlers import register_all

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def _daily_earnings_job(context):
    """Scheduled job: credit daily profits to active investments."""
    count = await process_daily_earnings()
    logger.info("Daily earnings job: %d investments credited", count)

    for admin_id in config.ADMIN_USER_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"Daily earnings processed: {count} investments credited. ✅",
            )
        except Exception:
            pass


async def _expire_deposits_job(context):
    """Scheduled job: expire pending deposits older than DEPOSIT_TIMEOUT_HOURS."""
    from database import get_db

    db = await get_db()
    timeout_hours = config.DEPOSIT_TIMEOUT_HOURS
    result = await db.execute(
        f"""UPDATE deposits SET status = 'expired'
            WHERE status = 'pending'
            AND datetime(created_at, '+{timeout_hours} hours') < datetime('now')""",
    )
    await db.commit()
    if result.rowcount and result.rowcount > 0:
        logger.info("Expired %d stale deposits", result.rowcount)


def main():
    if not config.BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set. Check your .env file.")
        return

    app = ApplicationBuilder().token(config.BOT_TOKEN).build()
    register_all(app)

    async def shutdown(update, context):
        if update.effective_user.id not in config.ADMIN_USER_IDS:
            return
        await update.message.reply_text("Shutting down...")
        await close_db()
        asyncio.get_event_loop().stop()

    app.add_handler(CommandHandler("shutdown", shutdown))

    job_queue = app.job_queue
    if job_queue:
        job_queue.run_daily(
            _daily_earnings_job,
            time=time(hour=0, minute=0, tzinfo=timezone.utc),
            name="daily_earnings",
        )
        job_queue.run_repeating(
            _expire_deposits_job,
            interval=3600,
            first=60,
            name="expire_deposits",
        )
        logger.info("Scheduled jobs: daily_earnings (00:00 UTC), expire_deposits (hourly)")

    if config.CP_PUBLIC_KEY and config.IPN_URL:
        logger.info("CoinPayments configured. IPN server on port %d", config.WEBHOOK_PORT)
        _start_ipn_server(app)
    else:
        logger.info("CoinPayments not configured. Running in offline/manual mode.")

    logger.info("Kimielbot starting...")
    app.run_polling(drop_pending_updates=True)


def _start_ipn_server(bot_app):
    """Start the IPN webhook server in a background thread."""
    import threading
    from aiohttp import web
    from ipn_server import create_ipn_app, set_bot_app

    set_bot_app(bot_app)
    ipn_app = create_ipn_app()

    def run_server():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        web.run_app(ipn_app, host="0.0.0.0", port=config.WEBHOOK_PORT, print=None)

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()


if __name__ == "__main__":
    main()
