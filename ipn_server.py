"""IPN webhook server for CoinPayments payment confirmations.

Supports both v1 (legacy HMAC header) and v2 (X-CoinPayments-Signature) webhooks.
When a payment is confirmed, activates the corresponding investment.
"""

from __future__ import annotations

import json
import logging

from aiohttp import web

import config
from coinpayments import (
    CP_NETWORK_FEE_PCT,
    is_payment_complete,
    is_payment_failed,
    verify_ipn_v1,
    verify_webhook_v2,
)
from complan import create_investment
from database import get_db

logger = logging.getLogger(__name__)

_bot_app = None

UNDERPAY_TOLERANCE = 0.03


def set_bot_app(app):
    """Store reference to telegram bot app for sending notifications."""
    global _bot_app
    _bot_app = app


async def handle_ipn(request: web.Request) -> web.Response:
    """Handle both v1 and v2 CoinPayments webhooks."""
    body = await request.read()

    is_v2 = "X-CoinPayments-Signature" in request.headers

    if is_v2:
        return await _handle_v2_webhook(request, body)
    return await _handle_v1_ipn(request, body)


async def _handle_v1_ipn(request: web.Request, body: bytes) -> web.Response:
    """Process v1 legacy IPN callback (form-encoded POST, HMAC header)."""
    hmac_header = request.headers.get("HMAC", "")
    if not hmac_header:
        hmac_header = (await request.post()).get("hmac", "")

    if config.CP_IPN_SECRET and not verify_ipn_v1(hmac_header, body):
        logger.warning("v1 IPN signature verification failed")
        return web.Response(text="HMAC verification failed", status=400)

    data = await request.post()

    merchant = data.get("merchant", "")
    if config.CP_MERCHANT_ID and merchant != config.CP_MERCHANT_ID:
        logger.warning("Merchant ID mismatch: %s", merchant)
        return web.Response(text="Merchant mismatch", status=400)

    txn_id = data.get("txn_id", "")
    status = int(data.get("status", "0"))
    status_text = data.get("status_text", "")
    custom = data.get("custom", "")

    # receivedf = actual crypto received by CoinPayments (after network fees)
    # amount1 = original requested amount in currency1
    received_amount = float(data.get("receivedf", data.get("amount1", "0")))
    net_amount = float(data.get("net", "0"))
    fee = float(data.get("fee", "0"))
    currency = data.get("currency1", data.get("currency2", ""))

    logger.info(
        "v1 IPN: txn=%s status=%s (%s) received=%s net=%s fee=%s %s",
        txn_id, status, status_text, received_amount, net_amount, fee, currency,
    )

    return await _process_payment_update(
        txn_id=txn_id,
        status=status,
        received_amount=received_amount,
        net_amount=net_amount,
        fee=fee,
        custom=custom,
    )


async def _handle_v2_webhook(request: web.Request, body: bytes) -> web.Response:
    """Process v2 webhook (JSON POST, X-CoinPayments-Signature header)."""
    signature = request.headers.get("X-CoinPayments-Signature", "")
    client_id = request.headers.get("X-CoinPayments-Client", "")
    timestamp = request.headers.get("X-CoinPayments-Timestamp", "")
    url = str(request.url)

    if config.CP_PRIVATE_KEY and not verify_webhook_v2(
        signature, client_id, timestamp, body, url,
    ):
        logger.warning("v2 webhook signature verification failed")
        return web.Response(text="Signature verification failed", status=400)

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return web.Response(text="Invalid JSON", status=400)

    from coinpayments import _map_v2_status

    txn_id = data.get("id", data.get("invoiceId", ""))
    status_str = data.get("status", "")
    status = _map_v2_status(status_str)
    custom = data.get("customData", "")

    paid = data.get("paidAmount", {})
    received_amount = float(paid.get("value", 0)) if paid else 0
    net_amount = received_amount
    fee = 0

    logger.info(
        "v2 webhook: id=%s status=%s (%s) received=%s",
        txn_id, status, status_str, received_amount,
    )

    return await _process_payment_update(
        txn_id=txn_id,
        status=status,
        received_amount=received_amount,
        net_amount=net_amount,
        fee=fee,
        custom=custom,
    )


async def _process_payment_update(
    txn_id: str,
    status: int,
    received_amount: float,
    net_amount: float,
    fee: float,
    custom: str,
) -> web.Response:
    """Shared logic for processing a payment status update from v1 or v2."""
    db = await get_db()

    deposit = await db.execute_fetchall(
        "SELECT id, user_id, plan_id, amount, currency, status FROM deposits WHERE cp_txn_id = ?",
        (txn_id,),
    )

    if not deposit and custom:
        parts = custom.split("|")
        if len(parts) == 2:
            try:
                user_id, plan_id = int(parts[0]), int(parts[1])
                deposit = await db.execute_fetchall(
                    """SELECT id, user_id, plan_id, amount, currency, status FROM deposits
                       WHERE user_id = ? AND plan_id = ? AND status = 'pending'
                       ORDER BY created_at DESC LIMIT 1""",
                    (user_id, plan_id),
                )
            except ValueError:
                pass

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

    if is_payment_complete(status):
        # CoinPayments takes a ~0.5% network fee. The actual received amount
        # (receivedf / net) may be slightly less than what the user sent.
        # We compare received against expected minus the CP fee tolerance.
        min_acceptable = dep_amount * (1 - (CP_NETWORK_FEE_PCT / 100) - UNDERPAY_TOLERANCE)

        if received_amount > 0 and received_amount < min_acceptable:
            logger.warning(
                "Underpayment for deposit %s: expected %s, received %s (min acceptable %s)",
                dep_id, dep_amount, received_amount, min_acceptable,
            )
            await db.execute(
                "UPDATE deposits SET status = 'underpaid' WHERE id = ?",
                (dep_id,),
            )
            await db.commit()
            await _notify_user(
                user_id, plan_id, dep_amount, dep_currency, "underpaid",
                received=received_amount,
            )
            return web.Response(text="IPN OK", status=200)

        await _activate_deposit(dep_id, user_id, plan_id, dep_amount, dep_currency)
        await _notify_user(user_id, plan_id, dep_amount, dep_currency, "confirmed")

    elif is_payment_failed(status):
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


async def _notify_user(
    user_id: int,
    plan_id: int,
    amount: float,
    currency: str,
    status: str,
    received: float = 0,
):
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
        elif status == "underpaid":
            text = (
                f"Your payment was short.\n"
                f"Expected: {amount} {currency}\n"
                f"Received: {received} {currency}\n\n"
                "Contact admin to resolve."
            )
        else:
            text = (
                f"Deposit cancelled/expired.\n"
                f"Plan {plan_id} | {amount} {currency}\n"
                "Try /invest again."
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
