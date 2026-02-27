"""IPN webhook server for CoinPayments payment confirmations.

Runs as a lightweight aiohttp server alongside the Telegram bot.
When a payment is confirmed, activates the corresponding investment.
"""

from __future__ import annotations

import logging

from aiohttp import web

import config
from coinpayments import (
    IPN_STATUS_CANCELLED,
    IPN_STATUS_COMPLETE,
    IPN_STATUS_CONFIRMED,
    verify_ipn,
)
from complan import create_investment
from database import get_db

logger = logging.getLogger(__name__)

_bot_app = None


def set_bot_app(app):
    """Store reference to telegram bot app for sending notifications."""
    global _bot_app
    _bot_app = app


async def handle_ipn(request: web.Request) -> web.Response:
    body = await request.read()

    hmac_header = request.headers.get("HMAC", "")
    if not hmac_header:
        hmac_header = (await request.post()).get("hmac", "")

    if config.CP_IPN_SECRET and not verify_ipn(hmac_header, body):
        logger.warning("IPN signature verification failed")
        return web.Response(text="HMAC verification failed", status=400)

    data = await request.post()

    ipn_mode = data.get("ipn_mode", "")
    if ipn_mode != "hmac":
        logger.warning("Unexpected IPN mode: %s", ipn_mode)

    merchant = data.get("merchant", "")
    if config.CP_MERCHANT_ID and merchant != config.CP_MERCHANT_ID:
        logger.warning("Merchant ID mismatch: %s", merchant)
        return web.Response(text="Merchant mismatch", status=400)

    txn_id = data.get("txn_id", "")
    status = int(data.get("status", "0"))
    status_text = data.get("status_text", "")
    amount = float(data.get("amount1", "0"))
    currency = data.get("currency1", "")
    custom = data.get("custom", "")

    logger.info(
        "IPN: txn=%s status=%s (%s) amount=%s %s custom=%s",
        txn_id, status, status_text, amount, currency, custom,
    )

    db = await get_db()

    deposit = await db.execute_fetchall(
        "SELECT id, user_id, plan_id, amount, currency, status FROM deposits WHERE cp_txn_id = ?",
        (txn_id,),
    )

    if not deposit:
        if custom:
            parts = custom.split("|")
            if len(parts) == 2:
                user_id, plan_id = int(parts[0]), int(parts[1])
                deposit = await db.execute_fetchall(
                    """SELECT id, user_id, plan_id, amount, currency, status FROM deposits
                       WHERE user_id = ? AND plan_id = ? AND status = 'pending'
                       ORDER BY created_at DESC LIMIT 1""",
                    (user_id, plan_id),
                )

    if not deposit:
        logger.warning("No matching deposit for txn %s", txn_id)
        return web.Response(text="IPN OK", status=200)

    dep_id, user_id, plan_id, dep_amount, dep_currency, dep_status = deposit[0]

    if dep_status != "pending":
        logger.info("Deposit %s already %s, skipping", dep_id, dep_status)
        return web.Response(text="IPN OK", status=200)

    await db.execute(
        "UPDATE deposits SET cp_status = ?, cp_txn_id = COALESCE(cp_txn_id, ?) WHERE id = ?",
        (status, txn_id, dep_id),
    )
    await db.commit()

    if status >= IPN_STATUS_COMPLETE or status == IPN_STATUS_CONFIRMED:
        await _activate_deposit(dep_id, user_id, plan_id, dep_amount, dep_currency)
        await _notify_user(user_id, plan_id, dep_amount, dep_currency, "confirmed")

    elif status == IPN_STATUS_CANCELLED or status < 0:
        await db.execute(
            "UPDATE deposits SET status = 'cancelled' WHERE id = ?",
            (dep_id,),
        )
        await db.commit()
        await _notify_user(user_id, plan_id, dep_amount, dep_currency, "cancelled")

    return web.Response(text="IPN OK", status=200)


async def _activate_deposit(dep_id: int, user_id: int, plan_id: int, amount: float, currency: str):
    """Mark deposit confirmed and create the investment."""
    db = await get_db()

    await db.execute(
        "UPDATE deposits SET status = 'confirmed', confirmed_at = datetime('now') WHERE id = ?",
        (dep_id,),
    )
    await db.commit()

    result = await create_investment(user_id, plan_id, amount, currency)

    await db.execute(
        "UPDATE investments SET deposit_id = ? WHERE id = ?",
        (dep_id, result["investment_id"]),
    )
    await db.commit()

    logger.info("Deposit %s confirmed, investment %s created", dep_id, result["investment_id"])


async def _notify_user(user_id: int, plan_id: int, amount: float, currency: str, status: str):
    """Send telegram notification about deposit status."""
    if not _bot_app:
        return

    try:
        if status == "confirmed":
            plan = config.PLANS[plan_id]
            text = (
                f"Payment confirmed! 🎉\n\n"
                f"{plan['name']} | {amount} {currency}\n"
                f"Profit: {plan['profit_pct']}% in {plan['duration_days']} days\n"
                "Your investment is now active. /portfolio"
            )
        else:
            text = (
                f"Deposit cancelled/expired.\n"
                f"Plan {plan_id} | {amount} {currency}\n"
                "Try /invest again if you want to continue."
            )

        await _bot_app.bot.send_message(chat_id=user_id, text=text)
    except Exception as e:
        logger.error("Failed to notify user %s: %s", user_id, e)


def create_ipn_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/ipn", handle_ipn)
    app.router.add_get("/health", _health)
    return app


async def _health(request: web.Request) -> web.Response:
    return web.Response(text="OK")
