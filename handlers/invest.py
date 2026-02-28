"""Investment handler with CoinPayments deposit flow."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

import config
from coinpayments import CoinPaymentsError, create_transaction
from complan import can_user_invest, validate_amount
from database import get_db

logger = logging.getLogger(__name__)


async def _ensure_registered(update: Update) -> bool:
    db = await get_db()
    row = await db.execute_fetchall(
        "SELECT user_id FROM users WHERE user_id = ?",
        (update.effective_user.id,),
    )
    if not row:
        await update.message.reply_text("Register ka muna: /start")
        return False
    return True


async def plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["Investment Plans:\n"]
    for pid, p in config.PLANS.items():
        lines.append(
            f"Plan {pid}: {p['profit_pct']}% in {p['duration_days']} days\n"
            f"  {p['min_amount']}-{p['max_amount']} TRX/USDT | unlock {p['lock_days']} days"
        )
    lines.append(
        f"\nWithdrawal: Every {config.PAYOUT_DAY}, {config.WITHDRAWAL_FEE_PCT}% fee, "
        f"min {config.MIN_WITHDRAWAL}\n"
        "1 active per plan, max 3 sabay.\n\n"
        "/invest <plan> <amount> [TRX/USDT]"
    )
    await update.message.reply_text("\n".join(lines))


async def invest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _ensure_registered(update):
        return

    user_id = update.effective_user.id

    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "/invest <plan> <amount> [TRX/USDT]\n"
            "Example: /invest 1 100 TRX"
        )
        return

    try:
        plan_id = int(context.args[0])
        amount = float(context.args[1])
    except ValueError:
        await update.message.reply_text("Plan at amount dapat numbers.")
        return

    if amount <= 0:
        await update.message.reply_text("Amount dapat positive number.")
        return

    currency = "TRX"
    if len(context.args) >= 3:
        currency = context.args[2].upper()
        if currency not in config.SUPPORTED_CURRENCIES:
            await update.message.reply_text("Supported: TRX, USDT")
            return

    if plan_id not in config.PLANS:
        await update.message.reply_text("Plan 1, 2, or 3 lang.")
        return

    err = validate_amount(plan_id, amount)
    if err:
        await update.message.reply_text(err)
        return

    allowed, reason = await can_user_invest(user_id, plan_id)
    if not allowed:
        await update.message.reply_text(reason)
        return

    db = await get_db()
    pending = await db.execute_fetchall(
        "SELECT id FROM deposits WHERE user_id = ? AND plan_id = ? AND status = 'pending'",
        (user_id, plan_id),
    )
    if pending:
        await update.message.reply_text(
            "May pending deposit ka pa for this plan.\n"
            f"Cancel: /canceldeposit {pending[0][0]}\n"
            "Or hintayin mag-expire.\n\n"
            "/deposits para makita status."
        )
        return

    custom_data = f"{user_id}|{plan_id}"

    if not config.CP_PUBLIC_KEY:
        deposit_id = await _create_offline_deposit(user_id, plan_id, amount, currency)
        await update.message.reply_text(
            f"Deposit #{deposit_id} created (offline mode)\n\n"
            f"Plan {plan_id} | {amount} {currency}\n"
            "Admin will confirm manually.\n\n"
            "/deposits para makita status."
        )
        return

    try:
        tx = await create_transaction(
            amount=amount,
            currency=currency,
            ipn_url=config.IPN_URL,
            custom=custom_data,
        )
    except CoinPaymentsError as e:
        logger.error("CoinPayments error: %s", e)
        await update.message.reply_text(
            "Payment system error. Try again later or contact admin."
        )
        return

    await db.execute(
        """INSERT INTO deposits
           (user_id, plan_id, amount, currency, cp_txn_id, deposit_address, status)
           VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
        (user_id, plan_id, amount, currency, tx["txn_id"], tx["address"]),
    )
    await db.commit()

    plan = config.PLANS[plan_id]
    timeout_hrs = config.DEPOSIT_TIMEOUT_HOURS

    await update.message.reply_text(
        f"Send {amount} {currency} to this address:\n\n"
        f"`{tx['address']}`\n\n"
        f"Plan: {plan['name']} ({plan['profit_pct']}% in {plan['duration_days']} days)\n"
        f"TXN: {tx['txn_id']}\n"
        f"Expires in {timeout_hrs} hours.\n\n"
        "Investment starts once payment is confirmed.\n"
        "/deposits para makita status.",
        parse_mode="Markdown",
    )


async def _create_offline_deposit(user_id: int, plan_id: int, amount: float, currency: str) -> int:
    db = await get_db()
    await db.execute(
        """INSERT INTO deposits
           (user_id, plan_id, amount, currency, cp_txn_id, deposit_address, status)
           VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
        (user_id, plan_id, amount, currency, None, "manual", "pending"),
    )
    await db.commit()
    row = await db.execute_fetchall("SELECT last_insert_rowid()")
    return row[0][0]


async def deposits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user's pending and recent deposits."""
    user_id = update.effective_user.id
    db = await get_db()

    rows = await db.execute_fetchall(
        """SELECT id, plan_id, amount, currency, status, deposit_address, cp_txn_id, created_at
           FROM deposits WHERE user_id = ?
           ORDER BY created_at DESC LIMIT 10""",
        (user_id,),
    )

    if not rows:
        await update.message.reply_text("No deposits yet. /invest para mag-start.")
        return

    lines = ["Your Deposits:\n"]
    for r in rows:
        dep_id, plan_id, amount, currency, status, addr, txn_id, created = r
        emoji = {
            "pending": "⏳", "confirmed": "✅", "expired": "❌",
            "cancelled": "❌", "underpaid": "⚠️",
        }.get(status, "?")
        lines.append(
            f"{emoji} #{dep_id} | Plan {plan_id} | {amount} {currency} | {status}\n"
            f"  {created[:16]}"
        )

    await update.message.reply_text("\n".join(lines))


async def canceldeposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel a pending deposit: /canceldeposit <deposit_id>"""
    user_id = update.effective_user.id

    if not context.args:
        await update.message.reply_text("Usage: /canceldeposit <deposit_id>")
        return

    try:
        dep_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID dapat number.")
        return

    db = await get_db()
    row = await db.execute_fetchall(
        "SELECT id, user_id, status FROM deposits WHERE id = ?",
        (dep_id,),
    )

    if not row:
        await update.message.reply_text("Deposit not found.")
        return

    if row[0][1] != user_id:
        await update.message.reply_text("Hindi sayo yang deposit.")
        return

    if row[0][2] != "pending":
        await update.message.reply_text(f"Deposit status: {row[0][2]}. Hindi na pwede i-cancel.")
        return

    await db.execute(
        "UPDATE deposits SET status = 'cancelled' WHERE id = ?",
        (dep_id,),
    )
    await db.commit()

    await update.message.reply_text(f"Deposit #{dep_id} cancelled.")


def register(app):
    app.add_handler(CommandHandler("plans", plans))
    app.add_handler(CommandHandler("invest", invest))
    app.add_handler(CommandHandler("deposits", deposits))
    app.add_handler(CommandHandler("canceldeposit", canceldeposit))
