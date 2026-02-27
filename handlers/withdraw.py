"""Withdrawal handler."""

from __future__ import annotations

from datetime import datetime

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

import config
from database import get_db


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db = await get_db()
    row = await db.execute_fetchall(
        "SELECT balance_trx, balance_usdt FROM users WHERE user_id = ?", (user_id,)
    )
    if not row:
        await update.message.reply_text("Register ka muna gamit /start.")
        return

    trx, usdt = row[0]
    text = (
        f"Balance mo:\n\n"
        f"TRX:  {trx:.4f}\n"
        f"USDT: {usdt:.4f}\n\n"
        f"Minimum withdrawal: {config.MIN_WITHDRAWAL} TRX\n"
        "Para mag-withdraw: /withdraw <amount> [TRX/USDT]"
    )
    await update.message.reply_text(text)


async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db = await get_db()

    if not context.args:
        await update.message.reply_text(
            "Usage: /withdraw <amount> [TRX/USDT]\n"
            "Halimbawa: /withdraw 50 TRX"
        )
        return

    try:
        amount = float(context.args[0])
    except ValueError:
        await update.message.reply_text("Amount dapat number.")
        return

    currency = "TRX"
    if len(context.args) >= 2:
        currency = context.args[1].upper()
        if currency not in config.SUPPORTED_CURRENCIES:
            await update.message.reply_text("Supported currencies: TRX, USDT")
            return

    if amount < config.MIN_WITHDRAWAL:
        await update.message.reply_text(
            f"Minimum withdrawal ay {config.MIN_WITHDRAWAL} {currency}."
        )
        return

    active_inv = await db.execute_fetchall(
        """SELECT id, unlocks_at FROM investments
           WHERE user_id = ? AND status = 'active'
           ORDER BY unlocks_at ASC""",
        (user_id,),
    )
    now = datetime.utcnow()
    all_locked = True
    for inv in active_inv:
        unlock_str = inv[1]
        if unlock_str and datetime.fromisoformat(unlock_str) <= now:
            all_locked = False
            break

    if active_inv and all_locked:
        nearest = min(
            datetime.fromisoformat(inv[1]) for inv in active_inv if inv[1]
        )
        days_left = (nearest - now).days
        await update.message.reply_text(
            f"Lock period pa ang investments mo. "
            f"Maa-unlock in {days_left} day(s). Balik ka ulit!"
        )
        return

    balance_col = "balance_trx" if currency == "TRX" else "balance_usdt"
    row = await db.execute_fetchall(
        f"SELECT {balance_col} FROM users WHERE user_id = ?", (user_id,)
    )
    if not row:
        await update.message.reply_text("Register ka muna gamit /start.")
        return

    current_balance = row[0][0]
    if amount > current_balance:
        await update.message.reply_text(
            f"Hindi enough ang balance mo. Meron ka lang {current_balance:.4f} {currency}."
        )
        return

    await db.execute(
        f"UPDATE users SET {balance_col} = {balance_col} - ? WHERE user_id = ?",
        (amount, user_id),
    )
    await db.execute(
        """INSERT INTO withdrawals (user_id, amount, currency, status)
           VALUES (?, ?, ?, 'pending')""",
        (user_id, amount, currency),
    )
    await db.commit()

    await update.message.reply_text(
        f"Withdrawal request submitted! 🎉\n\n"
        f"Amount: {amount} {currency}\n"
        "Status: Pending\n\n"
        "I-process namin to as soon as possible. Salamat!"
    )


def register(app):
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("withdraw", withdraw))
